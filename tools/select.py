from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPen
from PyQt6.QtWidgets import QGraphicsRectItem

from core.history import DeleteAnnotCmd, MoveAnnotCmd, MoveTextCmd, _capture_annot
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

_HIT_TOLERANCE = 5  # PDF points of extra hit area around annotation rects


@dataclass
class _Selection:
    page_num: int
    obj_type: str          # 'annot' | 'text' | 'image' | 'drawing'
    pdf_rect: fitz.Rect
    xref: int | None       # annotation / image xref
    snap: dict | None      # full annotation snapshot (for undo of delete)
    span: dict | None      # text span dict (obj_type='text')
    drawing: dict | None = None  # get_drawings() entry (obj_type='drawing')
    drag_start_pdf: fitz.Point | None = None
    overlay: QGraphicsRectItem | None = None


class SelectTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._sel: _Selection | None = None
        self._dragging = False

    # ── mouse ─────────────────────────────────────────────────────────────────

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        self._clear_overlay()
        obj = self._hit_test(page_num, pdf_pos)
        if obj is None:
            self._sel = None
            return
        self._sel = obj
        self._sel.drag_start_pdf = pdf_pos
        self._dragging = True
        self._show_overlay(obj.page_num, obj.pdf_rect)

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if not self._dragging or self._sel is None or self._sel.drag_start_pdf is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        dx = pdf_pos.x - self._sel.drag_start_pdf.x
        dy = pdf_pos.y - self._sel.drag_start_pdf.y
        moved = fitz.Rect(
            self._sel.pdf_rect.x0 + dx, self._sel.pdf_rect.y0 + dy,
            self._sel.pdf_rect.x1 + dx, self._sel.pdf_rect.y1 + dy,
        )
        if self._sel.overlay:
            self._sel.overlay.setRect(self._pdf_rect_to_scene(self._sel.page_num, moved))

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if not self._dragging or self._sel is None or self._sel.drag_start_pdf is None:
            self._dragging = False
            return
        dx = pdf_pos.x - self._sel.drag_start_pdf.x
        dy = pdf_pos.y - self._sel.drag_start_pdf.y
        if abs(dx) > 2 or abs(dy) > 2:
            new_rect = fitz.Rect(
                self._sel.pdf_rect.x0 + dx, self._sel.pdf_rect.y0 + dy,
                self._sel.pdf_rect.x1 + dx, self._sel.pdf_rect.y1 + dy,
            )
            self._apply_move(new_rect, dx, dy)
        self._dragging = False

    # ── keyboard ──────────────────────────────────────────────────────────────

    def on_key(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._sel:
            self._apply_delete()

    # ── cancel ────────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        self._clear_overlay()
        self._sel = None
        self._dragging = False

    # ── hit test ──────────────────────────────────────────────────────────────

    def _hit_test(self, page_num: int, pdf_pos: fitz.Point) -> _Selection | None:
        doc = self.canvas.document
        if doc is None:
            return None
        page = doc.get_page(page_num)

        # annotations first — inflate rect for easier clicking
        for annot in page.annots():
            r = annot.rect
            hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                               r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
            if hit_r.contains(pdf_pos):
                snap = _capture_annot(annot)
                return _Selection(
                    page_num=page_num,
                    obj_type="annot",
                    pdf_rect=fitz.Rect(r),
                    xref=annot.xref,
                    snap=snap,
                    span=None,
                )

        # raster images — pick smallest containing bbox (avoids large background images)
        best_img_area = float("inf")
        best_img: tuple[fitz.Rect, int] | None = None
        for img in page.get_image_info(xrefs=True):
            xref = img.get("xref", 0)
            if not xref:
                continue
            r = fitz.Rect(img["bbox"])
            if r.is_empty:
                continue
            hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                               r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
            if hit_r.contains(pdf_pos):
                area = r.width * r.height
                if area < best_img_area:
                    best_img_area = area
                    best_img = (r, xref)
        if best_img is not None:
            r, xref = best_img
            return _Selection(
                page_num=page_num,
                obj_type="image",
                pdf_rect=r,
                xref=xref,
                snap=None,
                span=None,
            )

        # vector drawings — pick smallest containing bbox
        best_drw_area = float("inf")
        best_drw: tuple[fitz.Rect, dict] | None = None
        for drw in page.get_drawings():
            r = fitz.Rect(drw["rect"])
            if r.is_empty:
                continue
            hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                               r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
            if hit_r.contains(pdf_pos):
                area = r.width * r.height
                if area < best_drw_area:
                    best_drw_area = area
                    best_drw = (r, drw)
        if best_drw is not None:
            r, drw = best_drw
            return _Selection(
                page_num=page_num,
                obj_type="drawing",
                pdf_rect=r,
                xref=None,
                snap=None,
                span=None,
                drawing=drw,
            )

        # text spans — checked last: span bboxes often overlap images/drawings
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    r = fitz.Rect(span["bbox"])
                    hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                                      r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
                    if hit_r.contains(pdf_pos):
                        return _Selection(
                            page_num=page_num,
                            obj_type="text",
                            pdf_rect=r,
                            xref=None,
                            snap=None,
                            span=span,
                        )

        return None

    # ── overlay ───────────────────────────────────────────────────────────────

    def _show_overlay(self, page_num: int, pdf_rect: fitz.Rect) -> None:
        pen = QPen(QColor(0, 120, 215), 1.5, Qt.PenStyle.DashLine)
        scene_rect = self._pdf_rect_to_scene(page_num, pdf_rect)
        item = self.canvas.scene().addRect(scene_rect, pen)
        item.setBrush(QColor(0, 120, 215, 25))
        if self._sel:
            self._sel.overlay = item

    def _clear_overlay(self) -> None:
        if self._sel and self._sel.overlay:
            if self._sel.overlay.scene() is not None:
                self.canvas.scene().removeItem(self._sel.overlay)
            self._sel.overlay = None

    def _pdf_rect_to_scene(self, page_num: int, r: fitz.Rect) -> QRectF:
        tl = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x0, r.y0))
        br = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x1, r.y1))
        return QRectF(tl, br)

    # ── drawing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _redraw_drawing(page: fitz.Page, drw: dict, dx: float, dy: float) -> None:
        """Reconstruct a vector drawing shifted by (dx, dy)."""
        shape = page.new_shape()
        delta = fitz.Point(dx, dy)
        for item in drw.get("items", []):
            typ = item[0]
            if typ == "l":
                shape.draw_line(item[1] + delta, item[2] + delta)
            elif typ == "c":
                shape.draw_bezier(
                    item[1] + delta, item[2] + delta,
                    item[3] + delta, item[4] + delta,
                )
            elif typ == "re":
                r = item[1]
                shape.draw_rect(fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy))
            elif typ == "qu":
                q = item[1]
                shape.draw_quad(fitz.Quad(
                    q.ul + delta, q.ur + delta, q.ll + delta, q.lr + delta,
                ))
        shape.finish(
            color=drw.get("color"),
            fill=drw.get("fill"),
            width=drw.get("width") or 1,
            dashes=drw.get("dashes"),
            even_odd=drw.get("even_odd", False),
            closePath=drw.get("closePath", False),
        )
        shape.commit()

    # ── apply ops ─────────────────────────────────────────────────────────────

    def _apply_move(self, new_rect: fitz.Rect, dx: float, dy: float) -> None:
        sel = self._sel
        if sel is None or self.canvas.document is None:
            return
        doc = self.canvas.document

        if sel.obj_type == "annot" and sel.xref is not None and sel.snap is not None:
            old_verts = sel.snap["vertices"]
            new_verts = [(x + dx, y + dy) for x, y in old_verts] if old_verts else []
            cmd = MoveAnnotCmd(
                sel.page_num, sel.xref,
                list(sel.pdf_rect), old_verts,
                list(new_rect), new_verts,
            )
            self.canvas.push_command(cmd, doc)
            # update selection state
            sel.pdf_rect = new_rect
            if sel.snap:
                sel.snap = dict(sel.snap, rect=list(new_rect), vertices=new_verts)

        elif sel.obj_type == "image" and sel.xref is not None:
            try:
                img_data = doc._doc.extract_image(sel.xref)
                img_bytes = img_data.get("image")
                if img_bytes:
                    page = doc.get_page(sel.page_num)
                    page.add_redact_annot(sel.pdf_rect)
                    page.apply_redactions()
                    page.insert_image(new_rect, stream=img_bytes)
                    sel.pdf_rect = new_rect
            except Exception:
                pass

        elif sel.obj_type == "drawing" and sel.drawing is not None:
            page = doc.get_page(sel.page_num)
            page.add_redact_annot(sel.pdf_rect)
            page.apply_redactions()
            self._redraw_drawing(page, sel.drawing, dx, dy)
            sel.pdf_rect = new_rect
            # shift stored drawing rect so a second drag is correct
            r = sel.drawing["rect"]
            sel.drawing = dict(sel.drawing, rect=fitz.Rect(
                r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy,
            ))

        elif sel.obj_type == "text" and sel.span is not None:
            span = sel.span
            c = span["color"]
            color = ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0
            origin = span.get("origin", (sel.pdf_rect.x0, sel.pdf_rect.y1))
            new_origin = [origin[0] + dx, origin[1] + dy]
            cmd = MoveTextCmd(
                sel.page_num, list(sel.pdf_rect), list(origin), new_origin,
                span["text"], span["size"], span["font"], color,
            )
            self.canvas.push_command(cmd, doc)
            sel.pdf_rect = new_rect
            # keep span origin in sync so a second drag on same selection is correct
            sel.span = dict(span, origin=new_origin)

        self.canvas.refresh_page(sel.page_num)
        self._clear_overlay()
        self._show_overlay(sel.page_num, sel.pdf_rect)

    def _apply_delete(self) -> None:
        sel = self._sel
        if sel is None or self.canvas.document is None:
            return
        doc = self.canvas.document

        if sel.obj_type == "annot" and sel.snap is not None:
            cmd = DeleteAnnotCmd(sel.page_num, sel.snap)
            self.canvas.push_command(cmd, doc)

        elif sel.obj_type in ("text", "image", "drawing"):
            page = doc.get_page(sel.page_num)
            page.add_redact_annot(sel.pdf_rect)
            page.apply_redactions()

        self._clear_overlay()
        self._sel = None
        self.canvas.refresh_page(sel.page_num)
