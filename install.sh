#!/bin/sh
# Add Bluetti EB3A to the app grid (and optionally to autostart) for the current user,
# pointing at this checkout. Re-run after moving the checkout.
#
#   ./install.sh               app launcher
#   ./install.sh --autostart   app launcher, plus start hidden in the tray at login
#   ./install.sh --uninstall   remove both
set -eu

APP_ID=io.github.fgtb599.BluettiLinux
DIR=$(cd "$(dirname "$0")" && pwd)
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
AUTOSTART="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

# Entry with this checkout's path; extra arguments are appended to Exec.
entry() {
    sed -e "s|/path/to/bluetti-linux|$DIR|" -e "/^Exec=/s|\$|$1|" "$DIR/$APP_ID.desktop"
}

case "${1:-}" in
"" | --autostart)
    mkdir -p "$APPS"
    entry "" >"$APPS/$APP_ID.desktop"
    echo "Launcher: $APPS/$APP_ID.desktop"
    if [ "${1:-}" = --autostart ]; then
        mkdir -p "$AUTOSTART"
        { entry " --hidden"; echo "X-GNOME-Autostart-enabled=true"; } >"$AUTOSTART/$APP_ID.desktop"
        rm -f "$AUTOSTART/bluetti-tray.desktop"  # entry from older versions
        echo "Autostart: $AUTOSTART/$APP_ID.desktop"
    fi
    ;;
--uninstall)
    rm -f "$APPS/$APP_ID.desktop" "$AUTOSTART/$APP_ID.desktop" "$AUTOSTART/bluetti-tray.desktop"
    echo "Removed launcher and autostart entries."
    ;;
*)
    sed -n '2,8s/^# \{0,1\}//p' "$0"
    exit 2
    ;;
esac
command -v update-desktop-database >/dev/null && update-desktop-database -q "$APPS" || true
