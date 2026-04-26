"""Group command: bundle multiple commands into one undo/redo step."""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.history import Command

if TYPE_CHECKING:
    from core.document import PDFDocument


class GroupCmd(Command):
    """Wrap multiple commands into one atomic undo/redo step."""

    def __init__(self, cmds: "list[Command]", page_num: int) -> None:
        self._cmds = cmds
        self._page_num = page_num

    def execute(self, doc: "PDFDocument") -> None:
        for cmd in self._cmds:
            cmd.execute(doc)

    def undo(self, doc: "PDFDocument") -> None:
        for cmd in reversed(self._cmds):
            cmd.undo(doc)
