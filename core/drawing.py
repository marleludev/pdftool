"""Vector drawing helpers (translate / render).

Extracted from core.document so drawing primitives can be reused by command
modules without importing PDFDocument.
"""
from __future__ import annotations

import fitz


def _shift_point(p, dx: float, dy: float):
    if isinstance(p, fitz.Point):
        return fitz.Point(p.x + dx, p.y + dy)
    return fitz.Point(p[0] + dx, p[1] + dy)


def _shift_drawing(drw: dict, dx: float, dy: float) -> dict:
    """Return a new drawing dict with all geometry translated by (dx, dy)."""
    new_items = []
    for it in drw.get("items", []):
        op = it[0]
        args = []
        for a in it[1:]:
            if isinstance(a, fitz.Point):
                args.append(fitz.Point(a.x + dx, a.y + dy))
            elif isinstance(a, fitz.Rect):
                args.append(fitz.Rect(a.x0 + dx, a.y0 + dy, a.x1 + dx, a.y1 + dy))
            elif isinstance(a, fitz.Quad):
                args.append(fitz.Quad(
                    fitz.Point(a.ul.x + dx, a.ul.y + dy),
                    fitz.Point(a.ur.x + dx, a.ur.y + dy),
                    fitz.Point(a.ll.x + dx, a.ll.y + dy),
                    fitz.Point(a.lr.x + dx, a.lr.y + dy),
                ))
            else:
                args.append(a)
        new_items.append((op, *args))
    r = fitz.Rect(drw["rect"])
    shifted = dict(drw)
    shifted["items"] = new_items
    shifted["rect"] = fitz.Rect(r.x0 + dx, r.y0 + dy, r.x1 + dx, r.y1 + dy)
    return shifted


def _render_drawing(page: fitz.Page, drw: dict) -> None:
    """Render a drawing dict onto a page via fitz.Shape."""
    shape = page.new_shape()
    for it in drw.get("items", []):
        op = it[0]
        try:
            if op == "l":
                shape.draw_line(it[1], it[2])
            elif op == "re":
                shape.draw_rect(it[1])
            elif op == "qu":
                shape.draw_quad(it[1])
            elif op == "c":
                shape.draw_bezier(it[1], it[2], it[3], it[4])
            elif op == "v":
                shape.draw_bezier(it[1], it[1], it[2], it[3])
            elif op == "y":
                shape.draw_bezier(it[1], it[2], it[3], it[3])
        except Exception:
            continue
    dtype = drw.get("type", "s")
    color = drw.get("color") if dtype in ("s", "fs", "sf") else None
    fill = drw.get("fill") if dtype in ("f", "fs", "sf") else None
    shape.finish(
        color=color,
        fill=fill,
        width=drw.get("width") or 1.0,
        closePath=drw.get("closePath", False),
        even_odd=drw.get("even_odd", False),
    )
    shape.commit()
