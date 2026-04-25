from __future__ import annotations

from typing import NamedTuple

import fitz
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)


def _fmt_size(b: int) -> str:
    if b >= 1_000_000:
        return f"{b / 1_000_000:.1f} MB"
    if b >= 1_000:
        return f"{b / 1_000:.1f} KB"
    return f"{b} B"


class _ImageRecord(NamedTuple):
    compressed_bytes: int  # current size of image stream in bytes
    native_dpi: float      # effective DPI at largest display rect found


class CompressImagesDialog(QDialog):
    """Dialog that scans embedded images, shows current file size,
    and estimates the resulting size for a given target DPI."""

    def __init__(
        self,
        doc: fitz.Document,
        file_size: int,
        default_dpi: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Reduce Image DPI")
        self.setMinimumWidth(400)

        self._file_size = file_size
        self._records: list[_ImageRecord] = []
        self._non_image_size = file_size

        self._scan(doc)

        layout = QVBoxLayout(self)

        # Current document info
        info_box = QGroupBox("Current document")
        info_form = QFormLayout(info_box)
        info_form.addRow("File size:", QLabel(_fmt_size(file_size)))
        info_form.addRow("Embedded images found:", QLabel(str(len(self._records))))
        layout.addWidget(info_box)

        # Target DPI control
        target_box = QGroupBox("Target")
        target_form = QFormLayout(target_box)
        self._spin = QSpinBox()
        self._spin.setRange(72, 600)
        self._spin.setSingleStep(25)
        self._spin.setValue(default_dpi)
        self._spin.setSuffix(" DPI")
        target_form.addRow("Max image DPI:", self._spin)
        layout.addWidget(target_box)

        # Live estimate
        est_box = QGroupBox("Estimated result")
        est_form = QFormLayout(est_box)
        self._lbl_new_size = QLabel()
        self._lbl_savings = QLabel()
        self._lbl_affected = QLabel()
        est_form.addRow("New file size:", self._lbl_new_size)
        est_form.addRow("Savings:", self._lbl_savings)
        est_form.addRow("Images to downsample:", self._lbl_affected)
        layout.addWidget(est_box)

        note = QLabel(
            "Estimate is approximate. Opaque images re-encoded as JPEG quality 85; "
            "transparent images as PNG."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(note)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        self._spin.valueChanged.connect(self._update_estimate)
        self._update_estimate(default_dpi)

    @property
    def target_dpi(self) -> int:
        return self._spin.value()

    def _scan(self, doc: fitz.Document) -> None:
        processed: set[int] = set()
        # Track the largest display width seen per xref (highest DPI calculation)
        xref_max_display_w: dict[int, float] = {}
        xref_bytes: dict[int, int] = {}
        xref_native_w: dict[int, int] = {}

        for page in doc:
            for info in page.get_image_info(xrefs=True):
                xref: int = info.get("xref", 0)
                if xref == 0:
                    continue
                bbox = info.get("bbox")
                if not bbox:
                    continue
                rect = fitz.Rect(bbox)
                display_w = rect.width  # in PDF points

                if xref not in xref_max_display_w or display_w > xref_max_display_w[xref]:
                    xref_max_display_w[xref] = display_w

                if xref not in xref_bytes:
                    try:
                        base = doc.extract_image(xref)
                        xref_bytes[xref] = len(base["image"])
                        xref_native_w[xref] = base["width"]
                    except Exception:
                        xref_bytes[xref] = 0
                        xref_native_w[xref] = 0

        total_image_bytes = 0
        for xref, display_w_pt in xref_max_display_w.items():
            native_w = xref_native_w.get(xref, 0)
            img_bytes = xref_bytes.get(xref, 0)
            if native_w == 0 or display_w_pt <= 0 or img_bytes == 0:
                continue
            display_w_inch = display_w_pt / 72.0
            native_dpi = native_w / display_w_inch
            self._records.append(_ImageRecord(img_bytes, native_dpi))
            total_image_bytes += img_bytes

        # Approximate non-image overhead (text, fonts, structure)
        self._non_image_size = max(0, self._file_size - total_image_bytes)

    def _update_estimate(self, target_dpi: int) -> None:
        new_image_bytes = 0
        affected = 0

        for rec in self._records:
            if rec.native_dpi > target_dpi:
                scale = target_dpi / rec.native_dpi
                # Pixel area (and compressed size) scales roughly as scale²
                new_image_bytes += int(rec.compressed_bytes * scale * scale)
                affected += 1
            else:
                new_image_bytes += rec.compressed_bytes

        est_total = self._non_image_size + new_image_bytes
        savings = self._file_size - est_total
        pct = (savings / self._file_size * 100) if self._file_size > 0 else 0.0

        self._lbl_new_size.setText(_fmt_size(est_total))
        self._lbl_savings.setText(
            f"~{_fmt_size(savings)} ({pct:.0f}%)" if savings > 0 else "—"
        )
        self._lbl_affected.setText(f"{affected} of {len(self._records)}")
