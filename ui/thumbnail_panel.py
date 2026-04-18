from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap
from PyQt6.QtWidgets import QListWidget, QListWidgetItem, QSizePolicy, QWidget, QVBoxLayout, QLabel

if TYPE_CHECKING:
    from core.document import PDFDocument

THUMB_WIDTH = 160
THUMB_SCALE = 0.3


class ThumbnailPanel(QWidget):
    page_selected = pyqtSignal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(THUMB_WIDTH + 24)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        label = QLabel("Pages")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self._list = QListWidget()
        self._list.setIconSize(self._list.iconSize().__class__(THUMB_WIDTH, 300))
        self._list.setSpacing(4)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.currentRowChanged.connect(self.page_selected)
        layout.addWidget(self._list)

    def load_document(self, doc: "PDFDocument") -> None:
        self._list.clear()
        for i in range(doc.page_count):
            pix_data = doc.render_page(i, THUMB_SCALE)
            qimg = QImage(
                pix_data.samples,
                pix_data.width,
                pix_data.height,
                pix_data.stride,
                QImage.Format.Format_RGB888,
            )
            pixmap = QPixmap.fromImage(qimg).scaledToWidth(
                THUMB_WIDTH, Qt.TransformationMode.SmoothTransformation
            )
            item = QListWidgetItem(f"  {i + 1}")
            item.setIcon(self._list.style().standardIcon(self._list.style().StandardPixmap.SP_FileIcon))
            item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
            self._list.addItem(item)

    def highlight_page(self, page_num: int) -> None:
        self._list.blockSignals(True)
        self._list.setCurrentRow(page_num)
        self._list.blockSignals(False)
