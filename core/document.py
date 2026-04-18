from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import fitz

def _needs_unicode(text: str) -> bool:
    try:
        text.encode("latin-1")
        return False
    except (UnicodeEncodeError, UnicodeDecodeError):
        return True


def _find_unicode_font() -> str | None:
    try:
        result = subprocess.run(
            ["fc-match", ":charset=20ac", "--format=%{file}"],
            capture_output=True, timeout=2,
        )
        path = result.stdout.decode().strip()
        if path and Path(path).exists():
            return path
    except Exception:
        pass
    for candidate in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


BUILTIN_FONT_MAP = {
    "helv": ["helvetica", "arial", "arialmt", "helveticaneue"],
    "tiro": ["timesnewroman", "times", "timesroman"],
    "cour": ["courier", "couriernew"],
    "hebo": ["helvetica-bold", "arial-bold", "arialmt-bold"],
    "tibo": ["times-bold", "timesnewroman-bold"],
    "cobo": ["courier-bold", "couriernew-bold"],
    "heob": ["helvetica-oblique", "helvetica-italic", "arial-italic"],
    "tiit": ["times-italic", "timesnewroman-italic"],
}


def _int_to_rgb(c: int) -> tuple[float, float, float]:
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _builtin_for_name(name: str) -> str | None:
    clean = name.split("+")[-1].lower().replace(" ", "").replace("-", "")
    for key, aliases in BUILTIN_FONT_MAP.items():
        for alias in aliases:
            if alias.replace("-", "") in clean or clean in alias.replace("-", ""):
                return key
    return None


