from __future__ import annotations

import fitz

try:
    import qtawesome as qta
    QTA_AVAILABLE = True
except ImportError:
    QTA_AVAILABLE = False

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


def _icon(name: str) -> QIcon:
    """Get icon from qtawesome."""
    if QTA_AVAILABLE:
        try:
            return qta.icon(f"mdi.{name}", color="#555555")
        except Exception:
            pass
    return QIcon()


def _fmt_size(n: int) -> str:
    if n >= 1_048_576:
        return f"{n / 1_048_576:.1f} MB"
    if n >= 1_024:
        return f"{n / 1_024:.1f} KB"
    return f"{n} B"


def analyze_for_prune(doc: fitz.Document) -> list[dict]:
    """
    Inspect a fitz.Document and return a list of removable-item dicts:
      {"name": str, "count": int, "size": int, "note": str}
    """
    items: list[dict] = []

    # ── embedded font streams ─────────────────────────────────────────────────
    seen_fonts: set[int] = set()
    font_count = font_size = 0
    for pn in range(len(doc)):
        for f in doc.get_page_fonts(pn, full=True):
            xref = f[0]
            if not xref or xref in seen_fonts:
                continue
            seen_fonts.add(xref)
            try:
                buf = doc.extract_font(xref)[3]
                if buf:
                    font_count += 1
                    font_size += len(buf)
            except Exception:
                pass
    if font_count:
        items.append({
            "name": "Embedded font streams",
            "count": font_count,
            "size": font_size,
            "note": "Unused fonts removed; referenced fonts kept",
        })

    # ── XML metadata stream ───────────────────────────────────────────────────
    try:
        cat = doc.pdf_catalog()
        mk = doc.xref_get_key(cat, "Metadata")
        if mk[0] == "xref":
            mxref = int(mk[1].split()[0])
            if doc.xref_is_stream(mxref):
                sz = len(doc.xref_stream_raw(mxref))
                items.append({
                    "name": "XML Metadata stream",
                    "count": 1,
                    "size": sz,
                    "note": "XMP/RDF metadata embedded in catalog",
                })
    except Exception:
        pass

    # ── page thumbnails ───────────────────────────────────────────────────────
    thumb_count = thumb_size = 0
    for pn in range(len(doc)):
        try:
            pxref = doc.page_xref(pn)
            th = doc.xref_get_key(pxref, "Thumb")
            if th[0] == "xref":
                thumb_count += 1
                txref = int(th[1].split()[0])
                if doc.xref_is_stream(txref):
                    thumb_size += len(doc.xref_stream_raw(txref))
        except Exception:
            pass
    if thumb_count:
        items.append({
            "name": "Page thumbnails",
            "count": thumb_count,
            "size": thumb_size,
            "note": "Small preview images stored per page",
        })

    # ── embedded file attachments ─────────────────────────────────────────────
    try:
        ec = doc.embfile_count()
        if ec > 0:
            esz = 0
            for i in range(ec):
                try:
                    esz += len(doc.embfile_get(i))
                except Exception:
                    pass
            items.append({
                "name": "Embedded file attachments",
                "count": ec,
                "size": esz,
                "note": "Files attached to the document",
            })
    except Exception:
        pass

    # ── ICC color profiles ────────────────────────────────────────────────────
    icc_count = icc_size = 0
    try:
        for xref in range(1, doc.xref_length()):
            if not doc.xref_is_stream(xref):
                continue
            obj = doc.xref_object(xref, compressed=False)
            if "/ICCBased" in obj or ("/ColorSpace" in obj and "ICC" in obj):
                icc_count += 1
                icc_size += len(doc.xref_stream_raw(xref))
    except Exception:
        pass
    if icc_count:
        items.append({
            "name": "ICC color profiles",
            "count": icc_count,
            "size": icc_size,
            "note": "Embedded color space profiles",
        })

    # ── duplicate/orphaned objects (qualitative) ──────────────────────────────
    try:
        total_xrefs = doc.xref_length() - 1
        if total_xrefs > 0:
            items.append({
                "name": "Orphaned / duplicate objects",
                "count": total_xrefs,
                "size": 0,
                "note": f"{total_xrefs} total xrefs — garbage collection removes unreferenced ones",
            })
    except Exception:
        pass

    return items


class PruneDialog(QDialog):
    def __init__(
        self,
        parent,
        findings: list[dict],
        orig_size: int,
        pruned_size: int,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Prune PDF")
        self.setWindowIcon(_icon("content-cut"))
        self.setMinimumWidth(620)

        saving = orig_size - pruned_size
        pct = (saving / orig_size * 100) if orig_size else 0

        header = QLabel(
            f"<b>Current size:</b> {_fmt_size(orig_size)}  →  "
            f"<b>After prune:</b> {_fmt_size(pruned_size)}  "
            f"<span style='color:green'>(saves {_fmt_size(saving)}, {pct:.0f}%)</span>"
        )
        header.setTextFormat(Qt.TextFormat.RichText)

        table = QTableWidget(len(findings), 4)
        table.setHorizontalHeaderLabels(["Item", "Count", "Size", "Note"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        for row, item in enumerate(findings):
            sz_str = _fmt_size(item["size"]) if item["size"] > 0 else "—"
            for col, val in enumerate([item["name"], str(item["count"]), sz_str, item["note"]]):
                cell = QTableWidgetItem(val)
                cell.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | (
                    Qt.AlignmentFlag.AlignRight if col in (1, 2) else Qt.AlignmentFlag.AlignLeft
                ))
                table.setItem(row, col, cell)

        note = QLabel(
            "Prune saves to a <b>new file</b>. Current document is not modified."
        )
        note.setTextFormat(Qt.TextFormat.RichText)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Prune and Save As…")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        vbox = QVBoxLayout(self)
        vbox.addWidget(header)
        vbox.addWidget(table)
        vbox.addWidget(note)
        vbox.addWidget(buttons)
