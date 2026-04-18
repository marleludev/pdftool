from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPen
from PyQt6.QtWidgets import QGraphicsRectItem

from core.history import AddAnnotCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas


class RectAnnotateTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._start_pdf: fitz.Point | None = None
        self._start_scene: QPointF | None = None
        self._page_num: int | None = None
        self._rubber: QGraphicsRectItem | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        self._page_num = page_num
        self._start_pdf = pdf_pos
        self._start_scene = scene_pos
        pen = QPen(QColor(220, 50, 50), 1.5, Qt.PenStyle.DashLine)
        self._rubber = self.canvas.scene().addRect(QRectF(scene_pos, scene_pos), pen)

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rubber and self._start_scene:
            self._rubber.setRect(QRectF(self._start_scene, scene_pos).normalized())

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None

        if self._start_pdf is None or self._page_num is None:
            return

        r = fitz.Rect(
            min(self._start_pdf.x, pdf_pos.x), min(self._start_pdf.y, pdf_pos.y),
            max(self._start_pdf.x, pdf_pos.x), max(self._start_pdf.y, pdf_pos.y),
        )
        if r.width < 5 or r.height < 5:
            self._reset()
            return

        if self.canvas.document:
            cmd = AddAnnotCmd(self._page_num, "rect_annot",
                              {"rect": list(r), "color": [1.0, 0.0, 0.0], "width": 1.5})
            self.canvas.push_command(cmd, self.canvas.document)
            self.canvas.refresh_page(self._page_num)

        self._reset()

    def cancel(self) -> None:
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None
        self._reset()

    def _reset(self) -> None:
        self._start_pdf = None
        self._start_scene = None
        self._page_num = None


class HighlightTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._start_pdf: fitz.Point | None = None
        self._start_scene: QPointF | None = None
        self._page_num: int | None = None
        self._rubber: QGraphicsRectItem | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        self._page_num = page_num
        self._start_pdf = pdf_pos
        self._start_scene = scene_pos
        pen = QPen(QColor(255, 220, 0, 180), 1, Qt.PenStyle.SolidLine)
        self._rubber = self.canvas.scene().addRect(QRectF(scene_pos, scene_pos), pen)
        self._rubber.setBrush(QColor(255, 255, 0, 80))

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rubber and self._start_scene:
            self._rubber.setRect(QRectF(self._start_scene, scene_pos).normalized())

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None

        if self._start_pdf is None or self._page_num is None:
            return

        r = fitz.Rect(
            min(self._start_pdf.x, pdf_pos.x), min(self._start_pdf.y, pdf_pos.y),
            max(self._start_pdf.x, pdf_pos.x), max(self._start_pdf.y, pdf_pos.y),
        )
        if r.width < 5 or r.height < 5:
            self._reset()
            return

        if self.canvas.document:
            cmd = AddAnnotCmd(self._page_num, "highlight", {"quads": [list(r.quad)]})
            self.canvas.push_command(cmd, self.canvas.document)
            self.canvas.refresh_page(self._page_num)

        self._reset()

    def cancel(self) -> None:
        if self._rubber:
            self.canvas.scene().removeItem(self._rubber)
            self._rubber = None
        self._reset()

    def _reset(self) -> None:
        self._start_pdf = None
        self._start_scene = None
        self._page_num = None