class PDFDocument:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._doc = fitz.open(str(path))

    @property
    def page_count(self) -> int:
        return len(self._doc)

    def get_page(self, page_num: int) -> fitz.Page:
        return self._doc[page_num]

    def render_page(self, page_num: int, scale: float = 1.5) -> fitz.Pixmap:
        page = self._doc[page_num]
        mat = fitz.Matrix(scale, scale)
        return page.get_pixmap(matrix=mat, alpha=False)

    # ── annotations (immediately applied, xref returned for undo) ────────────

    def apply_highlight(self, page_num: int, quads: list) -> int:
        page = self._doc[page_num]
        fitz_quads = [fitz.Quad(q) for q in quads]
        annot = page.add_highlight_annot(fitz_quads)
        return annot.xref

    def apply_rect_annot(self, page_num: int, rect: list, color: list, width: float) -> int:
        page = self._doc[page_num]
        annot = page.add_rect_annot(fitz.Rect(rect))
        annot.set_colors(stroke=tuple(color))
        annot.set_border(width=width)
        annot.update()
        return annot.xref

    def delete_annotation(self, page_num: int, xref: int) -> None:
        page = self._doc[page_num]
        annot = page.load_annot(xref)
        if annot:
            page.delete_annot(annot)

    # ── text operations ───────────────────────────────────────────────────────

    def apply_text_insert(
        self,
        page_num: int,
        rect: list,
        text: str,
        fontsize: float = 12,
        font_name: str = "helv",
        color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> None:
        font = self._resolve_font(page_num, font_name, text)
        page = self._doc[page_num]
        tw = fitz.TextWriter(page.rect)
        # baseline = top of rect + fontsize
        tw.append((rect[0], rect[1] + fontsize), text, font=font, fontsize=fontsize)
        tw.write_text(page, color=color)

    def apply_text_move(
        self,
        page_num: int,
        src_bbox: list,
        current_origin: list,
        new_origin: list,
        text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
    ) -> list:
        """Redact source area, reinsert only spans that actually disappeared, move span."""
        font = self._resolve_font(page_num, font_name, text)
        page = self._doc[page_num]
        src_rect = fitz.Rect(src_bbox)
        ox, oy = current_origin[0], current_origin[1]

        # Snapshot all spans before redaction
        def _get_spans(pg: fitz.Page) -> list[dict]:
            spans = []
            for block in pg.get_text("dict")["blocks"]:
                if block.get("type") != 0:
                    continue
                for line in block["lines"]:
                    spans.extend(line["spans"])
            return spans

        def _span_key(s: dict) -> tuple:
            return (round(s["origin"][0], 1), round(s["origin"][1], 1), s["text"])

        spans_before = _get_spans(page)
        keys_before = {_span_key(s): s for s in spans_before}

        page.add_redact_annot(src_rect)
        page.apply_redactions()

        keys_after = {_span_key(s) for s in _get_spans(page)}

        # Reinsert spans that actually disappeared, except the moved span itself
        for key, span in keys_before.items():
            if key in keys_after:
                continue  # survived redaction — do not duplicate
            sx, sy = span["origin"]
            if abs(sx - ox) < 2 and abs(sy - oy) < 2:
                continue  # this is the moved span — intentionally removed
            c = span["color"]
            sc = ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0
            sf = self._resolve_font(page_num, span["font"], span["text"])
            stw = fitz.TextWriter(page.rect)
            stw.append(fitz.Point(sx, sy), span["text"], font=sf, fontsize=span["size"])
            stw.write_text(page, color=sc)

        tw = fitz.TextWriter(page.rect)
        text_rect, _ = tw.append(fitz.Point(new_origin[0], new_origin[1]), text, font=font, fontsize=fontsize)
        tw.write_text(page, color=color)
        return [text_rect.x0, text_rect.y0, text_rect.x1, text_rect.y1]

    def apply_text_edit(
        self,
        page_num: int,
        span_bbox: tuple | list,
        span_origin: tuple | list,
        new_text: str,
        fontsize: float,
        font_name: str,
        color: tuple[float, float, float],
    ) -> list:
        """Redact old text, insert new text via TextWriter; return actual bbox for undo."""
        font = self._resolve_font(page_num, font_name, new_text)
        page = self._doc[page_num]
        page.add_redact_annot(fitz.Rect(span_bbox))
        page.apply_redactions()
        tw = fitz.TextWriter(page.rect)
        text_rect, _ = tw.append(
            fitz.Point(span_origin[0], span_origin[1]),
            new_text,
            font=font,
            fontsize=fontsize,
        )
        tw.write_text(page, color=color)
        return [text_rect.x0, text_rect.y0, text_rect.x1, text_rect.y1]

    def _resolve_font(self, page_num: int, font_name: str, text: str = "") -> fitz.Font:
        """Return a fitz.Font suitable for rendering text (handles Unicode / embedded fonts)."""
        if text and _needs_unicode(text):
            uf = _find_unicode_font()
            if uf:
                return fitz.Font(fontfile=uf)

        if font_name in BUILTIN_FONT_MAP:
            return fitz.Font(fontname=font_name)

        builtin = _builtin_for_name(font_name)
        if builtin:
            return fitz.Font(fontname=builtin)

        # try embedded font — only TTF/OTF work with fitz.Font(fontbuffer=)
        page = self._doc[page_num]
        clean_name = font_name.split("+")[-1].lower()
        for xref, *_, name, _ in page.get_fonts():
            if not (name and name.lower().replace(" ", "") == clean_name.replace(" ", "")):
                continue
            try:
                _, ext, _, font_data, _ = self._doc.extract_font(xref)
                if font_data and ext in ("ttf", "otf"):
                    return fitz.Font(fontbuffer=font_data)
            except Exception:
                pass

        # system font via fc-match
        try:
            result = subprocess.run(
                ["fc-match", font_name, "--format=%{file}"],
                capture_output=True, timeout=2,
            )
            path = result.stdout.decode().strip()
            if path and Path(path).exists():
                return fitz.Font(fontfile=path)
        except Exception:
            pass

        return fitz.Font(fontname="helv")

    # ── persist ───────────────────────────────────────────────────────────────

    def save(self, output_path: Path) -> None:
        self._doc.save(str(output_path), garbage=4, deflate=True)

    def close(self) -> None:
        self._doc.close()
