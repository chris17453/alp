"""Rendering: the ALP script as images (RFC-ALP-001 v1.1 §6) and documents.

§6.2 assembly model — a composition renders as one block::

              [ modal | epistemic ]
                       |
    [ causal ] ---  HEAD   --- [ scalar ]
                       |
              [ temporal | valence ]

    roles descend beneath the block as an ordered stack

No conforming font exists yet, so blocks are drawn procedurally: the head is a
class-0 shape at full weight in the block centre, modifiers attach as marks in
their class position, roles stack beneath, and residue rides under everything
as a ribbon (it is English, and the RFC wants it visibly so).  The ASCII
transliteration (§6.5) is always printed alongside — the script is a rendering
of it, not a replacement.

Two output paths share one document model:

    Doc = [Heading | Para | Blocks | Rule | Spacer]
    render_png(doc)  -> list[PIL.Image]      (paginated)
    render_pdf(doc)  -> bytes                (reportlab; selectable text)

§6.1 is explicit: the script buys human audit, not compression.  Nothing here
should be fed to a model.
"""

from __future__ import annotations

import io
import math
import os
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence, Union

from PIL import Image, ImageDraw, ImageFont

from .alpb import Pid
from . import inventory as inv
from .composition import Composition, Node

# ---------------------------------------------------------------------------
# Palette (class -> colour) and glyph tables
# ---------------------------------------------------------------------------

CLASS_COLOR = {
    inv.CLASS_ONTOLOGICAL: (34, 34, 40),
    inv.CLASS_MODAL: (86, 61, 176),
    inv.CLASS_SCALAR: (198, 108, 26),
    inv.CLASS_TEMPORAL: (26, 128, 160),
    inv.CLASS_CAUSAL: (176, 46, 60),
    inv.CLASS_EPISTEMIC: (48, 132, 72),
    inv.CLASS_ILLOCUTIONARY: (150, 70, 140),
    inv.CLASS_VALENCE: (150, 130, 20),
    inv.CLASS_STRUCTURAL: (120, 120, 120),
}

# Short marks for modifiers (2-4 chars) so a block stays legible when small.
ABBREV = {
    "AFFIRM": "AFF", "NEGATE": "NEG", "POSSIBLE": "POS", "NECESSARY": "NEC",
    "DESIRED": "DES", "HYPOTHETICAL": "HYP", "PERMITTED": "PERM", "FORBIDDEN": "FORB",
    "NONE": "0", "SOME": "SOME", "ALL": "ALL", "LOW": "LO", "MID": "MID", "HIGH": "HI",
    "EXTREME": "MAX", "BOUNDED": "BND", "UNBOUNDED": "UNB", "INCREASE": "▲", "DECREASE": "▼",
    "PAST": "PAST", "NOW": "NOW", "FUTURE": "FUT", "DURATIVE": "DUR", "PUNCTUAL": "PNCT",
    "BEFORE": "BEF", "DURING": "DURG", "AFTER": "AFT", "REPEAT": "REP", "BEGIN": "BEG", "END": "END",
    "CAUSE": "CAUS", "ENABLE": "ENAB", "PREVENT": "PREV", "CORRELATE": "CORR", "DEPEND": "DEP",
    "TRIGGER": "TRIG",
    "KNOWN": "KNWN", "BELIEVED": "BLV", "INFERRED": "INF", "UNKNOWN": "UNK", "CONTESTED": "CNT",
    "OBSERVED": "OBS", "PREDICTED": "PRED",
    "ASSERT": "ASRT", "REQUEST": "REQ", "COMMIT": "CMT", "QUERY": "QRY", "WARN": "WARN",
    "REFUSE": "REF!", "PROPOSE": "PROP", "ACKNOWLEDGE": "ACK",
    "GOOD": "GOOD", "BAD": "BAD", "REQUIRED": "REQD", "OPTIONAL": "OPT", "SAFE": "SAFE",
    "HARM": "HARM", "COST": "COST", "BENEFIT": "BEN",
    "ENTITY": "ENT", "PROCESS": "PROC", "PROPERTY": "PROP", "RELATION": "REL", "QUANTITY": "QTY",
    "AGENT": "AGT", "STATE": "STAT", "PLACE": "PLC", "MOMENT": "MOM", "SIGN": "SIGN",
    "EVENT": "EVT", "GROUP": "GRP",
}

