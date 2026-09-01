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
from . import glyphs
from . import inventory as inv
from .composition import Composition, Node

# ---------------------------------------------------------------------------
# Themes and layout constants
# ---------------------------------------------------------------------------

THEMES = {
    "dark":  {"bg": (16, 16, 18), "ink": (232, 232, 228), "dim": (110, 110, 106), "slot": (52, 52, 56), "text": (200, 200, 196)},
    "light": {"bg": (255, 255, 255), "ink": (24, 24, 26), "dim": (150, 150, 146), "slot": (200, 200, 196), "text": (60, 60, 60)},
}

# Where a modifier class attaches (§6.2, as drawn in the reference sheet):
#   above: modal, epistemic      left: causal, illocutionary
#   right: scalar                lower-right: valence/deontic
#   below: temporal              NEGATE crosses the head itself
POSITION = {
    inv.CLASS_MODAL: "top", inv.CLASS_EPISTEMIC: "top",
    inv.CLASS_CAUSAL: "left", inv.CLASS_ILLOCUTIONARY: "left",
    inv.CLASS_SCALAR: "right", inv.CLASS_VALENCE: "lowright",
    inv.CLASS_TEMPORAL: "bottom",
}
_ORDER = ["top", "left", "right", "lowright", "bottom"]

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
_font_cache: dict[tuple[str, int], Any] = {}
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
# Block rendering — the script proper.  No text.  One ink.
# ---------------------------------------------------------------------------

@dataclass
class BlockStyle:
    head: int = 72               # head glyph cell, px
    theme: str = "dark"
    weight: float = 0.06         # stroke width as a fraction of glyph cell
    frame: bool = True           # draw the rounded card around the block
    pad: int = 14
    caption: bool = False        # transliteration under the block (ASCII fallback, §6.5)

    @property
    def colors(self) -> dict:
        return THEMES[self.theme]


def _mods_by_position(comp: Composition) -> tuple[dict[str, list[Pid]], list[Composition], bool]:
    buckets: dict[str, list[Pid]] = {k: [] for k in _ORDER}
    nested: list[Composition] = []
    negate = False
    for m in sorted(comp.modifiers, key=lambda n: (0, n.code) if isinstance(n, Pid) else (1, 0)):
        if isinstance(m, Composition):
            nested.append(m)
        elif inv.name_of(m) == "NEGATE":
            negate = True
        else:
            buckets[POSITION.get(m.cls, "left")].append(m)
    return buckets, nested, negate


def measure_block(comp: Composition, st: BlockStyle, depth: int = 0) -> tuple[int, int]:
    return render_block(comp, st, depth).size


