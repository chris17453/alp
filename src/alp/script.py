"""The ALP script, character form: one composition = one square character.

Design references: hanzi (components fused into one em-box, reshaped by
position), Egyptian quadrats (a group packed into one square; names in a
cartouche), cuneiform (every sign built from wedge impressions).

A character is composed, not stacked.  The head radical (one of 12 kinds of
thing) sits in the centre of a 17×17 em-box and every modifier class
*transforms* it in its own way:

  scalar        the head's SCALE and FILL          NONE tiny · LOW small · HIGH large · EXTREME doubled
                                                   ALL filled · SOME hatched · BOUNDED bracketed · UNBOUNDED open
                                                   INCREASE / DECREASE: a rising / falling tip on its corner
  epistemic     the head's STROKE                  KNOWN heavy · INFERRED dashed · UNKNOWN dotted
                                                   CONTESTED doubled · OBSERVED eye · PREDICTED forward tip
  modal         the ENCLOSURE around the head      NECESSARY box · POSSIBLE dashed box · HYPOTHETICAL corners
                                                   PERMITTED open-top box · FORBIDDEN lidded box · DESIRED box+dot
                                                   NEGATE slashes the head itself
  valence       the CROWN above                    GOOD ^ · BAD v · REQUIRED = · OPTIONAL dashed · SAFE roof · HARM zigzag
  temporal      the GROUND LINE the head stands on dot left/centre/right = PAST/NOW/FUTURE · doubled = DURATIVE
                                                   tick = PUNCTUAL · end-stops = BEGIN/END · reference bars = BEFORE/DURING/AFTER
  illocutionary the LEFT RADICAL (speech)          bar · +hook REQUEST · doubled COMMIT · +top hook QUERY · crossed REFUSE …
  causal/relational the CONNECTOR on the right     arrows for causation; the relation form for equal/greater/part/has/…
  deictic / affect  INNER marks in the head        upper = who/which; lower = feeling
  logical       small marks at the top-left corner
  roles         ARG0 / ARG1 are seeds INSIDE the head's lobes; other roles form a reduced row beneath,
                each seed with its role marker.  A nested composition's own character follows (depth-first).
  literals      numbers (wedge counts), names (cartouche with visual hash), times, units, refs (seals):
                bound values written after the word they bind to.

Strokes are axis-aligned or 45°, one weight, wedge-headed.  Nothing textual.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from PIL import Image, ImageDraw

from .alpb import Pid, Ref
from . import inventory as inv
from .composition import Composition, Node

GRID = 17
Seg = tuple[float, float, float, float]      # x0, y0, x1, y1 in grid units

# ---------------------------------------------------------------------------
# Head radicals as closed polygons (6×6 local) + extra strokes; seeds (2×2)
# ---------------------------------------------------------------------------

Poly = list[tuple[float, float]]

HEADS: dict[str, tuple[list[Poly], list[Seg]]] = {
    "ENTITY":   ([[(0.5, 0.5), (5.5, 0.5), (5.5, 5.5), (0.5, 5.5)]], []),
    "PROCESS":  ([[(0.5, 1.5), (3.5, 1.5), (3.5, 0.3), (5.7, 3), (3.5, 5.7), (3.5, 4.5), (0.5, 4.5)]], []),
    "PROPERTY": ([[(3, 0.3), (5.7, 3), (3, 5.7), (0.3, 3)]], []),
    "RELATION": ([[(0.5, 0.5), (3, 3), (0.5, 5.5)], [(5.5, 0.5), (3, 3), (5.5, 5.5)]], []),
    "QUANTITY": ([[(0.5, 3.6), (1.7, 3.6), (1.7, 5.7), (0.5, 5.7)], [(2.4, 2.0), (3.6, 2.0), (3.6, 5.7), (2.4, 5.7)],
                  [(4.3, 0.3), (5.5, 0.3), (5.5, 5.7), (4.3, 5.7)]], []),
    "AGENT":    ([[(0.5, 2.5), (3, 0.3), (5.5, 2.5), (5.5, 5.5), (0.5, 5.5)]], []),
    "STATE":    ([[(2, 0.3), (4, 0.3), (5.7, 2), (5.7, 4), (4, 5.7), (2, 5.7), (0.3, 4), (0.3, 2)]], []),
    "PLACE":    ([[(0.3, 0.5), (5.7, 0.5), (3, 5.7)]], [(3, 0.5, 3, 2.3)]),
    "MOMENT":   ([[(2, 0.3), (4, 0.3), (5.7, 2), (5.7, 4), (4, 5.7), (2, 5.7), (0.3, 4), (0.3, 2)]], [(3, 3, 3, 1.3), (3, 3, 4.5, 3)]),
    "SIGN":     ([[(1.2, 0.3), (5.7, 1.9), (1.2, 3.5)]], [(1.2, 0.3, 1.2, 5.7)]),
    "EVENT":    ([[(3, 0.2), (4, 2), (5.8, 3), (4, 4), (3, 5.8), (2, 4), (0.2, 3), (2, 2)]], []),
    "GROUP":    ([[(0.4, 0.4), (2.6, 0.4), (2.6, 2.6), (0.4, 2.6)], [(3.4, 0.4), (5.6, 0.4), (5.6, 2.6), (3.4, 2.6)],
                  [(1.9, 3.4), (4.1, 3.4), (4.1, 5.6), (1.9, 5.6)]], []),
}
# heads with interior room for argument seeds (left lobe / right lobe in local coords)
LOBES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "ENTITY": ((1.2, 2.0), (3.8, 2.0)), "PROPERTY": ((1.6, 2.0), (3.4, 2.0)), "RELATION": ((0.9, 2.0), (4.1, 2.0)),
    "AGENT": ((1.2, 2.8), (3.8, 2.8)), "STATE": ((1.2, 2.0), (3.8, 2.0)), "MOMENT": ((1.0, 3.4), (3.9, 3.4)),
    "PLACE": ((1.4, 1.2), (3.6, 1.2)), "EVENT": ((1.7, 2.0), (3.3, 2.0)), "PROCESS": ((0.9, 2.0), (3.0, 2.0)),
}

SEEDS: dict[str, list[Seg]] = {
    "ENTITY":   [(0.2, 0.2, 1.8, 0.2), (1.8, 0.2, 1.8, 1.8), (1.8, 1.8, 0.2, 1.8), (0.2, 1.8, 0.2, 0.2)],
    "PROCESS":  [(0.2, 0.2, 1.8, 1), (1.8, 1, 0.2, 1.8)],
    "PROPERTY": [(1, 0.1, 1.9, 1), (1.9, 1, 1, 1.9), (1, 1.9, 0.1, 1), (0.1, 1, 1, 0.1)],
    "RELATION": [(0.2, 0.2, 1.8, 1.8), (0.2, 1.8, 1.8, 0.2)],
    "QUANTITY": [(0.5, 1.8, 0.5, 0.9), (1.5, 1.8, 1.5, 0.2)],
    "AGENT":    [(0.2, 1, 1, 0.2), (1, 0.2, 1.8, 1), (0.2, 1, 0.2, 1.8), (1.8, 1, 1.8, 1.8)],
    "STATE":    [(0.6, 0.2, 1.4, 0.2), (1.4, 0.2, 1.8, 0.6), (1.8, 0.6, 1.8, 1.4), (1.8, 1.4, 1.4, 1.8), (1.4, 1.8, 0.6, 1.8), (0.6, 1.8, 0.2, 1.4), (0.2, 1.4, 0.2, 0.6), (0.2, 0.6, 0.6, 0.2)],
    "PLACE":    [(0.2, 0.2, 1.8, 0.2), (1.8, 0.2, 1, 1.8), (1, 1.8, 0.2, 0.2)],
    "MOMENT":   [(0.2, 0.2, 1.8, 0.2), (1, 0.2, 1, 1.8)],
    "SIGN":     [(0.4, 0.2, 0.4, 1.8), (0.4, 0.2, 1.8, 0.8), (1.8, 0.8, 0.4, 1.3)],
    "EVENT":    [(1, 0.1, 1, 1.9), (0.1, 1, 1.9, 1), (0.35, 0.35, 1.65, 1.65), (0.35, 1.65, 1.65, 0.35)],
    "GROUP":    [(0.3, 0.3, 0.7, 0.3), (1.3, 0.3, 1.7, 0.3), (0.8, 1.5, 1.2, 1.5), (0.3, 0.3, 0.3, 0.7), (1.7, 0.3, 1.7, 0.7)],
}

# The small-form alphabet (3×3 local), used for inner marks, role markers, digits, hashes.
FORMS: list[list[Seg]] = [
    [(1.5, 0, 1.5, 3)], [(0, 1.5, 3, 1.5)], [(0, 3, 3, 0)], [(0, 0, 3, 3)],
    [(0, 0.9, 3, 0.9), (0, 2.1, 3, 2.1)], [(1.5, 0, 1.5, 3), (0, 1.5, 3, 1.5)],
    [(0.3, 0, 0.3, 3), (0.3, 3, 3, 3)], [(0, 0, 3, 0), (2.7, 0, 2.7, 3)],
    [(0.3, 0, 2.7, 1.5), (2.7, 1.5, 0.3, 3)], [(2.7, 0, 0.3, 1.5), (0.3, 1.5, 2.7, 3)],
    [(0.3, 0.3, 2.7, 0.3), (2.7, 0.3, 2.7, 2.7), (2.7, 2.7, 0.3, 2.7), (0.3, 2.7, 0.3, 0.3)],
    [(1, 1, 2, 1), (2, 1, 2, 2), (2, 2, 1, 2), (1, 2, 1, 1)],
]

# Scalar: how the head is scaled / filled  (name -> (scale, fill))
SCALAR_SHAPE = {
    "NONE": (0.55, "hollow"), "SOME": (1.0, "half"), "ALL": (1.0, "full"),
    "LOW": (0.72, None), "MID": (1.0, None), "HIGH": (1.18, None), "EXTREME": (1.3, "double"),
    "BOUNDED": (1.0, "brackets"), "UNBOUNDED": (1.0, "open"), "INCREASE": (1.0, "rise"), "DECREASE": (1.0, "fall"),
}
# Epistemic: how the head is stroked  (weight multiplier, dash pattern)
EPISTEMIC_STROKE = {
    "KNOWN": (1.7, None), "BELIEVED": (1.0, None), "INFERRED": (1.0, "dash"), "UNKNOWN": (1.0, "dot"),
    "CONTESTED": (1.0, "double"), "OBSERVED": (1.0, "eye"), "PREDICTED": (1.0, "ahead"),
}

BASE = 8.0            # head box side at scale 1, in grid units
CX = 9.0              # head centre x (room for the left radical)


@dataclass
class CharStyle:
    cell: int = 64                 # px per character
    theme: str = "dark"
    weight: float = 0.55           # stroke width in grid units
    wedge: bool = True             # cuneiform-style wedge head at each stroke start
    gap: float = 0.18              # gap between characters of one word, in cells
    word_gap: float = 0.6          # gap between words, in cells
    frame: bool = False            # faint em-box outline
    grid: bool = False             # faint grid (design aid)


THEMES = {
    "dark": {"bg": (14, 14, 16), "ink": (236, 236, 230), "dim": (78, 78, 82), "faint": (32, 32, 36), "clay": (196, 160, 110)},
    "light": {"bg": (255, 255, 255), "ink": (20, 20, 22), "dim": (180, 180, 176), "faint": (236, 236, 232), "clay": (120, 90, 50)},
}


# ---------------------------------------------------------------------------
# Pen
# ---------------------------------------------------------------------------

class _Pen:
    def __init__(self, draw: ImageDraw.ImageDraw, ox: float, oy: float, unit: float, ink, st: CharStyle) -> None:
        self.d, self.ox, self.oy, self.u, self.ink, self.st = draw, ox, oy, unit, ink, st
        self.w = max(1, int(round(st.weight * unit)))

    def P(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.u, self.oy + y * self.u

    def seg(self, x0, y0, x1, y1, ink=None, w: int | None = None, dash: str | None = None, wedge: bool | None = None) -> None:
        ink = ink or self.ink
        w = w or self.w
        if dash:
            self._dashed(x0, y0, x1, y1, ink, w, dash)
            return
        X0, Y0 = self.P(x0, y0)
        X1, Y1 = self.P(x1, y1)
        self.d.line([(X0, Y0), (X1, Y1)], fill=ink, width=w)
        h = w / 2
        dx, dy = X1 - X0, Y1 - Y0
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        axis = (x0 == x1) or (y0 == y1)
        for (X, Y) in ((X0, Y0), (X1, Y1)):
            if axis:
                self.d.rectangle([X - h, Y - h, X + h, Y + h], fill=ink)
            else:
                self.d.ellipse([X - h, Y - h, X + h, Y + h], fill=ink)
        if (self.st.wedge if wedge is None else wedge) and L > 6.0 * w:
            bw, bl = 1.3 * w, 2.3 * w
            px, py = -uy, ux
            self.d.polygon([(X0 - ux * h + px * bw, Y0 - uy * h + py * bw),
                            (X0 - ux * h - px * bw, Y0 - uy * h - py * bw),
                            (X0 + ux * bl, Y0 + uy * bl)], fill=ink)

    def _dashed(self, x0, y0, x1, y1, ink, w, dash) -> None:
        L = math.hypot(x1 - x0, y1 - y0)
        if L == 0:
            return
        on, off = (0.9, 0.55) if dash == "dash" else (0.28, 0.5)
        n = max(1, int(L // (on + off)))
        step = L / n
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        seg_on = min(on, step * 0.6)
        for i in range(n):
            a = i * step + (step - seg_on) / 2
            self.seg(x0 + ux * a, y0 + uy * a, x0 + ux * (a + seg_on), y0 + uy * (a + seg_on), ink, w, None, False)

    def segs(self, segs: list[Seg], ox: float, oy: float, scale: float = 1.0, ink=None, w: int | None = None, dash=None) -> None:
        for x0, y0, x1, y1 in segs:
            self.seg(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale, ink, w, dash)

    def poly(self, pts: Poly, ox: float, oy: float, scale: float = 1.0, ink=None, w: int | None = None,
             dash=None, fill: bool = False) -> None:
        if fill:
            self.d.polygon([self.P(ox + x * scale, oy + y * scale) for x, y in pts], fill=ink or self.ink)
            return
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            self.seg(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale, ink, w, dash)


def _form(member: int) -> list[Seg]:
    return FORMS[member % len(FORMS)]


def _seed_name(n: Node) -> str | None:
    if isinstance(n, Pid):
        return inv.name_of(n) if n.cls == inv.CLASS_ONTOLOGICAL else None
    if isinstance(n, Composition):
        return inv.name_of(n.head)
    return None


def _draw_seed(pen: _Pen, node: Node, x: float, y: float, scale: float = 1.0, ink=None) -> None:
    name = _seed_name(node)
    if name is not None:
        pen.segs(SEEDS[name], x, y, scale, ink)
    elif isinstance(node, Pid):
        pen.segs(_form(node.member), x - 0.2 * scale, y - 0.2 * scale, 0.75 * scale, ink)
    else:  # SID reference: hook
        pen.seg(x + 0.2 * scale, y + 1.8 * scale, x + 1.8 * scale, y + 0.2 * scale, ink)
        pen.seg(x + 1.8 * scale, y + 0.2 * scale, x + 1.8 * scale, y + 1.1 * scale, ink)


# ---------------------------------------------------------------------------
# The composer
# ---------------------------------------------------------------------------

@dataclass
class _Plan:
    scalar: list[Pid] = field(default_factory=list)
    epistemic: list[Pid] = field(default_factory=list)
    modal: list[Pid] = field(default_factory=list)
    temporal: list[Pid] = field(default_factory=list)
    valence: list[Pid] = field(default_factory=list)
    illoc: list[Pid] = field(default_factory=list)
    causal: list[Pid] = field(default_factory=list)
    relational: list[Pid] = field(default_factory=list)
    deictic: list[Pid] = field(default_factory=list)
    logical: list[Pid] = field(default_factory=list)
    affect: list[Pid] = field(default_factory=list)
    negate: bool = False
    overflow: list[Pid] = field(default_factory=list)


_CLASS_FIELD = {
    inv.CLASS_SCALAR: ("scalar", 1), inv.CLASS_EPISTEMIC: ("epistemic", 2), inv.CLASS_MODAL: ("modal", 1),
    inv.CLASS_TEMPORAL: ("temporal", 2), inv.CLASS_VALENCE: ("valence", 1), inv.CLASS_ILLOCUTIONARY: ("illoc", 1),
    inv.CLASS_CAUSAL: ("causal", 1), inv.CLASS_RELATIONAL: ("relational", 1), inv.CLASS_DEICTIC: ("deictic", 1),
    inv.CLASS_LOGICAL: ("logical", 2), inv.CLASS_AFFECT: ("affect", 1),
}


def _plan(comp: Composition) -> _Plan:
    pl = _Plan()
    for m in sorted((m for m in comp.modifiers if isinstance(m, Pid)), key=lambda p: p.code):
        if inv.name_of(m) == "NEGATE":
            pl.negate = True
            continue
        f = _CLASS_FIELD.get(m.cls)
        if f is None:
            continue
        name, cap = f
        lst = getattr(pl, name)
        if len(lst) < cap:
            lst.append(m)
        else:
            pl.overflow.append(m)
    return pl


def draw_char(draw: ImageDraw.ImageDraw, comp: Composition | None, x: float, y: float, st: CharStyle,
              depth: int = 0, overflow: list[Pid] | None = None, extra_roles: list | None = None) -> None:
    """Compose one character at (x, y).

    With ``overflow``/``extra_roles`` this draws a continuation character:
    the same head, faint, carrying only the spill-over modifiers / roles."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    if st.grid:
        for i in range(GRID + 1):
            draw.line([(x + i * u, y), (x + i * u, y + st.cell)], fill=C["faint"], width=1)
            draw.line([(x, y + i * u), (x + st.cell, y + i * u)], fill=C["faint"], width=1)
    if st.frame:
        draw.rectangle([x, y, x + st.cell - 1, y + st.cell - 1], outline=C["dim"], width=1)
    if comp is None:
        return
    continuation = overflow is not None or extra_roles is not None
    if continuation:
        pl = _Plan()
        for m in overflow or []:
            f = _CLASS_FIELD.get(m.cls)
            if f:
                getattr(pl, f[0]).append(m)
        roles = list(extra_roles or [])
    else:
        pl = _plan(comp)
        roles = list(comp.roles)
    hname = inv.name_of(comp.head)

    # -- geometry: head box ------------------------------------------------------
    scale, fillmode = 1.0, None
    if pl.scalar:
        scale, fillmode = SCALAR_SHAPE[inv.name_of(pl.scalar[0])]
    side = BASE * scale
    has_crown = bool(pl.valence)
    has_base = bool(pl.temporal)
    # vertical placement: crown above, ground line below, role row at the bottom
    top = 2.4 if has_crown else 1.2
    bottom_reserved = (1.8 if has_base else 0.6) + (2.6 if _below_roles(comp, roles, hname, scale) else 0)
    avail = GRID - top - bottom_reserved
    if side > avail:
        scale *= avail / side
        side = avail
    hx0 = CX - side / 2
    hy0 = top + (avail - side) / 2
    k = side / 6.0                                  # local 6×6 -> grid
    wmul, dash = 1.0, None
    for ep in pl.epistemic:                      # two epistemic marks combine: weight from one, texture from the other
        w2, d2 = EPISTEMIC_STROKE[inv.name_of(ep)]
        wmul = max(wmul, w2)
        if d2 in ("dash", "dot") and dash not in ("dash", "dot"):
            dash = d2
        elif dash is None:
            dash = d2
    hw = max(1, int(round(pen.w * wmul)))
    ink = C["dim"] if continuation else C["ink"]
    polys, extra = HEADS[hname]

    # -- head ---------------------------------------------------------------------
    if fillmode == "full":
        for pg in polys:
            pen.poly(pg, hx0, hy0, k, ink, fill=True)
    else:
        d = dash if dash in ("dash", "dot") else None
        for pg in polys:
            pen.poly(pg, hx0, hy0, k, ink, hw, d)
        pen.segs(extra, hx0, hy0, k, ink, hw, d)
        if dash == "double":
            for pg in polys:
                pen.poly(pg, hx0 + 0.55, hy0 + 0.55, k, C["dim"], max(1, hw // 2))
        if fillmode == "half":
            for i in range(3):
                yy = hy0 + side * (0.62 + i * 0.12)
                pen.seg(hx0 + side * 0.18, yy, hx0 + side * 0.82, yy, ink, max(1, hw // 2), wedge=False)
        if fillmode == "double":
            for pg in polys:
                pen.poly(pg, hx0 + 0.9 * k / (side / 6), hy0 + 0.9, k * 0.7, ink, max(1, hw // 2))
        if fillmode == "hollow":
            pen.seg(hx0 + side / 2, hy0 + side / 2, hx0 + side / 2, hy0 + side / 2, ink, max(1, hw // 2))
    ep_names = {inv.name_of(e) for e in pl.epistemic}
    if "OBSERVED" in ep_names:
        cx, cy = hx0 + side / 2, hy0 + side / 2
        pen.segs(FORMS[11], cx - 1.5, cy - 1.5, 1.0, ink)
    if "CONTESTED" in ep_names and dash != "double":
        for pg in polys:
            pen.poly(pg, hx0 + 0.55, hy0 + 0.55, k, C["dim"], max(1, hw // 2))
    if "PREDICTED" in ep_names and dash != "ahead":
        dash = "ahead"
    if dash == "ahead":
        cy = hy0 + side / 2
        pen.seg(hx0 + side, cy, hx0 + side + 1.6, cy, ink, hw)
        pen.seg(hx0 + side + 1.6, cy, hx0 + side + 0.8, cy - 0.8, ink, hw, wedge=False)
        pen.seg(hx0 + side + 1.6, cy, hx0 + side + 0.8, cy + 0.8, ink, hw, wedge=False)
    if fillmode == "brackets":
        for sx, dx in ((hx0 - 0.9, 0.7), (hx0 + side + 0.9, -0.7)):
            pen.seg(sx, hy0, sx, hy0 + side, ink, hw)
            pen.seg(sx, hy0, sx + dx, hy0, ink, hw, wedge=False)
            pen.seg(sx, hy0 + side, sx + dx, hy0 + side, ink, hw, wedge=False)
    if fillmode == "open":
        cy = hy0 + side / 2
        pen.seg(hx0 - 2.2, cy, hx0, cy, ink, hw)
        pen.seg(hx0 + side, cy, hx0 + side + 2.2, cy, ink, hw)
    if fillmode in ("rise", "fall"):
        yy = hy0 if fillmode == "rise" else hy0 + side
        pen.seg(hx0 + side, yy, hx0 + side + 1.6, yy - 1.6 if fillmode == "rise" else yy + 1.6, ink, hw)
        tip = (hx0 + side + 1.6, yy - 1.6 if fillmode == "rise" else yy + 1.6)
        pen.seg(tip[0], tip[1], tip[0] - 1.2, tip[1], ink, hw, wedge=False)
        pen.seg(tip[0], tip[1], tip[0], tip[1] + (1.2 if fillmode == "rise" else -1.2), ink, hw, wedge=False)

    # -- negation: the slash across the head ---------------------------------------
    if pl.negate and not continuation:
        pen.seg(hx0 - 0.4, hy0 + side + 0.4, hx0 + side + 0.4, hy0 - 0.4, ink, hw)

    # -- modal enclosure ------------------------------------------------------------
    if pl.modal:
        mname = inv.name_of(pl.modal[0])
        m = 1.0
        ex0, ey0, ex1, ey1 = hx0 - m, hy0 - m, hx0 + side + m, hy0 + side + m
        box = [(ex0, ey0), (ex1, ey0), (ex1, ey1), (ex0, ey1)]
        thin = max(1, int(pen.w * 0.7))
        if mname == "NECESSARY":
            pen.poly(box, 0, 0, 1, ink, thin)
        elif mname == "POSSIBLE":
            pen.poly(box, 0, 0, 1, ink, thin, "dash")
        elif mname == "HYPOTHETICAL":
            L = 1.4
            for (px, py, sx, sy) in ((ex0, ey0, 1, 1), (ex1, ey0, -1, 1), (ex1, ey1, -1, -1), (ex0, ey1, 1, -1)):
                pen.seg(px, py, px + sx * L, py, ink, thin, wedge=False)
                pen.seg(px, py, px, py + sy * L, ink, thin, wedge=False)
        elif mname == "PERMITTED":
            pen.seg(ex0, ey0, ex0, ey1, ink, thin); pen.seg(ex0, ey1, ex1, ey1, ink, thin); pen.seg(ex1, ey1, ex1, ey0, ink, thin)
        elif mname == "FORBIDDEN":
            pen.poly(box, 0, 0, 1, ink, thin)
            pen.seg(ex0, ey0 - 0.9, ex1, ey0 - 0.9, ink, hw)
        elif mname == "DESIRED":
            pen.poly(box, 0, 0, 1, ink, thin)
            pen.segs(FORMS[11], ex1 - 2.2, ey0 - 0.9, 0.6, ink)
        elif mname == "AFFIRM":
            pen.seg(ex0, ey1, ex1, ey1, ink, thin)
        hx_enc0, hx_enc1, hy_enc0, hy_enc1 = ex0, ex1, ey0, ey1
    else:
        hx_enc0, hx_enc1, hy_enc0, hy_enc1 = hx0, hx0 + side, hy0, hy0 + side

    # -- valence crown --------------------------------------------------------------
    if pl.valence:
        v = inv.name_of(pl.valence[0])
        cy = hy_enc0 - 0.9
        cx0, cx1 = hx_enc0 + 0.5, hx_enc1 - 0.5
        mid = (cx0 + cx1) / 2
        if v == "GOOD":
            pen.seg(cx0, cy, mid, cy - 1.3, ink, hw); pen.seg(mid, cy - 1.3, cx1, cy, ink, hw)
        elif v == "BAD":
            pen.seg(cx0, cy - 1.3, mid, cy, ink, hw); pen.seg(mid, cy, cx1, cy - 1.3, ink, hw)
        elif v == "REQUIRED":
            pen.seg(cx0, cy, cx1, cy, ink, hw); pen.seg(cx0, cy - 1.0, cx1, cy - 1.0, ink, hw)
        elif v == "OPTIONAL":
            pen.seg(cx0, cy, cx1, cy, ink, hw, "dash")
        elif v == "SAFE":
            pen.seg(cx0, cy - 0.6, cx1, cy - 0.6, ink, hw); pen.seg(cx0, cy - 0.6, cx0, cy + 0.6, ink, hw, wedge=False); pen.seg(cx1, cy - 0.6, cx1, cy + 0.6, ink, hw, wedge=False)
        elif v == "HARM":
            n = 4
            step = (cx1 - cx0) / n
            for i in range(n):
                a, b = cx0 + i * step, cx0 + (i + 0.5) * step
                pen.seg(a, cy, b, cy - 1.3, ink, hw, wedge=False); pen.seg(b, cy - 1.3, a + step, cy, ink, hw, wedge=False)
        elif v == "COST":
            pen.seg(cx0, cy, cx1, cy, ink, hw); pen.seg(cx0, cy, cx0, cy + 1.0, ink, hw, wedge=False)
        elif v == "BENEFIT":
            pen.seg(cx0, cy, cx1, cy, ink, hw); pen.seg(cx1, cy, cx1, cy - 1.2, ink, hw, wedge=False)

    # -- temporal ground line -------------------------------------------------------
    role_y = None
    if pl.temporal:
        gy = hy_enc1 + 0.9
        gx0, gx1 = hx_enc0 - 0.6, hx_enc1 + 0.6
        for i, t in enumerate(pl.temporal):
            tn = inv.name_of(t)
            yy = gy + i * 1.1
            dot = {"PAST": 0.12, "NOW": 0.5, "FUTURE": 0.88, "BEFORE": 0.2, "AFTER": 0.8, "DURING": 0.5}.get(tn)
            if tn == "PUNCTUAL":
                pen.seg(CX, yy - 0.5, CX, yy + 0.5, ink, hw)
            elif tn == "DURATIVE":
                pen.seg(gx0, yy, gx1, yy, ink, hw); pen.seg(gx0, yy + 0.7, gx1, yy + 0.7, ink, hw)
            elif tn == "REPEAT":
                pen.seg(gx0, yy, gx1, yy, ink, hw)
                for f in (0.3, 0.6):
                    px = gx0 + (gx1 - gx0) * f
                    pen.seg(px, yy - 0.7, px + 0.7, yy, ink, hw, wedge=False); pen.seg(px + 0.7, yy, px, yy + 0.7, ink, hw, wedge=False)
            elif tn == "BEGIN":
                pen.seg(gx0, yy, gx1, yy, ink, hw); pen.seg(gx0, yy - 0.9, gx0, yy + 0.9, ink, hw)
            elif tn == "END":
                pen.seg(gx0, yy, gx1, yy, ink, hw); pen.seg(gx1, yy - 0.9, gx1, yy + 0.9, ink, hw)
            else:
                pen.seg(gx0, yy, gx1, yy, ink, hw)
                if tn in ("BEFORE", "AFTER", "DURING"):
                    for f in ((0.65,) if tn == "BEFORE" else (0.35,) if tn == "AFTER" else (0.2, 0.8)):
                        px = gx0 + (gx1 - gx0) * f
                        pen.seg(px, yy - 0.9, px, yy + 0.9, ink, hw)
                if dot is not None:
                    px = gx0 + (gx1 - gx0) * dot
                    pen.segs(FORMS[11], px - 1.5, yy - 1.5, 1.0, ink)
        role_y = gy + len(pl.temporal) * 1.1 + 0.6
    else:
        role_y = hy_enc1 + 0.9

    # -- illocutionary left radical -------------------------------------------------
    if pl.illoc:
        iname = inv.name_of(pl.illoc[0])
        rx = 1.3
        ry0, ry1 = hy_enc0, hy_enc1
        if iname == "PROPOSE":
            pen.seg(rx, ry0, rx, ry1, ink, hw, "dash")
        else:
            pen.seg(rx, ry0, rx, ry1, ink, hw)
        if iname == "REQUEST":
            pen.seg(rx, ry1, rx + 1.3, ry1, ink, hw, wedge=False)
        elif iname == "COMMIT":
            pen.seg(rx + 1.1, ry0, rx + 1.1, ry1, ink, hw)
        elif iname == "QUERY":
            pen.seg(rx, ry0, rx + 1.3, ry0, ink, hw, wedge=False); pen.seg(rx + 1.3, ry0, rx + 1.3, ry0 + 1.3, ink, hw, wedge=False)
        elif iname == "WARN":
            pen.seg(rx, (ry0 + ry1) / 2, rx + 1.3, (ry0 + ry1) / 2, ink, hw, wedge=False)
        elif iname == "REFUSE":
            pen.seg(rx - 0.9, (ry0 + ry1) / 2 + 1, rx + 0.9, (ry0 + ry1) / 2 - 1, ink, hw, wedge=False)
        elif iname == "ACKNOWLEDGE":
            pen.seg(rx, ry1, rx + 0.7, ry1 + 0.7, ink, hw, wedge=False); pen.seg(rx + 0.7, ry1 + 0.7, rx + 1.6, ry1 - 0.6, ink, hw, wedge=False)

    # -- causal / relational connector on the right -----------------------------------
    conn = (pl.causal + pl.relational)[:1]
    if conn:
        cn = inv.name_of(conn[0])
        cy = (hy_enc0 + hy_enc1) / 2
        ax0, ax1 = hx_enc1 + 0.5, min(GRID - 0.6, hx_enc1 + 3.0)
        def arrow(x0, x1, yy, back=False):
            pen.seg(x0, yy, x1, yy, ink, hw)
            tip, dirn = (x0, 1) if back else (x1, -1)
            pen.seg(tip, yy, tip + dirn * 0.9, yy - 0.9, ink, hw, wedge=False); pen.seg(tip, yy, tip + dirn * 0.9, yy + 0.9, ink, hw, wedge=False)
        if cn == "CAUSE":
            arrow(ax0, ax1, cy)
        elif cn == "ENABLE":
            pen.seg(ax0, cy, ax1 - 0.9, cy, ink, hw, "dash"); arrow(ax1 - 1.0, ax1, cy)
        elif cn == "PREVENT":
            arrow(ax0, ax1, cy); pen.seg((ax0 + ax1) / 2, cy - 1.1, (ax0 + ax1) / 2, cy + 1.1, ink, hw)
        elif cn == "CORRELATE":
            arrow(ax0, ax1, cy); pen.seg(ax0, cy, ax0 + 0.9, cy - 0.9, ink, hw, wedge=False); pen.seg(ax0, cy, ax0 + 0.9, cy + 0.9, ink, hw, wedge=False)
        elif cn == "DEPEND":
            arrow(ax0, ax1, cy, back=True)
        elif cn == "TRIGGER":
            pen.seg(ax0, cy - 1.1, ax0, cy + 1.1, ink, hw); arrow(ax0, ax1, cy)
        else:  # relational: the member's form, sitting on the right edge
            pen.segs(_form(conn[0].member), ax0, cy - 1.5, 1.0, ink)

    # -- inner marks: deixis (upper), affect (lower), logical (upper-left outside) -------
    if pl.deictic:
        pen.segs(_form(pl.deictic[0].member), CX - 0.9, hy0 + side * 0.12, 0.6, ink)
    if pl.affect:
        pen.segs(_form(pl.affect[0].member), CX - 0.9, hy0 + side * 0.72, 0.6, ink)
    for i, lg in enumerate(pl.logical):
        pen.segs(_form(lg.member), 0.4 + i * 2.0, 0.2, 0.55, ink)

    # -- roles: ARG0/ARG1 inside the lobes when there is room, the rest in a row below ----
    inside: dict[int, Node] = {}
    below: list[tuple[int, Node]] = []
    lob = LOBES.get(hname) if (scale >= 0.9 and fillmode not in ("full", "half") and not continuation) else None
    for code, node in roles:
        if lob is not None and code in (1, 2) and code not in inside:
            inside[code] = node
        else:
            below.append((code, node))
    if lob is not None:
        for code, node in inside.items():
            lx, ly = lob[0 if code == 1 else 1]
            _draw_seed(pen, node, hx0 + lx * k, hy0 + ly * k, max(0.7, k * 0.85), ink)
            if isinstance(node, Composition):
                pen.seg(hx0 + lx * k, hy0 + (ly + 2.4) * k, hx0 + (lx + 2) * k, hy0 + (ly + 2.4) * k, ink, max(1, hw // 2), wedge=False)
    if below:
        n = min(len(below), 4)
        sw = 3.2
        rx0 = CX - (n * sw) / 2
        yy = max(role_y, GRID - 2.6)
        yy = min(yy, GRID - 2.4)
        for i, (code, node) in enumerate(below[:4]):
            sx = rx0 + i * sw
            _draw_seed(pen, node, sx, yy, 1.0, ink)
            pen.segs(_form(code - 1), sx + 2.15, yy + 0.7, 0.33, ink, max(1, pen.w // 2))
            if isinstance(node, Composition):
                pen.seg(sx, yy - 0.5, sx + 2, yy - 0.5, ink, max(1, hw // 2), wedge=False)

    if continuation:
        return
    if comp.residue is not None:
        pen.segs([(0, 1.6, 0.6, 0), (0.6, 0, 1.2, 1.6), (1.2, 1.6, 1.8, 0), (1.8, 0, 2.4, 1.6)], 0.6, GRID - 2.2, 1.0, C["dim"], max(1, pen.w // 2))
    for i in range(depth):
        pen.seg(0.6 + i * 0.9, GRID - 0.6, 0.6 + i * 0.9, GRID - 0.6, ink)


def _below_roles(comp: Composition, roles: list, hname: str, scale: float) -> bool:
    lob = LOBES.get(hname) if scale >= 0.9 else None
    return any(not (lob is not None and code in (1, 2)) for code, _ in roles)


def word_chars(comp: Composition) -> list[tuple[Composition, int, list | None, list | None]]:
    """(comp, depth, overflow-mods|None, extra-roles|None) per character of the word."""
    out: list = []

    def visit(c: Composition, depth: int) -> None:
        out.append((c, depth, None, None))
        pl = _plan(c)
        lob = LOBES.get(inv.name_of(c.head))
        below = [r for r in c.roles if not (lob is not None and r[0] in (1, 2))]
        extra = below[4:]
        if pl.overflow or extra:
            out.append((c, depth, pl.overflow, extra))
        for m in c.modifiers:
            if isinstance(m, Composition):
                visit(m, depth + 1)
        for _, node in c.roles:
            if isinstance(node, Composition):
                visit(node, depth + 1)

    visit(comp, 0)
    return out


# ---------------------------------------------------------------------------
# Literal characters: numbers, names, times, units, references
# ---------------------------------------------------------------------------

def _digit_segs(d: int) -> list[Seg]:
    """Cuneiform-style digit in a 3×3 cell: d wedges, stacked in rows of three; 0 = box."""
    if d == 0:
        return FORMS[11]
    segs: list[Seg] = []
    for i in range(d):
        row, col = divmod(i, 3)
        n_in_row = min(3, d - row * 3)
        x = 0.5 + col * 1.0 + (3 - n_in_row) * 0.5
        y0 = 0.1 + row * 1.0
        segs.append((x, y0, x, y0 + 0.8))
    return segs


def draw_numeral(draw: ImageDraw.ImageDraw, value: float | int, x: float, y: float, st: CharStyle) -> int:
    """Number as wedge-count digits, four per character.  Returns characters used."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    neg = value < 0
    value = abs(value)
    if isinstance(value, float) and not value.is_integer():
        text = f"{value:.6g}"
    else:
        text = str(int(value))
    if "e" in text:
        text = f"{float(text):.0f}"
    groups = [text[i:i + 4] for i in range(0, len(text), 4)]
    cells = 0
    for gi, g in enumerate(groups):
        pen = _Pen(draw, x + cells * (st.cell + st.gap * st.cell), y, u, C["ink"], st)
        # frame line under the digits marks a numeral character (NUM marker)
        pen.seg(1, 15.5, 16, 15.5, w=max(1, pen.w // 2))
        if gi == 0 and neg:
            pen.seg(1, 2, 3, 2)
        cx = 1.5
        for ch in g:
            if ch == ".":
                pen.segs(FORMS[11], cx + 0.8, 11.5, 0.6)
                cx += 1.8
                continue
            pen.segs(_digit_segs(int(ch)), cx - 0.3, 4.5, 1.6, w=max(1, pen.w))
            cx += 4.0
        cells += 1
    return cells


def visual_hash(text: str) -> list[int]:
    """Nine form indices from the SHA-256 of the text — a name's visual signature."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    return [b % len(FORMS) for b in h[:9]]


def draw_cartouche(draw: ImageDraw.ImageDraw, name: str, x: float, y: float, st: CharStyle) -> int:
    """A name: an enclosure (the cartouche) around a 3×3 visual hash of the name."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    w = max(1, pen.w // 2)
    # rounded enclosure: straight sides, chamfered corners, a tie at the bottom
    pen.segs([(1.5, 0.5, 15.5, 0.5), (15.5, 0.5, 16.5, 1.5), (16.5, 1.5, 16.5, 14.5), (16.5, 14.5, 15.5, 15.5),
              (15.5, 15.5, 1.5, 15.5), (1.5, 15.5, 0.5, 14.5), (0.5, 14.5, 0.5, 1.5), (0.5, 1.5, 1.5, 0.5),
              (6, 15.5, 6, 16.8), (11, 15.5, 11, 16.8)], 0, 0, 1.0, C["clay"], w)
    for i, f in enumerate(visual_hash(name)):
        r, c = divmod(i, 3)
        pen.segs(FORMS[f], 3.2 + c * 4.0, 2.5 + r * 4.0, 0.9)
    return 1


def draw_seal(draw: ImageDraw.ImageDraw, ref: bytes, x: float, y: float, st: CharStyle, eid: bool = False) -> int:
    """A reference to a SID or EID: a seal — a square with a 2×2 hash pattern."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    w = max(1, pen.w // 2)
    pen.segs([(1, 1, 16, 1), (16, 1, 16, 16), (16, 16, 1, 16), (1, 16, 1, 1)], 0, 0, 1.0, C["clay"], w)
    if eid:
        pen.segs([(1, 1, 16, 16)], 0, 0, 1.0, C["clay"], w)
    for i, b in enumerate(bytes(ref)[:4]):
        r, c = divmod(i, 2)
        pen.segs(FORMS[b % len(FORMS)], 3 + c * 6.5, 3 + r * 6.5, 1.5)
    return 1


_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")


def draw_time(draw: ImageDraw.ImageDraw, iso: str, x: float, y: float, st: CharStyle) -> int:
    """A date/time literal: MOMENT seed in the corner, then numerals YYYY MMDD [HHMM]."""
    C = THEMES[st.theme]
    m = _ISO.match(iso)
    if not m:
        return draw_cartouche(draw, iso, x, y, st)
    parts = [m.group(1), m.group(2) + m.group(3)] + ([m.group(4) + m.group(5)] if m.group(4) else [])
    cells = 0
    for i, p in enumerate(parts):
        px = x + cells * (st.cell + st.gap * st.cell)
        n = draw_numeral(draw, int(p), px, y, st)
        if i == 0:
            pen = _Pen(draw, px, y, st.cell / GRID, C["ink"], st)
            pen.segs(SEEDS["MOMENT"], 0.5, 0.5, 1.0, C["clay"])
        cells += n
    return cells


def draw_unit(draw: ImageDraw.ImageDraw, unit: str, x: float, y: float, st: CharStyle) -> int:
    """A unit of measure: a small cartouche-like tag (units are names too)."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    w = max(1, pen.w // 2)
    pen.segs([(2, 4, 15, 4), (15, 4, 15, 13), (15, 13, 2, 13), (2, 13, 2, 4)], 0, 0, 1.0, C["clay"], w)
    for i, f in enumerate(visual_hash("unit:" + unit)[:3]):
        pen.segs(FORMS[f], 3.5 + i * 3.9, 6, 0.85)
    return 1


# ---------------------------------------------------------------------------
# Bindings: the value side of an utterance
# ---------------------------------------------------------------------------

def literals_of(value: Any) -> list[tuple[str, str, Any]]:
    """Flatten an ASSERT value into (role-path, kind, payload) literals.

    Recognised shapes:  ``True``;  ``{"bind": {path: literal}}`` where a literal
    is an int/float, a str, ``{"t": iso}``, ``{"u": unit}``, ``{"n": num, "u": unit}``,
    a ``Ref``;  legacy ``{"names": {path: str}}``;  any other scalar.
    """
    out: list[tuple[str, str, Any]] = []
    if value is True or value is None:
        return out
    if isinstance(value, dict) and ("bind" in value or "names" in value):
        for path, lit in (value.get("bind") or value.get("names") or {}).items():
            out += _literal(path, lit)
        return out
    return _literal(".", value)


def _literal(path: str, lit: Any) -> list[tuple[str, str, Any]]:
    if isinstance(lit, bool):
        return []
    if isinstance(lit, (int, float)):
        return [(path, "num", lit)]
    if isinstance(lit, str):
        return [(path, "time", lit)] if _ISO.match(lit) else [(path, "name", lit)]
    if isinstance(lit, Ref):
        return [(path, "eref" if lit.is_eid else "ref", lit.data)]
    if isinstance(lit, dict):
        out = []
        if "n" in lit:
            out.append((path, "num", lit["n"]))
        if "t" in lit:
            out.append((path, "time", lit["t"]))
        if "s" in lit:
            out.append((path, "name", lit["s"]))
        if "u" in lit:
            out.append((path, "unit", lit["u"]))
        return out
    if isinstance(lit, list):
        out = []
        for x in lit:
            out += _literal(path, x)
        return out
    return [(path, "name", str(lit))]


def _role_code_of_path(path: str) -> int | None:
    last = path.split("/")[-1]
    return inv.ROLES.get(last)


def draw_literal(draw: ImageDraw.ImageDraw, kind: str, payload: Any, x: float, y: float, st: CharStyle) -> int:
    if kind == "num":
        return draw_numeral(draw, payload, x, y, st)
    if kind == "name":
        return draw_cartouche(draw, payload, x, y, st)
    if kind == "time":
        return draw_time(draw, payload, x, y, st)
    if kind == "unit":
        return draw_unit(draw, payload, x, y, st)
    if kind in ("ref", "eref"):
        return draw_seal(draw, payload, x, y, st, eid=(kind == "eref"))
    return 0


def _binding_marker(draw: ImageDraw.ImageDraw, path: str, x: float, y: float, st: CharStyle) -> None:
    """Between a word and its literal: the role's form (which slot the literal fills)."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["clay"], st)
    code = _role_code_of_path(path)
    if code is None:
        pen.seg(3, 8.5, 6, 8.5, w=max(1, pen.w // 2))
    else:
        pen.segs(_form(code - 1), 3, 7, 1.0, C["clay"], max(1, pen.w // 2))


# ---------------------------------------------------------------------------
# Words, utterances, text
# ---------------------------------------------------------------------------

def _n_literal_cells(value: Any, st: CharStyle) -> int:
    n = 0
    for path, kind, payload in literals_of(value):
        n += 1   # marker
        if kind == "num":
            txt = f"{abs(payload):.6g}" if isinstance(payload, float) and not float(payload).is_integer() else str(int(abs(payload)))
            n += max(1, math.ceil(len(txt) / 4))
        elif kind == "time":
            m = _ISO.match(str(payload))
            n += (3 if m and m.group(4) else 2) if m else 1
        else:
            n += 1
    return n


def word_width(comp: Composition, st: CharStyle, value: Any = True) -> int:
    n = len(word_chars(comp)) + _n_literal_cells(value, st)
    return int(n * st.cell + (n - 1) * st.gap * st.cell)


def draw_word(draw: ImageDraw.ImageDraw, comp: Composition, x: float, y: float, st: CharStyle, value: Any = True) -> float:
    """Draw a composition (and its bound literals) as a word; returns the x after it."""
    step = st.cell + st.gap * st.cell
    for i, (c, depth, overflow, extra_roles) in enumerate(word_chars(comp)):
        if overflow is not None or extra_roles is not None:
            draw_char(draw, c, x, y, st, depth, overflow=overflow or [], extra_roles=extra_roles or [])
        else:
            draw_char(draw, c, x, y, st, depth)
        x += step
    for path, kind, payload in literals_of(value):
        _binding_marker(draw, path, x, y, st)
        x += step * 0.5
        n = draw_literal(draw, kind, payload, x, y, st)
        x += step * n
    return x - st.gap * st.cell


def render_word(comp: Composition, st: CharStyle | None = None, value: Any = True) -> Image.Image:
    st = st or CharStyle()
    C = THEMES[st.theme]
    w = word_width(comp, st, value)
    img = Image.new("RGB", (w, st.cell), C["bg"])
    draw_word(ImageDraw.Draw(img), comp, 0, 0, st, value)
    return img


def render_char(comp: Composition, st: CharStyle | None = None) -> Image.Image:
    st = st or CharStyle()
    C = THEMES[st.theme]
    img = Image.new("RGB", (st.cell, st.cell), C["bg"])
    draw_char(ImageDraw.Draw(img), comp, 0, 0, st)
    return img


Utterance = tuple  # (Composition, value) ; None = line break


def render_text(words: Sequence[Utterance | Composition | None], st: CharStyle | None = None, width: int = 1200,
                margin: int = 24, line_gap: float = 0.45) -> Image.Image:
    """Lay utterances out as running text.  ``None`` forces a line break."""
    st = st or CharStyle()
    C = THEMES[st.theme]
    inner = width - 2 * margin
    norm: list[tuple[Composition, Any] | None] = []
    for w in words:
        if w is None:
            norm.append(None)
        elif isinstance(w, Composition):
            norm.append((w, True))
        else:
            norm.append((w[0], w[1]))
    lines: list[list[tuple[Composition, Any]]] = [[]]
    cur_w = 0
    for w in norm:
        if w is None:
            lines.append([])
            cur_w = 0
            continue
        ww = word_width(w[0], st, w[1])
        add = ww + (st.word_gap * st.cell if lines[-1] else 0)
        if lines[-1] and cur_w + add > inner:
            lines.append([w])
            cur_w = ww
        else:
            lines[-1].append(w)
            cur_w += add
    line_h = st.cell * (1 + line_gap)
    height = int(2 * margin + len(lines) * line_h)
    img = Image.new("RGB", (width, height), C["bg"])
    d = ImageDraw.Draw(img)
    y = margin
    for line in lines:
        x = margin
        for comp, value in line:
            x = draw_word(d, comp, x, y, st, value) + st.word_gap * st.cell
        y += line_h
    return img


def render_chart(st: CharStyle | None = None) -> Image.Image:
    """Design chart: the 12 heads bare, then every modifier class on an ENTITY head, then literals."""
    st = st or CharStyle(cell=80, frame=True)
    C = THEMES[st.theme]
    heads = [Composition(p) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]
    rows: list[list[Composition]] = [heads]
    for cls in (inv.CLASS_MODAL, inv.CLASS_SCALAR, inv.CLASS_TEMPORAL, inv.CLASS_CAUSAL, inv.CLASS_EPISTEMIC,
                inv.CLASS_ILLOCUTIONARY, inv.CLASS_VALENCE, inv.CLASS_RELATIONAL, inv.CLASS_DEICTIC,
                inv.CLASS_LOGICAL, inv.CLASS_AFFECT):
        head = "RELATION" if cls in (inv.CLASS_CAUSAL, inv.CLASS_RELATIONAL) else "ENTITY"
        rows.append([Composition(inv.pid(head), frozenset([p])) for p in inv.by_class(cls)])
    ncol = max(len(r) for r in rows)
    gap = int(st.cell * 0.25)
    extra = 1
    img = Image.new("RGB", (ncol * (st.cell + gap) + gap, (len(rows) + extra) * (st.cell + gap) + gap), C["bg"])
    d = ImageDraw.Draw(img)
    for r, row in enumerate(rows):
        for c, comp in enumerate(row):
            draw_char(d, comp, gap + c * (st.cell + gap), gap + r * (st.cell + gap), st)
    # literal row: numerals 0-9, a cartouche, a seal, a unit, a time
    y = gap + len(rows) * (st.cell + gap)
    x = gap
    for n in (0, 1, 2, 5, 9, 4200, -3.5):
        x += (draw_numeral(d, n, x, y, st)) * (st.cell + gap)
    draw_cartouche(d, "alice", x, y, st); x += st.cell + gap
    draw_cartouche(d, "checkout", x, y, st); x += st.cell + gap
    draw_seal(d, hashlib.sha256(b"x").digest(), x, y, st); x += st.cell + gap
    draw_unit(d, "ms", x, y, st)
    return img
