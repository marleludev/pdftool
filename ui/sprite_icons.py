"""Sprite-backed icon loader.

Renders icons from a single SVG sprite (`ui/icons/pdf-icons-sprite.svg`)
into QIcon instances. Falls back to an empty QIcon when a name is unknown.

The sprite uses `currentColor` for strokes/fills; we substitute the requested
hex color before handing the standalone SVG to QSvgRenderer.
"""
from __future__ import annotations

import re
from pathlib import Path

from PyQt6.QtCore import QByteArray, Qt
from PyQt6.QtGui import QIcon, QPainter, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_SPRITE_PATH = Path(__file__).parent / "icons" / "pdf-icons-sprite.svg"

_SYMBOL_RE = re.compile(
    r'<symbol\s+id="(?P<id>[^"]+)"\s+viewBox="(?P<vb>[^"]+)"\s*>(?P<body>.*?)</symbol>',
    re.DOTALL,
)

_symbols: dict[str, tuple[str, str]] = {}


def _load() -> None:
    if _symbols or not _SPRITE_PATH.exists():
        return
    text = _SPRITE_PATH.read_text(encoding="utf-8")
    for m in _SYMBOL_RE.finditer(text):
        _symbols[m.group("id")] = (m.group("vb"), m.group("body"))


# Resolve theme/mdi/internal names to sprite symbol ids.
_NAME_TO_SYMBOL: dict[str, str] = {
    # File ops
    "document-open":           "icon-open",
    "document-save":           "icon-save",
    "document-save-as":        "icon-export",
    "document-close":          "icon-close",
    "document-open-recent":    "icon-document-open-recent",
    "document-properties":     "icon-settings",
    "preferences-other":       "icon-settings",
    "document-print":          "icon-print",
    # Edit ops
    "edit-undo":               "icon-undo",
    "edit-redo":               "icon-redo",
    "edit-paste":              "icon-edit-paste",
    "edit-select":             "icon-select",
    "edit-rect-select":        "icon-select-text",
    "insert-page":             "icon-page-add",
    "insert-text":             "icon-text",
    "insert-image":            "icon-image",
    "document-edit":           "icon-text-block",
    # Draw / annotate
    "draw-rectangle":          "icon-draw-rectangle",
    "draw-highlight":          "icon-highlight",
    "draw-brush":              "icon-draw-line",
    "draw-encircle":           "icon-draw-encircle",
    "draw-freehand":           "icon-edit-multiline-text",
    # Tools / nav
    "transform-move":          "icon-transform-move",
    "input-mouse":             "icon-input-mouse",
    # Z-order
    "object-order-back":       "icon-layer-down",
    "object-order-front":      "icon-layer-up",
    # Zoom
    "zoom-in":                 "icon-zoom-in",
    "zoom-out":                "icon-zoom-out",
    "zoom-fit-best":           "icon-fit-page",
    # Image / scan
    "scanner":                 "icon-scanner",
    "image-x-generic":         "icon-image",
    "image-x-raw":             "icon-image",
    # Misc
    "user-trash":              "icon-page-delete",
    "application-certificate": "icon-application-certificate",
    "mail-signed":             "icon-sign",
    "document-encrypt":        "icon-redact",
    "document-unlock":         "icon-document-unlock",
    # mdi-style names used in dialogs / thumbnail panel
    "folder-open":             "icon-open",
    "close":                   "icon-close",
    "draw":                    "icon-sign",
    "file-cog":                "icon-settings",
    "content-cut":             "icon-split",
    "file-plus":               "icon-page-add",
    "file-plus-outline":       "icon-page-add",
    "resize":                  "icon-fit-page",
    "rotate-right":            "icon-rotate-cw",
    "rotate-left":             "icon-rotate-ccw",
    "trash-can":               "icon-page-delete",
    "file-document":           "icon-file-document",
}


def sprite_icon(name: str, color: str = "#555555", size: int = 64) -> QIcon:
    """Build a QIcon from the sprite. Returns null QIcon if name unknown."""
    _load()
    symbol_id = _NAME_TO_SYMBOL.get(name)
    if symbol_id is None:
        return QIcon()
    rec = _symbols.get(symbol_id)
    if rec is None:
        return QIcon()
    viewbox, body = rec
    body_colored = body.replace("currentColor", color)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}">'
        f'{body_colored}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    if not renderer.isValid():
        return QIcon()
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    renderer.render(painter)
    painter.end()
    return QIcon(pm)
