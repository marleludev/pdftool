from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QImage, QPixmap
from PyQt6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QWidget,
    QVBoxLayout,
    QLabel,
    QAbstractItemView,
)

if TYPE_CHECKING:
    from core.document import PDFDocument

logger = logging.getLogger(__name__)

THUMB_WIDTH = 160
THUMB_SCALE = 0.3


from ui.sprite_icons import sprite_icon


def _icon(name: str) -> QIcon:
    """Return icon from the SVG sprite (see ui/sprite_icons.py)."""
    return sprite_icon(name)


class ThumbnailPanel(QWidget):
    page_selected = pyqtSignal(int)
    page_move_requested = pyqtSignal(int, int)   # from_index, to_index
    page_delete_requested = pyqtSignal(int)       # index
    page_insert_requested = pyqtSignal(int)       # index (insert before)
    page_rotate_requested = pyqtSignal(int, int)  # index, degrees (+90 CW / -90 CCW)
    page_resize_requested = pyqtSignal(int)        # index

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._doc: PDFDocument | None = None
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        self.setFixedWidth(THUMB_WIDTH + 24)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        label = QLabel("Pages")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)

        self._list = QListWidget()
        self._list.setIconSize(QSize(THUMB_WIDTH, 300))
        self._list.setSpacing(4)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._list.model().rowsMoved.connect(self._on_rows_moved)
        self._list.currentRowChanged.connect(self._on_current_row_changed)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

        # Track if we're handling a move to avoid double signals
        self._handling_move = False

    def _on_current_row_changed(self, row: int) -> None:
        """Handle page selection changes."""
        if row >= 0 and not self._handling_move:
            self.page_selected.emit(row)

    def _on_rows_moved(self, parent, start: int, end: int, destination, row: int) -> None:
        """Handle drag-and-drop reordering.

        This is called when the user drags items within the list.
        """
        if self._handling_move:
            return

        self._handling_move = True
        # Calculate the actual from/to indices
        from_index = start
        to_index = row if row <= start else row - 1

        logger.debug("Page move requested: %d -> %d", from_index, to_index)
        self.page_move_requested.emit(from_index, to_index)
        self._handling_move = False

    def _on_context_menu(self, position) -> None:
        """Show context menu for page operations."""
        if self._doc is None:
            return

        index = self._list.indexAt(position).row()
        if index < 0:
            index = self._list.count()  # Clicked below last item

        menu = QMenu(self)

        # Insert page actions with icons
        insert_before = QAction(_icon("file-plus"), "Insert page before", self)
        insert_before.triggered.connect(lambda: self.page_insert_requested.emit(index))
        menu.addAction(insert_before)

        if index < self._list.count():
            insert_after = QAction(_icon("file-plus-outline"), "Insert page after", self)
            insert_after.triggered.connect(lambda: self.page_insert_requested.emit(index + 1))
            menu.addAction(insert_after)

            menu.addSeparator()

            resize_action = QAction(_icon("resize"), "Resize page…", self)
            resize_action.triggered.connect(lambda checked, i=index: self.page_resize_requested.emit(i))
            menu.addAction(resize_action)

            menu.addSeparator()

            rot_cw = QAction(_icon("rotate-right"), "Rotate 90° clockwise", self)
            rot_cw.triggered.connect(lambda checked, i=index: self.page_rotate_requested.emit(i, 90))
            menu.addAction(rot_cw)

            rot_ccw = QAction(_icon("rotate-left"), "Rotate 90° counter-clockwise", self)
            rot_ccw.triggered.connect(lambda checked, i=index: self.page_rotate_requested.emit(i, -90))
            menu.addAction(rot_ccw)

            menu.addSeparator()

            delete_action = QAction(_icon("trash-can"), "Delete page", self)
            delete_action.triggered.connect(lambda: self.page_delete_requested.emit(index))
            menu.addAction(delete_action)

        menu.exec(self._list.viewport().mapToGlobal(position))

    def load_document(self, doc: "PDFDocument") -> None:
        """Load and display all pages from the document."""
        self._doc = doc
        self._list.clear()
        for i in range(doc.page_count):
            self._add_thumbnail(i)

    def _add_thumbnail(self, index: int) -> None:
        """Add a thumbnail for the specified page."""
        if self._doc is None:
            return

        pix_data = self._doc.render_page(index, THUMB_SCALE)
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
        item = QListWidgetItem(f"  {index + 1}")
        item.setIcon(_icon("file-document"))
        item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self._list.addItem(item)

    def refresh_thumbnails(self) -> None:
        """Refresh all thumbnails after page structure changes."""
        if self._doc is None:
            return

        current_row = self._list.currentRow()
        self._list.clear()
        for i in range(self._doc.page_count):
            self._add_thumbnail(i)

        # Restore selection
        if 0 <= current_row < self._doc.page_count:
            self._list.setCurrentRow(current_row)
        elif self._doc.page_count > 0:
            self._list.setCurrentRow(min(current_row, self._doc.page_count - 1))

    def insert_thumbnail(self, index: int) -> None:
        """Insert a new thumbnail at the specified index."""
        self._list.blockSignals(True)
        if self._doc is None:
            return

        pix_data = self._doc.render_page(index, THUMB_SCALE)
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
        item = QListWidgetItem(f"  {index + 1}")
        item.setIcon(_icon("file-document"))
        item.setData(Qt.ItemDataRole.DecorationRole, pixmap)
        item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom)
        self._list.insertItem(index, item)

        # Renumber items after insertion
        for i in range(index + 1, self._list.count()):
            self._list.item(i).setText(f"  {i + 1}")

        self._list.blockSignals(False)

    def remove_thumbnail(self, index: int) -> None:
        """Remove a thumbnail at the specified index."""
        self._list.blockSignals(True)
        self._list.takeItem(index)

        # Renumber remaining items
        for i in range(index, self._list.count()):
            self._list.item(i).setText(f"  {i + 1}")

        self._list.blockSignals(False)

    def highlight_page(self, page_num: int) -> None:
        """Highlight the specified page in the thumbnail list."""
        self._list.blockSignals(True)
        self._list.setCurrentRow(page_num)
        self._list.blockSignals(False)
