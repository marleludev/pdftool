from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image
from PyQt6.QtCore import Qt, QBuffer, QIODevice, QSettings
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QToolButton,
)

from core.document import PDFDocument
from core.history import InsertPageCmd, MovePageCmd, DeletePageCmd, RotatePageCmd, ResizePageCmd
from tools.annotate import HighlightTool, RectAnnotateTool
from tools.brush import BrushTool, EncircleTool, BRUSH_STYLES
from tools.image_insert import ImageInsertTool
from tools.rect_select import RectangleSelectTool
from tools.select import SelectTool
from tools.text_add import TextAddTool
from tools.text_edit import TextEditTool
from ui.canvas import PDFCanvas
from ui.properties_dialog import PropertiesDialog
from ui.thumbnail_panel import ThumbnailPanel

logger = logging.getLogger(__name__)


# Theme-name → qtawesome Font Awesome 6 Solid icon name (fa6s prefix).
# Browse glyphs at https://fontawesome.com/v4/icons/ — FA6 covers every FA4
# icon with renamed keys. Reference rename map:
# https://fontawesome.com/docs/web/setup/upgrade/whats-changed
# FA5 Solid not used: Qt6 dedupes "Font Awesome 5 Free" family across weights,
# breaking solid-only glyphs.
_QTA: dict[str, str] = {
    # File ops  (fa6 = regular/outline, fa6s = solid-only)
    "document-open":           "fa6.folder-open",
    "document-save":           "fa6.floppy-disk",
    "document-save-as":        "fa6.share-from-square",
    "document-close":          "fa6.circle-xmark",
    "document-open-recent":    "fa6s.clock-rotate-left",
    "document-properties":     "fa6s.gear",
    # Edit ops
    "edit-undo":               "fa6s.rotate-left",
    "edit-redo":               "fa6s.rotate-right",
    "edit-paste":              "fa6.clipboard",
    "edit-select":             "fa6s.arrow-pointer",
    "edit-rect-select":        "fa6.object-group",
    "insert-page":             "fa6.file",
    "insert-text":             "fa6s.font",
    "insert-image":            "fa6.image",
    "document-edit":           "fa6.pen-to-square",
    # Draw / annotate
    "draw-rectangle":          "fa6.square",
    "draw-highlight":          "fa6s.paintbrush",
    "draw-brush":              "fa6s.pen-nib",
    "draw-encircle":           "fa6s.draw-polygon",
    "draw-freehand":           "fa6s.pencil",
    # Tools / nav
    "transform-move":          "fa6s.up-down-left-right",
    "input-mouse":             "fa6.hand",
    # Z-order
    "object-order-back":       "fa6s.turn-down",
    "object-order-front":      "fa6s.turn-up",
    # Zoom
    "zoom-in":                 "fa6s.magnifying-glass-plus",
    "zoom-out":                "fa6s.magnifying-glass-minus",
    "zoom-fit-best":           "fa6s.expand",
    # Image / scan
    "scanner":                 "fa6s.camera",
    "image-x-generic":         "fa6.image",
    "image-x-raw":             "fa6.image",
    # Misc
    "user-trash":              "fa6.trash-can",
    "application-certificate": "fa6s.certificate",
    "mail-signed":             "fa6s.signature",
    "document-encrypt":        "fa6s.lock",
    "document-unlock":         "fa6s.lock-open",
}


def _qta_icon(name: str) -> QIcon:
    qta_name = _QTA.get(name)
    if not qta_name:
        return QIcon()
    try:
        import qtawesome as qta
        return qta.icon(qta_name, color="#555555")
    except Exception:
        return QIcon()


def _icon(theme: str, fallback_sp=None) -> QIcon:
    """Return qtawesome icon; fall back to theme then QStyle standard pixmap."""
    ic = _qta_icon(theme)
    if not ic.isNull():
        return ic
    ic = QIcon.fromTheme(theme)
    if not ic.isNull():
        return ic
    if fallback_sp is not None:
        style = QApplication.style()
        if style:
            return style.standardIcon(fallback_sp)
    return QIcon()


def _icon_any(*names: str) -> QIcon:
    """Return first non-null qtawesome icon, then fallback to theme icons."""
    for name in names:
        ic = _qta_icon(name)
        if not ic.isNull():
            return ic
    for name in names:
        ic = QIcon.fromTheme(name)
        if not ic.isNull():
            return ic
    return QIcon()


MAX_RECENT = 10

_SIG_DIR        = Path.home() / ".config" / "PDFTool" / "signatures"
_SIG_MAX_W      = 5 * 72 / 2.54   # 5 cm in PDF points ≈ 141.7
_SCAN_DPI_KEY   = "scanDpi"
_SCAN_DPI_DEFAULT = 150
_COMPRESS_DPI_KEY     = "compressImagesDpi"
_COMPRESS_DPI_DEFAULT = 200


