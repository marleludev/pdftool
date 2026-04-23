from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QTimer
from PyQt6.QtGui import QMouseEvent

from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

_DEFAULT_WIDTH = 200.0  # PDF points


class ImageInsertTool(AbstractTool):
    """Click-to-place tool. Places img_bytes at clicked position, then reverts to pan."""

    def __init__(
        self,
        canvas: "PDFCanvas",
        img_bytes: bytes,
        img_w: int,
        img_h: int,
        max_w: float | None = None,
    ) -> None:
        super().__init__(canvas)
        self._img_bytes = img_bytes
        self._aspect = img_w / img_h if img_h > 0 else 1.0
        self._max_w = max_w

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if not self.canvas.document:
            return
        w = _DEFAULT_WIDTH if self._max_w is None else self._max_w
        h = w / self._aspect
        rect = fitz.Rect(pdf_pos.x, pdf_pos.y, pdf_pos.x + w, pdf_pos.y + h)
        page = self.canvas.document.get_page(page_num)
        page.insert_image(rect, stream=self._img_bytes)
        self.canvas.document_modified.emit()
        self.canvas.refresh_page(page_num)
        QTimer.singleShot(0, lambda: self.canvas.set_tool(None))

    def cancel(self) -> None:
        pass
