"""Composition Records, canonical form, SIDs and the ALP/T composition syntax
(RFC-ALP-001 v1.1 §3, §5, §7.6).

    SID = SHA-256( canonical_ALP/B( CompositionRecord \\ gloss ) )

Record keys: h head (PID), r roles MAP<u8,Node>, m modifiers SET<Node>,
s supersedes (full SID ref), g gloss (excluded from hash), x residue (text,
included in hash).  A Node is a PID, a nested record, or a SID reference.

Transliteration (§7.6, normative fallback for the script):

    $HEAD.MOD.MOD :ROLE $PRIM :ROLE (nested comp) :ROLE #sid ~"residue"
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Iterator, Union

from . import alpb
from .alpb import Pid, Ref, REF_SID_FULL, REF_SID
from . import inventory as inv
from .inventory import (
    CLASS_ONTOLOGICAL, CLASS_STRUCTURAL, MAX_DEPTH, MAX_MODIFIERS, ROLES, ROLE_NAMES,
)


class CompositionError(ValueError):
    code = "E_MALFORMED"


class DepthError(CompositionError):
    code = "E_DEPTH"


class CycleError(CompositionError):
    code = "E_CYCLE"


class SIDMismatch(ValueError):
    """E_SID_MISMATCH: a supplied composition does not hash to the claimed SID."""


Node = Union[Pid, "Composition", bytes]   # bytes = full 32-byte SID reference


def _node_key(n: Node) -> bytes:
    """Canonical encoded bytes of a node, used to sort the modifier set."""
    return alpb.encode(_node_value(n))


def _node_value(n: Node) -> Any:
    if isinstance(n, Pid):
        return n
    if isinstance(n, Composition):
        return n.to_map(include_gloss=False)
    if isinstance(n, (bytes, bytearray)):
        return Ref(REF_SID_FULL, bytes(n))
    raise TypeError(f"bad node {type(n).__name__}")


def _node_from_value(v: Any) -> Node:
    if isinstance(v, Pid):
        return v
    if isinstance(v, dict):
        return Composition.from_map(v)
    if isinstance(v, Ref):
        return v.data
    raise CompositionError(f"bad node value {type(v).__name__}")


@dataclass(frozen=True)
class Composition:
    head: Pid
    modifiers: frozenset[Node] = frozenset()
    roles: tuple[tuple[int, Node], ...] = ()      # sorted by role code
    residue: str | None = None
    supersedes: bytes | None = None
    gloss: str | None = None                       # advisory, not hashed

    # -- construction ---------------------------------------------------------
    def __post_init__(self) -> None:
        # normalise inputs so equality/hash behave
        mods = frozenset(self.modifiers)
        roles = tuple(sorted(((int(c), n) for c, n in dict(self.roles).items()), key=lambda cn: cn[0]))
        object.__setattr__(self, "modifiers", mods)
        object.__setattr__(self, "roles", roles)
        if self.residue is not None:
            object.__setattr__(self, "residue", alpb.nfc(self.residue))
        if self.gloss is not None:
            object.__setattr__(self, "gloss", alpb.nfc(self.gloss))
        self.validate()

    @classmethod
    def build(
        cls,
        head: str | Pid,
        *modifiers: str | Pid | Node,
        roles: dict[str | int, Node | str] | None = None,
        residue: str | None = None,
        supersedes: bytes | None = None,
        gloss: str | None = None,
    ) -> "Composition":
        """Friendly constructor accepting primitive names."""
        def as_node(x: Any) -> Node:
            if isinstance(x, str):
                return inv.pid(x)
            return x
        h = inv.pid(head) if isinstance(head, str) else head
        mods = frozenset(as_node(m) for m in modifiers)
        rs = {inv.role_code(k): as_node(v) for k, v in (roles or {}).items()}
        return cls(h, mods, tuple(rs.items()), residue, supersedes, gloss)

    def with_gloss(self, gloss: str | None) -> "Composition":
        return Composition(self.head, self.modifiers, self.roles, self.residue, self.supersedes, gloss)

    # -- validation (§5.1) ------------------------------------------------------
    def validate(self, depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            raise DepthError(f"E_DEPTH: nesting exceeds {MAX_DEPTH}")
        if not isinstance(self.head, Pid):
            raise CompositionError("E_MALFORMED: head must be a PID")
        if self.head.cls != CLASS_ONTOLOGICAL:
            raise CompositionError(
                f"E_MALFORMED: head must be ontological, got ${inv.name_of(self.head)}"
            )
        if len(self.modifiers) > MAX_MODIFIERS:
            raise DepthError(f"E_DEPTH: {len(self.modifiers)} modifiers exceeds {MAX_MODIFIERS}")
        for m in self.modifiers:
            if isinstance(m, Pid) and m.cls == CLASS_STRUCTURAL:
                raise CompositionError(f"E_MALFORMED: structural primitive as modifier: ${inv.name_of(m)}")
            if isinstance(m, Composition):
                m.validate(depth + 1)
        for code, node in self.roles:
            if code not in ROLE_NAMES:
                raise CompositionError(f"E_MALFORMED: unknown role code {code}")
            if isinstance(node, Composition):
                node.validate(depth + 1)
            elif isinstance(node, Pid):
                if node.cls == CLASS_STRUCTURAL:
                    raise CompositionError("E_MALFORMED: structural primitive as role filler")
            elif isinstance(node, (bytes, bytearray)):
                if len(node) != 32:
                    raise CompositionError("E_MALFORMED: SID reference must be 32 bytes")
            else:
                raise CompositionError(f"E_MALFORMED: bad role node {type(node).__name__}")
        # Cycles are structurally impossible: a nested record is a value, and a
        # SID reference cannot name a record that contains it (§5.1 rule 5).
        # We still guard against the one thing Python allows — an identical
        # object nested inside itself — which would otherwise recurse forever.
        for _ in self._walk(seen=(id(self),)):
            pass

    def _walk(self, seen: tuple[int, ...] = ()) -> Iterator["Composition"]:
        for child in self.children():
            if isinstance(child, Composition):
                if id(child) in seen:
                    raise CycleError("E_CYCLE: composition contains itself")
                yield child
                yield from child._walk(seen + (id(child),))

    def children(self) -> list[Node]:
        return [m for m in self.modifiers] + [n for _, n in self.roles]

    # -- canonical form (§3.3) --------------------------------------------------
    def to_map(self, include_gloss: bool = True) -> dict[str, Any]:
        m: dict[str, Any] = {"h": self.head}
        if self.modifiers:
            vals = [_node_value(x) for x in self.modifiers]
            vals.sort(key=alpb.encode)
            m["m"] = vals
        if self.roles:
            m["r"] = {code: _node_value(n) for code, n in self.roles}
        if self.supersedes is not None:
            m["s"] = Ref(REF_SID_FULL, self.supersedes)
        if self.residue is not None:
            m["x"] = self.residue
        if include_gloss and self.gloss is not None:
            m["g"] = self.gloss
        return m

    @classmethod
    def from_map(cls, m: dict[str, Any]) -> "Composition":
        if not isinstance(m, dict) or "h" not in m:
            raise CompositionError("E_MALFORMED: composition record needs a head")
        head = m["h"]
        if not isinstance(head, Pid):
            raise CompositionError("E_MALFORMED: head is not a PID")
        mods = frozenset(_node_from_value(x) for x in m.get("m", []))
        roles = {}
        for k, v in m.get("r", {}).items():
            if not isinstance(k, int):
                raise CompositionError("E_MALFORMED: role key is not an integer")
            roles[k] = _node_from_value(v)
        sup = m.get("s")
        if sup is not None:
            if not isinstance(sup, Ref) or not sup.is_sid:
                raise CompositionError("E_MALFORMED: supersedes is not a SID ref")
            sup = sup.data
        return cls(head, mods, tuple(roles.items()), m.get("x"), sup, m.get("g"))

    def canonical(self) -> bytes:
        """Canonical ALP/B bytes of the record with gloss stripped (the hash preimage)."""
        return alpb.encode(self.to_map(include_gloss=False))

    def transport(self) -> bytes:
        """Canonical ALP/B including gloss (allowed in transport, §3.3 rule 5)."""
        return alpb.encode(self.to_map(include_gloss=True))

    @property
    def sid(self) -> bytes:
        return hashlib.sha256(self.canonical()).digest()

    def sid_hex(self, width: int | None = None) -> str:
        h = self.sid.hex()
        return h if width is None else h[:width]

    def ref(self) -> Ref:
        return Ref(REF_SID, self.sid)

    # -- primitives used -------------------------------------------------------
    def primitives(self) -> list[Pid]:
        """Canonical linear primitive sequence (head, modifiers, roles) for the script."""
        seq = [self.head]
        for m in sorted(self.modifiers, key=_node_key):
            if isinstance(m, Pid):
                seq.append(m)
            else:
                seq += [inv.pid("SCOPE_OPEN"), *m.primitives(), inv.pid("SCOPE_CLOSE")]
        for _, n in self.roles:
            if isinstance(n, Pid):
                seq.append(n)
            elif isinstance(n, Composition):
                seq += [inv.pid("SCOPE_OPEN"), *n.primitives(), inv.pid("SCOPE_CLOSE")]
            else:
                seq.append(inv.pid("REF"))
        if self.residue is not None:
            seq.append(inv.pid("RESIDUE"))
        return seq

    def script(self) -> str:
        """PUA script string (§6.3)."""
        return inv.script_text(self.primitives())

    def residue_bearing(self) -> bool:
        if self.residue is not None:
            return True
        return any(c.residue_bearing() for c in self.children() if isinstance(c, Composition))

    # -- transliteration (§7.6) --------------------------------------------------
    def transliterate(self, sid_width: int | None = None) -> str:
        out = "$" + inv.name_of(self.head)
        for m in sorted(self.modifiers, key=_node_key):
            if isinstance(m, Pid):
                out += "." + inv.name_of(m)
            else:
                out += ".(" + _render_node(m, sid_width) + ")"
        for code, node in self.roles:
            out += f" :{ROLE_NAMES[code]} " + _render_node(node, sid_width)
        if self.residue is not None:
            out += " ~" + quote(self.residue)
        return out

    def reading(self) -> str:
        """A generated English reading of the composition (hydration, §8.3).

        This is derived surface form.  It is not authoritative and must never
        re-enter the stream (§8.3).
        """
        return read_composition(self)

    def __str__(self) -> str:
        return self.transliterate()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Composition {self.sid_hex(8)} {self.transliterate(8)}>"


def _render_node(node: Node, sid_width: int | None) -> str:
    if isinstance(node, Composition):
        return "(" + node.transliterate(sid_width) + ")"
    if isinstance(node, Pid):
        return "$" + inv.name_of(node)
    h = bytes(node).hex()
    return "#" + (h if sid_width is None else h[:sid_width])


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def verify(comp: Composition, claimed_sid: bytes) -> None:
    """Raise SIDMismatch unless ``comp`` hashes to ``claimed_sid`` (a prefix is accepted)."""
    if not comp.sid.startswith(bytes(claimed_sid)):
        raise SIDMismatch(
            f"composition {comp.transliterate(8)} hashes to {comp.sid_hex(16)}…, "
            f"not {bytes(claimed_sid).hex()[:16]}…"
        )


# ---------------------------------------------------------------------------
# Parser for the transliteration syntax
# ---------------------------------------------------------------------------

_TOKEN = re.compile(
    r"""\s*(?:
        (?P<prim>\$[A-Za-z_][A-Za-z0-9_]*)
      | (?P<mod>\.[A-Za-z_][A-Za-z0-9_]*)
      | (?P<role>:[A-Za-z_][A-Za-z0-9_]*)
      | (?P<sid>\#[0-9A-Fa-f]+)
      | (?P<str>"(?:[^"\\]|\\.)*")
      | (?P<punct>[().~^])
    )""",
    re.VERBOSE,
)


def unquote(tok: str) -> str:
    body = tok[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


class _Parser:
    def __init__(self, text: str, resolve=None) -> None:
        self.toks: list[tuple[str, str]] = []
        pos = 0
        text = text.strip()
        while pos < len(text):
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos:
                raise CompositionError(f"cannot parse composition at: {text[pos:pos+20]!r}")
            pos = m.end()
            kind = m.lastgroup
            self.toks.append((kind, m.group(kind)))
        self.i = 0
        self.resolve = resolve

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def next(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise CompositionError("unexpected end of composition")
        self.i += 1
        return t

    def sid(self, tok: str) -> bytes:
        raw = tok[1:]
        if len(raw) % 2:
            raise CompositionError(f"odd-length SID {tok}")
        b = bytes.fromhex(raw)
        if len(b) < 32:
            if self.resolve is None:
                raise CompositionError(f"truncated SID {tok} cannot be resolved without a lexicon")
            full = self.resolve(b)
            if full is None:
                raise CompositionError(f"unresolvable SID {tok}")
            return full
        return b

    def node(self) -> Node:
        kind, val = self.next()
        if kind == "prim":
            return inv.pid(val[1:])
        if kind == "sid":
            return self.sid(val)
        if kind == "punct" and val == "(":
            c = self.comp()
            k, v = self.next()
            if (k, v) != ("punct", ")"):
                raise CompositionError("expected ')'")
            return c
        raise CompositionError(f"unexpected {val!r} where a node was expected")

    def comp(self) -> Composition:
        kind, val = self.next()
        if kind != "prim":
            raise CompositionError(f"composition must start with $HEAD, got {val!r}")
        head = inv.pid(val[1:])
        mods: set[Node] = set()
        roles: dict[int, Node] = {}
        residue = None
        supersedes = None
        while True:
            t = self.peek()
            if t is None or t == ("punct", ")"):
                break
            kind, val = t
            if kind == "mod":
                self.i += 1
                mods.add(inv.pid(val[1:]))
            elif kind == "punct" and val == ".":
                # ".(" nested modifier composition
                self.i += 1
                mods.add(self.node())
            elif kind == "role":
                self.i += 1
                code = inv.role_code(val[1:])
                if code in roles:
                    raise CompositionError(f"duplicate role {val}")
                roles[code] = self.node()
            elif kind == "punct" and val == "~":
                self.i += 1
                k, v = self.next()
                if k != "str":
                    raise CompositionError("residue must be a quoted string")
                residue = unquote(v)
            elif kind == "punct" and val == "^":
                self.i += 1
                k, v = self.next()
                if k != "sid":
                    raise CompositionError("supersedes must be #sid")
                supersedes = self.sid(v)
            else:
                raise CompositionError(f"unexpected {val!r} in composition")
        return Composition(head, frozenset(mods), tuple(roles.items()), residue, supersedes)


def parse(text: str, resolve=None) -> Composition:
    """Parse the ALP/T composition syntax.

    ``resolve(prefix_bytes) -> full_sid | None`` is used to expand truncated
    ``#sid`` references (as they appear in human-written examples).  Archived
    ALP/T always carries full SIDs and needs no resolver.
    """
    p = _Parser(text, resolve)
    c = p.comp()
    if p.peek() is not None:
        raise CompositionError(f"trailing tokens after composition: {p.peek()[1]!r}")
    return c


# ---------------------------------------------------------------------------
# English reading (hydration)
# ---------------------------------------------------------------------------

_HEAD_NOUN = {
    "ENTITY": "a thing", "PROCESS": "a process", "PROPERTY": "a property",
    "RELATION": "a relation", "QUANTITY": "a quantity", "AGENT": "an agent",
    "STATE": "a state", "PLACE": "a place", "MOMENT": "a moment",
    "SIGN": "a signal", "EVENT": "an event", "GROUP": "a group",
}

_MOD_PHRASE = {
    "AFFIRM": "affirmed", "NEGATE": "negated (not holding)", "POSSIBLE": "possible",
    "NECESSARY": "necessary", "DESIRED": "desired", "HYPOTHETICAL": "hypothetical",
    "PERMITTED": "permitted", "FORBIDDEN": "forbidden",
    "NONE": "zero", "SOME": "partial", "ALL": "total", "LOW": "low", "MID": "middling",
    "HIGH": "high", "EXTREME": "at the limit", "BOUNDED": "bounded", "UNBOUNDED": "unbounded",
    "INCREASE": "rising", "DECREASE": "falling",
    "PAST": "in the past", "NOW": "at present", "FUTURE": "in the future",
    "DURATIVE": "extended in time", "PUNCTUAL": "instantaneous", "BEFORE": "before a reference",
    "DURING": "during a reference", "AFTER": "after a reference", "REPEAT": "recurring",
    "BEGIN": "beginning", "END": "ending",
    "CAUSE": "causing", "ENABLE": "enabling", "PREVENT": "preventing",
    "CORRELATE": "correlated", "DEPEND": "dependent", "TRIGGER": "triggering",
    "KNOWN": "known", "BELIEVED": "believed", "INFERRED": "inferred", "UNKNOWN": "unknown",
    "CONTESTED": "contested", "OBSERVED": "observed", "PREDICTED": "predicted",
    "ASSERT": "asserted", "REQUEST": "requested", "COMMIT": "committed to",
    "QUERY": "queried", "WARN": "warned about", "REFUSE": "refused",
    "PROPOSE": "proposed", "ACKNOWLEDGE": "acknowledged",
    "GOOD": "good", "BAD": "bad", "REQUIRED": "required", "OPTIONAL": "optional",
    "SAFE": "safe", "HARM": "harmful", "COST": "costly", "BENEFIT": "beneficial",
    "EQUAL": "equal to", "GREATER": "greater than", "LESS": "less than", "PART": "part of",
    "HAS": "having", "MEMBER": "a member of", "NEAR": "near", "INSIDE": "inside", "OUTSIDE": "outside",
    "ABOVE": "above", "BELOW": "below", "TOWARD": "toward",
    "SELF": "I/we", "ADDRESSEE": "you", "THIS": "this", "THAT": "that", "WHICH": "which?",
    "SAME": "the same one", "OTHER": "another", "EACH": "each", "ANY": "any", "GENERIC": "in general",
    "AND": "and", "OR": "or", "XOR": "either-or", "IFF": "if and only if", "IMPLIES": "implying",
    "ONLY": "only", "EXCEPT": "except",
    "JOY": "glad", "FEAR": "afraid", "ANGER": "angry", "TRUST": "trusting", "SURPRISE": "surprised",
    "DISGUST": "disgusted", "SADNESS": "sad", "CALM": "calm",
    "NUM": "(number)", "STR": "(name)", "TIME": "(time)", "UNIT": "(unit)", "EREF": "(earlier utterance)",
}

_ROLE_PHRASE = {
    "ARG0": "whose agent is", "ARG1": "whose patient is", "ARG2": "whose instrument is",
    "SCOPE": "over", "MEASURE": "measured by", "CONDITION": "given",
    "LOC": "at", "TIME": "when", "MANNER": "by means of", "PURPOSE": "for", "SOURCE": "from", "GOAL": "to",
}

_CLASS_ORDER = [inv.CLASS_DEICTIC, inv.CLASS_EPISTEMIC, inv.CLASS_MODAL, inv.CLASS_LOGICAL, inv.CLASS_SCALAR,
                inv.CLASS_TEMPORAL, inv.CLASS_CAUSAL, inv.CLASS_RELATIONAL, inv.CLASS_VALENCE,
                inv.CLASS_AFFECT, inv.CLASS_ILLOCUTIONARY]


def read_node(n: Node, label=None) -> str:
    if isinstance(n, Pid):
        return _HEAD_NOUN.get(inv.name_of(n), inv.name_of(n).lower()) if n.cls == CLASS_ONTOLOGICAL \
            else _MOD_PHRASE.get(inv.name_of(n), inv.name_of(n).lower())
    if isinstance(n, Composition):
        return "(" + read_composition(n, label) + ")"
    if label:
        text = label(bytes(n))
        if text:
            return f"the symbol “{text}”"
    return f"symbol #{bytes(n).hex()[:8]}"


def read_composition(c: Composition, label=None) -> str:
    """English rendering. ``label(sid)->str|None`` supplies glosses for SID refs."""
    parts = [_HEAD_NOUN.get(inv.name_of(c.head), "a thing")]
    pid_mods = sorted((m for m in c.modifiers if isinstance(m, Pid)), key=lambda p: (_CLASS_ORDER.index(p.cls) if p.cls in _CLASS_ORDER else 99, p.code))
    words = [_MOD_PHRASE.get(inv.name_of(m), inv.name_of(m).lower()) for m in pid_mods]
    words += [read_node(m, label) for m in c.modifiers if isinstance(m, Composition)]
    if words:
        parts.append("that is " + ", ".join(words))
    for code, node in c.roles:
        parts.append(f"{_ROLE_PHRASE[ROLE_NAMES[code]]} {read_node(node, label)}")
    if c.residue:
        parts.append(f"— “{c.residue}”")
    text = " ".join(parts)
    if c.gloss:
        text += f' [gloss: "{c.gloss}"]'
    return text
