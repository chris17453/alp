"""The ALP script glyph set (RFC-ALP-001 v1.1 §6): one abstract glyph per primitive.

No letters, no colour, one ink.  Every glyph is a small stroke program in a
unit square (0..1, y down) so it can be drawn at any size by Pillow or emitted
as vector paths for a PDF or a font.  The design is systematic so the script
can be *learned*, not looked up:

  class 0x00 ontological  large closed forms — the heads.  Each is a distinct
                           silhouette (square, chevron, lozenge, bowtie, bars,
                           house, ring, drop, ring+tick, pennant, star, triad).
  class 0x01 modal        a ring, varied by what is inside/through it
  class 0x02 scalar       a horizontal baseline with a level or bracket
  class 0x03 temporal     a time line with a dot placed on it
  class 0x04 causal       an arrow, varied by head/tail/bar
  class 0x05 epistemic    a lozenge (eye), varied by fill and rays
  class 0x06 illocution   a speech wedge, varied by its contents
  class 0x07 valence      a cross/bar family (plus, minus, double, hollow…)
  class 0x08 structural   brackets and hooks (format controls)

Stroke ops:  ("L", x1,y1,x2,y2)  line
             ("P", [(x,y),...], fill)  polygon (closed)
             ("C", cx,cy,r, fill)  circle
             ("A", cx,cy,r, a0,a1)  arc in degrees
             ("D", cx,cy,r)  filled dot
"""

from __future__ import annotations

import math
from typing import Any

from .alpb import Pid
from . import inventory as inv

Op = tuple


def _ring(cx=0.5, cy=0.5, r=0.4) -> list[Op]:
    return [("C", cx, cy, r, False)]


def _arrow(x0, y0, x1, y1, head=0.16) -> list[Op]:
    ang = math.atan2(y1 - y0, x1 - x0)
    hx, hy = x1, y1
    p1 = (hx - head * math.cos(ang - 0.5), hy - head * math.sin(ang - 0.5))
    p2 = (hx - head * math.cos(ang + 0.5), hy - head * math.sin(ang + 0.5))
    return [("L", x0, y0, x1, y1), ("L", hx, hy, *p1), ("L", hx, hy, *p2)]


def _lozenge(cx=0.5, cy=0.5, w=0.42, h=0.26, fill=False) -> list[Op]:
    return [("P", [(cx - w, cy), (cx, cy - h), (cx + w, cy), (cx, cy + h)], fill)]


def _timeline(dot: float | None, span=(0.1, 0.9), y=0.5, thick=False) -> list[Op]:
    ops: list[Op] = [("L", span[0], y, span[1], y)]
    if thick:
        ops.append(("L", span[0], y + 0.08, span[1], y + 0.08))
    if dot is not None:
        ops.append(("D", dot, y, 0.09))
    return ops


def _wedge(extra: list[Op]) -> list[Op]:
    return [("P", [(0.12, 0.15), (0.88, 0.15), (0.88, 0.65), (0.45, 0.65), (0.3, 0.88), (0.3, 0.65), (0.12, 0.65)], False)] + extra


def _star(cx, cy, r, n=8, inner=0.55) -> list[tuple[float, float]]:
    pts = []
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * inner
        a = -math.pi / 2 + math.pi * i / n
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return pts


def _poly(cx, cy, r, n, rot=-math.pi / 2):
    return [(cx + r * math.cos(rot + 2 * math.pi * i / n), cy + r * math.sin(rot + 2 * math.pi * i / n)) for i in range(n)]


