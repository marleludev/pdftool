from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from core.history import EditTextCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas

BUILTIN_FONTS = {
    "Helvetica": "helv",
    "Helvetica Bold": "hebo",
    "Helvetica Oblique": "heob",
    "Times Roman": "tiro",
    "Times Bold": "tibo",
    "Times Italic": "tiit",
    "Courier": "cour",
    "Courier Bold": "cobo",
}


def _int_to_rgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _rgb_to_qcolor(r: float, g: float, b: float) -> QColor:
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class TextEditDialog(QDialog):
    def __init__(self, span: dict, page_fonts: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Text")
        self.setMinimumWidth(380)

        self._color: tuple[float, float, float] = _int_to_rgb(span.get("color", 0))

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        # original info
        orig_font = span.get("font", "unknown").split("+")[-1]
        form.addRow("Original font:", QLabel(f"{orig_font}  {span.get('size', 0):.1f}pt"))

        # text
        self._text_edit = QLineEdit(span.get("text", ""))
        form.addRow("Text:", self._text_edit)

        # font family
        self._font_combo = QComboBox()
        self._font_combo.addItems(list(BUILTIN_FONTS.keys()))
        for pf in page_fonts:
            if pf not in BUILTIN_FONTS:
                self._font_combo.addItem(pf)
        # try to pre-select closest match
        for i, name in enumerate(BUILTIN_FONTS.keys()):
            if any(part in orig_font.lower() for part in name.lower().split()):
                self._font_combo.setCurrentIndex(i)
                break
        form.addRow("Font:", self._font_combo)

        # font size
        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(4.0, 200.0)
        self._size_spin.setSingleStep(0.5)
        self._size_spin.setValue(round(span.get("size", 12), 1))
        form.addRow("Size (pt):", self._size_spin)

        # color
        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(60)
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        form.addRow("Color:", self._color_btn)

        # buttons
        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _pick_color(self) -> None:
        qc = _rgb_to_qcolor(*self._color)
        chosen = QColorDialog.getColor(qc, self, "Pick text color")
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._update_color_btn()

    def _update_color_btn(self) -> None:
        r, g, b = self._color
        self._color_btn.setStyleSheet(
            f"background-color: rgb({int(r*255)},{int(g*255)},{int(b*255)})"
        )

    @property
    def result_text(self) -> str:
        return self._text_edit.text()

    @property
    def result_size(self) -> float:
        return self._size_spin.value()

    @property
    def result_font(self) -> str:
        label = self._font_combo.currentText()
        return BUILTIN_FONTS.get(label, label)

    @property
    def result_color(self) -> tuple[float, float, float]:
        return self._color


class TextEditTool(AbstractTool):
    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if not self.canvas.document:
            return
        span = self._find_span(page_num, pdf_pos)
        if span is None:
            return

        page_fonts = self._page_font_names(page_num)
        dlg = TextEditDialog(span, page_fonts, parent=self.canvas)
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
            span.get("font", "helv"), orig_color,
            dlg.result_text, dlg.result_size,
            dlg.result_font, dlg.result_color,
        )
        self.canvas.push_command(cmd, self.canvas.document)
        self.canvas.refresh_page(page_num)

    def _find_span(self, page_num: int, pdf_pos: fitz.Point) -> dict | None:
        page = self.canvas.document.get_page(page_num)
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    if fitz.Rect(span["bbox"]).contains(pdf_pos):
                        return span
        return None

    def _page_font_names(self, page_num: int) -> list[str]:
        page = self.canvas.document.get_page(page_num)
        names = []
        for _, *_, name, _ in page.get_fonts():
            clean = name.split("+")[-1] if name else ""
            if clean and clean not in names and clean not in BUILTIN_FONTS:
                names.append(clean)
        return names
