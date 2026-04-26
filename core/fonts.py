"""Font resolution helpers for PDF rendering.

Extracted from core.document so font logic can be reused by command modules
without importing PDFDocument.
"""
from __future__ import annotations

import logging
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import fitz

logger = logging.getLogger(__name__)


def _needs_unicode(text: str) -> bool:
    """Check if text contains characters outside Latin-1 encoding."""
    try:
        text.encode("latin-1")
        return False
    except (UnicodeEncodeError, UnicodeDecodeError):
        return True


@lru_cache(maxsize=1)
def _find_unicode_font() -> str | None:
    """Find a system font that supports Unicode characters.

    Uses fc-match to find a suitable font, falling back to common system fonts.
    Result is cached to avoid repeated subprocess calls.
    """
    try:
        result = subprocess.run(
            ["fc-match", ":charset=20ac", "--format=%{file}"],
            capture_output=True,
            timeout=2,
        )
        path = result.stdout.decode().strip()
        if path and Path(path).exists():
            logger.debug("Found Unicode font via fc-match: %s", path)
            return path
    except Exception as e:
        logger.debug("fc-match failed: %s", e)

    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
        "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/noto/NotoSans-Regular.ttf",
        "/usr/share/fonts/google-noto/NotoSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            logger.debug("Found Unicode font via fallback: %s", candidate)
            return candidate

    logger.warning("No Unicode font found")
    return None


# Normalised family name substrings → fitz built-in family key.
# "nimbus*" are the free PostScript substitutes bundled with Ghostscript/Linux:
#   NimbusMonoPS ≈ Courier,  NimbusSans ≈ Helvetica,  NimbusR ≈ Times.
_FAMILY_KEYS = {
    "helv": ["helvetica", "arial", "nimbussans", "freesans"],
    "tiro": ["times", "timesnewroman", "nimbusr", "freeserif"],
    "cour": ["courier", "couriernew", "nimbusmonops", "nimbusmono", "freemono"],
}

# (is_bold, is_italic) → fitz built-in font name per family.
# Courier has no oblique built-in so italic maps to regular "cour".
_STYLE_MAP = {
    "helv": {(False, False): "helv", (True, False): "hebo", (False, True): "heob", (True, True): "hebo"},
    "tiro": {(False, False): "tiro", (True, False): "tibo", (False, True): "tiit", (True, True): "tiit"},
    "cour": {(False, False): "cour", (True, False): "cobo", (False, True): "cour", (True, True): "cobo"},
}

_FITZ_BUILTINS = {"helv", "hebo", "heob", "tiro", "tibo", "tiit", "cour", "cobo"}


def _int_to_rgb(c: int) -> tuple[float, float, float]:
    """Convert integer color to RGB float tuple."""
    return ((c >> 16) & 0xFF) / 255.0, ((c >> 8) & 0xFF) / 255.0, (c & 0xFF) / 255.0


def _builtin_for_name(name: str) -> str | None:
    """Map any font name (including PostScript variants) to a fitz built-in identifier.

    PDF span font names often use PostScript conventions that differ from the
    PDF basefont name: "CourierNewPS-BoldMT", "NimbusMonoPS-Regular", "ArialMT".
    Strip the PostScript markers (PS, MT, OT) first, then detect bold/italic
    from keywords, then match family — so style is determined before the
    family lookup, not after.
    """
    base = name.split("+")[-1]
    norm = re.sub(r"(?i)(PS|MT|OT)", "", base)
    norm = re.sub(r"[-_ ]", "", norm).lower()
    is_bold = "bold" in norm
    is_italic = "italic" in norm or "oblique" in norm
    family = re.sub(
        r"(bold|italic|oblique|regular|roman|medium|narrow|cond|light|thin|semi|demi|extra|black)",
        "",
        norm,
    )
    for base_key, variants in _FAMILY_KEYS.items():
        for v in variants:
            if v in family or family in v:
                return _STYLE_MAP[base_key][(is_bold, is_italic)]
    return None


def resolve_font(
    fitz_doc: fitz.Document,
    page_num: int,
    font_name: str,
    text: str = "",
) -> fitz.Font:
    """Resolve a font name to a fitz.Font object.

    Handles Unicode text, embedded fonts, and system font lookups. Falls back
    to Helvetica when nothing else matches.
    """
    if text and _needs_unicode(text):
        uf = _find_unicode_font()
        if uf:
            return fitz.Font(fontfile=uf)

    if font_name in _FITZ_BUILTINS:
        return fitz.Font(fontname=font_name)

    builtin = _builtin_for_name(font_name)
    if builtin:
        return fitz.Font(fontname=builtin)

    page = fitz_doc[page_num]
    clean_name = font_name.split("+")[-1].lower().replace(" ", "")
    for font_info in page.get_fonts():
        xref = font_info[0]
        basefont = font_info[3]  # /BaseFont
        fname = font_info[4]     # font name
        candidate = (basefont or fname or "").split("+")[-1].lower().replace(" ", "")
        if not candidate or candidate != clean_name:
            continue
        try:
            _, ext, _, font_data, _ = fitz_doc.extract_font(xref)
            if font_data:
                return fitz.Font(fontbuffer=font_data)
        except Exception as e:
            logger.debug("Failed to extract embedded font: %s", e)

    try:
        result = subprocess.run(
            ["fc-match", font_name, "--format=%{file}"],
            capture_output=True,
            timeout=2,
        )
        path = result.stdout.decode().strip()
        if path and Path(path).exists():
            return fitz.Font(fontfile=path)
    except Exception as e:
        logger.debug("fc-match for font %r failed: %s", font_name, e)

    return fitz.Font(fontname="helv")
