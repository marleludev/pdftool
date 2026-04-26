from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from core.document import PDFDocument

logger = logging.getLogger(__name__)


class SaveWorker(QObject):
    """Run PDFDocument.save off the UI thread.

    The PDFDocument is touched from a worker thread; while save runs the UI
    must not call other mutating methods on the same document. MainWindow
    enforces this by disabling save actions while the worker is alive.
    """

    finished = pyqtSignal(object)  # emits Path
    failed = pyqtSignal(str)

    def __init__(self, doc: PDFDocument, out_path: Path) -> None:
        super().__init__()
        self._doc = doc
        self._out_path = Path(out_path)

    def run(self) -> None:
        try:
            self._doc.save(self._out_path)
        except Exception as exc:
            logger.exception("Background save failed for %s", self._out_path)
            self.failed.emit(str(exc))
            return
        self.finished.emit(self._out_path)
