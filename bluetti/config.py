"""Persistent settings in ~/.config/bluetti-linux/config.json."""

import json
from pathlib import Path

from gi.repository import GLib

PATH = Path(GLib.get_user_config_dir()) / "bluetti-linux" / "config.json"


class Config:
    def __init__(self):
        try:
            data = json.loads(PATH.read_text())
        except (OSError, ValueError):
            data = {}
        self.theme = data.get("theme", "system")
        # Older versions had "icon" and "output" views; map them onto the two that remain.
        view = data.get("tray_view", "full")
        self.tray_view = {"icon": "battery", "output": "full"}.get(view, view)
        self.devices = data.get("devices", [])
        self.active = data.get("active")

    def save(self):
        PATH.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "theme": self.theme,
            "tray_view": self.tray_view,
            "devices": self.devices,
            "active": self.active,
        }
        PATH.write_text(json.dumps(data, indent=2))

    def set_theme(self, theme):
        self.theme = theme
        self.save()

    def set_tray_view(self, view):
        self.tray_view = view
        self.save()

    def set_active(self, address):
        self.active = address
        self.save()

    def add_device(self, name, address):
        if any(d["address"] == address for d in self.devices):
            return
        self.devices.append({"name": name, "address": address})
        self.save()

    def remove_device(self, address):
        self.devices = [d for d in self.devices if d["address"] != address]
        if self.active == address:
            self.active = self.devices[0]["address"] if self.devices else None
        self.save()
