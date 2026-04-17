"""Inline SVG icons for sidebar rows and future panels.

Icons are defined as SVG strings in this file and rendered on demand
through :class:`QSvgRenderer` into :class:`QPixmap`.  Results are
cached per ``(name, size, color)`` so the same row-height + palette
produces only one rasterisation.

Rendering inline SVG (rather than bundling .svg asset files) keeps the
icons versioned with the code that consumes them, sidesteps path
lookups for pyinstaller/zipapp packaging, and lets the icon pick up
a palette colour by string-substituting ``{color}`` at render time.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# ── SVG definitions ─────────────────────────────────────────────────────
#
# Viewbox for all icons is 16×16 so rendering at any device-pixel size
# stays crisp; strokes are ~1.6 units wide to read clearly at 12px UI
# size and still look balanced at 24px zoomed.  Colours are injected by
# substituting ``{color}`` at render time.

_SVG_CHEVRON_RIGHT = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M6 3.5 L10.5 8 L6 12.5"
        fill="none" stroke="{color}" stroke-width="1.6"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

_SVG_CHEVRON_DOWN = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <path d="M3.5 6 L8 10.5 L12.5 6"
        fill="none" stroke="{color}" stroke-width="1.6"
        stroke-linecap="round" stroke-linejoin="round"/>
</svg>"""

# Class glyph: rounded square, filled with a subtle accent wash, with a
# crisp "C" letter centred on it.  Using a single-path "C" (one arc +
# trimmed ends) keeps the letter shape readable at 12–16 px.
_SVG_CLASS = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">
  <rect x="2" y="2" width="12" height="12" rx="2.5" ry="2.5"
        fill="{bg}" stroke="{color}" stroke-width="0.8"/>
  <path d="M10.5 5.5
           A 3.2 3.2 0 1 0 10.5 10.5"
        fill="none" stroke="{color}" stroke-width="1.8"
        stroke-linecap="round"/>
</svg>"""


_SVGS: dict[str, str] = {
    "chevron_right": _SVG_CHEVRON_RIGHT,
    "chevron_down":  _SVG_CHEVRON_DOWN,
    "class":         _SVG_CLASS,
}


# ── cache ─────────────────────────────────────────────────────────────


# Keyed on (name, px, color, bg-or-None).
_CACHE: dict[tuple[str, int, str, str], QIcon] = {}


def icon(name: str, *, size: int = 16, color: str = "#a7abb3",
         bg: str = "transparent") -> QIcon:
    """Return a cached :class:`QIcon` for ``name`` rendered with the
    given size (pixels) and colour.

    ``bg`` is only honoured by icons that define a ``{bg}`` token
    (currently the ``"class"`` glyph).  Passing the palette accent
    wash there tints the letter block without altering the stroke.
    """
    key = (name, size, color, bg)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    template = _SVGS.get(name)
    if template is None:
        _CACHE[key] = QIcon()
        return _CACHE[key]

    svg = template.format(color=color, bg=bg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))

    # Render at 2x target size and let Qt downscale — smoother on
    # fractional-DPI displays than rendering at the target directly.
    px = QPixmap(size * 2, size * 2)
    px.fill(Qt.transparent)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    renderer.render(painter, QRectF(0, 0, size * 2, size * 2))
    painter.end()

    icon_obj = QIcon(px)
    _CACHE[key] = icon_obj
    return icon_obj
