from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from PyQt6.QtGui import QKeyEvent, QMouseEvent

if TYPE_CHECKING:
    from PyQt6.QtCore import QPointF
    import fitz
    from ui.canvas import PDFCanvas


class AbstractTool(ABC):
    """Base class for all canvas editing tools.

    PDFCanvas routes mouse and keyboard events to the active tool via
    on_press / on_move / on_release / on_key.  cancel() is called whenever
    the tool is deactivated (tool switch, Escape, zoom re-render) so it can
    clean up any in-progress scene items.

    Coordinates are provided in both PDF space (pdf_pos, in points) and
    scene space (scene_pos, in pixels at current render scale).  Tools that
    write to the PDF use pdf_pos; tools that add preview graphics to the
    QGraphicsScene use scene_pos.
    """

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