# Head shapes: one per ontological primitive, distinguishable at a glance.
HEAD_SHAPE = {
    "ENTITY": "square", "PROCESS": "arrow", "PROPERTY": "diamond", "RELATION": "bowtie",
    "QUANTITY": "bars", "AGENT": "pentagon", "STATE": "circle", "PLACE": "pin",
    "MOMENT": "clock", "SIGN": "flag", "EVENT": "burst", "GROUP": "cluster",
}

# Where a modifier class attaches (§6.2).
POSITION = {
    inv.CLASS_MODAL: "top", inv.CLASS_EPISTEMIC: "top",
    inv.CLASS_CAUSAL: "left", inv.CLASS_SCALAR: "right",
    inv.CLASS_TEMPORAL: "bottom", inv.CLASS_VALENCE: "bottom",
    inv.CLASS_ILLOCUTIONARY: "corner",
}

_FONT_CANDIDATES = {
    "sans": ["DejaVuSans.ttf", "NotoSans-Regular.ttf", "NotoSans[wght].ttf", "LiberationSans-Regular.ttf", "Arial.ttf"],
    "bold": ["DejaVuSans-Bold.ttf", "NotoSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf"],
    "mono": ["DejaVuSansMono.ttf", "NotoSansMono-Regular.ttf", "NotoSansMono[wght].ttf", "LiberationMono-Regular.ttf", "Courier New.ttf"],
}
_FONT_DIRS = [
    "/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts"),
    os.path.expanduser("~/.local/share/fonts"), "/Library/Fonts", "/System/Library/Fonts",
    "C:\\Windows\\Fonts",
]
_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}
_font_path_cache: dict[str, str | None] = {}


def _find_font(kind: str) -> str | None:
    if kind in _font_path_cache:
        return _font_path_cache[kind]
    names = _FONT_CANDIDATES[kind]
    found = None
    for d in _FONT_DIRS:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for n in names:
                if n in files:
                    found = os.path.join(root, n)
                    break
            if found:
                break
        if found:
            break
    _font_path_cache[kind] = found
    return found


def font(kind: str = "sans", size: int = 14):
    key = (kind, size)
    if key not in _font_cache:
        path = _find_font(kind)
        try:
            f = ImageFont.truetype(path, size) if path else ImageFont.load_default(size)
        except Exception:  # noqa: BLE001
            f = ImageFont.load_default()
        _font_cache[key] = f
    return _font_cache[key]


def text_size(draw: ImageDraw.ImageDraw, s: str, f) -> tuple[int, int]:
    box = draw.textbbox((0, 0), s, font=f)
    return box[2] - box[0], box[3] - box[1]


# ---------------------------------------------------------------------------
# Block rendering
# ---------------------------------------------------------------------------

@dataclass
class BlockStyle:
    size: int = 160            # head square side
    mark_h: int = 22
    pad: int = 10
    bg: tuple = (255, 255, 255)
    fg: tuple = (30, 30, 30)
    show_residue: bool = True
    show_caption: bool = True  # transliteration + SID below the block


def _polygon(cx: float, cy: float, r: float, n: int, rot: float = -math.pi / 2) -> list[tuple[float, float]]:
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n), cy + r * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]


