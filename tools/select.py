from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPen
from PyQt6.QtWidgets import QGraphicsRectItem

from core.history import DeleteAnnotCmd, MoveAnnotCmd, MoveTextCmd, _capture_annot
from tools._drawing_surgery import strip_drawing
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

def _shift_verts(verts: list, dx: float, dy: float) -> list:
    """Translate vertices by (dx, dy). Handles flat and nested (ink) formats."""
    if not verts:
        return []
    if isinstance(verts[0], list):  # ink: list of strokes
        return [[(pt[0] + dx, pt[1] + dy) for pt in stroke] for stroke in verts]
    return [(pt[0] + dx, pt[1] + dy) for pt in verts]


_HIT_TOLERANCE = 5        # PDF points of extra hit area around object rects
_TEXT_HIT_TOLERANCE = 2  # tighter tolerance for text spans (bboxes tend to overlap)
_DRAG_THRESHOLD = 3       # PDF points of movement before drag is confirmed


def _extract_image_bytes(doc: fitz.Document, xref: int) -> bytes | None:
    """Return PNG bytes for the xref, combining RGB with SMask alpha when present."""
    try:
        img_data = doc.extract_image(xref)
        raw = img_data.get("image")
        if raw is None:
            return None
        smask_xref = img_data.get("smask", 0)
        if not smask_xref:
            return raw
        # PDF stores alpha separately as SMask — reconstruct RGBA PNG
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.colorspace and pix.colorspace.n > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)  # strip alpha before re-adding
            alpha_pix = fitz.Pixmap(doc, smask_xref)
            if alpha_pix.colorspace and alpha_pix.colorspace.n != 1:
                alpha_pix = fitz.Pixmap(fitz.csGRAY, alpha_pix)
            if alpha_pix.alpha:
                alpha_pix = fitz.Pixmap(alpha_pix, 0)
            rgba_pix = fitz.Pixmap(pix, 1)  # correct API: adds opaque alpha channel
            rgba_pix.set_alpha(alpha_pix.samples)
            return rgba_pix.tobytes("png")
        except Exception:
            return raw  # fallback: image visible but without transparency
    except Exception:
        return None


