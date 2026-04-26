"""Annotation-text commands: insert / transform / delete reusable text blocks.

Annotation text is rendered into the page (with the embedded Architects
Daughter font) plus an invisible Square marker so SelectTool can recognise
the block for move/resize/edit.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import fitz

from core.history import Command, _wipe_rect

if TYPE_CHECKING:
    from core.document import PDFDocument

logger = logging.getLogger(__name__)


class AnnotationTextCmd(Command):
    """Insert annotation text. Undo redacts the rect and removes the marker."""

    def __init__(self, page_num: int, rect: list, text: str,
                 fontsize: float, color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._rect = list(rect)
        self._text = text
        self._fontsize = fontsize
        self._color = color
        self._xref: int | None = None

    def execute(self, doc: "PDFDocument") -> None:
        self._xref = doc.apply_annotation_text(
            self._page_num, self._rect, self._text, self._fontsize, self._color,
        )

    def undo(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        _wipe_rect(page, self._rect)
        if self._xref is not None:
            try:
                annot = page.load_annot(self._xref)
                if annot is not None:
                    page.delete_annot(annot)
            except Exception as e:
                logger.debug("AnnotationTextCmd.undo: load/delete xref %d failed: %s",
                             self._xref, e)


class TransformAnnotTextCmd(Command):
    """Move or resize an annotation-text marker. Re-renders the text into
    the new rect so wrapped lines reflow, and updates the marker rect.
    Undo reverses the transform.
    """

    def __init__(self, page_num: int, xref: int,
                 old_rect: list, new_rect: list,
                 text: str, fontsize: float,
                 color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._xref = xref
        self._old_rect = list(old_rect)
        self._new_rect = list(new_rect)
        self._text = text
        self._fontsize = fontsize
        self._color = color

    def _apply(self, doc: "PDFDocument", src: list, dst: list) -> None:
        page = doc.get_page(self._page_num)
        _wipe_rect(page, src)
        doc._render_annot_text(self._page_num, dst, self._text, self._fontsize, self._color)
        try:
            annot = page.load_annot(self._xref)
            if annot is not None:
                annot.set_rect(fitz.Rect(dst))
                annot.update()
        except Exception as e:
            logger.debug("TransformAnnotTextCmd: rect update on xref %d failed: %s",
                         self._xref, e)

    def execute(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._old_rect, self._new_rect)

    def undo(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._new_rect, self._old_rect)


class DeleteAnnotTextCmd(Command):
    """Delete an annotation-text marker: redact the rect and remove the
    marker annot. Undo re-renders + re-creates marker.
    """

    def __init__(self, page_num: int, xref: int, rect: list, text: str,
                 fontsize: float, color: tuple[float, float, float]) -> None:
        self._page_num = page_num
        self._xref = xref
        self._rect = list(rect)
        self._text = text
        self._fontsize = fontsize
        self._color = color

    def execute(self, doc: "PDFDocument") -> None:
        page = doc.get_page(self._page_num)
        _wipe_rect(page, self._rect)
        try:
            annot = page.load_annot(self._xref)
            if annot is not None:
                page.delete_annot(annot)
        except Exception as e:
            logger.debug("DeleteAnnotTextCmd: load/delete xref %d failed: %s",
                         self._xref, e)

    def undo(self, doc: "PDFDocument") -> None:
        self._xref = doc.apply_annotation_text(
            self._page_num, self._rect, self._text, self._fontsize, self._color,
        )