def _draw_head(d: ImageDraw.ImageDraw, name: str, cx: float, cy: float, r: float, color) -> None:
    shape = HEAD_SHAPE.get(name, "circle")
    w = max(2, int(r / 9))
    if shape == "square":
        d.rectangle([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
    elif shape == "circle":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
    elif shape == "diamond":
        d.polygon(_polygon(cx, cy, r, 4), outline=color, width=w)
    elif shape == "pentagon":
        d.polygon(_polygon(cx, cy, r, 5), outline=color, width=w)
    elif shape == "arrow":
        pts = [(cx - r, cy - r * 0.5), (cx + r * 0.3, cy - r * 0.5), (cx + r * 0.3, cy - r),
               (cx + r, cy), (cx + r * 0.3, cy + r), (cx + r * 0.3, cy + r * 0.5), (cx - r, cy + r * 0.5)]
        d.polygon(pts, outline=color, width=w)
    elif shape == "bowtie":
        d.polygon([(cx - r, cy - r), (cx + r, cy + r), (cx + r, cy - r), (cx - r, cy + r)], outline=color, width=w)
    elif shape == "bars":
        for i, h in enumerate((0.4, 0.75, 1.0)):
            x0 = cx - r + i * (2 * r / 3) + w
            d.rectangle([x0, cy + r - 2 * r * h, x0 + 2 * r / 3 - 2 * w, cy + r], outline=color, width=w)
    elif shape == "pin":
        d.ellipse([cx - r * 0.7, cy - r, cx + r * 0.7, cy + r * 0.4], outline=color, width=w)
        d.polygon([(cx - r * 0.45, cy + r * 0.1), (cx + r * 0.45, cy + r * 0.1), (cx, cy + r)], outline=color, width=w)
    elif shape == "clock":
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=w)
        d.line([(cx, cy), (cx, cy - r * 0.6)], fill=color, width=w)
        d.line([(cx, cy), (cx + r * 0.45, cy)], fill=color, width=w)
    elif shape == "flag":
        d.line([(cx - r * 0.7, cy - r), (cx - r * 0.7, cy + r)], fill=color, width=w)
        d.polygon([(cx - r * 0.7, cy - r), (cx + r, cy - r * 0.5), (cx - r * 0.7, cy)], outline=color, width=w)
    elif shape == "burst":
        pts = []
        for i in range(16):
            rr = r if i % 2 == 0 else r * 0.55
            a = -math.pi / 2 + 2 * math.pi * i / 16
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, outline=color, width=w)
    elif shape == "cluster":
        for dx, dy in ((-0.45, -0.35), (0.45, -0.35), (0, 0.45)):
            d.ellipse([cx + dx * r - r * 0.45, cy + dy * r - r * 0.45, cx + dx * r + r * 0.45, cy + dy * r + r * 0.45],
                      outline=color, width=w)


def _mark(d: ImageDraw.ImageDraw, x: float, y: float, w: float, h: float, label: str, color, f) -> None:
    d.rounded_rectangle([x, y, x + w, y + h], radius=h / 3, fill=color)
    tw, th = text_size(d, label, f)
    d.text((x + (w - tw) / 2, y + (h - th) / 2 - 1), label, font=f, fill=(255, 255, 255))


def _node_label(n: Node) -> str:
    if isinstance(n, Pid):
        return "$" + inv.name_of(n)
    if isinstance(n, Composition):
        return n.transliterate(8)
    return "#" + bytes(n).hex()[:8]


