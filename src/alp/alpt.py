"""ALP/T: the canonical text projection (RFC-ALP-001 v1.1 §7.6).

ALP/T is a *projection* of ALP/B.  It MUST round-trip to byte-identical
canonical ALP/B and hashes are never computed over it.  This module writes and
parses it losslessly.

Document::

    %alp/t 1 inv 1 profile SID-128 stream <hex>
    ; comment

    !<sid> $HEAD.MOD :ROLE $PRIM ~"residue"      ; standalone symbol block
    = "gloss"

    @<eid> TYPE
    <- <eid> <eid>                                ; parents (omitted if none)
    by #<sid>
    at 2026-08-31T14:00:00Z
    fl 0x04                                       ; flags, only if nonzero
      <body line>
      <body line>
    sig 0x<hex>                                   ; detached signature, if SIGNED

Body lines.  Event payloads are either a LIST (ASSERT, AMEND, GROUND, ATTEST)
or a MAP (everything else).  For LIST payloads each body line is one element;
for MAP payloads each body line is ``key term``.  A body line beginning with
``>`` carries the whole payload as a single term (escape hatch for foreign
payload shapes).

Terms::

    #hex        SID ref, profile width       ##hex   SID ref, full 32 bytes
    @hex        EID ref, profile width       @@hex   EID ref, full 32 bytes
    $NAME       primitive                    !sid $comp [= "gloss"]   composition record
    12  -3  1.5  true  false  null  "text"  0xDEADBEEF  (list ...)  {key value ...}

Extensions beyond the RFC grammar (``profile``/``stream`` in the header, the
``fl``/``sig`` lines, ``@hex`` EID terms and ``{}`` maps) exist only because
the RFC's grammar sketch does not cover every ALP/B value that a frame can
carry, and the round-trip requirement (§7.6) wins.
"""

from __future__ import annotations

import calendar
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from . import alpb
from .alpb import Pid, Ref, REF_SID, REF_EID, REF_SID_FULL, REF_EID_FULL, HASH_LEN
from . import inventory as inv
from .composition import Composition, SIDMismatch, quote, unquote, verify as verify_comp
from .events import (
    Event, EventType, Stream, PROFILE_NAMES, PROFILE_BY_NAME, PROFILE_CODES, StreamError,
)
from .inventory import INVENTORY_VERSION, PROTOCOL_VERSION

LIST_PAYLOAD = {EventType.ASSERT, EventType.AMEND, EventType.GROUND, EventType.ATTEST}


class ALPTError(ValueError):
    def __init__(self, msg: str, line: int | None = None) -> None:
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _hex(b: bytes) -> str:
    return bytes(b).hex()


def fmt_term(v: Any, gloss_inline: bool = True) -> str:
    """Render one ALP/B value as an ALP/T term."""
    if v is True:
        return "true"
    if v is False:
        return "false"
    if v is None:
        return "null"
    if isinstance(v, Pid):
        return "$" + inv.name_of(v)
    if isinstance(v, Ref):
        prefix = {REF_SID: "#", REF_EID: "@", REF_SID_FULL: "##", REF_EID_FULL: "@@"}[v.kind]
        return prefix + _hex(v.data)
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        r = repr(v)
        return r if any(c in r for c in ".eina") else r + ".0"
    if isinstance(v, str):
        return quote(v)
    if isinstance(v, (bytes, bytearray)):
        return "0x" + _hex(v)
    if isinstance(v, dict):
        if "h" in v and isinstance(v.get("h"), Pid):
            comp = Composition.from_map(v)
            return fmt_comp(comp, gloss_inline=gloss_inline)
        inner = " ".join(f"{fmt_term(k)} {fmt_term(x)}" for k, x in v.items())
        return "{" + inner + "}"
    if isinstance(v, (list, tuple)):
        return "(" + " ".join(fmt_term(x) for x in v) + ")"
    raise TypeError(f"cannot format {type(v).__name__}")


