"""Page-level commands: insert / delete / move / resize / rotate."""
from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from core.history import Command

if TYPE_CHECKING:
    from core.document import PDFDocument


class InsertPageCmd(Command):
    """Insert a blank page; undo deletes it."""

    def __init__(self, index: int, width: float | None = None, height: float | None = None) -> None:
        self._index = index
        self._width = width
        self._height = height

    def execute(self, doc: "PDFDocument") -> None:
        doc.insert_blank_page(self._index, self._width, self._height)

    def undo(self, doc: "PDFDocument") -> None:
        doc.delete_page(self._index)


class DeletePageCmd(Command):
    """Delete a page; undo re-inserts it.

    Note: This stores the entire page content which may be memory-intensive
    for large pages. For production use with large documents, consider
    storing only a reference and requiring the original file for undo.
    """

    def __init__(self, index: int) -> None:
        self._index = index
        self._page_bytes: bytes | None = None

    def execute(self, doc: "PDFDocument") -> None:
        # Snapshot single page into a temporary doc, then delete from main doc.
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc.fitz_doc, from_page=self._index, to_page=self._index)
        self._page_bytes = temp_doc.tobytes()
        temp_doc.close()
        doc.delete_page(self._index)

    def undo(self, doc: "PDFDocument") -> None:
        if self._page_bytes is None:
            return
        temp_doc = fitz.open(stream=self._page_bytes, filetype="pdf")
        doc.fitz_doc.insert_pdf(temp_doc, start_at=self._index)
        temp_doc.close()


class MovePageCmd(Command):
    """Move a page from one position to another; undo moves it back."""

    def __init__(self, from_index: int, to_index: int) -> None:
        self._from_index = from_index
        self._to_index = to_index
        # Alias so History.undo/redo classify this as a page op (returns -1).
        self._index = to_index

    def execute(self, doc: "PDFDocument") -> None:
        doc.move_page(self._from_index, self._to_index)

    def undo(self, doc: "PDFDocument") -> None:
        doc.move_page(self._to_index, self._from_index)


class ResizePageCmd(Command):
    """Resize a page; undo restores the original page content and dimensions."""

    def __init__(self, index: int, new_w: float, new_h: float, content_mode: str) -> None:
        self._index = index
        self._new_w = new_w
        self._new_h = new_h
        self._content_mode = content_mode
        self._page_bytes: bytes | None = None

    def execute(self, doc: "PDFDocument") -> None:
        snap = fitz.open()
        snap.insert_pdf(doc.fitz_doc, from_page=self._index, to_page=self._index)
        self._page_bytes = snap.tobytes()
        snap.close()
        doc.resize_page(self._index, self._new_w, self._new_h, self._content_mode)

    def undo(self, doc: "PDFDocument") -> None:
        if self._page_bytes is None:
            return
        snap = fitz.open(stream=self._page_bytes, filetype="pdf")
        doc.fitz_doc.delete_page(self._index)
        doc.fitz_doc.insert_pdf(snap, start_at=self._index)
        snap.close()


class RotatePageCmd(Command):
    """Rotate a page by delta degrees; undo reverses the rotation."""

    def __init__(self, index: int, degrees: int) -> None:
        self._index = index
        self._degrees = degrees

    def execute(self, doc: "PDFDocument") -> None:
        doc.rotate_page(self._index, self._degrees)

    def undo(self, doc: "PDFDocument") -> None:
        doc.rotate_page(self._index, -self._degrees)
