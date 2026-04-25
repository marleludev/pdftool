from __future__ import annotations

from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
)

_PT_TO_MM = 25.4 / 72.0
_MM_TO_PT = 72.0 / 25.4

# (label, width_pt, height_pt) — always portrait order
PAPER_FORMATS: list[tuple[str, float, float]] = [
    ("A2",       1191, 1684),
    ("A3",        842, 1191),
    ("A4",        595,  842),
    ("A5",        420,  595),
    ("A6",        298,  420),
    ("Letter",    612,  792),
    ("Legal",     612, 1008),
    ("Tabloid",   792, 1224),
    ("Executive", 522,  756),
    ("Custom",      0,    0),
]

CONTENT_SCALE = "scale"
CONTENT_KEEP  = "keep"
CONTENT_CROP  = "crop"

_TOL = 3.0  # pt tolerance for format detection


def _detect_format(w_pt: float, h_pt: float) -> tuple[int, bool]:
    """Return (combo_index, is_landscape) for the given page size, or (Custom, False)."""
    for i, (_, pw, ph) in enumerate(PAPER_FORMATS):
        if pw == 0:
            continue
        if abs(w_pt - pw) < _TOL and abs(h_pt - ph) < _TOL:
            return i, False
        if abs(w_pt - ph) < _TOL and abs(h_pt - pw) < _TOL:
            return i, True
    return len(PAPER_FORMATS) - 1, False  # Custom


class ResizePageDialog(QDialog):
    def __init__(
        self,
        current_w: float,
        current_h: float,
        page_count: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Resize Page")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        # ── current size ──────────────────────────────────────────────────────
        cur_box = QGroupBox("Current page size")
        cur_form = QFormLayout(cur_box)
        cur_form.addRow(
            "Width × Height:",
            QLabel(
                f"{current_w * _PT_TO_MM:.1f} × {current_h * _PT_TO_MM:.1f} mm"
                f"  ({current_w:.0f} × {current_h:.0f} pt)"
            ),
        )
        layout.addWidget(cur_box)

        # ── target format ─────────────────────────────────────────────────────
        target_box = QGroupBox("Target page size")
        target_layout = QVBoxLayout(target_box)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self._fmt_combo = QComboBox()
        for name, w, h in PAPER_FORMATS:
            self._fmt_combo.addItem(name, (w, h))
        fmt_row.addWidget(self._fmt_combo, 1)
        target_layout.addLayout(fmt_row)

        orient_row = QHBoxLayout()
        self._portrait  = QRadioButton("Portrait")
        self._landscape = QRadioButton("Landscape")
        self._portrait.setChecked(True)
        orient_row.addWidget(self._portrait)
        orient_row.addWidget(self._landscape)
        orient_row.addStretch()
        target_layout.addLayout(orient_row)

        custom_form = QFormLayout()
        self._custom_w = QDoubleSpinBox()
        self._custom_h = QDoubleSpinBox()
        for sp in (self._custom_w, self._custom_h):
            sp.setRange(10.0, 10000.0)
            sp.setSuffix(" mm")
            sp.setDecimals(1)
            sp.setSingleStep(1.0)
        custom_form.addRow("Width:", self._custom_w)
        custom_form.addRow("Height:", self._custom_h)
        target_layout.addLayout(custom_form)

        self._preview_lbl = QLabel()
        target_layout.addWidget(self._preview_lbl)

        layout.addWidget(target_box)

        # ── apply to ─────────────────────────────────────────────────────────
        apply_box = QGroupBox("Apply to")
        apply_layout = QVBoxLayout(apply_box)
        self._apply_current = QRadioButton("Current page only")
        self._apply_all     = QRadioButton(f"All pages  ({page_count})")
        self._apply_current.setChecked(True)
        apply_layout.addWidget(self._apply_current)
        apply_layout.addWidget(self._apply_all)
        layout.addWidget(apply_box)

        # ── content handling ──────────────────────────────────────────────────
        content_box = QGroupBox("Content handling")
        content_layout = QVBoxLayout(content_box)
        self._radio_scale = QRadioButton("Scale content to fit new page")
        self._radio_keep  = QRadioButton("Keep content at original size (may add margins or clip)")
        self._radio_crop  = QRadioButton("Crop content to new dimensions")
        self._radio_scale.setChecked(True)
        self._content_grp = QButtonGroup(self)
        for rb in (self._radio_scale, self._radio_keep, self._radio_crop):
            content_layout.addWidget(rb)
            self._content_grp.addButton(rb)
        layout.addWidget(content_box)

        # ── buttons ───────────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # ── signals ───────────────────────────────────────────────────────────
        self._fmt_combo.currentIndexChanged.connect(self._on_format_changed)
        self._portrait.toggled.connect(self._update_preview)
        self._custom_w.valueChanged.connect(self._update_preview)
        self._custom_h.valueChanged.connect(self._update_preview)

        # Pre-select format matching current page
        fmt_idx, is_landscape = _detect_format(current_w, current_h)
        self._fmt_combo.setCurrentIndex(fmt_idx)
        if is_landscape:
            self._landscape.setChecked(True)
        self._on_format_changed(fmt_idx)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _on_format_changed(self, idx: int) -> None:
        w_pt, h_pt = self._fmt_combo.itemData(idx)
        is_custom = (w_pt == 0 and h_pt == 0)
        self._custom_w.setEnabled(is_custom)
        self._custom_h.setEnabled(is_custom)
        if not is_custom:
            self._custom_w.blockSignals(True)
            self._custom_h.blockSignals(True)
            self._custom_w.setValue(w_pt * _PT_TO_MM)
            self._custom_h.setValue(h_pt * _PT_TO_MM)
            self._custom_w.blockSignals(False)
            self._custom_h.blockSignals(False)
        self._update_preview()

    def _update_preview(self) -> None:
        w, h = self.target_size_pt
        self._preview_lbl.setText(
            f"→  {w * _PT_TO_MM:.1f} × {h * _PT_TO_MM:.1f} mm  ({w:.0f} × {h:.0f} pt)"
        )

    def _resolved_mm(self) -> tuple[float, float]:
        w = self._custom_w.value()
        h = self._custom_h.value()
        if self._landscape.isChecked():
            return max(w, h), min(w, h)
        return min(w, h), max(w, h)

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def target_size_pt(self) -> tuple[float, float]:
        w_mm, h_mm = self._resolved_mm()
        return w_mm * _MM_TO_PT, h_mm * _MM_TO_PT

    @property
    def apply_all(self) -> bool:
        return self._apply_all.isChecked()

    @property
    def content_mode(self) -> str:
        if self._radio_scale.isChecked():
            return CONTENT_SCALE
        if self._radio_keep.isChecked():
            return CONTENT_KEEP
        return CONTENT_CROP