def fmt_comp(comp: Composition, sid_width: int | None = None, gloss_inline: bool = True) -> str:
    s = "!" + comp.sid_hex(None if sid_width is None else sid_width * 2) + " " + comp.transliterate()
    if comp.supersedes is not None:
        s += " ^#" + _hex(comp.supersedes)
    if gloss_inline and comp.gloss is not None:
        s += " = " + quote(comp.gloss)
    return s


def symbol_block(comp: Composition, sid_width: int | None = None, indent: str = "") -> list[str]:
    """The two-line form: ``!sid comp`` then ``= "gloss"``."""
    lines = [indent + fmt_comp(comp, sid_width, gloss_inline=False)]
    if comp.gloss is not None:
        lines.append(indent + "= " + quote(comp.gloss))
    return lines


def event_block(e: Event, note: str | None = None, author_name: str | None = None) -> list[str]:
    lines: list[str] = []
    if note:
        for ln in note.splitlines():
            lines.append("; " + ln)
    lines.append(f"@{_hex(e.eid_ref)} {e.type.name}")
    if e.parents:
        lines.append("<- " + " ".join(_hex(p) for p in e.parents))
    by = f"by #{_hex(e.author)}"
    if author_name:
        by += f"  ; {author_name}"
    lines.append(by)
    lines.append("at " + e.iso_time())
    if e.flags:
        lines.append(f"fl 0x{e.flags:02x}")
    lines += payload_lines(e)
    if e.signature is not None:
        lines.append("sig 0x" + _hex(e.signature))
    return lines


def payload_lines(e: Event) -> list[str]:
    p = e.payload
    out: list[str] = []
    if e.type in LIST_PAYLOAD and isinstance(p, list):
        for item in p:
            if isinstance(item, dict) and isinstance(item.get("h"), Pid):
                out += symbol_block(Composition.from_map(item), indent="  ")
            else:
                out.append("  " + fmt_term(item))
        if not p:
            out.append("  >()")
    elif e.type not in LIST_PAYLOAD and isinstance(p, dict) and all(isinstance(k, str) and _KEY.fullmatch(k) for k in p):
        for k, v in p.items():
            out.append(f"  {k} {fmt_term(v)}")
        if not p:
            out.append("  >{}")
    else:
        out.append("  >" + fmt_term(p))
    return out


def header(sid_width: int, stream_id: bytes | None = None) -> str:
    h = f"%alp/t {PROTOCOL_VERSION} inv {INVENTORY_VERSION} profile {PROFILE_NAMES[sid_width]}"
    if stream_id is not None:
        h += f" stream {_hex(stream_id)}"
    return h


def dumps(stream: Stream, notes: dict[bytes, str] | None = None, preamble: Iterable[Composition] = (),
          names: bool = True) -> str:
    """Serialize a stream to ALP/T (events in canonical total order)."""
    lines = [header(stream.sid_width, stream.stream_id), ""]
    for c in preamble:
        lines += symbol_block(c)
        lines.append("")
    for e in stream.ordered():
        note = (notes or {}).get(e.eid) or (notes or {}).get(e.eid_ref)
        lines += event_block(e, note, stream.author_name(e.author) if names else None)
        lines.append("")
    return "\n".join(lines)


def dumps_symbols(comps: Iterable[Composition]) -> str:
    """A lexicon-only document (no events)."""
    lines = [header(HASH_LEN), ""]
    for c in comps:
        lines += symbol_block(c)
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Tokenizer / parser
# ---------------------------------------------------------------------------

_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

