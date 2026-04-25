from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QFocusEvent, QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import QGraphicsTextItem

from core.history import AddTextCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

_DEFAULT_BOX_W = 200.0  # PDF points
_DEFAULT_BOX_H = 50.0


class _TextItem(QGraphicsTextItem):
    """QGraphicsTextItem that signals commit/cancel on Enter/Escape/focusOut."""

    commit_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        mods = event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if mods & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(event)  # Shift+Enter → newline
            else:
                self.commit_requested.emit()
        elif key == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.commit_requested.emit()


class TextAddTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._page_num: int | None = None
        self._text_item: _TextItem | None = None
        self._pdf_pos: fitz.Point | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        # if a text item already exists and user clicks elsewhere, commit it first
        if self._text_item is not None:
            self.commit()
            return  # don't start a new one on the same click that committed the old one

        self._page_num = page_num
        self._pdf_pos = pdf_pos

        item = _TextItem()
        item.setTextInteractionFlags(Qt.TextInteractionFlag.TextEditorInteraction)
        item.setDefaultTextColor(Qt.GlobalColor.black)
        item.setPos(scene_pos)
        item.commit_requested.connect(self.commit)
        item.cancel_requested.connect(self.cancel)
        self.canvas.scene().addItem(item)
        item.setFocus()
        self._text_item = item

    def cancel(self) -> None:
        if self._text_item:
            self._text_item.commit_requested.disconnect()
            self._text_item.cancel_requested.disconnect()
            if self._text_item.scene() is not None:
                self.canvas.scene().removeItem(self._text_item)
            self._text_item = None
        self._page_num = None
        self._pdf_pos = None

    def commit(self) -> None:
        if self._text_item is None or self._page_num is None or self._pdf_pos is None:
            return

        # Disconnect BEFORE removeItem: Qt fires focusOut when an item is removed
        # from the scene, which would trigger commit_requested a second time.
        self._text_item.commit_requested.disconnect()
        self._text_item.cancel_requested.disconnect()

        text = self._text_item.toPlainText().strip()
        if text and self.canvas.document:
            rect = [
                self._pdf_pos.x,
                self._pdf_pos.y,
                self._pdf_pos.x + _DEFAULT_BOX_W,
                self._pdf_pos.y + _DEFAULT_BOX_H,
            ]
            cmd = AddTextCmd(self._page_num, rect, text, 12.0, "helv", (0.0, 0.0, 0.0))
            self.canvas.push_command(cmd, self.canvas.document)
            self.canvas.refresh_page(self._page_num)

        if self._text_item.scene() is not None:
            self.canvas.scene().removeItem(self._text_item)
        self._text_item = None
        self._page_num = None
        self._pdf_pos = None
