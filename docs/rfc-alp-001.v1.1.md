# RFC-ALP-001: Agent Lexicon Protocol (ALP)

**Status:** Draft
**Version:** 1.0-draft
**License:** MIT

---

## Abstract

ALP is a protocol for machine agents to negotiate, acquire, and speak a shared
symbolic vocabulary that is denser than natural language, portable across
tokenizers and model families, and durable independently of the models that
produced it.

Symbols are identified by the hash of their own definition. The lexicon is
append-only and grows without coordination. Communication is an ordered-by-
causality stream of immutable events, so receivers hold no session state and
may join, leave, or be replaced mid-conversation. A conversation archived under
ALP remains fully interpretable after every participating model has been
retired.

---

## 1. Introduction

### 1.1 Problem Statement

Agents that converse in natural language pay for expressiveness they do not
need. Agents that converse in a schema-bound binary format pay in brittleness:
the schema becomes a coordination dependency, stored messages become
unreadable without the registry that was live when they were written, and
substituting one model for another invalidates the arrangement.

Three properties are simultaneously required and are not jointly satisfied by
any existing serialization format:

1. **Density.** Recurring concepts SHOULD cost a symbol reference, not a
   restatement.
2. **Dynamism.** The vocabulary MUST grow during a live conversation, from
   either side, without a coordinator and without renumbering.
3. **Durability.** A stored conversation MUST remain interpretable after the
   models, the vocabulary, and the participants have all changed.

ALP obtains all three from one decision: **a symbol's identity is the hash of
its definition.** Every other property in this document is downstream of that.

### 1.2 Non-Goals

ALP does not attempt to:

- Reduce the token cost of a model's own inference. At the boundary where a
  model ingests a conversation, ALP content is projected into a surface form
  that model reads well, and that projection costs approximately what natural
  language costs. ALP's savings are in transport, storage at rest, and
  **selective hydration** (§7.5) — not in the forward pass.
- Guarantee semantic agreement. ALP can prove two agents decode a symbol
  identically. It cannot prove they mean the same thing by it. See §9.
- Replace a general-purpose serialization format. ALP is a language with a
  lexicon, not a wire codec with a schema.

### 1.3 Requirements Language

The key words MUST, MUST NOT, REQUIRED, SHALL, SHALL NOT, SHOULD, SHOULD NOT,
RECOMMENDED, MAY, and OPTIONAL are to be interpreted as described in BCP 14
(RFC 2119, RFC 8174).

### 1.4 Terminology

| Term | Definition |
|---|---|
| **Agent** | A participant in a stream. Backed by one or more models over its lifetime. |
| **Symbol** | An interned unit of meaning. Identified by SID. |
| **SID** | Symbol Identifier. Hash of the symbol's canonical Definition Record. |
| **Definition Record** | The self-contained, immutable definition of a symbol. |
| **Grounding** | The natural-language explanation carried inside a Definition Record. |
| **Lexicon** | The set of symbols known to a stream. Append-only. |
| **Event** | An immutable frame in a stream. Identified by EID. |
| **EID** | Event Identifier. Hash of the canonical binary frame body. |
| **Stream** | A causally-ordered DAG of events constituting one conversation. |
| **Competence** | The subset of the lexicon an agent can correctly encode and decode. |
| **Hydration** | Projecting ALP content into a surface form a model can reason over. |

---

## 2. Architecture

### 2.1 Layer Separation

ALP separates three concerns that schema-bound formats conflate. The split
follows ASN.1's distinction between abstract syntax and transfer syntax, with
a third layer for participant capability.

```
  +---------------------------------------------------+
  |  L3  Competence   who can speak which symbols     |
  +---------------------------------------------------+
  |  L2  Transfer     ALP/B binary | ALP/T canonical  |
  +---------------------------------------------------+
  |  L1  Lexicon      symbol graph, content-addressed |
  +---------------------------------------------------+
```