def render_block(comp: Composition, style: BlockStyle | None = None, depth: int = 0) -> Image.Image:
    """Render one composition as a script block (RGB image)."""
    st = style or BlockStyle()
    S = st.size if depth == 0 else max(56, int(st.size * 0.55 ** depth))
    mark_h = st.mark_h if depth == 0 else max(14, int(st.mark_h * 0.75 ** depth))
    f_mark = font("bold", max(9, int(mark_h * 0.55)))
    f_head = font("bold", max(10, int(S * 0.16)))
    f_cap = font("mono", max(9, int(st.mark_h * 0.6)))
    f_role = font("sans", max(9, int(mark_h * 0.6)))
    pad = st.pad

    # bucket modifiers by position
    buckets: dict[str, list] = {"top": [], "left": [], "right": [], "bottom": [], "corner": [], "nested": []}
    for m in sorted(comp.modifiers, key=lambda n: (0, n.code) if isinstance(n, Pid) else (1, 0)):
        if isinstance(m, Pid):
            buckets[POSITION.get(m.cls, "corner")].append(m)
        else:
            buckets["nested"].append(m)

    # measure side columns
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    def mark_w(p: Pid) -> int:
        return text_size(tmp, ABBREV.get(inv.name_of(p), inv.name_of(p)[:4]), f_mark)[0] + mark_h

    side_w = max([mark_w(p) for p in buckets["left"] + buckets["right"]] + [0])
    left_h = len(buckets["left"]) * (mark_h + 4)
    right_h = len(buckets["right"]) * (mark_h + 4)
    top_row = buckets["top"] + buckets["corner"]
    top_w = sum(mark_w(p) + 4 for p in top_row)
    bot_w = sum(mark_w(p) + 4 for p in buckets["bottom"])
    core_w = max(S, top_w, bot_w) + 2 * (side_w + pad if side_w else 0)
    core_h = S + 2 * (mark_h + 6)

    # role stack + nested modifier compositions
    sub_imgs: list[tuple[str, Image.Image | None, str]] = []
    for code, node in comp.roles:
        rname = inv.ROLE_NAMES[code]
        if isinstance(node, Composition):
            sub_imgs.append((rname, render_block(node, st, depth + 1), ""))
        else:
            sub_imgs.append((rname, None, _node_label(node)))
    for m in buckets["nested"]:
        sub_imgs.append(("MOD", render_block(m, st, depth + 1), ""))

    roles_h = 0
    roles_w = 0
    for rname, img, label in sub_imgs:
        if img is not None:
            roles_h += img.height + 6
            roles_w = max(roles_w, img.width + text_size(tmp, rname, f_role)[0] + 12)
        else:
            roles_h += mark_h + 6
            roles_w = max(roles_w, text_size(tmp, f"{rname} {label}", f_role)[0] + 12)

    residue_h = 0
    residue_txt = ""
    if comp.residue is not None and st.show_residue:
        residue_txt = "~ " + comp.residue
        residue_h = mark_h + 6

    caption_lines: list[str] = []
    if st.show_caption and depth == 0:
        caption_lines = [comp.transliterate(8), "#" + comp.sid_hex(16)]
        if comp.gloss:
            caption_lines.append("= " + comp.gloss)
    cap_h = sum(text_size(tmp, ln, f_cap)[1] + 4 for ln in caption_lines)
    cap_w = max([text_size(tmp, ln, f_cap)[0] for ln in caption_lines] + [0])

    W = int(max(core_w, roles_w, cap_w, text_size(tmp, residue_txt, f_role)[0] + 16 if residue_txt else 0) + 2 * pad)
    H = int(core_h + roles_h + residue_h + cap_h + 2 * pad + (6 if caption_lines else 0))
    img = Image.new("RGB", (W, H), st.bg)
    d = ImageDraw.Draw(img)

    cx = W / 2
    top_y = pad
    cy = top_y + mark_h + 6 + S / 2
    head_name = inv.name_of(comp.head)
    color = CLASS_COLOR[inv.CLASS_ONTOLOGICAL]

    # head
    _draw_head(d, head_name, cx, cy, S / 2 - 4, color)
    label = ABBREV.get(head_name, head_name[:4])
    tw, th = text_size(d, label, f_head)
    if HEAD_SHAPE.get(head_name) in ("bars", "bowtie", "pin", "cluster", "flag", "clock"):
        # shapes without an empty centre: label sits in the lower part, boxed
        ly = cy + S / 2 - th - 8
        d.rectangle([cx - tw / 2 - 3, ly - 1, cx + tw / 2 + 3, ly + th + 4], fill=st.bg)
        d.text((cx - tw / 2, ly), label, font=f_head, fill=color)
    else:
        d.text((cx - tw / 2, cy - th / 2 - 2), label, font=f_head, fill=color)

    # top marks (modal | epistemic, illocutionary at the corner)
    x = cx - top_w / 2
    for p in top_row:
        w = mark_w(p)
        _mark(d, x, top_y, w, mark_h, ABBREV.get(inv.name_of(p), inv.name_of(p)[:4]), CLASS_COLOR[p.cls], f_mark)
        x += w + 4
    if top_row:
        d.line([(cx, top_y + mark_h), (cx, cy - S / 2 + 2)], fill=(160, 160, 160), width=1)

    # bottom marks (temporal | valence)
    by = cy + S / 2 + 6
    x = cx - bot_w / 2
    for p in buckets["bottom"]:
        w = mark_w(p)
        _mark(d, x, by, w, mark_h, ABBREV.get(inv.name_of(p), inv.name_of(p)[:4]), CLASS_COLOR[p.cls], f_mark)
        x += w + 4
    if buckets["bottom"]:
        d.line([(cx, cy + S / 2 - 2), (cx, by)], fill=(160, 160, 160), width=1)

    # left (causal) and right (scalar)
    y = cy - left_h / 2
    for p in buckets["left"]:
        w = mark_w(p)
        _mark(d, cx - S / 2 - pad - w, y, w, mark_h, ABBREV.get(inv.name_of(p), inv.name_of(p)[:4]), CLASS_COLOR[p.cls], f_mark)
        d.line([(cx - S / 2 - pad, y + mark_h / 2), (cx - S / 2 + 2, y + mark_h / 2)], fill=(160, 160, 160), width=1)
        y += mark_h + 4
    y = cy - right_h / 2
    for p in buckets["right"]:
        w = mark_w(p)
        _mark(d, cx + S / 2 + pad, y, w, mark_h, ABBREV.get(inv.name_of(p), inv.name_of(p)[:4]), CLASS_COLOR[p.cls], f_mark)
        d.line([(cx + S / 2 - 2, y + mark_h / 2), (cx + S / 2 + pad, y + mark_h / 2)], fill=(160, 160, 160), width=1)
        y += mark_h + 4

    # roles stack
    y = top_y + core_h + 4
    if sub_imgs:
        d.line([(cx, by + (mark_h if buckets["bottom"] else 0)), (cx, y)], fill=(160, 160, 160), width=1)
    for rname, sub, label in sub_imgs:
        rw = text_size(d, rname, f_role)[0]
        if sub is not None:
            x0 = cx - (sub.width + rw + 8) / 2
            d.text((x0, y + 4), rname, font=f_role, fill=(90, 90, 90))
            img.paste(sub, (int(x0 + rw + 8), int(y)))
            d.rectangle([x0 + rw + 8, y, x0 + rw + 8 + sub.width - 1, y + sub.height - 1], outline=(200, 200, 200))
            y += sub.height + 6
        else:
            txt = f"{rname}  {label}"
            tw = text_size(d, txt, f_role)[0]
            col = CLASS_COLOR[inv.CLASS_STRUCTURAL]
            d.rounded_rectangle([cx - tw / 2 - 6, y, cx + tw / 2 + 6, y + mark_h], radius=4, outline=col)
            d.text((cx - tw / 2, y + 3), txt, font=f_role, fill=(60, 60, 60))
            y += mark_h + 6

    # residue ribbon
    if residue_txt:
        tw = text_size(d, residue_txt, f_role)[0]
        col = (235, 225, 200)
        d.rectangle([cx - tw / 2 - 8, y, cx + tw / 2 + 8, y + mark_h], fill=col, outline=(200, 180, 120))
        d.text((cx - tw / 2, y + 3), residue_txt, font=f_role, fill=(90, 70, 20))
        y += residue_h

    # caption
    if caption_lines:
        y += 6
        for ln in caption_lines:
            tw, th = text_size(d, ln, f_cap)
            d.text((cx - tw / 2, y), ln, font=f_cap, fill=(70, 70, 70))
            y += th + 4
    return img


