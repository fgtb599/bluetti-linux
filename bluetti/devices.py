"""Devices window: saved units, which one is active, and scanning for new ones."""

from gi.repository import Gtk

from .dashboard import label


class DevicesDialog(Gtk.Dialog):
    def __init__(self, parent, config, on_use, scan):
        super().__init__(title="Devices", transient_for=parent)
        self.config = config
        self.on_use = on_use
        self.scan = scan
        self.found = []
        self.scanned = False
        self.closed = False
        self.set_default_size(440, 380)
        self.add_button("Close", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda d, _r: d.destroy())
        self.connect("destroy", lambda _d: setattr(self, "closed", True))

        box = self.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)

        box.add(label("Saved devices", "card-title"))
        self.saved = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add(self.saved)

        scan_row = Gtk.Box(spacing=8)
        self.scan_button = Gtk.Button(label="Scan for devices")
        self.scan_button.connect("clicked", self._start_scan)
        self.spinner = Gtk.Spinner()
        scan_row.pack_start(self.scan_button, False, False, 0)
        scan_row.pack_start(self.spinner, False, False, 0)
        box.add(scan_row)

        box.add(label("Nearby", "card-title"))
        self.nearby = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        box.add(self.nearby)

        hint = label(
            "Only the EB3A is supported. Close the phone app first: "
            "the unit accepts one Bluetooth connection at a time.",
            "muted",
        )
        hint.set_line_wrap(True)
        box.add(hint)

        self.refresh()

    def refresh(self):
        if self.closed:
            return
        for listbox in (self.saved, self.nearby):
            for child in listbox.get_children():
                listbox.remove(child)

        if not self.config.devices:
            self.saved.add(label("No devices yet — scan to add one.", "muted"))
        for device in self.config.devices:
            address = device["address"]
            active = address == self.config.active
            buttons = [] if active else [self._button("Use", self._use, address)]
            buttons.append(self._button("Remove", self._remove, address))
            self.saved.add(self._row(device["name"], address, buttons, "Active" if active else None))

        saved = {d["address"] for d in self.config.devices}
        new = [(name, address) for name, address in self.found if address not in saved]
        if not new:
            hint = "Nothing new found." if self.scanned else "Press Scan to look for devices."
            self.nearby.add(label(hint, "muted"))
        for name, address in new:
            self.nearby.add(self._row(name, address, [self._button("Add", self._add, (name, address))]))
        self.show_all()

    @staticmethod
    def _row(name, address, buttons, badge=None):
        row = Gtk.Box(spacing=8, margin=6)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        text.add(label(name, "row-label"))
        text.add(label(address, "muted"))
        row.pack_start(text, True, True, 0)
        if badge:
            row.pack_start(label(badge, "muted"), False, False, 0)
        for button in buttons:
            row.pack_start(button, False, False, 0)
        return row

    @staticmethod
    def _button(text, handler, arg):
        button = Gtk.Button(label=text, valign=Gtk.Align.CENTER)
        button.connect("clicked", lambda _b: handler(arg))
        return button

    def _use(self, address):
        self.on_use(address)
        self.refresh()

    def _remove(self, address):
        was_active = address == self.config.active
        self.config.remove_device(address)
        if was_active:
            self.on_use(self.config.active)
        self.refresh()

    def _add(self, device):
        name, address = device
        self.config.add_device(name, address)
        if self.config.active is None:
            self.on_use(address)
        self.refresh()

    def _start_scan(self, _button):
        self.scan_button.set_sensitive(False)
        self.spinner.start()
        self.scan(self._on_scan)

    def _on_scan(self, found):
        if self.closed:
            return False
        self.found = found
        self.scanned = True
        self.spinner.stop()
        self.scan_button.set_sensitive(True)
        self.refresh()
        return False