GLYPHS: dict[str, list[Op]] = {
    # -- 0x00 ontological heads -------------------------------------------------
    "ENTITY":   [("P", [(0.12, 0.12), (0.88, 0.12), (0.88, 0.88), (0.12, 0.88)], False)],
    "PROCESS":  [("P", [(0.08, 0.3), (0.55, 0.3), (0.55, 0.1), (0.95, 0.5), (0.55, 0.9), (0.55, 0.7), (0.08, 0.7)], False)],
    "PROPERTY": [("P", _poly(0.5, 0.5, 0.44, 4), False)],
    "RELATION": [("P", [(0.1, 0.12), (0.5, 0.5), (0.9, 0.12), (0.9, 0.88), (0.5, 0.5), (0.1, 0.88)], False)],
    "QUANTITY": [("P", [(0.1, 0.6), (0.3, 0.6), (0.3, 0.9), (0.1, 0.9)], False),
                 ("P", [(0.4, 0.38), (0.6, 0.38), (0.6, 0.9), (0.4, 0.9)], False),
                 ("P", [(0.7, 0.12), (0.9, 0.12), (0.9, 0.9), (0.7, 0.9)], False)],
    "AGENT":    [("P", _poly(0.5, 0.52, 0.44, 5), False)],
    "STATE":    [("C", 0.5, 0.5, 0.42, False)],
    "PLACE":    [("P", [(0.5, 0.92), (0.14, 0.42), (0.5, 0.08), (0.86, 0.42)], False), ("D", 0.5, 0.42, 0.07)],
    "MOMENT":   [("C", 0.5, 0.5, 0.42, False), ("L", 0.5, 0.5, 0.5, 0.18), ("L", 0.5, 0.5, 0.72, 0.5)],
    "SIGN":     [("L", 0.2, 0.08, 0.2, 0.92), ("P", [(0.2, 0.1), (0.9, 0.32), (0.2, 0.54)], False)],
    "EVENT":    [("P", _star(0.5, 0.5, 0.45), False)],
    "GROUP":    [("C", 0.32, 0.36, 0.2, False), ("C", 0.68, 0.36, 0.2, False), ("C", 0.5, 0.68, 0.2, False)],

    # -- 0x01 modal: ring family ---------------------------------------------------
    "AFFIRM":       _ring(),
    "NEGATE":       _ring() + [("L", 0.22, 0.78, 0.78, 0.22)],
    "POSSIBLE":     [("A", 0.5, 0.5, 0.4, 20, 160), ("A", 0.5, 0.5, 0.4, 200, 340)],
    "NECESSARY":    [("C", 0.5, 0.5, 0.4, True)],
    "DESIRED":      _ring() + [("D", 0.5, 0.5, 0.14)],
    "HYPOTHETICAL": [("A", 0.5, 0.5, 0.4, a, a + 40) for a in range(0, 360, 90)],
    "PERMITTED":    _ring() + [("L", 0.5, 0.15, 0.5, 0.85)],
    "FORBIDDEN":    _ring() + [("L", 0.22, 0.22, 0.78, 0.78), ("L", 0.22, 0.78, 0.78, 0.22)],

    # -- 0x02 scalar: baseline + level ---------------------------------------------
    "NONE":      [("L", 0.1, 0.85, 0.9, 0.85)],
    "SOME":      [("L", 0.1, 0.85, 0.9, 0.85), ("P", [(0.3, 0.85), (0.7, 0.85), (0.7, 0.65), (0.3, 0.65)], True)],
    "ALL":       [("P", [(0.1, 0.15), (0.9, 0.15), (0.9, 0.85), (0.1, 0.85)], True)],
    "LOW":       [("L", 0.1, 0.85, 0.9, 0.85), ("L", 0.1, 0.65, 0.9, 0.65)],
    "MID":       [("L", 0.1, 0.85, 0.9, 0.85), ("L", 0.1, 0.5, 0.9, 0.5)],
    "HIGH":      [("L", 0.1, 0.85, 0.9, 0.85), ("L", 0.1, 0.25, 0.9, 0.25)],
    "EXTREME":   [("L", 0.1, 0.85, 0.9, 0.85), ("L", 0.1, 0.22, 0.9, 0.22), ("L", 0.1, 0.12, 0.9, 0.12)],
    "BOUNDED":   [("L", 0.15, 0.15, 0.15, 0.85), ("L", 0.85, 0.15, 0.85, 0.85), ("L", 0.15, 0.5, 0.85, 0.5)],
    "UNBOUNDED": [("L", 0.05, 0.5, 0.95, 0.5), ("L", 0.05, 0.5, 0.2, 0.3), ("L", 0.05, 0.5, 0.2, 0.7),
                  ("L", 0.95, 0.5, 0.8, 0.3), ("L", 0.95, 0.5, 0.8, 0.7)],
    "INCREASE":  [("L", 0.1, 0.85, 0.9, 0.85)] + _arrow(0.15, 0.75, 0.85, 0.2),
    "DECREASE":  [("L", 0.1, 0.85, 0.9, 0.85)] + _arrow(0.15, 0.2, 0.85, 0.75),

    # -- 0x03 temporal: timeline + dot ---------------------------------------------------
    "PAST":     _timeline(0.2),
    "NOW":      _timeline(0.5),
    "FUTURE":   _timeline(0.8),
    "DURATIVE": _timeline(None, thick=True),
    "PUNCTUAL": [("D", 0.5, 0.5, 0.12)],
    "BEFORE":   _timeline(0.28) + [("L", 0.6, 0.3, 0.6, 0.7)],
    "DURING":   _timeline(0.5) + [("L", 0.25, 0.3, 0.25, 0.7), ("L", 0.75, 0.3, 0.75, 0.7)],
    "AFTER":    _timeline(0.72) + [("L", 0.4, 0.3, 0.4, 0.7)],
    "REPEAT":   [("A", 0.5, 0.5, 0.32, 30, 330)] + _arrow(0.78, 0.34, 0.8, 0.3, 0.14),
    "BEGIN":    _timeline(None, span=(0.3, 0.9)) + [("L", 0.3, 0.2, 0.3, 0.8), ("D", 0.3, 0.5, 0.09)],
    "END":      _timeline(None, span=(0.1, 0.7)) + [("L", 0.7, 0.2, 0.7, 0.8), ("D", 0.7, 0.5, 0.09)],

    # -- 0x04 causal: arrow family ----------------------------------------------------------
    "CAUSE":     _arrow(0.1, 0.5, 0.9, 0.5),
    "ENABLE":    [("L", 0.1, 0.5, 0.25, 0.5), ("L", 0.35, 0.5, 0.5, 0.5), ("L", 0.6, 0.5, 0.75, 0.5)] + _arrow(0.75, 0.5, 0.9, 0.5, 0.16),
    "PREVENT":   _arrow(0.1, 0.5, 0.9, 0.5) + [("L", 0.55, 0.25, 0.55, 0.75)],
    "CORRELATE": _arrow(0.5, 0.5, 0.9, 0.5) + _arrow(0.5, 0.5, 0.1, 0.5),
    "DEPEND":    _arrow(0.9, 0.5, 0.1, 0.5),
    "TRIGGER":   [("L", 0.1, 0.3, 0.1, 0.7)] + _arrow(0.1, 0.5, 0.9, 0.5),

    # -- 0x05 epistemic: lozenge (eye) family -------------------------------------------------
    "KNOWN":     _lozenge(fill=True),
    "BELIEVED":  _lozenge(),
    "INFERRED":  _lozenge() + [("L", 0.5, 0.5, 0.5, 0.92)],
    "UNKNOWN":   _lozenge() + [("L", 0.3, 0.5, 0.7, 0.5)],
    "CONTESTED": _lozenge(cx=0.36, w=0.3, h=0.2) + _lozenge(cx=0.64, w=0.3, h=0.2),
    "OBSERVED":  _lozenge() + [("D", 0.5, 0.5, 0.1)],
    "PREDICTED": _lozenge(cx=0.4, w=0.32, h=0.22) + _arrow(0.72, 0.5, 0.95, 0.5, 0.12),

    # -- 0x06 illocutionary: speech wedge family -------------------------------------------------
    "ASSERT":      _wedge([("L", 0.3, 0.4, 0.7, 0.4)]),
    "REQUEST":     _wedge(_arrow(0.3, 0.4, 0.7, 0.4, 0.12)),
    "COMMIT":      _wedge([("D", 0.5, 0.4, 0.1)]),
    "QUERY":       _wedge([("A", 0.5, 0.36, 0.13, 180, 90), ("D", 0.5, 0.56, 0.05)]),
    "WARN":        _wedge([("L", 0.5, 0.25, 0.5, 0.45), ("D", 0.5, 0.55, 0.05)]),
    "REFUSE":      _wedge([("L", 0.35, 0.28, 0.65, 0.52), ("L", 0.35, 0.52, 0.65, 0.28)]),
    "PROPOSE":     _wedge([("A", 0.5, 0.4, 0.13, 20, 160), ("A", 0.5, 0.4, 0.13, 200, 340)]),
    "ACKNOWLEDGE": _wedge([("L", 0.32, 0.4, 0.45, 0.52), ("L", 0.45, 0.52, 0.7, 0.28)]),

    # -- 0x07 valence / deontic: bar and cross family ------------------------------------------------
    "GOOD":     [("L", 0.5, 0.15, 0.5, 0.85), ("L", 0.15, 0.5, 0.85, 0.5)],
    "BAD":      [("L", 0.15, 0.5, 0.85, 0.5)],
    "REQUIRED": [("L", 0.4, 0.15, 0.4, 0.85), ("L", 0.6, 0.15, 0.6, 0.85), ("L", 0.15, 0.5, 0.85, 0.5)],
    "OPTIONAL": [("L", 0.15, 0.4, 0.85, 0.4), ("L", 0.15, 0.6, 0.85, 0.6)],
    "SAFE":     [("P", [(0.2, 0.15), (0.8, 0.15), (0.8, 0.55), (0.5, 0.88), (0.2, 0.55)], False)],
    "HARM":     [("P", [(0.2, 0.15), (0.8, 0.15), (0.8, 0.55), (0.5, 0.88), (0.2, 0.55)], False),
                 ("L", 0.35, 0.3, 0.65, 0.6), ("L", 0.35, 0.6, 0.65, 0.3)],
    "COST":     [("L", 0.15, 0.5, 0.85, 0.5), ("L", 0.85, 0.5, 0.65, 0.3), ("L", 0.85, 0.5, 0.65, 0.7), ("L", 0.15, 0.35, 0.15, 0.65)],
    "BENEFIT":  [("L", 0.5, 0.15, 0.5, 0.85), ("L", 0.15, 0.5, 0.85, 0.5), ("C", 0.5, 0.5, 0.42, False)],

    # -- 0x08 structural ---------------------------------------------------------------------------------
    "REF":         [("C", 0.5, 0.5, 0.15, False)] + _arrow(0.65, 0.35, 0.92, 0.08, 0.12),
    "SCOPE_OPEN":  [("L", 0.6, 0.1, 0.4, 0.1), ("L", 0.4, 0.1, 0.4, 0.9), ("L", 0.4, 0.9, 0.6, 0.9)],
    "SCOPE_CLOSE": [("L", 0.4, 0.1, 0.6, 0.1), ("L", 0.6, 0.1, 0.6, 0.9), ("L", 0.6, 0.9, 0.4, 0.9)],
    "SUPERSEDE":   _arrow(0.5, 0.9, 0.5, 0.1) + [("L", 0.3, 0.9, 0.7, 0.9)],
    "RESIDUE":     [("L", 0.2, 0.7, 0.35, 0.3), ("L", 0.35, 0.3, 0.5, 0.7), ("L", 0.5, 0.7, 0.65, 0.3), ("L", 0.65, 0.3, 0.8, 0.7)],
}

