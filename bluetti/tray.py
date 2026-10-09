"""Tray icons spoken straight over D-Bus: org.kde.StatusNotifierItem plus com.canonical.dbusmenu.

This replaces libayatana-appindicator, which is deprecated, and whose replacement
(libayatana-appindicator-glib) exports menus as org.gtk.Menus — a format the GNOME AppIndicator
extension can't show, since it only reads com.canonical.dbusmenu.

Menus are described once as `MenuItem` trees: each tray icon exports them over D-Bus, and
`gtk_menu()` turns the same items into a Gtk.Menu for the dashboard, so labels and radio
states stay in sync everywhere.
"""

import logging

from gi.repository import Gio, GLib, Gtk

log = logging.getLogger(__name__)

WATCHER = "org.kde.StatusNotifierWatcher"

SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconAccessibleDesc" type="s" access="read"/>
    <property name="IconThemePath" type="s" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="XAyatanaLabel" type="s" access="read"/>
    <property name="XAyatanaLabelGuide" type="s" access="read"/>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="XAyatanaSecondaryActivate">
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewTitle"/>
    <signal name="NewIcon"/>
    <signal name="NewStatus"><arg name="status" type="s"/></signal>
    <signal name="NewIconThemePath"><arg name="icon_theme_path" type="s"/></signal>
    <signal name="XAyatanaNewLabel">
      <arg name="label" type="s"/>
      <arg name="guide" type="s"/>
    </signal>
  </interface>
</node>
"""

MENU_XML = """
<node>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg type="i" name="parentId" direction="in"/>
      <arg type="i" name="recursionDepth" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="u" name="revision" direction="out"/>
      <arg type="(ia{sv}av)" name="layout" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="as" name="propertyNames" direction="in"/>
      <arg type="a(ia{sv})" name="properties" direction="out"/>
    </method>
    <method name="GetProperty">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="name" direction="in"/>
      <arg type="v" name="value" direction="out"/>
    </method>
    <method name="Event">
      <arg type="i" name="id" direction="in"/>
      <arg type="s" name="eventId" direction="in"/>
      <arg type="v" name="data" direction="in"/>
      <arg type="u" name="timestamp" direction="in"/>
    </method>
    <method name="EventGroup">
      <arg type="a(isvu)" name="events" direction="in"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <method name="AboutToShow">
      <arg type="i" name="id" direction="in"/>
      <arg type="b" name="needUpdate" direction="out"/>
    </method>
    <method name="AboutToShowGroup">
      <arg type="ai" name="ids" direction="in"/>
      <arg type="ai" name="updatesNeeded" direction="out"/>
      <arg type="ai" name="idErrors" direction="out"/>
    </method>
    <signal name="ItemsPropertiesUpdated">
      <arg type="a(ia{sv})" name="updatedProps"/>
      <arg type="a(ias)" name="removedProps"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg type="u" name="revision"/>
      <arg type="i" name="parent"/>
    </signal>
  </interface>
