from __future__ import annotations

import re
from dataclasses import dataclass, field

import fitz

_NUM_RE = re.compile(rb"^-?(\d+\.\d*|\d+|\.\d+)([eE][+-]?\d+)?$")
_WS = b" \t\r\n\f"

_PATH_CONSTR = {"m", "l", "c", "v", "y", "re", "h"}
_PATH_PAINT = {"S", "s", "f", "F", "f*", "B", "B*", "b", "b*", "n"}


def _tokenize(data: bytes) -> list[tuple[int, int, bytes]]:
    tokens: list[tuple[int, int, bytes]] = []
    i, n = 0, len(data)
    while i < n:
        while i < n and data[i : i + 1] in _WS:
            i += 1
        if i >= n:
            break
        if data[i : i + 1] == b"%":
            while i < n and data[i : i + 1] not in b"\r\n":
                i += 1
            continue
        s = i
        c = data[i : i + 1]
        if c == b"(":
            depth = 1
            i += 1
            while i < n and depth:
                cc = data[i : i + 1]
                if cc == b"\\":
                    i += 2
                elif cc == b"(":
                    depth += 1
                    i += 1
                elif cc == b")":
                    depth -= 1
                    i += 1
                else:
                    i += 1
        elif c == b"<":
            i += 1
            while i < n and data[i : i + 1] != b">":
                i += 1
            i += 1
        else:
            while i < n and data[i : i + 1] not in _WS:
                i += 1
        tokens.append((s, i, data[s:i]))
    return tokens


def _apply_mtx(m: list[float], x: float, y: float) -> tuple[float, float]:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def _mul_mtx(a: list[float], b: list[float]) -> list[float]:
    return [
        b[0] * a[0] + b[1] * a[2],
        b[0] * a[1] + b[1] * a[3],
        b[2] * a[0] + b[3] * a[2],
        b[2] * a[1] + b[3] * a[3],
        b[4] * a[0] + b[5] * a[2] + a[4],
        b[4] * a[1] + b[5] * a[3] + a[5],
    ]


@dataclass
class _QGroup:
    start: int
    end: int = -1
    paint_count: int = 0
    path_indices: list[int] = field(default_factory=list)


@dataclass
class _Path:
    start: int
    end: int
    bbox: fitz.Rect
    q_index: int  # -1 if naked


