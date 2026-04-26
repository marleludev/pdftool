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
    info = {}
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
    than by updating the xref directly.  fitz.Annot caches its geometry at
    load time, so xref_set_key() + annot.update() would regenerate the
    appearance stream from stale cached values — the annotation would snap
    back to its original position visually.  Recreating avoids the cache.
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
        # PDF_REDACT_IMAGE_REMOVE deletes every image placement whose bbox
        # touches the redact rect — backgrounds and overlapping images would
        # otherwise vanish. Skip the image being moved (bbox == wipe_r).
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

        # Redact source FIRST, then insert dst — protects dst from redaction
        # when src/dst overlap.
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


def _wipe_rect(page: fitz.Page, rect: list) -> None:
    page.add_redact_annot(fitz.Rect(rect))
    page.apply_redactions(images=0, graphics=0, text=0)


class AnnotationTextCmd(Command):
    """Insert annotation text: render the text into the page (with embedded
    Architects Daughter) and add an invisible Square marker for re-edit.
    Undo redacts the rect and removes the marker.
    """

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
            except Exception:
                pass


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
        except Exception:
            pass

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
        except Exception:
            pass

    def undo(self, doc: "PDFDocument") -> None:
        self._xref = doc.apply_annotation_text(
            self._page_num, self._rect, self._text, self._fontsize, self._color,
        )


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
        # Store the page before deleting
        page = doc.get_page(self._index)
        # Create a temporary document with just this page
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc.fitz_doc, from_page=self._index, to_page=self._index)
        self._page_bytes = temp_doc.tobytes()
        temp_doc.close()
        # Now delete the page
        doc.delete_page(self._index)

    def undo(self, doc: "PDFDocument") -> None:
        if self._page_bytes is None:
            return
        # Re-insert the page
        temp_doc = fitz.open(stream=self._page_bytes, filetype="pdf")
        doc.fitz_doc.insert_pdf(temp_doc, start_at=self._index)
        temp_doc.close()


class MovePageCmd(Command):
    """Move a page from one position to another; undo moves it back."""

    def __init__(self, from_index: int, to_index: int) -> None:
        self._from_index = from_index
        self._to_index = to_index

    def execute(self, doc: "PDFDocument") -> None:
        doc.move_page(self._from_index, self._to_index)

    def undo(self, doc: "PDFDocument") -> None:
        # Reverse the move
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
        # Snapshot page before resize for undo
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


class GroupCmd(Command):
    """Wrap multiple commands into one atomic undo/redo step."""

    def __init__(self, cmds: "list[Command]", page_num: int) -> None:
        self._cmds = cmds
        self._page_num = page_num

    def execute(self, doc: "PDFDocument") -> None:
        for cmd in self._cmds:
            cmd.execute(doc)

    def undo(self, doc: "PDFDocument") -> None:
        for cmd in reversed(self._cmds):
            cmd.undo(doc)


# ── history stack ─────────────────────────────────────────────────────────────

class History:
    def __init__(self, max_size: int = 500) -> None:
        self._undo_stack: deque[Command] = deque(maxlen=max_size)
        self._redo_stack: deque[Command] = deque(maxlen=max_size)

    def push(self, cmd: Command, doc: "PDFDocument") -> None:
        cmd.execute(doc)
        self._undo_stack.append(cmd)
        self._redo_stack.clear()  # any new action invalidates the redo branch

    def undo(self, doc: "PDFDocument") -> int | None:
        """Execute undo; return page_num of affected page, or -1 for page operations, or None if nothing to undo."""
        if not self._undo_stack:
            return None
        cmd = self._undo_stack.pop()
        cmd.undo(doc)
        self._redo_stack.append(cmd)
        # Return _page_num for content operations, -1 for page operations, None otherwise
        return getattr(cmd, "_page_num", -1 if hasattr(cmd, "_index") else None)

    def redo(self, doc: "PDFDocument") -> int | None:
        """Execute redo; return page_num of affected page, or -1 for page operations, or None if nothing to redo."""
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
