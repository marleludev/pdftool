from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolBar,
)


def _icon(theme: str, fallback_sp=None) -> QIcon:
    """Return theme icon; fall back to QStyle standard pixmap if theme icon missing."""
    ic = QIcon.fromTheme(theme)
    if not ic.isNull():
        return ic
    if fallback_sp is not None:
        style = QApplication.style()
        if style:
            return style.standardIcon(fallback_sp)
    return QIcon()

from core.document import PDFDocument
from tools.annotate import HighlightTool, RectAnnotateTool
from tools.select import SelectTool
from tools.text_add import TextAddTool
from tools.text_edit import TextEditTool
from ui.canvas import PDFCanvas
from ui.properties_dialog import PropertiesDialog
from ui.thumbnail_panel import ThumbnailPanel

MAX_RECENT = 10


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDF Tool")
        self.resize(1280, 900)

        self._doc: PDFDocument | None = None
        self._modified: bool = False
        self._settings = QSettings("PDFTool", "PDFTool")

        self._build_ui()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()
        self._rebuild_recent_menu()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._canvas = PDFCanvas()
        self._thumb_panel = ThumbnailPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._thumb_panel)
        splitter.addWidget(self._canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1080])
        self.setCentralWidget(splitter)

        self._status_page = QLabel("No document")
        self._status_zoom = QLabel("")
        sb = QStatusBar()
        sb.addWidget(self._status_page)
        sb.addPermanentWidget(self._status_zoom)
        self.setStatusBar(sb)

    def _build_menus(self) -> None:
        from PyQt6.QtWidgets import QStyle
        SP = QStyle.StandardPixmap
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self._act_open = QAction(_icon("document-open", SP.SP_DialogOpenButton), "&Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction(_icon("document-save", SP.SP_DialogSaveButton), "&Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction(_icon("document-save-as"), "Save &As…", self, shortcut=QKeySequence("Ctrl+Shift+S"))
        self._act_close = QAction(_icon("document-close", SP.SP_DialogCloseButton), "&Close", self, shortcut=QKeySequence.StandardKey.Close)

        file_menu.addAction(self._act_open)
        file_menu.addSeparator()

        self._recent_menu = QMenu("Open &Recent", self)
        self._recent_menu.setIcon(_icon("document-open-recent"))
        file_menu.addMenu(self._recent_menu)

        file_menu.addSeparator()
        file_menu.addActions([self._act_save, self._act_save_as])
        file_menu.addSeparator()
        file_menu.addAction(self._act_close)

        edit_menu = mb.addMenu("&Edit")
        self._act_undo = QAction(_icon("edit-undo", SP.SP_ArrowBack), "&Undo", self, shortcut=QKeySequence.StandardKey.Undo)
        self._act_redo = QAction(_icon("edit-redo", SP.SP_ArrowForward), "&Redo", self, shortcut=QKeySequence.StandardKey.Redo)
        edit_menu.addActions([self._act_undo, self._act_redo])

        doc_menu = mb.addMenu("&Document")
        self._act_properties = QAction(
            _icon("document-properties"), "&Properties…", self,
            shortcut=QKeySequence("Ctrl+Shift+P"),
        )
        doc_menu.addAction(self._act_properties)

        view_menu = mb.addMenu("&View")
        self._act_zoom_in  = QAction(_icon("zoom-in"),       "Zoom &In",   self, shortcut=QKeySequence("Ctrl+="))
        self._act_zoom_out = QAction(_icon("zoom-out"),      "Zoom &Out",  self, shortcut=QKeySequence("Ctrl+-"))
        self._act_fit      = QAction(_icon("zoom-fit-best"), "Fit &Width", self, shortcut=QKeySequence("Ctrl+0"))
        view_menu.addActions([self._act_zoom_in, self._act_zoom_out, self._act_fit])

    def _build_toolbar(self) -> None:
        tb = QToolBar("Tools", self)
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        tb.setIconSize(tb.iconSize().__class__(24, 24))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, tb)

        self._act_pan = QAction(_icon("transform-move", None) or _icon("input-mouse"),
                                "Pan", self, checkable=True, checked=True)
        self._act_pan.setToolTip("Pan (scroll)")

        self._act_select = QAction(_icon("edit-select"), "Select", self, checkable=True)
        self._act_select.setToolTip("Select / move / delete objects (Del to remove)")

        self._act_text = QAction(_icon("insert-text"), "Add Text", self, checkable=True)
        self._act_text.setToolTip("Add text box")

        self._act_text_edit = QAction(_icon("document-edit"), "Edit Text", self, checkable=True)
        self._act_text_edit.setToolTip("Edit existing text")

        self._act_rect = QAction(_icon("draw-rectangle"), "Rectangle", self, checkable=True)
        self._act_rect.setToolTip("Draw rectangle annotation")

        self._act_highlight = QAction(_icon("draw-highlight"), "Highlight", self, checkable=True)
        self._act_highlight.setToolTip("Highlight text region")

        for act in (self._act_pan, self._act_select, self._act_text, self._act_text_edit, self._act_rect, self._act_highlight):
            tb.addAction(act)
            act.triggered.connect(self._on_tool_selected)

        tb.addSeparator()
        tb.addAction(self._act_zoom_in)
        tb.addAction(self._act_zoom_out)
        tb.addAction(self._act_fit)
        tb.addSeparator()
        tb.addAction(self._act_undo)
        tb.addAction(self._act_redo)
        tb.addSeparator()
        tb.addAction(self._act_open)
        tb.addAction(self._act_save)
        tb.addAction(self._act_properties)

        self._tool_actions = {
            self._act_pan: None,
            self._act_select: "select",
            self._act_text: "text",
            self._act_text_edit: "text_edit",
            self._act_rect: "rect",
            self._act_highlight: "highlight",
        }

    def _connect_signals(self) -> None:
        self._act_open.triggered.connect(self._open_file)
        self._act_save.triggered.connect(self._save_file)
        self._act_save_as.triggered.connect(self._save_file_as)
        self._act_close.triggered.connect(self._close_document)
        self._act_undo.triggered.connect(self._undo)
        self._act_redo.triggered.connect(self._redo)
        self._act_properties.triggered.connect(self._edit_properties)
        self._canvas.document_modified.connect(self._mark_modified)
        self._act_zoom_in.triggered.connect(self._canvas.zoom_in)
        self._act_zoom_out.triggered.connect(self._canvas.zoom_out)
        self._act_fit.triggered.connect(self._canvas.fit_width)
        self._thumb_panel.page_selected.connect(self._canvas.scroll_to_page)
        self._canvas.page_changed.connect(self._on_page_changed)

    # ── recent files ──────────────────────────────────────────────────────────

    def _recent_paths(self) -> list[str]:
        return self._settings.value("recentFiles", [], type=list)  # type: ignore[return-value]

    def _add_to_recent(self, path: str) -> None:
        paths: list[str] = self._recent_paths()
        if path in paths:
            paths.remove(path)
        paths.insert(0, path)
        self._settings.setValue("recentFiles", paths[:MAX_RECENT])
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self) -> None:
        self._recent_menu.clear()
        paths = self._recent_paths()
        if not paths:
            self._recent_menu.addAction("(empty)").setEnabled(False)
            return
        for i, path in enumerate(paths):
            label = f"&{i + 1}  {Path(path).name}  —  {Path(path).parent}"
            act = QAction(label, self)
            act.setData(path)
            act.triggered.connect(self._open_recent)
            self._recent_menu.addAction(act)
        self._recent_menu.addSeparator()
        clear_act = QAction("Clear Recent Files", self)
        clear_act.triggered.connect(self._clear_recent)
        self._recent_menu.addAction(clear_act)

    def _open_recent(self) -> None:
        act = self.sender()
        if act:
            self._load_path(Path(act.data()))  # type: ignore[union-attr]

    def _clear_recent(self) -> None:
        self._settings.setValue("recentFiles", [])
        self._rebuild_recent_menu()

    # ── file operations ───────────────────────────────────────────────────────

    def _open_file(self) -> None:
        start_dir = str(Path.home())
        paths = self._recent_paths()
        if paths:
            start_dir = str(Path(paths[0]).parent)
        path, _ = QFileDialog.getOpenFileName(self, "Open PDF", start_dir, "PDF Files (*.pdf)")
        if path:
            self._load_path(Path(path))

    def _load_path(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "File not found", f"File not found:\n{path}")
            return
        if not self._confirm_discard():
            return
        if self._doc:
            self._doc.close()
        self._doc = PDFDocument(path)
        self._modified = False
        self._canvas.load_document(self._doc)
        self._thumb_panel.load_document(self._doc)
        self.setWindowTitle(f"PDF Tool — {path.name}")
        self._status_page.setText(f"Page 1 / {self._doc.page_count}")
        self._add_to_recent(str(path))

    def _save_file(self) -> None:
        if not self._doc:
            return
        self._commit_active_tool()
        try:
            out = self._doc.path.with_stem(self._doc.path.stem + "_edited")
            self._doc.save(out)
            self._doc.path = out
            self._clear_modified()
            self.setWindowTitle(f"PDF Tool — {out.name}")
            self._add_to_recent(str(out))
            QMessageBox.information(self, "Saved", f"Saved to:\n{out}")
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))

    def _save_file_as(self) -> None:
        if not self._doc:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PDF As", str(self._doc.path.parent), "PDF Files (*.pdf)"
        )
        if not path:
            return
        self._commit_active_tool()
        try:
            self._doc.save(Path(path))
            self._clear_modified()
            QMessageBox.information(self, "Saved", f"Saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save error", str(exc))

    def _close_document(self) -> None:
        if not self._confirm_discard():
            return
        if self._doc:
            self._doc.close()
            self._doc = None
        self._modified = False
        self._canvas.document = None
        self._canvas._scene.clear()
        self._canvas._page_items.clear()
        self._canvas._page_rects.clear()
        self._thumb_panel._list.clear()
        self.setWindowTitle("PDF Tool")
        self._status_page.setText("No document")

    # ── tools ─────────────────────────────────────────────────────────────────

    def _on_tool_selected(self, checked: bool) -> None:
        sender = self.sender()
        for act in self._tool_actions:
            act.setChecked(act is sender)

        tool_name = self._tool_actions.get(sender)  # type: ignore[arg-type]
        if tool_name is None:
            self._canvas.set_tool(None)
        elif tool_name == "select":
            self._canvas.set_tool(SelectTool(self._canvas))
        elif tool_name == "text":
            self._canvas.set_tool(TextAddTool(self._canvas))
        elif tool_name == "text_edit":
            self._canvas.set_tool(TextEditTool(self._canvas))
        elif tool_name == "rect":
            self._canvas.set_tool(RectAnnotateTool(self._canvas))
        elif tool_name == "highlight":
            self._canvas.set_tool(HighlightTool(self._canvas))

    def _commit_active_tool(self) -> None:
        tool = self._canvas._current_tool
        if hasattr(tool, "commit"):
            tool.commit()  # type: ignore[union-attr]

    # ── modified state ────────────────────────────────────────────────────────

    def _mark_modified(self) -> None:
        if not self._modified:
            self._modified = True
            self.setWindowTitle(self.windowTitle() + " *")

    def _clear_modified(self) -> None:
        self._modified = False
        self.setWindowTitle(self.windowTitle().removesuffix(" *"))

    def _confirm_discard(self) -> bool:
        """Return True if it's OK to discard unsaved changes."""
        if not self._modified:
            return True
        ans = QMessageBox.warning(
            self, "Unsaved changes",
            "Document has unsaved changes. Save before closing?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if ans == QMessageBox.StandardButton.Save:
            self._save_file()
            return True
        return ans == QMessageBox.StandardButton.Discard

    # ── document properties ───────────────────────────────────────────────────

    def _edit_properties(self) -> None:
        if not self._doc:
            return
        dlg = PropertiesDialog(self._doc._doc.metadata, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        # Merge to preserve fields not shown in the dialog (producer, creationDate, etc.)
        merged = dict(self._doc._doc.metadata)
        merged.update(dlg.result_meta)
        self._doc._doc.set_metadata(merged)
        self._mark_modified()

    # ── edit ─────────────────────────────────────────────────────────────────

    def _undo(self) -> None:
        if self._doc:
            page = self._canvas.history.undo(self._doc)
            if page is not None:
                self._canvas.refresh_page(page)

    def _redo(self) -> None:
        if self._doc:
            page = self._canvas.history.redo(self._doc)
            if page is not None:
                self._canvas.refresh_page(page)

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()

    # ── status bar ────────────────────────────────────────────────────────────

    def _on_page_changed(self, page_num: int) -> None:
        if self._doc:
            self._status_page.setText(f"Page {page_num + 1} / {self._doc.page_count}")
            self._thumb_panel.highlight_page(page_num)
