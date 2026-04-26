"""Text commands: insert, move, edit span, edit paragraph."""
from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from core.history import Command

if TYPE_CHECKING:
    from core.document import PDFDocument


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
    """Edit an existing text span; undo re-applies with original text/font/color.

    orig_font_bytes / new_font_bytes carry the raw embedded font data so the
    typeface is re-embedded verbatim on each execute/undo cycle rather than
    being re-resolved from name (which could produce a different font if the
    original was a non-standard PostScript face).
    """

    def __init__(self, page_num: int, span_bbox: list, span_origin: list,
                 orig_text: str, orig_size: float, orig_font: str,
                 orig_color: tuple[float, float, float], orig_font_bytes: bytes | None,
                 new_text: str, new_size: float, new_font: str,
                 new_color: tuple[float, float, float], new_font_bytes: bytes | None) -> None:
        self._page_num = page_num
        self._bbox = list(span_bbox)
        self._origin = list(span_origin)
        self._orig = (orig_text, orig_size, orig_font, orig_color, orig_font_bytes)
        self._new  = (new_text,  new_size,  new_font,  new_color,  new_font_bytes)

    def execute(self, doc: "PDFDocument") -> None:
        new_bbox = doc.apply_text_edit(self._page_num, self._bbox, self._origin, *self._new)
        self._bbox = new_bbox

    def undo(self, doc: "PDFDocument") -> None:
        new_bbox = doc.apply_text_edit(self._page_num, self._bbox, self._origin, *self._orig)
        self._bbox = new_bbox


class EditParagraphCmd(Command):
    """Replace a paragraph (block) with new text. Undo replays the original
    lines at their original origins so styling and per-line positioning are
    preserved on revert.
    """

    def __init__(self, page_num: int, orig_bbox: list, orig_lines: list,
                 new_text: str, new_size: float, new_font: str,
                 new_color: tuple[float, float, float],
                 new_font_bytes: bytes | None) -> None:
        self._page_num = page_num
        self._orig_bbox = list(orig_bbox)
        self._orig_lines = orig_lines
        self._new_text = new_text
        self._new_size = new_size
        self._new_font = new_font
        self._new_color = new_color
        self._new_font_bytes = new_font_bytes
        self._new_bbox: list | None = None

    def execute(self, doc: "PDFDocument") -> None:
        self._new_bbox = doc.apply_paragraph_edit(
            self._page_num, self._orig_bbox,
            self._new_text, self._new_size, self._new_font,
            self._new_color, self._new_font_bytes,
        )

    def undo(self, doc: "PDFDocument") -> None:
        wipe = self._new_bbox or self._orig_bbox
        doc.apply_paragraph_replay(self._page_num, wipe, self._orig_lines)
