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

# Head radicals as stroke programs on a 6×6 local grid.  Each op:
#   ("poly", pts, fill)   closed outline (filled if fill)     ("seg", x0,y0,x1,y1)
#   ("circle", cx,cy,r,fill)   ("arc", cx,cy,r,a0,a1)   ("pie", cx,cy,r,a0,a1)  filled sector
# Ops after the "LOD" marker are inner detail, drawn only when the head is large enough.
LOD = ("lod",)
HEADS: dict[str, list[tuple]] = {
    # a thing that persists: the square, doubled at the corners like a stamped block
    "ENTITY":   [("poly", [(0.4, 0.4), (5.6, 0.4), (5.6, 5.6), (0.4, 5.6)], False),
                 LOD, ("poly", [(1.5, 1.5), (4.5, 1.5), (4.5, 4.5), (1.5, 4.5)], False)],
    # something that unfolds: a bold chevron band pointing forward
    "PROCESS":  [("curve", 0.5, 0.3, 4.6, 1.0, 5.8, 3.0, "na"), ("curve", 5.8, 3.0, 4.6, 5.0, 0.5, 5.7, "pie"),
                 ("curve", 0.5, 1.4, 2.6, 2.0, 3.6, 3.0, "na"), ("curve", 3.6, 3.0, 2.6, 4.0, 0.5, 4.6, "pie"),
                 LOD, ("seg", 0.5, 3.0, 1.6, 3.0)],
    # an attribute borne: the lozenge with its centre
    "PROPERTY": [("poly", [(3.0, 0.2), (5.8, 3.0), (3.0, 5.8), (0.2, 3.0)], False),
                 LOD, ("circle", 3.0, 3.0, 0.55, True)],
    # a tie between things: the hourglass with a knot
    "RELATION": [("poly", [(0.4, 0.4), (5.6, 0.4), (0.4, 5.6), (5.6, 5.6)], False),
                 LOD, ("circle", 3.0, 3.0, 0.6, True)],
    # a magnitude: a staircase silhouette, rising
    "QUANTITY": [("poly", [(0.3, 5.7), (0.3, 3.9), (2.1, 3.9), (2.1, 2.1), (3.9, 2.1), (3.9, 0.3), (5.7, 0.3), (5.7, 5.7)], False),
                 LOD, ("seg", 2.1, 5.7, 2.1, 3.9), ("seg", 3.9, 5.7, 3.9, 2.1)],
    # an actor: the house with a figure inside
    "AGENT":    [("curve", 3.0, 0.2, 1.2, 1.0, 0.4, 2.6, "pie"), ("curve", 3.0, 0.2, 4.8, 1.0, 5.6, 2.6, "na"),
                 ("seg", 0.4, 2.6, 0.4, 5.7), ("seg", 5.6, 2.6, 5.6, 5.7), ("seg", 0.4, 5.7, 5.6, 5.7),
                 LOD, ("circle", 3.0, 3.0, 0.55, True), ("seg", 3.0, 3.7, 3.0, 5.0)],
    # a condition holding: the ring (octagon) with a level line
    "STATE":    [("poly", [(1.9, 0.3), (4.1, 0.3), (5.7, 1.9), (5.7, 4.1), (4.1, 5.7), (1.9, 5.7), (0.3, 4.1), (0.3, 1.9)], False),
                 LOD, ("seg", 1.5, 3.0, 4.5, 3.0)],
    # a location: the pin — a round head over a point
    "PLACE":    [("circle", 3.0, 2.3, 2.1, False), ("poly", [(1.55, 3.7), (4.45, 3.7), (3.0, 5.9)], True),
                 LOD, ("circle", 3.0, 2.3, 0.6, True)],
    # a time: the dial with a swept sector
    "MOMENT":   [("circle", 3.0, 3.0, 2.8, False), ("pie", 3.0, 3.0, 2.0, 270, 360),
                 LOD, ("seg", 3.0, 3.0, 3.0, 0.6)],
    # information: the pennant on its staff
    "SIGN":     [("seg", 0.9, 0.3, 0.9, 5.8), ("poly", [(0.9, 0.5), (5.7, 1.9), (0.9, 3.3)], True),
                 ("curve", 0.9, 3.3, 3.2, 3.6, 5.7, 1.9, "na")],
    # a bounded occurrence: the spark (four-point star)
    "EVENT":    [("curve", 3.0, 0.1, 3.3, 2.7, 5.9, 3.0, "na"), ("curve", 5.9, 3.0, 3.3, 3.3, 3.0, 5.9, "pie"),
                 ("curve", 3.0, 5.9, 2.7, 3.3, 0.1, 3.0, "na"), ("curve", 0.1, 3.0, 2.7, 2.7, 3.0, 0.1, "pie"),
                 LOD, ("circle", 3.0, 3.0, 0.5, True)],
    # a collection: three members, one body
    "GROUP":    [("circle", 1.6, 1.8, 1.25, True), ("circle", 4.4, 1.8, 1.25, True), ("circle", 3.0, 4.3, 1.25, True),
                 LOD, ("seg", 1.6, 1.8, 4.4, 1.8), ("seg", 1.6, 1.8, 3.0, 4.3), ("seg", 4.4, 1.8, 3.0, 4.3)],
}
HEAD_POLYS: dict[str, list[Poly]] = {n: [op[1] for op in ops if op[0] == "poly"] for n, ops in HEADS.items()}
HEAD_POLYS["PROCESS"] = [[(0.5, 0.3), (5.8, 3.0), (0.5, 5.7), (3.6, 3.0)]]
HEAD_POLYS["AGENT"] = [[(0.4, 2.6), (3.0, 0.2), (5.6, 2.6), (5.6, 5.7), (0.4, 5.7)]]
HEAD_POLYS["EVENT"] = [[(3.0, 0.1), (3.6, 2.4), (5.9, 3.0), (3.6, 3.6), (3.0, 5.9), (2.4, 3.6), (0.1, 3.0), (2.4, 2.4)]]
# heads with interior room for argument seeds (left lobe / right lobe in local coords)
LOBES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "ENTITY": ((0.9, 2.1), (3.3, 2.1)), "PROPERTY": ((1.6, 2.1), (2.8, 2.1)), "RELATION": ((0.7, 2.1), (3.9, 2.1)),
    "AGENT": ((0.8, 3.2), (3.8, 3.2)), "STATE": ((0.9, 2.1), (3.3, 2.1)), "MOMENT": ((0.6, 3.3), (3.6, 3.3)),
    "EVENT": ((1.6, 2.1), (2.8, 2.1)),
}