@dataclass
class _TabState:
    canvas: PDFCanvas
    thumb_panel: ThumbnailPanel
    splitter: QSplitter
    doc: PDFDocument | None = None
    modified: bool = False


class MainWindow(QMainWindow):

    # ── tab state properties ──────────────────────────────────────────────────

    @property
    def _canvas(self) -> PDFCanvas:
        return self._tabs[self._tab_idx].canvas

    @property
    def _thumb_panel(self) -> ThumbnailPanel:
        return self._tabs[self._tab_idx].thumb_panel

    @property
    def _doc(self) -> PDFDocument | None:
        if not self._tabs or self._tab_idx >= len(self._tabs):
            return None
        return self._tabs[self._tab_idx].doc

    @_doc.setter
    def _doc(self, value: PDFDocument | None) -> None:
        self._tabs[self._tab_idx].doc = value
        self._update_tab_title()

    @property
    def _modified(self) -> bool:
        if not self._tabs or self._tab_idx >= len(self._tabs):
            return False
        return self._tabs[self._tab_idx].modified

    @_modified.setter
    def _modified(self, value: bool) -> None:
        if self._tabs and self._tab_idx < len(self._tabs):
            self._tabs[self._tab_idx].modified = value
            self._update_tab_title()

    # ── init ──────────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        super().__init__()
        _icon_path = Path(__file__).parent.parent / "pdftool.png"
        if _icon_path.exists():
            self.setWindowIcon(QIcon(str(_icon_path)))
        _ver = QApplication.applicationVersion()
        if _ver:
            self.setWindowTitle(f"PDF Tool {_ver}")
        self.resize(1280, 900)

        self._tabs: list[_TabState] = []
        self._tab_idx: int = 0
        self._settings = QSettings("PDFTool", "PDFTool")
        self._highlight_color: tuple[float, float, float] = (1.0, 1.0, 0.0)  # yellow default
        self._brush_color: tuple[float, float, float] = (0.0, 0.0, 0.8)    # blue default
        self._brush_style: str = "pen"
        self._brush_smoothness: str = "normal"
        self._brush_close_path: bool = False
        self._encircle_color: tuple[float, float, float] = (0.8, 0.0, 0.0)  # red default

        self._build_ui()
        self._create_actions()
        self._build_menus()
        self._build_toolbar()
        self._connect_signals()
        self._rebuild_recent_menu()

    def _create_actions(self) -> None:
        """Create actions that are used in menus and toolbar."""
        self._act_insert_page = QAction(_icon("insert-page"), "Insert Page", self,
                                         shortcut=QKeySequence("Ctrl+Shift+N"))
        self._act_insert_page.setToolTip("Insert new blank page after current page")

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(True)
        self._tab_widget.setMovable(True)
        self._tab_widget.setDocumentMode(True)
        self.setCentralWidget(self._tab_widget)

        self._make_tab()  # initial empty tab

        self._status_page = QLabel("No document")
        self._status_zoom = QLabel("")
        sb = QStatusBar()
        sb.addWidget(self._status_page)
        sb.addPermanentWidget(self._status_zoom)
        self.setStatusBar(sb)

    def _make_tab(self) -> int:
        """Create a new tab with its own canvas and thumbnail panel. Returns new tab index."""
        canvas = PDFCanvas()
        thumb = ThumbnailPanel()

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(thumb)
        splitter.addWidget(canvas)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([200, 1080])

        tab = _TabState(canvas=canvas, thumb_panel=thumb, splitter=splitter)
        self._tabs.append(tab)
        idx = len(self._tabs) - 1
        self._tab_widget.addTab(splitter, "No document")

        # Per-tab signal connections
        canvas.document_modified.connect(lambda: self._on_canvas_modified(canvas))
        canvas.page_changed.connect(lambda p: self._on_canvas_page_changed(canvas, p))
        thumb.page_selected.connect(canvas.scroll_to_page)
        thumb.page_move_requested.connect(self._on_page_move)
        thumb.page_delete_requested.connect(self._on_page_delete)
        thumb.page_insert_requested.connect(self._on_page_insert)
        thumb.page_rotate_requested.connect(self._on_page_rotate)
        thumb.page_resize_requested.connect(self._on_page_resize_from_thumb)

        return idx

    def _tab_for_canvas(self, canvas: PDFCanvas) -> tuple[int, _TabState] | None:
        for i, tab in enumerate(self._tabs):
            if tab.canvas is canvas:
                return i, tab
        return None

    def _update_tab_title(self, idx: int | None = None) -> None:
        if not hasattr(self, "_tab_widget") or not self._tabs:
            return
        if idx is None:
            idx = self._tab_idx
        if idx >= len(self._tabs):
            return
        tab = self._tabs[idx]
        name = tab.doc.path.name if tab.doc else "No document"
        suffix = " *" if tab.modified else ""
        self._tab_widget.setTabText(idx, name + suffix)
        if idx == self._tab_idx:
            base = f"PDF Tool — {name}" if tab.doc else "PDF Tool"
            self.setWindowTitle(base + suffix)

    # ── tab event handlers ────────────────────────────────────────────────────

    def _on_tab_changed(self, index: int) -> None:
        if index < 0 or index >= len(self._tabs):
            return
        self._tab_idx = index
        tab = self._tabs[index]
        self._update_tab_title(index)
        if tab.doc:
            self._apply_doc_permissions()
            self._status_page.setText(f"Page 1 / {tab.doc.page_count}")
        else:
            self._status_page.setText("No document")

    def _on_tab_close_requested(self, index: int) -> None:
        if len(self._tabs) == 1:
            # Last tab: clear content but keep the tab
            self._close_document()
            return

        tab = self._tabs[index]
        if tab.modified:
            # Temporarily point properties at the tab being closed
            prev_idx = self._tab_idx
            self._tab_idx = index
            ok = self._confirm_discard()
            self._tab_idx = prev_idx
            if not ok:
                return

        if tab.doc:
            tab.doc.close()
        self._tabs.pop(index)
        self._tab_widget.removeTab(index)
        # currentChanged fires automatically when needed; _on_tab_changed updates _tab_idx

    def _on_canvas_modified(self, canvas: PDFCanvas) -> None:
        result = self._tab_for_canvas(canvas)
        if result is None:
            return
        idx, tab = result
        tab.modified = True
        self._update_tab_title(idx)

    def _on_canvas_page_changed(self, canvas: PDFCanvas, page_num: int) -> None:
        result = self._tab_for_canvas(canvas)
        if result is None:
            return
        idx, tab = result
        if idx != self._tab_idx:
            return
        if tab.doc:
            self._status_page.setText(f"Page {page_num + 1} / {tab.doc.page_count}")
            tab.thumb_panel.highlight_page(page_num)

    def _build_menus(self) -> None:
        from PyQt6.QtWidgets import QStyle
        SP = QStyle.StandardPixmap
        mb = self.menuBar()

        file_menu = mb.addMenu("&File")
        self._act_open = QAction(_icon("document-open", SP.SP_DialogOpenButton), "&Open…", self, shortcut=QKeySequence.StandardKey.Open)
        self._act_save = QAction(_icon("document-save", SP.SP_DialogSaveButton), "&Save", self, shortcut=QKeySequence.StandardKey.Save)
        self._act_save_as = QAction(_icon("document-save-as"), "Save &As…", self, shortcut=QKeySequence("Ctrl+Shift+S"))
        self._act_close = QAction(_icon("document-close", SP.SP_DialogCloseButton), "&Close Tab", self, shortcut=QKeySequence.StandardKey.Close)

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
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_insert_page)

        doc_menu = mb.addMenu("&Document")
        self._act_properties = QAction(
            _icon("document-properties"), "&Properties…", self,
            shortcut=QKeySequence("Ctrl+Shift+P"),
        )
        self._act_scan = QAction(
            _icon_any("scanner", "image-x-generic", "document-export"),
            "Convert to &Scannered…", self,
        )
        self._act_scan.setToolTip("Rasterize all pages to images, strip fonts and vectors, minimize file size")
        self._act_compress_images = QAction(
            _icon_any("zoom-out", "image-x-generic"),
            "&Reduce Image DPI…", self,
        )
        self._act_compress_images.setToolTip("Downsample embedded images exceeding a target DPI to reduce file size")
        self._act_prune = QAction(
            _icon_any("edit-clear", "user-trash", "document-revert"),
            "&Prune…", self,
        )
        self._act_prune.setToolTip("Remove unused fonts, metadata, thumbnails, attachments to reduce file size")
        self._act_encrypt = QAction(
            _icon("document-encrypt"),
            "&Encrypt / Set Password…", self,
        )
        self._act_encrypt.setToolTip("Save an encrypted copy with owner and optional open passwords (AES-256)")
        self._act_unlock = QAction(
            _icon("document-unlock"),
            "&Unlock for Editing…", self,
        )
        self._act_unlock.setToolTip("Authenticate with owner password to unlock restricted editing")
        doc_menu.addAction(self._act_properties)
        doc_menu.addSeparator()
        doc_menu.addAction(self._act_encrypt)
        doc_menu.addAction(self._act_unlock)
        doc_menu.addSeparator()
        self._act_resize_pages = QAction(
            _icon_any("resize", "zoom-fit-best"),
            "Resize &Page(s)…", self,
        )
        self._act_resize_pages.setToolTip("Change page dimensions for current or all pages")
        doc_menu.addAction(self._act_scan)
        doc_menu.addAction(self._act_compress_images)
        doc_menu.addAction(self._act_resize_pages)
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

        self._act_rect_select = QAction(_icon("edit-rect-select"), "Rectangle Select", self, checkable=True)
        self._act_rect_select.setToolTip("Drag rectangle to select multiple objects (↓=inside, ↑=intersect)")

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

        self._act_signatures = QAction(
            _icon("mail-signed"),
            "Signatures…", self,
            shortcut=QKeySequence("Ctrl+Shift+G"))
        self._act_signatures.setToolTip("Manage and place signatures (Ctrl+Shift+G)")

        for act in (self._act_pan, self._act_select, self._act_rect_select, self._act_text, self._act_text_edit, self._act_rect):
            tb.addAction(act)
            act.triggered.connect(self._on_tool_selected)

        # Highlight tool button with color picker drop-down
        self._act_highlight.triggered.connect(self._on_tool_selected)
        _hl_btn = QToolButton(self)
        _hl_btn.setDefaultAction(self._act_highlight)
        _hl_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        _hl_menu = QMenu(_hl_btn)
        for _label, _rgb in (
            ("Yellow",     (1.0, 1.0, 0.0)),
            ("Orange",     (1.0, 0.6, 0.0)),
            ("Green",      (0.2, 0.9, 0.2)),
            ("Light Blue", (0.0, 0.8, 1.0)),
        ):
            _act = QAction(self._color_swatch(_rgb), _label, self)
            _act.setData(_rgb)
            _act.triggered.connect(self._on_highlight_color_selected)
            _hl_menu.addAction(_act)
        _hl_btn.setMenu(_hl_menu)
        tb.addWidget(_hl_btn)

        # Brush tool button with color + style drop-down
        self._act_brush = QAction(_icon("draw-brush"), "Brush", self, checkable=True)
        self._act_brush.setToolTip("Freehand brush drawing")
        self._act_brush.triggered.connect(self._on_tool_selected)
        _br_btn = QToolButton(self)
        _br_btn.setDefaultAction(self._act_brush)
        _br_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        _br_menu = QMenu(_br_btn)
        for _label, _rgb in (
            ("Black",  (0.0, 0.0, 0.0)),
            ("Blue",   (0.0, 0.0, 0.8)),
            ("Red",    (0.8, 0.0, 0.0)),
            ("Green",  (0.0, 0.55, 0.0)),
            ("Purple", (0.5, 0.0, 0.8)),
        ):
            _ca = QAction(self._color_swatch(_rgb), _label, self)
            _ca.setData(("color", _rgb))
            _ca.triggered.connect(self._on_brush_option_selected)
            _br_menu.addAction(_ca)
        _br_menu.addSeparator()
        self._brush_style_actions: list[QAction] = []
        for _slabel, _skey in (("Pen (thin)", "pen"), ("Brush (medium)", "brush"), ("Marker (wide)", "marker")):
            _sa = QAction(_slabel, self)
            _sa.setData(("style", _skey))
            _sa.setCheckable(True)
            _sa.setChecked(_skey == self._brush_style)
            _sa.triggered.connect(self._on_brush_option_selected)
            _br_menu.addAction(_sa)
            self._brush_style_actions.append(_sa)
        _br_menu.addSeparator()
        self._brush_smoothness_actions: list[QAction] = []
        for _smlab, _smkey in (("Normal", "normal"), ("Smooth", "smooth"), ("Very smooth", "max")):
            _sma = QAction(_smlab, self)
            _sma.setData(("smoothness", _smkey))
            _sma.setCheckable(True)
            _sma.setChecked(_smkey == self._brush_smoothness)
            _sma.triggered.connect(self._on_brush_option_selected)
            _br_menu.addAction(_sma)
            self._brush_smoothness_actions.append(_sma)
        _br_menu.addSeparator()
        self._act_brush_close = QAction("Close path", self)
        self._act_brush_close.setData(("close_path", None))
        self._act_brush_close.setCheckable(True)
        self._act_brush_close.setChecked(self._brush_close_path)
        self._act_brush_close.triggered.connect(self._on_brush_option_selected)
        _br_menu.addAction(self._act_brush_close)
        _br_btn.setMenu(_br_menu)
        tb.addWidget(_br_btn)

        # Encircle tool button with color picker
        self._act_encircle = QAction(_icon("draw-encircle"), "Encircle", self, checkable=True)
        self._act_encircle.setToolTip("Draw closed freehand shape to encircle content")
        self._act_encircle.triggered.connect(self._on_tool_selected)
        _ec_btn = QToolButton(self)
        _ec_btn.setDefaultAction(self._act_encircle)
        _ec_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        _ec_menu = QMenu(_ec_btn)
        for _label, _rgb in (
            ("Red",    (0.8, 0.0, 0.0)),
            ("Blue",   (0.0, 0.0, 0.8)),
            ("Black",  (0.0, 0.0, 0.0)),
            ("Green",  (0.0, 0.55, 0.0)),
            ("Purple", (0.5, 0.0, 0.8)),
        ):
            _eca = QAction(self._color_swatch(_rgb), _label, self)
            _eca.setData(_rgb)
            _eca.triggered.connect(self._on_encircle_color_selected)
            _ec_menu.addAction(_eca)
        _ec_btn.setMenu(_ec_menu)
        tb.addWidget(_ec_btn)

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
            self._act_rect_select: "rect_select",
            self._act_text: "text",
            self._act_text_edit: "text_edit",
            self._act_rect: "rect",
            self._act_highlight: "highlight",
            self._act_brush: "brush",
            self._act_encircle: "encircle",
        }

    def _connect_signals(self) -> None:
        self._act_open.triggered.connect(self._open_file)
        self._act_save.triggered.connect(self._save_file)
        self._act_save_as.triggered.connect(self._save_file_as)
        self._act_close.triggered.connect(lambda: self._on_tab_close_requested(self._tab_idx))
        self._act_undo.triggered.connect(self._undo)
        self._act_redo.triggered.connect(self._redo)
        self._act_properties.triggered.connect(self._edit_properties)
        # Lambdas so property is evaluated at call time, not connection time
        self._act_zoom_in.triggered.connect(lambda: self._canvas.zoom_in())
        self._act_zoom_out.triggered.connect(lambda: self._canvas.zoom_out())
        self._act_fit.triggered.connect(lambda: self._canvas.fit_width())
        self._act_img_file.triggered.connect(self._insert_image_file)
        self._act_img_paste.triggered.connect(self._insert_image_clipboard)
        self._act_send_back.triggered.connect(lambda: self._image_zorder(to_back=True))
        self._act_bring_front.triggered.connect(lambda: self._image_zorder(to_back=False))
        self._act_signatures.triggered.connect(self._open_signatures)
        self._act_encrypt.triggered.connect(self._encrypt_document)
        self._act_unlock.triggered.connect(self._unlock_document)
        self._act_scan.triggered.connect(self._convert_to_scanned)
        self._act_compress_images.triggered.connect(self._compress_images)
        self._act_resize_pages.triggered.connect(lambda: self._open_resize_dialog(None))
        self._act_prune.triggered.connect(self._prune_document)
        self._act_insert_page.triggered.connect(self._on_insert_page_toolbar)
        self._tab_widget.currentChanged.connect(self._on_tab_changed)
        self._tab_widget.tabCloseRequested.connect(self._on_tab_close_requested)

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
        files, _ = QFileDialog.getOpenFileNames(self, "Open PDF", start_dir, "PDF Files (*.pdf)")
        for f in files:
            self._load_path(Path(f))

    def _load_path(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "File not found", f"File not found:\n{path}")
            return
        if path.suffix.lower() != ".pdf":
            QMessageBox.warning(self, "Invalid file", f"Not a PDF file:\n{path}")
            return

        try:
            doc = PDFDocument(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open error", f"Failed to open PDF:\n{exc}")
            logger.exception("Failed to open PDF: %s", path)
            return

        if doc._doc.needs_pass:
            pw, ok = QInputDialog.getText(
                self, "Password required", "Enter document password:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not doc._doc.authenticate(pw):
                QMessageBox.critical(self, "Wrong password", "Incorrect password — document not opened.")
                doc.close()
                return

        # Use current tab if empty, otherwise open a new tab
        if self._doc is not None:
            new_idx = self._make_tab()
            self._tab_widget.setCurrentIndex(new_idx)
            # currentChanged fires synchronously → _on_tab_changed → self._tab_idx updated

        if self._doc:
            self._doc.close()

        self._tabs[self._tab_idx].doc = doc
        self._tabs[self._tab_idx].modified = False
        self._canvas.load_document(doc)
        self._thumb_panel.load_document(doc)
        self._update_tab_title()
        self._apply_doc_permissions()
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
            self._update_tab_title()
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
        """Close document in current tab, reset tab to empty state."""
        if not self._confirm_discard():
            return
        tab = self._tabs[self._tab_idx]
        if tab.doc:
            tab.doc.close()
            tab.doc = None
        tab.modified = False
        tab.canvas.document = None
        tab.canvas._scene.clear()
        tab.canvas._page_items.clear()
        tab.canvas._page_rects.clear()
        tab.thumb_panel._list.clear()
        for act in (self._act_select, self._act_rect_select,
                    self._act_text, self._act_text_edit,
                    self._act_img_file, self._act_img_paste,
                    self._act_insert_page,
                    self._act_send_back, self._act_bring_front,
                    self._act_signatures, self._act_rect, self._act_highlight,
                    self._act_properties, self._act_undo, self._act_redo):
            act.setEnabled(True)
        self._update_tab_title()
        self._status_page.setText("No document")

    # ── image insert ──────────────────────────────────────────────────────────

    def _start_image_insert(self, img_bytes: bytes) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return

        try:
            with Image.open(io.BytesIO(img_bytes)) as img:
                img.verify()
        except Exception as e:
            logger.warning("Invalid image data: %s", e)
            QMessageBox.critical(self, "Image error", "Invalid or corrupted image data.")
            return

        try:
            pm = fitz.Pixmap(img_bytes)
            w, h = pm.width, pm.height
        except Exception as e:
            logger.warning("Cannot read image dimensions: %s", e)
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
                garbage=4,
                deflate=True,
                clean=True,
            )
        finally:
            new_doc.close()

        QMessageBox.information(
            self, "Done",
            f"Scanned PDF saved:\n{out_path}"
        )

    # ── compress images ───────────────────────────────────────────────────────

    def _compress_images(self) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return

        from ui.compress_dialog import CompressImagesDialog
        default_dpi = int(self._settings.value(_COMPRESS_DPI_KEY, _COMPRESS_DPI_DEFAULT))

        path = self._doc.path
        file_size = path.stat().st_size if path.exists() else len(self._doc._doc.tobytes())

        dlg = CompressImagesDialog(self._doc._doc, file_size, default_dpi, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        dpi = dlg.target_dpi
        self._settings.setValue(_COMPRESS_DPI_KEY, dpi)

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Compressed PDF", str(self._doc.path.parent), "PDF files (*.pdf)"
        )
        if not out_path:
            return

        src_bytes = self._doc._doc.tobytes()
        work_doc = fitz.open(stream=src_bytes, filetype="pdf")
        reduced = 0
        skipped = 0

        try:
            processed_xrefs: set[int] = set()

            for page in work_doc:
                for info in page.get_image_info(xrefs=True):
                    xref: int = info.get("xref", 0)
                    if xref == 0 or xref in processed_xrefs:
                        continue
                    processed_xrefs.add(xref)

                    # Display rect in PDF points (72 pt = 1 inch)
                    bbox = info.get("bbox")
                    if not bbox:
                        continue
                    rect = fitz.Rect(bbox)
                    display_w_inch = rect.width / 72.0
                    if display_w_inch <= 0:
                        continue

                    try:
                        base_image = work_doc.extract_image(xref)
                    except Exception:
                        skipped += 1
                        continue

                    native_w: int = base_image["width"]
                    native_h: int = base_image["height"]
                    img_bytes: bytes = base_image["image"]

                    native_dpi = native_w / display_w_inch
                    if native_dpi <= dpi:
                        continue  # already within target

                    scale = dpi / native_dpi
                    new_w = max(1, int(native_w * scale))
                    new_h = max(1, int(native_h * scale))

                    try:
                        with Image.open(io.BytesIO(img_bytes)) as img:
                            has_alpha = img.mode in ("RGBA", "LA", "PA")
                            img_resized = img.resize((new_w, new_h), Image.LANCZOS)
                            buf = io.BytesIO()
                            if has_alpha:
                                img_resized.save(buf, format="PNG", optimize=True)
                            else:
                                if img_resized.mode not in ("RGB", "L"):
                                    img_resized = img_resized.convert("RGB")
                                img_resized.save(buf, format="JPEG", quality=85, optimize=True)
                        page.replace_image(xref, stream=buf.getvalue())
                        reduced += 1
                    except Exception as exc:
                        logger.warning("Could not replace image xref %d: %s", xref, exc)
                        skipped += 1

            work_doc.save(out_path, garbage=4, deflate=True, clean=True)
        finally:
            work_doc.close()

        msg = f"Reduced {reduced} image(s) to ≤{dpi} DPI."
        if skipped:
            msg += f"\n{skipped} image(s) skipped (unsupported format)."
        msg += f"\nSaved to:\n{out_path}"
        QMessageBox.information(self, "Done", msg)

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
        orig_size = (
            Path(orig_path).stat().st_size
            if orig_path and Path(orig_path).exists()
            else pruned_size
        )

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

    # ── permissions ───────────────────────────────────────────────────────────

    def _apply_doc_permissions(self) -> None:
        if not self._doc:
            return
        perms = self._doc._doc.permissions
        unlocked = perms == -4
        can_modify = unlocked or bool(perms & fitz.PDF_PERM_MODIFY)
        can_annotate = unlocked or bool(perms & (fitz.PDF_PERM_ANNOTATE | fitz.PDF_PERM_FORM))

        for act in (self._act_select, self._act_rect_select,
                    self._act_text, self._act_text_edit,
                    self._act_img_file, self._act_img_paste,
                    self._act_insert_page,
                    self._act_send_back, self._act_bring_front,
                    self._act_signatures):
            act.setEnabled(can_modify)
        for act in (self._act_rect, self._act_highlight, self._act_brush, self._act_encircle):
            act.setEnabled(can_annotate)

        self._act_properties.setEnabled(can_modify)
        self._act_undo.setEnabled(can_modify or can_annotate)
        self._act_redo.setEnabled(can_modify or can_annotate)

        if not (can_modify or can_annotate):
            for act in self._tool_actions:
                act.setChecked(act is self._act_pan)
            self._canvas.set_tool(None)

        page_count = self._doc.page_count
        lock_tag = "" if (can_modify and can_annotate) else "  🔒"
        self._status_page.setText(f"Page 1 / {page_count}{lock_tag}")
        self._act_unlock.setEnabled(perms != -4)

    def _unlock_document(self) -> None:
        if not self._doc:
            return
        pw, ok = QInputDialog.getText(
            self, "Owner password", "Enter owner password to unlock editing:",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        if not self._doc._doc.authenticate(pw):
            QMessageBox.critical(self, "Wrong password", "Incorrect owner password.")
            return
        self._apply_doc_permissions()

    # ── encrypt ───────────────────────────────────────────────────────────────

    def _encrypt_document(self) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        from ui.encrypt_dialog import EncryptDialog
        dlg = EncryptDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save Encrypted PDF", str(self._doc.path.parent), "PDF files (*.pdf)"
        )
        if not out_path:
            return
        try:
            self._doc._doc.save(
                out_path,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw=dlg.owner_password,
                user_pw=dlg.user_password,
                permissions=dlg.permissions,
                garbage=4,
                deflate=True,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Encrypt error", str(exc))
            return
        QMessageBox.information(self, "Done", f"Encrypted PDF saved:\n{out_path}")

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
        elif tool_name == "rect_select":
            self._canvas.set_tool(RectangleSelectTool(self._canvas))
        elif tool_name == "text":
            self._canvas.set_tool(TextAddTool(self._canvas))
        elif tool_name == "text_edit":
            self._canvas.set_tool(TextEditTool(self._canvas))
        elif tool_name == "rect":
            self._canvas.set_tool(RectAnnotateTool(self._canvas))
        elif tool_name == "highlight":
            self._canvas.set_tool(HighlightTool(self._canvas, self._highlight_color))
        elif tool_name == "brush":
            self._canvas.set_tool(BrushTool(
                self._canvas, self._brush_color, self._brush_style,
                self._brush_smoothness, self._brush_close_path,
            ))
        elif tool_name == "encircle":
            self._canvas.set_tool(EncircleTool(self._canvas, self._encircle_color))

    @staticmethod
    def _color_swatch(rgb: tuple[float, float, float]) -> QIcon:
        from PyQt6.QtGui import QPixmap, QColor
        pm = QPixmap(16, 16)
        pm.fill(QColor(int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)))
        return QIcon(pm)

    def _on_brush_option_selected(self) -> None:
        act = self.sender()
        kind, value = act.data()  # type: ignore[union-attr]
        if kind == "color":
            self._brush_color = value
        elif kind == "style":
            self._brush_style = value
            for a in self._brush_style_actions:
                a.setChecked(a.data()[1] == self._brush_style)
        elif kind == "smoothness":
            self._brush_smoothness = value
            for a in self._brush_smoothness_actions:
                a.setChecked(a.data()[1] == self._brush_smoothness)
        else:  # close_path
            self._brush_close_path = self._act_brush_close.isChecked()
        for a in self._tool_actions:
            a.setChecked(a is self._act_brush)
        self._canvas.set_tool(BrushTool(
            self._canvas, self._brush_color, self._brush_style,
            self._brush_smoothness, self._brush_close_path,
        ))

    def _on_encircle_color_selected(self) -> None:
        act = self.sender()
        self._encircle_color = act.data()  # type: ignore[union-attr]
        for a in self._tool_actions:
            a.setChecked(a is self._act_encircle)
        self._canvas.set_tool(EncircleTool(self._canvas, self._encircle_color))

    def _on_highlight_color_selected(self) -> None:
        act = self.sender()
        self._highlight_color = act.data()  # type: ignore[union-attr]
        for a in self._tool_actions:
            a.setChecked(a is self._act_highlight)
        self._canvas.set_tool(HighlightTool(self._canvas, self._highlight_color))

    def _commit_active_tool(self) -> None:
        tool = self._canvas._current_tool
        if hasattr(tool, "commit"):
            tool.commit()  # type: ignore[union-attr]

    # ── modified state ────────────────────────────────────────────────────────

    def _mark_modified(self) -> None:
        if not self._modified:
            self._modified = True  # setter calls _update_tab_title

    def _clear_modified(self) -> None:
        self._modified = False  # setter calls _update_tab_title

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
        pages = [self._doc.get_page_size(i) for i in range(self._doc.page_count)]
        dlg = PropertiesDialog(self._doc._doc.metadata, pages=pages, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        merged = dict(self._doc._doc.metadata)
        merged.update(dlg.result_meta)
        self._doc._doc.set_metadata(merged)
        self._mark_modified()

    # ── edit ─────────────────────────────────────────────────────────────────

    def _undo(self) -> None:
        if self._doc:
            result = self._canvas.history.undo(self._doc)
            if result is not None:
                if result == -1:
                    self._thumb_panel.refresh_thumbnails()
                    self._canvas.load_document(self._doc)
                elif result >= 0:
                    self._canvas.set_tool(None)
                    self._canvas.refresh_page(result)
                    self._canvas.viewport().update()
                self._clear_modified()

    def _redo(self) -> None:
        if self._doc:
            result = self._canvas.history.redo(self._doc)
            if result is not None:
                if result == -1:
                    self._thumb_panel.refresh_thumbnails()
                    self._canvas.load_document(self._doc)
                elif result >= 0:
                    self._canvas.set_tool(None)
                    self._canvas.refresh_page(result)
                    self._canvas.viewport().update()
                self._mark_modified()

    def closeEvent(self, event) -> None:
        for i, tab in enumerate(self._tabs):
            if tab.modified:
                self._tab_widget.setCurrentIndex(i)
                # currentChanged fires → _on_tab_changed → _tab_idx = i
                if not self._confirm_discard():
                    event.ignore()
                    return
        for tab in self._tabs:
            if tab.doc:
                tab.doc.close()
        event.accept()

    # ── status bar / page changed ─────────────────────────────────────────────

    def _on_page_changed(self, page_num: int) -> None:
        # Legacy slot kept for compatibility; per-tab version is _on_canvas_page_changed
        if self._doc:
            self._status_page.setText(f"Page {page_num + 1} / {self._doc.page_count}")
            self._thumb_panel.highlight_page(page_num)

    # ── page manipulation ─────────────────────────────────────────────────────

    def _on_insert_page_toolbar(self) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return

        current_page = self._canvas.page_at_scene_pos(self._canvas.mapToScene(self._canvas.viewport().rect().center()))
        if current_page is None:
            current_page = 0

        self._on_page_insert(current_page + 1)

    def _on_page_insert(self, index: int) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return

        ref_index = max(0, min(index - 1, self._doc.page_count - 1))
        if self._doc.page_count > 0:
            width, height = self._doc.get_page_size(ref_index)
        else:
            width, height = 595, 842  # Default A4

        cmd = InsertPageCmd(index, width, height)
        self._canvas.push_command(cmd, self._doc)
        self._mark_modified()

        self._thumb_panel.refresh_thumbnails()
        self._canvas.load_document(self._doc)
        self._status_page.setText(f"Page 1 / {self._doc.page_count}")

    def _on_page_delete(self, index: int) -> None:
        if not self._doc:
            return

        reply = QMessageBox.question(
            self,
            "Delete Page",
            f"Are you sure you want to delete page {index + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        cmd = DeletePageCmd(index)
        self._canvas.push_command(cmd, self._doc)
        self._mark_modified()

        self._thumb_panel.refresh_thumbnails()
        self._canvas.load_document(self._doc)

        if self._doc.page_count > 0:
            current = min(index, self._doc.page_count - 1)
            self._status_page.setText(f"Page {current + 1} / {self._doc.page_count}")
        else:
            self._status_page.setText("No pages")

    def _on_page_resize_from_thumb(self, index: int) -> None:
        self._open_resize_dialog(index)

    def _open_resize_dialog(self, page_index: int | None) -> None:
        if not self._doc:
            QMessageBox.warning(self, "No document", "Open a PDF first.")
            return
        from ui.resize_page_dialog import ResizePageDialog
        from core.history import GroupCmd

        # Determine which page to show current size for
        if page_index is None:
            # Use page currently visible in canvas
            page_index = self._canvas.page_at_scene_pos(
                self._canvas.mapToScene(self._canvas.viewport().rect().center())
            ) or 0

        current_w, current_h = self._doc.get_page_size(page_index)
        dlg = ResizePageDialog(current_w, current_h, self._doc.page_count, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        new_w, new_h = dlg.target_size_pt
        mode = dlg.content_mode

        if dlg.apply_all:
            cmds = [ResizePageCmd(i, new_w, new_h, mode) for i in range(self._doc.page_count)]
            cmd = GroupCmd(cmds, -1)
        else:
            cmd = ResizePageCmd(page_index, new_w, new_h, mode)

        self._canvas.push_command(cmd, self._doc)
        self._mark_modified()
        self._thumb_panel.refresh_thumbnails()
        self._canvas.load_document(self._doc)

    def _on_page_rotate(self, index: int, degrees: int) -> None:
        if not self._doc:
            return
        cmd = RotatePageCmd(index, degrees)
        self._canvas.push_command(cmd, self._doc)
        self._mark_modified()
        self._thumb_panel.refresh_thumbnails()
        self._canvas.load_document(self._doc)

    def _on_page_move(self, from_index: int, to_index: int) -> None:
        if not self._doc:
            return

        if from_index == to_index:
            return

        cmd = MovePageCmd(from_index, to_index)
        self._canvas.push_command(cmd, self._doc)
        self._mark_modified()

        self._thumb_panel.refresh_thumbnails()
        self._canvas.load_document(self._doc)
        self._thumb_panel.highlight_page(to_index)
        self._status_page.setText(f"Page {to_index + 1} / {self._doc.page_count}")
