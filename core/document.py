from __future__ import annotations

import logging
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any

import fitz

logger = logging.getLogger(__name__)


def _needs_unicode(text: str) -> bool:
    """Check if text contains characters outside Latin-1 encoding."""
    try:
        text.encode("latin-1")
        return False
    except (UnicodeEncodeError, UnicodeDecodeError):
        return True


@lru_cache(maxsize=1)
def _find_unicode_font() -> str | None:
    """Find a system font that supports Unicode characters.

    Uses fc-match to find a suitable font, falling back to common system fonts.
    Result is cached to avoid repeated subprocess calls.

    Returns:
        Path to a suitable font file, or None if no font is found.
    """
    try:
        result = subprocess.run(
            ["fc-match", ":charset=20ac", "--format=%{file}"],
            capture_output=True,
            timeout=2,
        )
        path = result.stdout.decode().strip()
        if path and Path(path).exists():
            logger.debug("Found Unicode font via fc-match: %s", path)
            return path
    except Exception as e:
        logger.debug("fc-match failed: %s", e)

    # Fallback to common system fonts
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            logger.debug("Found Unicode font via fallback: %s", candidate)
            return candidate

    logger.warning("No Unicode font found")
    return None


BUILTIN_FONT_MAP = {
    "helv": ["helvetica", "arial", "arialmt", "helveticaneue"],
    "tiro": ["timesnewroman", "times", "timesroman"],
    "cour": ["courier", "couriernew"],
    "hebo": ["helvetica-bold", "arial-bold", "arialmt-bold"],
    "tibo": ["times-bold", "timesnewroman-bold"],
    "cobo": ["courier-bold", "couriernew-bold"],
    "heob": ["helvetica-oblique", "helvetica-italic", "arial-italic"],
    "tiit": ["times-italic", "timesnewroman-italic"],
}


def _int_to_rgb(c: int) -> tuple[float, float, float]:
    """Convert integer color to RGB float tuple."""
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _shift_point(p, dx: float, dy: float):
    if isinstance(p, fitz.Point):
        return fitz.Point(p.x + dx, p.y + dy)
    # tuple/list fallback
    return fitz.Point(p[0] + dx, p[1] + dy)


def _shift_drawing(drw: dict, dx: float, dy: float) -> dict:
    """Return a new drawing dict with all geometry translated by (dx, dy)."""
    new_items = []
    for it in drw.get("items", []):
        op = it[0]
        args = []
        for a in it[1:]:
            if isinstance(a, fitz.Point):
                args.append(fitz.Point(a.x + dx, a.y + dy))
            elif isinstance(a, fitz.Rect):
                args.append(fitz.Rect(a.x0 + dx, a.y0 + dy, a.x1 + dx, a.y1 + dy))
            elif isinstance(a, fitz.Quad):
                args.append(fitz.Quad(
                    fitz.Point(a.ul.x + dx, a.ul.y + dy),
                    fitz.Point(a.ur.x + dx, a.ur.y + dy),
                    fitz.Point(a.ll.x + dx, a.ll.y + dy),
                    fitz.Point(a.lr.x + dx, a.lr.y + dy),
                ))
            else:
                args.append(a)
        new_items.append((op, *args))
    r = fitz.Rect(drw["rect"])
    shifted = dict(drw)
    shifted["items"] = new_items
    shifted["rect"] = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
    return shifted


def _render_drawing(page: fitz.Page, drw: dict) -> None:
    """Render a drawing dict onto a page via fitz.Shape."""
    shape = page.new_shape()
    for it in drw.get("items", []):
        op = it[0]
        try:
            if op == "l":
                shape.draw_line(it[1], it[2])
            elif op == "re":
                shape.draw_rect(it[1])
            elif op == "qu":
                shape.draw_quad(it[1])
            elif op == "c":
                shape.draw_bezier(it[1], it[2], it[3], it[4])
            elif op == "v":
                # quadratic with implicit first control = start
                shape.draw_bezier(it[1], it[1], it[2], it[3])
            elif op == "y":
                shape.draw_bezier(it[1], it[2], it[3], it[3])
        except Exception:
            continue
    dtype = drw.get("type", "s")
    color = drw.get("color") if dtype in ("s", "fs", "sf") else None
    fill = drw.get("fill") if dtype in ("f", "fs", "sf") else None
    shape.finish(
        color=color,
        fill=fill,
        width=drw.get("width") or 1.0,
        closePath=drw.get("closePath", False),
        even_odd=drw.get("even_odd", False),
    )
    shape.commit()