_HANDLE_SIZE  = 8.0  # scene units for resize handle squares
_TL, _TR, _BR, _BL = 0, 1, 2, 3  # corner indices


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
        self._drag_confirmed = False  # True once movement exceeds _DRAG_THRESHOLD
        self._handles: list[QGraphicsRectItem] = []
        self._drag_handle: int | None = None
        self._drag_orig_rect: fitz.Rect | None = None
        self._orig_aspect: float = 1.0

    # ── mouse ─────────────────────────────────────────────────────────────────

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        # check resize handle hit first (only present for images)
        hi = self._handle_at(scene_pos)
        if hi is not None and self._sel is not None:
            self._drag_handle = hi
            self._drag_orig_rect = fitz.Rect(self._sel.pdf_rect)
            r = self._sel.pdf_rect
            self._orig_aspect = r.width / r.height if r.height else 1.0
            return

        self._clear_overlay()
        self._clear_handles()
        self._dragging = False
        self._drag_confirmed = False
        obj = self._hit_test(page_num, pdf_pos)
        if obj is None:
            self._sel = None
            return
        self._sel = obj
        self._sel.drag_start_pdf = pdf_pos
        self._dragging = True
        self._show_overlay(obj.page_num, obj.pdf_rect)
        if obj.obj_type == "image" or self._is_freetext(obj):
            self._show_handles(obj.page_num, obj.pdf_rect)

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._drag_handle is not None and self._sel is not None and self._drag_orig_rect is not None:
            new_rect = self._compute_resize_rect(pdf_pos, event)
            if self._sel.overlay:
                self._sel.overlay.setRect(self._pdf_rect_to_scene(self._sel.page_num, new_rect))
            self._update_handles(self._sel.page_num, new_rect)
            return
        if not self._dragging or self._sel is None or self._sel.drag_start_pdf is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        dx = pdf_pos.x - self._sel.drag_start_pdf.x
        dy = pdf_pos.y - self._sel.drag_start_pdf.y
        if not self._drag_confirmed:
            if dx * dx + dy * dy < _DRAG_THRESHOLD ** 2:
                return
            self._drag_confirmed = True
        moved = fitz.Rect(
            self._sel.pdf_rect.x0 + dx, self._sel.pdf_rect.y0 + dy,
            self._sel.pdf_rect.x1 + dx, self._sel.pdf_rect.y1 + dy,
        )
        if self._sel.overlay:
            self._sel.overlay.setRect(self._pdf_rect_to_scene(self._sel.page_num, moved))

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._drag_handle is not None and self._sel is not None and self._drag_orig_rect is not None:
            new_rect = self._compute_resize_rect(pdf_pos, event)
            if self._sel.obj_type == "image":
                self._apply_resize(new_rect)
            elif self._is_freetext(self._sel):
                self._apply_annot_resize(new_rect)
            self._drag_handle = None
            self._drag_orig_rect = None
            return
        if not self._dragging or self._sel is None or self._sel.drag_start_pdf is None:
            self._dragging = False
            self._drag_confirmed = False
            return
        dx = pdf_pos.x - self._sel.drag_start_pdf.x
        dy = pdf_pos.y - self._sel.drag_start_pdf.y
        if self._drag_confirmed and (abs(dx) > 2 or abs(dy) > 2):
            new_rect = fitz.Rect(
                self._sel.pdf_rect.x0 + dx, self._sel.pdf_rect.y0 + dy,
                self._sel.pdf_rect.x1 + dx, self._sel.pdf_rect.y1 + dy,
            )
            self._apply_move(new_rect, dx, dy)  # pushes undo command
        self._dragging = False
        self._drag_confirmed = False

    # ── keyboard ──────────────────────────────────────────────────────────────

    def on_key(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._sel:
            self._apply_delete()

    # ── cancel ────────────────────────────────────────────────────────────────

    def cancel(self) -> None:
        self._clear_overlay()
        self._clear_handles()
        self._sel = None
        self._dragging = False
        self._drag_confirmed = False
        self._drag_handle = None
        self._drag_orig_rect = None

    # ── hit test ──────────────────────────────────────────────────────────────

    def _hit_test(self, page_num: int, pdf_pos: fitz.Point) -> _Selection | None:
        doc = self.canvas.document
        if doc is None:
            return None
        page = doc.get_page(page_num)

        # Priority order: annotations > images > drawings > text.
        # Text is last because its bboxes overlap images and annotations in
        # almost every real document; clicking a highlight should select the
        # annotation, not the underlying text span.

        # annotations first — pick closest center among all hits (handles overlaps)
        best_annot_dist = float("inf")
        best_annot: _Selection | None = None
        for annot in page.annots():
            r = annot.rect
            hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                               r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
            if hit_r.contains(pdf_pos):
                cx = (r.x0 + r.x1) / 2
                cy = (r.y0 + r.y1) / 2
                dist = (pdf_pos.x - cx) ** 2 + (pdf_pos.y - cy) ** 2
                if dist < best_annot_dist:
                    best_annot_dist = dist
                    snap = _capture_annot(annot)
                    best_annot = _Selection(
                        page_num=page_num,
                        obj_type="annot",
                        pdf_rect=fitz.Rect(r),
                        xref=annot.xref,
                        snap=snap,
                        span=None,
                    )
        if best_annot is not None:
            return best_annot

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

        # vector drawings — pick smallest containing bbox, skip full-page backgrounds
        page_area = page.rect.width * page.rect.height
        best_drw_area = float("inf")
        best_drw: tuple[fitz.Rect, dict] | None = None
        for drw in page.get_drawings():
            r = fitz.Rect(drw["rect"])
            if r.is_empty:
                continue
            area = r.width * r.height
            if area > page_area * 0.5:  # skip full-page background fills (borders, shading)
                continue
            # skip white drawings — legacy erase-marks in older files
            c = drw.get("color")
            if c is not None and all(v >= 0.99 for v in c):
                continue
            hit_r = fitz.Rect(r.x0 - _HIT_TOLERANCE, r.y0 - _HIT_TOLERANCE,
                               r.x1 + _HIT_TOLERANCE, r.y1 + _HIT_TOLERANCE)
            if hit_r.contains(pdf_pos):
                if area <= best_drw_area:  # <= prefers later in stream (visible over ghost)
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
                    hit_r = fitz.Rect(r.x0 - _TEXT_HIT_TOLERANCE, r.y0 - _TEXT_HIT_TOLERANCE,
                                      r.x1 + _TEXT_HIT_TOLERANCE, r.y1 + _TEXT_HIT_TOLERANCE)
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

    # ── resize handles (images only) ──────────────────────────────────────────

    def _show_handles(self, page_num: int, pdf_rect: fitz.Rect) -> None:
        self._clear_handles()
        sr = self._pdf_rect_to_scene(page_num, pdf_rect)
        hs = _HANDLE_SIZE / 2
        for pt in (sr.topLeft(), sr.topRight(), sr.bottomRight(), sr.bottomLeft()):
            h = self.canvas.scene().addRect(
                QRectF(pt.x() - hs, pt.y() - hs, _HANDLE_SIZE, _HANDLE_SIZE),
                QPen(QColor(0, 120, 215), 1),
            )
            h.setBrush(QColor(255, 255, 255, 220))
            h.setZValue(10)
            self._handles.append(h)

    def _update_handles(self, page_num: int, pdf_rect: fitz.Rect) -> None:
        sr = self._pdf_rect_to_scene(page_num, pdf_rect)
        hs = _HANDLE_SIZE / 2
        for h, pt in zip(self._handles, (sr.topLeft(), sr.topRight(), sr.bottomRight(), sr.bottomLeft())):
            h.setRect(QRectF(pt.x() - hs, pt.y() - hs, _HANDLE_SIZE, _HANDLE_SIZE))

    def _clear_handles(self) -> None:
        for h in self._handles:
            if h.scene() is not None:
                self.canvas.scene().removeItem(h)
        self._handles.clear()

    def _handle_at(self, scene_pos: QPointF) -> int | None:
        tol = 3.0
        for i, h in enumerate(self._handles):
            if h.rect().adjusted(-tol, -tol, tol, tol).contains(scene_pos):
                return i
        return None

    def _compute_resize_rect(self, pdf_pos: fitz.Point, event: QMouseEvent) -> fitz.Rect:
        orig = self._drag_orig_rect
        hi = self._drag_handle
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        MIN = 10.0

        if hi == _TL:
            x0, y0, x1, y1 = pdf_pos.x, pdf_pos.y, orig.x1, orig.y1
        elif hi == _TR:
            x0, y0, x1, y1 = orig.x0, pdf_pos.y, pdf_pos.x, orig.y1
        elif hi == _BR:
            x0, y0, x1, y1 = orig.x0, orig.y0, pdf_pos.x, pdf_pos.y
        else:  # _BL
            x0, y0, x1, y1 = pdf_pos.x, orig.y0, orig.x1, pdf_pos.y

        # prevent inversion
        if x1 - x0 < MIN:
            x0 = x1 - MIN if hi in (_TL, _BL) else x0
            x1 = x0 + MIN if hi in (_TR, _BR) else x1
        if y1 - y0 < MIN:
            y0 = y1 - MIN if hi in (_TL, _TR) else y0
            y1 = y0 + MIN if hi in (_BR, _BL) else y1

        if shift:
            w = x1 - x0
            h_size = w / self._orig_aspect
            if hi in (_TL, _TR):
                y0 = y1 - h_size
            else:
                y1 = y0 + h_size

        return fitz.Rect(x0, y0, x1, y1)

    ANNOT_TEXT_MARKER = "PDFTOOL_ANNOT_TEXT"

    @classmethod
    def _is_annot_text(cls, sel: "_Selection") -> bool:
        return (sel.obj_type == "annot" and sel.snap is not None
                and sel.snap.get("subject") == cls.ANNOT_TEXT_MARKER)

    # Backwards-compat alias used by handle/overlay branches.
    _is_freetext = _is_annot_text

    @staticmethod
    def _parse_annot_text_meta(snap: dict) -> tuple[str, float, tuple[float, float, float]]:
        text = snap.get("content", "") or ""
        size = 12.0
        color = (0.0, 0.0, 0.0)
        title = snap.get("title", "") or ""
        for part in title.split(";"):
            if part.startswith("size="):
                try:
                    size = float(part[5:])
                except ValueError:
                    pass
            elif part.startswith("color="):
                try:
                    rgb = part[6:].split(",")
                    if len(rgb) == 3:
                        color = (float(rgb[0]), float(rgb[1]), float(rgb[2]))
                except ValueError:
                    pass
        return text, size, color

    def _apply_annot_resize(self, new_rect: fitz.Rect) -> None:
        sel = self._sel
        if sel is None or sel.xref is None or self.canvas.document is None:
            return
        if not self._is_annot_text(sel) or sel.snap is None:
            return
        text, fsize, color = self._parse_annot_text_meta(sel.snap)
        from core.history import TransformAnnotTextCmd
        cmd = TransformAnnotTextCmd(
            sel.page_num, sel.xref,
            list(sel.pdf_rect), list(new_rect),
            text, fsize, color,
        )
        self.canvas.push_command(cmd, self.canvas.document)
        sel.pdf_rect = new_rect
        sel.snap = dict(sel.snap, rect=list(new_rect))
        self.canvas.refresh_page(sel.page_num)
        self._clear_overlay()
        self._clear_handles()
        self._show_overlay(sel.page_num, sel.pdf_rect)
        self._show_handles(sel.page_num, sel.pdf_rect)

    def _apply_resize(self, new_rect: fitz.Rect) -> None:
        sel = self._sel
        if sel is None or sel.obj_type != "image" or sel.xref is None:
            return
        doc = self.canvas.document
        if doc is None:
            return
        img_bytes = _extract_image_bytes(doc._doc, sel.xref)
        if img_bytes is None:
            return
        page = doc.get_page(sel.page_num)
        siblings = self._capture_sibling_images(page, sel.pdf_rect, sel.xref, doc._doc)
        page.add_redact_annot(sel.pdf_rect, fill=None)
        page.apply_redactions(images=1, graphics=0, text=0)
        for r, b in siblings:
            page.insert_image(r, stream=b, overlay=True)
        page.insert_image(new_rect, stream=img_bytes)
        sel.pdf_rect = new_rect
        self.canvas.document_modified.emit()
        self.canvas.refresh_page(sel.page_num)
        self._clear_overlay()
        self._clear_handles()
        self._show_overlay(sel.page_num, sel.pdf_rect)
        self._show_handles(sel.page_num, sel.pdf_rect)

    def _pdf_rect_to_scene(self, page_num: int, r: fitz.Rect) -> QRectF:
        tl = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x0, r.y0))
        br = self.canvas.pdf_to_scene(page_num, fitz.Point(r.x1, r.y1))
        return QRectF(tl, br)

    # ── z-order ───────────────────────────────────────────────────────────────

    def set_image_zorder(self, to_back: bool) -> None:
        """Reinsert selected image with overlay=False (back) or overlay=True (front)."""
        sel = self._sel
        if sel is None or sel.obj_type != "image" or sel.xref is None:
            return
        doc = self.canvas.document
        if doc is None:
            return
        img_bytes = _extract_image_bytes(doc._doc, sel.xref)
        if img_bytes is not None:
            page = doc.get_page(sel.page_num)
            siblings = self._capture_sibling_images(page, sel.pdf_rect, sel.xref, doc._doc)
            page.add_redact_annot(sel.pdf_rect, fill=None)
            page.apply_redactions(images=1, graphics=0, text=0)
            for r, b in siblings:
                page.insert_image(r, stream=b, overlay=True)
            page.insert_image(sel.pdf_rect, stream=img_bytes, overlay=not to_back)
            self.canvas.document_modified.emit()
            self.canvas.refresh_page(sel.page_num)
            self._clear_overlay()
            self._clear_handles()
            self._show_overlay(sel.page_num, sel.pdf_rect)
            self._show_handles(sel.page_num, sel.pdf_rect)

    # ── drawing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _draw_items(shape: fitz.Shape, drw: dict, dx: float = 0.0, dy: float = 0.0) -> None:
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

    @staticmethod
    def _redraw_drawing(page: fitz.Page, drw: dict, dx: float, dy: float) -> None:
        """Reconstruct a vector drawing shifted by (dx, dy)."""
        shape = page.new_shape()
        SelectTool._draw_items(shape, drw, dx, dy)
        shape.finish(
            color=drw.get("color"),
            fill=drw.get("fill"),
            width=drw.get("width") or 1,
            dashes=drw.get("dashes"),
            even_odd=drw.get("even_odd", False),
            closePath=drw.get("closePath", False),
        )
        shape.commit()

    @staticmethod
    def _shift_drawing(drw: dict, dx: float, dy: float) -> dict:
        """Return copy of drw with all item coordinates shifted by (dx, dy)."""
        delta = fitz.Point(dx, dy)
        new_items = []
        for item in drw.get("items", []):
            typ = item[0]
            if typ == "l":
                new_items.append((typ, item[1] + delta, item[2] + delta) + item[3:])
            elif typ == "c":
                new_items.append((typ, item[1]+delta, item[2]+delta, item[3]+delta, item[4]+delta) + item[5:])
            elif typ == "re":
                r = item[1]
                new_items.append((typ, fitz.Rect(r.x0+dx, r.y0+dy, r.x1+dx, r.y1+dy)) + item[2:])
            elif typ == "qu":
                q = item[1]
                new_items.append((typ, fitz.Quad(q.ul+delta, q.ur+delta, q.ll+delta, q.lr+delta)) + item[2:])
            else:
                new_items.append(item)
        dr = drw["rect"]
        return dict(drw,
                    items=new_items,
                    rect=fitz.Rect(dr.x0+dx, dr.y0+dy, dr.x1+dx, dr.y1+dy))

    @staticmethod
    def _capture_sibling_images(
        page: fitz.Page, rect: fitz.Rect, skip_xref: int, doc: fitz.Document,
    ) -> list[tuple[fitz.Rect, bytes]]:
        """Return (bbox, raw_bytes) for images fully inside rect, excluding skip_xref."""
        out: list[tuple[fitz.Rect, bytes]] = []
        for info in page.get_image_info(xrefs=True):
            xr = info.get("xref", 0)
            if not xr or xr == skip_xref:
                continue
            r = fitz.Rect(info["bbox"])
            if rect.contains(r):
                b = _extract_image_bytes(doc, xr)
                if b is not None:
                    out.append((r, b))
        return out

    # ── apply ops ─────────────────────────────────────────────────────────────

    def _apply_move(self, new_rect: fitz.Rect, dx: float, dy: float) -> None:
        sel = self._sel
        if sel is None or self.canvas.document is None:
            return
        doc = self.canvas.document

        if sel.obj_type == "annot" and sel.xref is not None and sel.snap is not None:
            if self._is_annot_text(sel):
                text, fsize, color = self._parse_annot_text_meta(sel.snap)
                from core.history import TransformAnnotTextCmd
                cmd = TransformAnnotTextCmd(
                    sel.page_num, sel.xref,
                    list(sel.pdf_rect), list(new_rect),
                    text, fsize, color,
                )
                self.canvas.push_command(cmd, doc)
                sel.pdf_rect = new_rect
                sel.snap = dict(sel.snap, rect=list(new_rect))
            else:
                old_verts = sel.snap["vertices"]
                new_verts = _shift_verts(old_verts, dx, dy)
                cmd = MoveAnnotCmd(
                    sel.page_num, sel.xref,
                    list(sel.pdf_rect), old_verts,
                    list(new_rect), new_verts,
                )
                self.canvas.push_command(cmd, doc)
                # Polygon/Ink moves go through delete+recreate, assigning a new xref.
                # Keep sel in sync so a subsequent move or delete targets the live
                # xref, not the stale one that was deleted during execute.
                sel.xref = cmd._xref
                sel.pdf_rect = new_rect
                if sel.snap:
                    sel.snap = dict(sel.snap, xref=cmd._xref, rect=list(new_rect), vertices=new_verts)

        elif sel.obj_type == "image" and sel.xref is not None:
            img_bytes = _extract_image_bytes(doc._doc, sel.xref)
            if img_bytes is None:
                return
            from core.history import MoveImageWithSiblingsCmd
            cmd = MoveImageWithSiblingsCmd(
                sel.page_num, sel.xref,
                list(sel.pdf_rect), list(new_rect),
                img_bytes,
            )
            self.canvas.push_command(cmd, doc)
            sel.pdf_rect = new_rect

        elif sel.obj_type == "drawing" and sel.drawing is not None:
            from core.history import MoveDrawingCmd
            cmd = MoveDrawingCmd(sel.page_num, sel.drawing, dx, dy)
            self.canvas.push_command(cmd, doc)
            sel.drawing = cmd._drawing
            sel.pdf_rect = new_rect

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
        self._clear_handles()
        self._show_overlay(sel.page_num, sel.pdf_rect)
        if sel.obj_type == "image" or self._is_freetext(sel):
            self._show_handles(sel.page_num, sel.pdf_rect)

    def _apply_delete(self) -> None:
        sel = self._sel
        if sel is None or self.canvas.document is None:
            return
        doc = self.canvas.document

        if sel.obj_type == "annot" and sel.snap is not None:
            if self._is_annot_text(sel) and sel.xref is not None:
                text, fsize, color = self._parse_annot_text_meta(sel.snap)
                from core.history import DeleteAnnotTextCmd
                cmd = DeleteAnnotTextCmd(
                    sel.page_num, sel.xref, list(sel.pdf_rect),
                    text, fsize, color,
                )
                self.canvas.push_command(cmd, doc)
            else:
                cmd = DeleteAnnotCmd(sel.page_num, sel.snap)
                self.canvas.push_command(cmd, doc)

        elif sel.obj_type == "drawing" and sel.drawing is not None:
            page = doc.get_page(sel.page_num)
            if not strip_drawing(doc._doc, page, sel.drawing):
                page.add_redact_annot(sel.pdf_rect, fill=None)
                page.apply_redactions(images=0, graphics=1, text=0)

        elif sel.obj_type in ("text", "image"):
            page = doc.get_page(sel.page_num)
            page.add_redact_annot(sel.pdf_rect)
            page.apply_redactions()

        self._clear_overlay()
        self._sel = None
        self.canvas.refresh_page(sel.page_num)