# ---------------------------------------------------------------------------
# Document model
# ---------------------------------------------------------------------------

@dataclass
class Heading:
    text: str
    level: int = 1


@dataclass
class Para:
    text: str
    mono: bool = False
    color: tuple = (30, 30, 30)


@dataclass
class Blocks:
    comps: list[Composition]
    style: BlockStyle = field(default_factory=BlockStyle)


@dataclass
class Rule:
    pass


@dataclass
class Spacer:
    height: int = 12


Item = Union[Heading, Para, Blocks, Rule, Spacer]
Doc = list


@dataclass
class PageSpec:
    width: int = 1240          # px, roughly A4 @ 150dpi
    height: int = 1754
    margin: int = 60
    bg: tuple = (255, 255, 255)
    scale: float = 1.0


def _wrap(draw, text: str, f, max_w: int) -> list[str]:
    out: list[str] = []
    for para in text.split("\n"):
        words = para.split(" ")
        line = ""
        for w in words:
            cand = (line + " " + w).strip()
            if text_size(draw, cand, f)[0] <= max_w or not line:
                line = cand
            else:
                out.append(line)
                line = w
        out.append(line)
    return out


def _grid(images: list[Image.Image], max_w: int, gap: int = 16, bg=(255, 255, 255)) -> list[Image.Image]:
    """Pack block images into rows no wider than max_w; returns row images."""
    rows: list[Image.Image] = []
    cur: list[Image.Image] = []
    cur_w = 0
    def flush():
        if not cur:
            return
        h = max(i.height for i in cur)
        w = sum(i.width for i in cur) + gap * (len(cur) - 1)
        row = Image.new("RGB", (w, h), bg)
        x = 0
        for i in cur:
            row.paste(i, (x, 0))
            x += i.width + gap
        rows.append(row)
    for im in images:
        if cur and cur_w + gap + im.width > max_w:
            flush()
            cur, cur_w = [], 0
        cur.append(im)
        cur_w += im.width + (gap if len(cur) > 1 else 0)
    flush()
    return rows


