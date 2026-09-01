"""Animation: characters being written, stroke by stroke.

The pen keeps a stroke budget (``script.BUDGET``).  Rendering a frame with a
budget of *k* units draws the first *k* strokes — the k-th partially — so a
sequence of frames with a rising budget is the word being written in stroke
order, with ink laid down the way the composer lays it down: head first, then
enclosure, crown, ground, radical, connector, marks, arguments.

    frames = write_word(comp)                     # list of PIL images
    save_gif(frames, "word.gif")
    save_mp4(frames, "word.mp4")                  # needs ffmpeg on PATH

``write_text`` animates running text; ``title_sequence`` builds a short film:
a fade from black, the chart's heads appearing one by one, then a sentence
written, then held.
"""

from __future__ import annotations

import math
import shutil
import subprocess
from collections.abc import Callable, Sequence
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import script
from .composition import Composition
from .script import THEMES, CharStyle

# ---------------------------------------------------------------------------
# budgeted rendering
# ---------------------------------------------------------------------------

def _count(render: Callable[[], Image.Image]) -> float:
    script.BUDGET = script.Budget(counting=True)
    try:
        render()
        return script.BUDGET.total
    finally:
        script.BUDGET = None


def _at(render: Callable[[], Image.Image], units: float) -> Image.Image:
    script.BUDGET = script.Budget(remaining=units)
    try:
        return render()
    finally:
        script.BUDGET = None


def _ease(t: float) -> float:
    """Ease-in-out so strokes start and finish gently."""
    return 0.5 - 0.5 * math.cos(math.pi * min(1.0, max(0.0, t)))


def frames_for(render: Callable[[], Image.Image], seconds: float = 3.0, fps: int = 24,
               hold: float = 1.0, lead: float = 0.3) -> list[Image.Image]:
    """Frames of ``render()`` drawn progressively over ``seconds``, then held."""
    total = _count(render)
    n = max(1, int(seconds * fps))
    frames: list[Image.Image] = []
    blank = _at(render, 0.0)
    for _ in range(int(lead * fps)):
        frames.append(blank)
    last = None
    for i in range(n + 1):
        units = total * _ease(i / n)
        img = _at(render, units)
        frames.append(img)
        last = img
    for _ in range(int(hold * fps)):
        frames.append(last)
    return frames


def _fast(st: CharStyle) -> CharStyle:
    """Animation frames are many: render at 2× instead of 4×."""
    from dataclasses import replace
    return replace(st, supersample=min(st.supersample, 2))


def write_word(comp: Composition, value: Any = True, st: CharStyle | None = None, seconds: float = 3.0,
               fps: int = 24, hold: float = 1.2) -> list[Image.Image]:
    st = _fast(st or CharStyle(cell=160, frame=False, headline=True))
    return frames_for(lambda: script.render_word(comp, st, value), seconds, fps, hold)


def write_text(words: Sequence, st: CharStyle | None = None, width: int = 1280, seconds: float | None = None,
               fps: int = 24, hold: float = 2.0) -> list[Image.Image]:
    """Running text written in reading order.  Duration defaults to ~0.9 s per character."""
    st = _fast(st or CharStyle(cell=72))
    render = lambda: script.render_text(words, st, width=width)
    if seconds is None:
        n_chars = sum(len(script.word_chars(w[0] if isinstance(w, tuple) else w)) for w in words if w is not None)
        seconds = min(24.0, max(2.0, 0.6 * n_chars))
    return frames_for(render, seconds, fps, hold)


def pulse_word(comp: Composition, value: Any = True, st: CharStyle | None = None, seconds: float = 4.0,
               fps: int = 24, cycles: float = 1.0, breathe: float = 0.12) -> list[Image.Image]:
    """The finished character, alive: class colours cycle through the hue circle
    and the ink breathes.  Loops seamlessly (``cycles`` full hue rotations)."""
    from dataclasses import replace
    st = _fast(st or CharStyle(cell=160, frame=False, headline=True))
    n = max(2, int(seconds * fps))
    frames = []
    for i in range(n):
        t = i / n
        s2 = replace(st, hue_shift=360.0 * cycles * t, blend=min(1.0, st.blend * (1 + breathe * math.sin(2 * math.pi * t))))
        frames.append(script.render_word(comp, s2, value))
    return frames


