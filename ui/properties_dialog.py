from __future__ import annotations

from datetime import datetime, timezone

_PT_TO_MM = 25.4 / 72.0
_PT_TO_IN = 1.0 / 72.0

# (width_pt, height_pt) tolerances ±2 pt — portrait orientation
_PAPER_NAMES: list[tuple[float, float, str]] = [
    (595, 842,  "A4"),
    (420, 595,  "A5"),
    (744, 1052, "A3"),
    (1051, 1487, "A2"),
    (612, 792,  "Letter"),
    (612, 1008, "Legal"),
    (792, 1224, "Tabloid / A3"),
    (396, 612,  "Statement"),
    (522, 756,  "Executive"),
]


def _paper_name(w_pt: float, h_pt: float) -> str:
    """Return standard paper name or empty string."""
    for pw, ph, name in _PAPER_NAMES:
        if abs(w_pt - pw) <= 2 and abs(h_pt - ph) <= 2:
            return name
        if abs(w_pt - ph) <= 2 and abs(h_pt - pw) <= 2:
            return name + " (landscape)"
    return ""


def _fmt_page_size(w_pt: float, h_pt: float) -> str:
    w_mm = w_pt * _PT_TO_MM
    h_mm = h_pt * _PT_TO_MM
    w_in = w_pt * _PT_TO_IN
    h_in = h_pt * _PT_TO_IN
    name = _paper_name(w_pt, h_pt)
    base = f"{w_mm:.1f} × {h_mm:.1f} mm  ({w_in:.2f} × {h_in:.2f} in)"
    return f"{name}  —  {base}" if name else base

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QGroupBox,
)


from ui.sprite_icons import sprite_icon


def _icon(name: str) -> QIcon:
    """Return icon from the SVG sprite (see ui/sprite_icons.py)."""
    return sprite_icon(name)


def _parse_date(d: str) -> str:
    if not d:
        return ""
    s = d.lstrip("D:").split("+")[0].split("-")[0].split("Z")[0]
    try:
        return datetime.strptime(s[:14], "%Y%m%d%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return d


def _to_pdf_date(s: str) -> str:
    s = s.strip()
    if not s:
        return ""
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("D:%Y%m%d%H%M%S+00'00'")
    except Exception:
        return s


class PropertiesDialog(QDialog):
    def __init__(self, meta: dict, pages: list[tuple[float, float]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        self.setWindowIcon(_icon("file-cog"))
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # ── read-only info ────────────────────────────────────────────────────
        info_box = QGroupBox("Document Info")
        info_form = QFormLayout(info_box)
        info_form.addRow("Format:", QLabel(meta.get("format", "") or "—"))
        info_form.addRow("Producer:", QLabel(meta.get("producer", "") or "—"))
        enc = meta.get("encryption")
        info_form.addRow("Encryption:", QLabel(enc if enc else "None"))

        if pages:
            info_form.addRow("Pages:", QLabel(str(len(pages))))
            unique = list(dict.fromkeys(pages))  # preserve order, deduplicate
            if len(unique) == 1:
                w, h = unique[0]
                info_form.addRow("Page size:", QLabel(_fmt_page_size(w, h)))
            else:
                w0, h0 = unique[0]
                info_form.addRow("Page size:", QLabel(f"Various — Page 1: {_fmt_page_size(w0, h0)}"))

        layout.addWidget(info_box)

        # ── editable metadata ─────────────────────────────────────────────────
        edit_box = QGroupBox("Editable Metadata")
        edit_form = QFormLayout(edit_box)

        self._title    = QLineEdit(meta.get("title", "") or "")
        self._author   = QLineEdit(meta.get("author", "") or "")
        self._subject  = QLineEdit(meta.get("subject", "") or "")
        self._keywords = QLineEdit(meta.get("keywords", "") or "")
        self._creator  = QLineEdit(meta.get("creator", "") or "")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        self._created  = QLineEdit(_parse_date(meta.get("creationDate", "")) or now_str)
        self._modified = QLineEdit(_parse_date(meta.get("modDate", "")) or now_str)
        self._created.setPlaceholderText("YYYY-MM-DD HH:MM:SS")
        self._modified.setPlaceholderText("YYYY-MM-DD HH:MM:SS")

        edit_form.addRow("Title:", self._title)
        edit_form.addRow("Author:", self._author)
        edit_form.addRow("Subject:", self._subject)
        edit_form.addRow("Keywords:", self._keywords)
        edit_form.addRow("Creator:", self._creator)
        edit_form.addRow("Created:", self._created)
        edit_form.addRow("Modified:", self._modified)
        layout.addWidget(edit_box)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)

    @property
    def result_meta(self) -> dict:
        return {
            "title":        self._title.text(),
            "author":       self._author.text(),
            "subject":      self._subject.text(),
            "keywords":     self._keywords.text(),
            "creator":      self._creator.text(),
            "creationDate": _to_pdf_date(self._created.text()),
            "modDate":      _to_pdf_date(self._modified.text()),
        }
