from __future__ import annotations

from typing import TYPE_CHECKING

import fitz
from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsPathItem

from core.history import AddAnnotCmd
from tools.base import AbstractTool

if TYPE_CHECKING:
    from PyQt6.QtGui import QMouseEvent
    from ui.canvas import PDFCanvas


# style → (stroke_width_pt, opacity)
BRUSH_STYLES: dict[str, tuple[float, float]] = {
    "pen":    (1.5,  1.0),
    "brush":  (3.5,  0.85),
    "marker": (10.0, 0.35),
}

# smoothness → (douglas-peucker epsilon in PDF pts, chaikin iterations)
# Higher epsilon discards more near-collinear points before smoothing.
SMOOTHNESS_PRESETS: dict[str, tuple[float, int]] = {
    "normal": (1.0, 2),
    "smooth": (4.0, 3),
    "max":    (10.0, 4),
}

_MIN_PTS = 2


def _pt_line_dist(p: list[float], a: list[float], b: list[float]) -> float:
    """Perpendicular distance from point p to line a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0 and dy == 0:
        return ((p[0] - a[0]) ** 2 + (p[1] - a[1]) ** 2) ** 0.5
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return ((p[0] - a[0] - t * dx) ** 2 + (p[1] - a[1] - t * dy) ** 2) ** 0.5


def _douglas_peucker(pts: list[list[float]], epsilon: float) -> list[list[float]]:
    """Ramer-Douglas-Peucker path simplification."""
    if len(pts) < 3:
        return pts
    dmax, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = _pt_line_dist(pts[i], pts[0], pts[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > epsilon:
        left  = _douglas_peucker(pts[:idx + 1], epsilon)
        right = _douglas_peucker(pts[idx:],     epsilon)
        return left[:-1] + right
    return [pts[0], pts[-1]]


def _chaikin(pts: list[list[float]], iterations: int = 3) -> list[list[float]]:
    """Chaikin corner-cutting for open paths.

    First and last points are preserved as anchors so the stroke starts and
    ends at the original mouse-down / mouse-up positions.
    """
    for _ in range(iterations):
        if len(pts) < 2:
            break
        result: list[list[float]] = [pts[0]]
        for i in range(len(pts) - 1):
            x0, y0 = pts[i]
            x1, y1 = pts[i + 1]
            result.append([0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1])
            result.append([0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1])
        result.append(pts[-1])
        pts = result
    return pts


def _chaikin_closed(pts: list[list[float]], iterations: int = 3) -> list[list[float]]:
    """Chaikin corner-cutting for closed paths.

    Unlike the open variant, no endpoints are fixed — all joints including
    last→first are treated equally via modular indexing.  This avoids the
    visible kink that would appear at the closing join if the open variant
    were used on a closed stroke.
    """
    for _ in range(iterations):
        n = len(pts)
        if n < 2:
            break
        result: list[list[float]] = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            result.append([0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1])
            result.append([0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1])
        pts = result
    return pts


class BrushTool(AbstractTool):
    def __init__(
        self,
        canvas: "PDFCanvas",
        color: tuple[float, float, float] = (0.0, 0.0, 0.8),
        style: str = "pen",
        smoothness: str = "normal",
        close_path: bool = False,
    ) -> None:
        super().__init__(canvas)
        self._color = color
        self._style = style
        self._close_path = close_path
        self._width, self._opacity = BRUSH_STYLES.get(style, BRUSH_STYLES["pen"])
        self._dp_epsilon, self._chaikin_iters = SMOOTHNESS_PRESETS.get(smoothness, SMOOTHNESS_PRESETS["normal"])

        self._page_num: int | None = None
        self._pdf_pts: list[list[float]] = []
        self._scene_pts: list[QPointF] = []
        self._preview: QGraphicsPathItem | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        self._page_num = page_num
        self._pdf_pts = [[pdf_pos.x, pdf_pos.y]]
        self._scene_pts = [QPointF(scene_pos)]

        r, g, b = (int(c * 255) for c in self._color)
        pen = QPen(QColor(r, g, b, int(self._opacity * 230)), self._width * 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCosmetic(True)

        self._preview = QGraphicsPathItem()
        self._preview.setPen(pen)
        self._preview.setBrush(QColor(0, 0, 0, 0))
        self.canvas.scene().addItem(self._preview)

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        if self._preview is None:
            return
        self._pdf_pts.append([pdf_pos.x, pdf_pos.y])
        self._scene_pts.append(QPointF(scene_pos))
        path = QPainterPath(self._scene_pts[0])
        for pt in self._scene_pts[1:]:
            path.lineTo(pt)
        if self._close_path:
            path.closeSubpath()
        self._preview.setPath(path)

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        if self._preview is not None:
            self.canvas.scene().removeItem(self._preview)
            self._preview = None

        if self._page_num is None or len(self._pdf_pts) < _MIN_PTS:
            self._reset()
            return

        simplified = _douglas_peucker(self._pdf_pts, self._dp_epsilon)
        if self._close_path:
            smoothed = _chaikin_closed(simplified, iterations=self._chaikin_iters)
            smoothed = smoothed + [smoothed[0]]
        else:
            smoothed = _chaikin(simplified, iterations=self._chaikin_iters)
        cmd = AddAnnotCmd(
            self._page_num,
            "ink",
            {
                "strokes": [smoothed],
                "color": list(self._color),
                "width": self._width,
                "opacity": self._opacity,
            },
        )
        if self.canvas.document:
            self.canvas.push_command(cmd, self.canvas.document)
            self.canvas.refresh_page(self._page_num)

        self._reset()

    def cancel(self) -> None:
        if self._preview is not None:
            self.canvas.scene().removeItem(self._preview)
            self._preview = None
        self._reset()

    def _reset(self) -> None:
        self._page_num = None
        self._pdf_pts = []
        self._scene_pts = []


class EncircleTool(AbstractTool):
    """Freehand closed polygon annotation for encircling document areas."""

    _MIN_PTS = 3

    def __init__(
        self,
        canvas: "PDFCanvas",
        color: tuple[float, float, float] = (0.8, 0.0, 0.0),
        width: float = 0.5,
        smoothness: str = "smooth",
    ) -> None:
        super().__init__(canvas)
        self._color = color
        self._width = width
        self._dp_epsilon, self._chaikin_iters = SMOOTHNESS_PRESETS.get(smoothness, SMOOTHNESS_PRESETS["smooth"])

        self._page_num: int | None = None
        self._pdf_pts: list[list[float]] = []
        self._scene_pts: list[QPointF] = []
        self._preview: QGraphicsPathItem | None = None

    def on_press(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        self._page_num = page_num
        self._pdf_pts = [[pdf_pos.x, pdf_pos.y]]
        self._scene_pts = [QPointF(scene_pos)]

        r, g, b = (int(c * 255) for c in self._color)
        pen = QPen(QColor(r, g, b, 220), self._width * 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCosmetic(True)

        self._preview = QGraphicsPathItem()
        self._preview.setPen(pen)
        self._preview.setBrush(QColor(r, g, b, 70))
        self.canvas.scene().addItem(self._preview)

    def on_move(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        if self._preview is None:
            return
        self._pdf_pts.append([pdf_pos.x, pdf_pos.y])
        self._scene_pts.append(QPointF(scene_pos))
        path = QPainterPath(self._scene_pts[0])
        for pt in self._scene_pts[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        self._preview.setPath(path)

    def on_release(self, page_num: int, pdf_pos: fitz.Point, scene_pos: QPointF, event: "QMouseEvent") -> None:
        if self._preview is not None:
            self.canvas.scene().removeItem(self._preview)
            self._preview = None

        if self._page_num is None or len(self._pdf_pts) < self._MIN_PTS:
            self._reset()
            return

        simplified = _douglas_peucker(self._pdf_pts, self._dp_epsilon)
        smoothed = _chaikin_closed(simplified, iterations=self._chaikin_iters)

        cmd = AddAnnotCmd(
            self._page_num,
            "polygon",
            {
                "points": smoothed,
                "color": list(self._color),
                "width": self._width,
            },
        )
        if self.canvas.document:
            self.canvas.push_command(cmd, self.canvas.document)
            self.canvas.refresh_page(self._page_num)

        self._reset()

    def cancel(self) -> None:
        if self._preview is not None:
            self.canvas.scene().removeItem(self._preview)
            self._preview = None
        self._reset()

    def _reset(self) -> None:
        self._page_num = None
        self._pdf_pts = []
        self._scene_pts = []
