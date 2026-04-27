from __future__ import annotations

import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, QRectF, Qt, QSettings
from PyQt6.QtGui import QColor, QMouseEvent, QPen
from PyQt6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsRectItem,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from core.history import AnnotationTextCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from ui.canvas import PDFCanvas


_ANNOT_FONT_FAMILY = "Architects Daughter"


def find_annotation_font_path() -> Path | None:
    """Return path to the Architects Daughter TTF/OTF if installed.

    fc-match always returns *something* — verify the resolved family actually
    matches before treating it as a hit, otherwise we'd silently substitute.
    """
    try:
        result = subprocess.run(
            ["fc-match", "--format=%{family[0]}|%{file}", _ANNOT_FONT_FAMILY],
            capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return None
    out = result.stdout.strip()
    if "|" not in out:
        return None
    family, file = out.split("|", 1)
    if "architects" not in family.lower():
        return None
    p = Path(file)
    if p.exists() and p.suffix.lower() in (".ttf", ".otf", ".ttc"):
        return p
    return None


# ── dialog ────────────────────────────────────────────────────────────────────

class AnnotationTextDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Insert Annotation Text")
        self.setMinimumWidth(420)
        self._color: tuple[float, float, float] = (0.15, 0.15, 0.75)

        # Load saved preferences
        settings = QSettings("PDFTool", "PDFTool")
        self._saved_font = settings.value("annotationFont", "DejaVu Sans", str)
        self._saved_size = settings.value("annotationFontSize", 12.0, float)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self._text_edit = QPlainTextEdit()
        self._text_edit.setMinimumHeight(120)
        self._text_edit.setPlaceholderText("Type annotation text…")
        form.addRow("Text:", self._text_edit)

        self._font_label = QLabel(self._saved_font)
        self._font_label.setStyleSheet("color: #666; font-size: 11px;")
        form.addRow("Font:", self._font_label)

        self._size_spin = QDoubleSpinBox()
        self._size_spin.setRange(4.0, 200.0)
        self._size_spin.setSingleStep(0.5)
        self._size_spin.setValue(self._saved_size)
        form.addRow("Size (pt):", self._size_spin)

        self._color_btn = QPushButton()
        self._color_btn.setFixedWidth(60)
        self._update_color_btn()
        self._color_btn.clicked.connect(self._pick_color)
        form.addRow("Color:", self._color_btn)

        layout.addLayout(form)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    def _pick_color(self) -> None:
        r, g, b = self._color
        chosen = QColorDialog.getColor(
            QColor(int(r * 255), int(g * 255), int(b * 255)),
            self, "Pick text color",
        )
        if chosen.isValid():
            self._color = (chosen.redF(), chosen.greenF(), chosen.blueF())
            self._update_color_btn()

    def _update_color_btn(self) -> None:
        r, g, b = self._color
        self._color_btn.setStyleSheet(
            f"background-color: rgb({int(r * 255)},{int(g * 255)},{int(b * 255)})"
        )

    @property
    def result_text(self) -> str:
        return self._text_edit.toPlainText()

    @property
    def result_size(self) -> float:
        return self._size_spin.value()

    @property
    def result_color(self) -> tuple[float, float, float]:
        return self._color


# ── tool ──────────────────────────────────────────────────────────────────────

class AnnotationTextTool(AbstractTool):
    """Draw a rect to define a wrapping text block, then place annotation
    text in it. The font is "Architects Daughter" if installed (embedded
    in the PDF); otherwise falls back to the built-in Helvetica face.
    """

    def __init__(self, canvas: "PDFCanvas") -> None:
        super().__init__(canvas)
        self._start_pdf: fitz.Point | None = None
        self._start_page: int | None = None
        self._rect_item: QGraphicsRectItem | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        self._start_pdf = pdf_pos
        self._start_page = page_num
        pen = QPen(QColor(0, 120, 215), 1.0, Qt.PenStyle.DashLine)
        scene_rect = self._scene_rect(page_num, pdf_pos, pdf_pos)
        self._rect_item = self.canvas.scene().addRect(scene_rect, pen)
        self._rect_item.setBrush(QColor(0, 120, 215, 25))

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rect_item is None or self._start_pdf is None or self._start_page is None:
            return
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        self._rect_item.setRect(self._scene_rect(self._start_page, self._start_pdf, pdf_pos))

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: QMouseEvent) -> None:
        if self._rect_item is None or self._start_pdf is None or self._start_page is None:
            return
        # remove rubber-band
        if self._rect_item.scene() is not None:
            self.canvas.scene().removeItem(self._rect_item)
        sp = self._start_pdf
        page = self._start_page
        self._rect_item = None
        self._start_pdf = None
        self._start_page = None

        rect = fitz.Rect(
            min(sp.x, pdf_pos.x), min(sp.y, pdf_pos.y),
            max(sp.x, pdf_pos.x), max(sp.y, pdf_pos.y),
        )
        if rect.width < 8 or rect.height < 8:
            return  # tap or sliver — ignore

        dlg = AnnotationTextDialog(parent=self.canvas)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        text = dlg.result_text
        if not text.strip():
            return
        cmd = AnnotationTextCmd(
            page, [rect.x0, rect.y0, rect.x1, rect.y1],
            text, dlg.result_size, dlg.result_color,
        )
        self.canvas.push_command(cmd, self.canvas.document)
        self.canvas.refresh_page(page)

    def cancel(self) -> None:
        if self._rect_item is not None and self._rect_item.scene() is not None:
            self.canvas.scene().removeItem(self._rect_item)
        self._rect_item = None
        self._start_pdf = None
        self._start_page = None

    def _scene_rect(self, page_num: int, p1: fitz.Point, p2: fitz.Point) -> QRectF:
        tl = self.canvas.pdf_to_scene(page_num, fitz.Point(min(p1.x, p2.x), min(p1.y, p2.y)))
        br = self.canvas.pdf_to_scene(page_num, fitz.Point(max(p1.x, p2.x), max(p1.y, p2.y)))
        return QRectF(tl, br)
