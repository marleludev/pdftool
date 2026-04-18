from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from PyQt6.QtGui import QKeyEvent, QMouseEvent

if TYPE_CHECKING:
    from PyQt6.QtCore import QPointF
    import fitz
    from ui.canvas import PDFCanvas


class AbstractTool(ABC):
    def __init__(self, canvas: "PDFCanvas") -> None:
        self.canvas = canvas

    def on_press(self, page_num: int, pdf_pos: "fitz.Point", scene_pos: "QPointF", event: QMouseEvent) -> None:
        pass

    def on_move(self, page_num: int, pdf_pos: "fitz.Point", scene_pos: "QPointF", event: QMouseEvent) -> None:
        pass

    def on_release(self, page_num: int, pdf_pos: "fitz.Point", scene_pos: "QPointF", event: QMouseEvent) -> None:
        pass

    def on_key(self, event: "QKeyEvent") -> None:
        pass

    def cancel(self) -> None:
        pass