def trace_word(comp: Composition, value: Any = True, st: CharStyle | None = None, seconds: float = 4.0,
               fps: int = 24, window: float = 3.0) -> list[Image.Image]:
    """The finished character with a bright pulse travelling along its strokes
    in stroke order, over a dimmed body.  Loops."""
    from dataclasses import replace
    st = _fast(st or CharStyle(cell=160, frame=False, headline=True))
    render = lambda s2: script.render_word(comp, s2, value)
    total = _count(lambda: render(st))
    dim = replace(st, blend=st.blend * 0.45, grain=0.0)
    n = max(2, int(seconds * fps))
    frames = []
    base = _at(lambda: render(dim), float("inf"))
    for i in range(n):
        pos = (total + window) * (i / n) - window
        script.BUDGET = script.Budget(remaining=window, start=max(0.0, pos))
        try:
            bright = replace(st, blend=min(1.0, st.blend * 1.15), grain=0.0)
            layer = script.render_word(comp, bright, value)
        finally:
            script.BUDGET = None
        # composite: the highlighted window over the dim body (lighter-ink wins)
        frames.append(Image.composite(layer, base, layer.convert("L").point(lambda v: 255 if v > 30 else 0)))
    return frames


# ---------------------------------------------------------------------------
# a short film
# ---------------------------------------------------------------------------

def _font(size: int, bold: bool = False):
    for name in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), "Arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:  # noqa: BLE001
            continue
    return ImageFont.load_default()


def _card(size: tuple[int, int], theme: str, title: str, sub: str = "") -> Image.Image:
    C = THEMES[theme]
    img = Image.new("RGB", size, C["bg"])
    d = ImageDraw.Draw(img)
    f1, f2 = _font(int(size[1] * 0.075), True), _font(int(size[1] * 0.035))
    w1 = d.textbbox((0, 0), title, font=f1)[2]
    d.text(((size[0] - w1) / 2, size[1] * 0.40), title, font=f1, fill=C["ink"])
    if sub:
        w2 = d.textbbox((0, 0), sub, font=f2)[2]
        d.text(((size[0] - w2) / 2, size[1] * 0.40 + size[1] * 0.11), sub, font=f2, fill=C["dim"])
    return img


