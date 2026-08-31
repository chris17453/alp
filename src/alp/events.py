"""Events, frames, streams and the stateless fold (RFC-ALP-001 v1.1 §7).

Frame layout (§7.5)::

    stream := frame*
    frame  := length:uvarint body:bytes[length]
    body   := version:u8 type:u8 flags:u8
              stream_id:REF(EID) parents:LIST<REF(EID)> timestamp:UINT
              author:REF(SID) payload:<type-specific> [signature:BYTES]
    EID    := SHA-256( canonical_ALP/B( body ) )   ; signature excluded

``version``, ``type`` and ``flags`` are single raw bytes; every other field is
one canonical ALP/B value, concatenated.

A stream has one truncation profile (§3.5), fixed at CHECKPOINT.  Header
references are emitted as profile-width refs (REF kinds 0/1) and the EID is
the hash of the body *as transmitted*, so a receiver can verify EIDs without
holding any state.  Changing profile therefore changes EIDs; ``Stream.
reprofile`` performs that re-hash explicitly (e.g. SID-128 transport ->
SID-256 archive, as §3.5 requires for storage).

Payload conventions (1.1 §7.1 / 1.0 Appendix B), as ALP/B values:

    JOIN        {"competence": [PID|SID...], "caps": {...}}
    LEAVE       {"reason": text}
    ASSERT      [[SID, value], ...]
    AMEND       [CompositionRecord map, ...]
    EXPAND      {"unknown": [SID...]}
    GROUND      [CompositionRecord map, ...]
    REGROUND    {"subject": SID, "evidence": [EID...], "reading": text, "proposal"?: SID}
    ACQUIRE     {"offer": [PID|SID...], "challenge"?: [[SID, value]...]}
    ATTEST      [[PID|SID, level], ...]
    CHECKPOINT  {"covers","hash_alg","sid_profile","inventory_ver","lexicon","comps"?,"state","digest"}
    ERROR       {"code": u8, "subject"?: REF, "detail": text}
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Iterable, Iterator

from . import alpb
from .alpb import Pid, Ref, REF_SID, REF_EID, HASH_LEN
from .composition import Composition
from .inventory import INVENTORY_VERSION, PROTOCOL_VERSION


class EventType(IntEnum):
    JOIN = 0x01
    LEAVE = 0x02
    ASSERT = 0x03
    AMEND = 0x04
    EXPAND = 0x05
    GROUND = 0x06
    REGROUND = 0x07
    ACQUIRE = 0x08
    ATTEST = 0x09
    CHECKPOINT = 0x0A
    ERROR = 0x0B


class Flag(IntEnum):
    SIGNED = 0x01
    CHECKPOINT_REF = 0x02
    EPHEMERAL = 0x04
    HYDRATE_HINT = 0x08


class AttestLevel(IntEnum):
    HELD = 0x01
    DEMONSTRATED = 0x02
    DECLINED = 0x03


class ErrorCode(IntEnum):
    E_VERSION = 0x01
    E_NONCANONICAL = 0x02
    E_SID_MISMATCH = 0x03
    E_UNKNOWN_PARENT = 0x04
    E_LEXICON_FULL = 0x05
    E_RATE = 0x06
    E_DIVERGENCE = 0x07
    E_PROFILE = 0x08
    E_DEPTH = 0x09
    E_CYCLE = 0x0A
    E_INVENTORY = 0x0B


PROFILE_CODES = {32: 0x00, 16: 0x01, 12: 0x02, 8: 0x03}
PROFILE_WIDTHS = {v: k for k, v in PROFILE_CODES.items()}
PROFILE_NAMES = {32: "SID-256", 16: "SID-128", 12: "SID-96", 8: "SID-64"}
PROFILE_BY_NAME = {v: k for k, v in PROFILE_NAMES.items()}
HASH_ALG_SHA256 = 0x01


class StreamError(ValueError):
    pass


def sha256(b: bytes) -> bytes:
    return hashlib.sha256(b).digest()


def agent_symbol(name: str) -> Composition:
    """``$AGENT ~"name"`` — authors are SIDs (§7.5), so an author is a symbol."""
    return Composition.build("AGENT", residue=name, gloss=f"agent {name}")


def agent_sid(name: str) -> bytes:
    return agent_symbol(name).sid


def new_stream_id(seed: str | bytes | None = None) -> bytes:
    """A stream id is an EID-shaped 32-byte value; random unless seeded."""
    if seed is None:
        return os.urandom(HASH_LEN)
    if isinstance(seed, str):
        seed = seed.encode("utf-8")
    return sha256(b"alp-stream:" + seed)


def _trunc(v: Any, width: int) -> Any:
    """Truncate profile-width refs in a payload to ``width`` bytes."""
    if isinstance(v, Ref):
        if v.kind in (REF_SID, REF_EID) and len(v.data) > width:
            return Ref(v.kind, v.data[:width])
        return v
    if isinstance(v, list):
        return [_trunc(x, width) for x in v]
    if isinstance(v, dict):
        return {_trunc(k, width): _trunc(x, width) for k, x in v.items()}
    return v


def iter_refs(v: Any) -> Iterator[Ref]:
    if isinstance(v, Ref):
        yield v
    elif isinstance(v, list):
        for x in v:
            yield from iter_refs(x)
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from iter_refs(k)
            yield from iter_refs(x)


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    type: EventType
    author: bytes                       # SID, profile width
    payload: Any                        # ALP/B value
    parents: tuple[bytes, ...] = ()     # EIDs, profile width
    timestamp: int = 0
    stream_id: bytes = b"\x00" * HASH_LEN
    flags: int = 0
    version: int = PROTOCOL_VERSION
    signature: bytes | None = None
    sid_width: int = HASH_LEN           # the stream's truncation profile

    def __post_init__(self) -> None:
        w = self.sid_width
        if w not in PROFILE_CODES:
            raise StreamError(f"E_PROFILE: bad width {w}")
        object.__setattr__(self, "type", EventType(self.type))
        object.__setattr__(self, "author", bytes(self.author)[:w])
        object.__setattr__(self, "stream_id", bytes(self.stream_id)[:w])
        object.__setattr__(self, "parents", tuple(bytes(p)[:w] for p in self.parents))
        object.__setattr__(self, "payload", _trunc(self.payload, w))
        if self.signature is not None and not self.flags & Flag.SIGNED:
            object.__setattr__(self, "flags", self.flags | Flag.SIGNED)
        for b, name in ((self.author, "author"), (self.stream_id, "stream_id"), *((p, "parent") for p in self.parents)):
            if len(b) != w:
                raise StreamError(f"E_PROFILE: {name} is {len(b)} bytes, profile is {w}")

    # -- encoding ------------------------------------------------------------
    def body(self) -> bytes:
        """Canonical body without signature."""
        enc = alpb.Encoder(self.sid_width)
        out = bytearray((self.version & 0xFF, int(self.type) & 0xFF, self.flags & 0xFF))
        out += enc.encode(Ref(REF_EID, self.stream_id))
        out += enc.encode([Ref(REF_EID, p) for p in self.parents])
        out += enc.encode(int(self.timestamp))
        out += enc.encode(Ref(REF_SID, self.author))
        out += enc.encode(self.payload)
        return bytes(out)

    @property
    def eid(self) -> bytes:
        return sha256(self.body())

    def eid_hex(self, width: int | None = None) -> str:
        h = self.eid.hex()
        return h if width is None else h[:width]

    @property
    def eid_ref(self) -> bytes:
        """The EID as it would appear in a parent list (profile width)."""
        return self.eid[: self.sid_width]

    def frame(self) -> bytes:
        body = self.body()
        if self.signature is not None:
            body += alpb.encode(self.signature)
        return alpb.uvarint_encode(len(body)) + body

    def signing_bytes(self) -> bytes:
        return self.body()

    # -- convenience ------------------------------------------------------------
    def compositions(self) -> list[Composition]:
        """Composition records carried by AMEND / GROUND / CHECKPOINT.comps."""
        if self.type in (EventType.AMEND, EventType.GROUND):
            return [Composition.from_map(m) for m in self.payload]
        if self.type == EventType.CHECKPOINT and isinstance(self.payload, dict):
            return [Composition.from_map(m) for m in self.payload.get("comps", [])]
        return []

    def iso_time(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.timestamp))

    def with_(self, **changes) -> "Event":
        d = dict(type=self.type, author=self.author, payload=self.payload, parents=self.parents,
                 timestamp=self.timestamp, stream_id=self.stream_id, flags=self.flags,
                 version=self.version, signature=self.signature, sid_width=self.sid_width)
        d.update(changes)
        return Event(**d)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"<Event {self.eid_hex(8)} {self.type.name}>"


# ---------------------------------------------------------------------------
# Frame decoding
# ---------------------------------------------------------------------------

def decode_body(body: bytes, sid_width: int = HASH_LEN) -> Event:
    if len(body) < 3:
        raise alpb.Truncated("frame body shorter than header")
    version, etype, flags = body[0], body[1], body[2]
    if version != PROTOCOL_VERSION:
        raise StreamError(f"E_VERSION: unsupported protocol version {version}")
    try:
        etype = EventType(etype)
    except ValueError:
        raise StreamError(f"unknown event type {etype:#x}") from None
    d = alpb.Decoder(body[3:], sid_width)
    stream_ref = d.decode()
    parents = d.decode()
    timestamp = d.decode()
    author_ref = d.decode()
    payload = d.decode()
    signature = None
    if flags & Flag.SIGNED:
        signature = d.decode()
        if not isinstance(signature, bytes):
            raise StreamError("signature must be BYTES")
    if not d.at_end():
        raise StreamError("trailing bytes in frame body")
    if not isinstance(stream_ref, Ref) or stream_ref.kind != REF_EID:
        raise StreamError("stream_id must be a profile-width EID ref")
    if not isinstance(parents, list) or not all(isinstance(p, Ref) and p.kind == REF_EID for p in parents):
        raise StreamError("parents must be a LIST of EID refs")
    if not isinstance(author_ref, Ref) or author_ref.kind != REF_SID:
        raise StreamError("author must be a profile-width SID ref")
    if not isinstance(timestamp, int) or timestamp < 0:
        raise StreamError("timestamp must be UINT")
    ev = Event(
        type=etype, author=author_ref.data, payload=payload,
        parents=tuple(p.data for p in parents), timestamp=timestamp,
        stream_id=stream_ref.data, flags=flags, version=version,
        signature=signature, sid_width=sid_width,
    )
    # Canonical-form guarantee: re-encoding must reproduce the wire bytes.
    if ev.body() != (body if signature is None else body[: len(ev.body())]):
        raise alpb.NonCanonical("frame body is not in canonical form")
    return ev


def split_frames(data: bytes) -> Iterator[bytes]:
    pos = 0
    while pos < len(data):
        n, pos = alpb.uvarint_decode(data, pos)
        if pos + n > len(data):
            raise alpb.Truncated("frame extends past end of stream")
        yield data[pos : pos + n]
        pos += n


def read_frames(data: bytes, sid_width: int = HASH_LEN) -> list[Event]:
    return [decode_body(b, sid_width) for b in split_frames(data)]


def write_frames(events: Iterable[Event]) -> bytes:
    return b"".join(e.frame() for e in events)


def sniff_profile(data: bytes) -> int | None:
    """Guess the profile of a binary stream from its first frame.

    Tries each width and returns the one whose decode is self-consistent."""
    try:
        first = next(split_frames(data))
    except StopIteration:
        return None
    for w in (32, 16, 12, 8):
        try:
            decode_body(first, w)
            return w
        except Exception:  # noqa: BLE001
            continue
    return None


# ---------------------------------------------------------------------------
# State and fold
# ---------------------------------------------------------------------------

@dataclass
class State:
    """S = (L, C, A) of §7.4."""

    lexicon: dict[bytes, Composition] = field(default_factory=dict)      # full SID -> record
    competence: dict[bytes, set] = field(default_factory=dict)          # author -> {PID | SID | (x, level)}
    assertions: dict[bytes, Any] = field(default_factory=dict)          # SID (as carried) -> value
    assertion_source: dict[bytes, bytes] = field(default_factory=dict)  # SID -> EID
    applied: set = field(default_factory=set)

    def digest(self) -> bytes:
        """Hash of the canonical materialized assertions (CHECKPOINT.digest)."""
        m = {Ref(REF_SID, k): v for k, v in sorted(self.assertions.items())}
        width = len(next(iter(self.assertions))) if self.assertions else HASH_LEN
        return sha256(alpb.encode(m, width))

    def resolve_sid(self, prefix: bytes) -> bytes | None:
        prefix = bytes(prefix)
        if prefix in self.lexicon:
            return prefix
        hits = [s for s in self.lexicon if s.startswith(prefix)]
        return hits[0] if len(hits) == 1 else None

    def symbol(self, sid: bytes) -> Composition | None:
        full = self.resolve_sid(sid)
        return self.lexicon.get(full) if full else None

    def label(self, sid: bytes) -> str | None:
        c = self.symbol(sid)
        if c is None:
            return None
        return c.gloss or c.transliterate(8)


def toposort(events: Iterable[Event]) -> list[Event]:
    """Causal partial order, ties broken by bytewise-ascending EID (§7.2)."""
    evs = list(events)
    by_eid = {e.eid: e for e in evs}
    by_ref = {e.eid_ref: e.eid for e in evs}
    indeg = {eid: 0 for eid in by_eid}
    children: dict[bytes, list[bytes]] = {eid: [] for eid in by_eid}
    for eid, e in by_eid.items():
        for p in e.parents:
            full = by_ref.get(p)
            if full is not None:
                indeg[eid] += 1
                children[full].append(eid)
    ready = sorted(eid for eid, n in indeg.items() if n == 0)
    out: list[Event] = []
    while ready:
        eid = ready.pop(0)
        out.append(by_eid[eid])
        for c in children[eid]:
            indeg[c] -= 1
            if indeg[c] == 0:
                ready.append(c)
        ready.sort()
    if len(out) != len(by_eid):
        raise StreamError("cycle in event DAG")
    return out


def apply(state: State, e: Event) -> State:
    """Idempotent fold step (§7.4)."""
    eid = e.eid
    if eid in state.applied:
        return state
    state.applied.add(eid)
    t = e.type
    if t in (EventType.AMEND, EventType.GROUND, EventType.CHECKPOINT):
        for c in e.compositions():
            state.lexicon.setdefault(c.sid, c)
    elif t == EventType.ASSERT:
        for pair in e.payload:
            sid = pair[0].data
            state.assertions[sid] = pair[1]
            state.assertion_source[sid] = eid
    elif t == EventType.JOIN:
        comp = state.competence.setdefault(e.author, set())
        for x in e.payload.get("competence", []):
            comp.add(x if isinstance(x, Pid) else x.data)
    elif t == EventType.ATTEST:
        comp = state.competence.setdefault(e.author, set())
        for item in e.payload:
            x, level = item[0], item[1]
            comp.add((x if isinstance(x, Pid) else x.data, int(level)))
    return state


def fold(events: Iterable[Event]) -> State:
    st = State()
    for e in toposort(events):
        apply(st, e)
    return st


# ---------------------------------------------------------------------------
# Stream
# ---------------------------------------------------------------------------

class Stream:
    """An append-only causal DAG with frontier tracking and a materialized fold."""

    def __init__(self, stream_id: bytes | None = None, sid_width: int = HASH_LEN) -> None:
        if sid_width not in PROFILE_CODES:
            raise StreamError(f"E_PROFILE: bad width {sid_width}")
        self.sid_width = sid_width
        self.stream_id = (stream_id if stream_id is not None else new_stream_id())[:sid_width]
        self.events: list[Event] = []
        self._index: dict[bytes, Event] = {}      # full EID -> event
        self._by_ref: dict[bytes, Event] = {}     # profile-width EID -> event
        self.frontier: list[bytes] = []           # profile-width EIDs
        self._state = State()
        self._state_n = 0                         # events folded into _state
        self._state_linear = True                 # every add extended the previous frontier
        self.authors: dict[bytes, str] = {}       # author SID -> name (tooling only)

    @property
    def profile(self) -> str:
        return PROFILE_NAMES[self.sid_width]

    @property
    def state(self) -> State:
        """The fold over all events in canonical total order (§7.2, §7.4).

        Kept incrementally while events arrive in causal order; recomputed
        from scratch once concurrency has been observed, so last-writer-wins
        always follows the EID tiebreak rather than arrival order."""
        if self._state_n == len(self.events):
            return self._state
        if self._state_linear:
            for e in self.events[self._state_n:]:
                apply(self._state, e)
        else:
            self._state = fold(self.events)
        self._state_n = len(self.events)
        return self._state

    # -- building --------------------------------------------------------------
    def add(self, event: Event) -> Event:
        if event.sid_width != self.sid_width:
            raise StreamError("E_PROFILE: event profile differs from stream profile")
        if event.eid in self._index:
            return event
        if self.frontier and set(event.parents) != set(self.frontier):
            self._state_linear = False
        self.events.append(event)
        self._index[event.eid] = event
        self._by_ref[event.eid_ref] = event
        self.frontier = [f for f in self.frontier if f not in event.parents] + [event.eid_ref]
        return event

    def author_sid(self, author: bytes | str) -> bytes:
        if isinstance(author, str):
            sid = agent_sid(author)
            self.authors[sid[: self.sid_width]] = author
            return sid
        return bytes(author)

    def emit(self, type: EventType | str, author: bytes | str, payload: Any,
             parents: Iterable[bytes] | None = None, timestamp: int | None = None,
             flags: int = 0) -> Event:
        """Create an event on the current frontier (or explicit parents) and append it."""
        if isinstance(type, str):
            type = EventType[type.upper()]
        ev = Event(
            type=type, author=self.author_sid(author), payload=payload,
            parents=tuple(self.frontier if parents is None else parents),
            timestamp=int(time.time()) if timestamp is None else int(timestamp),
            stream_id=self.stream_id, flags=flags, sid_width=self.sid_width,
        )
        return self.add(ev)

    # -- typed emitters -----------------------------------------------------------
    @staticmethod
    def _sid(x: Composition | bytes) -> Ref:
        return Ref(REF_SID, x.sid if isinstance(x, Composition) else bytes(x))

    def join(self, author, competence: Iterable[Pid | bytes | Composition] = (), caps: dict | None = None, **kw) -> Event:
        comp = [x if isinstance(x, Pid) else self._sid(x) for x in competence]
        return self.emit(EventType.JOIN, author, {"competence": comp, "caps": caps or {}}, **kw)

    def leave(self, author, reason: str | None = None, **kw) -> Event:
        return self.emit(EventType.LEAVE, author, {"reason": reason} if reason else {}, **kw)

    def amend(self, author, comps: Iterable[Composition], **kw) -> Event:
        return self.emit(EventType.AMEND, author, [c.to_map() for c in comps], **kw)

    def ground(self, author, comps: Iterable[Composition], **kw) -> Event:
        return self.emit(EventType.GROUND, author, [c.to_map() for c in comps], **kw)

    def assert_(self, author, pairs: Iterable[tuple[Composition | bytes, Any]], **kw) -> Event:
        return self.emit(EventType.ASSERT, author, [[self._sid(s), v] for s, v in pairs], **kw)

    def expand(self, author, unknown: Iterable[Composition | bytes], **kw) -> Event:
        return self.emit(EventType.EXPAND, author, {"unknown": [self._sid(x) for x in unknown]}, **kw)

    def reground(self, author, subject, evidence: Iterable[bytes], reading: str, proposal=None, **kw) -> Event:
        p: dict[str, Any] = {
            "subject": self._sid(subject),
            "evidence": [Ref(REF_EID, bytes(e)) for e in evidence],
            "reading": reading,
        }
        if proposal is not None:
            p["proposal"] = self._sid(proposal)
        return self.emit(EventType.REGROUND, author, p, **kw)

    def acquire(self, author, offer: Iterable[Pid | bytes | Composition], challenge=None, **kw) -> Event:
        p: dict[str, Any] = {"offer": [x if isinstance(x, Pid) else self._sid(x) for x in offer]}
        if challenge:
            p["challenge"] = [[self._sid(s), v] for s, v in challenge]
        return self.emit(EventType.ACQUIRE, author, p, **kw)

    def attest(self, author, items: Iterable[tuple[Pid | bytes | Composition, AttestLevel | int]], **kw) -> Event:
        payload = [[x if isinstance(x, Pid) else self._sid(x), int(level)] for x, level in items]
        return self.emit(EventType.ATTEST, author, payload, **kw)

    def error(self, author, code: ErrorCode | int, detail: str, subject: Ref | None = None, **kw) -> Event:
        p: dict[str, Any] = {"code": int(code), "detail": detail}
        if subject is not None:
            p["subject"] = subject
        return self.emit(EventType.ERROR, author, p, **kw)

    def checkpoint(self, author, inline: bool = True, **kw) -> Event:
        st = self.state
        payload = {
            "covers": [Ref(REF_EID, f) for f in self.frontier],
            "hash_alg": HASH_ALG_SHA256,
            "sid_profile": PROFILE_CODES[self.sid_width],
            "inventory_ver": INVENTORY_VERSION,
            "lexicon": [Ref(REF_SID, s) for s in st.lexicon],
            "state": {Ref(REF_SID, k): v for k, v in st.assertions.items()},
            "digest": st.digest(),
        }
        if inline:
            payload["comps"] = [c.to_map() for c in st.lexicon.values()]
        return self.emit(EventType.CHECKPOINT, author, payload, **kw)

    # -- access --------------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def get(self, eid: bytes) -> Event | None:
        eid = bytes(eid)
        return self._index.get(eid) or self._by_ref.get(eid)

    def ordered(self) -> list[Event]:
        return toposort(self.events)

    def lexicon(self) -> dict[bytes, Composition]:
        return self.state.lexicon

    def author_name(self, sid: bytes) -> str | None:
        sid = bytes(sid)
        if sid in self.authors:
            return self.authors[sid]
        c = self.state.symbol(sid)
        return c.residue if c is not None and c.residue else None

    # -- serialization ---------------------------------------------------------------
    def to_bytes(self) -> bytes:
        return write_frames(self.ordered())

    @classmethod
    def from_bytes(cls, data: bytes, sid_width: int | None = None) -> "Stream":
        if sid_width is None:
            sid_width = sniff_profile(data)
            if sid_width is None:
                raise StreamError("cannot determine stream profile")
        events = read_frames(data, sid_width)
        st = cls(events[0].stream_id if events else None, sid_width)
        for ev in toposort(events):
            st.add(ev)
        return st

    def reprofile(self, sid_width: int) -> "Stream":
        """Re-hash the stream at another profile.

        Widening (transport -> SID-256 archive) is exact when every reference
        can be resolved from the stream's own lexicon and events.  Narrowing
        simply truncates.  EIDs change either way, by construction."""
        if sid_width == self.sid_width:
            return self
        full_ids = {e.eid_ref: e.eid for e in self.events}
        # A stream id is not an event and cannot be recovered from a truncated
        # transport; widening zero-pads it (visibly) rather than inventing bits.
        sid_new = self.stream_id[:sid_width].ljust(sid_width, b"\x00")
        out = Stream(sid_new, sid_width)
        out.authors = dict(self.authors)
        mapping: dict[bytes, bytes] = {}   # old eid_ref -> new eid_ref
        for e in self.ordered():
            payload = self._expand_payload(e.payload, sid_width)
            if e.type == EventType.CHECKPOINT and isinstance(payload, dict):
                payload = dict(payload, sid_profile=PROFILE_CODES[sid_width])
            ne = Event(
                type=e.type, author=self._expand_sid(e.author, sid_width), payload=payload,
                parents=tuple(mapping[p] for p in e.parents if p in mapping),
                timestamp=e.timestamp, stream_id=out.stream_id, flags=e.flags,
                version=e.version, signature=None, sid_width=sid_width,
            )
            out.add(ne)
            mapping[e.eid_ref] = ne.eid_ref
        return out

    def _expand_sid(self, sid: bytes, width: int) -> bytes:
        if len(sid) >= width:
            return sid[:width]
        full = self.state.resolve_sid(sid)
        if full is None:
            for a in self.authors:
                if a.startswith(sid):
                    full = agent_sid(self.authors[a])
                    break
        if full is None:
            raise StreamError(f"cannot widen SID {sid.hex()}: not in lexicon")
        return full[:width]

    def _expand_eid(self, eid: bytes, width: int) -> bytes:
        if len(eid) >= width:
            return eid[:width]
        e = self._by_ref.get(eid)
        if e is not None:
            return e.eid[:width]
        raise StreamError(f"cannot widen EID {eid.hex()}: unknown event")

    def _expand_payload(self, v: Any, width: int) -> Any:
        if isinstance(v, Ref):
            if v.kind == REF_SID:
                return Ref(REF_SID, self._expand_sid(v.data, width))
            if v.kind == REF_EID:
                try:
                    return Ref(REF_EID, self._expand_eid(v.data, width))
                except StreamError:
                    return v
            return v
        if isinstance(v, list):
            return [self._expand_payload(x, width) for x in v]
        if isinstance(v, dict):
            return {self._expand_payload(k, width): self._expand_payload(x, width) for k, x in v.items()}
        return v

    def verify(self) -> list[str]:
        """Structural checks: parents resolve, compositions valid, inventory matches."""
        problems: list[str] = []
        for e in self.events:
            for p in e.parents:
                if p not in self._by_ref:
                    problems.append(f"{e.eid_hex(8)}: E_UNKNOWN_PARENT {p.hex()[:8]}")
            try:
                e.compositions()
            except Exception as ex:  # noqa: BLE001
                problems.append(f"{e.eid_hex(8)}: {ex}")
            if e.type == EventType.CHECKPOINT and isinstance(e.payload, dict):
                if e.payload.get("inventory_ver") != INVENTORY_VERSION:
                    problems.append(f"{e.eid_hex(8)}: E_INVENTORY")
                if e.payload.get("sid_profile") != PROFILE_CODES[self.sid_width]:
                    problems.append(f"{e.eid_hex(8)}: E_PROFILE")
        return problems