- **L1 (Lexicon)** defines meaning. It is a DAG of Definition Records.
- **L2 (Transfer)** defines encoding. Two projections of L1: `ALP/B` for
  transport, `ALP/T` for storage, audit, diff, and external translation. Both
  MUST be lossless with respect to L1 and MUST round-trip to each other.
- **L3 (Competence)** defines capability. A per-agent set of SIDs.

An implementation MUST NOT allow an L2 concern to influence an L1 identity.
Hashes are computed over canonical ALP/B only (§4.2); ALP/T is a projection
and is never authoritative.

### 2.2 Event Stream Model

A conversation is not a session. It is an append-only log of immutable events
forming a causal DAG. Consequences:

- Receivers are stateless. All state is a deterministic fold over the event set
  (§6.4).
- An agent MAY join mid-stream, leave, and rejoin. There is no handshake to
  resume.
- An agent MAY replace its backing model between any two events (§8.4).
- Two agents MAY emit concurrently without a coordinator. Concurrency is
  represented, not prevented (§6.2).
- Replay is idempotent. Applying an event twice is a no-op, since events are
  identified by content.

---

## 3. Symbol Identity

### 3.1 Definition Record

A Definition Record is self-contained. It MUST NOT reference a mutable
external resource.

| Field | Key | Type | Req | Description |
|---|---|---|---|---|
| Kind | `k` | u8 | MUST | Symbol kind (§3.2) |
| Label | `l` | text | MUST | Short human/model-facing name. Not an identifier. |
| Grounding | `g` | text | MUST | Natural-language definition. The authoritative meaning. |
| Type | `t` | u8 | SHOULD | Value type this symbol admits (§5.2) |
| Constraints | `c` | map | MAY | Range, enum, unit, cardinality |
| Supersedes | `s` | SID | MAY | Prior symbol this refines or replaces (§3.4) |
| Related | `r` | list\<SID\> | MAY | Non-superseding semantic links |
| Minted | `m` | u64 | MAY | Unix seconds. Advisory only; MUST NOT affect ordering. |

The Label is deliberately not an identifier. Two agents MAY mint distinct
symbols sharing a Label; they are distinct symbols. Collision of Labels is not
an error and MUST NOT be treated as one.

### 3.2 Symbol Kinds

| Kind | Value | Meaning |
|---|---|---|
| `CONCEPT` | 0x01 | A predicate, field, or attribute |
| `VALUE` | 0x02 | An interned enum member or constant |
| `RELATION` | 0x03 | A binary relation between symbols |
| `ACTION` | 0x04 | A performative or invocable operation |
| `FRAME` | 0x05 | A composite: an ordered set of CONCEPT slots |

### 3.3 SID Computation

```
SID = H( canonical_ALP/B( DefinitionRecord ) )
```

`H` is SHA-256 by default. Implementations MUST support SHA-256 and MAY
negotiate others; the algorithm is carried in the CHECKPOINT (§6.3) and MUST
NOT vary within a stream.

**This is the load-bearing decision of the protocol.** Because a SID is
derived from the definition and nothing else:

- No authority assigns identifiers. There is no registry to be unavailable,
  partitioned, or shut down.
- Two agents minting the same concept independently converge on the same SID
  automatically. Two agents minting different concepts cannot collide.
- Concurrent amendment is not a conflict. Leader election, merge resolution,
  and renumbering are not merely solved but structurally impossible to need.
- A symbol is self-authenticating. Its grounding is inside the hash preimage,
  so a supplied definition either matches its SID or is rejected (§10.3).

### 3.4 Truncation Profiles

Full SIDs are 32 bytes, which dominates a small frame. Implementations MAY
truncate to a profile negotiated at CHECKPOINT and constant within a stream.

