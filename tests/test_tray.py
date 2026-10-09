import unittest

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from bluetti.tray import DBusMenu, MenuItem, gtk_menu  # noqa: E402


class FakeConnection:
    """Stands in for the session bus: records exported objects and emitted signals."""

    def __init__(self):
        self.signals = []

    def register_object_with_closures2(self, *_args):
        return 1

    def emit_signal(self, _dest, _path, _iface, name, params):
        self.signals.append((name, params.unpack()))


def unpacked(props):
    return {k: v.unpack() for k, v in props.items()}


def radio_menu():
    selected = {"key": "a"}
    items = {}

    def select(key):
        selected["key"] = key
        for k, item in items.items():
            item.update(checked=k == key)

    for key in ("a", "b"):
        items[key] = MenuItem(key.upper(), lambda k=key: select(k), radio=True, checked=key == "a")
    return selected, items


class DBusMenuTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConnection()
        self.status = MenuItem("Searching…", enabled=False)
        self.selected, self.radios = radio_menu()
        self.menu = DBusMenu(
            self.conn,
            "/test/menu",
            [self.status, MenuItem.separator_item(), MenuItem("Theme", children=list(self.radios.values()))],
        )

    def test_layout_ids_follow_tree_order(self):
        _id, props, children = self.menu._layout(self.menu.root, -1, ["type", "children-display"])
        self.assertEqual(unpacked(props), {"children-display": "submenu"})
        ids = [c.unpack()[0] for c in children]
        self.assertEqual(ids, [1, 2, 3])
        self.assertEqual([c[0] for c in children[2].unpack()[2]], [4, 5])

    def test_layout_depth_zero_has_no_children(self):
        self.assertEqual(self.menu._layout(self.menu.root, 0, [])[2], [])

    def test_item_properties(self):
        self.assertEqual(unpacked(self.menu._props(self.status)), {"label": "Searching…", "enabled": False})
        self.assertEqual(unpacked(self.menu._props(self.menu.items[2])), {"type": "separator"})
        self.assertEqual(
            unpacked(self.menu._props(self.radios["a"])),
            {"label": "A", "enabled": True, "toggle-type": "radio", "toggle-state": 1},
        )

    def test_update_emits_one_signal_per_change(self):
        self.status.update(label="Battery 80%")
        self.status.update(label="Battery 80%")  # unchanged: no signal
        self.assertEqual(len(self.conn.signals), 1)
        name, (updated, removed) = self.conn.signals[0]
        self.assertEqual(name, "ItemsPropertiesUpdated")
        self.assertEqual(updated, [(1, {"label": "Battery 80%", "enabled": False})])
        self.assertEqual(removed, [])

    def test_click_selects_radio(self):
        self.menu._activate(self.radios["b"])
        self.assertEqual(self.selected["key"], "b")
        states = {i: props["toggle-state"] for _name, (updated, _) in self.conn.signals for i, props in updated}
        self.assertEqual(states, {4: 0, 5: 1})


@unittest.skipUnless(Gtk.init_check()[0], "needs a display")
class GtkMenuTest(unittest.TestCase):
    def test_radio_click_runs_once_and_follows_model(self):
        selected, radios = radio_menu()
        calls = []
        for key, item in radios.items():
            on_activate = item.on_activate
            item.on_activate = lambda f=on_activate, k=key: (calls.append(k), f())
        menu = gtk_menu(list(radios.values()))  # keep it: a dropped Gtk.Menu destroys its items
        a_widget, b_widget = menu.get_children()

        b_widget.activate()

        # Unchecking A in response must not re-run A's selection (GTK 3's set_active emits "activate").
        self.assertEqual(calls, ["b"])
        self.assertEqual(selected["key"], "b")
        self.assertFalse(a_widget.get_active())
        self.assertTrue(b_widget.get_active())

    def test_clicking_selected_radio_keeps_it_checked(self):
        _selected, radios = radio_menu()
        menu = gtk_menu(list(radios.values()))
        a_widget, _b = menu.get_children()
        a_widget.activate()
        self.assertTrue(a_widget.get_active())


if __name__ == "__main__":
    unittest.main()