def render_png(doc: Doc, page: PageSpec | None = None) -> list[Image.Image]:
    """Lay the document out onto one or more pages."""
    ps = page or PageSpec()
    pages: list[Image.Image] = []
    inner_w = ps.width - 2 * ps.margin
    fonts = {1: font("bold", 30), 2: font("bold", 22), 3: font("bold", 17)}
    f_body = font("sans", 15)
    f_mono = font("mono", 13)

    cur = Image.new("RGB", (ps.width, ps.height), ps.bg)
    d = ImageDraw.Draw(cur)
    y = ps.margin

    def new_page():
        nonlocal cur, d, y
        pages.append(cur)
        cur = Image.new("RGB", (ps.width, ps.height), ps.bg)
        d = ImageDraw.Draw(cur)
        y = ps.margin

    def ensure(h: int):
        if y + h > ps.height - ps.margin and y > ps.margin:
            new_page()

    for item in doc:
        if isinstance(item, Heading):
            f = fonts.get(item.level, fonts[3])
            for ln in _wrap(d, item.text, f, inner_w):
                h = text_size(d, ln, f)[1] + 8
                ensure(h)
                d.text((ps.margin, y), ln, font=f, fill=(20, 20, 20))
                y += h
            y += 6
        elif isinstance(item, Para):
            f = f_mono if item.mono else f_body
            for ln in _wrap(d, item.text, f, inner_w):
                h = text_size(d, "Ag", f)[1] + 6
                ensure(h)
                d.text((ps.margin, y), ln, font=f, fill=item.color)
                y += h
            y += 4
        elif isinstance(item, Blocks):
            imgs = [render_block(c, item.style) for c in item.comps]
            for row in _grid(imgs, inner_w):
                if row.width > inner_w:
                    row = row.resize((inner_w, int(row.height * inner_w / row.width)))
                ensure(row.height + 10)
                cur.paste(row, (ps.margin, y))
                y += row.height + 10
        elif isinstance(item, Rule):
            ensure(12)
            d.line([(ps.margin, y + 5), (ps.width - ps.margin, y + 5)], fill=(190, 190, 190), width=1)
            y += 12
        elif isinstance(item, Spacer):
            y += item.height
    pages.append(cur)
    # trim trailing whitespace of the last page if it's a single-page doc
    return pages


