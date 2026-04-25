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
            self._xref = doc.apply_highlight(
                self._page_num, self._data["quads"],
                color=self._data.get("color"),
            )
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
    """Move an image, preserving sibling images that share the same page area."""

    def __init__(self, page_num: int, xref: int,
                 src_rect: list, dst_rect: list,
                 image_bytes: bytes,
                 siblings: "list[tuple]") -> None:
        self._page_num = page_num
        self._xref = xref
        self._src_rect = list(src_rect)
        self._dst_rect = list(dst_rect)
        self._bytes = image_bytes
        self._siblings = siblings  # list of (fitz.Rect, bytes)

    def _apply(self, doc: "PDFDocument", wipe_rect: list, place_rect: list) -> None:
        page = doc.get_page(self._page_num)
        page.insert_image(fitz.Rect(place_rect), stream=self._bytes, overlay=True)
        page.add_redact_annot(fitz.Rect(wipe_rect), fill=None)
        # text=1: keep text; graphics=0: keep drawings; images=1: remove image refs in area
        page.apply_redactions(images=1, graphics=0, text=1)
        for r, b in self._siblings:
            page.insert_image(r, stream=b, overlay=True)

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
        self._redo_stack.clear()

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