_TOK = re.compile(
    r"""\s*(?:
        (?P<comment>;.*)
      | (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<comp>![0-9A-Fa-f]+)
      | (?P<sidfull>\#\#[0-9A-Fa-f]+)
      | (?P<eidfull>@@[0-9A-Fa-f]+)
      | (?P<sid>\#[0-9A-Fa-f]+)
      | (?P<eid>@[0-9A-Fa-f]+)
      | (?P<prim>\$[A-Za-z_][A-Za-z0-9_]*)
      | (?P<mod>\.[A-Za-z_][A-Za-z0-9_]*)
      | (?P<role>:[A-Za-z_][A-Za-z0-9_]*)
      | (?P<bytes>0x[0-9A-Fa-f]*)
      | (?P<num>-?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?|-?inf|nan)
      | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
      | (?P<punct>[(){}~^=.>])
    )""",
    re.VERBOSE,
)


@dataclass
class _Tok:
    kind: str
    text: str
    line: int


def tokenize(text: str, line: int = 0) -> list[_Tok]:
    toks: list[_Tok] = []
    pos = 0
    text = text.rstrip("\n")
    while pos < len(text):
        m = _TOK.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip() == "":
                break
            raise ALPTError(f"cannot tokenize near {text[pos:pos+20]!r}", line)
        pos = m.end()
        kind = m.lastgroup
        if kind == "comment":
            break
        toks.append(_Tok(kind, m.group(kind), line))
    return toks


class TermParser:
    def __init__(self, toks: list[_Tok], sid_width: int, strict_sid: bool = True) -> None:
        self.toks = toks
        self.i = 0
        self.width = sid_width
        self.strict_sid = strict_sid

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> _Tok:
        t = self.peek()
        if t is None:
            last = self.toks[-1].line if self.toks else None
            raise ALPTError("unexpected end of input", last)
        self.i += 1
        return t

    def expect(self, kind: str, text: str | None = None) -> _Tok:
        t = self.next()
        if t.kind != kind or (text is not None and t.text != text):
            raise ALPTError(f"expected {text or kind}, got {t.text!r}", t.line)
        return t

    def at_end(self) -> bool:
        return self.peek() is None

    # -- hashes --------------------------------------------------------------
    def _hash(self, hexstr: str, want: int | None, t: _Tok) -> bytes:
        if len(hexstr) % 2:
            raise ALPTError(f"odd-length hash {hexstr}", t.line)
        b = bytes.fromhex(hexstr)
        if want is not None and len(b) != want:
            raise ALPTError(f"hash is {len(b)} bytes, expected {want}", t.line)
        return b

    # -- terms ---------------------------------------------------------------
    def term(self) -> Any:
        t = self.next()
        k, s = t.kind, t.text
        if k == "str":
            return unquote(s)
        if k == "num":
            if re.fullmatch(r"-?\d+", s):
                return int(s)
            return float(s)
        if k == "word":
            if s == "true":
                return True
            if s == "false":
                return False
            if s == "null":
                return None
            raise ALPTError(f"unexpected word {s!r}", t.line)
        if k == "bytes":
            return bytes.fromhex(s[2:])
        if k == "prim":
            return inv.pid(s[1:])
        if k == "sid":
            return Ref(REF_SID, self._hash(s[1:], self.width, t))
        if k == "eid":
            return Ref(REF_EID, self._hash(s[1:], self.width, t))
        if k == "sidfull":
            return Ref(REF_SID_FULL, self._hash(s[2:], HASH_LEN, t))
        if k == "eidfull":
            return Ref(REF_EID_FULL, self._hash(s[2:], HASH_LEN, t))
        if k == "comp":
            return self.comp_record(t).to_map()
        if k == "punct" and s == "(":
            items = []
            while not (self.peek() and self.peek().kind == "punct" and self.peek().text == ")"):
                if self.peek() is None:
                    raise ALPTError("unclosed '('", t.line)
                items.append(self.term())
            self.next()
            return items
        if k == "punct" and s == "{":
            d: dict = {}
            while not (self.peek() and self.peek().kind == "punct" and self.peek().text == "}"):
                if self.peek() is None:
                    raise ALPTError("unclosed '{'", t.line)
                key = self.term()
                if isinstance(key, (list, dict)):
                    raise ALPTError("map key must be scalar", t.line)
                d[key] = self.term()
            self.next()
            return d
        raise ALPTError(f"unexpected {s!r}", t.line)

    # -- compositions ----------------------------------------------------------
    def comp_record(self, comp_tok: _Tok) -> Composition:
        """After ``!sid``: parse the composition, optional ``= "gloss"``, verify SID."""
        claimed = self._hash(comp_tok.text[1:], None, comp_tok)
        comp = self.comp()
        gloss = None
        p = self.peek()
        if p and p.kind == "punct" and p.text == "=":
            self.next()
            gloss = unquote(self.expect("str").text)
        comp = comp.with_gloss(gloss)
        if self.strict_sid:
            try:
                verify_comp(comp, claimed)
            except SIDMismatch as e:
                raise ALPTError(f"E_SID_MISMATCH: {e}", comp_tok.line) from None
        return comp

    def node(self) -> Any:
        t = self.next()
        if t.kind == "prim":
            return inv.pid(t.text[1:])
        if t.kind in ("sid", "sidfull"):
            hexstr = t.text.lstrip("#")
            b = self._hash(hexstr, None, t)
            if len(b) != HASH_LEN:
                raise ALPTError("SID references inside compositions must be full 32 bytes", t.line)
            return b
        if t.kind == "punct" and t.text == "(":
            c = self.comp()
            self.expect("punct", ")")
            return c
        raise ALPTError(f"expected a node, got {t.text!r}", t.line)

    def comp(self) -> Composition:
        t = self.expect("prim")
        head = inv.pid(t.text[1:])
        mods: set = set()
        roles: dict[int, Any] = {}
        residue = None
        supersedes = None
        while True:
            p = self.peek()
            if p is None:
                break
            if p.kind == "mod":
                self.next()
                mods.add(inv.pid(p.text[1:]))
            elif p.kind == "punct" and p.text == ".":
                self.next()
                mods.add(self.node())
            elif p.kind == "role":
                self.next()
                code = inv.role_code(p.text[1:])
                roles[code] = self.node()
            elif p.kind == "punct" and p.text == "~":
                self.next()
                residue = unquote(self.expect("str").text)
            elif p.kind == "punct" and p.text == "^":
                self.next()
                st = self.next()
                if st.kind not in ("sid", "sidfull"):
                    raise ALPTError("^ must be followed by #sid", st.line)
                supersedes = self._hash(st.text.lstrip("#"), HASH_LEN, st)
            else:
                break
        try:
            return Composition(head, frozenset(mods), tuple(roles.items()), residue, supersedes)
        except ValueError as e:
            raise ALPTError(str(e), t.line) from None


