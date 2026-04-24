from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QImage, QKeyEvent, QMouseEvent, QPixmap, QWheelEvent
from PyQt6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from core.history import Command, History

if TYPE_CHECKING:
    from core.document import PDFDocument
    from tools.base import AbstractTool

# Layout constants
PAGE_GAP = 20                    # px between pages in scene
SCENE_MARGIN = 10                # px margin around content in scene rect

# Rendering constants
RENDER_SCALE = 2.0               # base render DPI multiplier — enough headroom for 1.5× zoom
MIN_RENDER_SCALE = 1.0           # minimum render scale
MAX_RENDER_SCALE = 5.0           # maximum render scale
RENDER_SCALE_THRESHOLD = 0.30    # re-render when scale changes by this fraction

# Zoom constants
ZOOM_IN_FACTOR = 1.25            # zoom in multiplier
ZOOM_OUT_FACTOR = 0.8            # zoom out multiplier (1/1.25)
WHEEL_ZOOM_FACTOR = 1.15         # wheel zoom multiplier
FIT_WIDTH_MARGIN = 20            # px margin when fitting to width

# Scale factor for TextWriter (1.5x view scale)
TEXT_WRITER_SCALE_FACTOR = 1.5


class PDFCanvas(QGraphicsView):
    page_changed = pyqtSignal(int)
    document_modified = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            self.renderHints()
            | self.renderHints().SmoothPixmapTransform  # type: ignore[attr-defined]
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.GlobalColor.darkGray)

        self.document: PDFDocument | None = None
        self.history: History = History()
        self._scale = RENDER_SCALE
        self._page_items: list[QGraphicsPixmapItem] = []
        self._page_rects: list[QRectF] = []
        self._current_tool: AbstractTool | None = None

    # ── document loading ──────────────────────────────────────────────────────

    def load_document(self, doc: "PDFDocument") -> None:
        if self._current_tool:
            self._current_tool.cancel()
        self.document = doc
        self.history = History()
        self._scale = RENDER_SCALE
        self.resetTransform()
        self._render_all_pages()

    def _render_all_pages(self) -> None:
        self._scene.clear()
        self._page_items.clear()
        self._page_rects.clear()

        if self.document is None:
            return

        y_offset = 0.0
        for i in range(self.document.page_count):
            item, rect = self._make_page_item(i, y_offset)
            self._page_items.append(item)
            self._page_rects.append(rect)
            y_offset += rect.height() + PAGE_GAP

        self._scene.setSceneRect(
            self._scene.itemsBoundingRect().adjusted(
                -SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN
            )
        )

    def _make_page_item(self, page_num: int, y_offset: float) -> tuple[QGraphicsPixmapItem, QRectF]:
        pix_data = self.document.render_page(page_num, self._scale)
        qimg = QImage(
            pix_data.samples,
            pix_data.width,
            pix_data.height,
            pix_data.stride,
            QImage.Format.Format_RGB888,
        )
        pixmap = QPixmap.fromImage(qimg)
        item = self._scene.addPixmap(pixmap)
        item.setPos(0.0, y_offset)
        item.setData(0, page_num)
        rect = QRectF(0.0, y_offset, float(pixmap.width()), float(pixmap.height()))
        return item, rect

    def refresh_page(self, page_num: int) -> None:
        if self.document is None or page_num >= len(self._page_items):
            return
        old_item = self._page_items[page_num]
        y_offset = self._page_rects[page_num].top()
        self._scene.removeItem(old_item)
        item, rect = self._make_page_item(page_num, y_offset)
        self._page_items[page_num] = item
        self._page_rects[page_num] = rect

    # ── coordinate conversion ─────────────────────────────────────────────────

    def scene_to_pdf(self, page_num: int, scene_pos: QPointF) -> fitz.Point:
        origin = self._page_rects[page_num].topLeft()
        return fitz.Point(
            (scene_pos.x() - origin.x()) / self._scale,
            (scene_pos.y() - origin.y()) / self._scale,
        )

    def pdf_to_scene(self, page_num: int, pdf_pt: fitz.Point) -> QPointF:
        origin = self._page_rects[page_num].topLeft()
        return QPointF(
            origin.x() + pdf_pt.x * self._scale,
            origin.y() + pdf_pt.y * self._scale,
        )

    def page_at_scene_pos(self, scene_pos: QPointF) -> int | None:
        for i, rect in enumerate(self._page_rects):
            if rect.contains(scene_pos):
                return i
        return None

    # ── zoom ──────────────────────────────────────────────────────────────────

    def zoom_in(self) -> None:
        self.scale(ZOOM_IN_FACTOR, ZOOM_IN_FACTOR)
        self._sync_render_scale()

    def zoom_out(self) -> None:
        self.scale(ZOOM_OUT_FACTOR, ZOOM_OUT_FACTOR)
        self._sync_render_scale()

    def fit_width(self) -> None:
        if not self._page_rects:
            return
        vw = self.viewport().width() - FIT_WIDTH_MARGIN
        factor = vw / self._page_rects[0].width()
        self.resetTransform()
        self.scale(factor, factor)
        self._sync_render_scale()

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            factor = WHEEL_ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / WHEEL_ZOOM_FACTOR
            self.scale(factor, factor)
            self._sync_render_scale()
        else:
            super().wheelEvent(event)

    def _sync_render_scale(self) -> None:
        """Re-render pages when effective resolution drifts far from 1:1 pixels."""
        if self.document is None:
            return
        view_zoom = self.transform().m11()            # current view scale factor
        desired = max(MIN_RENDER_SCALE, min(view_zoom * TEXT_WRITER_SCALE_FACTOR, MAX_RENDER_SCALE))

        if abs(desired - self._scale) / self._scale < RENDER_SCALE_THRESHOLD:
            return  # not worth the re-render cost

        # save center in PDF-space coordinates (page 0 approximation)
        center_scene = self.mapToScene(self.viewport().rect().center())

        old_render = self._scale
        self._scale = desired
        if self._current_tool:
            self._current_tool.cancel()  # prevent dangling item refs after scene.clear()
        self.resetTransform()
        self._render_all_pages()

        # restore scroll position
        ratio = desired / old_render
        self.centerOn(center_scene.x() * ratio, center_scene.y() * ratio)

    # ── tool routing ─────────────────────────────────────────────────────────

    def set_tool(self, tool: "AbstractTool | None") -> None:
        if self._current_tool:
            self._current_tool.cancel()
        self._current_tool = tool
        if tool is None:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.setCursor(Qt.CursorShape.CrossCursor)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._current_tool:
            sp = self.mapToScene(event.pos())
            pn = self.page_at_scene_pos(sp)
            if pn is not None:
                self._current_tool.on_press(pn, self.scene_to_pdf(pn, sp), sp, event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._current_tool:
            sp = self.mapToScene(event.pos())
            pn = self.page_at_scene_pos(sp)
            if pn is not None:
                self._current_tool.on_move(pn, self.scene_to_pdf(pn, sp), sp, event)
                self.page_changed.emit(pn)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._current_tool:
            sp = self.mapToScene(event.pos())
            pn = self.page_at_scene_pos(sp)
            if pn is not None:
                self._current_tool.on_release(pn, self.scene_to_pdf(pn, sp), sp, event)
        else:
            super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if self._current_tool:
            if key == Qt.Key.Key_Escape:
                self._current_tool.cancel()
                return
            # A scene item (e.g. inline text editor) has focus — let the scene route
            # the event to that item; don't intercept typing/backspace/etc.
            if self._scene.focusItem() is not None:
                super().keyPressEvent(event)
                return
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if hasattr(self._current_tool, "commit"):
                    self._current_tool.commit()  # type: ignore[union-attr]
                    return
            self._current_tool.on_key(event)
            return
        super().keyPressEvent(event)

    def push_command(self, cmd: "Command", doc: "PDFDocument") -> None:
        self.history.push(cmd, doc)
        self.document_modified.emit()

    def scroll_to_page(self, page_num: int) -> None:
        if 0 <= page_num < len(self._page_rects):
            self.ensureVisible(self._page_rects[page_num], 0, 0)