assert set(GLYPHS) == set(inv.PRIMITIVES), set(inv.PRIMITIVES) ^ set(GLYPHS)


def glyph(p: Pid | str) -> list[Op]:
    name = p if isinstance(p, str) else inv.name_of(p)
    return GLYPHS[name]


# ---------------------------------------------------------------------------
# Rasterisation (Pillow) and vector emission (PDF / SVG)
# ---------------------------------------------------------------------------

def draw_glyph(draw, p: Pid | str, x: float, y: float, size: float, ink=(0, 0, 0), weight: float | None = None) -> None:
    """Draw a glyph into the square (x, y, x+size, y+size) with a Pillow ImageDraw."""
    w = max(1, int(round(size * (weight if weight is not None else 0.075))))
    def X(u): return x + u * size
    def Y(v): return y + v * size
    for op in glyph(p):
        k = op[0]
        if k == "L":
            draw.line([(X(op[1]), Y(op[2])), (X(op[3]), Y(op[4]))], fill=ink, width=w)
            # round the joins a little
            for ux, uy in ((op[1], op[2]), (op[3], op[4])):
                draw.ellipse([X(ux) - w / 2, Y(uy) - w / 2, X(ux) + w / 2, Y(uy) + w / 2], fill=ink)
        elif k == "P":
            pts = [(X(u), Y(v)) for u, v in op[1]]
            if op[2]:
                draw.polygon(pts, fill=ink)
            else:
                draw.polygon(pts, outline=ink, width=w)
        elif k == "C":
            r = op[3] * size
            box = [X(op[1]) - r, Y(op[2]) - r, X(op[1]) + r, Y(op[2]) + r]
            if op[4]:
                draw.ellipse(box, fill=ink)
            else:
                draw.ellipse(box, outline=ink, width=w)
        elif k == "A":
            r = op[3] * size
            box = [X(op[1]) - r, Y(op[2]) - r, X(op[1]) + r, Y(op[2]) + r]
            draw.arc(box, op[4], op[5], fill=ink, width=w)
        elif k == "D":
            r = op[3] * size
            draw.ellipse([X(op[1]) - r, Y(op[2]) - r, X(op[1]) + r, Y(op[2]) + r], fill=ink)


