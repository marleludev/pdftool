from __future__ import annotations

from abc import ABC, abstractmethod
from collections import deque
from typing import TYPE_CHECKING

import fitz

if TYPE_CHECKING:
    from core.document import PDFDocument


class Command(ABC):
    @abstractmethod
    def execute(self, doc: "PDFDocument") -> None: ...

    @abstractmethod
    def undo(self, doc: "PDFDocument") -> None: ...


# ── helpers ───────────────────────────────────────────────────────────────────

def _capture_annot(annot: fitz.Annot) -> dict:
    """Snapshot all state needed to recreate an annotation."""
    return {
        "type_name": annot.type[1],
        "rect": list(annot.rect),
        "colors": dict(annot.colors),
        "border": dict(annot.border),
        "vertices": list(annot.vertices) if annot.vertices else [],
        "xref": annot.xref,
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
    else:
        annot = page.add_rect_annot(rect)
        annot.update()
    return annot.xref


def _move_annot(page: fitz.Page, xref: int, new_rect: fitz.Rect, new_verts: list) -> None:
    annot = page.load_annot(xref)
    if annot is None:
        return
    if new_verts:
        annot.set_vertices(new_verts)
    annot.set_rect(new_rect)
    annot.update()


# ── concrete commands ─────────────────────────────────────────────────────────

class AddAnnotCmd(Command):
    """Undo: delete annotation by xref."""

    def __init__(self, page_num: int, annot_type: str, data: dict) -> None:
        self._page_num = page_num
        self._annot_type = annot_type
        self._data = data
        self._xref: int | None = None

    def execute(self, doc: "PDFDocument") -> None:
        if self._annot_type == "highlight":
            self._xref = doc.apply_highlight(self._page_num, self._data["quads"])
        elif self._annot_type == "rect_annot":
            self._xref = doc.apply_rect_annot(
                self._page_num, self._data["rect"],
                self._data["color"], self._data["width"]
            )

    def undo(self, doc: "PDFDocument") -> None:
        if self._xref is not None:
            doc.delete_annotation(self._page_num, self._xref)


class DeleteAnnotCmd(Command):
    """Undo: recreate annotation from snapshot."""

    def __init__(self, page_num: int, snap: dict) -> None:
        self._page_num = page_num
        self._snap = snap
        self._new_xref: int | None = None

    def execute(self, doc: "PDFDocument") -> None:
        doc.delete_annotation(self._page_num, self._snap["xref"])

    def undo(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        self._new_xref = _recreate_annot(page, self._snap)
        # update xref in snapshot so a subsequent redo can delete the right one
        self._snap = dict(self._snap, xref=self._new_xref)


class MoveAnnotCmd(Command):
    """Undo: move annotation back to original rect/vertices."""

    def __init__(self, page_num: int, xref: int,
                 old_rect: list, old_verts: list,
                 new_rect: list, new_verts: list) -> None:
        self._page_num = page_num
        self._xref = xref
        self._old_rect = old_rect
        self._old_verts = old_verts
        self._new_rect = new_rect
        self._new_verts = new_verts

    def execute(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        _move_annot(page, self._xref, fitz.Rect(self._new_rect), self._new_verts)

    def undo(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        _move_annot(page, self._xref, fitz.Rect(self._old_rect), self._old_verts)


class AddTextCmd(Command):
    """Undo: redact the inserted text rect."""

    def __init__(self, page_num: int, rect: list, text: str,
                 fontsize: float, font_name: str,
                 color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._rect = rect
        self._text = text
        self._fontsize = fontsize
        self._font_name = font_name
        self._color = color

    def execute(self, doc: "PDFDocument") -> None:
        doc.apply_text_insert(self._page_num, self._rect, self._text,
                              self._fontsize, self._font_name, self._color)

    def undo(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        page.add_redact_annot(fitz.Rect(self._rect))
        page.apply_redactions()


class MoveTextCmd(Command):
    """Move a text span; undo puts it back. Tracks bbox and current origin after each op."""

    def __init__(self, page_num: int, src_bbox: list, src_origin: list,
                 new_origin: list, text: str, fontsize: float,
                 font_name: str, color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._bbox = list(src_bbox)
        self._from_origin = list(src_origin)  # where span IS before this cmd
        self._to_origin = list(new_origin)    # where span GOES on execute
        self._text = text
        self._fontsize = fontsize
        self._font_name = font_name
        self._color = color

    def _apply(self, doc: "PDFDocument", current_origin: list, target_origin: list) -> None:
        new_bbox = doc.apply_text_move(
            self._page_num, self._bbox, current_origin, target_origin,
            self._text, self._fontsize, self._font_name, self._color,
        )
        self._bbox = new_bbox

    def execute(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._from_origin, self._to_origin)

    def undo(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._to_origin, self._from_origin)


class EditTextCmd(Command):
    """Undo: re-apply edit with original span data."""

    def __init__(self, page_num: int, span_bbox: list, span_origin: list,
                 orig_text: str, orig_size: float, orig_font: str,
                 orig_color: tuple[float, float, float],
                 new_text: str, new_size: float, new_font: str,
                 new_color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._bbox = list(span_bbox)
        self._origin = list(span_origin)
        self._orig = (orig_text, orig_size, orig_font, orig_color)
        self._new = (new_text, new_size, new_font, new_color)

    def execute(self, doc: "PDFDocument") -> None:
        new_bbox = doc.apply_text_edit(self._page_num, self._bbox, self._origin, *self._new)
        self._bbox = new_bbox  # track actual extent so undo redacts the right area

    def undo(self, doc: "PDFDocument") -> None:
        new_bbox = doc.apply_text_edit(self._page_num, self._bbox, self._origin, *self._orig)
        self._bbox = new_bbox


# ── history stack ─────────────────────────────────────────────────────────────

class History:
    def __init__(self, max_size: int = 500) -> None:
        self._undo_stack: deque[Command] = deque(maxlen=max_size)
        self._redo_stack: deque[Command] = deque(maxlen=max_size)

    def push(self, cmd: Command, doc: "PDFDocument") -> None:
        cmd.execute(doc)
        self._undo_stack.append(cmd)
        self._redo_stack.clear()

    def undo(self, doc: "PDFDocument") -> int | None:
        """Execute undo; return page_num of affected page, or None if nothing to undo."""
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        cmd.undo(doc)
        self._redo_stack.append(cmd)
        return getattr(cmd, "_page_num", None)

    def redo(self, doc: "PDFDocument") -> int | None:
        """Execute redo; return page_num of affected page, or None if nothing to redo."""
        if not self._redo_stack:
            return None
        cmd = self._redo_stack.pop()
        cmd.execute(doc)
        self._undo_stack.append(cmd)
        return getattr(cmd, "_page_num", None)

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo_stack)