# ---------------------------------------------------------------------------
# Document parser
# ---------------------------------------------------------------------------

@dataclass
class Document:
    stream: Stream
    symbols: list[Composition] = field(default_factory=list)   # standalone ! blocks
    notes: dict[bytes, str] = field(default_factory=dict)


_ISO = "%Y-%m-%dT%H:%M:%SZ"


def _parse_time(s: str, line: int) -> int:
    try:
        return calendar.timegm(time.strptime(s, _ISO))
    except ValueError:
        raise ALPTError(f"bad timestamp {s!r}", line) from None


def loads(text: str, strict_sid: bool = True) -> Document:
    lines = text.splitlines()
    if not lines or not lines[0].startswith("%alp/t"):
        raise ALPTError("missing %alp/t header", 1)
    hdr = lines[0].split()
    if len(hdr) < 2 or hdr[1] != str(PROTOCOL_VERSION):
        raise ALPTError(f"E_VERSION: unsupported ALP/T version {hdr[1:2]}", 1)
    opts: dict[str, str] = {}
    rest = hdr[2:]
    for i in range(0, len(rest) - 1, 2):
        opts[rest[i]] = rest[i + 1]
    if opts.get("inv", str(INVENTORY_VERSION)) != str(INVENTORY_VERSION):
        raise ALPTError(f"E_INVENTORY: inventory {opts.get('inv')} != {INVENTORY_VERSION}", 1)
    width: int | None = None
    if "profile" in opts:
        if opts["profile"] not in PROFILE_BY_NAME:
            raise ALPTError(f"E_PROFILE: unknown profile {opts['profile']}", 1)
        width = PROFILE_BY_NAME[opts["profile"]]
    stream_id = bytes.fromhex(opts["stream"]) if "stream" in opts else None

    # group into blocks
    blocks: list[list[tuple[int, str]]] = []
    cur: list[tuple[int, str]] = []
    pending_notes: list[str] = []
    for n, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "":
            if cur:
                blocks.append(cur)
                cur = []
            continue
        if raw.lstrip().startswith(";"):
            if not cur:
                pending_notes.append(raw.lstrip()[1:].strip())
            continue
        if raw[0] in "@!" and cur:
            blocks.append(cur)
            cur = []
        if raw[0] in "@!" and pending_notes:
            cur.append((-1, "\n".join(pending_notes)))
            pending_notes = []
        cur.append((n, raw))
    if cur:
        blocks.append(cur)

    # infer width from the first event hash if the header did not say
    if width is None:
        for b in blocks:
            for _, raw in b:
                if raw.startswith("@"):
                    h = raw[1:].split()[0]
                    if len(h) // 2 in PROFILE_CODES:
                        width = len(h) // 2
                    break
            if width:
                break
    if width is None:
        width = HASH_LEN

    stream = Stream(stream_id, width)
    doc = Document(stream)
    for b in blocks:
        note = None
        if b and b[0][0] == -1:
            note = b[0][1]
            b = b[1:]
        n0, first = b[0]
        if first.startswith("!"):
            toks = []
            for n, raw in b:
                toks += tokenize(raw, n)
            tp = TermParser(toks, width, strict_sid)
            comp_tok = tp.expect("comp")
            comp = tp.comp_record(comp_tok)
            if not tp.at_end():
                raise ALPTError("trailing tokens after symbol block", n0)
            doc.symbols.append(comp)
            stream.state.lexicon.setdefault(comp.sid, comp)
        elif first.startswith("@"):
            ev, author_name = _parse_event(b, width, strict_sid, stream.stream_id)
            if author_name:
                stream.authors[ev.author] = author_name
            if ev.stream_id != stream.stream_id:
                if stream_id is None and not stream.events:
                    stream.stream_id = ev.stream_id
                else:
                    raise ALPTError("event belongs to a different stream", n0)
            stream.add(ev)
            if note:
                doc.notes[ev.eid] = note
        else:
            raise ALPTError(f"expected '@' or '!' block, got {first!r}", n0)
    return doc


