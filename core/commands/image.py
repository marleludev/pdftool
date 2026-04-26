"""Image and vector-drawing commands."""
from __future__ import annotations

from typing import TYPE_CHECKING

import fitz

from core.history import Command

if TYPE_CHECKING:
    from core.document import PDFDocument


class MoveImageCmd(Command):
    """Move an image from src_rect to dst_rect; undo moves it back."""

    def __init__(self, page_num: int, xref: int,
                 src_rect: list, dst_rect: list,
                 image_bytes: bytes) -> None:
        self._page_num = page_num
        self._xref = xref
        self._src_rect = list(src_rect)
        self._dst_rect = list(dst_rect)
        self._bytes = image_bytes

    def execute(self, doc: "PDFDocument") -> None:
        doc.apply_image_move(self._page_num, self._xref,
                             self._src_rect, self._dst_rect, self._bytes)

    def undo(self, doc: "PDFDocument") -> None:
        doc.apply_image_move(self._page_num, self._xref,
                             self._dst_rect, self._src_rect, self._bytes)


class MoveImageWithSiblingsCmd(Command):
    """Move an image by redacting the source then inserting at the new position.

    Avoids delete_image() which corrupts state. Order matters: redacting the
    source AFTER inserting at the destination would also remove the freshly
    placed dst image when src and dst rects overlap (small drags). Other
    images touching the wipe rect are captured and re-inserted so backgrounds
    and overlapping images are preserved.
    """

    def __init__(self, page_num: int, xref: int,
                 src_rect: list, dst_rect: list,
                 image_bytes: bytes) -> None:
        self._page_num = page_num
        self._xref = xref
        self._src_rect = list(src_rect)
        self._dst_rect = list(dst_rect)
        self._bytes = image_bytes

    def _apply(self, doc: "PDFDocument", wipe_rect: list, place_rect: list) -> None:
        from tools.select import _extract_image_bytes
        page = doc.get_page(self._page_num)
        wipe_r = fitz.Rect(wipe_rect)
        place_r = fitz.Rect(place_rect)

        # Capture other images intersecting wipe_r so we can restore them.
        siblings: list[tuple[fitz.Rect, bytes]] = []
        for info in page.get_image_info(xrefs=True):
            xr = info.get("xref", 0)
            if not xr:
                continue
            r = fitz.Rect(info["bbox"])
            if r.is_empty or not r.intersects(wipe_r):
                continue
            if (abs(r.x0 - wipe_r.x0) < 1.0 and abs(r.y0 - wipe_r.y0) < 1.0
                and abs(r.x1 - wipe_r.x1) < 1.0 and abs(r.y1 - wipe_r.y1) < 1.0):
                continue
            b = _extract_image_bytes(doc._doc, xr)
            if b is not None:
                siblings.append((r, b))

        if wipe_r.width > 0 and wipe_r.height > 0:
            page.add_redact_annot(wipe_r, fill=None)
            page.apply_redactions(images=1, graphics=0, text=1)
            for r, b in siblings:
                page.insert_image(r, stream=b, overlay=True)

        if place_r.width > 0 and place_r.height > 0:
            page.insert_image(place_r, stream=self._bytes, overlay=True)

    def execute(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._src_rect, self._dst_rect)

    def undo(self, doc: "PDFDocument") -> None:
        self._apply(doc, self._dst_rect, self._src_rect)


class MoveDrawingCmd(Command):
    """Translate a vector drawing by (dx, dy); undo reverses the shift.

    The drawing dict is updated after each apply to reflect the current
    on-page position so that subsequent execute/undo cycles use the right
    source geometry for the strip-and-redraw step.
    """

    def __init__(self, page_num: int, drawing: dict, dx: float, dy: float) -> None:
        self._page_num = page_num
        self._drawing = drawing  # current on-page drawing dict
        self._dx = dx
        self._dy = dy

    def execute(self, doc: "PDFDocument") -> None:
        self._drawing = doc.apply_drawing_move(
            self._page_num, self._drawing, self._dx, self._dy
        )

    def undo(self, doc: "PDFDocument") -> None:
        self._drawing = doc.apply_drawing_move(
            self._page_num, self._drawing, -self._dx, -self._dy
        )