def strip_drawing(doc: fitz.Document, page: fitz.Page, drw: dict) -> bool:
    """Remove one vector path from the page content stream without touching anything else.

    PyMuPDF has no direct API for deleting a single path; redaction would also
    erase overlapping text/images.  Instead we tokenise the raw stream bytes,
    track q/Q graphics-state groups, find the path whose bbox matches drw['rect'],
    and splice out exactly the bytes that define it.

    If the target path is the only painted path inside its q…Q group, the
    entire group (including cm, w, gs setup operators) is removed.  Otherwise
    only the path construction + paint operators are removed, leaving the
    surrounding graphics state intact for other paths in the same group.

    Returns True on success, False if the path could not be found or the
    stream contains inline images (BI…EI), which would break byte offsets.
    """
    try:
        page.clean_contents()
        xrefs = page.get_contents()
        if not xrefs:
            return False
        xref = xrefs[0]
        data = doc.xref_stream(xref)
        if data is None:
            return False
    except Exception:
        return False

    if b"\nBI\n" in data or b" BI\n" in data or b"\nBI " in data:
        return False

    page_h = page.rect.height
    target = fitz.Rect(drw["rect"])
    tol = max((drw.get("width") or 1) * 2.0, 2.0)

    tokens = _tokenize(data)
    stack: list[float] = []
    mtx_stack: list[list[float]] = [[1.0, 0.0, 0.0, 1.0, 0.0, 0.0]]
    q_groups: list[_QGroup] = []
    q_active: list[int] = []  # indices into q_groups
    paths: list[_Path] = []
    path_start: int | None = None
    path_min: list[float] | None = None
    path_max: list[float] | None = None

    def upd(x: float, y: float) -> None:
        nonlocal path_min, path_max
        fy = page_h - y
        if path_min is None:
            path_min = [x, fy]
            path_max = [x, fy]
        else:
            if x < path_min[0]:
                path_min[0] = x
            if fy < path_min[1]:
                path_min[1] = fy
            if x > path_max[0]:
                path_max[0] = x
            if fy > path_max[1]:
                path_max[1] = fy

    def close_path(end_byte: int) -> None:
        nonlocal path_start, path_min, path_max
        if path_start is None or path_min is None or path_max is None:
            path_start = None
            path_min = None
            path_max = None
            return
        bbox = fitz.Rect(path_min[0], path_min[1], path_max[0], path_max[1])
        q_idx = q_active[-1] if q_active else -1
        paths.append(_Path(path_start, end_byte, bbox, q_idx))
        if q_idx >= 0:
            q_groups[q_idx].paint_count += 1
            q_groups[q_idx].path_indices.append(len(paths) - 1)
        path_start = None
        path_min = None
        path_max = None

    for s, e, tok in tokens:
        if _NUM_RE.match(tok):
            try:
                stack.append(float(tok))
            except ValueError:
                stack.clear()
            continue
        op = tok.decode("latin-1", errors="ignore")

        if op == "q":
            q_groups.append(_QGroup(start=s))
            q_active.append(len(q_groups) - 1)
            mtx_stack.append(list(mtx_stack[-1]))
        elif op == "Q":
            if q_active:
                q_groups[q_active[-1]].end = e
                q_active.pop()
            if len(mtx_stack) > 1:
                mtx_stack.pop()
        elif op == "cm" and len(stack) >= 6:
            a, b, c, d, e_, f = stack[-6:]
            mtx_stack[-1] = _mul_mtx(mtx_stack[-1], [a, b, c, d, e_, f])
        elif op in _PATH_CONSTR:
            if path_start is None:
                path_start = s
            if op == "m" and len(stack) >= 2:
                x, y = _apply_mtx(mtx_stack[-1], stack[-2], stack[-1])
                upd(x, y)
            elif op == "l" and len(stack) >= 2:
                x, y = _apply_mtx(mtx_stack[-1], stack[-2], stack[-1])
                upd(x, y)
            elif op == "c" and len(stack) >= 6:
                for i in range(0, 6, 2):
                    x, y = _apply_mtx(mtx_stack[-1], stack[-6 + i], stack[-5 + i])
                    upd(x, y)
            elif op in ("v", "y") and len(stack) >= 4:
                for i in range(0, 4, 2):
                    x, y = _apply_mtx(mtx_stack[-1], stack[-4 + i], stack[-3 + i])
                    upd(x, y)
            elif op == "re" and len(stack) >= 4:
                x, y, w, h = stack[-4:]
                for px, py in ((x, y), (x + w, y), (x + w, y + h), (x, y + h)):
                    xt, yt = _apply_mtx(mtx_stack[-1], px, py)
                    upd(xt, yt)
        elif op in _PATH_PAINT:
            close_path(e)
        stack.clear()

    # find matching path
    match_idx = -1
    for i, p in enumerate(paths):
        r = p.bbox
        if (
            abs(r.x0 - target.x0) < tol
            and abs(r.x1 - target.x1) < tol
            and abs(r.y0 - target.y0) < tol
            and abs(r.y1 - target.y1) < tol
        ):
            match_idx = i
            break

    if match_idx < 0:
        return False

    p = paths[match_idx]
    if p.q_index >= 0:
        g = q_groups[p.q_index]
        if g.paint_count == 1 and g.end > 0:
            s_byte, e_byte = g.start, g.end
        else:
            s_byte, e_byte = p.start, p.end
    else:
        s_byte, e_byte = p.start, p.end

    new_data = data[:s_byte] + data[e_byte:]
    try:
        doc.update_stream(xref, new_data)
    except Exception:
        return False
    return True
