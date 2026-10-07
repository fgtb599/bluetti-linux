#!/usr/bin/env python3
"""Bluetti EB3A tray monitor with an Android-app-style dashboard."""

import argparse
import asyncio
import logging
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")
from gi.repository import AyatanaAppIndicator3 as AppIndicator, Gdk, Gio, GLib, Gtk  # noqa: E402

from bluetti import __version__  # noqa: E402
from bluetti.ble import Poller  # noqa: E402
from bluetti.config import Config  # noqa: E402
from bluetti.dashboard import CSS, PALETTES, Dashboard, flow_text  # noqa: E402
from bluetti.devices import DevicesDialog  # noqa: E402
from bluetti.tray_icon import DIR as ICON_DIR, arrow_icon, icon_name  # noqa: E402

THEMES = [("system", "System"), ("light", "Light"), ("dark", "Dark")]
TRAY_VIEWS = [("battery", "Battery"), ("full", "Battery + in/out")]


class TrayApp:
    def __init__(self, config, address, interval):
        self.config = config
        self.status = None
        self.device = None  # (name, address) of the connected unit
        self.theme_items = []
        self.view_items = []
        self.info_menus = []  # status lines of each tray item's menu
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

        self.dashboard = Dashboard(on_output=self.poller.set_output, menu=self._build_menu(tray=False))

        # Separate tray items so the input/output arrows can be coloured icons next to their watts.
        # The panel puts each new item to the left of earlier ones, so create them right-to-left
        # to read: battery → input → output.
        self.indicators = {}
        self.indicators["out"] = self._make_indicator(
            "bluetti-eb3a-out", "Bluetti EB3A output", arrow_icon("out", False)
        )
        self.indicators["in"] = self._make_indicator("bluetti-eb3a-in", "Bluetti EB3A input", arrow_icon("in", False))
        self.indicators["battery"] = self._make_indicator("bluetti-eb3a", "Bluetti EB3A battery", icon_name(None))
        self._update_tray()

        self.apply_theme()
        self.dashboard.show_all()
        threading.Thread(target=lambda: asyncio.run(self.poller.run()), daemon=True).start()

    def _make_indicator(self, indicator_id, title, icon):
        indicator = AppIndicator.Indicator.new_with_path(
            indicator_id, icon, AppIndicator.IndicatorCategory.HARDWARE, str(ICON_DIR)
        )
        indicator.set_title(title)
        indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        menu, open_item = self._build_menu(tray=True)
        indicator.set_menu(menu)
        # Middle-click on the icon opens the dashboard directly.
        indicator.set_secondary_activate_target(open_item)
        return indicator

    # Menus: every tray item's menu and the dashboard's ☰ menu share Theme / Tray view / Devices / About.

    def _build_menu(self, tray):
        menu = Gtk.Menu()
        if tray:
            info_items = [Gtk.MenuItem(label="Searching…", sensitive=False) for _ in range(4)]
            for item in info_items:
                menu.append(item)
            self.info_menus.append(info_items)
            menu.append(Gtk.SeparatorMenuItem())

        menu.append(self._radio_menu("Theme", THEMES, self.config.theme, self.select_theme, self.theme_items))
        menu.append(
            self._radio_menu("Tray view", TRAY_VIEWS, self.config.tray_view, self.select_tray_view, self.view_items)
        )
        devices_item = Gtk.MenuItem(label="Devices…")
        devices_item.connect("activate", lambda _i: self.show_devices())
        menu.append(devices_item)
        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", lambda _i: self.show_about())
        menu.append(about_item)

        if not tray:
            menu.show_all()
            return menu
        menu.append(Gtk.SeparatorMenuItem())
        open_item = Gtk.MenuItem(label="Open dashboard")
        open_item.connect("activate", lambda _i: self.dashboard.present())
        menu.append(open_item)
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _i: Gtk.main_quit())
        menu.append(quit_item)
        menu.show_all()
        return menu, open_item

    @staticmethod
    def _radio_menu(title, options, current, on_select, items):
        """Submenu of radio items; `items` collects (key, item) so all menus can be kept in sync."""
        submenu = Gtk.Menu()
        group = None
        for key, name in options:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, name)
            group = item
            item.set_active(key == current)
            item.connect("toggled", lambda i, k: i.get_active() and on_select(k), key)
            submenu.append(item)
            items.append((key, item))
        menu_item = Gtk.MenuItem(label=title)
        menu_item.set_submenu(submenu)
        return menu_item

    @staticmethod
    def _sync_radio(items, current):
        for key, item in items:
            if item.get_active() != (key == current):
                item.set_active(key == current)

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
        battery = self.indicators["battery"]
        if s is None:
            battery.set_icon_full(icon_name(None), "Not connected")
            battery.set_label("", "")
        else:
            battery.set_icon_full(icon_name(s), f"{s.battery_pct}%")
            battery.set_label(f"{s.battery_pct}%", "100%")

        show_flow = s is not None and self.config.tray_view == "full"
        for key, watts in (("in", s.input_w if s else 0), ("out", s.output_w if s else 0)):
            indicator = self.indicators[key]
            if not show_flow:
                indicator.set_status(AppIndicator.IndicatorStatus.PASSIVE)
                continue
            indicator.set_icon_full(arrow_icon(key, watts > 0), f"{key} {watts} W")
            indicator.set_label(f"{watts} W", "8888 W")
            indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)

    def _set_info(self, lines):
        for items in self.info_menus:
            for item, text in zip(items, lines):
                item.set_label(text)

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

    config = Config()
    app = TrayApp(config, args.address or config.active, args.interval)
    if args.hidden:
        app.dashboard.hide()
    Gtk.main()


if __name__ == "__main__":
    main()
