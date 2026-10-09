#!/usr/bin/env python3
"""Bluetti EB3A tray monitor with an Android-app-style dashboard."""

import argparse
import asyncio
import logging
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

from bluetti import __version__  # noqa: E402
from bluetti.ble import Poller  # noqa: E402
from bluetti.config import Config  # noqa: E402
from bluetti.dashboard import CSS, PALETTES, Dashboard, flow_text  # noqa: E402
from bluetti.devices import DevicesDialog  # noqa: E402
from bluetti.tray import WATCHER, MenuItem, TrayIcon, gtk_menu  # noqa: E402
from bluetti.tray_icon import DIR as ICON_DIR, arrow_icon, icon_name  # noqa: E402

APP_ID = "io.github.fgtb599.BluettiLinux"  # also the launcher's file name, so GNOME matches the window to it
THEMES = [("system", "System"), ("light", "Light"), ("dark", "Dark")]
TRAY_VIEWS = [("battery", "Battery"), ("full", "Battery + in/out")]

log = logging.getLogger(__name__)


def tray_host_available():
    """Whether something on the session bus shows StatusNotifier icons right now.

    The tray icons register once a host appears, but until then nothing shows in the top bar.
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION)
        reply = bus.call_sync(
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
            "NameHasOwner",
            GLib.Variant("(s)", (WATCHER,)),
            GLib.VariantType("(b)"),
            Gio.DBusCallFlags.NONE,
            1000,
        )
    except GLib.Error as e:
        log.debug("Could not check for a tray host: %s", e.message)
        return True
    return reply.unpack()[0]


class TrayApp:
    def __init__(self, app, config, address, interval):
        self.app = app
        self.config = config
        self.status = None
        self.device = None  # (name, address) of the connected unit
        self.devices_dialog = None

        self.css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), self.css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        # Light/dark variants of the desktop's GTK theme, e.g. Yaru-olive / Yaru-olive-dark.
        gtk_settings = Gtk.Settings.get_default()
        self.base_gtk_theme = gtk_settings.get_property("gtk-theme-name").removesuffix("-dark")
        self.desktop = Gio.Settings.new("org.gnome.desktop.interface")
        self.desktop.connect("changed::color-scheme", lambda *_: self.apply_theme())

        self.poller = Poller(
            on_status=lambda s: GLib.idle_add(self._on_status, s),
            on_state=lambda t: GLib.idle_add(self._on_state, t),
            on_device=lambda n, a: GLib.idle_add(self._on_device, n, a),
            address=address,
            interval=interval,
        )

        shared_menu = self._build_menu()
        self.dashboard = Dashboard(on_output=self.poller.set_output, menu=gtk_menu(shared_menu))

        # Every tray item's menu: four status lines, the shared items, then Open dashboard / Quit.
        self.info_items = [MenuItem("Searching…", enabled=False) for _ in range(4)]
        tray_menu = [
            *self.info_items,
            MenuItem.separator_item(),
            *shared_menu,
            MenuItem.separator_item(),
            MenuItem("Open dashboard", self.dashboard.present),
            MenuItem("Quit", self.app.quit),
        ]

        # Separate tray items so the input/output arrows can be coloured icons next to their watts.
        # The panel puts each new item to the left of earlier ones, so create them right-to-left
        # to read: battery → input → output.
        self.icons = {}
        self.icons["out"] = self._make_icon(
            "bluetti-eb3a-out", "Bluetti EB3A output", arrow_icon("out", False), tray_menu
        )
        self.icons["in"] = self._make_icon("bluetti-eb3a-in", "Bluetti EB3A input", arrow_icon("in", False), tray_menu)
        self.icons["battery"] = self._make_icon("bluetti-eb3a", "Bluetti EB3A battery", icon_name(None), tray_menu)
        self._update_tray()

        self.apply_theme()
        self.dashboard.set_application(app)
        self.dashboard.show_all()
        threading.Thread(target=lambda: asyncio.run(self.poller.run()), daemon=True).start()

    def _make_icon(self, item_id, title, icon, menu):
        # Middle-click on the icon opens the dashboard directly.
        return TrayIcon(item_id, title, icon, ICON_DIR, menu, on_secondary_activate=self.dashboard.present)

    # Menus: the tray items and the dashboard's ☰ menu share the same Theme / Tray view / Devices / About
    # items, so a radio change shows up everywhere at once.

    def _build_menu(self):
        self.theme_items = self._radio_items(THEMES, self.config.theme, self.select_theme)
        self.view_items = self._radio_items(TRAY_VIEWS, self.config.tray_view, self.select_tray_view)
        return [
            MenuItem("Theme", children=[item for _key, item in self.theme_items]),
            MenuItem("Tray view", children=[item for _key, item in self.view_items]),
            MenuItem("Devices…", self.show_devices),
            MenuItem("About", self.show_about),
        ]

    @staticmethod
    def _radio_items(options, current, on_select):
        """(key, item) pairs of radio items; selecting one calls on_select(key)."""
        return [
            (key, MenuItem(name, lambda k=key: on_select(k), radio=True, checked=key == current))
            for key, name in options
        ]

    @staticmethod
    def _sync_radio(items, current):
        for key, item in items:
            item.update(checked=key == current)

    def select_theme(self, key):
        if key != self.config.theme:
            self.config.set_theme(key)
            self.apply_theme()

    def select_tray_view(self, key):
        if key != self.config.tray_view:
            self.config.set_tray_view(key)
            self._sync_radio(self.view_items, key)
            self._update_tray()

    def apply_theme(self):
        theme = self.config.theme
        if theme == "system":
            dark = self.desktop.get_string("color-scheme") == "prefer-dark"
        else:
            dark = theme == "dark"
        palette = PALETTES["dark" if dark else "light"]
        self.css.load_from_data(CSS.substitute(palette).encode())
        gtk_settings = Gtk.Settings.get_default()
        gtk_settings.set_property("gtk-theme-name", self.base_gtk_theme + ("-dark" if dark else ""))
        gtk_settings.set_property("gtk-application-prefer-dark-theme", dark)
        self.dashboard.set_palette(palette)
        self._sync_radio(self.theme_items, theme)

    # Tray items.

    def _update_tray(self):
        s = self.status
        battery = self.icons["battery"]
        if s is None:
            battery.set_icon(icon_name(None), "Not connected")
            battery.set_label("", "")
        else:
            battery.set_icon(icon_name(s), f"{s.battery_pct}%")
            battery.set_label(f"{s.battery_pct}%", "100%")

        show_flow = s is not None and self.config.tray_view == "full"
        for key, watts in (("in", s.input_w if s else 0), ("out", s.output_w if s else 0)):
            icon = self.icons[key]
            if not show_flow:
                icon.set_visible(False)
                continue
            icon.set_icon(arrow_icon(key, watts > 0), f"{key} {watts} W")
            icon.set_label(f"{watts} W", "8888 W")
            icon.set_visible(True)

    def _set_info(self, lines):
        for item, text in zip(self.info_items, lines):
            item.update(label=text)

    # Devices and About windows.

    def show_devices(self):
        if self.devices_dialog:
            self.devices_dialog.present()
            return
        self.devices_dialog = DevicesDialog(
            parent=self.dashboard,
            config=self.config,
            on_use=self.use_device,
            scan=lambda done: self.poller.scan(lambda found: GLib.idle_add(done, found)),
        )
        self.devices_dialog.connect("destroy", lambda _d: setattr(self, "devices_dialog", None))
        self.devices_dialog.present()

    def use_device(self, address):
        self.config.set_active(address)
        self.status = None
        self.device = None
        self.poller.set_address(address)

    def show_about(self):
        about = Gtk.AboutDialog(
            transient_for=self.dashboard if self.dashboard.get_visible() else None,
            program_name="Bluetti Linux",
            version=__version__,
            comments="\n".join(self._about_lines()),
            license_type=Gtk.License.MIT_X11,
            authors=["Oleksii Chistyakov"],
            copyright="© 2026 Oleksii Chistyakov",
            logo_icon_name="battery-full-symbolic",
            website="https://github.com/fgtb599/bluetti-linux",
            website_label="GitHub",
        )
        about.add_credit_section("Protocol research", ["bluetti_mqtt by warhammerkid"])
        about.connect("response", lambda d, _r: d.destroy())
        about.present()

    def _about_lines(self):
        lines = ["Tray monitor and dashboard for the Bluetti EB3A over Bluetooth LE.", ""]
        if not (self.status and self.device):
            return lines + ["No device connected."]
        s = self.status
        return lines + [
            f"Connected: {s.model} · SN {s.serial}",
            f"Address: {self.device[1]}",
            f"Firmware: ARM {s.arm_version} · DSP {s.dsp_version}",
        ]

    # Callbacks from the BLE thread (delivered via GLib.idle_add).

    def _on_device(self, name, address):
        self.device = (name, address)
        self.config.add_device(name, address)
        if self.config.active is None:
            self.config.set_active(address)
        if self.devices_dialog:
            self.devices_dialog.refresh()
        return False

    def _on_state(self, text):
        self.dashboard.set_state(text)
        if text != "Connected":
            self.status = None
            self._update_tray()
            self._set_info([text, "", "", ""])
        return False

    def _on_status(self, s):
        self.status = s
        self.dashboard.update(s)
        self._update_tray()
        self._set_info([
            f"Battery {s.battery_pct}% ({flow_text(s).lower()})",
            f"Input {s.input_w} W  (AC {s.ac_input_w} / DC {s.dc_input_w})",
            f"Output {s.output_w} W  (AC {s.ac_output_w} / DC {s.dc_output_w})",
            f"AC {'on' if s.ac_on else 'off'}  ·  DC {'on' if s.dc_on else 'off'}",
        ])
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--address",
        help="connect to this EB3A for this run only (default: the active device from the Devices window)",
    )
    parser.add_argument("--interval", type=float, default=5.0, help="poll interval in seconds")
    parser.add_argument("--hidden", action="store_true", help="start with the dashboard hidden")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    # One instance per session: launching again (app grid, dock, a second autostart) only opens
    # the dashboard of the running one. Our own options were parsed above, so GApplication gets none.
    GLib.set_prgname(APP_ID)  # window class on X11, so the dock shows the launcher's icon
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
    tray = None

    def on_startup(app):
        nonlocal tray
        if not tray_host_available():
            log.warning(
                "No tray host on the session bus, so the top-bar icons will not show. On GNOME, enable "
                "the AppIndicator extension: gnome-extensions enable ubuntu-appindicators@ubuntu.com"
            )
        app.hold()  # keep running in the tray while the dashboard is hidden
        config = Config()
        tray = TrayApp(app, config, args.address or config.active, args.interval)
        if args.hidden:
            tray.dashboard.hide()

    start_hidden = args.hidden

    def on_activate(_app):
        # Every launch activates, this one included; only this one may start hidden (--hidden).
        nonlocal start_hidden
        if start_hidden:
            start_hidden = False
            return
        tray.dashboard.present()

    app.connect("startup", on_startup)
    app.connect("activate", on_activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()