| Profile | Bytes | Collision risk (birthday) | Use |
|---|---|---|---|
| `SID-256` | 32 | negligible | Archival, adversarial, cross-org |
| `SID-128` | 16 | ~2^64 symbols | RECOMMENDED default |
| `SID-96` | 12 | ~2^48 symbols | High-volume trusted transport |
| `SID-64` | 8 | ~2^32 symbols | NOT RECOMMENDED. Trusted, short-lived only. |

Archived streams MUST store SIDs at `SID-256` regardless of the transport
profile used. Truncation is a transport optimization and MUST NOT propagate
into storage.

### 3.5 Supersession, Not Redefinition

A symbol's meaning is immutable. Changing a meaning requires minting a new
symbol whose `supersedes` field points at the old SID.

This is what makes epoch markers unnecessary. Under a mutable vocabulary, a
message's meaning depends on when it was read, so every stored message needs a
point-in-time registry lookup and every in-flight message is ambiguous during
renegotiation. Under ALP, a message's meaning is fixed at write time by
construction. An event from the first turn of a stream reads identically after
ten thousand subsequent amendments.

Supersession is advisory. A receiver MAY continue to use a superseded symbol
and MUST still be able to decode it. Superseded symbols are never removed from
the lexicon; see §11.4 on compaction.

---

## 4. Wire Format: ALP/B

### 4.1 Value Encoding

ALP/B uses a tag-length-value encoding intentionally shaped like CBOR
(RFC 8949), so existing decoders can be adapted rather than written. It is not
CBOR-compatible; the major type assignments differ.

A tag byte is `MMMAAAAA`: 3-bit major type, 5-bit argument. Argument values
0–23 are immediate. 24, 25, 26, 27 indicate a following 1, 2, 4, or 8-byte
big-endian argument. 31 indicates indefinite length, terminated by `0xFF`.

| Major | Value | Type | Argument means |
|---|---|---|---|
| 0 | `UINT` | unsigned integer | the value |
| 1 | `NINT` | negative integer | -(value + 1) |
| 2 | `BYTES` | byte string | byte count |
| 3 | `TEXT` | UTF-8 string | byte count |
| 4 | `LIST` | array | element count |
| 5 | `MAP` | map | pair count |
| 6 | `REF` | SID or EID reference | reference kind (§4.1.1) |
| 7 | `SIMPLE` | simple/float | false=20, true=21, null=22, f64=27 |

#### 4.1.1 REF Arguments

| Arg | Meaning |
|---|---|
| 0 | SID, profile width per stream |
| 1 | EID, profile width per stream |
| 2 | SID, full 32 bytes (overrides profile) |
| 3 | EID, full 32 bytes (overrides profile) |

A `REF` is the density primitive. A concept that would cost 40–200 bytes of
natural language costs 13–17 bytes at `SID-128`, and its grounding is
transmitted at most once per participant per stream (§8.3).

### 4.2 Canonical Form

Hashing requires exactly one byte sequence per logical value. Canonical ALP/B:

1. Integers MUST use the shortest argument encoding that fits.
2. Indefinite-length encoding MUST NOT be used.
3. Map keys MUST be sorted bytewise ascending on their encoded form.
4. Duplicate map keys MUST NOT appear.
5. Absent OPTIONAL fields MUST be omitted, never encoded as null.
6. Floats MUST be f64. NaN MUST be canonical quiet NaN.
7. Text MUST be NFC-normalized UTF-8.

A decoder receiving non-canonical bytes where canonical form is REQUIRED MUST
reject the frame with `E_NONCANONICAL` (§10.5).

### 4.3 Frame Structure

Streams are length-prefixed to permit framing over any ordered byte transport.

```
  stream  := frame*
  frame   := length:uvarint body:bytes[length]

  body    := version:u8
             type:u8
             flags:u8
             stream_id:REF(EID)
             parents:LIST<REF(EID)>
             timestamp:UINT
             author:REF(SID)
             payload:<type-specific>
             [signature:BYTES]      ; present iff flags & 0x01
```

