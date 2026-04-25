from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent, QPixmap
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from core.history import EditTextCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

BUILTIN_FONTS = {
    "Helvetica":         "helv",
    "Helvetica Bold":    "hebo",
    "Helvetica Oblique": "heob",
    "Times Roman":       "tiro",
    "Times Bold":        "tibo",
    "Times Italic":      "tiit",
    "Courier":           "cour",
    "Courier Bold":      "cobo",
}

_PICK_SYSTEM = "── System font… ──"

_FLAG_NAMES = {1: "Superscript", 2: "Italic", 4: "Serif", 8: "Monospace", 16: "Bold"}


# ── helpers ───────────────────────────────────────────────────────────────────

def _int_to_rgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _rgb_to_qcolor(r: float, g: float, b: float) -> QColor:
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def _color_swatch(r: float, g: float, b: float) -> QLabel:
    lbl = QLabel()
    lbl.setFixedSize(16, 16)
    pm = QPixmap(16, 16)
    pm.fill(QColor(int(r * 255), int(g * 255), int(b * 255)))
    lbl.setPixmap(pm)
    return lbl


def _flags_str(flags: int) -> str:
    parts = [name for bit, name in _FLAG_NAMES.items() if flags & bit]
    return ", ".join(parts) if parts else "Regular"


def _dir_str(d: tuple) -> str:
    dx, dy = d
    if dx > 0.9:   return "Left → Right"
    if dx < -0.9:  return "Right → Left"
    if dy > 0.9:   return "Bottom → Top"
    if dy < -0.9:  return "Top → Bottom"
    return f"({dx:.2f}, {dy:.2f})"


def _find_font_file(family: str, style: str = "") -> Path | None:
    try:
        query = f"{family}:style={style}" if style else family
        result = subprocess.run(
            ["fc-match", "--format=%{file}", query],
            capture_output=True, text=True, timeout=3,
        )
        p = Path(result.stdout.strip())
        if p.exists() and p.suffix.lower() in (".ttf", ".otf", ".ttc"):
            return p
    except Exception:
        pass
    return None


def _avg_char_pitch(chars: list) -> float | None:
    """Average x-distance between consecutive char origins (horizontal text)."""
    origs = [ch["origin"][0] for ch in chars if ch.get("c", " ") != " "]
    if len(origs) < 2:
        return None
    diffs = [origs[i + 1] - origs[i] for i in range(len(origs) - 1) if origs[i + 1] > origs[i]]
    return sum(diffs) / len(diffs) if diffs else None


# ── dialog ────────────────────────────────────────────────────────────────────