def _builtin_for_name(name: str) -> str | None:
    """Map a font name to a built-in PDF font identifier."""
    clean = name.split("+")[-1].lower().replace(" ", "").replace("-", "")
    for key, aliases in BUILTIN_FONT_MAP.items():
        for alias in aliases:
            if alias.replace("-", "") in clean or clean in alias.replace("-", ""):
                return key
    return None


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

    def apply_highlight(self, page_num: int, quads: list) -> int:
        """Add a highlight annotation to a page.

        Args:
            page_num: Zero-based page index.
            quads: List of quadrilaterals defining the highlight areas.

        Returns:
            The xref (cross-reference number) of the created annotation.
        """
        page = self._doc[page_num]
        fitz_quads = [fitz.Quad(q) for q in quads]
        annot = page.add_highlight_annot(fitz_quads)
        logger.debug("Added highlight annotation on page %d (xref=%d)", page_num, annot.xref)
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
        annot = page.load_annot(xref)
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

    def apply_text_edit(
        self,
        page_num: int,
        span_bbox: tuple | list,
        span_origin: tuple | list,
        new_text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
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
        except Exception:
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
        """Resolve a font name to a fitz.Font object.

        Handles Unicode text, embedded fonts, and system font lookups.

        Args:
            page_num: Zero-based page index.
            font_name: Font name or family identifier.
            text: Optional text content to check for Unicode requirements.

        Returns:
            A fitz.Font object suitable for rendering the text.
        """
        if text and _needs_unicode(text):
            uf = _find_unicode_font()
            if uf:
                return fitz.Font(fontfile=uf)

        if font_name in BUILTIN_FONT_MAP:
            return fitz.Font(fontname=font_name)

        builtin = _builtin_for_name(font_name)
        if builtin:
            return fitz.Font(fontname=builtin)

        # Try embedded font — only TTF/OTF work with fitz.Font(fontbuffer=)
        page = self._doc[page_num]
        clean_name = font_name.split("+")[-1].lower()
        for xref, *_, name, _ in page.get_fonts():
            if not (name and name.lower().replace(" ", "") == clean_name.replace(" ", "")):
                continue
            try:
                _, ext, _, font_data, _ = self._doc.extract_font(xref)
                if font_data and ext in ("ttf", "otf"):
                    return fitz.Font(fontbuffer=font_data)
            except Exception as e:
                logger.debug("Failed to extract embedded font: %s", e)

        # System font via fc-match
        try:
            result = subprocess.run(
                ["fc-match", font_name, "--format=%{file}"],
                capture_output=True,
                timeout=2,
            )
            path = result.stdout.decode().strip()
            if path and Path(path).exists():
                return fitz.Font(fontfile=path)
        except Exception as e:
            logger.debug("fc-match for font %r failed: %s", font_name, e)

        # Ultimate fallback
        return fitz.Font(fontname="helv")

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
            to_index: Target zero-based index for the page.

        Returns:
            The new index of the moved page.
        """
        self._doc.move_page(from_index, to_index)
        logger.info("Moved page from %d to %d", from_index, to_index)
        return to_index if to_index < from_index else to_index

    def get_page_size(self, page_num: int) -> tuple[float, float]:
        """Get the dimensions of a page.

        Args:
            page_num: Zero-based page index.

        Returns:
            Tuple of (width, height) in points.
        """
        page = self._doc[page_num]
        return (page.rect.width, page.rect.height)

    # ── persist ───────────────────────────────────────────────────────────────

    def save(self, output_path: Path) -> None:
        """Save the document to a file.

        Args:
            output_path: Path where the PDF should be saved.
        """
        self._doc.save(str(output_path), garbage=4, deflate=True)
        logger.info("Saved PDF to: %s", output_path)

    def close(self) -> None:
        """Close the document and release resources."""
        self._doc.close()
        logger.info("Closed PDF document: %s", self.path)
