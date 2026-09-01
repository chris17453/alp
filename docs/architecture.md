# Architecture

```
English ──translate──▶ Composition tree + bound literals ──▶ ASSERT / AMEND events
                                   │                                │
                             realize (English out)           Stream (causal DAG, fold)
                                   │                                │
                                script ◀────── render / anim ◀──── alpt (text) · alpb (binary)
```

| module | responsibility | depends on |
|---|---|---|
| `alpb` | canonical TLV codec; `Pid`, `Ref`; strict canonical-form errors | — |
| `inventory` | primitive inventory v2, classes, roles, codepoints | `alpb` |
| `composition` | `Composition` (head, modifier set, ordered roles, residue, gloss), canonical bytes, SID, transliteration parser | `alpb`, `inventory` |
| `events` | `Event`/frames, EIDs, `Stream` (frontier, fold, reprofile, verify), payload conventions | `composition` |
| `alpt` | ALP/T writer + parser, lossless round-trip | `events` |
| `peer` | a participant: buffering/EXPAND/GROUND, attestation, checkpoints, rate limits | `events` |
| `translate` | English → trees (compositional) and the RFC's simple front end | `composition` |
| `realize` | trees → English by reverse lexicon | `translate` |
| `script` | the character composer: stroke pen, layout, palettes, running text, chart, key | `composition` |
| `anim` | stroke-budgeted frames; write / pulse / trace; title sequence; GIF/MP4 | `script` |
| `svg` | vector backend for the script | `script` |
| `render` | documents (PNG/PDF): transcripts, per-utterance rows, stream audits | `script`, `alpt` |
| `lexicon` | synonymy-fork scan | `composition` |
| `cli` | `alp …` | everything |

Invariants:

* A SID depends only on the canonical composition (gloss excluded); nothing in `script`, `render` or `anim` may influence a hash.
* ALP/T ↔ ALP/B is byte-exact; `alp verify` proves it for any stream.
* The inventory is closed per version; adding a primitive is `INVENTORY_VERSION += 1`.
* `Peer` never discards an event it cannot resolve; it buffers and asks (§9.3).