def _parse_event(block: list[tuple[int, str]], width: int, strict_sid: bool, default_stream: bytes) -> tuple[Event, str | None]:
    n0, first = block[0]
    parts = first[1:].split()
    if len(parts) < 2:
        raise ALPTError("event header needs '@eid TYPE'", n0)
    eid_hex, type_name = parts[0], parts[1]
    try:
        etype = EventType[type_name.upper()]
    except KeyError:
        raise ALPTError(f"unknown event type {type_name}", n0) from None
    parents: list[bytes] = []
    author = None
    author_name = None
    ts = None
    flags = 0
    sig = None
    body: list[tuple[int, str]] = []
    stream_id = None
    for n, raw in block[1:]:
        if raw.startswith("<-"):
            parents = [bytes.fromhex(h) for h in raw[2:].split()]
        elif raw.startswith("by "):
            tok = raw[3:].split()[0]
            if not tok.startswith("#"):
                raise ALPTError("'by' needs #sid", n)
            author = bytes.fromhex(tok[1:])
            if ";" in raw:
                author_name = raw.split(";", 1)[1].strip() or None
        elif raw.startswith("at "):
            ts = _parse_time(raw[3:].split()[0], n)
        elif raw.startswith("fl "):
            flags = int(raw[3:].split()[0], 0)
        elif raw.startswith("in "):
            stream_id = bytes.fromhex(raw[3:].split()[0])
        elif raw.startswith("sig "):
            s = raw[4:].strip()
            sig = bytes.fromhex(s[2:] if s.startswith("0x") else s)
        elif raw.startswith((" ", "\t")):
            body.append((n, raw))
        else:
            raise ALPTError(f"unexpected line {raw!r}", n)
    if author is None:
        raise ALPTError("event lacks 'by' line", n0)
    if ts is None:
        raise ALPTError("event lacks 'at' line", n0)

    payload = _parse_payload(etype, body, width, strict_sid, n0)
    ev = Event(
        type=etype, author=author, payload=payload, parents=tuple(parents),
        timestamp=ts, stream_id=stream_id if stream_id is not None else default_stream,
        flags=flags, signature=sig, sid_width=width,
    )
    claimed = bytes.fromhex(eid_hex)
    if not ev.eid.startswith(claimed):
        raise ALPTError(
            f"EID mismatch: header says {eid_hex[:16]}…, body hashes to {ev.eid_hex(16)}…", n0
        )
    return ev, author_name


