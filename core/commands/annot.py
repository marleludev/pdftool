"""Annotation commands: add / delete / move existing annotations."""
from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from core.history import Command, _move_annot, _recreate_annot

if TYPE_CHECKING:
    from core.document import PDFDocument


class AddAnnotCmd(Command):
    """Undo: delete annotation by xref."""

    def __init__(self, page_num: int, annot_type: str, data: dict) -> None:
        self._page_num = page_num
        self._annot_type = annot_type
        self._data = data
        self._xref: int | None = None

    def execute(self, doc: "PDFDocument") -> None:
        if self._annot_type == "highlight":
            self._xref = doc.apply_highlight(
                self._page_num, self._data["quads"],
                color=self._data.get("color"),
            )
        elif self._annot_type == "rect_annot":
            self._xref = doc.apply_rect_annot(
                self._page_num, self._data["rect"],
                self._data["color"], self._data["width"]
            )
        elif self._annot_type == "polygon":
            self._xref = doc.apply_polygon_annot(
                self._page_num,
                self._data["points"],
                self._data["color"],
                self._data["width"],
            )
        elif self._annot_type == "ink":
            self._xref = doc.apply_ink_annot(
                self._page_num,
                self._data["strokes"],
                self._data["color"],
                self._data["width"],
                self._data.get("opacity", 1.0),
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
        self._xref = _move_annot(page, self._xref, fitz.Rect(self._new_rect), self._new_verts)

    def undo(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        self._xref = _move_annot(page, self._xref, fitz.Rect(self._old_rect), self._old_verts)
