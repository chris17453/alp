"""``alp`` command line interface.

    alp translate "we suspect the deploy caused the outage" --png out.png
    alp encode -f notes.txt -o notes.alpb --png notes.png --pdf notes.pdf
    alp decode notes.alpb
    alp export notes.alpb -o notes.alpt          # ALP/B -> ALP/T
    alp import notes.alpt -o notes.alpb          # ALP/T -> ALP/B
    alp render notes.alpt --pdf audit.pdf
    alp compose '$PROPERTY.HIGH.PUNCTUAL.REQUIRED' --png urgency.png
    alp key --png key.png                        # the glyph key (the only English)
    alp forks notes.alpt                         # synonymy-fork candidates (§12.6)
    alp verify notes.alpb
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

from . import __version__, alpt, render
from . import inventory as inv
from .alpb import Pid, Ref
from .composition import Composition
from .events import (
    AttestLevel, EventType, Stream, StreamError, agent_sid, new_stream_id,
    PROFILE_BY_NAME, PROFILE_NAMES,
)
from .lexicon import find_forks
from .translate import Translator, SimpleTranslator, split_sentences, stats

DEFAULT_LEXICON = Path(os.environ.get("ALP_LEXICON", Path.home() / ".local" / "share" / "alp" / "lexicon.alpt"))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_text(args) -> str:
    if getattr(args, "file", None):
        if args.file == "-":
            return sys.stdin.read()
        return Path(args.file).read_text(encoding="utf-8")
    if getattr(args, "text", None):
        return " ".join(args.text)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("error: give text, -f FILE, or pipe text on stdin")


def _profile(name: str) -> int:
    if name.isdigit():
        n = int(name)
        if n in (256, 128, 96, 64):
            return n // 8
        if n in (32, 16, 12, 8):
            return n
    key = name.upper() if name.upper().startswith("SID-") else "SID-" + name
    if key in PROFILE_BY_NAME:
        return PROFILE_BY_NAME[key]
    raise argparse.ArgumentTypeError(f"unknown profile {name!r} (SID-256|SID-128|SID-96|SID-64)")


def _translator(args) -> Translator | SimpleTranslator:
    if getattr(args, "simple", False):
        return SimpleTranslator(keep_gloss=not args.no_gloss)
    return Translator(names=args.names, keep_gloss=not args.no_gloss)


def _load_stream(path: str, profile: int | None = None) -> tuple[Stream, str | None]:
    data = sys.stdin.buffer.read() if path == "-" else Path(path).read_bytes()
    if data.lstrip().startswith(b"%alp/t"):
        text = data.decode("utf-8")
        return alpt.loads(text).stream, text
    return Stream.from_bytes(data, profile), None


def _load_lexicon(path: Path) -> list[Composition]:
    if not path.exists():
        return []
    return alpt.loads(path.read_text(encoding="utf-8")).symbols


def _save_lexicon(path: Path, comps: dict[bytes, Composition]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(alpt.dumps_symbols(comps.values()), encoding="utf-8")


def _out(path: str | None, data: bytes | str) -> None:
    if path is None or path == "-":
        if isinstance(data, bytes):
            sys.stdout.buffer.write(data)
        else:
            sys.stdout.write(data)
            if not data.endswith("\n"):
                sys.stdout.write("\n")
    else:
        Path(path).write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))


def _build_stream(translations, author: str, profile: int, stream_seed: str | None,
                  clock: int | None, checkpoint: bool, values: bool) -> Stream:
    """English -> stream: JOIN, AMEND each new symbol, ASSERT it with its bound data."""
    s = Stream(new_stream_id(stream_seed), profile)
    t = int(time.time()) if clock is None else clock
    s.join(author, competence=list(inv.PRIMITIVES.values()), timestamp=t)
    seen: set[bytes] = set()
    for i, tr in enumerate(translations, 1):
        c = tr.composition
        if c.sid not in seen:
            s.amend(author, [c], timestamp=t + i * 2)
            seen.add(c.sid)
        if values:
            s.assert_(author, [(c, getattr(tr, "value", True))], timestamp=t + i * 2 + 1)
    if checkpoint:
        s.checkpoint(author, timestamp=t + len(translations) * 2 + 2)
    return s


def _emit_images(doc, args, title: str) -> list[str]:
    written = []
    if getattr(args, "png", None):
        written += render.save_png(doc, args.png, theme=_theme(args))
    if getattr(args, "pdf", None):
        written.append(render.save_pdf(doc, args.pdf, title=title, theme=("light" if args.theme == "auto" else args.theme)))
    return written


def _theme(args) -> str:
    return "dark" if args.theme == "auto" else args.theme


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def _print_translations(results, args) -> None:
    width = args.width
    for r in results:
        c = r.composition
        line = f"{c.sid_hex(width)}  {c.transliterate(8)}"
        print(line)
        if r.names:
            print(f"{' ' * width}  bound:   " + "  ".join(f"{k}={v!r}" for k, v in r.names.items()))
        if r.unconsumed:
            print(f"{' ' * width}  residue: {' '.join(r.unconsumed)}")
        if args.verbose:
            print(f"{' ' * width}  source:  {r.source}")
            print(f"{' ' * width}  reads:   {c.reading()}")
            print(f"{' ' * width}  script:  {c.script()!r}")


def cmd_translate(args) -> int:
    text = _read_text(args)
    tr = _translator(args)
    results = tr.translate_text(text)
    if args.json:
        out = []
        for r in results:
            c = r.composition
            out.append({
                "source": r.source, "sid": c.sid_hex(), "composition": c.transliterate(),
                "script": c.script(), "reading": c.reading(), "residue": c.residue,
                "names": r.names, "unconsumed": r.unconsumed, "canonical_hex": c.canonical().hex(),
            })
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        _print_translations(results, args)
    if args.stats:
        print()
        print(stats(results).summary())
    if args.png or args.pdf:
        title = args.title or "ALP"
        doc = render.doc_for_compositions([r.composition for r in results], [r.source for r in results],
                                          title=title, english=args.english, theme=_theme(args),
                                          values=[getattr(r, "value", True) for r in results],
                                          mode=args.style, cell=args.cell, transliteration=not args.no_translit)
        for p in _emit_images(doc, args, title):
            print(f"wrote {p}", file=sys.stderr)
    if args.lexicon:
        lex = {c.sid: c for c in _load_lexicon(args.lexicon)}
        for r in results:
            lex.setdefault(r.composition.sid, r.composition)
        _save_lexicon(args.lexicon, lex)
    return 0


def cmd_encode(args) -> int:
    text = _read_text(args)
    tr = _translator(args)
    results = tr.translate_text(text)
    if not results:
        raise SystemExit("error: no utterances found")
    s = _build_stream(results, args.author, args.profile, args.stream, args.clock,
                      checkpoint=not args.no_checkpoint, values=not args.no_assert)
    if args.text or (args.out and args.out.endswith(".alpt")):
        _out(args.out, alpt.dumps(s))
    else:
        _out(args.out, s.to_bytes())
    if args.stats:
        st = stats(results)
        eng = len(text.encode("utf-8"))
        print(st.summary(), file=sys.stderr)
        print(f"english {eng} B  ->  ALP/B {len(s.to_bytes())} B ({s.profile}, {len(s)} events)  "
              f"ALP/T {len(alpt.dumps(s).encode())} B", file=sys.stderr)
    if args.png or args.pdf:
        title = args.title or "ALP"
        if args.audit:
            doc = render.doc_for_stream(s, title=title, alpt_text=alpt.dumps(s), theme=_theme(args), english=args.english,
                                        mode=args.style, cell=args.cell)
        else:
            doc = render.doc_for_compositions([r.composition for r in results], [r.source for r in results],
                                              title=title, english=args.english, theme=_theme(args),
                                              values=[getattr(r, "value", True) for r in results],
                                              mode=args.style, cell=args.cell, transliteration=not args.no_translit)
        for p in _emit_images(doc, args, title):
            print(f"wrote {p}", file=sys.stderr)
    return 0


def _describe_value(v: Any) -> str:
    if v is True:
        return ""
    if isinstance(v, dict) and "names" in v:
        return "  [" + ", ".join(f"{k}={n!r}" for k, n in v["names"].items()) + "]"
    return "  =  " + alpt.fmt_term(v)


def cmd_decode(args) -> int:
    s, _ = _load_stream(args.input, args.profile)
    lex = s.state.lexicon
    label = s.state.label
    ind = "  " if args.events else ""
    for e in s.ordered():
        who = s.author_name(e.author) or "#" + e.author.hex()[:8]
        if args.events:
            print(f"@{e.eid_hex(8)} {e.type.name:<10} by {who} at {e.iso_time()}")
        if e.type in (EventType.AMEND, EventType.GROUND):
            for c in e.compositions():
                if args.readings or not c.gloss:
                    print(f"{ind}{c.transliterate(8)}")
                    print(f"{ind}  = {c.reading()}")
                else:
                    print(f"{ind}{c.gloss}")
        elif e.type == EventType.ASSERT:
            for pair in e.payload:
                sym = s.state.symbol(pair[0].data)
                if sym is None:
                    desc = f"#{pair[0].hex[:8]} (unknown symbol)"
                elif args.readings or not sym.gloss:
                    desc = sym.reading()
                else:
                    desc = sym.gloss
                print(f"{ind}{desc}{_describe_value(pair[1])}")
        elif args.events:
            if e.type == EventType.REGROUND:
                print(f"  reground {label(e.payload['subject'].data) or e.payload['subject'].hex[:8]}: {e.payload.get('reading')!r}")
            elif e.type == EventType.EXPAND:
                print("  unknown: " + ", ".join(label(r.data) or r.hex[:8] for r in e.payload.get("unknown", [])))
            elif e.type == EventType.ERROR:
                print(f"  error {e.payload.get('code')}: {e.payload.get('detail')}")
            elif e.type == EventType.CHECKPOINT:
                print(f"  checkpoint: {len(e.payload.get('lexicon', []))} symbols, digest {e.payload.get('digest', b'').hex()[:16]}")
    if args.stats:
        n_res = sum(1 for c in lex.values() if c.residue_bearing())
        print(f"\n{len(s)} events, {len(lex)} symbols, {n_res} residue-bearing, profile {s.profile}", file=sys.stderr)
    return 0


def cmd_export(args) -> int:
    s, text = _load_stream(args.input, args.profile)
    if args.archive and s.sid_width != 32:
        s = s.reprofile(32)
    _out(args.out, alpt.dumps(s, names=not args.no_names))
    return 0


def cmd_import(args) -> int:
    s, _ = _load_stream(args.input)
    if args.reprofile:
        s = s.reprofile(args.reprofile)
    _out(args.out, s.to_bytes())
    return 0


def cmd_verify(args) -> int:
    try:
        s, text = _load_stream(args.input, args.profile)
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {args.input}: {e}")
        return 1
    problems = s.verify()
    txt = alpt.dumps(s)
    try:
        again = alpt.loads(txt).stream
        if again.to_bytes() != s.to_bytes():
            problems.append("ALP/T round-trip is not byte-identical")
    except Exception as e:  # noqa: BLE001
        problems.append(f"ALP/T round-trip failed: {e}")
    for p in problems:
        print(f"  {p}")
    print(f"{'FAIL' if problems else 'ok'} {args.input}: {len(s)} events, {len(s.lexicon())} symbols, "
          f"profile {s.profile}, digest {s.state.digest().hex()[:16]}")
    return 1 if problems else 0


def cmd_render(args) -> int:
    title = args.title or "ALP"
    theme = _theme(args)
    doc = None
    src = args.input
    if src and Path(src).exists():
        raw = Path(src).read_bytes()
        if not args.english_input:
            try:
                s, text = _load_stream(src, args.profile)
                doc = render.doc_for_stream(s, title=args.title, alpt_text=text or alpt.dumps(s),
                                            blocks=not args.no_blocks, theme=theme, english=args.english,
                                            mode=args.style, cell=args.cell)
            except Exception:  # noqa: BLE001
                if raw.lstrip().startswith(b"%alp/t"):
                    raise
        if doc is None:
            text = raw.decode("utf-8")
            results = _translator(args).translate_text(text)
            doc = render.doc_for_compositions([r.composition for r in results], [r.source for r in results],
                                              title=args.title, english=args.english, theme=theme,
                                              values=[getattr(r, "value", True) for r in results],
                                              mode=args.style, cell=args.cell, transliteration=not args.no_translit)
    else:
        text = " ".join(([src] if src else []) + list(args.text or [])) or _read_text(args)
        if text.lstrip().startswith(("$", "!")):
            c = alpt.parse_composition(text)
            doc = render.doc_for_compositions([c], title=args.title, english=args.english, theme=theme,
                                              mode=args.style, cell=args.cell, transliteration=not args.no_translit)
        else:
            results = _translator(args).translate_text(text)
            doc = render.doc_for_compositions([r.composition for r in results], [r.source for r in results],
                                              title=args.title, english=args.english, theme=theme,
                                              values=[getattr(r, "value", True) for r in results],
                                              mode=args.style, cell=args.cell, transliteration=not args.no_translit)
    if args.linear:
        comps = [c for item in doc if isinstance(item, render.Blocks) for c in item.comps]
        comps += [w[0] for item in doc if isinstance(item, render.Chars) for w in item.words if w is not None]
        render.render_linear(comps, theme=theme).save(args.linear)
        print(f"wrote {args.linear}")
    if not (args.png or args.pdf or args.linear):
        args.png = "alp.png"
    for p in _emit_images(doc, args, title):
        print(f"wrote {p}")
    return 0


def cmd_compose(args) -> int:
    c = alpt.parse_composition(" ".join(args.composition))
    if args.gloss:
        c = c.with_gloss(args.gloss)
    print(f"sid        {c.sid_hex()}")
    print(f"comp       {c.transliterate()}")
    print(f"script     {c.script()!r}")
    print(f"canonical  {c.canonical().hex()}  ({len(c.canonical())} B)")
    print(f"reads      {c.reading()}")
    if c.residue_bearing():
        print("note       residue-bearing: not fully derivable from the inventory (§5.5)")
    doc = render.doc_for_compositions([c], title=args.title, english=args.english, theme=_theme(args),
                                      mode=args.style, cell=max(args.cell, 96), transliteration=not args.no_translit)
    for p in _emit_images(doc, args, args.title or "ALP"):
        print(f"wrote {p}")
    return 0


def cmd_inventory(args) -> int:
    if args.json:
        print(json.dumps({
            "inventory_version": inv.INVENTORY_VERSION,
            "primitives": [{"name": n, "pid": p.code, "class": inv.CLASS_NAMES[p.cls],
                            "codepoint": f"U+{0xE000 + p.code:04X}", "sense": inv.SENSES[p]}
                           for n, p in inv.PRIMITIVES.items()],
            "roles": inv.ROLES,
        }, indent=2))
    else:
        print(inv.inventory_table())
    if args.png or args.pdf:
        return cmd_key(args)
    return 0


def cmd_key(args) -> int:
    theme = "light" if args.theme == "auto" else args.theme
    doc = render.doc_for_inventory(theme)
    if args.svg:
        from .glyphs import svg_path
        cells = []
        for i, (name, p) in enumerate(inv.PRIMITIVES.items()):
            x, y = (i % 12) * 60, (i // 12) * 60
            cells.append(f'<g transform="translate({x},{y})">{svg_path(p, 50)}</g>')
        svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="720" height="{((len(cells) + 11) // 12) * 60}" style="color:#eee;background:#111">' + "".join(cells) + "</svg>"
        Path(args.svg).write_text(svg)
        print(f"wrote {args.svg}")
    if not (args.png or args.pdf or args.svg):
        args.png = "alp-key.png"
    if args.png:
        render.save_png(doc, args.png, theme=theme)
        print(f"wrote {args.png}")
    if args.pdf:
        render.save_pdf(doc, args.pdf, title="ALP glyph key", theme=theme)
        print(f"wrote {args.pdf}")
    return 0


def cmd_transcribe(args) -> int:
    """English document -> transcript: script images, ALP/T, ALP/B stream, text transcript."""
    text = _read_text(args)
    tr = _translator(args)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = args.name or (Path(args.file).stem if args.file and args.file != "-" else "transcript")
    paragraphs: list = []
    for block in re.split(r"\n\s*\n", text.strip()):
        para = []
        for sent in split_sentences(block):
            para.append((sent, tr.translate(sent)))
        if para:
            paragraphs.append(para)
    all_tr = [t for para in paragraphs for _, trs in para for t in trs]
    title = args.title or stem
    theme = _theme(args)
    # images
    doc = render.doc_for_transcript(paragraphs, title=title, theme=theme, cell=args.cell, english=False)
    render.save_png(doc, str(out / f"{stem}-script.png"), theme=theme)
    doc_en = render.doc_for_transcript(paragraphs, title=title, theme=theme, cell=args.cell, english=True)
    render.save_png(doc_en, str(out / f"{stem}-transcript.png"), theme=theme)
    render.save_pdf(doc_en, str(out / f"{stem}-transcript.pdf"), title=title, theme="light")
    # stream
    s = _build_stream(all_tr, args.author, args.profile, args.stream or stem, args.clock, checkpoint=True, values=True)
    (out / f"{stem}.alpb").write_bytes(s.to_bytes())
    (out / f"{stem}.alpt").write_text(alpt.dumps(s), encoding="utf-8")
    # text transcript: English | tree | bound | reading
    lines = [f"# {title}", ""]
    for para in paragraphs:
        for src, trs in para:
            lines.append(src)
            for t in trs:
                lines.append(f"    {t.composition.sid_hex(8)}  {t.composition.transliterate(8)}")
                if t.value is not True:
                    lines.append(f"    bound: " + "  ".join(f"{k}={alpt.fmt_term(v)}" for k, v in t.value["bind"].items()))
                lines.append(f"    reads: {t.composition.reading()}")
                if t.unconsumed:
                    lines.append(f"    residue: {' '.join(t.unconsumed)}")
        lines.append("")
    st = stats(all_tr)
    lines.append(st.summary())
    lines.append(f"english {len(text.encode())} B -> ALP/B {len(s.to_bytes())} B ({s.profile}, {len(s)} events)")
    (out / f"{stem}-transcript.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"{stem}: {len(all_tr)} utterances in {len(paragraphs)} paragraphs -> {out}/")
    print(st.summary())
    return 0


def cmd_chart(args) -> int:
    theme = _theme(args)
    doc = render.doc_for_chart(theme)
    if not (args.png or args.pdf):
        args.png = "alp-chart.png"
    for p in _emit_images(doc, args, "ALP character chart"):
        print(f"wrote {p}")
    return 0


def cmd_forks(args) -> int:
    if Path(args.input).exists() and not args.input.endswith(".txt"):
        s, _ = _load_stream(args.input)
        comps = list(s.lexicon().values())
    else:
        comps = _load_lexicon(Path(args.input))
    forks = find_forks(comps, args.threshold)
    for f in forks:
        print(f.describe())
    print(f"{len(forks)} candidate fork(s) among {len(comps)} symbols (threshold {args.threshold})", file=sys.stderr)
    return 0


def cmd_lexicon(args) -> int:
    comps = _load_lexicon(args.lexicon)
    if args.action == "list":
        for c in comps:
            print(f"{c.sid_hex(16)}  {c.transliterate(8)}" + (f'  = "{c.gloss}"' if c.gloss else ""))
        print(f"{len(comps)} symbols in {args.lexicon}", file=sys.stderr)
    elif args.action == "add":
        lex = {c.sid: c for c in comps}
        for text in args.items:
            if text.lstrip().startswith(("$", "!")):
                c = alpt.parse_composition(text)
                lex.setdefault(c.sid, c)
            else:
                for r in Translator().translate_text(text):
                    lex.setdefault(r.composition.sid, r.composition)
        _save_lexicon(args.lexicon, lex)
        print(f"{len(lex)} symbols", file=sys.stderr)
    elif args.action == "export":
        _out(args.out, alpt.dumps_symbols(comps))
    elif args.action == "forks":
        for f in find_forks(comps):
            print(f.describe())
    return 0


def cmd_stats(args) -> int:
    s, _ = _load_stream(args.input, args.profile)
    lex = s.state.lexicon
    by_type: dict[str, int] = {}
    for e in s.events:
        by_type[e.type.name] = by_type.get(e.type.name, 0) + 1
    print(f"profile        {s.profile}")
    print(f"events         {len(s)}  " + " ".join(f"{k}={v}" for k, v in sorted(by_type.items())))
    print(f"symbols        {len(lex)}  residue-bearing={sum(1 for c in lex.values() if c.residue_bearing())}")
    print(f"assertions     {len(s.state.assertions)}")
    print(f"ALP/B bytes    {len(s.to_bytes())}")
    print(f"ALP/T bytes    {len(alpt.dumps(s).encode())}")
    print(f"state digest   {s.state.digest().hex()}")
    print(f"fork candidates {len(find_forks(lex.values()))}")
    return 0


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="alp", description="Agent Lexicon Protocol (RFC-ALP-001 v1.1) toolkit")
    p.add_argument("--version", action="version", version=f"alp {__version__} (inventory {inv.INVENTORY_VERSION})")
    sub = p.add_subparsers(dest="cmd", required=True)

    def text_inputs(sp):
        sp.add_argument("text", nargs="*", help="English text (or use -f / stdin)")
        sp.add_argument("-f", "--file", help="read English from FILE ('-' = stdin)")

    def translator_opts(sp):
        sp.add_argument("--names", choices=["bind", "residue", "drop"], default="bind",
                        help="what to do with names/unknown words: bind as ASSERT data (default), RFC residue, or drop")
        sp.add_argument("--simple", action="store_true", help="use the RFC Appendix E one-head translator")
        sp.add_argument("--no-gloss", action="store_true", help="do not attach the source sentence as gloss")

    def image_outputs(sp):
        sp.add_argument("--png", help="write a PNG image")
        sp.add_argument("--pdf", help="write a PDF document")
        sp.add_argument("--title", help="document title")
        sp.add_argument("--theme", choices=["auto", "dark", "light"], default="auto", help="auto = dark PNG, light PDF")
        sp.add_argument("--english", action="store_true", help="include English source/readings in images (off by default)")
        sp.add_argument("--style", choices=["text", "each", "block"], default="text",
                        help="text = running script (compact, default); each = one utterance per row; block = expanded §6.2 blocks")
        sp.add_argument("--cell", type=int, default=56, help="character size in px for the script")
        sp.add_argument("--no-translit", action="store_true", help="omit the ALP/T listing under the script")
        sp.add_argument("--frame", choices=["faint", "on", "off"], default="faint", help="em-box around each character")
        sp.add_argument("--no-headline", action="store_true", help="omit the word headline")

    sp = sub.add_parser("translate", help="English -> compositions (no stream)")
    text_inputs(sp)
    translator_opts(sp)
    sp.add_argument("--width", type=int, default=8, help="hex digits of SID to display")
    sp.add_argument("--stats", action="store_true", help="report the English-leakage metric")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.add_argument("--lexicon", type=Path, nargs="?", const=DEFAULT_LEXICON, help="also record symbols in a lexicon file")
    image_outputs(sp)
    sp.set_defaults(func=cmd_translate)

    sp = sub.add_parser("encode", help="English -> ALP stream (ALP/B, or ALP/T with --text)")
    text_inputs(sp)
    translator_opts(sp)
    sp.add_argument("-o", "--out", help="output file (default stdout; .alpt extension implies --text)")
    sp.add_argument("--text", action="store_true", help="emit ALP/T instead of ALP/B")
    sp.add_argument("--author", default="a000", help="author agent name (SID = $AGENT ~\"name\")")
    sp.add_argument("--profile", type=_profile, default=16, help="SID-256|SID-128|SID-96|SID-64 (default SID-128)")
    sp.add_argument("--stream", help="seed for a deterministic stream id")
    sp.add_argument("--clock", type=int, help="fixed start timestamp (unix seconds) for reproducible output")
    sp.add_argument("--no-checkpoint", action="store_true")
    sp.add_argument("--no-assert", action="store_true", help="only AMEND symbols, do not ASSERT them")
    sp.add_argument("--stats", action="store_true", help="print size and leakage statistics to stderr")
    sp.add_argument("--audit", action="store_true", help="image/PDF shows the whole stream, not just the symbols")
    image_outputs(sp)
    sp.set_defaults(func=cmd_encode)

    sp = sub.add_parser("decode", help="ALP stream -> English readings")
    sp.add_argument("input", help="ALP/B or ALP/T file ('-' = stdin)")
    sp.add_argument("--profile", type=_profile, help="profile of a binary stream (sniffed if omitted)")
    sp.add_argument("--events", action="store_true", help="show every event, not just content")
    sp.add_argument("--readings", action="store_true", help="generate readings from primitives instead of stored glosses")
    sp.add_argument("--stats", action="store_true")
    sp.set_defaults(func=cmd_decode)

    sp = sub.add_parser("export", help="ALP/B -> ALP/T")
    sp.add_argument("input")
    sp.add_argument("-o", "--out")
    sp.add_argument("--profile", type=_profile)
    sp.add_argument("--archive", action="store_true", help="re-profile to SID-256 for storage (§3.5)")
    sp.add_argument("--no-names", action="store_true", help="omit author-name comments")
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("import", help="ALP/T -> ALP/B")
    sp.add_argument("input")
    sp.add_argument("-o", "--out")
    sp.add_argument("--reprofile", type=_profile, help="re-hash to another profile")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("verify", help="check hashes, canonical form, parents and round-trip")
    sp.add_argument("input")
    sp.add_argument("--profile", type=_profile)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("render", help="images: English, a $COMPOSITION, or a stream -> PNG/PDF")
    sp.add_argument("input", nargs="?", help="file (English, .alpb, .alpt) or inline text / $COMPOSITION")
    sp.add_argument("text", nargs="*")
    sp.add_argument("-f", "--file")
    translator_opts(sp)
    sp.add_argument("--profile", type=_profile)
    sp.add_argument("--english-input", action="store_true", help="force: treat the file as English text")
    sp.add_argument("--no-blocks", action="store_true", help="stream audit without script blocks")
    sp.add_argument("--linear", help="also write the §6.4 linear glyph strip to this PNG")
    image_outputs(sp)
    sp.set_defaults(func=cmd_render)

    sp = sub.add_parser("compose", help="hash and describe a composition written in ALP/T syntax")
    sp.add_argument("composition", nargs="+", help="e.g. '$PROPERTY.HIGH.PUNCTUAL.REQUIRED'")
    sp.add_argument("--gloss")
    image_outputs(sp)
    sp.set_defaults(func=cmd_compose)

    sp = sub.add_parser("inventory", help="print the primitive inventory")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--svg", help="also write the glyph sheet as SVG")
    image_outputs(sp)
    sp.set_defaults(func=cmd_inventory)

    sp = sub.add_parser("key", help="the glyph key: every glyph beside its name (the only English in the script)")
    sp.add_argument("--svg", help="write the raw glyph sheet as SVG")
    image_outputs(sp)
    sp.set_defaults(func=cmd_key)

    sp = sub.add_parser("transcribe", help="English document -> transcript directory (script PNG/PDF, ALP/T, ALP/B, text)")
    text_inputs(sp)
    translator_opts(sp)
    sp.add_argument("-o", "--out-dir", default="transcript", help="output directory")
    sp.add_argument("--name", help="file stem (default: input file name)")
    sp.add_argument("--author", default="a000")
    sp.add_argument("--profile", type=_profile, default=16)
    sp.add_argument("--stream", help="stream id seed")
    sp.add_argument("--clock", type=int)
    image_outputs(sp)
    sp.set_defaults(func=cmd_transcribe)

    sp = sub.add_parser("chart", help="the character chart: heads, every modifier as a transformation, literals")
    image_outputs(sp)
    sp.set_defaults(func=cmd_chart)

    sp = sub.add_parser("forks", help="synonymy-fork candidates in a stream or lexicon (§12.6)")
    sp.add_argument("input", help=".alpb / .alpt stream or lexicon file")
    sp.add_argument("--threshold", type=float, default=0.7)
    sp.set_defaults(func=cmd_forks)

    sp = sub.add_parser("lexicon", help="manage a local lexicon file (ALP/T symbol blocks)")
    sp.add_argument("action", choices=["list", "add", "export", "forks"])
    sp.add_argument("items", nargs="*", help="for add: English or $COMPOSITION strings")
    sp.add_argument("--lexicon", type=Path, default=DEFAULT_LEXICON)
    sp.add_argument("-o", "--out")
    sp.set_defaults(func=cmd_lexicon)

    sp = sub.add_parser("stats", help="size and content statistics for a stream")
    sp.add_argument("input")
    sp.add_argument("--profile", type=_profile)
    sp.set_defaults(func=cmd_stats)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (StreamError, alpt.ALPTError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