class TextEditDialog(QDialog):
    def __init__(self, span: dict, font_bytes: bytes | None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Text")
        self.setMinimumWidth(460)

        self._orig_font_bytes   = font_bytes
        self._system_font_bytes: bytes | None = None
        self._color: tuple[float, float, float] = _int_to_rgb(span.get("color", 0))

        layout = QVBoxLayout(self)

        # ── read-only info panel ──────────────────────────────────────────
        layout.addWidget(self._build_info_panel(span, font_bytes))

        # ── editable fields ───────────────────────────────────────────────
        edit_box = QGroupBox("Edit")
        form = QFormLayout(edit_box)

        # rawdict spans don't always carry a top-level "text" key; reconstruct
        # from individual char entries so the field is never blank.
        current_text = span.get("text") or "".join(
            ch.get("c", "") for ch in span.get("chars", [])
        )
        self._text_edit = QLineEdit(current_text)
        form.addRow("Text:", self._text_edit)

        self._orig_font_name = span.get("font", "helv")
        # Strip subset prefix (e.g. "ABCDEF+CourierNewPS-BoldMT" → "CourierNewPS-BoldMT")
        # so the user sees the real face name, not a meaningless hex tag.
        font_clean = self._orig_font_name.split("+")[-1]
        self._orig_label = f"Original: {font_clean}"

        self._font_combo = QComboBox()
        self._font_combo.addItem(self._orig_label)
        for label in BUILTIN_FONTS:
            self._font_combo.addItem(label)
        self._font_combo.addItem(_PICK_SYSTEM)
        self._font_combo.setCurrentIndex(0)
        form.addRow("Font:", self._font_combo)

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(4.0, 200.0)
        self._size_spin.setSingleStep(0.5)
        self._size_spin.setValue(round(span.get("size", 12), 2))
        form.addRow("Size (pt):", self._size_spin)

        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(60)
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        form.addRow("Color:", self._color_btn)

        layout.addWidget(edit_box)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

        self._font_combo.currentIndexChanged.connect(self._on_font_index_changed)

    # ── info panel builder ────────────────────────────────────────────────────

    def _build_info_panel(self, span: dict, font_bytes: bytes | None) -> QGroupBox:
        box = QGroupBox("Original text properties")
        form = QFormLayout(box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        size       = span.get("size", 0.0)
        flags      = span.get("flags", 0)
        ascender   = span.get("ascender", 0.8)
        descender  = span.get("descender", -0.2)
        origin     = span.get("origin", [0.0, 0.0])
        bbox       = span.get("bbox", [0.0, 0.0, 0.0, 0.0])
        font_full  = span.get("font", "?")
        font_clean = font_full.split("+")[-1]
        chars      = span.get("chars", [])
        direction  = span.get("_dir", (1.0, 0.0))
        wmode      = span.get("_wmode", 0)

        line_h     = (ascender - descender) * size
        bbox_w     = bbox[2] - bbox[0]
        bbox_h     = bbox[3] - bbox[1]
        r, g, b    = self._color
        hex_color  = f"#{int(r*255):02X}{int(g*255):02X}{int(b*255):02X}"
        embedded   = "✓ embedded" if font_bytes else "✗ not embedded"
        pitch      = _avg_char_pitch(chars)

        form.addRow("Font:",        QLabel(f"{font_clean}  ({embedded})"))
        form.addRow("Full name:",   QLabel(font_full))
        form.addRow("Style:",       QLabel(_flags_str(flags)))
        form.addRow("Size:",        QLabel(f"{size:.2f} pt"))

        color_row = QLabel(f" {hex_color}")
        color_row.setStyleSheet(
            f"background-color: {hex_color}; color: {'#000' if (r+g+b)>1.5 else '#fff'};"
            "padding: 1px 6px; border-radius: 3px;"
        )
        form.addRow("Color:", color_row)

        form.addRow("Ascender:",    QLabel(f"{ascender:.4f}  →  {ascender * size:.2f} pt"))
        form.addRow("Descender:",   QLabel(f"{descender:.4f}  →  {descender * size:.2f} pt"))
        form.addRow("Line height:", QLabel(f"~{line_h:.2f} pt"))
        form.addRow("Bbox:",        QLabel(f"{bbox_w:.2f} × {bbox_h:.2f} pt"))
        form.addRow("Origin:",      QLabel(f"({origin[0]:.2f}, {origin[1]:.2f}) pt"))
        form.addRow("Direction:",   QLabel(_dir_str(direction)))
        form.addRow("Writing:",     QLabel("Horizontal" if wmode == 0 else "Vertical"))
        form.addRow("Characters:",  QLabel(str(len(span.get("text", "")))))
        if pitch is not None:
            form.addRow("Avg char pitch:", QLabel(f"{pitch:.3f} pt"))

        return box

    # ── slots ──────────────────────────────────────────────────────────────────

    def _on_font_index_changed(self, _: int) -> None:
        if self._font_combo.currentText() == _PICK_SYSTEM:
            self._pick_system_font()

    def _pick_system_font(self) -> None:
        font, ok = QFontDialog.getFont(self)
        if not ok:
            self._font_combo.setCurrentIndex(0)
            return
        family = font.family()
        style  = font.styleName() or ""
        path = _find_font_file(family, style) or _find_font_file(family)
        if path is None:
            QMessageBox.warning(
                self, "Font not found",
                f"Could not locate a TTF/OTF file for '{family}'.\n"
                "Install the font or choose a different one.",
            )
            self._font_combo.setCurrentIndex(0)
            return
        self._system_font_bytes = path.read_bytes()
        self._font_combo.setItemText(
            self._font_combo.currentIndex(), f"System: {family}"
        )

    def _pick_color(self) -> None:
        chosen = QColorDialog.getColor(_rgb_to_qcolor(*self._color), self, "Pick text color")
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._update_color_btn()

    def _update_color_btn(self) -> None:
        r, g, b = self._color
        self._color_btn.setStyleSheet(
            f"background-color: rgb({int(r*255)},{int(g*255)},{int(b*255)})"
        )

    # ── result properties ──────────────────────────────────────────────────────

    @property
    def result_text(self) -> str:
        return self._text_edit.text()

    @property
    def result_size(self) -> float:
        return self._size_spin.value()

    @property
    def result_font(self) -> str:
        # Index 0 = "Original: …" item — pass the raw stored name so document.py
        # can re-resolve the same embedded font without a name round-trip.
        if self._font_combo.currentIndex() == 0:
            return self._orig_font_name
        return BUILTIN_FONTS.get(self._font_combo.currentText(), "helv")

    @property
    def result_font_bytes(self) -> bytes | None:
        # Check by index, not label text, so a renamed "System: …" entry is
        # still detected correctly after _pick_system_font relabels item 2.
        if self._font_combo.currentIndex() == 0:
            return self._orig_font_bytes
        label = self._font_combo.currentText()
        if label.startswith("System:") or label == _PICK_SYSTEM:
            return self._system_font_bytes
        return None  # built-in fitz fonts need no bytes

    @property
    def result_color(self) -> tuple[float, float, float]:
        return self._color


# ── tool ──────────────────────────────────────────────────────────────────────

class TextEditTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if not self.canvas.document:
            return
        span = self._find_span(page_num, pdf_pos)
        if span is None:
            return

        font_bytes = self.canvas.document.get_span_font_bytes(page_num, span.get("font", ""))

        dlg = TextEditDialog(span, font_bytes, parent=self.canvas)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        orig_c = span.get("color", 0)
        orig_color: tuple[float, float, float] = (
            ((orig_c >> 16) & 0xFF) / 255.0,
            ((orig_c >> 8) & 0xFF) / 255.0,
            (orig_c & 0xFF) / 255.0,
        )
        cmd = EditTextCmd(
            page_num,
            list(span["bbox"]),
            list(span["origin"]),
            span.get("text", ""), span.get("size", 12.0),
            span.get("font", "helv"), orig_color, font_bytes,
            dlg.result_text, dlg.result_size,
            dlg.result_font, dlg.result_color, dlg.result_font_bytes,
        )
        self.canvas.push_command(cmd, self.canvas.document)
        self.canvas.refresh_page(page_num)

    def _find_span(self, page_num: int, pdf_pos: fitz.Point) -> dict | None:
        """Return span dict from rawdict (includes chars, ascender, descender, flags)
        with line-level dir and wmode injected as _dir and _wmode."""
        page = self.canvas.document.get_page(page_num)
        for block in page.get_text("rawdict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if fitz.Rect(span["bbox"]).contains(pdf_pos):
                        result = dict(span)
                        result["_dir"]   = line.get("dir", (1.0, 0.0))
                        result["_wmode"] = line.get("wmode", 0)
                        return result
        return None