def _fit(img: Image.Image, size: tuple[int, int], bg) -> Image.Image:
    """Letterbox ``img`` into ``size``."""
    canvas = Image.new("RGB", size, bg)
    scale = min(size[0] / img.width, size[1] / img.height, 1.0)
    im = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), Image.LANCZOS) if scale < 1 else img
    canvas.paste(im, ((size[0] - im.width) // 2, (size[1] - im.height) // 2))
    return canvas


def _fade(a: Image.Image, b: Image.Image, n: int) -> list[Image.Image]:
    return [Image.blend(a, b, _ease((i + 1) / n)) for i in range(n)]


def title_sequence(words: Sequence, title: str = "ALP", subtitle: str = "a written language for machines",
                   size: tuple[int, int] = (1280, 720), fps: int = 24, theme: str = "dark",
                   caption: str | None = None) -> list[Image.Image]:
    """Title card → the twelve heads appearing → a sentence written → caption → hold."""
    C = THEMES[theme]
    bg = C["bg"]
    black = Image.new("RGB", size, bg)
    frames: list[Image.Image] = []
    # 1. title
    card = _card(size, theme, title, subtitle)
    frames += _fade(black, card, int(0.8 * fps))
    frames += [card] * int(1.6 * fps)
    frames += _fade(card, black, int(0.5 * fps))
    # 2. the twelve heads, one by one
    from . import inventory as inv
    heads = [Composition(p) for p in inv.by_class(inv.CLASS_ONTOLOGICAL)]
    st = _fast(CharStyle(cell=int(size[0] / 14), frame=False, headline=False, theme=theme))
    render_all = lambda: script.render_text([(h, True) for h in heads], st, width=size[0] - 40, margin=20, line_gap=0.2, align="center")
    # cumulative stroke budgets: heads are laid out left to right, so the k-th head's strokes follow the (k-1)-th's
    cum = [0.0] + [_count(lambda k=k: script.render_text([(h, True) for h in heads[:k]], st, width=size[0] - 40, margin=20, line_gap=0.2))
                   for k in range(1, len(heads) + 1)]
    per = int(0.3 * fps)
    for k in range(1, len(heads) + 1):
        for i in range(1, per + 1):
            units = cum[k - 1] + (cum[k] - cum[k - 1]) * _ease(i / per)
            frames.append(_fit(_at(render_all, units), size, bg))
    frames += [frames[-1]] * int(0.8 * fps)
    frames += _fade(frames[-1], black, int(0.4 * fps))
    # 3. the sentence
    n_chars = sum(len(script.word_chars(w[0] if isinstance(w, tuple) else w)) for w in words if w is not None)
    cell = int(min(size[1] / 3.4, (size[0] - 120) / max(1, n_chars + 1) / 1.25))
    st2 = _fast(CharStyle(cell=max(72, cell), frame=False, headline=True, theme=theme))
    render = lambda: script.render_text(words, st2, width=size[0] - 80, margin=40, line_gap=0.35, align="center")
    written = frames_for(render, seconds=max(3.0, 1.2 * sum(len(script.word_chars(w[0] if isinstance(w, tuple) else w)) for w in words if w is not None)), fps=fps, hold=0.3, lead=0.2)
    frames += [_fit(f, size, bg) for f in written]
    # 4. caption under it
    if caption:
        last = frames[-1].copy()
        d = ImageDraw.Draw(last)
        f = _font(int(size[1] * 0.04))
        w = d.textbbox((0, 0), caption, font=f)[2]
        d.text(((size[0] - w) / 2, size[1] * 0.86), caption, font=f, fill=C["text"])
        frames += _fade(frames[-1], last, int(0.5 * fps))
        frames += [last] * int(2.2 * fps)
    else:
        frames += [frames[-1]] * int(2.0 * fps)
    frames += _fade(frames[-1], black, int(0.8 * fps))
    return frames


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------

def save_gif(frames: Sequence[Image.Image], path: str, fps: int = 24, max_width: int | None = 560, colors: int = 64) -> str:
    fr = list(frames)
    if max_width and fr and fr[0].width > max_width:
        h = int(fr[0].height * max_width / fr[0].width)
        fr = [f.resize((max_width, h), Image.LANCZOS) for f in fr]
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=colors, dither=Image.FLOYDSTEINBERG) for f in fr]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 / fps), loop=0, optimize=False, disposal=2)
    return path


def have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def save_mp4(frames: Sequence[Image.Image], path: str, fps: int = 24, crf: int = 18) -> str:
    """H.264 MP4 via ffmpeg (frames piped as PNG).  Raises if ffmpeg is missing."""
    if not have_ffmpeg():
        raise RuntimeError("ffmpeg not found on PATH")
    fr = list(frames)
    w, h = fr[0].size
    w -= w % 2; h -= h % 2                      # yuv420p needs even dimensions
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "image2pipe", "-vcodec", "png", "-framerate", str(fps),
           "-i", "-", "-vf", f"scale={w}:{h}", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", str(crf),
           "-movflags", "+faststart", path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    assert proc.stdin is not None
    for f in fr:
        f.save(proc.stdin, format="PNG")
    proc.stdin.close()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode})")
    return path


def save(frames: Sequence[Image.Image], path: str, fps: int = 24) -> str:
    if path.lower().endswith(".gif"):
        return save_gif(frames, path, fps)
    if path.lower().endswith((".mp4", ".mov", ".webm")):
        return save_mp4(frames, path, fps)
    raise ValueError("animation path must end in .gif or .mp4")
