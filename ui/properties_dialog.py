from __future__ import annotations

from datetime import datetime, timezone

from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QGroupBox,
)


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
    def __init__(self, meta: dict, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # ── read-only info ────────────────────────────────────────────────────
        info_box = QGroupBox("Document Info")
        info_form = QFormLayout(info_box)
        info_form.addRow("Format:", QLabel(meta.get("format", "") or "—"))
        info_form.addRow("Producer:", QLabel(meta.get("producer", "") or "—"))
        enc = meta.get("encryption")
        info_form.addRow("Encryption:", QLabel(enc if enc else "None"))
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