| Flag | Bit | Meaning |
|---|---|---|
| `SIGNED` | 0x01 | Trailing detached signature over `body` sans signature |
| `CHECKPOINT_REF` | 0x02 | Payload includes a checkpoint EID for fast join |
| `EPHEMERAL` | 0x04 | Sender requests this event be excluded from archive |
| `HYDRATE_HINT` | 0x08 | Payload carries a projection hint (§7.5) |

`EPHEMERAL` is a request, not a guarantee. An archiver MAY honor or ignore it,
and MUST record which it did.

### 4.4 EID Computation

```
EID = H( canonical_ALP/B( body ) )     ; signature field excluded
```

Excluding the signature means a signed and unsigned copy of the same event
share an EID, so signing is additive and does not fork the DAG.

---

## 5. Canonical Text Form: ALP/T

### 5.1 Purpose

ALP/T exists so that a stored conversation is auditable, diffable, greppable,
and translatable by tools and humans that have no ALP/B decoder — and so that
the archive outlives any particular implementation. It is REQUIRED for
archival, OPTIONAL for transport.

ALP/T MUST round-trip to byte-identical canonical ALP/B. It is a projection.
Hashes are never computed over it.

### 5.2 Grammar

```
  document   := "%alp/t" SP version NL block+
  block      := event | defn
  event      := "@" eid SP type NL
                ("<-" SP eid (SP eid)* NL)?
                ("by" SP sid NL)
                ("at" SP iso8601 NL)
                body-line+
  defn       := "!" sid SP kind SP quoted NL
                ("=" SP quoted NL)          ; grounding
                ("^" SP sid NL)?            ; supersedes
                ("?" SP constraint NL)*
  body-line  := INDENT term NL
  term       := ref | literal | "(" term* ")"
  ref        := "#" sid ("~" label)?
```

The `~label` suffix is a decoration. Readers MUST ignore it when decoding and
MUST NOT treat it as identifying. It exists so a human reading an archive is
not staring at bare hashes.

### 5.3 Example

```
%alp/t 1

!3f2a1b9c "urgency" CONCEPT
= "Operator-facing priority. Integer 0-4. 4 requires human ack within 15m."
? range 0 4

!88b1c07d "urgency" CONCEPT
= "Operator-facing priority. Integer 0-4. 4 pages on-call immediately."
^ 3f2a1b9c
? range 0 4

@a91c2f04 ASSERT
<- 9c8d7e11 1122aa33
by #de11ce00
at 2026-08-31T14:02:11Z
  (#88b1c07d~urgency 4)
  (#77bd0142~deadline "2026-09-01T12:00:00Z")
```

Note both `urgency` symbols coexist. The second refines the escalation
semantics of the first and supersedes it. Events written under the first
remain unambiguous forever.

---

## 6. Event Model

### 6.1 Event Types

| Type | Code | Direction | Purpose |
|---|---|---|---|
| `JOIN` | 0x01 | any | Announce participation and initial competence |
| `LEAVE` | 0x02 | any | Announce departure. Advisory. |
| `ASSERT` | 0x03 | any | State content using lexicon symbols |
| `AMEND` | 0x04 | any | Introduce Definition Records into the lexicon |
| `EXPAND` | 0x05 | request | "I do not hold SID X; supply its definition" |
| `GROUND` | 0x06 | response | Supply Definition Records for requested SIDs |
| `REGROUND` | 0x07 | any | "I believe we have diverged on SID X" (§9) |
| `ACQUIRE` | 0x08 | any | Offer a vocabulary for a joining or replaced model |
| `ATTEST` | 0x09 | any | Claim or demonstrate competence over SIDs |
| `CHECKPOINT` | 0x0A | any | Materialized state snapshot for fast join |
| `ERROR` | 0x0B | any | Signal a protocol fault (§10.5) |

There is no ACK. Acknowledgment is implicit in causal reference: an event that
names another as a parent has observed it.

### 6.2 Causality