def _parse_payload(etype: EventType, body: list[tuple[int, str]], width: int, strict_sid: bool, n0: int) -> Any:
    if not body:
        return [] if etype in LIST_PAYLOAD else {}
    # escape hatch: single raw term
    if body[0][1].strip().startswith(">"):
        toks = []
        for n, raw in body:
            toks += tokenize(raw.replace(">", " ", 1), n)
        tp = TermParser(toks, width, strict_sid)
        v = tp.term()
        if not tp.at_end():
            raise ALPTError("trailing tokens in raw payload", n0)
        return v
    if etype in LIST_PAYLOAD:
        items: list[Any] = []
        toks: list[_Tok] = []
        for n, raw in body:
            toks += tokenize(raw, n)
        tp = TermParser(toks, width, strict_sid)
        while not tp.at_end():
            items.append(tp.term())
        return items
    # MAP payload: "key term" per line, where a term may continue onto
    # following lines that start with a composition/gloss continuation.
    result: dict[str, Any] = {}
    i = 0
    while i < len(body):
        n, raw = body[i]
        stripped = raw.strip()
        m = _KEY.match(stripped)
        if not m:
            raise ALPTError(f"expected 'key term', got {stripped!r}", n)
        key = m.group(0)
        toks = tokenize(stripped[m.end():], n)
        # gather continuation lines (those starting with '=' gloss or '!' records inside parens)
        j = i + 1
        depth = sum(1 for t in toks if t.kind == "punct" and t.text in "({") - \
            sum(1 for t in toks if t.kind == "punct" and t.text in ")}")
        while depth > 0 and j < len(body):
            more = tokenize(body[j][1], body[j][0])
            toks += more
            depth += sum(1 for t in more if t.kind == "punct" and t.text in "({") - \
                sum(1 for t in more if t.kind == "punct" and t.text in ")}")
            j += 1
        tp = TermParser(toks, width, strict_sid)
        result[key] = tp.term()
        if not tp.at_end():
            raise ALPTError(f"trailing tokens after value for {key}", n)
        i = j
    return result


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def parse_composition(text: str, strict_sid: bool = True) -> Composition:
    """Parse ``$HEAD...`` or ``!sid $HEAD... [= "gloss"]`` from a string."""
    toks = tokenize(text, 1)
    tp = TermParser(toks, HASH_LEN, strict_sid)
    if toks and toks[0].kind == "comp":
        c = tp.comp_record(tp.next())
    else:
        c = tp.comp()
        p = tp.peek()
        if p and p.kind == "punct" and p.text == "=":
            tp.next()
            c = c.with_gloss(unquote(tp.expect("str").text))
    if not tp.at_end():
        raise ALPTError(f"trailing tokens: {tp.peek().text!r}", 1)
    return c
