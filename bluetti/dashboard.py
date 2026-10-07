"""Dashboard window: battery ring, input/output cards and AC/DC switches."""

import math
from string import Template

from gi.repository import GLib, Gtk

CSS = Template("""
.dashboard { background: $bg; color: $text; }
.card { background: $card; border-radius: 16px; padding: 14px; }
.card-title { color: $muted; font-size: 11pt; }
.watts { color: $text; font-size: 20pt; font-weight: bold; }
.row-label { color: $row; }
.model { color: $text; font-size: 16pt; font-weight: bold; }
.muted { color: $muted; }
""")

PALETTES = {
    "dark": {
        "bg": "#000000", "card": "#1c1c1e", "text": "#f9fafb", "row": "#d1d5db", "muted": "#9ca3af",
        "track": (0.23, 0.23, 0.24), "ring_text": (0.98, 0.98, 0.98), "ring_sub": (0.61, 0.64, 0.69),
    },
    "light": {
        "bg": "#f2f4f7", "card": "#ffffff", "text": "#111827", "row": "#374151", "muted": "#6b7280",
        "track": (0.86, 0.88, 0.91), "ring_text": (0.07, 0.09, 0.15), "ring_sub": (0.42, 0.45, 0.5),
    },
}


def fmt_hours(hours):
    if hours is None:
        return "—"
    h, m = divmod(round(hours * 60), 60)
    return f"{h} h {m:02d} min"


def flow_text(status):
    if status.input_w == status.output_w:
        return "Pass-through"
    net = abs(status.input_w - status.output_w)
    return f"{'Charging' if status.charging else 'Discharging'} · {net} W"


def label(text="", css=None, xalign=0.0):
    widget = Gtk.Label(label=text, xalign=xalign)
    if css:
        widget.get_style_context().add_class(css)
    return widget


def set_switch(switch, on):
    """Show the device's state without firing the toggle handler."""
    switch.handler_block(switch.handler_id)
    switch.set_active(on)
    switch.set_state(on)
    switch.handler_unblock(switch.handler_id)


class BatteryRing(Gtk.DrawingArea):
    def __init__(self):
        super().__init__()
        self.set_size_request(220, 220)
        self.status = None
        self.palette = PALETTES["dark"]
        self.connect("draw", self._draw)

    def update(self, status):
        self.status = status
        self.queue_draw()

    def _draw(self, _widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cx, cy, r = w / 2, h / 2, min(w, h) / 2 - 14
        pct = self.status.battery_pct if self.status else 0

        cr.set_line_width(14)
        cr.set_source_rgb(*self.palette["track"])
        cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()

        if pct > 20:
            cr.set_source_rgb(0.09, 0.64, 0.29)
        else:
            cr.set_source_rgb(0.86, 0.15, 0.15)
        cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * pct / 100)
        cr.stroke()

        cr.set_source_rgb(*self.palette["ring_text"])
        cr.select_font_face("Sans", 0, 1)
        cr.set_font_size(46)
        text = f"{pct}%" if self.status else "--"
        ext = cr.text_extents(text)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy + ext.height / 2 - 10)
        cr.show_text(text)

        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(13)
        cr.set_source_rgb(*self.palette["ring_sub"])
        sub = flow_text(self.status) if self.status else ""
        ext = cr.text_extents(sub)
        cr.move_to(cx - ext.width / 2 - ext.x_bearing, cy + 34)
        cr.show_text(sub)


class PowerCard(Gtk.Box):
    """Card with a total wattage and per-port rows, like the Android app's input/output tiles."""

    def __init__(self, title, rows, on_toggle=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.get_style_context().add_class("card")
        self.add(label(title, "card-title"))
        self.total = label("— W", "watts")
        self.add(self.total)
        self.rows = {}
        for key, name in rows:
            row = Gtk.Box(spacing=8)
            row.pack_start(label(name, "row-label"), True, True, 0)
            value = label("—", xalign=1.0)
            row.pack_start(value, False, False, 0)
            switch = None
            if on_toggle:
                switch = Gtk.Switch(valign=Gtk.Align.CENTER, sensitive=False)
                switch.handler_id = switch.connect("state-set", on_toggle, key)
                row.pack_start(switch, False, False, 0)
            self.rows[key] = (value, switch)
            self.add(row)

    def update(self, total, values, states=None):
        self.total.set_text(f"{total} W")
        for key, (value, switch) in self.rows.items():
            value.set_text(f"{values[key]} W")
            if switch:
                set_switch(switch, states[key])
                switch.set_sensitive(True)

    def disable_switches(self):
        for _value, switch in self.rows.values():
            if switch:
                switch.set_sensitive(False)


class Dashboard(Gtk.Window):
    def __init__(self, on_output, menu):
        super().__init__(title="Bluetti EB3A")
        self.on_output = on_output
        self.set_default_size(380, -1)  # height follows the content
        self.get_style_context().add_class("dashboard")
        self.connect("delete-event", lambda w, _e: w.hide_on_delete())

        header = Gtk.HeaderBar(title="Bluetti EB3A", show_close_button=True)
        menu_button = Gtk.MenuButton(popup=menu)
        if menu_button.get_child():
            menu_button.remove(menu_button.get_child())
        menu_button.add(Gtk.Image.new_from_icon_name("open-menu-symbolic", Gtk.IconSize.BUTTON))
        header.pack_end(menu_button)
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin=16)
        self.add(box)

        self.model = label("EB3A", "model", 0.5)
        self.state = label("Searching…", "muted", 0.5)
        box.add(self.model)
        box.add(self.state)

        self.ring = BatteryRing()
        box.add(self.ring)
        self.remaining = label("", "muted", 0.5)
        box.add(self.remaining)

        cards = Gtk.Box(spacing=12, homogeneous=True)
        self.input = PowerCard("Input", [("ac", "AC (wall)"), ("dc", "DC / Solar")])
        self.output = PowerCard("Output", [("ac", "AC"), ("dc", "DC")], on_toggle=self._toggle)
        cards.add(self.input)
        cards.add(self.output)
        box.add(cards)

        self.footer = label("", "muted", 0.5)
        box.add(self.footer)

    def set_palette(self, palette):
        self.ring.palette = palette
        self.ring.queue_draw()

    def set_state(self, text):
        self.state.set_text(text)
        if text != "Connected":
            self.output.disable_switches()

    def _toggle(self, switch, on, key):
        if key == "ac" and not on and not self._confirm_ac_off():
            GLib.idle_add(set_switch, switch, True)
            return True
        self.on_output(key, on)
        # Let the switch flip now; the next poll corrects it if the write failed.
        return False

    def _confirm_ac_off(self):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Turn off AC output?",
        )
        dialog.format_secondary_text(
            "Everything plugged into the EB3A's AC sockets loses power — including this PC if it runs from it."
        )
        confirmed = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return confirmed

    def update(self, s):
        self.model.set_text(s.model or "EB3A")
        self.ring.update(s)
        what = "Time to full" if s.charging else "Remaining"
        self.remaining.set_text(f"{what}: {fmt_hours(s.hours_remaining())}")
        self.input.update(s.input_w, {"ac": s.ac_input_w, "dc": s.dc_input_w})
        self.output.update(
            s.output_w,
            {"ac": s.ac_output_w, "dc": s.dc_output_w},
            {"ac": s.ac_on, "dc": s.dc_on},
        )
        self.footer.set_text(f"SN {s.serial}")
