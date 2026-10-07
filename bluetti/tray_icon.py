"""Coloured tray icons, written as small SVG files to the runtime dir.

The panel only shows plain text in an indicator's label, so the colour lives in the icons:
a battery with green fill (red at 20% or below, bolt while charging, grey outline when
disconnected), and green ↓ / orange ↑ arrows for input and output (grey at 0 W).
"""

from pathlib import Path

from gi.repository import GLib

DIR = Path(GLib.get_user_runtime_dir()) / "bluetti-linux" / "icons"

GREEN = "#2ecc71"
RED = "#e74c3c"
ORANGE = "#f39c12"
OUTLINE = "#ffffff"
MUTED = "#9e9e9e"
BOLT = (
    '<path d="M11 4.5 L6.5 12 H9.8 L8.8 17.5 L13.5 10 H10.2 Z" '
    'fill="#ffffff" stroke="#1e1e1e" stroke-width="0.8" stroke-linejoin="round"/>'
)
ARROWS = {
    "in": ("M11 3.5 V16.5 M5.5 11 L11 16.5 L16.5 11", GREEN),
    "out": ("M11 18.5 V5.5 M5.5 11 L11 5.5 L16.5 11", ORANGE),
}


def icon_name(status):
    """Battery icon for this state."""
    if status is None:
        return _write("bluetti-none", _battery_svg(None, False, False))
    level = min(100, round(status.battery_pct / 5) * 5)
    low = status.battery_pct <= 20
    name = f"bluetti-{level}{'-low' if low else ''}{'-charging' if status.charging else ''}"
    return _write(name, _battery_svg(level, low, status.charging))


def arrow_icon(direction, active):
    """Input (↓) or output (↑) arrow; grey when no power is flowing."""
    path, color = ARROWS[direction]
    if not active:
        color = MUTED
    svg = (
        f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2.6" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return _write(f"bluetti-{direction}{'' if active else '-idle'}", _wrap(svg))


def _write(name, svg):
    path = DIR / f"{name}.svg"
    if not path.exists():
        DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(svg)
    return name


def _wrap(body):
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 22 22">{body}</svg>'


def _battery_svg(level, low, charging):
    outline = MUTED if level is None else OUTLINE
    parts = [
        f'<rect x="1.5" y="6.5" width="17" height="9" rx="2" fill="none" stroke="{outline}" stroke-width="1.5"/>',
        f'<rect x="19" y="9" width="2" height="4" rx="0.8" fill="{outline}"/>',
    ]
    if level:
        color = RED if low else GREEN
        parts.append(f'<rect x="3.5" y="8.5" width="{13 * level / 100:.2f}" height="5" rx="1" fill="{color}"/>')
    if charging:
        parts.append(BOLT)
    return _wrap("".join(parts))