def svg_path(p: Pid | str, size: float = 100, stroke: float | None = None) -> str:
    """The glyph as SVG elements (for fonts / web); origin top-left."""
    sw = size * (stroke if stroke is not None else 0.075)
    out = []
    S = size
    for op in glyph(p):
        k = op[0]
        if k == "L":
            out.append(f'<line x1="{op[1]*S:.1f}" y1="{op[2]*S:.1f}" x2="{op[3]*S:.1f}" y2="{op[4]*S:.1f}" stroke="currentColor" stroke-width="{sw:.1f}" stroke-linecap="round"/>')
        elif k == "P":
            pts = " ".join(f"{u*S:.1f},{v*S:.1f}" for u, v in op[1])
            fill = "currentColor" if op[2] else "none"
            out.append(f'<polygon points="{pts}" fill="{fill}" stroke="currentColor" stroke-width="{sw:.1f}" stroke-linejoin="round"/>')
        elif k == "C":
            fill = "currentColor" if op[4] else "none"
            out.append(f'<circle cx="{op[1]*S:.1f}" cy="{op[2]*S:.1f}" r="{op[3]*S:.1f}" fill="{fill}" stroke="currentColor" stroke-width="{sw:.1f}"/>')
        elif k == "A":
            cx, cy, r, a0, a1 = op[1] * S, op[2] * S, op[3] * S, op[4], op[5]
            x0, y0 = cx + r * math.cos(math.radians(a0)), cy + r * math.sin(math.radians(a0))
            x1, y1 = cx + r * math.cos(math.radians(a1)), cy + r * math.sin(math.radians(a1))
            large = 1 if ((a1 - a0) % 360) > 180 else 0
            out.append(f'<path d="M{x0:.1f},{y0:.1f} A{r:.1f},{r:.1f} 0 {large} 1 {x1:.1f},{y1:.1f}" fill="none" stroke="currentColor" stroke-width="{sw:.1f}" stroke-linecap="round"/>')
        elif k == "D":
            out.append(f'<circle cx="{op[1]*S:.1f}" cy="{op[2]*S:.1f}" r="{op[3]*S:.1f}" fill="currentColor"/>')
    return "\n".join(out)


