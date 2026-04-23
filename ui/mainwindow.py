from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, QBuffer, QIODevice, QSettings
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QToolBar,
)


# Theme-name → qtawesome MDI icon name
_QTA: dict[str, str] = {
    "document-open":           "mdi.folder-open",
    "document-save":           "mdi.content-save",
    "document-save-as":        "mdi.content-save-edit",
    "document-close":          "mdi.close-circle-outline",
    "document-open-recent":    "mdi.history",
    "document-properties":     "mdi.file-cog",
    "document-edit":           "mdi.file-edit",
    "document-export":         "mdi.file-export",
    "document-revert":         "mdi.file-restore",
    "document-sign":           "mdi.draw",
    "edit-undo":               "mdi.undo",
    "edit-redo":               "mdi.redo",
    "edit-paste":              "mdi.content-paste",
    "edit-select":             "mdi.cursor-default-click",
    "edit-clear":              "mdi.eraser",
    "insert-text":             "mdi.format-text",
    "insert-image":            "mdi.image-plus",
    "draw-rectangle":          "mdi.rectangle-outline",
    "draw-highlight":          "mdi.marker",
    "draw-freehand":           "mdi.draw",
    "draw-calligraph":         "mdi.pen",
    "transform-move":          "mdi.cursor-move",
    "input-mouse":             "mdi.cursor-default",
    "object-order-back":       "mdi.arrange-send-to-back",
    "object-order-front":      "mdi.arrange-bring-to-front",
    "zoom-in":                 "mdi.magnify-plus",
    "zoom-out":                "mdi.magnify-minus",
    "zoom-fit-best":           "mdi.fit-to-page-outline",
    "scanner":                 "mdi.scanner",
    "image-x-generic":         "mdi.image",
    "image-x-raw":             "mdi.image",
    "user-trash":              "mdi.trash-can",
    "application-certificate": "mdi.certificate",
    "mail-signed":             "mdi.draw",
    "document-sign":           "mdi.draw",
}


def _qta_icon(name: str) -> QIcon:
    qta_name = _QTA.get(name)
    if not qta_name:
        return QIcon()
    try:
        import qtawesome as qta
        return qta.icon(qta_name, color="#444444")
    except Exception:
        return QIcon()


def _icon(theme: str, fallback_sp=None) -> QIcon:
    """Return theme icon; fall back to qtawesome then QStyle standard pixmap."""
    ic = QIcon.fromTheme(theme)
    if not ic.isNull():
        return ic
    ic = _qta_icon(theme)
    if not ic.isNull():
        return ic
    if fallback_sp is not None:
        style = QApplication.style()
        if style:
            return style.standardIcon(fallback_sp)
    return QIcon()


def _icon_any(*names: str) -> QIcon:
    """Return first non-null icon from theme names, then qtawesome fallbacks."""
    for name in names:
        ic = QIcon.fromTheme(name)
        if not ic.isNull():
            return ic
    for name in names:
        ic = _qta_icon(name)
        if not ic.isNull():
            return ic
    return QIcon()

import fitz
from core.document import PDFDocument
from tools.annotate import HighlightTool, RectAnnotateTool
from tools.image_insert import ImageInsertTool
from tools.select import SelectTool
from tools.text_add import TextAddTool
from tools.text_edit import TextEditTool
from ui.canvas import PDFCanvas
from ui.properties_dialog import PropertiesDialog
from ui.thumbnail_panel import ThumbnailPanel

MAX_RECENT = 10