`parents` holds the EIDs of every event the author had observed and not yet
referenced, at emission. This yields a Merkle DAG with the same properties Git
relies on: partial order without a clock, tamper-evidence, and lossless
representation of concurrency.

- Events with no causal path between them are **concurrent**. Concurrency is
  legal and is NOT an error.
- For any operation requiring a total order (rendering, hydration, archival),
  implementations MUST use the causal partial order, breaking ties by
  bytewise-ascending EID. This is deterministic and identical across agents.
- `timestamp` is advisory. It MUST NOT be used for ordering. Agents lie,
  drift, and reboot.

### 6.3 CHECKPOINT

Replaying a long stream to derive state is wasteful, and a joining agent may
not possess the history. A CHECKPOINT materializes the fold at a point in the
DAG.

| Field | Type | Description |
|---|---|---|
| `covers` | LIST\<EID\> | DAG frontier this checkpoint summarizes |
| `hash_alg` | u8 | Hash algorithm for the stream |
| `sid_profile` | u8 | Truncation profile (§3.4) |
| `lexicon` | LIST\<SID\> | Live symbols. Definitions fetched via EXPAND as needed. |
| `defs` | LIST\<DefRec\> | OPTIONAL inline definitions for the hot subset |
| `state` | MAP | Materialized assertions |
| `digest` | BYTES | Hash of canonical `state`, for divergence detection |

Any agent MAY emit a CHECKPOINT. A receiver MUST verify `digest` by
independent computation before trusting one from an untrusted peer. Two
correct agents checkpointing the same frontier MUST produce identical
`digest` values; a mismatch indicates divergence or a faulty implementation
and MUST raise `E_DIVERGENCE`.

Emitting CHECKPOINT every N events trades stream volume against join latency
(§11.2).

### 6.4 Stateless Fold

State is a pure function of the event set.

```
  state(E) = fold(apply, S0, toposort(E))

  S = (L, C, A)
      L : SID  -> DefinitionRecord     ; lexicon,    grow-only
      C : AGT  -> Set<SID>             ; competence, grow-only per agent
      A : SID  -> Value                ; assertions, last-writer-wins
```

`L` and `C` are grow-only sets (G-Sets). Union is commutative, associative,
and idempotent, so they form a join-semilattice and converge under strong
eventual consistency with no coordination. **This is why append-only is
required rather than merely convenient** — it is the property that lets
agents amend the vocabulary concurrently and still agree.

`A` is not a G-Set; it resolves conflicting concurrent assertions by the total
order of §6.2 (last-writer-wins on causal order, EID tiebreak). Implementations
requiring different assertion merge semantics MUST declare them at CHECKPOINT.

Because the fold is pure and events are content-addressed, `apply` MUST be
idempotent: applying an already-seen EID is a no-op.

---

## 7. Density and Hydration

### 7.1 Where the Savings Are

An implementer MUST NOT expect ALP to reduce inference cost directly. The
budget:

| Path | ALP effect |
|---|---|
| Agent-to-agent transport | Large reduction. Symbols are references. |
| Storage at rest | Large reduction, plus interpretability guarantee. |
| Selective hydration | Large reduction. The dominant win for long-running agents. |
| Model ingestion of hydrated content | Approximately neutral. |

### 7.2 First-Use Cost

The first use of a symbol by a given participant costs an EXPAND/GROUND round
trip plus the full grounding text — more than simply having said it in
English. Every subsequent use costs a reference. Break-even is typically 2–4
uses. Short conversations over a cold lexicon will underperform plain
language (§11.1).

### 7.3 Selective Hydration

A model does not need the whole transcript. It needs the symbols relevant to
its current task. Because the fold is pure and assertions are keyed by SID, an
agent MAY hydrate an arbitrary subset:

```
  hydrate(state, sids, competence) -> surface_form
```

For a long-running stream this is the difference between replaying ten
thousand events and materializing forty relevant assertions. Implementations
SHOULD expose hydration scope as an explicit parameter rather than defaulting
to full replay.

