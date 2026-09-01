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

# Epistemic: how the head is stroked  (weight multiplier, dash pattern)
EPISTEMIC_STROKE = {
    "KNOWN": (1.7, None), "BELIEVED": (1.0, None), "INFERRED": (1.0, "dash"), "UNKNOWN": (1.0, "dot"),
    "CONTESTED": (1.0, "double"), "OBSERVED": (1.0, "eye"), "PREDICTED": (1.0, "ahead"),
}

BASE = 7.0            # head box side at scale 1, in grid units
CX = 8.6              # head centre x (room for the left radical and the right connector)
HEAD_CY = 8.0         # head centre y
ENC_MARGIN = 1.1      # clearance between head and enclosure
CROWN_Y = 1.9         # baseline of the crown zone (nothing else enters rows 0-2.6)
GROUND_Y = 13.9       # the ground line (rows 13.2-14.8 are its zone)
ROLE_Y = 15.3         # top of the role row (rows 15.2-17)
ROLE_COLS = {         # fixed columns for the roles that live below the head; (col, underline)
    0x03: (0, False), 0x0B: (0, True),    # ARG2 | SOURCE
    0x04: (1, False), 0x09: (1, True),    # SCOPE | MANNER
    0x05: (2, False), 0x0A: (2, True),    # MEASURE | PURPOSE
    0x06: (3, False),                     # CONDITION
    0x07: (4, False), 0x0C: (4, True),    # LOC | GOAL
    0x08: (5, False),                     # TIME
    0x01: (0, False), 0x02: (5, False),   # ARG0/ARG1 fall back here only when the head has no lobes
}
ROLE_COL_X = [2.3, 4.6, 6.9, 9.2, 11.5, 13.8]
SCALAR_SHAPE = {
    "NONE": (0.5, "hollow"), "SOME": (1.0, "half"), "ALL": (1.0, "full"),
    "LOW": (0.72, None), "MID": (1.0, None), "HIGH": (1.15, None), "EXTREME": (1.15, "double"),
    "BOUNDED": (1.0, "brackets"), "UNBOUNDED": (1.0, "open"), "INCREASE": (1.0, "rise"), "DECREASE": (1.0, "fall"),
}


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
        if (self.st.wedge if wedge is None else wedge) and L > 7.0 * w:
            bw, bl = 1.05 * w, 1.9 * w
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

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, ink=None, w: int | None = None) -> None:
        """Arc in degrees, screen orientation (0 = east, 90 = south)."""
        ink = ink or self.ink
        w = w or self.w
        X, Y = self.P(cx, cy)
        R = r * self.u
        self.d.arc([X - R, Y - R, X + R, Y + R], a0, a1, fill=ink, width=w)

    def circle(self, cx: float, cy: float, r: float, ink=None, w: int | None = None, fill: bool = False) -> None:
        ink = ink or self.ink
        X, Y = self.P(cx, cy)
        R = r * self.u
        if fill:
            self.d.ellipse([X - R, Y - R, X + R, Y + R], fill=ink)
        else:
            self.d.ellipse([X - R, Y - R, X + R, Y + R], outline=ink, width=w or self.w)

    def wave(self, x0: float, y: float, x1: float, amp: float = 0.5, n: int = 3, ink=None, w: int | None = None) -> None:
        """A sine-ish wiggle from x0 to x1 at height y."""
        ink = ink or self.ink
        w = w or self.w
        steps = n * 8
        pts = []
        for i in range(steps + 1):
            t = i / steps
            pts.append(self.P(x0 + (x1 - x0) * t, y + amp * math.sin(t * n * 2 * math.pi)))
        self.d.line(pts, fill=ink, width=w, joint="curve")

    def rounded_box(self, x0: float, y0: float, x1: float, y1: float, r: float, ink=None, w: int | None = None,
                    dash: str | None = None, open_top: bool = False, corners_only: bool = False) -> None:
        ink = ink or self.ink
        w = w or self.w
        # corner arcs
        self.arc(x0 + r, y0 + r, r, 180, 270, ink, w)
        self.arc(x1 - r, y0 + r, r, 270, 360, ink, w)
        self.arc(x1 - r, y1 - r, r, 0, 90, ink, w)
        self.arc(x0 + r, y1 - r, r, 90, 180, ink, w)
        if corners_only:
            return
        if not open_top:
            self.seg(x0 + r, y0, x1 - r, y0, ink, w, dash, wedge=False)
        self.seg(x1, y0 + r, x1, y1 - r, ink, w, dash, wedge=False)
        self.seg(x1 - r, y1, x0 + r, y1, ink, w, dash, wedge=False)
        self.seg(x0, y1 - r, x0, y0 + r, ink, w, dash, wedge=False)

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

    Zones are exclusive so strokes never collide:
        rows 0-2.6      crown (valence) and, at the far left, logical marks
        rows 3-13       head box, its enclosure (modal), left radical (illocution, x 0.4-2.4),
                        right connector (causal/relational, x 14.6-16.8), scalar tips at the enclosure corners
        rows 13.2-14.8  ground line (temporal)
        rows 15.2-17    role row (fixed columns) ; depth dots at the far left
    Inside the head: deixis mark (upper band), ARG0/ARG1 seeds (middle band), affect mark (lower band).
    """
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    thin = max(1, int(round(pen.w * 0.6)))
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
    ink = C["dim"] if continuation else C["ink"]

    # -- head geometry ---------------------------------------------------------------
    scale, fillmode = 1.0, None
    if pl.scalar:
        scale, fillmode = SCALAR_SHAPE[inv.name_of(pl.scalar[0])]
    side = BASE * scale
    hx0, hy0 = CX - side / 2, HEAD_CY - side / 2
    k = side / 6.0
    wmul, dash = 1.0, None
    for ep in pl.epistemic:
        w2, d2 = EPISTEMIC_STROKE[inv.name_of(ep)]
        wmul = max(wmul, w2)
        if d2 in ("dash", "dot") and dash not in ("dash", "dot"):
            dash = d2
        elif dash is None:
            dash = d2
    hw = max(1, int(round(pen.w * wmul)))
    polys, extra = HEADS[hname]
    ep_names = {inv.name_of(e) for e in pl.epistemic}

    # -- head ---------------------------------------------------------------------------
    d = dash if dash in ("dash", "dot") else None
    if fillmode == "full":
        for pg in polys:
            pen.poly(pg, hx0, hy0, k, ink, fill=True)
    else:
        for pg in polys:
            pen.poly(pg, hx0, hy0, k, ink, hw, d)
        pen.segs(extra, hx0, hy0, k, ink, hw, d)
        if fillmode == "half":
            for i in range(3):
                yy = hy0 + side * (0.6 + i * 0.13)
                pen.seg(hx0 + side * 0.2, yy, hx0 + side * 0.8, yy, ink, thin, wedge=False)
        if fillmode == "double" or "CONTESTED" in ep_names:
            # concentric inner outline (never an offset shadow: those collide)
            for pg in polys:
                cx_, cy_ = hx0 + side / 2, hy0 + side / 2
                inner = [(cx_ + (hx0 + px * k - cx_) * 0.62, cy_ + (hy0 + py * k - cy_) * 0.62) for px, py in pg]
                pen.poly(inner, 0, 0, 1, ink, thin)
        if fillmode == "hollow":
            pen.circle(CX, HEAD_CY, 0.35, ink, fill=True)
    if "OBSERVED" in ep_names:
        pen.circle(CX, HEAD_CY, 0.55, ink, thin)
        pen.circle(CX, HEAD_CY, 0.18, ink, fill=True)

    # -- negation ---------------------------------------------------------------------------
    if pl.negate and not continuation:
        pen.seg(hx0 - 0.5, hy0 + side + 0.5, hx0 + side + 0.5, hy0 - 0.5, ink, hw)

    # -- enclosure (modal) : a rounded box with clearance ---------------------------------------
    m = ENC_MARGIN
    ex0, ey0, ex1, ey1 = hx0 - m, hy0 - m, hx0 + side + m, hy0 + side + m
    if pl.modal:
        mname = inv.name_of(pl.modal[0])
        r = 1.0
        if mname == "NECESSARY":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
        elif mname == "POSSIBLE":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin, dash="dash")
        elif mname == "HYPOTHETICAL":
            pen.rounded_box(ex0, ey0, ex1, ey1, 1.6, ink, thin, corners_only=True)
        elif mname == "PERMITTED":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin, open_top=True)
        elif mname == "FORBIDDEN":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
            pen.seg(ex0 - 0.3, ey0, ex1 + 0.3, ey0, ink, hw, wedge=False)     # the lid
        elif mname == "DESIRED":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
            pen.circle(ex1 - 0.9, ey0 + 0.9, 0.3, ink, fill=True)
        elif mname == "AFFIRM":
            pen.arc(CX, ey1 - 0.2, (ex1 - ex0) / 2 - 0.4, 20, 160, ink, thin)     # a smile of assent under the head
    enc0, enc1 = (ex0, ex1)
    ency0, ency1 = (ey0, ey1)

    # -- scalar tips at the enclosure's right corners ------------------------------------------
    if fillmode == "brackets":
        for sx, dx in ((enc0 - 0.5, 0.8), (enc1 + 0.5, -0.8)):
            pen.seg(sx, ency0 + 0.5, sx, ency1 - 0.5, ink, hw, wedge=False)
            pen.seg(sx, ency0 + 0.5, sx + dx, ency0 + 0.5, ink, hw, wedge=False)
            pen.seg(sx, ency1 - 0.5, sx + dx, ency1 - 0.5, ink, hw, wedge=False)
    if fillmode == "open":
        pen.seg(enc0 - 1.6, HEAD_CY, enc0 - 0.2, HEAD_CY, ink, hw, wedge=False)
        pen.seg(enc1 + 0.2, HEAD_CY, enc1 + 1.6, HEAD_CY, ink, hw, wedge=False)
    if fillmode in ("rise", "fall"):
        tx, ty = enc1 + 0.4, (ency0 - 0.2 if fillmode == "rise" else ency1 + 0.2)
        dy = -1 if fillmode == "rise" else 1
        pen.seg(tx, ty - dy * 1.4, tx + 1.4, ty, ink, hw, wedge=False)
        pen.seg(tx + 1.4, ty, tx + 0.3, ty, ink, hw, wedge=False)
        pen.seg(tx + 1.4, ty, tx + 1.4, ty - dy * 1.1, ink, hw, wedge=False)

    # -- crown (valence), rows 0.4-2.6 ------------------------------------------------------------
    if pl.valence:
        v = inv.name_of(pl.valence[0])
        cx0, cx1 = enc0 + 0.6, enc1 - 0.6
        mid = (cx0 + cx1) / 2
        cy = CROWN_Y
        if v == "GOOD":
            pen.arc(mid, cy + 1.2, (cx1 - cx0) / 2, 200, 340, ink, hw)
        elif v == "BAD":
            pen.arc(mid, cy - 1.4, (cx1 - cx0) / 2, 20, 160, ink, hw)
        elif v == "REQUIRED":
            pen.seg(cx0, cy - 0.5, cx1, cy - 0.5, ink, hw, wedge=False); pen.seg(cx0, cy + 0.5, cx1, cy + 0.5, ink, hw, wedge=False)
        elif v == "OPTIONAL":
            pen.seg(cx0, cy, cx1, cy, ink, hw, "dash")
        elif v == "SAFE":
            pen.seg(cx0, cy - 0.4, cx1, cy - 0.4, ink, hw, wedge=False)
            pen.seg(cx0, cy - 0.4, cx0, cy + 0.7, ink, hw, wedge=False); pen.seg(cx1, cy - 0.4, cx1, cy + 0.7, ink, hw, wedge=False)
        elif v == "HARM":
            pen.wave(cx0, cy, cx1, 0.6, 3, ink, hw)
        elif v == "COST":
            pen.seg(cx0, cy, cx1, cy, ink, hw, wedge=False); pen.seg(cx0, cy - 0.7, cx0, cy + 0.7, ink, hw, wedge=False)
        elif v == "BENEFIT":
            pen.seg(cx0, cy, cx1, cy, ink, hw, wedge=False); pen.seg(cx1, cy - 0.7, cx1, cy + 0.7, ink, hw, wedge=False)
    for i, lg in enumerate(pl.logical[:2]):
        _logic_mark(pen, inv.name_of(lg), 0.6 + i * 2.2, CROWN_Y, ink, thin)

    # -- ground line (temporal), rows 13.2-14.8 ------------------------------------------------------
    if pl.temporal:
        gx0, gx1 = enc0 - 0.4, enc1 + 0.4
        gy = GROUND_Y
        names = [inv.name_of(t) for t in pl.temporal]
        line = not (names == ["PUNCTUAL"])
        if "DURATIVE" in names:
            pen.seg(gx0, gy - 0.35, gx1, gy - 0.35, ink, hw, wedge=False); pen.seg(gx0, gy + 0.35, gx1, gy + 0.35, ink, hw, wedge=False)
        elif "REPEAT" in names:
            pen.wave(gx0, gy, gx1, 0.5, 3, ink, hw)
        elif line:
            pen.seg(gx0, gy, gx1, gy, ink, hw, wedge=False)
        for tn in names:
            dot = {"PAST": 0.1, "NOW": 0.5, "FUTURE": 0.9, "BEFORE": 0.22, "AFTER": 0.78, "DURING": 0.5}.get(tn)
            if tn == "PUNCTUAL":
                pen.seg(CX, gy - 0.8, CX, gy + 0.8, ink, hw, wedge=False)
            elif tn == "BEGIN":
                pen.seg(gx0, gy - 0.8, gx0, gy + 0.8, ink, hw, wedge=False)
            elif tn == "END":
                pen.seg(gx1, gy - 0.8, gx1, gy + 0.8, ink, hw, wedge=False)
            if tn in ("BEFORE", "AFTER", "DURING"):
                for f in ((0.62,) if tn == "BEFORE" else (0.38,) if tn == "AFTER" else (0.15, 0.85)):
                    px = gx0 + (gx1 - gx0) * f
                    pen.seg(px, gy - 0.8, px, gy + 0.8, ink, hw, wedge=False)
            if dot is not None:
                pen.circle(gx0 + (gx1 - gx0) * dot, gy, 0.42, ink, fill=True)

    # -- left radical (illocution), x 0.4-2.4 ------------------------------------------------------
    if pl.illoc:
        iname = inv.name_of(pl.illoc[0])
        rx = 1.2
        ry0, ry1 = ency0 + 0.3, ency1 - 0.3
        pen.seg(rx, ry0, rx, ry1, ink, hw, "dash" if iname == "PROPOSE" else None, wedge=False)
        if iname == "REQUEST":
            pen.arc(rx + 0.9, ry1 - 0.9, 0.9, 0, 90, ink, hw)
        elif iname == "COMMIT":
            pen.seg(rx + 1.0, ry0, rx + 1.0, ry1, ink, hw, wedge=False)
        elif iname == "QUERY":
            pen.arc(rx + 0.9, ry0 + 0.9, 0.9, 180, 360, ink, hw)
            pen.seg(rx + 1.8, ry0 + 0.9, rx + 1.8, ry0 + 1.9, ink, hw, wedge=False)
        elif iname == "WARN":
            pen.seg(rx - 0.8, (ry0 + ry1) / 2, rx + 0.8, (ry0 + ry1) / 2, ink, hw, wedge=False)
        elif iname == "REFUSE":
            pen.seg(rx - 0.9, (ry0 + ry1) / 2 + 1, rx + 0.9, (ry0 + ry1) / 2 - 1, ink, hw, wedge=False)
        elif iname == "ACKNOWLEDGE":
            pen.seg(rx - 0.6, ry1 - 0.9, rx, ry1, ink, hw, wedge=False); pen.seg(rx, ry1, rx + 1.0, ry1 - 1.6, ink, hw, wedge=False)
        elif iname == "ASSERT":
            pen.circle(rx, ry0 - 0.1, 0.3, ink, fill=True)

    # -- connector (causal / relational), x 14.6-16.8 ----------------------------------------------
    conn = (pl.causal + pl.relational)[:1]
    if conn:
        cn = inv.name_of(conn[0])
        cy = HEAD_CY
        ax0, ax1 = max(enc1 + 0.4, 14.4), 16.6
        _connector(pen, cn, ax0, ax1, cy, ink, hw, thin)

    # -- inner marks --------------------------------------------------------------------------------------
    inner_ok = scale >= 0.9 and fillmode not in ("full", "half") and not continuation
    if pl.deictic and inner_ok:
        _deictic_mark(pen, inv.name_of(pl.deictic[0]), CX, hy0 + side * 0.2, ink, thin)
    if pl.affect and inner_ok:
        _affect_mark(pen, inv.name_of(pl.affect[0]), CX, hy0 + side * 0.8, ink, thin)

    # -- roles: lobes inside, fixed columns below -----------------------------------------------------
    lob = LOBES.get(hname) if inner_ok else None
    for code, node in roles:
        if lob is not None and code in (1, 2):
            lx, ly = lob[0 if code == 1 else 1]
            sx, sy = hx0 + lx * k, hy0 + ly * k
            _draw_seed(pen, node, sx, sy, max(0.7, k * 0.85), ink)
            if isinstance(node, Composition):
                pen.seg(sx, sy + 2.3 * k * 0.85, sx + 1.7, sy + 2.3 * k * 0.85, ink, thin, wedge=False)
            continue
        col, underline = ROLE_COLS.get(code, (3, False))
        sx = ROLE_COL_X[col] - 0.9
        _draw_seed(pen, node, sx, ROLE_Y, 0.9, ink)
        if underline:
            pen.seg(sx, ROLE_Y + 2.15, sx + 1.8, ROLE_Y + 2.15, ink, thin, wedge=False)
        if isinstance(node, Composition):
            pen.seg(sx, ROLE_Y - 0.45, sx + 1.8, ROLE_Y - 0.45, ink, thin, wedge=False)

    if continuation:
        return
    if any(isinstance(m, Composition) for m in comp.modifiers):
        pen.seg(enc0, ency1 + 0.3, enc1, ency1 + 0.3, C["dim"], thin, wedge=False)
    if comp.residue is not None:
        pen.wave(0.5, GRID - 1.0, 2.6, 0.35, 2, C["dim"], thin)
    for i in range(depth):
        pen.circle(0.8 + i * 0.9, GRID - 0.8, 0.22, ink, fill=True)


def _connector(pen: _Pen, cn: str, ax0: float, ax1: float, cy: float, ink, hw: int, thin: int) -> None:
    def arrow(x0, x1, yy, back=False):
        pen.seg(x0, yy, x1, yy, ink, hw, wedge=False)
        tip, dirn = (x0, 1) if back else (x1, -1)
        pen.seg(tip, yy, tip + dirn * 0.9, yy - 0.9, ink, hw, wedge=False); pen.seg(tip, yy, tip + dirn * 0.9, yy + 0.9, ink, hw, wedge=False)
    mid = (ax0 + ax1) / 2
    if cn == "CAUSE":
        arrow(ax0, ax1, cy)
    elif cn == "ENABLE":
        pen.seg(ax0, cy, ax1 - 1.0, cy, ink, hw, "dash"); arrow(ax1 - 1.0, ax1, cy)
    elif cn == "PREVENT":
        arrow(ax0, ax1, cy); pen.seg(mid, cy - 1.1, mid, cy + 1.1, ink, hw, wedge=False)
    elif cn == "CORRELATE":
        pen.seg(ax0 + 0.3, cy, ax1 - 0.3, cy, ink, hw, wedge=False)
        for t, dirn in ((ax0 + 0.3, 1), (ax1 - 0.3, -1)):
            pen.seg(t, cy, t + dirn * 0.8, cy - 0.8, ink, hw, wedge=False); pen.seg(t, cy, t + dirn * 0.8, cy + 0.8, ink, hw, wedge=False)
    elif cn == "DEPEND":
        arrow(ax0, ax1, cy, back=True)
    elif cn == "TRIGGER":
        pen.seg(ax0, cy - 1.1, ax0, cy + 1.1, ink, hw, wedge=False); arrow(ax0, ax1, cy)
    elif cn == "EQUAL":
        pen.seg(ax0, cy - 0.5, ax1, cy - 0.5, ink, hw, wedge=False); pen.seg(ax0, cy + 0.5, ax1, cy + 0.5, ink, hw, wedge=False)
    elif cn == "GREATER":
        pen.seg(ax0, cy - 1.0, ax1, cy, ink, hw, wedge=False); pen.seg(ax1, cy, ax0, cy + 1.0, ink, hw, wedge=False)
    elif cn == "LESS":
        pen.seg(ax1, cy - 1.0, ax0, cy, ink, hw, wedge=False); pen.seg(ax0, cy, ax1, cy + 1.0, ink, hw, wedge=False)
    elif cn == "PART":
        pen.arc(ax1, cy, 1.0, 90, 270, ink, hw)
    elif cn == "HAS":
        pen.arc(ax0, cy, 1.0, 270, 450, ink, hw)
    elif cn == "MEMBER":
        pen.arc(ax1, cy, 1.0, 90, 270, ink, hw); pen.seg(ax1 - 1.0, cy, ax1, cy, ink, hw, wedge=False)
    elif cn == "NEAR":
        pen.circle(mid - 0.6, cy, 0.35, ink, fill=True); pen.circle(mid + 0.6, cy, 0.35, ink, fill=True)
    elif cn == "INSIDE":
        pen.circle(mid, cy, 1.0, ink, thin); pen.circle(mid, cy, 0.3, ink, fill=True)
    elif cn == "OUTSIDE":
        pen.circle(mid - 0.3, cy, 0.9, ink, thin); pen.circle(ax1 - 0.1, cy - 0.9, 0.3, ink, fill=True)
    elif cn == "ABOVE":
        pen.seg(ax0, cy + 0.6, ax1, cy + 0.6, ink, hw, wedge=False); pen.circle(mid, cy - 0.5, 0.35, ink, fill=True)
    elif cn == "BELOW":
        pen.seg(ax0, cy - 0.6, ax1, cy - 0.6, ink, hw, wedge=False); pen.circle(mid, cy + 0.5, 0.35, ink, fill=True)
    elif cn == "TOWARD":
        pen.circle(ax0 + 0.3, cy, 0.35, ink, fill=True); arrow(ax0 + 0.8, ax1, cy)


def _deictic_mark(pen: _Pen, name: str, cx: float, cy: float, ink, thin: int) -> None:
    r = 0.55
    if name == "SELF":
        pen.circle(cx, cy, r, ink, thin); pen.circle(cx, cy, 0.2, ink, fill=True)
    elif name == "ADDRESSEE":
        pen.circle(cx - 0.4, cy, r, ink, thin); pen.seg(cx + 0.3, cy, cx + 1.3, cy, ink, thin, wedge=False)
    elif name == "THIS":
        pen.circle(cx - 0.6, cy, 0.25, ink, fill=True); pen.seg(cx - 0.1, cy, cx + 0.9, cy, ink, thin, wedge=False)
    elif name == "THAT":
        pen.seg(cx - 0.9, cy, cx + 0.2, cy, ink, thin, wedge=False); pen.circle(cx + 0.7, cy, 0.25, ink, fill=True)
    elif name == "WHICH":
        pen.arc(cx, cy - 0.1, 0.5, 200, 90, ink, thin); pen.circle(cx, cy + 0.9, 0.18, ink, fill=True)
    elif name == "SAME":
        pen.seg(cx - 0.8, cy - 0.3, cx + 0.8, cy - 0.3, ink, thin, wedge=False); pen.seg(cx - 0.8, cy + 0.3, cx + 0.8, cy + 0.3, ink, thin, wedge=False)
    elif name == "OTHER":
        pen.circle(cx - 0.6, cy, 0.25, ink, fill=True); pen.circle(cx + 0.6, cy, 0.4, ink, thin)
    elif name == "EACH":
        for dx in (-0.8, 0, 0.8):
            pen.circle(cx + dx, cy, 0.22, ink, fill=True)
    elif name == "ANY":
        pen.circle(cx - 0.6, cy, 0.3, ink, thin); pen.circle(cx + 0.6, cy, 0.3, ink, thin)
    elif name == "GENERIC":
        pen.arc(cx, cy, 0.7, 0, 360, ink, thin); pen.seg(cx - 0.4, cy, cx + 0.4, cy, ink, thin, wedge=False)


def _affect_mark(pen: _Pen, name: str, cx: float, cy: float, ink, thin: int) -> None:
    if name == "JOY":
        pen.arc(cx, cy - 0.5, 0.9, 20, 160, ink, thin)
    elif name == "SADNESS":
        pen.arc(cx, cy + 0.6, 0.9, 200, 340, ink, thin)
    elif name == "FEAR":
        pen.wave(cx - 1.0, cy, cx + 1.0, 0.3, 2, ink, thin)
    elif name == "ANGER":
        pen.seg(cx - 1.0, cy + 0.4, cx - 0.5, cy - 0.4, ink, thin, wedge=False); pen.seg(cx - 0.5, cy - 0.4, cx, cy + 0.4, ink, thin, wedge=False)
        pen.seg(cx, cy + 0.4, cx + 0.5, cy - 0.4, ink, thin, wedge=False); pen.seg(cx + 0.5, cy - 0.4, cx + 1.0, cy + 0.4, ink, thin, wedge=False)
    elif name == "TRUST":
        pen.seg(cx - 0.9, cy, cx + 0.9, cy, ink, thin, wedge=False); pen.circle(cx, cy - 0.6, 0.2, ink, fill=True)
    elif name == "SURPRISE":
        pen.circle(cx, cy, 0.5, ink, thin)
    elif name == "DISGUST":
        pen.wave(cx - 1.0, cy + 0.2, cx + 1.0, 0.3, 1, ink, thin); pen.seg(cx - 1.0, cy - 0.5, cx + 1.0, cy - 0.5, ink, thin, wedge=False)
    elif name == "CALM":
        pen.arc(cx, cy + 3.0, 3.4, 250, 290, ink, thin)


def _logic_mark(pen: _Pen, name: str, x: float, y: float, ink, thin: int) -> None:
    if name == "AND":
        pen.seg(x, y + 0.8, x + 0.6, y - 0.8, ink, thin, wedge=False); pen.seg(x + 0.6, y - 0.8, x + 1.2, y + 0.8, ink, thin, wedge=False)
        pen.seg(x + 0.25, y + 0.2, x + 0.95, y + 0.2, ink, thin, wedge=False)
    elif name == "OR":
        pen.seg(x, y - 0.8, x + 0.6, y + 0.8, ink, thin, wedge=False); pen.seg(x + 0.6, y + 0.8, x + 1.2, y - 0.8, ink, thin, wedge=False)
    elif name == "XOR":
        pen.seg(x, y - 0.8, x + 0.6, y + 0.8, ink, thin, wedge=False); pen.seg(x + 0.6, y + 0.8, x + 1.2, y - 0.8, ink, thin, wedge=False)
        pen.seg(x, y - 1.1, x + 1.2, y - 1.1, ink, thin, wedge=False)
    elif name == "IFF":
        pen.seg(x, y - 0.3, x + 1.4, y - 0.3, ink, thin, wedge=False); pen.seg(x, y + 0.3, x + 1.4, y + 0.3, ink, thin, wedge=False)
        pen.seg(x, y - 0.3, x - 0.3, y, ink, thin, wedge=False); pen.seg(x + 1.4, y + 0.3, x + 1.7, y, ink, thin, wedge=False)
    elif name == "IMPLIES":
        pen.seg(x, y - 0.3, x + 1.2, y - 0.3, ink, thin, wedge=False); pen.seg(x, y + 0.3, x + 1.2, y + 0.3, ink, thin, wedge=False)
        pen.seg(x + 1.2, y - 0.6, x + 1.7, y, ink, thin, wedge=False); pen.seg(x + 1.2, y + 0.6, x + 1.7, y, ink, thin, wedge=False)
    elif name == "ONLY":
        pen.circle(x + 0.6, y, 0.25, ink, fill=True); pen.seg(x, y - 0.8, x, y + 0.8, ink, thin, wedge=False); pen.seg(x + 1.2, y - 0.8, x + 1.2, y + 0.8, ink, thin, wedge=False)
    elif name == "EXCEPT":
        pen.circle(x + 0.6, y, 0.7, ink, thin); pen.seg(x + 0.9, y - 0.3, x + 1.6, y - 1.0, ink, thin, wedge=False)


def _below_roles(comp: Composition, roles: list, hname: str, scale: float) -> bool:
    lob = LOBES.get(hname) if scale >= 0.9 else None
    return any(not (lob is not None and code in (1, 2)) for code, _ in roles)


def word_chars(comp: Composition) -> list[tuple[Composition, int, list | None, list | None]]:
    """(comp, depth, overflow-mods|None, extra-roles|None) per character of the word."""
    out: list = []

    def visit(c: Composition, depth: int) -> None:
        out.append((c, depth, None, None))
        pl = _plan(c)
        if pl.overflow:
            out.append((c, depth, pl.overflow, []))
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
