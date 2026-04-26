"""Command pattern base class, annotation helpers, and History stack.

Concrete Command subclasses live in `core/commands/`. They are re-exported
at the bottom of this module for backward compatibility, so the legacy
``from core.history import EditTextCmd`` form keeps working.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from core.document import PDFDocument

logger = logging.getLogger(__name__)


class Command(ABC):
    @abstractmethod
    def execute(self, doc: "PDFDocument") -> None: ...

    @abstractmethod
    def undo(self, doc: "PDFDocument") -> None: ...


# ── annotation helpers ────────────────────────────────────────────────────────

def _capture_annot(annot: fitz.Annot) -> dict:
    """Snapshot all state needed to recreate an annotation."""
    try:
        info = annot.info or {}
    except Exception:
        info = {}
    return {
        "type_name": annot.type[1],
        "rect": list(annot.rect),
        "colors": dict(annot.colors),
        "border": dict(annot.border),
        "vertices": list(annot.vertices) if annot.vertices else [],
        "opacity": annot.opacity,
        "xref": annot.xref,
        "subject": info.get("subject", ""),
        "title": info.get("title", ""),
        "content": info.get("content", ""),
    }


def _recreate_annot(page: fitz.Page, snap: dict) -> int:
    """Recreate annotation from snapshot, return new xref."""
    tname = snap["type_name"]
    rect = fitz.Rect(snap["rect"])

    if tname == "Highlight":
        verts = snap["vertices"]
        quads = [fitz.Quad(verts[i:i + 4]) for i in range(0, len(verts), 4)] if verts else [rect.quad]
        annot = page.add_highlight_annot(quads)
    elif tname == "Square":
        annot = page.add_rect_annot(rect)
        stroke = snap["colors"].get("stroke")
        if stroke:
            annot.set_colors(stroke=stroke)
        annot.set_border(width=snap["border"].get("width", 1.5))
        annot.update()
    elif tname == "Circle":
        annot = page.add_circle_annot(rect)
        stroke = snap["colors"].get("stroke")
        if stroke:
            annot.set_colors(stroke=stroke)
        annot.update()
    elif tname == "Polygon":
        pts = [fitz.Point(pt) for pt in snap["vertices"]]
        annot = page.add_polygon_annot(pts)
        stroke = snap["colors"].get("stroke")
        if stroke:
            annot.set_colors(stroke=stroke)
        annot.set_border(width=snap["border"].get("width", 1.5))
        annot.update()
    elif tname == "Ink":
        strokes = snap["vertices"]  # list of lists of points
        annot = page.add_ink_annot(strokes)
        stroke = snap["colors"].get("stroke")
        if stroke:
            annot.set_colors(stroke=stroke)
        annot.set_border(width=snap["border"].get("width", 1.5))
        opacity = snap.get("opacity", 1.0)
        if opacity is not None and opacity < 1.0:
            annot.set_opacity(opacity)
        annot.update()
    else:
        annot = page.add_rect_annot(rect)
        annot.update()
    return annot.xref


def _move_annot(page: fitz.Page, xref: int, new_rect: fitz.Rect, new_verts: list) -> int:
    """Move annotation to new_rect/new_verts. Returns the (possibly new) xref.

    Polygon, PolyLine, and Ink annotations are moved by delete+recreate rather
    than by updating the xref directly. fitz.Annot caches its geometry at
    load time, so xref_set_key() + annot.update() would regenerate the
    appearance stream from stale cached values — the annotation would snap
    back to its original position visually. Recreating avoids the cache.
    """
    annot = page.load_annot(xref)
    if annot is None:
        return xref
    tname = annot.type[1] if annot.type else ""
    if tname in ("Polygon", "PolyLine", "Ink"):
        snap = _capture_annot(annot)
        if new_verts:
            snap["vertices"] = new_verts
        snap["rect"] = list(new_rect)
        page.delete_annot(annot)
        return _recreate_annot(page, snap)
    else:
        annot.set_rect(new_rect)
        annot.update()
        return xref


def _wipe_rect(page: fitz.Page, rect: list) -> None:
    """Redact a rect on the page without removing images, drawings, or text outside it."""
    page.add_redact_annot(fitz.Rect(rect))
    page.apply_redactions(images=0, graphics=0, text=0)


# ── history stack ─────────────────────────────────────────────────────────────

class History:
    def __init__(self, max_size: int = 500) -> None:
        self._undo_stack: "deque[Command]" = deque(maxlen=max_size)
        self._redo_stack: "deque[Command]" = deque(maxlen=max_size)

    def push(self, cmd: Command, doc: "PDFDocument") -> None:
        cmd.execute(doc)
        self._undo_stack.append(cmd)
        self._redo_stack.clear()  # any new action invalidates the redo branch

    def undo(self, doc: "PDFDocument") -> int | None:
        """Execute undo; return page_num of affected page, -1 for page operations,
        or None if nothing to undo."""
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        cmd.undo(doc)
        self._redo_stack.append(cmd)
        return getattr(cmd, "_page_num", -1 if hasattr(cmd, "_index") else None)

    def redo(self, doc: "PDFDocument") -> int | None:
        """Execute redo; return page_num of affected page, -1 for page operations,
        or None if nothing to redo."""
        if not self._redo_stack:
            return None
        cmd = self._redo_stack.pop()
        cmd.execute(doc)
        self._undo_stack.append(cmd)
        return getattr(cmd, "_page_num", -1 if hasattr(cmd, "_index") else None)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)


# ── back-compat re-exports ────────────────────────────────────────────────────
# Imported AFTER Command + helpers are defined so the submodules can do
# `from core.history import Command, _capture_annot, ...` without a circular-
# import failure.
from core.commands.annot import AddAnnotCmd, DeleteAnnotCmd, MoveAnnotCmd  # noqa: E402
from core.commands.annot_text import (  # noqa: E402
    AnnotationTextCmd,
    DeleteAnnotTextCmd,
    TransformAnnotTextCmd,
)
from core.commands.group import GroupCmd  # noqa: E402
from core.commands.image import (  # noqa: E402
    MoveDrawingCmd,
    MoveImageCmd,
    MoveImageWithSiblingsCmd,
)
from core.commands.page import (  # noqa: E402
    DeletePageCmd,
    InsertPageCmd,
    MovePageCmd,
    ResizePageCmd,
    RotatePageCmd,
)
from core.commands.text import (  # noqa: E402
    AddTextCmd,
    EditParagraphCmd,
    EditTextCmd,
    MoveTextCmd,
)

__all__ = [
    "Command",
    "History",
    "_capture_annot",
    "_recreate_annot",
    "_move_annot",
    "_wipe_rect",
    "AddAnnotCmd",
    "DeleteAnnotCmd",
    "MoveAnnotCmd",
    "AnnotationTextCmd",
    "DeleteAnnotTextCmd",
    "TransformAnnotTextCmd",
    "GroupCmd",
    "MoveDrawingCmd",
    "MoveImageCmd",
    "MoveImageWithSiblingsCmd",
    "DeletePageCmd",
    "InsertPageCmd",
    "MovePageCmd",
    "ResizePageCmd",
    "RotatePageCmd",
    "AddTextCmd",
    "EditParagraphCmd",
    "EditTextCmd",
    "MoveTextCmd",
]