### 7.4 Hydration Is Not Canonical

Hydrated surface form is generated output. It MUST NOT be fed back into the
stream as authoritative, and it MUST NOT participate in any hash. An agent
that has reasoned over hydrated content and wishes to record a conclusion MUST
emit a new ASSERT.

---

## 8. Competence

### 8.1 Model

Competence is tracked **per symbol**, never per lexicon. Whole-lexicon
competence is untenable in a vocabulary that grows continuously: every AMEND
would invalidate every participant. Per-symbol competence follows directly
from hashed identity — each agent holds a set of SIDs it can work.

A sender SHOULD maintain a competence estimate for each receiver. This
estimate is an optimization, not a correctness requirement: §8.3 guarantees
that a wrong estimate degrades performance rather than meaning.

### 8.2 ATTEST

An agent claims competence by emitting ATTEST with a SID list and a level:

| Level | Code | Meaning |
|---|---|---|
| `HELD` | 0x01 | Definition is stored. Decode claimed, not demonstrated. |
| `DEMONSTRATED` | 0x02 | Passed a round-trip challenge over this SID. |
| `DECLINED` | 0x03 | Cannot or will not work this SID. Do not send it unexpanded. |

`DEMONSTRATED` is obtained by encoding a challenge value under the symbol and
decoding a challenge encoding, both supplied by the challenger. It proves the
agent can transform the symbol correctly. **It does not prove semantic
agreement** (§9).

### 8.3 Unknown Symbols Never Fail a Message

On encountering a SID it does not hold, a receiver MUST NOT discard the event.
It MUST emit EXPAND naming the unknown SIDs, and SHOULD buffer the event
pending GROUND.

Rationale: failing loses the message permanently and requires the sender to
maintain a perfectly accurate competence model. Expansion costs one grounding
transmission, amortized across every later use in the stream. This is how
humans handle an unfamiliar word, and it is the reason a wrong competence
estimate is merely slow.

A sender MAY pre-empt this by including definitions inline when it believes
the receiver lacks them. A sender MAY also degrade a single symbol to natural
language for one message without amending the lexicon; the receiver learns
nothing from this, so it SHOULD be a last resort.

### 8.4 Model Substitution

An agent MAY change its backing model between any two events. The stream is
unaffected: no session state exists to be lost.

The incoming model, however, does not possess the vocabulary. A lexicon is a
competence, not a configuration — it must be acquired before it can be used.
The substituting agent MUST:

1. Emit ACQUIRE, or resolve the current CHECKPOINT, to obtain live symbols.
2. Establish competence over the symbols it intends to use, by loading
   groundings and OPTIONALLY by round-trip challenge.
3. Emit ATTEST reflecting its actual, possibly reduced, competence.

Partial competence is expected and MUST be representable. An agent competent
in 80% of the lexicon is a useful participant; §8.3 covers the remainder at
runtime. Implementations MUST NOT treat acquisition as pass/fail.

An agent whose competence has *narrowed* after substitution MUST emit ATTEST
with `DECLINED` for symbols it no longer holds. Competence per agent is
grow-only within the fold (§6.4); `DECLINED` is therefore recorded as a
distinct assertion, not as a retraction.

---

## 9. Semantic Drift

This is the open problem and implementers should not be misled about it.

Passing a round-trip challenge proves an agent decodes a symbol. It does not
prove the agent attaches the same meaning. If one agent's `urgency 4` fires at
four hours and another's at forty, both decode SID `88b1c07d` correctly, both
ATTEST `DEMONSTRATED`, and they miscommunicate silently. Grounding text
constrains this but does not close it, because natural language is exactly the
imprecision ALP is trying to escape.

Human language has this failure too and survives it through **repair**: the
misunderstanding surfaces downstream and participants backtrack. ALP therefore
makes repair a first-class message rather than pretending the problem is
solved.

`REGROUND` carries:

| Field | Type | Description |
|---|---|---|
| `subject` | SID | The symbol suspected of divergence |
| `evidence` | LIST\<EID\> | Events exhibiting the suspected mismatch |
| `reading` | text | The sender's operative interpretation |
| `proposal` | SID | OPTIONAL. A newly minted superseding symbol. |

REGROUND is not an error. It is an expected part of a long conversation, and
implementations SHOULD surface it rather than suppress it. A stream in which
REGROUND never occurs over thousands of events is more likely
drift-accumulating than drift-free.

Detection remains unsolved. Implementations SHOULD monitor for behavioral
divergence on shared symbols and MAY use periodic challenge sampling, but ALP
specifies no detection mechanism.

---

## 10. Security Considerations

### 10.1 Truncation Collisions

`SID-64` and `SID-96` are attackable by an adversary who can mint symbols: a
collision lets a malicious definition impersonate a trusted one. Streams with
untrusted participants MUST use `SID-128` or wider, and SHOULD use `SID-256`.

### 10.2 Lexicon Growth as Denial of Service

The lexicon is grow-only and unauthenticated minting is cheap. An adversary
can exhaust receiver memory with AMEND floods. Implementations MUST rate-limit
AMEND per author and SHOULD cap lexicon size, emitting `E_LEXICON_FULL` rather
than degrading.

### 10.3 Grounding Poisoning

Because SID is the hash of the Definition Record and the grounding is inside
that record, groundings are self-authenticating. A receiver MUST verify that
supplied definitions hash to the requested SID and MUST reject mismatches with
`E_SID_MISMATCH`.

Consequently an attacker cannot alter an existing symbol's meaning. It can
only mint a *different* symbol with a misleading grounding and induce use of
it, which is detectable at the SID level and is why Labels are explicitly
non-identifying (§3.1).

### 10.4 EXPAND Amplification

An adversary may request expansion of many symbols to force expensive
responses. Implementations SHOULD rate-limit GROUND per requester and MAY
require ATTEST before honoring bulk EXPAND.

### 10.5 Error Codes

| Code | Name | Meaning |
|---|---|---|
| 0x01 | `E_VERSION` | Unsupported protocol version |
| 0x02 | `E_NONCANONICAL` | Canonical encoding violated |
| 0x03 | `E_SID_MISMATCH` | Definition does not hash to claimed SID |
| 0x04 | `E_UNKNOWN_PARENT` | Referenced parent EID unresolvable |
| 0x05 | `E_LEXICON_FULL` | Lexicon cap reached |
| 0x06 | `E_RATE` | Rate limit exceeded |
| 0x07 | `E_DIVERGENCE` | Checkpoint digest mismatch |
| 0x08 | `E_PROFILE` | SID profile mismatch within stream |

### 10.6 Authenticity

ALP does not mandate signing. Where participants are mutually untrusted,
events SHOULD set `SIGNED` and carry a detached signature over the canonical
body. Because EID excludes the signature, unsigned and signed copies of an
event share identity and do not fork the DAG.

Replay is not a threat: events are content-addressed and application is
idempotent.

---

## 11. Tradeoffs

Presented for decision, not resolved here.

### 11.1 Cold Start

Hashed identity costs more bytes than integer field numbers, and learn-on-
demand front-loads grounding transmission. Short conversations over a cold
lexicon will run worse than plain natural language. The crossover depends on
symbol reuse rate. **Decision:** whether to ship pre-seeded domain lexicons,
which restores a coordination dependency at setup time in exchange for
eliminating cold start.

### 11.2 Checkpoint Frequency

Frequent CHECKPOINT means fast joins and cheap replacement, at the cost of
stream volume — checkpoints are the largest events in the protocol. Infrequent
CHECKPOINT means a lean stream and slow, expensive joins. **Decision:** fixed
interval, size-triggered, or on-demand only.

### 11.3 Competence State