_SIG_DIR        = Path.home() / ".config" / "PDFTool" / "signatures"
_SIG_MAX_W      = 5 * 72 / 2.54   # 5 cm in PDF points ≈ 141.7
_SCAN_DPI_KEY   = "scanDpi"
_SCAN_DPI_DEFAULT = 150


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        _icon_path = Path(__file__).parent.parent / "pdftool.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))
        _ver = QApplication.applicationVersion()
        if _ver:
            self.setWindowTitle(f"PDF Tool {_ver}")
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
        self._act_img_paste = QAction(_icon("edit-paste"), "&Paste Image", self, shortcut=QKeySequence.StandardKey.Paste)
        self._act_img_paste.setToolTip("Paste image from clipboard (click to place)")
        edit_menu.addActions([self._act_undo, self._act_redo])
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_img_paste)

        doc_menu = mb.addMenu("&Document")
        self._act_properties = QAction(
            _icon("document-properties"), "&Properties…", self,
            shortcut=QKeySequence("Ctrl+Shift+P"),
        )
        self._act_scan = QAction(
            _icon_any("scanner", "image-x-generic", "document-export"),
            "Convert to &Scanned…", self,
        )
        self._act_scan.setToolTip("Rasterize all pages to images, strip fonts and vectors, minimize file size")
        self._act_prune = QAction(
            _icon_any("edit-clear", "user-trash", "document-revert"),
            "&Prune…", self,
        )
        self._act_prune.setToolTip("Remove unused fonts, metadata, thumbnails, attachments to reduce file size")
        doc_menu.addAction(self._act_properties)
        doc_menu.addSeparator()
        doc_menu.addAction(self._act_scan)
        doc_menu.addAction(self._act_prune)

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

        self._act_send_back  = QAction(_icon("object-order-back"),  "Send to Back",    self, shortcut=QKeySequence("["))
        self._act_bring_front = QAction(_icon("object-order-front"), "Bring to Front",  self, shortcut=QKeySequence("]"))
        self._act_send_back.setToolTip("Send selected image behind all other content  [")
        self._act_bring_front.setToolTip("Bring selected image in front of all other content  ]")

        self._act_img_file = QAction(_icon("insert-image"), "Insert Image", self,
                                     shortcut=QKeySequence("Ctrl+Shift+I"))
        self._act_img_file.setToolTip("Insert image from file (click to place) — Ctrl+V to paste from clipboard")

        _sign_icon = QIcon(str(Path(__file__).parent.parent / "sign.png"))
        self._act_signatures = QAction(
            _sign_icon if not _sign_icon.isNull() else _icon_any("application-certificate", "draw-freehand", "document-edit"),
            "Signatures…", self,
            shortcut=QKeySequence("Ctrl+Shift+G"))
        self._act_signatures.setToolTip("Manage and place signatures (Ctrl+Shift+G)")

        for act in (self._act_pan, self._act_select, self._act_text, self._act_text_edit, self._act_rect, self._act_highlight):
            tb.addAction(act)
            act.triggered.connect(self._on_tool_selected)

        tb.addSeparator()
        tb.addAction(self._act_img_file)
        tb.addAction(self._act_send_back)
        tb.addAction(self._act_bring_front)
        tb.addSeparator()
        tb.addAction(self._act_signatures)
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
        self._act_img_file.triggered.connect(self._insert_image_file)
        self._act_img_paste.triggered.connect(self._insert_image_clipboard)
        self._act_send_back.triggered.connect(lambda: self._image_zorder(to_back=True))
        self._act_bring_front.triggered.connect(lambda: self._image_zorder(to_back=False))
        self._act_signatures.triggered.connect(self._open_signatures)
        self._act_scan.triggered.connect(self._convert_to_scanned)
        self._act_prune.triggered.connect(self._prune_document)

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

    # ── image insert ──────────────────────────────────────────────────────────

    def _start_image_insert(self, img_bytes: bytes) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        try:
            pm = fitz.Pixmap(img_bytes)
            w, h = pm.width, pm.height
        except Exception:
            QMessageBox.critical(self, "Image error", "Cannot read image dimensions.")
            return
        for act in self._tool_actions:
            act.setChecked(False)
        self._canvas.set_tool(ImageInsertTool(self._canvas, img_bytes, w, h))

    def _image_zorder(self, to_back: bool) -> None:
        tool = self._canvas._current_tool
        if isinstance(tool, SelectTool):
            tool.set_image_zorder(to_back)

    def _insert_image_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert Image", str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif *.webp)"
        )
        if not path:
            return
        self._start_image_insert(Path(path).read_bytes())

    def _insert_image_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        qimg = clipboard.image()
        if qimg.isNull():
            QMessageBox.warning(self, "Clipboard", "No image found in clipboard.")
            return
        buf = QBuffer()
        buf.open(QIODevice.OpenMode.WriteOnly)
        qimg.save(buf, "PNG")
        self._start_image_insert(bytes(buf.data()))

    # ── signature ─────────────────────────────────────────────────────────────

    def _open_signatures(self) -> None:
        from ui.signature_dialog import SignatureDialog
        dlg = SignatureDialog(self)
        dlg.place_requested.connect(self._place_signature_slot)
        dlg.exec()

    def _place_signature_slot(self, slot: int) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        from ui.signature_dialog import sig_path
        p = sig_path(slot)
        if not p.exists():
            return
        img_bytes = p.read_bytes()
        try:
            pm = fitz.Pixmap(img_bytes)
            w, h = pm.width, pm.height
        except Exception:
            QMessageBox.critical(self, "Signature", "Signature image is corrupted.")
            return
        for act in self._tool_actions:
            act.setChecked(False)
        self._canvas.set_tool(
            ImageInsertTool(self._canvas, img_bytes, w, h, max_w=_SIG_MAX_W)
        )

    # ── convert to scanned ────────────────────────────────────────────────────

    def _convert_to_scanned(self) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        current_dpi = int(self._settings.value(_SCAN_DPI_KEY, _SCAN_DPI_DEFAULT))
        dpi, ok = QInputDialog.getInt(
            self, "Convert to Scanned",
            "Render DPI (72–600):\n"
            "150 = good quality / small size\n"
            "300 = print quality / larger size",
            current_dpi, 72, 600, 25,
        )
        if not ok:
            return
        self._settings.setValue(_SCAN_DPI_KEY, dpi)

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Scanned PDF", str(Path.home()), "PDF files (*.pdf)"
        )
        if not out_path:
            return

        src = self._doc._doc
        scale = dpi / 72.0
        mat = fitz.Matrix(scale, scale)
        new_doc = fitz.open()
        try:
            for i in range(len(src)):
                page = src[i]
                pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=fitz.csRGB)
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(new_page.rect, pixmap=pix)
            new_doc.save(
                out_path,
                garbage=4,      # remove all unused objects/streams
                deflate=True,   # compress streams
                clean=True,     # sanitize content streams
            )
        finally:
            new_doc.close()

        QMessageBox.information(
            self, "Done",
            f"Scanned PDF saved:\n{out_path}"
        )

    # ── prune ─────────────────────────────────────────────────────────────────

    def _prune_document(self) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        from ui.prune_dialog import PruneDialog, analyze_for_prune
        src = self._doc._doc

        findings = analyze_for_prune(src)

        try:
            pruned_bytes = src.tobytes(garbage=4, deflate=True, clean=True)
            pruned_size = len(pruned_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Prune error", f"Could not compute pruned size:\n{e}")
            return

        orig_path = src.name
        from pathlib import Path as _Path
        orig_size = _Path(orig_path).stat().st_size if orig_path and _Path(orig_path).exists() else pruned_size

        dlg = PruneDialog(self, findings, orig_size, pruned_size)
        if dlg.exec() != PruneDialog.DialogCode.Accepted:
            return

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Pruned PDF", str(Path.home()), "PDF files (*.pdf)"
        )
        if not out_path:
            return

        try:
            Path(out_path).write_bytes(pruned_bytes)
        except Exception as e:
            QMessageBox.critical(self, "Save error", str(e))
            return

        QMessageBox.information(self, "Done", f"Pruned PDF saved:\n{out_path}")

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