SEEDS: dict[str, list[tuple]] = {   # 2×2 local; same op forms as HEADS
    "ENTITY":   [("poly", [(0.15, 0.15), (1.85, 0.15), (1.85, 1.85), (0.15, 1.85)], False)],
    "PROCESS":  [("poly", [(0.1, 0.1), (0.9, 0.1), (1.9, 1.0), (0.9, 1.9), (0.1, 1.9), (1.0, 1.0)], False)],
    "PROPERTY": [("poly", [(1.0, 0.05), (1.95, 1.0), (1.0, 1.95), (0.05, 1.0)], False)],
    "RELATION": [("poly", [(0.1, 0.1), (1.9, 0.1), (0.1, 1.9), (1.9, 1.9)], False)],
    "QUANTITY": [("poly", [(0.1, 1.9), (0.1, 1.3), (0.7, 1.3), (0.7, 0.7), (1.3, 0.7), (1.3, 0.1), (1.9, 0.1), (1.9, 1.9)], False)],
    "AGENT":    [("poly", [(0.1, 0.9), (1.0, 0.05), (1.9, 0.9), (1.9, 1.9), (0.1, 1.9)], False)],
    "STATE":    [("circle", 1.0, 1.0, 0.9, False)],
    "PLACE":    [("circle", 1.0, 0.75, 0.65, False), ("poly", [(0.55, 1.2), (1.45, 1.2), (1.0, 1.95)], True)],
    "MOMENT":   [("circle", 1.0, 1.0, 0.9, False), ("pie", 1.0, 1.0, 0.65, 270, 360)],
    "SIGN":     [("seg", 0.3, 0.05, 0.3, 1.95), ("poly", [(0.3, 0.15), (1.9, 0.65), (0.3, 1.15)], True)],
    "EVENT":    [("poly", [(1.0, 0.0), (1.3, 0.7), (2.0, 1.0), (1.3, 1.3), (1.0, 2.0), (0.7, 1.3), (0.0, 1.0), (0.7, 0.7)], False)],
    "GROUP":    [("circle", 0.55, 0.6, 0.42, True), ("circle", 1.45, 0.6, 0.42, True), ("circle", 1.0, 1.45, 0.42, True)],
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

BASE = 7.2            # head box side at scale 1, in grid units
CX = 8.6              # head centre x (room for the left radical and the right connector)
HEAD_CY = 8.4         # head centre y
ENC_MARGIN = 1.0      # clearance between head and enclosure
HEADLINE_Y = 0.55     # the word's headline
CROWN_Y = 2.4         # baseline of the crown zone (rows 1.2-3.2)
GROUND_Y = 14.0       # the ground line (rows 13.3-14.7 are its zone)
ROLE_Y = 15.2         # top of the role row (rows 15.1-17)
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
    frame: bool | str = "faint"    # em-box: False, True (dim outline) or "faint"
    headline: bool = True          # a line along the top joining the characters of a word (Devanagari style)
    color: bool = True             # modifier classes in their colours; the head in ink
    supersample: int = 3           # render at N× and downsample: soft, blended edges
    blend: float = 0.86            # ink opacity per stroke; crossings darken like wet ink
    pressure: bool = True          # brush pressure profiles and a slight bow on long strokes
    grid: bool = False             # faint grid (design aid)


THEMES = {
    "dark": {"bg": (14, 14, 16), "ink": (240, 240, 234), "dim": (92, 92, 96), "faint": (44, 44, 48), "clay": (206, 168, 112),
             "modal": (170, 140, 255), "scalar": (255, 176, 64), "temporal": (72, 200, 220), "causal": (255, 96, 96),
             "epistemic": (120, 220, 130), "illoc": (240, 120, 210), "valence": (240, 210, 70), "relational": (255, 140, 110),
             "deictic": (110, 170, 255), "logical": (160, 190, 220), "affect": (255, 130, 160), "literal": (206, 168, 112)},
    "light": {"bg": (255, 255, 255), "ink": (22, 22, 24), "dim": (170, 170, 166), "faint": (226, 226, 222), "clay": (140, 100, 50),
              "modal": (98, 60, 200), "scalar": (196, 110, 0), "temporal": (0, 130, 150), "causal": (200, 40, 40),
              "epistemic": (30, 140, 60), "illoc": (170, 40, 150), "valence": (170, 130, 0), "relational": (200, 80, 40),
              "deictic": (30, 90, 200), "logical": (80, 110, 150), "affect": (200, 60, 110), "literal": (140, 100, 50)},
}


# ---------------------------------------------------------------------------
# Pen
# ---------------------------------------------------------------------------

class _Pen:
    """The stroke set, drawn like a brush.

        heng  horizontal   light entry, thin belly, heavy rounded exit
        shu   vertical     heavy pressed entry, steady body, slight lift at the end
        pie   falling-left full pressure at entry tapering to a point
        na    falling-right light entry swelling to a broad foot, then a quick lift
        dian  dot          a pressed teardrop;  hu arc;  wan wave

    Horizontals are lighter than verticals; weight never drops below 1/17 em.
    Strokes are composited at partial opacity so crossings darken the way wet
    ink does, and long strokes bow slightly as a brush arm gives.
    """

    def __init__(self, draw: ImageDraw.ImageDraw, ox: float, oy: float, unit: float, ink, st: CharStyle) -> None:
        self.d, self.ox, self.oy, self.u, self.ink, self.st = draw, ox, oy, unit, ink, st
        self.w = max(1.5, st.weight * unit, st.cell / 17)
        img = getattr(draw, "_image", None)
        self.img = img if (img is not None and getattr(img, "mode", "") == "RGBA" and st.blend < 1.0) else None

    def P(self, x: float, y: float) -> tuple[float, float]:
        return self.ox + x * self.u, self.oy + y * self.u

    # -- compositing ---------------------------------------------------------
    def _fill(self, pts: list[tuple[float, float]], ink) -> None:
        if self.img is None or len(pts) < 3:
            self.d.polygon(pts, fill=ink)
            return
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0, y0 = int(math.floor(min(xs))) - 1, int(math.floor(min(ys))) - 1
        x1, y1 = int(math.ceil(max(xs))) + 1, int(math.ceil(max(ys))) + 1
        W, H = self.img.size
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
        if x1 <= x0 or y1 <= y0:
            return
        layer = Image.new("RGBA", (x1 - x0, y1 - y0), (0, 0, 0, 0))
        a = int(255 * self.st.blend)
        col = (ink[0], ink[1], ink[2], a) if isinstance(ink, tuple) else ink
        ImageDraw.Draw(layer).polygon([(x - x0, y - y0) for x, y in pts], fill=col)
        self.img.alpha_composite(layer, (x0, y0))

    def _disc(self, X: float, Y: float, r: float, ink) -> None:
        n = 20
        self._fill([(X + r * math.cos(2 * math.pi * i / n), Y + r * math.sin(2 * math.pi * i / n)) for i in range(n)], ink)

    def _band(self, pts: list[tuple[float, float]], half: list[float], ink) -> None:
        if len(pts) < 2:
            return
        left, right = [], []
        for i, (x, y) in enumerate(pts):
            if i == 0:
                dx, dy = pts[1][0] - x, pts[1][1] - y
            elif i == len(pts) - 1:
                dx, dy = x - pts[i - 1][0], y - pts[i - 1][1]
            else:
                dx, dy = pts[i + 1][0] - pts[i - 1][0], pts[i + 1][1] - pts[i - 1][1]
            L = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / L * half[i], dx / L * half[i]
            left.append((x + nx, y + ny))
            right.append((x - nx, y - ny))
        self._fill(left + right[::-1], ink)

    # -- pressure profiles: half-width as a fraction of w along t in 0..1 ---------
    @staticmethod
    def _profile(kind: str, t: float) -> float:
        if kind == "heng":
            entry = 0.30 + 0.12 * math.sin(min(1.0, t / 0.18) * math.pi / 2)
            belly = 0.36 + 0.06 * math.cos(math.pi * t)
            exit_ = 0.20 * max(0.0, (t - 0.72) / 0.28) ** 1.5
            return min(entry, belly) + exit_
        if kind == "shu":
            return 0.55 - 0.08 * t + 0.10 * max(0.0, 1 - t / 0.12)
        if kind == "pie":
            return 0.08 + 0.50 * (1 - t) ** 1.5
        if kind == "na":
            if t < 0.86:
                return 0.22 + 0.42 * t ** 1.7
            return 0.22 + 0.42 * 0.86 ** 1.7 - 0.35 * ((t - 0.86) / 0.14) ** 2
        return 0.5

    def stroke(self, x0, y0, x1, y1, ink=None, w: float | None = None, kind: str | None = None,
               dash: str | None = None) -> None:
        ink = ink or self.ink
        w = float(w or self.w)
        if dash:
            self._dashed(x0, y0, x1, y1, ink, w, dash)
            return
        X0, Y0 = self.P(x0, y0)
        X1, Y1 = self.P(x1, y1)
        dx, dy = X1 - X0, Y1 - Y0
        L = math.hypot(dx, dy)
        if L < 0.5:
            self._disc(X0, Y0, w / 2, ink)
            return
        if kind is None:
            ang = abs(math.degrees(math.atan2(dy, dx)))
            if ang < 20 or ang > 160:
                kind = "heng"
            elif 70 < ang < 110:
                kind = "shu"
            elif (dx > 0) == (dy > 0):
                kind = "na"
            else:
                kind = "pie"
        n = 16
        ts = [i / n for i in range(n + 1)]
        bow = 0.0
        if self.st.pressure and L > 5 * w and kind in ("heng", "shu"):
            bow = 0.018 * L * (1 if kind == "heng" else -1)
        nx, ny = -dy / L, dx / L
        pts = [(X0 + dx * t + nx * bow * math.sin(math.pi * t), Y0 + dy * t + ny * bow * math.sin(math.pi * t)) for t in ts]
        half = [w * (self._profile(kind, t) if self.st.pressure else 0.5) for t in ts]
        self._band(pts, half, ink)
        if kind == "heng":
            self._disc(X1, Y1, w * 0.60, ink); self._disc(X0, Y0, w * 0.34, ink)
        elif kind == "shu":
            self._disc(X0, Y0, w * 0.62, ink); self._disc(X1, Y1, w * 0.46, ink)
        elif kind == "pie":
            self._disc(X0, Y0, w * 0.56, ink)
        elif kind == "na":
            self._disc(X0, Y0, w * 0.26, ink)
        else:
            self._disc(X0, Y0, w * 0.5, ink); self._disc(X1, Y1, w * 0.5, ink)

    def curve(self, x0, y0, cx, cy, x1, y1, ink=None, w: float | None = None, kind: str = "pie") -> None:
        """A bent stroke (quadratic Bézier) with the same pressure profile as a straight one."""
        ink = ink or self.ink
        w = float(w or self.w)
        n = 18
        pts, half = [], []
        for i in range(n + 1):
            t = i / n
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1
            pts.append(self.P(bx, by))
            half.append(w * (self._profile(kind, t) if self.st.pressure else 0.5))
        self._band(pts, half, ink)
        if kind in ("pie", "shu"):
            self._disc(pts[0][0], pts[0][1], w * 0.55, ink)
        if kind == "heng":
            self._disc(pts[-1][0], pts[-1][1], w * 0.6, ink)

    def seg(self, x0, y0, x1, y1, ink=None, w=None, dash=None, wedge=None) -> None:
        self.stroke(x0, y0, x1, y1, ink, w, None, dash)

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
            X0, Y0 = self.P(x0 + ux * a, y0 + uy * a)
            X1, Y1 = self.P(x0 + ux * (a + seg_on), y0 + uy * (a + seg_on))
            if dash == "dot":
                self._disc((X0 + X1) / 2, (Y0 + Y1) / 2, w * 0.42, ink)
            else:
                self._band([(X0, Y0), (X1, Y1)], [w * 0.42, w * 0.42], ink)

    def dot(self, cx: float, cy: float, r: float = 0.45, ink=None) -> None:
        ink = ink or self.ink
        X, Y = self.P(cx, cy)
        R = max(1.5, r * self.u)
        self._disc(X, Y, R, ink)
        self._fill([(X - R * 0.7, Y - R * 0.7), (X + R * 0.95, Y + R * 0.15), (X + R * 0.15, Y + R * 0.95)], ink)

    def arc(self, cx: float, cy: float, r: float, a0: float, a1: float, ink=None, w: float | None = None) -> None:
        ink = ink or self.ink
        w = float(w or self.w * 0.85)
        sweep = (a1 - a0) % 360 or 360
        n = max(8, int(sweep / 8))
        pts, half = [], []
        for i in range(n + 1):
            t = i / n
            a = math.radians(a0 + sweep * t)
            pts.append(self.P(cx + r * math.cos(a), cy + r * math.sin(a)))
            half.append(w * (0.32 + 0.22 * math.sin(math.pi * t)) if self.st.pressure else w * 0.5)
        self._band(pts, half, ink)

    def circle(self, cx: float, cy: float, r: float, ink=None, w: float | None = None, fill: bool = False) -> None:
        ink = ink or self.ink
        X, Y = self.P(cx, cy)
        if fill:
            self._disc(X, Y, r * self.u, ink)
        else:
            self.arc(cx, cy, r, -60, 300, ink, w or self.w * 0.9)

    def pie(self, cx: float, cy: float, r: float, a0: float, a1: float, ink=None) -> None:
        ink = ink or self.ink
        X, Y = self.P(cx, cy)
        R = r * self.u
        n = max(6, int(((a1 - a0) % 360) / 6))
        pts = [(X, Y)] + [(X + R * math.cos(math.radians(a0 + (a1 - a0) * i / n)), Y + R * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]
        self._fill(pts, ink)

    def wave(self, x0: float, y: float, x1: float, amp: float = 0.5, n: int = 3, ink=None, w: float | None = None) -> None:
        ink = ink or self.ink
        w = float(w or self.w * 0.8)
        steps = n * 10
        tt = [i / steps for i in range(steps + 1)]
        pts = [self.P(x0 + (x1 - x0) * t, y + amp * math.sin(t * n * 2 * math.pi)) for t in tt]
        half = [w * (0.28 + 0.18 * abs(math.cos(t * n * 2 * math.pi))) for t in tt]
        self._band(pts, half, ink)

    def rounded_box(self, x0: float, y0: float, x1: float, y1: float, r: float, ink=None, w: float | None = None,
                    dash: str | None = None, open_top: bool = False, corners_only: bool = False) -> None:
        ink = ink or self.ink
        w = w or self.w * 0.7
        self.arc(x0 + r, y0 + r, r, 180, 270, ink, w)
        self.arc(x1 - r, y0 + r, r, 270, 360, ink, w)
        self.arc(x1 - r, y1 - r, r, 0, 90, ink, w)
        self.arc(x0 + r, y1 - r, r, 90, 180, ink, w)
        if corners_only:
            return
        def line(a, b, c, d):
            if dash:
                self._dashed(a, b, c, d, ink, w, dash)
            else:
                A, B = self.P(a, b); Cc, D = self.P(c, d)
                self._band([(A, B), (Cc, D)], [w * 0.42, w * 0.42], ink)
        if not open_top:
            line(x0 + r, y0, x1 - r, y0)
        line(x1, y0 + r, x1, y1 - r)
        line(x1 - r, y1, x0 + r, y1)
        line(x0, y1 - r, x0, y0 + r)

    def segs(self, segs: list[Seg], ox: float, oy: float, scale: float = 1.0, ink=None, w=None, dash=None) -> None:
        for x0, y0, x1, y1 in segs:
            self.stroke(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale, ink, w, None, dash)

    def poly(self, pts: Poly, ox: float, oy: float, scale: float = 1.0, ink=None, w=None,
             dash=None, fill: bool = False) -> None:
        if fill:
            self._fill([self.P(ox + x * scale, oy + y * scale) for x, y in pts], ink or self.ink)
            return
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            self.stroke(ox + x0 * scale, oy + y0 * scale, ox + x1 * scale, oy + y1 * scale, ink, w, None, dash)

    def ops(self, ops: list[tuple], ox: float, oy: float, scale: float, ink=None, w=None,
            dash: str | None = None, fill_all: bool = False, detail: bool = True) -> None:
        for op in ops:
            k = op[0]
            if k == "lod":
                if not detail:
                    return
                continue
            if k == "poly":
                self.poly(op[1], ox, oy, scale, ink, w, dash, fill=(op[2] or fill_all))
            elif k == "seg":
                self.stroke(ox + op[1] * scale, oy + op[2] * scale, ox + op[3] * scale, oy + op[4] * scale, ink, w, None, dash)
            elif k == "circle":
                self.circle(ox + op[1] * scale, oy + op[2] * scale, op[3] * scale, ink, w, fill=(op[4] or fill_all))
            elif k == "arc":
                self.arc(ox + op[1] * scale, oy + op[2] * scale, op[3] * scale, op[4], op[5], ink, w)
            elif k == "pie":
                self.pie(ox + op[1] * scale, oy + op[2] * scale, op[3] * scale, op[4], op[5], ink)
            elif k == "curve":
                self.curve(ox + op[1] * scale, oy + op[2] * scale, ox + op[3] * scale, oy + op[4] * scale,
                           ox + op[5] * scale, oy + op[6] * scale, ink, w, op[7])


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
        pen.ops(SEEDS[name], x, y, scale, ink, max(1, int(pen.w * 0.8)), detail=False)
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
        getattr(pl, name).append(m)
    return pl


INK_BUDGET = 6        # components per character before a composition is written as a compound


def _components(pl: "_Plan", roles: list, hname: str) -> int:
    lob = LOBES.get(hname)
    below = [r for r in roles if not (lob is not None and r[0] in (1, 2))]
    return (len(pl.scalar) + len(pl.epistemic) + len(pl.modal) + len(pl.temporal) + len(pl.valence) + len(pl.illoc)
            + len(pl.causal) + len(pl.relational) + len(pl.deictic) + len(pl.affect) + len(pl.logical)
            + (1 if pl.negate else 0) + len(below) + (1 if len(roles) > len(below) else 0))


def _split_plan(pl: "_Plan") -> tuple["_Plan", "_Plan"]:
    """Compound split: the first character keeps what shapes the head itself
    (scale, stroke, enclosure, negation, inner marks, connector); the second
    carries what stands around it (crown, ground, radical, logic) and the
    role row.  Fixed order, so a reader learns it once."""
    a, b = _Plan(), _Plan()
    a.scalar, a.epistemic, a.modal, a.negate = pl.scalar, pl.epistemic, pl.modal, pl.negate
    a.deictic, a.affect, a.causal, a.relational = pl.deictic, pl.affect, pl.causal, pl.relational
    b.temporal, b.valence, b.illoc, b.logical = pl.temporal, pl.valence, pl.illoc, pl.logical
    return a, b


@dataclass
class _Layout:
    """The structure chosen for a character and the boxes that follow from it."""
    x0: float; y0: float; x1: float; y1: float           # box left for the head after bands are taken
    crown: tuple | None = None                          # (x0, x1, y_base)
    ground: tuple | None = None                         # (x0, x1, y)
    radical: tuple | None = None                        # (x, y0, y1)
    connector: tuple | None = None                      # (x0, x1, y)
    rolerow: tuple | None = None                        # (y, x0, x1)
    enclosure: tuple | None = None                      # (x0, y0, x1, y1)
    head: tuple = (0, 0, 0)                             # (hx0, hy0, side)


def _layout(pl: "_Plan", has_below_roles: bool, scalar_scale: float) -> _Layout:
    """Structure selection: bands exist only for components that are present,
    and the head takes the largest square that remains (米 grid: everything
    is centred on the vertical axis through the head)."""
    L = _Layout(1.0, HEADLINE_Y + 1.0, GRID - 1.0, GRID - 0.8)
    if pl.valence:
        L.crown = (0, 0, L.y0 + 1.6)
        L.y0 += 2.6
    if has_below_roles:
        L.rolerow = (L.y1 - 2.0, 0, 0)
        L.y1 -= 2.8
    if pl.temporal:
        L.ground = (0, 0, L.y1 - 0.9)
        L.y1 -= 2.3
    if pl.illoc:
        L.radical = (L.x0 + 1.0, 0, 0)
        L.x0 += 2.6
    if pl.causal or pl.relational:
        L.connector = (0, L.x1, 0)
        L.x1 -= 3.0
    inset = ENC_MARGIN + 0.3 if pl.modal else 0.0
    avail = min(L.x1 - L.x0, L.y1 - L.y0) - 2 * inset
    side = avail * min(1.0, scalar_scale)
    cx = (L.x0 + L.x1) / 2
    cy = (L.y0 + L.y1) / 2
    hx0, hy0 = cx - side / 2, cy - side / 2
    L.head = (hx0, hy0, side)
    if pl.modal:
        m = ENC_MARGIN
        L.enclosure = (hx0 - m, hy0 - m, hx0 + side + m, hy0 + side + m)
    ex0, ey0, ex1, ey1 = L.enclosure if L.enclosure else (hx0, hy0, hx0 + side, hy0 + side)
    if L.crown:
        L.crown = (ex0 + 0.3, ex1 - 0.3, ey0 - 0.45)
    if L.ground:
        L.ground = (ex0 - 0.3, ex1 + 0.3, ey1 + 0.75)
    if L.radical:
        L.radical = (L.radical[0], ey0 + 0.2, ey1 - 0.2)
    if L.connector:
        L.connector = (ex1 + 0.05, L.connector[1], cy)
    if L.rolerow:
        L.rolerow = (L.rolerow[0], ex0 - 0.6, ex1 + 0.6)
    return L


def draw_char(draw: ImageDraw.ImageDraw, comp: Composition | None, x: float, y: float, st: CharStyle,
              depth: int = 0, part: int = 0, pl_override: "_Plan | None" = None, roles_override: list | None = None) -> None:
    """Compose one character at (x, y).

    ``part`` 0 = a whole composition or the first character of a compound,
    1 = the second character of a compound (head shown as a small seed)."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["ink"], st)
    thin = pen.w * 0.62
    if st.grid:
        for i in range(GRID + 1):
            draw.line([(x + i * u, y), (x + i * u, y + st.cell)], fill=C["faint"], width=1)
            draw.line([(x, y + i * u), (x + st.cell, y + i * u)], fill=C["faint"], width=1)
    if st.frame:
        draw.rectangle([x, y, x + st.cell - 1, y + st.cell - 1], outline=C["faint"] if st.frame == "faint" else C["dim"], width=1)
    if comp is None:
        return
    hname = inv.name_of(comp.head)
    pl = pl_override if pl_override is not None else _plan(comp)
    roles = list(comp.roles) if roles_override is None else list(roles_override)
    ink = C["ink"]
    def K(cls: str):
        return C[cls] if st.color else C["ink"]

    scalar_scale, fillmode = 1.0, None
    if pl.scalar:
        scalar_scale, fillmode = SCALAR_SHAPE[inv.name_of(pl.scalar[0])]
    lob = LOBES.get(hname)
    below = [r for r in roles if not (lob is not None and r[0] in (1, 2))]
    inside = [r for r in roles if lob is not None and r[0] in (1, 2)]
    L = _layout(pl, bool(below), scalar_scale)
    hx0, hy0, side = L.head
    k = side / 6.0
    cx, cy = hx0 + side / 2, hy0 + side / 2

    # stroke for the head: epistemic
    wmul, dash = 1.0, None
    for ep in pl.epistemic:
        w2, d2 = EPISTEMIC_STROKE[inv.name_of(ep)]
        wmul = max(wmul, w2)
        if d2 in ("dash", "dot") and dash not in ("dash", "dot"):
            dash = d2
        elif dash is None:
            dash = d2
    ep_names = {inv.name_of(e) for e in pl.epistemic}
    hw = pen.w * wmul
    detail = side >= 5.2 and fillmode not in ("full", "half") and not inside and not pl.deictic and not pl.affect and not pl.modal

    # -- head ------------------------------------------------------------------------------
    d = dash if dash in ("dash", "dot") else None
    head_ink = K("epistemic") if (d or "CONTESTED" in ep_names or "KNOWN" in ep_names) else ink
    if part == 1:
        # second character of a compound: the head as a seed, centred, so the character keeps its identity
        pen.ops(SEEDS[hname], cx - 1.3, cy - 1.3, 1.3, C["dim"], pen.w * 0.8, detail=False)
    elif fillmode == "full":
        for pg in HEAD_POLYS[hname]:
            pen.poly(pg, hx0, hy0, k, ink, fill=True)
        for op in HEADS[hname]:
            if op[0] == "circle":
                pen.circle(hx0 + op[1] * k, hy0 + op[2] * k, op[3] * k, ink, fill=True)
            if op[0] == "lod":
                break
    else:
        pen.ops(HEADS[hname], hx0, hy0, k, head_ink, hw, d, detail=detail)
        if fillmode == "half":
            for i in range(3):
                yy = hy0 + side * (0.6 + i * 0.13)
                pen.stroke(hx0 + side * 0.2, yy, hx0 + side * 0.8, yy, K("scalar"), thin, "heng")
        if fillmode == "double" or "CONTESTED" in ep_names:
            iink = K("scalar") if fillmode == "double" else K("epistemic")
            for pg in HEAD_POLYS[hname]:
                inner = [(cx + (hx0 + px * k - cx) * 0.6, cy + (hy0 + py * k - cy) * 0.6) for px, py in pg]
                pen.poly(inner, 0, 0, 1, iink, thin)
            if not HEAD_POLYS[hname]:
                pen.circle(cx, cy, side * 0.28, iink, thin)
        if fillmode == "hollow":
            pen.dot(cx, cy, 0.35, ink)
        if "OBSERVED" in ep_names:
            pen.circle(cx, cy, 0.9, C["bg"], fill=True)
            pen.circle(cx, cy, 0.65, K("epistemic"), thin)
            pen.dot(cx, cy, 0.22, K("epistemic"))
        if pl.negate:
            pen.stroke(hx0 + 0.1, hy0 + side - 0.1, hx0 + side - 0.1, hy0 + 0.1, K("modal"), hw * 1.1, "pie")

    # -- enclosure (modal), attached: it is the head's outer edge -----------------------------------
    ex0, ey0, ex1, ey1 = L.enclosure if L.enclosure else (hx0, hy0, hx0 + side, hy0 + side)
    if pl.modal:
        mname = inv.name_of(pl.modal[0])
        ink = K("modal")
        r = 0.9
        if mname == "NECESSARY":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
        elif mname == "POSSIBLE":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin, dash="dash")
        elif mname == "HYPOTHETICAL":
            pen.rounded_box(ex0, ey0, ex1, ey1, 1.5, ink, thin, corners_only=True)
        elif mname == "PERMITTED":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin, open_top=True)
        elif mname == "FORBIDDEN":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
            pen.stroke(ex0 - 0.3, ey0, ex1 + 0.3, ey0, ink, hw, "heng")
        elif mname == "DESIRED":
            pen.rounded_box(ex0, ey0, ex1, ey1, r, ink, thin)
            pen.dot(ex1 - 0.8, ey0 + 0.8, 0.3, ink)
        elif mname == "AFFIRM":
            pen.arc(cx, ey1 - 0.1, (ex1 - ex0) / 2 - 0.3, 20, 160, ink, thin)

    ink = K("scalar")
    # -- scalar tips at the enclosure's right corners ------------------------------------------
    if fillmode == "brackets":
        for sx, dx in ((ex0 - 0.5, 0.8), (ex1 + 0.5, -0.8)):
            pen.stroke(sx, ey0, sx, ey1, ink, hw, "shu")
            pen.stroke(sx, ey0, sx + dx, ey0, ink, hw, "heng"); pen.stroke(sx, ey1, sx + dx, ey1, ink, hw, "heng")
    if fillmode == "open":
        pen.stroke(ex0 - 1.6, cy, ex0, cy, ink, hw, "heng"); pen.stroke(ex1, cy, ex1 + 1.6, cy, ink, hw, "heng")
    if fillmode in ("rise", "fall"):
        dy = -1 if fillmode == "rise" else 1
        tx, ty = ex1, (ey0 if fillmode == "rise" else ey1)
        pen.stroke(tx, ty, tx + 1.5, ty + dy * 1.5, ink, hw)
        pen.stroke(tx + 1.5, ty + dy * 1.5, tx + 0.4, ty + dy * 1.5, ink, hw, "heng")
        pen.stroke(tx + 1.5, ty + dy * 1.5, tx + 1.5, ty + dy * 0.4, ink, hw, "shu")

    # -- crown (valence): sits on the head/enclosure top edge --------------------------------------
    ink = K("valence")
    if L.crown and pl.valence:
        v = inv.name_of(pl.valence[0])
        cx0, cx1, cyb = L.crown
        mid = (cx0 + cx1) / 2
        rr = min((cx1 - cx0) / 2, 2.6)
        if v == "GOOD":
            pen.arc(mid, cyb + 0.6, rr, 195, 345, ink, hw)
        elif v == "BAD":
            pen.arc(mid, cyb - 1.9, rr, 15, 165, ink, hw)
        elif v == "REQUIRED":
            pen.stroke(cx0, cyb - 1.0, cx1, cyb - 1.0, ink, hw, "heng"); pen.stroke(cx0, cyb, cx1, cyb, ink, hw, "heng")
        elif v == "OPTIONAL":
            pen.stroke(cx0, cyb - 0.4, cx1, cyb - 0.4, ink, hw, dash="dash")
        elif v == "SAFE":
            pen.stroke(cx0, cyb - 1.0, cx1, cyb - 1.0, ink, hw, "heng")
            pen.stroke(cx0, cyb - 1.0, cx0, cyb + 0.2, ink, hw, "shu"); pen.stroke(cx1, cyb - 1.0, cx1, cyb + 0.2, ink, hw, "shu")
        elif v == "HARM":
            pen.wave(cx0, cyb - 0.6, cx1, 0.6, 3, ink, hw)
        elif v == "COST":
            pen.stroke(cx0, cyb - 0.4, cx1, cyb - 0.4, ink, hw, "heng"); pen.stroke(cx0, cyb - 1.2, cx0, cyb + 0.2, ink, hw, "shu")
        elif v == "BENEFIT":
            pen.stroke(cx0, cyb - 0.4, cx1, cyb - 0.4, ink, hw, "heng"); pen.stroke(cx1, cyb - 1.4, cx1, cyb + 0.2, ink, hw, "shu")
    for i, lg in enumerate(pl.logical[:2]):
        _logic_mark(pen, inv.name_of(lg), 1.0 + i * 2.2, HEADLINE_Y + 1.7, K("logical"), thin)

    # -- ground line (temporal): the head stands on it ----------------------------------------------
    ink = K("temporal")
    if L.ground and pl.temporal:
        gx0, gx1, gy = L.ground
        names = [inv.name_of(t) for t in pl.temporal]
        if "DURATIVE" in names:
            pen.stroke(gx0, gy - 0.3, gx1, gy - 0.3, ink, hw, "heng"); pen.stroke(gx0, gy + 0.45, gx1, gy + 0.45, ink, hw, "heng")
        elif "REPEAT" in names:
            pen.wave(gx0, gy, gx1, 0.5, 3, ink, hw)
        elif names != ["PUNCTUAL"]:
            pen.stroke(gx0, gy, gx1, gy, ink, hw, "heng")
        for tn in names:
            dotpos = {"PAST": 0.1, "NOW": 0.5, "FUTURE": 0.9, "BEFORE": 0.22, "AFTER": 0.78, "DURING": 0.5}.get(tn)
            if tn == "PUNCTUAL":
                pen.stroke(cx, gy - 0.9, cx, gy + 0.9, ink, hw, "shu")
            elif tn == "BEGIN":
                pen.stroke(gx0, gy - 0.9, gx0, gy + 0.9, ink, hw, "shu")
            elif tn == "END":
                pen.stroke(gx1, gy - 0.9, gx1, gy + 0.9, ink, hw, "shu")
            if tn in ("BEFORE", "AFTER", "DURING"):
                for f in ((0.62,) if tn == "BEFORE" else (0.38,) if tn == "AFTER" else (0.12, 0.88)):
                    px = gx0 + (gx1 - gx0) * f
                    pen.stroke(px, gy - 0.9, px, gy + 0.9, ink, hw, "shu")
            if dotpos is not None:
                pen.dot(gx0 + (gx1 - gx0) * dotpos, gy, 0.45, ink)

    # -- left radical (illocution): a tall narrow allomorph beside the head -------------------------
    ink = K("illoc")
    if L.radical and pl.illoc:
        iname = inv.name_of(pl.illoc[0])
        rx, ry0, ry1 = L.radical
        pen.stroke(rx, ry0, rx, ry1, ink, hw, "shu", dash="dash" if iname == "PROPOSE" else None)
        if iname == "REQUEST":
            pen.arc(rx + 0.9, ry1 - 0.9, 0.9, 0, 90, ink, hw)
        elif iname == "COMMIT":
            pen.stroke(rx + 0.95, ry0, rx + 0.95, ry1, ink, hw, "shu")
        elif iname == "QUERY":
            pen.arc(rx + 0.8, ry0 + 0.8, 0.8, 180, 360, ink, hw)
            pen.stroke(rx + 1.6, ry0 + 0.8, rx + 1.6, ry0 + 1.8, ink, hw, "shu")
        elif iname == "WARN":
            pen.stroke(rx - 0.8, (ry0 + ry1) / 2, rx + 0.8, (ry0 + ry1) / 2, ink, hw, "heng")
        elif iname == "REFUSE":
            pen.stroke(rx + 0.9, (ry0 + ry1) / 2 - 1, rx - 0.9, (ry0 + ry1) / 2 + 1, ink, hw, "pie")
        elif iname == "ACKNOWLEDGE":
            pen.stroke(rx - 0.6, ry1 - 0.9, rx, ry1, ink, hw, "na"); pen.stroke(rx + 1.0, ry1 - 1.6, rx, ry1, ink, hw, "pie")
        elif iname == "ASSERT":
            pen.dot(rx, ry0 - 0.2, 0.32, ink)

    # -- connector (causal / relational): leaves the head's right edge ---------------------------------
    conn = (pl.causal + pl.relational)[:1]
    if L.connector and conn:
        ax0, ax1, ay = L.connector
        _connector(pen, inv.name_of(conn[0]), ax0, ax1, ay, K("causal") if pl.causal else K("relational"), hw, thin)

    # -- inner marks: on the vertical axis, upper and lower thirds --------------------------------------
    inner_ok = part == 0 and side >= 4.6 and fillmode not in ("full", "half")
    msc = max(0.9, side / 7.5)
    if pl.deictic and inner_ok:
        _deictic_mark(pen, inv.name_of(pl.deictic[0]), cx, hy0 + side * 0.17, K("deictic"), thin, msc)
    if pl.affect and inner_ok:
        _affect_mark(pen, inv.name_of(pl.affect[0]), cx, hy0 + side * 0.85, K("affect"), thin, msc)
    ink = C["ink"]

    # -- roles: lobes inside; the rest in the role row under the ground --------------------------------
    if inside and inner_ok:
        for code, node in inside:
            lx, ly = lob[0 if code == 1 else 1]
            sx, sy = hx0 + lx * k, hy0 + ly * k
            sc = max(0.7, k * 0.85)
            _draw_seed(pen, node, sx, sy, sc, ink)
            if isinstance(node, Composition):
                pen.stroke(sx, sy + 2.35 * sc, sx + 2 * sc, sy + 2.35 * sc, ink, thin, "heng")
    elif inside:
        below = inside + below
    if L.rolerow and below:
        ry, rx0, rx1 = L.rolerow
        n = len(below)
        span = max(rx1 - rx0, 2.4 * n)
        x0r = cx - span / 2
        slot = span / n
        for i, (code, node) in enumerate(below):
            sx = x0r + i * slot + slot / 2 - 0.9
            _draw_seed(pen, node, sx, ry, 0.9, ink)
            if isinstance(node, Composition):
                pen.stroke(sx, ry - 0.45, sx + 1.8, ry - 0.45, ink, thin, "heng")
            col, underline = ROLE_COLS.get(code, (3, False))
            if underline:
                pen.stroke(sx, ry + 2.15, sx + 1.8, ry + 2.15, ink, thin, "heng")

    if part == 0 and any(isinstance(m, Composition) for m in comp.modifiers):
        pen.stroke(ex0, ey1 + 0.3, ex1, ey1 + 0.3, C["dim"], thin, "heng")
    if comp.residue is not None and part == 0:
        pen.wave(0.6, GRID - 0.9, 2.6, 0.35, 2, C["dim"], thin)
    for i in range(depth):
        pen.dot(0.9 + i * 0.9, GRID - 0.9, 0.2, ink)


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


def _sub(pen: _Pen, cx: float, cy: float, sc: float) -> _Pen:
    """A pen whose origin is (cx, cy) and whose unit is scaled: inner marks grow with the head."""
    X, Y = pen.P(cx, cy)
    sub = _Pen(pen.d, X, Y, pen.u * sc, pen.ink, pen.st)
    sub.w = pen.w
    return sub


def _deictic_mark(pen: _Pen, name: str, cx: float, cy: float, ink, thin: int, sc: float = 1.0) -> None:
    if sc != 1.0:
        pen, cx, cy = _sub(pen, cx, cy, sc), 0.0, 0.0
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


def _affect_mark(pen: _Pen, name: str, cx: float, cy: float, ink, thin: int, sc: float = 1.0) -> None:
    if sc != 1.0:
        pen, cx, cy = _sub(pen, cx, cy, sc), 0.0, 0.0
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


def word_chars(comp: Composition) -> list[tuple]:
    """The character sequence for a composition.

    Each entry is (comp, depth, part, plan, roles).  A composition whose
    component count exceeds the ink budget is written as a compound of two
    characters (part 0 and part 1) in a fixed split; nested compositions
    follow depth-first in role order."""
    out: list = []

    def visit(c: Composition, depth: int) -> None:
        pl = _plan(c)
        hname = inv.name_of(c.head)
        roles = list(c.roles)
        lob = LOBES.get(hname)
        inside = [r for r in roles if lob is not None and r[0] in (1, 2)]
        below = [r for r in roles if not (lob is not None and r[0] in (1, 2))]
        if _components(pl, roles, hname) > INK_BUDGET:
            a, b = _split_plan(pl)
            out.append((c, depth, 0, a, inside))
            out.append((c, depth, 1, b, below))
        else:
            out.append((c, depth, 0, pl, roles))
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

def _draw_digit(pen: _Pen, d: int, x: float, y: float, sc: float, ink) -> None:
    """Cuneiform-style digit in a 3×3 cell: d verticals in rows of three, 0 a ring."""
    if d == 0:
        pen.circle(x + 1.5 * sc, y + 1.5 * sc, 0.9 * sc, ink, pen.w * 0.8)
        return
    for i in range(d):
        row, col = divmod(i, 3)
        n_in_row = min(3, d - row * 3)
        cx = x + (0.5 + col * 1.0 + (3 - n_in_row) * 0.5) * sc
        y0 = y + (0.1 + row * 1.0) * sc
        pen.stroke(cx, y0, cx, y0 + 0.85 * sc, ink, pen.w * 0.9, "shu")


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
        pen.stroke(1.0, 15.2, 16.0, 15.2, C["literal"], pen.w * 0.9, "heng")     # numeral baseline
        if gi == 0 and neg:
            pen.stroke(1.0, 3.0, 3.4, 3.0, C["ink"], None, "heng")
        cx = 1.2
        for ch in g:
            if ch == ".":
                pen.dot(cx + 0.6, 13.6, 0.4, C["ink"])
                cx += 1.6
                continue
            _draw_digit(pen, int(ch), cx, 4.6, 1.5, C["ink"])
            cx += 3.9
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
            pen.ops(SEEDS["MOMENT"], 0.5, 0.5, 1.2, C["clay"], detail=False)
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
    """Between a word and its literal: a light tie carrying the role's seed
    (the head kind is not known here, so the tie shows the role by column
    position on a small rule: ARG0..GOAL left to right)."""
    C = THEMES[st.theme]
    u = st.cell / GRID
    pen = _Pen(draw, x, y, u, C["literal"], st)
    pen.stroke(2.5, 8.5, 6.0, 8.5, C["literal"], pen.w * 0.6, "heng")
    code = _role_code_of_path(path)
    if code is not None:
        col = (code - 1) % 6
        pen.dot(2.6 + col * 0.65, 7.2, 0.28, C["clay"])


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
    chars = word_chars(comp)
    if st.headline:
        C = THEMES[st.theme]
        u = st.cell / GRID
        n = len(chars)
        x1 = x + n * st.cell + (n - 1) * st.gap * st.cell
        draw.line([(x + u * 0.6, y + HEADLINE_Y * u), (x1 - u * 0.6, y + HEADLINE_Y * u)], fill=C["dim"], width=max(1, int(st.weight * u * 0.5)))
    for i, (c, depth, part, plan, roles) in enumerate(chars):
        draw_char(draw, c, x, y, st, depth, part=part, pl_override=plan, roles_override=roles)
        x += step
    for path, kind, payload in literals_of(value):
        _binding_marker(draw, path, x, y, st)
        x += step * 0.5
        n = draw_literal(draw, kind, payload, x, y, st)
        x += step * n
    return x - st.gap * st.cell


def _hi(st: CharStyle) -> tuple[CharStyle, int]:
    """A style scaled up for supersampling, and the factor."""
    S = max(1, int(st.supersample))
    if S == 1:
        return st, 1
    from dataclasses import replace
    return replace(st, cell=st.cell * S, supersample=1), S


def _canvas(w: int, h: int, bg) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (int(w), int(h)), tuple(bg) + (255,))
    return img, ImageDraw.Draw(img)


def _down(img: Image.Image, S: int) -> Image.Image:
    out = img.convert("RGB")
    if S > 1:
        out = out.resize((max(1, img.width // S), max(1, img.height // S)), Image.LANCZOS)
    return out


def render_word(comp: Composition, st: CharStyle | None = None, value: Any = True) -> Image.Image:
    st = st or CharStyle()
    hs, S = _hi(st)
    C = THEMES[st.theme]
    img, d = _canvas(word_width(comp, hs, value), hs.cell, C["bg"])
    draw_word(d, comp, 0, 0, hs, value)
    return _down(img, S)


def render_char(comp: Composition, st: CharStyle | None = None) -> Image.Image:
    st = st or CharStyle()
    hs, S = _hi(st)
    C = THEMES[st.theme]
    img, d = _canvas(hs.cell, hs.cell, C["bg"])
    draw_char(d, comp, 0, 0, hs)
    return _down(img, S)


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
    hs, S = _hi(st)
    img, d = _canvas(width * S, height * S, C["bg"])
    y = margin * S
    for line in lines:
        x = margin * S
        for comp, value in line:
            x = draw_word(d, comp, x, y, hs, value) + hs.word_gap * hs.cell
        y += line_h * S
    return _down(img, S)


def render_chart(st: CharStyle | None = None) -> Image.Image:
    """Design chart: the 12 heads bare, then every modifier class on an ENTITY head, then literals."""
    st = st or CharStyle(cell=80, frame=True)
    C = THEMES[st.theme]
    heads = [Composition(p) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]
    rows: list[list[Composition]] = [heads,
                                     [Composition(p, frozenset([inv.pid("LOW")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)],
                                     [Composition(p, frozenset([inv.pid("NONE")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)],
                                     [Composition(p, frozenset([inv.pid("ALL")])) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]]
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