def render_block(comp: Composition, style: BlockStyle | None = None, depth: int = 0) -> Image.Image:
    """Render one composition as a script block."""
    st = style or BlockStyle()
    C = st.colors
    H = st.head if depth == 0 else max(28, int(st.head * 0.62 ** depth))
    m = max(10, int(H * 0.42))          # modifier mark cell
    gap = max(3, int(H * 0.08))
    buckets, nested, negate = _mods_by_position(comp)

    # role slots and nested modifier compositions rendered first (we need sizes)
    subs: list[tuple[str, Image.Image | None, Any]] = []
    for code, node in comp.roles:
        if isinstance(node, Composition):
            subs.append(("role", render_block(node, BlockStyle(st.head, st.theme, st.weight, False, 6, False), depth + 1), node))
        else:
            subs.append(("role", None, node))
    for n in nested:
        subs.append(("mod", render_block(n, BlockStyle(st.head, st.theme, st.weight, False, 6, False), depth + 1), n))

    slot = int(m * 1.5)
    top_w = len(buckets["top"]) * (m + gap)
    bot_w = len(buckets["bottom"]) * (m + gap)
    left_h = len(buckets["left"]) * (m + gap)
    right_h = len(buckets["right"]) * (m + gap)
    lr_h = len(buckets["lowright"]) * (m + gap)
    side = m + gap if (buckets["left"] or buckets["right"] or buckets["lowright"]) else 0
    core_w = max(H + 2 * side, top_w, bot_w)
    core_h = H + (m + gap if buckets["top"] else 0) + (m + gap if buckets["bottom"] else 0)
    core_h = max(core_h, left_h, right_h + lr_h)

    stack_h = 0
    stack_w = 0
    for kind, img, node in subs:
        if img is not None:
            stack_h += img.height + gap
            stack_w = max(stack_w, img.width + slot // 2)
        else:
            stack_h += slot + gap
            stack_w = max(stack_w, slot)
    residue_h = (m + gap) if comp.residue is not None else 0

    cap_lines: list[str] = []
    f_cap = font("mono", max(9, int(H * 0.16)))
    tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    if st.caption and depth == 0:
        cap_lines = [comp.transliterate(8)]
    cap_h = sum(text_size(tmp, ln, f_cap)[1] + 4 for ln in cap_lines) + (gap if cap_lines else 0)
    cap_w = max([text_size(tmp, ln, f_cap)[0] for ln in cap_lines] + [0])

    pad = st.pad
    W = int(max(core_w, stack_w, cap_w) + 2 * pad)
    Hh = int(core_h + (gap if subs else 0) + stack_h + residue_h + cap_h + 2 * pad)
    img = Image.new("RGB", (W, Hh), C["bg"])
    d = ImageDraw.Draw(img)
    if st.frame and depth == 0:
        d.rounded_rectangle([0, 0, W - 1, Hh - 1], radius=int(pad * 0.8), outline=C["slot"], width=1)

    cx = W / 2
    y0 = pad
    hy = y0 + (m + gap if buckets["top"] else 0)          # head top
    # centre the core vertically if side columns are taller than the head
    extra = core_h - (H + (m + gap if buckets["top"] else 0) + (m + gap if buckets["bottom"] else 0))
    hy += extra / 2
    hx = cx - H / 2
    hcy = hy + H / 2

    # head
    glyphs.draw_glyph(d, comp.head, hx, hy, H, C["ink"], st.weight)
    if negate:  # the one mark that crosses the glyph
        w = max(2, int(H * st.weight))
        d.line([(hx + H * 0.08, hy + H * 0.92), (hx + H * 0.92, hy + H * 0.08)], fill=C["ink"], width=w)

    # marks
    x = cx - top_w / 2 + gap / 2
    for p in buckets["top"]:
        glyphs.draw_glyph(d, p, x, hy - m - gap, m, C["ink"], st.weight)
        x += m + gap
    x = cx - bot_w / 2 + gap / 2
    for p in buckets["bottom"]:
        glyphs.draw_glyph(d, p, x, hy + H + gap, m, C["ink"], st.weight)
        x += m + gap
    y = hcy - left_h / 2 + gap / 2
    for p in buckets["left"]:
        glyphs.draw_glyph(d, p, hx - m - gap, y, m, C["ink"], st.weight)
        y += m + gap
    y = hcy - (right_h + lr_h) / 2 + gap / 2
    for p in buckets["right"]:
        glyphs.draw_glyph(d, p, hx + H + gap, y, m, C["ink"], st.weight)
        y += m + gap
    for p in buckets["lowright"]:
        glyphs.draw_glyph(d, p, hx + H + gap + m * 0.35, y, m, C["ink"], st.weight)
        y += m + gap

    # role stack: ordered slots beneath the block
    y = y0 + core_h + gap
    for kind, sub, node in subs:
        if sub is not None:
            x = cx - sub.width / 2
            img.paste(sub, (int(x), int(y)))
            d.rounded_rectangle([x - 2, y - 2, x + sub.width + 1, y + sub.height + 1], radius=4,
                                outline=C["slot"] if kind == "role" else C["dim"], width=1)
            y += sub.height + gap
        else:
            x = cx - slot / 2
            d.rounded_rectangle([x, y, x + slot, y + slot], radius=3, outline=C["slot"], width=1)
            if isinstance(node, Pid):
                glyphs.draw_glyph(d, node, x + slot * 0.15, y + slot * 0.15, slot * 0.7, C["ink"], st.weight)
            else:  # SID reference
                glyphs.draw_glyph(d, "REF", x + slot * 0.15, y + slot * 0.15, slot * 0.7, C["ink"], st.weight)
            y += slot + gap
    if comp.residue is not None:
        glyphs.draw_glyph(d, "RESIDUE", cx - m / 2, y, m, C["dim"], st.weight)
        y += m + gap
    if cap_lines:
        y += gap
        for ln in cap_lines:
            tw, th = text_size(d, ln, f_cap)
            d.text((cx - tw / 2, y), ln, font=f_cap, fill=C["text"])
            y += th + 4
    return img


def render_linear(comps: Sequence[Composition], cell: int = 36, theme: str = "dark", weight: float = 0.07) -> Image.Image:
    """§6.4 rule 4 fallback: the canonical primitive sequence as a line of glyphs."""
    C = THEMES[theme]
    seqs = [c.primitives() for c in comps]
    n = sum(len(s) for s in seqs) + max(0, len(seqs) - 1)
    img = Image.new("RGB", (n * cell + cell, cell + 8), C["bg"])
    d = ImageDraw.Draw(img)
    x = cell / 2
    for i, seq in enumerate(seqs):
        for p in seq:
            glyphs.draw_glyph(d, p, x + cell * 0.1, 4 + cell * 0.1, cell * 0.8, C["ink"], weight)
            x += cell
        if i < len(seqs) - 1:
            d.line([(x + cell * 0.5, 8), (x + cell * 0.5, cell)], fill=C["dim"], width=1)
            x += cell
    return img


def render_key(theme: str = "light", cell: int = 40) -> Image.Image:
    """The glyph key — the one place English appears: glyph, name, sense, class position."""
    C = THEMES[theme]
    f = font("sans", 13)
    f_b = font("bold", 13)
    f_s = font("sans", 11)
    rows = []
    for cls in range(9):
        rows.append(("hdr", cls))
        for p in inv.by_class(cls):
            rows.append(("row", p))
    h = sum(cell if k == "row" else cell * 0.9 for k, _ in rows) + 40
    img = Image.new("RGB", (620, int(h)), C["bg"])
    d = ImageDraw.Draw(img)
    y = 20
    for k, v in rows:
        if k == "hdr":
            pos = {"top": "above head", "left": "left of head", "right": "right of head", "lowright": "lower right", "bottom": "below head"}.get(POSITION.get(v, ""), "head" if v == 0 else "structural")
            d.text((20, y + 8), f"class 0x{v:02X}  {inv.CLASS_NAMES[v]}  —  {pos}", font=f_b, fill=C["ink"])
            y += cell * 0.9
        else:
            glyphs.draw_glyph(d, v, 24, y + 4, cell - 8, C["ink"], 0.07)
            d.text((80, y + 6), inv.name_of(v), font=f, fill=C["ink"])
            d.text((200, y + 8), inv.SENSES[v], font=f_s, fill=C["text"])
            d.text((520, y + 8), f"U+{0xE000 + v.code:04X}", font=f_s, fill=C["dim"])
            y += cell
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
    dim: bool = False


@dataclass
class Blocks:
    comps: list
    style: BlockStyle = field(default_factory=BlockStyle)


@dataclass
class Chars:
    """Running text in the character script: a list of (composition, bound value) or None (line break)."""
    words: list
    cell: int = 56
    theme: str = "dark"
    frame: object = "faint"
    headline: bool = True


@dataclass
class Img:
    image: Image.Image


@dataclass
class Rule:
    pass


@dataclass
class Spacer:
    height: int = 12


Item = Union[Heading, Para, Blocks, Chars, Img, Rule, Spacer]
Doc = list


@dataclass
class PageSpec:
    width: int = 1240          # px, roughly A4 @ 150dpi
    height: int = 1754
    margin: int = 60
    theme: str = "dark"


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
    C = THEMES[ps.theme]
    pages: list[Image.Image] = []
    inner_w = ps.width - 2 * ps.margin
    fonts = {1: font("bold", 30), 2: font("bold", 22), 3: font("bold", 17)}
    f_body = font("sans", 15)
    f_mono = font("mono", 13)

    cur = Image.new("RGB", (ps.width, ps.height), C["bg"])
    d = ImageDraw.Draw(cur)
    y = ps.margin

    def new_page():
        nonlocal cur, d, y
        pages.append(cur)
        cur = Image.new("RGB", (ps.width, ps.height), C["bg"])
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
                d.text((ps.margin, y), ln, font=f, fill=C["ink"])
                y += h
            y += 6
        elif isinstance(item, Para):
            f = f_mono if item.mono else f_body
            for ln in _wrap(d, item.text, f, inner_w):
                h = text_size(d, "Ag", f)[1] + 6
                ensure(h)
                d.text((ps.margin, y), ln, font=f, fill=C["dim"] if item.dim else C["text"])
                y += h
            y += 4
        elif isinstance(item, Blocks):
            imgs = [render_block(c, item.style) for c in item.comps]
            for row in _grid(imgs, inner_w, bg=C["bg"]):
                if row.width > inner_w:
                    row = row.resize((inner_w, int(row.height * inner_w / row.width)))
                ensure(row.height + 10)
                cur.paste(row, (ps.margin, y))
                y += row.height + 10
        elif isinstance(item, (Img, Chars)):
            im = item.image if isinstance(item, Img) else _chars_image(item, inner_w)
            if im.width > inner_w:
                im = im.resize((inner_w, int(im.height * inner_w / im.width)))
            ensure(im.height + 10)
            cur.paste(im, (ps.margin, y))
            y += im.height + 10
        elif isinstance(item, Rule):
            ensure(12)
            d.line([(ps.margin, y + 5), (ps.width - ps.margin, y + 5)], fill=C["slot"], width=1)
            y += 12
        elif isinstance(item, Spacer):
            y += item.height
    pages.append(cur)
    return pages


def render_png_single(doc: Doc, width: int = 1240, margin: int = 60, theme: str = "dark") -> Image.Image:
    """One tall image sized to content."""
    ps = PageSpec(width=width, height=200000, margin=margin, theme=theme)
    page = render_png(doc, ps)[0]
    bg = THEMES[theme]["bg"]
    diff = Image.eval(page.convert("L"), lambda v: 255 - v) if sum(bg) > 380 else page.convert("L")
    bbox = diff.point(lambda v: 255 if v > 24 else 0).getbbox()
    bottom = (bbox[3] if bbox else margin) + margin
    return page.crop((0, 0, width, min(bottom, page.height)))


def save_png(doc: Doc, path: str, single: bool = True, theme: str = "dark", **kw) -> list[str]:
    """Write PNG(s).  Multi-page output gets ``-1``, ``-2`` suffixes."""
    if single:
        render_png_single(doc, theme=theme, **kw).save(path)
        return [path]
    pages = render_png(doc, PageSpec(theme=theme))
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


def render_pdf(doc: Doc, title: str = "ALP", theme: str = "light") -> bytes:
    """Render to PDF with reportlab: real text, embedded block images."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as rl_canvas

    C = THEMES[theme]
    buf = io.BytesIO()
    W, H = A4
    margin = 42
    c = rl_canvas.Canvas(buf, pagesize=A4)
    c.setTitle(title)
    c.setAuthor("alp")
    y = H - margin
    inner_w = W - 2 * margin

    def paint_bg():
        if theme != "light":
            c.setFillColorRGB(*[v / 255 for v in C["bg"]])
            c.rect(0, 0, W, H, stroke=0, fill=1)

    def fill(rgb):
        c.setFillColorRGB(*[v / 255 for v in rgb])

    paint_bg()

    def newpage():
        nonlocal y
        c.showPage()
        paint_bg()
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
            fill(C["ink"])
            for ln in wrap_pdf(item.text, "Helvetica-Bold", size):
                ensure(size + 6)
                c.setFont("Helvetica-Bold", size)
                c.drawString(margin, y - size, ln)
                y -= size + 6
            y -= 4
        elif isinstance(item, Para):
            fname, size = ("Courier", 8.5) if item.mono else ("Helvetica", 10)
            fill(C["dim"] if item.dim else C["text"])
            for ln in wrap_pdf(item.text, fname, size):
                ensure(size + 4)
                c.setFont(fname, size)
                c.drawString(margin, y - size, ln)
                y -= size + 4
            y -= 3
        elif isinstance(item, Blocks):
            imgs = [render_block(cm, item.style) for cm in item.comps]
            for row in _grid(imgs, int(inner_w * 2), bg=C["bg"]):
                scale = min(0.5, inner_w / row.width)
                w, h = row.width * scale, row.height * scale
                ensure(h + 8)
                c.drawImage(ImageReader(row), margin, y - h, width=w, height=h)
                y -= h + 8
        elif isinstance(item, (Img, Chars)):
            im = item.image if isinstance(item, Img) else _chars_image(item, int(inner_w * 2))
            scale = min(0.5, inner_w / im.width)
            w, h = im.width * scale, im.height * scale
            if h > H - 2 * margin:
                scale = (H - 2 * margin) / im.height
                w, h = im.width * scale, im.height * scale
            ensure(h + 8)
            c.drawImage(ImageReader(im), margin, y - h, width=w, height=h)
            y -= h + 8
        elif isinstance(item, Rule):
            ensure(10)
            c.setStrokeColorRGB(*[v / 255 for v in C["slot"]])
            c.line(margin, y - 4, W - margin, y - 4)
            y -= 10
        elif isinstance(item, Spacer):
            y -= item.height * 0.6
    c.save()
    return buf.getvalue()


def save_pdf(doc: Doc, path: str, title: str = "ALP", theme: str = "light") -> str:
    with open(path, "wb") as fh:
        fh.write(render_pdf(doc, title, theme))
    return path


def _chars_image(item: "Chars", width: int) -> Image.Image:
    from . import script
    return script.render_text(item.words, script.CharStyle(cell=item.cell, theme=item.theme, frame=item.frame, headline=item.headline), width=width, margin=0)


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def doc_for_compositions(comps: Sequence[Composition], sources: Sequence[str] | None = None,
                         title: str | None = None, style: BlockStyle | None = None,
                         english: bool = False, theme: str = "dark", values: Sequence[Any] | None = None,
                         mode: str = "text", cell: int = 56, transliteration: bool = True) -> Doc:
    """Compositions in the character script.

    mode="text": all utterances flow as running text (compact; one line per source sentence
                 when sources are given), then the ALP/T listing.
    mode="each": one utterance per row with its ALP/T line (and English on request).
    mode="block": the expanded §6.2 block form (one glyph per primitive, stacked)."""
    from .alpt import fmt_term
    doc: Doc = []
    if title:
        doc.append(Heading(title, 1))
    vals = list(values) if values else [True] * len(comps)
    if mode == "text":
        words: list = []
        last_src = object()
        for i, c in enumerate(comps):
            src = sources[i] if sources and i < len(sources) else None
            if sources and src != last_src and words:
                words.append(None)
            last_src = src
            words.append((c, vals[i]))
        doc.append(Chars(words, cell=cell, theme=theme))
        if transliteration or english:
            doc.append(Rule())
            for i, c in enumerate(comps):
                if english and sources and i < len(sources) and sources[i] and (i == 0 or sources[i] != sources[i - 1]):
                    doc.append(Para(sources[i]))
                line = f"!{c.sid_hex(8)}  {c.transliterate(8)}"
                if vals[i] not in (None, True):
                    line += f"   ← {fmt_term(vals[i])}"
                doc.append(Para(line, mono=True, dim=not english))
                if english:
                    doc.append(Para("reads: " + c.reading(), dim=True))
        return doc
    for i, c in enumerate(comps):
        if english and sources and i < len(sources) and sources[i]:
            doc.append(Para(sources[i]))
        if mode == "block":
            doc.append(Blocks([c], style or BlockStyle(theme=theme)))
        else:
            doc.append(Chars([(c, vals[i])], cell=cell, theme=theme))
        line = f"!{c.sid_hex(16)}…  {c.transliterate(8)}"
        if vals[i] not in (None, True):
            line += f"   ← {fmt_term(vals[i])}"
        doc.append(Para(line, mono=True))
        if english:
            doc.append(Para("reads: " + c.reading(), dim=True))
        if i < len(comps) - 1:
            doc.append(Rule())
    return doc


def doc_for_stream(stream, title: str | None = None, alpt_text: str | None = None,
                   style: BlockStyle | None = None, blocks: bool = True, theme: str = "dark",
                   english: bool = False, mode: str = "text", cell: int = 48) -> Doc:
    """A stream as a document.

    First the *conversation*: every ASSERT as one line of script (the words
    with their bound literals), the way it would be read.  Then the audit:
    each event with its ALP/T and, for AMEND/GROUND, the new symbols."""
    from .alpt import event_block, fmt_term
    doc: Doc = [Heading(title or f"ALP stream {stream.stream_id.hex()[:16]}…", 1),
                Para(f"{len(stream)} events · profile {stream.profile} · {len(stream.lexicon())} symbols", dim=True)]
    # conversation
    words: list = []
    for e in stream.ordered():
        if e.type.name != "ASSERT":
            continue
        for pair in e.payload:
            sym = stream.state.symbol(pair[0].data)
            if sym is not None:
                words.append((sym, pair[1]))
        words.append(None)
    if words:
        doc.append(Rule())
        doc.append(Chars(words, cell=cell, theme=theme))
    if not blocks:
        if alpt_text:
            doc.append(Rule()); doc.append(Heading("ALP/T", 2)); doc.append(Para(alpt_text, mono=True))
        return doc
    doc.append(Rule())
    doc.append(Heading("events", 2))
    for e in stream.ordered():
        doc.append(Heading(f"@{e.eid_hex(16)}  {e.type.name}", 3))
        doc.append(Para("\n".join(event_block(e, author_name=stream.author_name(e.author))[1:]), mono=True, dim=True))
        comps = e.compositions()
        if comps:
            if mode == "block":
                doc.append(Blocks(comps, style or BlockStyle(head=56, theme=theme)))
            else:
                doc.append(Chars([(c, True) for c in comps], cell=cell, theme=theme))
            if english:
                for c in comps:
                    doc.append(Para("reads: " + c.reading(), dim=True))
        doc.append(Spacer(4))
    if alpt_text:
        doc.append(Rule())
        doc.append(Heading("ALP/T", 2))
        doc.append(Para(alpt_text, mono=True))
    return doc


def doc_for_transcript(paragraphs: Sequence[Sequence], title: str | None = None, theme: str = "dark",
                       cell: int = 56, english: bool = True) -> Doc:
    """A transcript of an English document.

    ``paragraphs`` is a list of paragraphs; each paragraph a list of
    (source_sentence, [Translation, ...]).  Each paragraph renders as running
    script; with ``english`` the sentences and their trees follow, so a reader
    can check every character against its source."""
    from .alpt import fmt_term
    doc: Doc = []
    if title:
        doc.append(Heading(title, 1))
    for pi, para in enumerate(paragraphs):
        words: list = []
        for src, trs in para:
            for t in trs:
                words.append((t.composition, t.value))
        if not words:
            continue
        doc.append(Chars(words, cell=cell, theme=theme))
        if english:
            for src, trs in para:
                doc.append(Para(src))
                for t in trs:
                    line = f"  {t.composition.sid_hex(8)}  {t.composition.transliterate(8)}"
                    if t.value is not True:
                        line += f"   ← {fmt_term(t.value)}"
                    doc.append(Para(line, mono=True, dim=True))
        if pi < len(paragraphs) - 1:
            doc.append(Rule())
    return doc


def doc_for_chart(theme: str = "dark") -> Doc:
    """The character chart: heads, then every modifier class as a transformation of one head, then literals."""
    from . import script
    return [Heading(f"ALP script — character chart, inventory v{inv.INVENTORY_VERSION}", 1),
            Para("Row 1: the twelve heads.  Following rows: each modifier class applied to one head "
                 "(modal · scalar · temporal · causal · epistemic · illocutionary · valence · relational · deictic · logical · affect).  "
                 "Last row: numerals, names (cartouches), a reference seal, a unit.", dim=True),
            Img(script.render_chart(script.CharStyle(cell=72, theme=theme, frame=True)))]


def doc_for_inventory(theme: str = "light") -> Doc:
    """The glyph key: every primitive's glyph beside its name and sense."""
    return [Heading(f"ALP script — glyph key, inventory v{inv.INVENTORY_VERSION}", 1),
            Para("The only place English appears.  Position around the head encodes class; the glyph encodes the member.", dim=True),
            Img(render_key(theme))]
