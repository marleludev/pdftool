from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import fitz

from core.drawing import _render_drawing, _shift_drawing, _shift_point
from core.fonts import (
    _builtin_for_name,
    _FAMILY_KEYS,
    _find_unicode_font,
    _int_to_rgb,
    _needs_unicode,
    _STYLE_MAP,
    resolve_font,
)

logger = logging.getLogger(__name__)


class PDFDocument:
    """Wrapper around PyMuPDF's fitz.Document for PDF editing operations.

    This class provides a higher-level interface for common PDF operations
    including annotations, text editing, and rendering.
    """

    def __init__(self, path: Path) -> None:
        """Initialize the document from a file path.

        Args:
            path: Path to the PDF file to open.
        """
        self.path = path
        self._doc = fitz.open(str(path))
        logger.info("Opened PDF document: %s (%d pages)", path, len(self._doc))

    @property
    def fitz_doc(self) -> fitz.Document:
        """Read-only access to the underlying fitz document."""
        return self._doc

    @property
    def page_count(self) -> int:
        """Return the total number of pages in the document."""
        return len(self._doc)

    def get_page(self, page_num: int) -> fitz.Page:
        """Get a specific page from the document.

        Args:
            page_num: Zero-based page index.

        Returns:
            The fitz.Page object for the requested page.
        """
        return self._doc[page_num]

    def render_page(self, page_num: int, scale: float = 1.5) -> fitz.Pixmap:
        """Render a page to a pixmap at the specified scale.

        Args:
            page_num: Zero-based page index.
            scale: Scale factor for rendering (1.0 = 72 DPI).

        Returns:
            A fitz.Pixmap containing the rendered page.
        """
        page = self._doc[page_num]
        mat = fitz.Matrix(scale, scale)
        return page.get_pixmap(matrix=mat, alpha=False)

    # ── annotations (immediately applied, xref returned for undo) ────────────

    def apply_highlight(self, page_num: int, quads: list, color: list | None = None) -> int:
        page = self._doc[page_num]
        fitz_quads = [fitz.Quad(q) for q in quads]
        annot = page.add_highlight_annot(fitz_quads)
        if color:
            annot.set_colors(stroke=color)
            annot.update()
        logger.debug("Added highlight annotation on page %d (xref=%d)", page_num, annot.xref)
        return annot.xref

    def apply_polygon_annot(
        self, page_num: int, points: list, color: list, width: float, opacity: float = 0.3
    ) -> int:
        page = self._doc[page_num]
        fitz_pts = [fitz.Point(pt[0], pt[1]) for pt in points]
        annot = page.add_polygon_annot(fitz_pts)
        annot.set_colors(stroke=color, fill=color)
        annot.set_border(width=width)
        annot.set_opacity(opacity)
        annot.update()
        logger.debug("Added polygon annotation on page %d (xref=%d)", page_num, annot.xref)
        return annot.xref

    def apply_ink_annot(
        self, page_num: int, strokes: list, color: list, width: float, opacity: float
    ) -> int:
        page = self._doc[page_num]
        raw_strokes = [[(pt[0], pt[1]) for pt in stroke] for stroke in strokes]
        annot = page.add_ink_annot(raw_strokes)
        annot.set_colors(stroke=color)
        annot.set_border(width=width)
        annot.set_opacity(opacity)
        annot.update()
        logger.debug("Added ink annotation on page %d (xref=%d)", page_num, annot.xref)
        return annot.xref

    def apply_rect_annot(
        self, page_num: int, rect: list, color: list, width: float
    ) -> int:
        """Add a rectangle annotation to a page.

        Args:
            page_num: Zero-based page index.
            rect: Rectangle coordinates [x0, y0, x1, y1].
            color: RGB stroke color values [r, g, b] (0.0-1.0).
            width: Border width in points.

        Returns:
            The xref (cross-reference number) of the created annotation.
        """
        page = self._doc[page_num]
        annot = page.add_rect_annot(fitz.Rect(rect))
        annot.set_colors(stroke=tuple(color))
        annot.set_border(width=width)
        annot.update()
        logger.debug("Added rectangle annotation on page %d (xref=%d)", page_num, annot.xref)
        return annot.xref

    def delete_annotation(self, page_num: int, xref: int) -> None:
        """Delete an annotation by its xref.

        Args:
            page_num: Zero-based page index.
            xref: The cross-reference number of the annotation to delete.
        """
        page = self._doc[page_num]
        try:
            annot = page.load_annot(xref)
        except Exception:
            # xref may have been invalidated by a prior delete+recreate cycle
            logger.warning("delete_annotation: xref %d not found on page %d", xref, page_num)
            return
        if annot:
            page.delete_annot(annot)
            logger.debug("Deleted annotation on page %d (xref=%d)", page_num, xref)

    # ── text operations ───────────────────────────────────────────────────────

    def apply_text_insert(
        self,
        page_num: int,
        rect: list,
        text: str,
        fontsize: float = 12,
        font_name: str = "helv",
        color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        """Insert text into the document.

        Args:
            page_num: Zero-based page index.
            rect: Bounding rectangle [x0, y0, x1, y1] for text placement.
            text: The text to insert.
            fontsize: Font size in points.
            font_name: Font name or family identifier.
            color: RGB color tuple (0.0-1.0).
        """
        font = self._resolve_font(page_num, font_name, text)
        page = self._doc[page_num]
        tw = fitz.TextWriter(page.rect)
        # baseline = top of rect + fontsize
        tw.append((rect[0], rect[1] + fontsize), text, font=font, fontsize=fontsize)
        tw.write_text(page, color=color)
        logger.debug("Inserted text on page %d: %r", page_num, text[:50])

    def apply_text_move(
        self,
        page_num: int,
        src_bbox: list,
        current_origin: list,
        new_origin: list,
        text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
    ) -> list:
        """Move text from one position to another on the page.

        Redacts the source area, reinserts spans that disappeared, and places
        the text at the new origin.

        Args:
            page_num: Zero-based page index.
            src_bbox: Source bounding box [x0, y0, x1, y1].
            current_origin: Current text origin [x, y].
            new_origin: New text origin [x, y].
            text: The text content to move.
            fontsize: Font size in points.
            font_name: Font name or family.
            color: RGB color tuple (0.0-1.0).

        Returns:
            The actual bounding box [x0, y0, x1, y1] of the inserted text.
        """
        font = self._resolve_font(page_num, font_name, text)
        page = self._doc[page_num]
        src_rect = fitz.Rect(src_bbox)
        ox, oy = current_origin[0], current_origin[1]

        # Snapshot all spans before redaction
        def _get_spans(pg: fitz.Page) -> list[dict]:
            spans = []
            for block in pg.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    spans.extend(line["spans"])
            return spans

        def _span_key(s: dict) -> tuple:
            return (round(s["origin"][0], 1), round(s["origin"][1], 1), s["text"])

        spans_before = _get_spans(page)
        keys_before = {_span_key(s): s for s in spans_before}

        page.add_redact_annot(src_rect)
        # Only wipe text in the source area — keep images/drawings/annots beneath.
        page.apply_redactions(images=0, graphics=0, text=0)

        keys_after = {_span_key(s) for s in _get_spans(page)}

        # Reinsert spans that actually disappeared, except the moved span itself.
        # Identify the moved span by text+origin match to avoid falsely suppressing
        # an unrelated span that merely sits near the source origin.
        for key, span in keys_before.items():
            if key in keys_after:
                continue  # survived redaction — do not duplicate
            sx, sy = span["origin"]
            if span["text"] == text and abs(sx - ox) < 0.5 and abs(sy - oy) < 0.5:
                continue  # this is the moved span — intentionally removed
            c = span["color"]
            sc = (
                ((c >> 16) & 0xFF) / 255.0,
                ((c >> 8) & 0xFF) / 255.0,
                (c & 0xFF) / 255.0,
            )
            sf = self._resolve_font(page_num, span["font"], span["text"])
            stw = fitz.TextWriter(page.rect)
            stw.append(fitz.Point(sx, sy), span["text"], font=sf, fontsize=span["size"])
            stw.write_text(page, color=sc)

        tw = fitz.TextWriter(page.rect)
        text_rect, _ = tw.append(
            fitz.Point(new_origin[0], new_origin[1]),
            text,
            font=font,
            fontsize=fontsize,
        )
        tw.write_text(page, color=color)
        return [text_rect.x0, text_rect.y0, text_rect.x1, text_rect.y1]

    def get_span_font_bytes(self, page_num: int, font_name: str) -> bytes | None:
        """Return embedded font bytes for font_name, or None if not embedded."""
        page = self._doc[page_num]
        clean = font_name.split("+")[-1].lower().replace(" ", "")

        for font_info in page.get_fonts():
            # page.get_fonts() tuple layout: (xref, ext, type, basefont, name, enc, referencer)
            xref = font_info[0]
            basefont = font_info[3]  # PDF /BaseFont — e.g. "Courier-Bold"
            fname = font_info[4]     # font name field — e.g. "CourierNewPS-BoldMT"
            candidate = (basefont or fname or "").split("+")[-1].lower().replace(" ", "")
            if not candidate or candidate != clean:
                continue
            try:
                _, _, _, font_data, _ = self._doc.extract_font(xref)
                if font_data:
                    logger.debug("Font '%s' loaded from PDF embedding", font_name)
                    return font_data
            except Exception as e:
                logger.debug("extract_font(xref=%d) failed: %s", xref, e)

        return None

    def apply_text_edit(
        self,
        page_num: int,
        span_bbox: tuple | list,
        span_origin: tuple | list,
        new_text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
        font_bytes: bytes | None = None,
    ) -> list:
        """Edit existing text by replacing it with new text.

        Args:
            page_num: Zero-based page index.
            span_bbox: Bounding box of the original text span.
            span_origin: Origin point of the original text.
            new_text: Replacement text.
            fontsize: Font size in points.
            font_name: Font name or family.
            color: RGB color tuple (0.0-1.0).

        Returns:
            The actual bounding box [x0, y0, x1, y1] of the inserted text for undo tracking.
        """
        # Resolve font BEFORE redacting: the span's font is still in the page
        # resource dict here.  After apply_redactions() the resource might be
        # unreferenced and harder to find by name.
        if font_bytes:
            try:
                font = fitz.Font(fontbuffer=font_bytes)
            except Exception:
                # fontbuffer fails for Type1 or malformed streams — fall back
                # to name-based resolution which hits the embedded-font lookup
                # while the page resource dict is still intact.
                font = self._resolve_font(page_num, font_name, new_text)
        else:
            font = self._resolve_font(page_num, font_name, new_text)
        page = self._doc[page_num]
        page.add_redact_annot(fitz.Rect(span_bbox))
        page.apply_redactions(images=0, graphics=0, text=0)
        tw = fitz.TextWriter(page.rect)
        text_rect, _ = tw.append(
            fitz.Point(span_origin[0], span_origin[1]),
            new_text,
            font=font,
            fontsize=fontsize,
        )
        tw.write_text(page, color=color)
        return [text_rect.x0, text_rect.y0, text_rect.x1, text_rect.y1]

    ANNOT_TEXT_MARKER = "PDFTOOL_ANNOT_TEXT"

    def _render_annot_text(
        self,
        page_num: int,
        rect: list,
        text: str,
        fontsize: float,
        color: tuple[float, float, float],
    ) -> None:
        """Draw annotation text into the page using Architects Daughter
        embedded via fontbuffer (so the font travels with the PDF). Falls
        back to Helvetica when the font is not installed.
        """
        from tools.annotation_text import find_annotation_font_path
        page = self._doc[page_num]
        font: fitz.Font | None = None
        font_path = find_annotation_font_path()
        if font_path is not None:
            try:
                font = fitz.Font(fontbuffer=font_path.read_bytes())
            except Exception as e:
                logger.debug("Annotation font load failed (%s): %s", font_path, e)
                font = None
        if font is None:
            font = self._resolve_font(page_num, "helv", text)
        tw = fitz.TextWriter(page.rect)
        tw.fill_textbox(fitz.Rect(rect), text, font=font, fontsize=fontsize, align=0)
        tw.write_text(page, color=color)

    def apply_annotation_text(
        self,
        page_num: int,
        rect: list,
        text: str,
        fontsize: float,
        color: tuple[float, float, float],
    ) -> int:
        """Insert annotation text: render the text into the page with the
        embedded Architects Daughter font, plus an invisible Square annot as
        a marker so SelectTool can recognise the block for move/resize/edit.

        Marker carries metadata in /T (title) and /Contents:
          - subject = ANNOT_TEXT_MARKER
          - title  = "size=<fontsize>;color=<r>,<g>,<b>"
          - content = original text
        Returns the marker annot xref.
        """
        self._render_annot_text(page_num, rect, text, fontsize, color)
        page = self._doc[page_num]
        annot = page.add_rect_annot(fitz.Rect(rect))
        try:
            annot.set_border(width=0)
        except Exception as e:
            logger.debug("annot.set_border(0) failed: %s", e)
        try:
            annot.set_colors(stroke=None, fill=None)
        except Exception as e:
            logger.debug("annot.set_colors(None) failed: %s", e)
        try:
            annot.set_opacity(0.0)
        except Exception as e:
            logger.debug("annot.set_opacity(0) failed: %s", e)
        r, g, b = color
        annot.set_info(
            title=f"size={fontsize};color={r:.6f},{g:.6f},{b:.6f}",
            content=text,
            subject=self.ANNOT_TEXT_MARKER,
        )
        annot.update()
        return annot.xref

    def apply_paragraph_edit(
        self,
        page_num: int,
        orig_bbox: list,
        new_text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
        font_bytes: bytes | None = None,
    ) -> list:
        """Replace a paragraph (block) with new multi-line text.

        Wipes the original block bbox, then renders new_text inside a rect
        spanning from the block's top-left to the page bottom (so longer
        replacements don't overflow). Returns the actual rendered bbox for
        undo tracking.
        """
        if font_bytes:
            try:
                font = fitz.Font(fontbuffer=font_bytes)
            except Exception:
                font = self._resolve_font(page_num, font_name, new_text)
        else:
            font = self._resolve_font(page_num, font_name, new_text)
        page = self._doc[page_num]
        page.add_redact_annot(fitz.Rect(orig_bbox))
        page.apply_redactions(images=0, graphics=0, text=0)

        x0, y0, x1, _ = orig_bbox
        fill_rect = fitz.Rect(x0, y0, x1, page.rect.y1)
        tw = fitz.TextWriter(page.rect)
        tw.fill_textbox(fill_rect, new_text, font=font, fontsize=fontsize, align=0)
        tw.write_text(page, color=color)
        r = tw.text_rect
        return [r.x0, r.y0, r.x1, r.y1]

    def apply_paragraph_replay(
        self,
        page_num: int,
        redact_bbox: list,
        lines: list,
    ) -> list:
        """Wipe redact_bbox and re-render a paragraph line-by-line at original
        origins/styles. Used by EditParagraphCmd.undo to restore the source.
        Returns the union bbox of replayed lines.
        """
        page = self._doc[page_num]
        page.add_redact_annot(fitz.Rect(redact_bbox))
        page.apply_redactions(images=0, graphics=0, text=0)
        union: fitz.Rect | None = None
        for ln in lines:
            font = self._resolve_font(page_num, ln["font"], ln["text"])
            tw = fitz.TextWriter(page.rect)
            text_rect, _ = tw.append(
                fitz.Point(ln["origin"][0], ln["origin"][1]),
                ln["text"], font=font, fontsize=ln["size"],
            )
            tw.write_text(page, color=tuple(ln["color"]))
            union = text_rect if union is None else union | text_rect
        if union is None:
            return list(redact_bbox)
        return [union.x0, union.y0, union.x1, union.y1]

    def apply_image_move(
        self,
        page_num: int,
        xref: int,
        src_rect: list,
        dst_rect: list,
        image_bytes: bytes,
    ) -> None:
        """Move an image from src_rect to dst_rect by wiping source and re-inserting."""
        page = self._doc[page_num]
        # Insert at destination FIRST so the image has two placements in the stream.
        # Then redact only the source rect — images=1 removes image references in that
        # area only, leaving the destination placement intact.
        # fill=None: no white paint over src, so text/graphics beneath remain visible.
        # text=1: don't erase text in src area.  graphics=0: don't erase drawings.
        page.insert_image(fitz.Rect(dst_rect), stream=image_bytes)
        page.add_redact_annot(fitz.Rect(src_rect), fill=None)
        page.apply_redactions(images=1, graphics=0, text=1)

    def get_image_bytes(self, xref: int) -> bytes | None:
        """Return raw image bytes for a given xref, or None if not extractable."""
        try:
            info = self._doc.extract_image(xref)
            return info.get("image") if info else None
        except Exception as e:
            logger.debug("extract_image(xref=%d) failed: %s", xref, e)
            return None

    def apply_drawing_move(
        self,
        page_num: int,
        drawing: dict,
        dx: float,
        dy: float,
    ) -> dict:
        """Translate a vector drawing by (dx, dy). Returns shifted drawing dict."""
        page = self._doc[page_num]
        from tools._drawing_surgery import strip_drawing
        if not strip_drawing(self._doc, page, drawing):
            # strip_drawing failed — fall back to area redact of the drawing bbox
            r = fitz.Rect(drawing["rect"])
            page.add_redact_annot(r, fill=None)
            page.apply_redactions(images=0, graphics=1, text=1)
        shifted = _shift_drawing(drawing, dx, dy)
        _render_drawing(page, shifted)
        return shifted

    def _resolve_font(
        self, page_num: int, font_name: str, text: str = ""
    ) -> fitz.Font:
        """Backward-compat wrapper around core.fonts.resolve_font."""
        return resolve_font(self._doc, page_num, font_name, text)

    # ── page operations ───────────────────────────────────────────────────────

    def insert_blank_page(self, index: int, width: float | None = None, height: float | None = None) -> int:
        """Insert a blank page at the specified index.

        If width and height are not specified, uses the dimensions of the
        first existing page (or A4 if document is empty).

        Args:
            index: Zero-based index where the new page should be inserted.
            width: Page width in points (optional).
            height: Page height in points (optional).

        Returns:
            The index of the newly inserted page.
        """
        if width is None or height is None:
            if len(self._doc) > 0:
                # Use first page dimensions
                ref_page = self._doc[0]
                width = width or ref_page.rect.width
                height = height or ref_page.rect.height
            else:
                # Default to A4
                width = width or 595
                height = height or 842

        self._doc.insert_page(index, width=width, height=height)
        logger.info("Inserted blank page at index %d (%fx%f)", index, width, height)
        return index

    def delete_page(self, index: int) -> None:
        """Delete a page at the specified index.

        Args:
            index: Zero-based index of the page to delete.
        """
        self._doc.delete_page(index)
        logger.info("Deleted page at index %d", index)

    def move_page(self, from_index: int, to_index: int) -> int:
        """Move a page from one position to another.

        Args:
            from_index: Current zero-based index of the page.
            to_index: Target zero-based index for the page (insert-before semantics).

        Returns:
            The final zero-based index of the moved page after the operation.
            Forward moves land at to_index - 1 because the page is removed first.
        """
        self._doc.move_page(from_index, to_index)
        final_index = to_index - 1 if to_index > from_index else to_index
        logger.info("Moved page from %d to %d (final %d)", from_index, to_index, final_index)
        return final_index

    def get_page_size(self, page_num: int) -> tuple[float, float]:
        """Get the dimensions of a page.

        Args:
            page_num: Zero-based page index.

        Returns:
            Tuple of (width, height) in points.
        """
        page = self._doc[page_num]
        return (page.rect.width, page.rect.height)

    def resize_page(self, page_num: int, new_w: float, new_h: float, content_mode: str) -> None:
        """Resize page to new_w × new_h points.

        content_mode:
          "scale" — scale content to fill new dimensions (flattens to XObject)
          "keep"  — keep content at original coords; page box changes only
          "crop"  — same as keep (new mediabox clips anything outside)
        """
        page = self._doc[page_num]
        new_rect = fitz.Rect(0, 0, new_w, new_h)

        if content_mode == "scale":
            snap = fitz.open()
            snap.insert_pdf(self._doc, from_page=page_num, to_page=page_num)
            # Clear annotations so they are not doubled after show_pdf_page
            for annot in list(page.annots()):
                page.delete_annot(annot)
            # Clear content streams
            page.clean_contents()
            for xref in page.get_contents():
                self._doc.update_stream(xref, b"")
            page.set_mediabox(new_rect)
            page.show_pdf_page(new_rect, snap, 0)
            snap.close()
        else:
            page.set_mediabox(new_rect)

    def rotate_page(self, page_num: int, delta: int) -> None:
        """Rotate page by delta degrees (cumulative, multiple of 90)."""
        page = self._doc[page_num]
        page.set_rotation((page.rotation + delta) % 360)

    # ── persist ───────────────────────────────────────────────────────────────

    def save(self, output_path: Path) -> None:
        """Save the document atomically to a file.

        Writes to a temp file in the destination directory, then atomically
        replaces the target. Survives crashes and supports in-place saves
        (fitz refuses direct writes when output_path == self.path).

        Args:
            output_path: Path where the PDF should be saved.
        """
        output_path = Path(output_path)
        output_dir = output_path.parent
        output_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.", suffix=".tmp", dir=output_dir
        )
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            self._doc.save(str(tmp_path), garbage=1, deflate=True)
            os.replace(tmp_path, output_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception as cleanup_exc:
                logger.debug("Failed to clean tmp save file %s: %s", tmp_path, cleanup_exc)
            raise
        logger.info("Saved PDF to: %s", output_path)

    def close(self) -> None:
        """Close the document and release resources."""
        self._doc.close()
        logger.info("Closed PDF document: %s", self.path)