def render_png_single(doc: Doc, width: int = 1240, margin: int = 60) -> Image.Image:
    """One tall image sized to content (handy for a single composition)."""
    ps = PageSpec(width=width, height=100000, margin=margin)
    page = render_png(doc, ps)[0]
    # crop to content
    gray = page.convert("L")
    bbox = Image.eval(gray, lambda p: 255 - p).getbbox()
    bottom = (bbox[3] if bbox else margin) + margin
    return page.crop((0, 0, width, min(bottom, page.height)))


def save_png(doc: Doc, path: str, single: bool = True, **kw) -> list[str]:
    """Write PNG(s).  Multi-page output gets ``-1``, ``-2`` suffixes."""
    if single:
        render_png_single(doc, **kw).save(path)
        return [path]
    pages = render_png(doc)
    if len(pages) == 1:
        pages[0].save(path)
        return [path]
    base, ext = os.path.splitext(path)
    out = []
    for i, p in enumerate(pages, 1):
        fn = f"{base}-{i}{ext}"
        p.save(fn)
        out.append(fn)
    return out


def render_pdf(doc: Doc, title: str = "ALP") -> bytes:
    """Render to PDF with reportlab: real text, embedded block images."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    buf = io.BytesIO()
    W, H = A4
    margin = 42
    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setAuthor("alp")
    y = H - margin
    inner_w = W - 2 * margin

    def newpage():
        nonlocal y
        c.showPage()
        y = H - margin

    def ensure(h: float):
        if y - h < margin:
            newpage()

    def wrap_pdf(text: str, fname: str, size: float) -> list[str]:
        from reportlab.pdfbase.pdfmetrics import stringWidth
        out = []
        for para in text.split("\n"):
            line = ""
            for w in para.split(" "):
                cand = (line + " " + w).strip()
                if stringWidth(cand, fname, size) <= inner_w or not line:
                    line = cand
                else:
                    out.append(line)
                    line = w
            out.append(line)
        return out

    for item in doc:
        if isinstance(item, Heading):
            size = {1: 18, 2: 14, 3: 12}.get(item.level, 12)
            for ln in wrap_pdf(item.text, "Helvetica-Bold", size):
                ensure(size + 6)
                c.setFont("Helvetica-Bold", size)
                c.drawString(margin, y - size, ln)
                y -= size + 6
            y -= 4
        elif isinstance(item, Para):
            fname, size = ("Courier", 8.5) if item.mono else ("Helvetica", 10)
            for ln in wrap_pdf(item.text, fname, size):
                ensure(size + 4)
                c.setFont(fname, size)
                r, g, b = [v / 255 for v in item.color]
                c.setFillColorRGB(r, g, b)
                c.drawString(margin, y - size, ln)
                y -= size + 4
            c.setFillColorRGB(0, 0, 0)
            y -= 3
        elif isinstance(item, Blocks):
            imgs = [render_block(cm, item.style) for cm in item.comps]
            for row in _grid(imgs, int(inner_w * 2)):
                scale = min(0.5, inner_w / row.width)
                w, h = row.width * scale, row.height * scale
                ensure(h + 8)
                c.drawImage(ImageReader(row), margin, y - h, width=w, height=h)
                y -= h + 8
        elif isinstance(item, Rule):
            ensure(10)
            c.setStrokeColorRGB(0.75, 0.75, 0.75)
            c.line(margin, y - 4, W - margin, y - 4)
            y -= 10
        elif isinstance(item, Spacer):
            y -= item.height * 0.6
    c.save()
    return buf.getvalue()


def save_pdf(doc: Doc, path: str, title: str = "ALP") -> str:
    with open(path, "wb") as fh:
        fh.write(render_pdf(doc, title))
    return path


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def doc_for_compositions(comps: Sequence[Composition], sources: Sequence[str] | None = None,
                         title: str | None = None, style: BlockStyle | None = None) -> Doc:
    """English (optional) + block + transliteration + reading for each composition."""
    st = style or BlockStyle()
    doc: Doc = []
    if title:
        doc.append(Heading(title, 1))
    for i, c in enumerate(comps):
        if sources and i < len(sources) and sources[i]:
            doc.append(Para(sources[i]))
        doc.append(Blocks([c], st))
        doc.append(Para(f"!{c.sid_hex(16)}…  {c.transliterate(8)}", mono=True))
        doc.append(Para("reads: " + c.reading(), color=(80, 80, 80)))
        if i < len(comps) - 1:
            doc.append(Rule())
    return doc


def doc_for_stream(stream, title: str | None = None, alpt_text: str | None = None,
                   style: BlockStyle | None = None, blocks: bool = True) -> Doc:
    """A stream rendered as an audit document: each event with its blocks."""
    from .alpt import event_block
    st = style or BlockStyle(size=120, mark_h=18)
    doc: Doc = [Heading(title or f"ALP stream {stream.stream_id.hex()[:16]}…", 1),
                Para(f"{len(stream)} events · profile {stream.profile} · {len(stream.lexicon())} symbols", color=(90, 90, 90)),
                Rule()]
    for e in stream.ordered():
        doc.append(Heading(f"@{e.eid_hex(16)}  {e.type.name}", 3))
        doc.append(Para("\n".join(event_block(e, author_name=stream.author_name(e.author))[1:]), mono=True))
        comps = e.compositions()
        if blocks and comps:
            doc.append(Blocks(comps, st))
        if e.type.name == "ASSERT":
            for pair in e.payload:
                sym = stream.state.symbol(pair[0].data)
                if sym is not None:
                    doc.append(Para(f"{sym.transliterate(8)}  ←  {pair[1]!r}", mono=True, color=(60, 60, 60)))
        doc.append(Spacer(6))
    if alpt_text:
        doc.append(Rule())
        doc.append(Heading("ALP/T", 2))
        doc.append(Para(alpt_text, mono=True))
    return doc


def doc_for_inventory(style: BlockStyle | None = None) -> Doc:
    """The primitive chart: one block per ontological head, one mark per modifier."""
    st = style or BlockStyle(size=90, mark_h=16, show_caption=False)
    doc: Doc = [Heading(f"ALP primitive inventory v{inv.INVENTORY_VERSION}", 1)]
    heads = [Composition(p) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]
    doc.append(Heading("class 0x00 — ontological heads", 2))
    doc.append(Blocks(heads, st))
    doc.append(Para("  ".join(f"${inv.name_of(p)}" for p in inv.by_class(inv.CLASS_ONTOLOGICAL)), mono=True))
    for cls in range(1, 8):
        doc.append(Heading(f"class 0x{cls:02X} — {inv.CLASS_NAMES[cls]} (position: {POSITION.get(cls, '-')})", 2))
        doc.append(Blocks([Composition(inv.pid("ENTITY"), frozenset([p])) for p in inv.by_class(cls)], st))
        doc.append(Para("  ".join(f"${inv.name_of(p)}={inv.SENSES[p]}" for p in inv.by_class(cls)), mono=True))
    return doc