def pdf_draw(c, p: Pid | str, x: float, y: float, size: float, stroke: float | None = None) -> None:
    """Draw a glyph on a reportlab canvas.  (x, y) is the *bottom-left* of the cell."""
    sw = size * (stroke if stroke is not None else 0.075)
    c.setLineWidth(sw)
    c.setLineCap(1)
    c.setLineJoin(1)
    def X(u): return x + u * size
    def Y(v): return y + (1 - v) * size
    for op in glyph(p):
        k = op[0]
        if k == "L":
            c.line(X(op[1]), Y(op[2]), X(op[3]), Y(op[4]))
        elif k == "P":
            path = c.beginPath()
            pts = op[1]
            path.moveTo(X(pts[0][0]), Y(pts[0][1]))
            for u, v in pts[1:]:
                path.lineTo(X(u), Y(v))
            path.close()
            c.drawPath(path, stroke=1, fill=1 if op[2] else 0)
        elif k == "C":
            c.circle(X(op[1]), Y(op[2]), op[3] * size, stroke=1, fill=1 if op[4] else 0)
        elif k == "A":
            r = op[3] * size
            # reportlab arcs are counter-clockwise in PDF space; our angles are screen-space (y down)
            c.arc(X(op[1]) - r, Y(op[2]) - r, X(op[1]) + r, Y(op[2]) + r, startAng=-op[5], extent=op[5] - op[4])
        elif k == "D":
            c.circle(X(op[1]), Y(op[2]), op[3] * size, stroke=0, fill=1)
