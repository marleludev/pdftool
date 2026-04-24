from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPen
from PyQt6.QtWidgets import QGraphicsRectItem

from core.history import _capture_annot
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas


@dataclass
class _SelectedObject:
    """Represents a selected object in multi-selection."""
    page_num: int
    obj_type: str
    pdf_rect: fitz.Rect
    xref: int | None
    snap: dict | None
    span: dict | None
    drawing: dict | None = None
    overlay: QGraphicsRectItem | None = None


class MultiSelectTool(AbstractTool):
    """Multi-selection tool that manages multiple selected objects.
    
    Features:
    - Visual highlighting of all selected objects
    - Move all selected together
    - Delete all selected together
    """

    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._selections: list[_SelectedObject] = []
        self._dragging: bool = False
        self._drag_start: fitz.Point | None = None
        self._drag_start_rects: list[fitz.Rect] = []

    def set_selections(self, selections: list[dict]) -> None:
        """Initialize with a list of selected objects."""
        self._clear_overlays()
        self._selections = []
        
        for sel_data in selections:
            sel = _SelectedObject(
                page_num=sel_data["page_num"],
                obj_type=sel_data["obj_type"],
                pdf_rect=fitz.Rect(sel_data["pdf_rect"]),
                xref=sel_data.get("xref"),
                snap=sel_data.get("snap"),
                span=sel_data.get("span"),
                drawing=sel_data.get("drawing"),
            )
            self._selections.append(sel)
            self._show_overlay(sel)

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Start dragging all selected objects."""
        if not self._selections:
            return
        
        self._dragging = True
        self._drag_start = pdf_pos
        self._drag_start_rects = [fitz.Rect(sel.pdf_rect) for sel in self._selections]

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Move all selected objects."""
        if not self._dragging or self._drag_start is None:
            return
        
        dx = pdf_pos.x - self._drag_start.x
        dy = pdf_pos.y - self._drag_start.y
        
        # Update all overlays
        for i, sel in enumerate(self._selections):
            if i < len(self._drag_start_rects):
                new_rect = fitz.Rect(
                    self._drag_start_rects[i].x0 + dx,
                    self._drag_start_rects[i].y0 + dy,
                    self._drag_start_rects[i].x1 + dx,
                    self._drag_start_rects[i].y1 + dy,
                )
                if sel.overlay:
                    sel.overlay.setRect(self._pdf_rect_to_scene(sel.page_num, new_rect))

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Apply move to all selected objects."""
        if not self._dragging or self._drag_start is None:
            return
        
        self._dragging = False
        dx = pdf_pos.x - self._drag_start.x
        dy = pdf_pos.y - self._drag_start.y
        
        # Only apply if significant movement
        if abs(dx) > 2 or abs(dy) > 2:
            self._apply_move_all(dx, dy)
        
        self._drag_start = None
        self._drag_start_rects = []

    def on_key(self, event: QKeyEvent) -> None:
        """Handle keyboard events."""
        key = event.key()
        
        # Delete = Delete all selected
        if key in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._delete_all()
            return

    def _apply_move_all(self, dx: float, dy: float) -> None:
        """Apply move operation to all selected objects as one atomic undo step."""
        if not self.canvas.document:
            return

        doc = self.canvas.document
        from core.history import (
            GroupCmd, MoveAnnotCmd, MoveTextCmd, MoveImageCmd, MoveDrawingCmd,
        )

        cmds: list = []
        page_num = self._selections[0].page_num if self._selections else 0

        for i, sel in enumerate(self._selections):
            if i >= len(self._drag_start_rects):
                continue

            old_rect = self._drag_start_rects[i]
            new_rect = fitz.Rect(
                old_rect.x0 + dx, old_rect.y0 + dy,
                old_rect.x1 + dx, old_rect.y1 + dy,
            )
            sel.pdf_rect = new_rect

            if sel.obj_type == "annot" and sel.xref is not None and sel.snap is not None:
                old_verts = sel.snap["vertices"]
                new_verts = [(x + dx, y + dy) for x, y in old_verts] if old_verts else []
                cmds.append(MoveAnnotCmd(
                    sel.page_num, sel.xref,
                    list(old_rect), old_verts,
                    list(new_rect), new_verts,
                ))
                sel.snap = dict(sel.snap, rect=list(new_rect), vertices=new_verts)

            elif sel.obj_type == "text" and sel.span is not None:
                span = sel.span
                c = span["color"]
                color = ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0
                origin = span.get("origin", (old_rect.x0, old_rect.y1))
                new_origin = [origin[0] + dx, origin[1] + dy]
                cmds.append(MoveTextCmd(
                    sel.page_num, list(old_rect), list(origin), new_origin,
                    span["text"], span["size"], span["font"], color,
                ))
                sel.span = dict(span, origin=new_origin)

            elif sel.obj_type == "image" and sel.xref is not None:
                img_bytes = doc.get_image_bytes(sel.xref)
                if img_bytes is not None:
                    cmds.append(MoveImageCmd(
                        sel.page_num, sel.xref,
                        list(old_rect), list(new_rect), img_bytes,
                    ))

            elif sel.obj_type == "drawing" and sel.drawing is not None:
                cmds.append(MoveDrawingCmd(sel.page_num, sel.drawing, dx, dy))

        if not cmds:
            return

        group = GroupCmd(cmds, page_num)
        # execute each sub-cmd directly so MoveDrawingCmd._drawing is updated
        # (GroupCmd.execute would call them, but we need sel.drawing synced too)
        for cmd, sel in zip(
            [c for c in cmds if hasattr(c, "_dx")],  # drawing cmds only
            [s for s in self._selections if s.obj_type == "drawing"],
        ):
            pass  # drawing sync handled below after push

        self.canvas.push_command(group, doc)

        # sync sel.drawing after GroupCmd.execute ran MoveDrawingCmd.execute
        drw_iter = (c for c in cmds if isinstance(c, MoveDrawingCmd))
        for sel in self._selections:
            if sel.obj_type == "drawing":
                drw_cmd = next(drw_iter, None)
                if drw_cmd is not None:
                    sel.drawing = drw_cmd._drawing
        
        # Refresh the page
        if self._selections:
            self.canvas.refresh_page(self._selections[0].page_num)

    def _delete_all(self) -> None:
        """Delete all selected objects."""
        if not self.canvas.document or not self._selections:
            return
        
        doc = self.canvas.document
        pages_to_refresh = set()
        
        for sel in self._selections:
            if sel.obj_type == "annot" and sel.snap is not None:
                from core.history import DeleteAnnotCmd
                cmd = DeleteAnnotCmd(sel.page_num, sel.snap)
                self.canvas.push_command(cmd, doc)
                pages_to_refresh.add(sel.page_num)
                
            elif sel.obj_type in ("text", "image"):
                page = doc.get_page(sel.page_num)
                page.add_redact_annot(sel.pdf_rect)
                page.apply_redactions()
                pages_to_refresh.add(sel.page_num)
                
            elif sel.obj_type == "drawing" and sel.drawing is not None:
                page = doc.get_page(sel.page_num)
                from tools._drawing_surgery import strip_drawing
                if not strip_drawing(doc._doc, page, sel.drawing):
                    page.add_redact_annot(sel.pdf_rect, fill=None)
                    page.apply_redactions(images=0, graphics=1, text=0)
                pages_to_refresh.add(sel.page_num)
        
        # Clear selections
        self._clear_overlays()
        self._selections = []
        
        # Refresh all affected pages
        for page_num in pages_to_refresh:
            self.canvas.refresh_page(page_num)
        
        # Return to default tool
        self.canvas.set_tool(None)

    def _show_overlay(self, sel: _SelectedObject) -> None:
        """Show selection overlay for an object."""
        pen = QPen(QColor(0, 120, 215), 1.5, Qt.PenStyle.DashLine)
        scene_rect = self._pdf_rect_to_scene(sel.page_num, sel.pdf_rect)
        item = self.canvas.scene().addRect(scene_rect, pen)
        item.setBrush(QColor(0, 120, 215, 25))
        sel.overlay = item

    def _clear_overlays(self) -> None:
        """Remove all selection overlays."""
        for sel in self._selections:
            if sel.overlay and sel.overlay.scene() is not None:
                self.canvas.scene().removeItem(sel.overlay)
                sel.overlay = None

    def _pdf_rect_to_scene(self, page_num: int, r: fitz.Rect):
        """Convert PDF rect to scene rect."""
        tl = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x0, r.y0))
        br = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x1, r.y1))
        return QRectF(tl, br)

    def cancel(self) -> None:
        """Cancel multi-selection."""
        self._clear_overlays()
        self._selections = []
        self._dragging = False
