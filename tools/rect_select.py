from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPen
from PyQt6.QtWidgets import QGraphicsRectItem

from core.history import _capture_annot
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas


class RectangleSelectTool(AbstractTool):
    """Rectangle selection tool with two modes based on drag direction.
    
    - Drag top-down (positive Y): Select objects completely INSIDE the rectangle
    - Drag bottom-up (negative Y): Select objects that INTERSECT/TOUCH the rectangle
    
    Selects MULTIPLE objects - all that match the criteria.
    """

    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._start_pdf: fitz.Point | None = None
        self._start_scene: QPointF | None = None
        self._page_num: int | None = None
        self._rubber: QGraphicsRectItem | None = None
        self._selection_mode: str = "inside"  # "inside" or "intersect"

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Start rectangle selection."""
        self._page_num = page_num
        self._start_pdf = pdf_pos
        self._start_scene = scene_pos
        
        # Create rubber band rectangle with dashed line
        pen = QPen(QColor(0, 120, 215), 1.5, Qt.PenStyle.DashLine)
        self._rubber = self.canvas.scene().addRect(QRectF(scene_pos, scene_pos), pen)
        self._rubber.setBrush(QColor(0, 120, 215, 30))

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Update rubber band rectangle and determine selection mode."""
        if self._rubber and self._start_scene:
            self._rubber.setRect(QRectF(self._start_scene, scene_pos).normalized())
            
            # Determine selection mode based on drag direction
            # Positive Y = dragging down = select INSIDE
            # Negative Y = dragging up = select INTERSECTING
            delta_y = scene_pos.y() - self._start_scene.y()
            if delta_y > 0:
                self._selection_mode = "inside"
                self._rubber.setBrush(QColor(0, 120, 215, 30))  # Blue tint
            else:
                self._selection_mode = "intersect"
                self._rubber.setBrush(QColor(255, 165, 0, 30))  # Orange tint

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        """Perform selection based on rectangle and mode."""
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None

        if self._start_pdf is None or self._page_num is None:
            return

        # Calculate selection rectangle in PDF coordinates
        r = fitz.Rect(
            min(self._start_pdf.x, pdf_pos.x), min(self._start_pdf.y, pdf_pos.y),
            max(self._start_pdf.x, pdf_pos.x), max(self._start_pdf.y, pdf_pos.y),
        )
        
        # Minimum selection size
        if r.width < 5 or r.height < 5:
            self._reset()
            return

        # Perform selection - select ALL matching objects
        if self.canvas.document:
            selected_objects = self._select_objects(self._page_num, r)
            if selected_objects:
                self._activate_multi_select(selected_objects)

        self._reset()

    def _select_objects(self, page_num: int, sel_rect: fitz.Rect) -> list[dict]:
        """Select ALL objects based on rectangle and current mode.
        
        Returns list of ALL selection dictionaries that match.
        """
        doc = self.canvas.document
        if doc is None:
            return []
        
        page = doc.get_page(page_num)
        selected = []
        
        # Check annotations
        for annot in page.annots():
            annot_rect = annot.rect
            if self._should_select(sel_rect, annot_rect):
                selected.append({
                    "page_num": page_num,
                    "obj_type": "annot",
                    "pdf_rect": fitz.Rect(annot_rect),
                    "xref": annot.xref,
                    "snap": _capture_annot(annot),
                    "span": None,
                })
        
        # Check images
        for img in page.get_image_info(xrefs=True):
            xref = img.get("xref", 0)
            if not xref:
                continue
            img_rect = fitz.Rect(img["bbox"])
            if img_rect.is_empty:
                continue
            if self._should_select(sel_rect, img_rect):
                selected.append({
                    "page_num": page_num,
                    "obj_type": "image",
                    "pdf_rect": img_rect,
                    "xref": xref,
                    "snap": None,
                    "span": None,
                })
        
        # Check vector drawings
        page_area = page.rect.width * page.rect.height
        for drw in page.get_drawings():
            drw_rect = fitz.Rect(drw["rect"])
            if drw_rect.is_empty:
                continue
            # Skip background drawings (>50% of page)
            if drw_rect.width * drw_rect.height > page_area * 0.5:
                continue
            # Skip white drawings (erase marks)
            c = drw.get("color")
            if c is not None and all(v >= 0.99 for v in c):
                continue
            if self._should_select(sel_rect, drw_rect):
                selected.append({
                    "page_num": page_num,
                    "obj_type": "drawing",
                    "pdf_rect": drw_rect,
                    "xref": None,
                    "snap": None,
                    "span": None,
                    "drawing": drw,
                })
        
        # Check text spans
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    span_rect = fitz.Rect(span["bbox"])
                    if self._should_select(sel_rect, span_rect):
                        selected.append({
                            "page_num": page_num,
                            "obj_type": "text",
                            "pdf_rect": span_rect,
                            "xref": None,
                            "snap": None,
                            "span": span,
                        })
        
        return selected

    def _should_select(self, sel_rect: fitz.Rect, obj_rect: fitz.Rect) -> bool:
        """Determine if object should be selected based on mode.
        
        - inside mode: object must be completely inside selection rectangle
        - intersect mode: object must intersect or touch selection rectangle
        """
        if self._selection_mode == "inside":
            # Object completely inside selection
            return sel_rect.contains(obj_rect)
        else:  # intersect mode
            # Object intersects or touches selection
            return sel_rect.intersects(obj_rect)

    def _activate_multi_select(self, selected_objects: list[dict]) -> None:
        """Switch to multi-select tool with all selected objects."""
        from tools.multi_select import MultiSelectTool
        
        if not selected_objects:
            return
        
        multi_tool = MultiSelectTool(self.canvas)
        multi_tool.set_selections(selected_objects)
        
        self.canvas.set_tool(multi_tool)

    def cancel(self) -> None:
        """Cancel the selection operation."""
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None
        self._reset()

    def _reset(self) -> None:
        """Reset internal state."""
        self._start_pdf = None
        self._start_scene = None
        self._page_num = None
        self._selection_mode = "inside"
