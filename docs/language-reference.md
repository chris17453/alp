# ALP language reference

The Agent Lexicon Protocol as implemented in this repository: the language
(compositions over a closed primitive inventory), the text form (ALP/T), the
value layer (literals bound at assertion), the script, and the protocol
events.  Section numbers refer to RFC-ALP-001 v1.1.

## 1. Compositions (§3, §5)

A **symbol** is a tree.  Its identity is `SHA-256(canonical ALP/B(tree))`.

```
composition := head modifier* role* residue?
head        := one ontological primitive           $ENTITY … $GROUP   (12)
modifier    := primitive of any non-structural class, or a nested composition
role        := :ROLE node        node := primitive | (composition) | #sid
residue     := ~"english that would not compose"   (hashed; avoid)
gloss       := = "advisory english"                (not hashed)
```

Rules that decide identity:

* modifiers are a **set** — `$PROPERTY.HIGH.FUTURE` ≡ `$PROPERTY.FUTURE.HIGH`
* roles are **ordered by code** and positional — swapping ARG0/ARG1 is a
  different symbol
* gloss never changes the SID; residue always does
* depth ≤ 8, ≤ 12 modifiers per node, no structural primitive as head/modifier

Write them in ALP/T composition syntax and hash with `alp compose`:

```
$RELATION.CAUSE.INFERRED :ARG0 ($EVENT.PAST.PUNCTUAL) :ARG1 ($STATE.NEGATE.BAD :SCOPE $PROCESS)
```

## 2. Inventory v2 (§4)

Twelve **heads** — what kind of thing:

| | | | |
|---|---|---|---|
| ENTITY a thing that persists | PROCESS something unfolding | PROPERTY an attribute | RELATION a tie |
| QUANTITY a magnitude | AGENT an actor | STATE a condition | PLACE a location |
| MOMENT a time | SIGN information | EVENT a bounded occurrence | GROUP a collection |

Modifier classes (the script draws each class in its own way and colour):

| class | members | script |
|---|---|---|
| modal 0x01 | AFFIRM NEGATE POSSIBLE NECESSARY DESIRED HYPOTHETICAL PERMITTED FORBIDDEN | enclosure around the head (NEGATE: slash) — violet |
| scalar 0x02 | NONE SOME ALL LOW MID HIGH EXTREME BOUNDED UNBOUNDED INCREASE DECREASE | head's scale / fill / brackets / tips — amber |
| temporal 0x03 | PAST NOW FUTURE DURATIVE PUNCTUAL BEFORE DURING AFTER REPEAT BEGIN END | ground line under the head — teal |
| causal 0x04 | CAUSE ENABLE PREVENT CORRELATE DEPEND TRIGGER | connector on the right — red |
| epistemic 0x05 | KNOWN BELIEVED INFERRED UNKNOWN CONTESTED OBSERVED PREDICTED | head's stroke (heavy / dashed / dotted / doubled / eye) — green |
| illocutionary 0x06 | ASSERT REQUEST COMMIT QUERY WARN REFUSE PROPOSE ACKNOWLEDGE | left radical — magenta |
| valence 0x07 | GOOD BAD REQUIRED OPTIONAL SAFE HARM COST BENEFIT | crown above — gold |
| relational 0x09 | EQUAL GREATER LESS PART HAS MEMBER NEAR INSIDE OUTSIDE ABOVE BELOW TOWARD | connector on the right — salmon |
| deictic 0x0A | SELF ADDRESSEE THIS THAT WHICH SAME OTHER EACH ANY GENERIC | inner mark, upper — blue |
| logical 0x0B | AND OR XOR IFF IMPLIES ONLY EXCEPT | corner marks — grey-blue |
| affect 0x0C | JOY FEAR ANGER TRUST SURPRISE DISGUST SADNESS CALM | inner mark, lower — pink |
| structural 0x08 | REF SCOPE_OPEN SCOPE_CLOSE SUPERSEDE RESIDUE NUM STR TIME UNIT EREF | format controls |

Roles (§5.3, extended): ARG0 agent/cause · ARG1 patient/effect · ARG2
instrument/recipient · SCOPE domain · MEASURE amount/unit · CONDITION
precondition · LOC where · TIME when · MANNER how · PURPOSE what for · SOURCE
from · GOAL to.  ARG0/ARG1 sit inside the head's lobes in the script; the
others form the role row beneath.

Idioms the translator produces and the realizer reads:

| meaning | shape |
|---|---|
| X causes Y | `$RELATION.CAUSE :ARG0 X :ARG1 Y` |
| X is greater than 5 % | `$RELATION.GREATER :ARG0 X :ARG1 ($STATE :MEASURE $QUANTITY)` + bound `ARG1/MEASURE = {n 5, u %}` |
| X or Y | `$GROUP.OR :ARG0 X :ARG1 Y` |
| if C then X | `X :CONDITION C` |
| I am afraid that P | `$AGENT.SELF.FEAR :ARG1 P` |
| a script that restarts the service | `$SIGN.PROCESS :SCOPE ($PROCESS.REPEAT.BEGIN :ARG0 $SIGN :ARG1 $PROCESS)` |
| the outage was caused by a bad deploy | `$RELATION.PAST.CAUSE :ARG0 (deploy) :ARG1 (outage)` — passives are normalised |
| hello / thanks / sorry / yes / no | `$SIGN.ACKNOWLEDGE` + ADDRESSEE.BEGIN / BENEFIT / SADNESS / AFFIRM / NEGATE |

## 3. Literals and binding (§5.4)

Symbols name concepts; **data is bound at ASSERT**.  An ASSERT payload is a
list of `(SID, value)`; the value is `true` or `{"bind": {path: literal}}`
where `path` is a role path (`"."`, `"LOC"`, `"ARG1/MEASURE"`) and a literal is
a number, a string (a name), `{"n": 4200, "u": "ms"}`, `{"t": "2026-09-01T12:00"}`,
or a `#sid` / `@eid` reference (anaphora: *it*, *that*, *the same*).

In the script literals are their own characters after the word: numerals
(wedge counts), names (cartouches with a visual hash), times, units, seals for
references — all in clay.

## 4. ALP/T (§7.6)

```
%alp/t 1 inv 2 profile SID-128 stream <hex>

!<sid> $HEAD.MOD :ROLE node …           ; a symbol
= "gloss"

@<eid> ASSERT                            ; an event
<- <parent eid> …
by #<author sid>  ; name
at 2026-08-31T14:00:00Z
  (#<sid> {"bind" {"LOC" "eu"}})         ; LIST payloads: one element per line
  key term                               ; MAP payloads: key term per line
```

Terms: `#sid` `##fullsid` `@eid` `@@fulleid` `$PRIM` `!sid $comp = "gloss"`
integers, floats, `true false null`, `"text"`, `0xhex`, `( … )` lists,
`{ k v … }` maps.  ALP/T round-trips to byte-identical ALP/B; `alp verify`
checks it.

## 5. Streams and events (§7)

Events: JOIN, LEAVE, ASSERT, AMEND, EXPAND, GROUND, REGROUND, ACQUIRE,
ATTEST, CHECKPOINT, ERROR.  Parents form a causal DAG; total order is causal
with EID tiebreak; state is a pure fold (lexicon and competence grow-only,
assertions last-writer-wins).  Truncation profiles SID-256/128/96/64; EIDs
hash the body as transmitted at the stream's profile; archives are
re-profiled to SID-256.

`alp.peer.Peer` implements the behaviours: buffer-and-EXPAND for unknown
SIDs, GROUND under rate limit and with SID verification, ATTEST HELD /
DEMONSTRATED / DECLINED, CHECKPOINT emission and independent digest
verification, model substitution.

## 6. Reading the script

1. Find the **head** (largest shape, in ink): what kind of thing.
2. Its **stroke** tells certainty (solid / heavy / dashed / dotted / doubled /
   eye); its **size and fill** tell degree.
3. An **enclosure** is modality; a **slash** is negation.
4. **Crown** above: value.  **Ground line** below: time (dot left = past,
   centre = now, right = future).
5. **Left radical**: speech act.  **Right connector**: causation or relation.
6. **Inner marks**: who (upper), feeling (lower).  **Lobes**: the two
   arguments, as seeds of their heads.  **Role row**: the other roles.
7. Following characters under the same headline are the nested arguments
   (depth dots bottom-left) and the second half of a compound.
8. Clay characters after the word are the bound data.

## 7. Commands

```
alp translate TEXT | -f FILE        English -> trees            (--stats, --json, --png/--pdf/--svg)
alp transcribe -f DOC -o DIR        document -> script + transcript + stream
alp encode / decode / export / import / verify / stats
alp render FILE|TEXT|'$COMP'        images   (--style text|each|block, --cell, --english, --mono, --frame, --svg)
alp compose '$COMP'                 SID, canonical bytes, reading, image
alp chart / key                     the character chart / the glyph key
alp forks STREAM                    synonymy-fork candidates (§12.6)
```
