"""A running ALP participant (RFC-ALP-001 v1.1 §8–§11).

``Peer`` is what an agent embeds.  It holds a stream, tracks competence,
and implements the protocol behaviours the RFC specifies beyond
serialization:

  §9.3  unknown symbols never fail a message — an event naming a SID the
        peer cannot resolve is buffered and an EXPAND is emitted; it is
        applied when a GROUND arrives.  Compositions are derivable, so this
        only happens for SIDs whose composition was never transmitted
        (references, or residue-bearing symbols from a checkpoint list).
  §9.2  ATTEST: HELD on receipt, DEMONSTRATED after a round-trip challenge.
  §9.4  model substitution: ``replace_model`` re-joins, acquires the
        inventory version, re-attests, DECLINES what it can no longer work.
  §7.3  CHECKPOINT: emitted every N events; a received checkpoint's digest
        is verified independently and E_DIVERGENCE raised on mismatch;
        inventory_ver mismatch raises E_INVENTORY.
  §10   REGROUND: repair as a first-class message; ``reground`` proposes a
        superseding symbol.
  §11.2 AMEND rate limit per author and lexicon cap -> E_RATE / E_LEXICON_FULL.
  §11.3 composition poisoning: GROUND payloads are verified against the
        requested SIDs (E_SID_MISMATCH) before they enter the lexicon.
  §11.4 EXPAND amplification: GROUND is rate-limited per requester.

Transport is left to the caller: ``outbox`` collects frames to send and
``receive`` accepts frames (or Events) from anywhere.  Two peers can be wired
directly (see ``examples/two_agents.py``) or over any ordered byte channel.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import alpb
from .alpb import Pid, Ref, REF_SID, REF_EID
from .composition import Composition, SIDMismatch, verify as verify_comp
from .events import (
    AttestLevel, ErrorCode, Event, EventType, Stream, StreamError, decode_body, split_frames,
    PROFILE_CODES, HASH_ALG_SHA256, agent_symbol,
)
from .inventory import INVENTORY_VERSION, PRIMITIVES


class ProtocolError(StreamError):
    def __init__(self, code: ErrorCode, detail: str) -> None:
        super().__init__(f"{code.name}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class RateLimit:
    events: int = 20          # max events of a kind per author per window
    window: float = 10.0      # seconds


@dataclass
class PeerConfig:
    checkpoint_every: int = 25
    lexicon_cap: int = 10_000
    amend_limit: RateLimit = field(default_factory=RateLimit)
    ground_limit: RateLimit = field(default_factory=lambda: RateLimit(events=10, window=10.0))
    require_attest_for_bulk_expand: int = 8      # EXPAND naming more SIDs than this needs an ATTEST from the requester
    clock: Callable[[], float] = time.time


class Peer:
    """One participant in one stream."""

    def __init__(self, name: str, stream: Stream | None = None, sid_width: int = 16,
                 config: PeerConfig | None = None, competence: Iterable[Pid] | None = None) -> None:
        self.name = name
        self.cfg = config or PeerConfig()
        self.stream = stream if stream is not None else Stream(sid_width=sid_width)
        self.stream.authors[agent_symbol(name).sid[: self.stream.sid_width]] = name
        self.me = agent_symbol(name).sid
        self.primitives: set[Pid] = set(competence if competence is not None else PRIMITIVES.values())
        self.declined: set[bytes] = set()
        self.outbox: list[Event] = []
        self.pending: deque[tuple[Event, set[bytes]]] = deque()     # buffered events awaiting GROUND
        self.requested: set[bytes] = set()
        self.private: dict[bytes, Composition] = {}                   # symbols this agent knows but has not transmitted
        self.log: list[str] = []
        self._rate: dict[tuple[bytes, str], deque] = {}
        self._since_checkpoint = 0
        self._joined = False

    # -- helpers -----------------------------------------------------------------
    def _note(self, msg: str) -> None:
        self.log.append(f"[{self.name}] {msg}")

    def _emit(self, ev: Event) -> Event:
        self.outbox.append(ev)
        self._since_checkpoint += 1
        if ev.type != EventType.CHECKPOINT and self._since_checkpoint >= self.cfg.checkpoint_every:
            self.checkpoint(timestamp=int(self.cfg.clock()))
        return ev

    def _rate_check(self, author: bytes, kind: str, limit: RateLimit) -> bool:
        now = self.cfg.clock()
        q = self._rate.setdefault((author, kind), deque())
        while q and now - q[0] > limit.window:
            q.popleft()
        if len(q) >= limit.events:
            return False
        q.append(now)
        return True

    def take_outbox(self) -> list[Event]:
        out, self.outbox = self.outbox, []
        return out

    def frames(self) -> bytes:
        return b"".join(e.frame() for e in self.take_outbox())

    @property
    def lexicon(self) -> dict[bytes, Composition]:
        return self.stream.lexicon()

    def know(self, comp: Composition) -> None:
        """Hold a symbol privately (e.g. from another stream or a local lexicon)."""
        self.private[comp.sid] = comp

    def resolve(self, sid: bytes) -> Composition | None:
        c = self.stream.state.symbol(sid)
        if c is not None:
            return c
        sid = bytes(sid)
        hits = [v for k, v in self.private.items() if k.startswith(sid)]
        return hits[0] if len(hits) == 1 else None

    def can_work(self, comp: Composition) -> bool:
        """Symbol competence is derived from primitive competence (§9.1)."""
        if comp.sid in self.declined:
            return False
        pids = {p for p in comp.primitives()}
        return pids <= self.primitives

    # -- sending ------------------------------------------------------------------
    def join(self, timestamp: int | None = None) -> Event:
        ev = self.stream.join(self.name, competence=sorted(self.primitives, key=lambda p: p.code),
                              caps={"inventory_ver": INVENTORY_VERSION}, timestamp=timestamp)
        self._joined = True
        return self._emit(ev)

    def leave(self, reason: str = "", timestamp: int | None = None) -> Event:
        return self._emit(self.stream.leave(self.name, reason, timestamp=timestamp))

    def amend(self, comps: Iterable[Composition], timestamp: int | None = None) -> Event:
        comps = list(comps)
        if not self._rate_check(self.me, "AMEND", self.cfg.amend_limit):
            raise ProtocolError(ErrorCode.E_RATE, "AMEND rate limit")
        if len(self.lexicon) + len(comps) > self.cfg.lexicon_cap:
            raise ProtocolError(ErrorCode.E_LEXICON_FULL, "lexicon cap")
        return self._emit(self.stream.amend(self.name, comps, timestamp=timestamp))

    def assert_(self, pairs: Iterable[tuple[Composition, Any]], timestamp: int | None = None, inline: bool = True) -> Event:
        """ASSERT.  With ``inline`` (default) any symbol not yet in the lexicon is
        AMENDed first, so receivers holding the inventory can read it with no
        round trip (§8.2)."""
        pairs = list(pairs)
        if inline:
            new = [c for c, _ in pairs if c.sid not in self.lexicon]
            if new:
                self.amend(new, timestamp=timestamp)
        return self._emit(self.stream.assert_(self.name, pairs, timestamp=timestamp))

    def attest(self, items: Iterable[tuple[Pid | Composition | bytes, AttestLevel]], timestamp: int | None = None) -> Event:
        return self._emit(self.stream.attest(self.name, items, timestamp=timestamp))

    def expand(self, sids: Iterable[bytes], timestamp: int | None = None) -> Event:
        sids = [s for s in sids if s not in self.requested]
        self.requested.update(sids)
        return self._emit(self.stream.expand(self.name, sids, timestamp=timestamp))

    def ground(self, comps: Iterable[Composition], timestamp: int | None = None) -> Event:
        return self._emit(self.stream.ground(self.name, comps, timestamp=timestamp))

    def reground(self, subject: Composition, evidence: Iterable[bytes], reading: str,
                 proposal: Composition | None = None, timestamp: int | None = None) -> Event:
        if proposal is not None and proposal.sid not in self.lexicon:
            self.amend([proposal], timestamp=timestamp)
        return self._emit(self.stream.reground(self.name, subject, evidence, reading, proposal, timestamp=timestamp))

    def checkpoint(self, timestamp: int | None = None) -> Event:
        self._since_checkpoint = 0
        return self._emit(self.stream.checkpoint(self.name, timestamp=timestamp))

    def error(self, code: ErrorCode, detail: str, timestamp: int | None = None) -> Event:
        return self._emit(self.stream.error(self.name, code, detail, timestamp=timestamp))

    # -- model substitution (§9.4) -----------------------------------------------------
    def replace_model(self, competence: Iterable[Pid], timestamp: int | None = None) -> list[Event]:
        """The backing model changed.  Acquire from the current state, re-attest,
        DECLINE symbols the new model cannot work."""
        old = self.primitives
        self.primitives = set(competence)
        evs = [self.join(timestamp=timestamp)]
        lost = old - self.primitives
        if lost:
            evs.append(self.attest([(p, AttestLevel.DECLINED) for p in sorted(lost, key=lambda p: p.code)], timestamp=timestamp))
            for sid, comp in list(self.lexicon.items()):
                if not self.can_work(comp):
                    self.declined.add(sid)
            if self.declined:
                evs.append(self.attest([(s, AttestLevel.DECLINED) for s in sorted(self.declined)], timestamp=timestamp))
        held = [(c, AttestLevel.HELD) for c in self.lexicon.values() if self.can_work(c)]
        if held:
            evs.append(self.attest(held[:64], timestamp=timestamp))
        self._note(f"model replaced: {len(self.primitives)} primitives, {len(self.declined)} symbols declined")
        return evs

    # -- receiving ----------------------------------------------------------------------
    def receive_frames(self, data: bytes) -> list[Event]:
        applied = []
        for body in split_frames(data):
            ev = decode_body(body, self.stream.sid_width)
            applied += self.receive(ev)
        return applied

    def receive(self, ev: Event) -> list[Event]:
        """Handle one incoming event.  Returns the events actually applied
        (the incoming one, plus any buffered ones a GROUND unblocked)."""
        if ev.stream_id != self.stream.stream_id:
            raise ProtocolError(ErrorCode.E_PROFILE, "event from another stream")
        if ev.eid in {e.eid for e in self.stream.events}:
            return []                                              # idempotent (§2.2)
        applied: list[Event] = []
        unknown = self._unknown_sids(ev)
        if unknown:
            self.pending.append((ev, unknown))
            self._note(f"buffered {ev.type.name} {ev.eid_hex(8)}: unknown {[s.hex()[:8] for s in unknown]}")
            self.expand(unknown)
            return applied
        self._apply(ev)
        applied.append(ev)
        # anything now resolvable?
        progressed = True
        while progressed and self.pending:
            progressed = False
            for _ in range(len(self.pending)):
                pev, unk = self.pending.popleft()
                still = {s for s in unk if self.resolve(s) is None}
                if still:
                    self.pending.append((pev, still))
                else:
                    self._apply(pev)
                    applied.append(pev)
                    progressed = True
                    self._note(f"applied buffered {pev.type.name} {pev.eid_hex(8)}")
        return applied

    def _unknown_sids(self, ev: Event) -> set[bytes]:
        """SIDs the event uses that this peer cannot resolve after applying it.
        Compositions carried inline (AMEND/GROUND/CHECKPOINT.comps) count as known."""
        carried = {c.sid[: self.stream.sid_width] for c in ev.compositions()} | {c.sid for c in ev.compositions()}
        needed: set[bytes] = set()
        if ev.type == EventType.ASSERT:
            for pair in ev.payload:
                needed.add(pair[0].data)
        elif ev.type == EventType.REGROUND:
            needed.add(ev.payload["subject"].data)
        elif ev.type == EventType.EXPAND or ev.type in (EventType.JOIN, EventType.ATTEST, EventType.ACQUIRE, EventType.CHECKPOINT, EventType.LEAVE, EventType.ERROR, EventType.AMEND, EventType.GROUND):
            return set()
        out = set()
        for s in needed:
            if s in carried or self.resolve(s) is not None:
                continue
            out.add(s)
        return out

    def _apply(self, ev: Event) -> None:
        t = ev.type
        if t == EventType.CHECKPOINT:
            self._verify_checkpoint(ev)
        if t == EventType.GROUND:
            self._verify_ground(ev)
        if t == EventType.AMEND:
            if not self._rate_check(ev.author, "AMEND", self.cfg.amend_limit):
                self.error(ErrorCode.E_RATE, f"AMEND rate from #{ev.author.hex()[:8]}")
                return
            if len(self.lexicon) + len(ev.compositions()) > self.cfg.lexicon_cap:
                self.error(ErrorCode.E_LEXICON_FULL, "lexicon cap reached")
                return
        self.stream.add(ev)
        if t in (EventType.AMEND, EventType.GROUND) and ev.author != self.me:
            items = []
            for c in ev.compositions():
                if self.can_work(c):
                    items.append((c, AttestLevel.HELD))
                else:
                    self.declined.add(c.sid)
                    items.append((c, AttestLevel.DECLINED))
            if items:
                self.attest(items)
        elif t == EventType.EXPAND and ev.author != self.me:
            self._answer_expand(ev)
        elif t == EventType.ACQUIRE and ev.author != self.me:
            chal = ev.payload.get("challenge") or []
            if chal:
                self._answer_challenge(ev, chal)

    # -- protocol checks ----------------------------------------------------------------
    def _verify_checkpoint(self, ev: Event) -> None:
        p = ev.payload
        if p.get("inventory_ver") != INVENTORY_VERSION:
            self.error(ErrorCode.E_INVENTORY, f"checkpoint inventory {p.get('inventory_ver')} != {INVENTORY_VERSION}")
            raise ProtocolError(ErrorCode.E_INVENTORY, "inventory version mismatch")
        if p.get("sid_profile") != PROFILE_CODES[self.stream.sid_width]:
            raise ProtocolError(ErrorCode.E_PROFILE, "checkpoint profile differs from stream")
        # independent digest over the checkpoint's own state map (§7.3)
        state = p.get("state", {})
        width = self.stream.sid_width
        digest = alpb.encode({Ref(REF_SID, bytes(k.data) if isinstance(k, Ref) else k): v for k, v in sorted(state.items(), key=lambda kv: kv[0].data if isinstance(kv[0], Ref) else kv[0])}, width)
        import hashlib
        if hashlib.sha256(digest).digest() != p.get("digest"):
            self.error(ErrorCode.E_DIVERGENCE, "checkpoint digest does not match its state")
            raise ProtocolError(ErrorCode.E_DIVERGENCE, "digest mismatch")
        # and against our own materialized assertions where we hold the same SIDs
        mine = self.stream.state.assertions
        for k, v in state.items():
            sid = k.data if isinstance(k, Ref) else k
            if sid in mine and mine[sid] != v:
                self.error(ErrorCode.E_DIVERGENCE, f"assertion differs for #{sid.hex()[:8]}")
                raise ProtocolError(ErrorCode.E_DIVERGENCE, f"divergent assertion #{sid.hex()[:8]}")

    def _verify_ground(self, ev: Event) -> None:
        """§11.3: every supplied composition must hash to a SID we asked for (or be new)."""
        for c in ev.compositions():
            if self.requested and not any(c.sid.startswith(r) for r in self.requested):
                continue
            for r in list(self.requested):
                if c.sid.startswith(r):
                    try:
                        verify_comp(c, r)
                    except SIDMismatch as e:
                        self.error(ErrorCode.E_SID_MISMATCH, str(e))
                        raise ProtocolError(ErrorCode.E_SID_MISMATCH, str(e))
                    self.requested.discard(r)

    def _answer_expand(self, ev: Event) -> None:
        unknown = [r.data for r in ev.payload.get("unknown", [])]
        if len(unknown) > self.cfg.require_attest_for_bulk_expand:
            attested = any(e.type == EventType.ATTEST and e.author == ev.author for e in self.stream.events)
            if not attested:
                self._note("bulk EXPAND from an unattested peer ignored (§11.4)")
                return
        if not self._rate_check(ev.author, "GROUND", self.cfg.ground_limit):
            self.error(ErrorCode.E_RATE, "GROUND rate limit for requester")
            return
        found = [self.resolve(s) for s in unknown]
        found = [c for c in found if c is not None]
        if found:
            self.ground(found)

    def _answer_challenge(self, ev: Event, challenge: list) -> None:
        """Round-trip challenge (§9.2): re-encode each challenged symbol and echo
        the value; a correct echo earns DEMONSTRATED."""
        items = []
        for sid_ref, value in challenge:
            c = self.resolve(sid_ref.data)
            if c is None or not self.can_work(c):
                items.append((sid_ref.data, AttestLevel.DECLINED))
                continue
            ok = alpb.decode(alpb.encode(c.to_map())) == c.to_map() and Composition.from_map(c.to_map()).sid == c.sid
            items.append((c, AttestLevel.DEMONSTRATED if ok else AttestLevel.HELD))
        if items:
            self.attest(items)

    # -- convenience -------------------------------------------------------------------------
    def hydrate(self, sids: Iterable[bytes] | None = None) -> list[str]:
        """§8.3 selective hydration: readings for a subset of the state."""
        st = self.stream.state
        out = []
        for sid, value in st.assertions.items():
            if sids is not None and not any(sid.startswith(s[: len(sid)]) for s in sids):
                continue
            c = st.symbol(sid)
            if c is None:
                continue
            from .realize import realize
            out.append(realize(c, value))
        return out


def wire(*peers: Peer, deliver: Callable[[Peer, Event], None] | None = None) -> Callable[[], int]:
    """Connect peers in memory.  Returns ``pump()`` which delivers every
    outbox event to every other peer until all outboxes are empty; it returns
    the number of events delivered."""
    def pump() -> int:
        n = 0
        while True:
            moved = False
            for p in peers:
                for ev in p.take_outbox():
                    moved = True
                    for q in peers:
                        if q is p:
                            continue
                        if deliver is not None:
                            deliver(q, ev)
                        else:
                            q.receive(ev)
                        n += 1
            if not moved:
                return n
    return pump
