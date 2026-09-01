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


@dataclass
class BlockStyle:
    """Kept for API compatibility; the expanded block form was retired in favour of the character script."""
    head: int = 72
    theme: str = "dark"


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
    color: bool = True


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
            item = Chars([(c, True) for c in item.comps], cell=item.style.head, theme=item.style.theme)
            im = _chars_image(item, inner_w)
            ensure(im.height + 10)
            cur.paste(im, (ps.margin, y))
            y += im.height + 10
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
            item = Chars([(cm, True) for cm in item.comps], cell=item.style.head, theme=item.style.theme)
            im = _chars_image(item, int(inner_w * 2))
            scale = min(0.5, inner_w / im.width)
            w, h = im.width * scale, im.height * scale
            ensure(h + 8)
            c.drawImage(ImageReader(im), margin, y - h, width=w, height=h)
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


CHAR_DEFAULTS: dict = {"frame": "faint", "headline": True, "color": True}


def set_char_defaults(**kw) -> None:
    """CLI hook: --frame / --no-headline / --mono apply to every Chars item built afterwards."""
    CHAR_DEFAULTS.update(kw)


def _chars(words: list, cell: int, theme: str) -> "Chars":
    return Chars(words, cell=cell, theme=theme, **CHAR_DEFAULTS)


def _chars_image(item: "Chars", width: int) -> Image.Image:
    from . import script
    return script.render_text(item.words, script.CharStyle(cell=item.cell, theme=item.theme, frame=item.frame, headline=item.headline, color=item.color), width=width, margin=0)


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
    """
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
        doc.append(_chars(words, cell, theme))
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
                    from .realize import realize
                    doc.append(Para("reads: " + realize(c, vals[i]), dim=True))
        return doc
    for i, c in enumerate(comps):
        if english and sources and i < len(sources) and sources[i]:
            doc.append(Para(sources[i]))
        doc.append(_chars([(c, vals[i])], cell, theme))
        line = f"!{c.sid_hex(16)}…  {c.transliterate(8)}"
        if vals[i] not in (None, True):
            line += f"   ← {fmt_term(vals[i])}"
        doc.append(Para(line, mono=True))
        if english:
            from .realize import realize
            doc.append(Para("reads: " + realize(c, vals[i]), dim=True))
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
        doc.append(_chars(words, cell, theme))
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
            doc.append(_chars([(c, True) for c in comps], cell, theme))
            if english:
                from .realize import realize
                for c in comps:
                    doc.append(Para("reads: " + realize(c), dim=True))
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
        doc.append(_chars(words, cell, theme))
        if english:
            for src, trs in para:
                doc.append(Para(src))
                from .realize import realize
                for t in trs:
                    line = f"  {t.composition.sid_hex(8)}  {t.composition.transliterate(8)}"
                    if t.value is not True:
                        line += f"   ← {fmt_term(t.value)}"
                    doc.append(Para(line, mono=True, dim=True))
                    doc.append(Para("  reads: " + realize(t.composition, t.value), dim=True))
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
    """The key: every primitive drawn with the character script beside its name and sense."""
    from . import script
    return [Heading(f"ALP script — key, inventory v{inv.INVENTORY_VERSION}", 1),
            Img(script.render_key(script.CharStyle(cell=64, theme=theme, headline=False)))]


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
        doc.append(_chars(words, cell, theme))
        if english:
            for src, trs in para:
                doc.append(Para(src))
                from .realize import realize
                for t in trs:
                    line = f"  {t.composition.sid_hex(8)}  {t.composition.transliterate(8)}"
                    if t.value is not True:
                        line += f"   ← {fmt_term(t.value)}"
                    doc.append(Para(line, mono=True, dim=True))
                    doc.append(Para("  reads: " + realize(t.composition, t.value), dim=True))
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