Per-symbol competence tracking means every sender holds a model of every
receiver. This is O(agents × symbols) and goes stale across model
substitutions. **Decision:** maintain estimates and accept staleness, or drop
estimation entirely and rely purely on §8.3 expansion, trading bandwidth for
simplicity.

### 11.4 Compaction

The lexicon only grows. Long-lived streams accumulate superseded symbols
indefinitely. Compaction is the one operation that reintroduces the
resolvability problem the design eliminates: dropping a symbol renders every
historical event using it uninterpretable. **Decision:** never compact and
accept unbounded growth; or compact live state while retaining a cold archive
of dropped definitions; or accept lossy history beyond a horizon. This is the
most consequential open issue in the specification.

### 11.5 DAG Overhead

Parent references cost bytes per event and storage grows with fan-in. A linear
log is cheaper but requires a coordinator and cannot represent concurrency.
**Decision:** DAG everywhere, or DAG only for multi-writer streams with a
linear fast path for two-party streams.

---

## 12. Open Issues

1. **Drift detection** (§9) has no specified mechanism. Repair is expressible;
   noticing the need for it is not.
2. **Compaction** (§11.4) has no safe formulation.
3. **Cross-stream lexicon reuse.** SIDs are globally unique by construction, so
   symbols are portable between streams. No transfer mechanism is specified.
4. **Competence transitivity.** If A trusts B's ATTEST and B trusts C's, A has
   no basis to trust C's. Undefined.
5. **Constraint language** (§3.1 `c`) is unspecified beyond range and enum.

---

## Appendix A: Minimal Exchange

Agent A holds `urgency`. Agent B has just replaced its model and holds nothing.

```
%alp/t 1

@0001 JOIN            by #a000  at 2026-08-31T14:00:00Z
  (competence 0)

@0002 ASSERT          by #a000  at 2026-08-31T14:00:02Z
<- 0001
  (#88b1~urgency 4)

@0003 EXPAND          by #b000  at 2026-08-31T14:00:02Z
<- 0002
  (unknown #88b1)

@0004 GROUND          by #a000  at 2026-08-31T14:00:03Z
<- 0003
  !88b1c07d "urgency" CONCEPT
  = "Operator-facing priority. Integer 0-4. 4 pages on-call immediately."
  ? range 0 4

@0005 ATTEST          by #b000  at 2026-08-31T14:00:03Z
<- 0004
  (#88b1 HELD)
```

Event `0002` is not retransmitted. B buffered it, and applies it on receipt of
`0004`. Every later use of `#88b1` in this stream costs 17 bytes at
`SID-128`.

---

## Appendix B: Frame Type Summary

| Type | Code | Payload |
|---|---|---|
| `JOIN` | 0x01 | `competence:LIST<SID>`, `caps:MAP` |
| `LEAVE` | 0x02 | `reason:TEXT` (optional) |
| `ASSERT` | 0x03 | `LIST<(SID, Value)>` |
| `AMEND` | 0x04 | `LIST<DefinitionRecord>` |
| `EXPAND` | 0x05 | `unknown:LIST<SID>` |
| `GROUND` | 0x06 | `LIST<DefinitionRecord>` |
| `REGROUND` | 0x07 | `subject:SID`, `evidence:LIST<EID>`, `reading:TEXT`, `proposal:SID?` |
| `ACQUIRE` | 0x08 | `offer:LIST<SID>`, `challenge:LIST<(SID, Value)>?` |
| `ATTEST` | 0x09 | `LIST<(SID, level:u8)>` |
| `CHECKPOINT` | 0x0A | see §6.3 |
| `ERROR` | 0x0B | `code:u8`, `subject:REF?`, `detail:TEXT` |

---

## Appendix C: License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this specification and associated documentation files (the "Specification"),
to deal in the Specification without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Specification, and to permit persons to whom the
Specification is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Specification.

THE SPECIFICATION IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SPECIFICATION OR THE USE OR OTHER DEALINGS IN
THE SPECIFICATION.
