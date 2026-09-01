"""SVG backend for the character script.

The composer in ``script.py`` draws through a ``_Pen`` whose primitives are a
handful of calls on a Pillow ``ImageDraw``.  ``SVGDraw`` implements that same
call surface (``line``, ``polygon``, ``ellipse``, ``arc``, ``pieslice``,
``rectangle``) and records SVG elements instead, so every renderer in
``script.py`` works unchanged for vector output:

    svg = render_word_svg(comp)          # one word
    svg = render_text_svg(words)         # running text
    svg = render_chart_svg()             # the chart
    glyphs = character_svgs(comps)       # {sid: <svg>} per character, for a font pipeline

Coordinates are pixels at the requested cell size, so an SVG matches the PNG
of the same call exactly.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

from . import script
from .composition import Composition
from .script import THEMES, CharStyle


def _rgb(c) -> str:
    if isinstance(c, tuple):
        return "#{:02x}{:02x}{:02x}".format(*c[:3])
    return str(c)


class SVGDraw:
    """Records SVG elements; mimics the subset of PIL.ImageDraw the script uses."""

    def __init__(self, width: int, height: int, bg=None) -> None:
        self.w, self.h = width, height
        self.el: list[str] = []
        if bg is not None:
            self.el.append(f'<rect width="{width}" height="{height}" fill="{_rgb(bg)}"/>')

    # -- PIL surface -------------------------------------------------------------
    def line(self, pts, fill=None, width: int = 1, joint=None) -> None:
        if isinstance(pts[0], (int, float)):
            pts = [(pts[0], pts[1]), (pts[2], pts[3])]
        d = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        self.el.append(f'<polyline points="{d}" fill="none" stroke="{_rgb(fill)}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')

    def polygon(self, pts, fill=None, outline=None, width: int = 1) -> None:
        d = " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
        f = _rgb(fill) if fill is not None else "none"
        st = f' stroke="{_rgb(outline)}" stroke-width="{width}"' if outline is not None else ""
        self.el.append(f'<polygon points="{d}" fill="{f}"{st}/>')

    def ellipse(self, box, fill=None, outline=None, width: int = 1) -> None:
        x0, y0, x1, y1 = box
        cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
        f = _rgb(fill) if fill is not None else "none"
        st = f' stroke="{_rgb(outline)}" stroke-width="{width}"' if outline is not None else ""
        self.el.append(f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" fill="{f}"{st}/>')

    def rectangle(self, box, fill=None, outline=None, width: int = 1) -> None:
        x0, y0, x1, y1 = box
        f = _rgb(fill) if fill is not None else "none"
        st = f' stroke="{_rgb(outline)}" stroke-width="{width}"' if outline is not None else ""
        self.el.append(f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" fill="{f}"{st}/>')

    def _arc_path(self, box, a0: float, a1: float) -> tuple[str, float, float]:
        x0, y0, x1, y1 = box
        cx, cy, r = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2
        sx, sy = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
        ex, ey = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
        sweep = (a1 - a0) % 360
        large = 1 if sweep > 180 else 0
        return f"M{sx:.2f},{sy:.2f} A{r:.2f},{r:.2f} 0 {large} 1 {ex:.2f},{ey:.2f}", cx, cy

    def arc(self, box, start: float, end: float, fill=None, width: int = 1) -> None:
        d, _, _ = self._arc_path(box, start, end)
        self.el.append(f'<path d="{d}" fill="none" stroke="{_rgb(fill)}" stroke-width="{width}" stroke-linecap="round"/>')

    def pieslice(self, box, start: float, end: float, fill=None, outline=None, width: int = 1) -> None:
        d, cx, cy = self._arc_path(box, start, end)
        self.el.append(f'<path d="{d} L{cx:.2f},{cy:.2f} Z" fill="{_rgb(fill)}"/>')

    # -- output -----------------------------------------------------------------------
    def svg(self) -> str:
        body = "\n".join(self.el)
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" '
                f'viewBox="0 0 {self.w} {self.h}">\n{body}\n</svg>')


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------

def render_word_svg(comp: Composition, st: CharStyle | None = None, value: Any = True, background: bool = True) -> str:
    st = st or CharStyle()
    C = THEMES[st.theme]
    w = script.word_width(comp, st, value)
    d = SVGDraw(w, st.cell, C["bg"] if background else None)
    script.draw_word(d, comp, 0, 0, st, value)
    return d.svg()


def render_char_svg(comp: Composition, st: CharStyle | None = None, background: bool = False) -> str:
    """One character (the first of the word) — the unit a font would carry."""
    st = st or CharStyle(frame=False, headline=False)
    C = THEMES[st.theme]
    d = SVGDraw(st.cell, st.cell, C["bg"] if background else None)
    chars = script.word_chars(comp)
    c, depth, part, plan, roles = chars[0]
    script.draw_char(d, c, 0, 0, st, depth, part=part, pl_override=plan, roles_override=roles)
    return d.svg()


def render_text_svg(words: Sequence, st: CharStyle | None = None, width: int = 1200, margin: int = 24,
                    line_gap: float = 0.45) -> str:
    """Same layout as script.render_text, as SVG."""
    st = st or CharStyle()
    C = THEMES[st.theme]
    inner = width - 2 * margin
    norm = []
    for w in words:
        if w is None:
            norm.append(None)
        elif isinstance(w, Composition):
            norm.append((w, True))
        else:
            norm.append((w[0], w[1]))
    lines: list[list] = [[]]
    cur = 0
    for w in norm:
        if w is None:
            lines.append([]); cur = 0
            continue
        ww = script.word_width(w[0], st, w[1])
        add = ww + (st.word_gap * st.cell if lines[-1] else 0)
        if lines[-1] and cur + add > inner:
            lines.append([w]); cur = ww
        else:
            lines[-1].append(w); cur += add
    line_h = st.cell * (1 + line_gap)
    height = int(2 * margin + len(lines) * line_h)
    d = SVGDraw(width, height, C["bg"])
    y = margin
    for line in lines:
        x = margin
        for comp, value in line:
            x = script.draw_word(d, comp, x, y, st, value) + st.word_gap * st.cell
        y += line_h
    return d.svg()


def render_chart_svg(st: CharStyle | None = None) -> str:
    st = st or CharStyle(cell=80, frame=True)
    img = script.render_chart(st)            # for size
    d = SVGDraw(img.width, img.height, THEMES[st.theme]["bg"])
    # re-run the chart drawing against the SVG surface
    _chart_into(d, st)
    return d.svg()


def _chart_into(d: SVGDraw, st: CharStyle) -> None:
    from . import inventory as inv
    heads = [Composition(p) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]
    rows = [heads,
            [Composition(p, frozenset([inv.pid("LOW")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)],
            [Composition(p, frozenset([inv.pid("NONE")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)],
            [Composition(p, frozenset([inv.pid("ALL")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]]
    for cls in (inv.CLASS_MODAL, inv.CLASS_SCALAR, inv.CLASS_TEMPORAL, inv.CLASS_CAUSAL, inv.CLASS_EPISTEMIC,
                inv.CLASS_ILLOCUTIONARY, inv.CLASS_VALENCE, inv.CLASS_RELATIONAL, inv.CLASS_DEICTIC,
                inv.CLASS_LOGICAL, inv.CLASS_AFFECT):
        rows.append([script.demo(p) for p in inv.by_class(cls)])
    gap = int(st.cell * 0.25)
    for r, row in enumerate(rows):
        for c, comp in enumerate(row):
            script.draw_char(d, comp, gap + c * (st.cell + gap), gap + r * (st.cell + gap), st)


def character_svgs(comps: Sequence[Composition], cell: int = 256, theme: str = "light") -> dict[str, str]:
    """One transparent SVG per composition's first character, keyed by SID hex —
    the input a font pipeline (fontforge / fonttools) wants."""
    st = CharStyle(cell=cell, theme=theme, frame=False, headline=False)
    return {c.sid_hex(): render_char_svg(c, st) for c in comps}