</node>
"""

SNI_INFO = Gio.DBusNodeInfo.new_for_xml(SNI_XML).interfaces[0]
MENU_INFO = Gio.DBusNodeInfo.new_for_xml(MENU_XML).interfaces[0]


class MenuItem:
    """One menu entry; `radio` items show a radio mark when `checked`. Use update() to change it."""

    def __init__(self, label="", on_activate=None, enabled=True, radio=False, checked=False, children=()):
        self.label = label
        self.on_activate = on_activate
        self.enabled = enabled
        self.radio = radio
        self.checked = checked
        self.children = list(children)
        self.separator = False
        self._listeners = []

    @classmethod
    def separator_item(cls):
        item = cls()
        item.separator = True
        return item

    def update(self, **props):
        """Change label / enabled / checked and tell every menu showing this item."""
        changed = {k: v for k, v in props.items() if getattr(self, k) != v}
        for key, value in changed.items():
            setattr(self, key, value)
        if changed:
            for listener in self._listeners:
                listener(self)

    def activate(self):
        if self.on_activate:
            self.on_activate()


def gtk_menu(items):
    """Gtk.Menu showing `items`, kept up to date as they change."""
    menu = Gtk.Menu()
    for item in items:
        menu.append(_gtk_item(item))
    menu.show_all()
    return menu


def _gtk_item(item):
    if item.separator:
        return Gtk.SeparatorMenuItem()
    if item.radio:
        # A check item drawn as a radio: the app decides what is selected, so after a click the
        # widget is reset to the model instead of GTK toggling it on its own.
        widget = Gtk.CheckMenuItem(label=item.label, draw_as_radio=True, active=item.checked)

        def on_activate(_w):
            item.activate()
            set_checked()

        handler = widget.connect("activate", on_activate)

        def set_checked():
            # GTK 3's set_active() emits "activate" again, which would re-run the selection.
            with widget.handler_block(handler):
                widget.set_active(item.checked)
    else:
        widget = Gtk.MenuItem(label=item.label)
        if item.children:
            widget.set_submenu(gtk_menu(item.children))
        else:
            widget.connect("activate", lambda _w: item.activate())
    widget.set_sensitive(item.enabled)

    def sync(_item):
        widget.set_label(item.label)
        widget.set_sensitive(item.enabled)
        if item.radio:
            set_checked()

    item._listeners.append(sync)
    return widget


def _register(connection, path, info, method_call, get_property):
    # register_object_with_closures2 (GLib 2.84+) replaces the now-deprecated register_object.
    register = getattr(connection, "register_object_with_closures2", None) or connection.register_object
    return register(path, info, method_call, get_property, None)


class DBusMenu:
    """Exports a MenuItem tree as com.canonical.dbusmenu at `path`."""

    def __init__(self, connection, path, items):
        self.connection = connection
        self.path = path
        self.root = MenuItem(children=items)
        # Ids follow tree order; the layout never changes, only item properties do.
        self.ids = {}
        self.items = {}
        self._index(self.root)
        _register(connection, path, MENU_INFO, self._on_call, self._on_get)

    def _index(self, item):
        item_id = len(self.ids)
        self.ids[id(item)] = item_id
        self.items[item_id] = item
        item._listeners.append(self._on_item_changed)
        for child in item.children:
            self._index(child)

    @staticmethod
    def _props(item, names=()):
        if item.separator:
            props = {"type": GLib.Variant("s", "separator")}
        else:
            props = {"label": GLib.Variant("s", item.label), "enabled": GLib.Variant("b", item.enabled)}
            if item.radio:
                props["toggle-type"] = GLib.Variant("s", "radio")
                props["toggle-state"] = GLib.Variant("i", 1 if item.checked else 0)
        if item.children:
            props["children-display"] = GLib.Variant("s", "submenu")
        if names:
            props = {k: v for k, v in props.items() if k in names}
        return props

    def _layout(self, item, depth, names):
        children = []
        if depth != 0:
            children = [
                GLib.Variant("(ia{sv}av)", self._layout(child, depth - 1, names)) for child in item.children
            ]
        return self.ids[id(item)], self._props(item, names), children

    def _on_item_changed(self, item):
        updated = [(self.ids[id(item)], self._props(item))]
        self.connection.emit_signal(
            None, self.path, MENU_INFO.name, "ItemsPropertiesUpdated", GLib.Variant("(a(ia{sv})a(ias))", (updated, []))
        )

    def _on_get(self, _conn, _sender, _path, _iface, name):
        return {
            "Version": GLib.Variant("u", 3),
            "TextDirection": GLib.Variant("s", "ltr"),
            "Status": GLib.Variant("s", "normal"),
            "IconThemePath": GLib.Variant("as", []),
        }.get(name)

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        args = params.unpack()
        if method == "GetLayout":
            parent_id, depth, names = args
            item = self.items.get(parent_id)
            if item is None:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", f"No item {parent_id}")
                return
            invocation.return_value(GLib.Variant("(u(ia{sv}av))", (1, self._layout(item, depth, names))))
        elif method == "GetGroupProperties":
            ids, names = args
            found = [(i, self._props(self.items[i], names)) for i in (ids or self.items) if i in self.items]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (found,)))
        elif method == "GetProperty":
            item_id, name = args
            value = self._props(self.items[item_id]).get(name) if item_id in self.items else None
            if value is None:
                invocation.return_dbus_error("org.freedesktop.DBus.Error.InvalidArgs", f"No {name} on {item_id}")
                return
            invocation.return_value(GLib.Variant("(v)", (value,)))
        elif method == "Event":
            item_id, event = args[0], args[1]
            invocation.return_value(None)
            self._event(item_id, event)
        elif method == "EventGroup":
            errors = [item_id for item_id, *_ in args[0] if item_id not in self.items]
            invocation.return_value(GLib.Variant("(ai)", (errors,)))
            for item_id, event, *_ in args[0]:
                self._event(item_id, event)
        elif method == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method == "AboutToShowGroup":
            invocation.return_value(GLib.Variant("(aiai)", ([], [])))

    def _event(self, item_id, event):
        item = self.items.get(item_id)
        if event == "clicked" and item is not None and item.enabled:
            # Run after the D-Bus reply has gone out, so a dialog opened here doesn't stall the panel.
            GLib.idle_add(self._activate, item)

    @staticmethod
    def _activate(item):
        item.activate()
        return GLib.SOURCE_REMOVE


class TrayIcon:
    """One StatusNotifierItem: icon, optional text label, and a dbusmenu.

    Registers with the tray host (the GNOME AppIndicator extension, KDE's tray, …) whenever one
    appears on the bus, so it survives GNOME Shell restarts and the extension being re-enabled.
    """

    def __init__(self, item_id, title, icon, icon_dir, menu, on_secondary_activate=None):
        self.connection = Gio.bus_get_sync(Gio.BusType.SESSION)
        self.path = f"/org/bluetti/tray/{item_id.replace('-', '_')}"
        self.props = {
            "Category": "Hardware",
            "Id": item_id,
            "Title": title,
            "Status": "Active",
            "IconName": icon,
            "IconAccessibleDesc": "",
            "IconThemePath": str(icon_dir),
            "XAyatanaLabel": "",
            "XAyatanaLabelGuide": "",
        }
        self.on_secondary_activate = on_secondary_activate
        self.menu = DBusMenu(self.connection, self.path + "/menu", menu)
        _register(self.connection, self.path, SNI_INFO, self._on_call, self._on_get)
        Gio.bus_watch_name_on_connection(
            self.connection, WATCHER, Gio.BusNameWatcherFlags.NONE, self._on_watcher_appeared, None
        )

    def set_icon(self, name, desc=""):
        if (name, desc) != (self.props["IconName"], self.props["IconAccessibleDesc"]):
            self.props.update(IconName=name, IconAccessibleDesc=desc)
            self._emit("NewIcon")

    def set_label(self, label, guide):
        if (label, guide) != (self.props["XAyatanaLabel"], self.props["XAyatanaLabelGuide"]):
            self.props.update(XAyatanaLabel=label, XAyatanaLabelGuide=guide)
            self._emit("XAyatanaNewLabel", GLib.Variant("(ss)", (label, guide)))

    def set_visible(self, visible):
        status = "Active" if visible else "Passive"
        if status != self.props["Status"]:
            self.props["Status"] = status
            self._emit("NewStatus", GLib.Variant("(s)", (status,)))

    def _emit(self, signal, params=None):
        self.connection.emit_signal(None, self.path, SNI_INFO.name, signal, params)

    def _on_watcher_appeared(self, connection, name, _owner):
        connection.call(
            name,
            "/StatusNotifierWatcher",
            WATCHER,
            "RegisterStatusNotifierItem",
            GLib.Variant("(s)", (self.path,)),
            None,
            Gio.DBusCallFlags.NONE,
            -1,
            None,
            self._on_registered,
        )

    def _on_registered(self, connection, result):
        try:
            connection.call_finish(result)
        except GLib.Error as e:
            log.warning("Could not register tray icon %s: %s", self.props["Id"], e.message)

    def _on_get(self, _conn, _sender, _path, _iface, name):
        if name == "Menu":
            return GLib.Variant("o", self.menu.path)
        if name == "ItemIsMenu":
            # No Activate method: a left click opens the menu.
            return GLib.Variant("b", True)
        value = self.props.get(name)
        return None if value is None else GLib.Variant("s", value)

    def _on_call(self, _conn, _sender, _path, _iface, method, _params, invocation):
        invocation.return_value(None)
        if method in ("SecondaryActivate", "XAyatanaSecondaryActivate") and self.on_secondary_activate:
            self.on_secondary_activate()
