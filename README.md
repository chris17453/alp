# alp — Agent Lexicon Protocol toolkit

A Python implementation of **RFC-ALP-001 v1.1** (`docs/rfc-alp-001.pdf`): a
protocol in which machine agents compose meaning from a closed inventory of 76
semantic primitives, identify each composed symbol by the hash of its
composition, and exchange symbols over an append-only causal event stream.

The package gives you:

| Layer | Module | What it does |
|---|---|---|
| L2 wire | `alp.alpb` | Canonical ALP/B TLV codec (CBOR-shaped, §7.5) with strict `E_NONCANONICAL` checking |
| L1 semantics | `alp.inventory`, `alp.composition` | The 76 primitives, composition records, SID derivation, ALP/T composition syntax |
| front end | `alp.translate` | Rule-based English → composition translator with residue reporting (§5.5, Appendix E) |
| stream | `alp.events` | Frames, EIDs, causal DAG, frontier, stateless fold, CHECKPOINT digests, truncation profiles |
| archive | `alp.alpt` | ALP/T text projection, lossless in both directions (§7.6) |
| script | `alp.render` | The §6 script rendered as visual blocks → PNG (Pillow) and PDF (reportlab) |
| CLI | `alp.cli` | `alp translate / encode / decode / export / import / verify / render / compose / inventory / lexicon / stats` |

## Install

```sh
uv sync                 # creates .venv with pillow + reportlab
uv run alp --help
uv run pytest           # 40-odd tests incl. RFC reference SIDs and byte-level round trips
```

## Quick tour

```sh
# English -> compositions (no stream), with the residue metric the RFC asks for
$ uv run alp translate "urgency is high and the deadline is tomorrow" --stats
037fac5d  $PROPERTY.HIGH.PUNCTUAL.REQUIRED ~"deadline"
          residue: deadline
1 utterances, 0 fully composed, token residue rate 14.3%

# English -> ALP/B stream, with images made on the fly
$ uv run alp encode -f incident.txt -o incident.alpb --png incident.png --pdf incident.pdf --stats

# ALP/B <-> ALP/T (the text form is a lossless projection; import reproduces identical bytes)
$ uv run alp export incident.alpb -o incident.alpt
$ uv run alp import incident.alpt -o again.alpb && cmp incident.alpb again.alpb

# ALP -> English (stored glosses, or --readings for text generated from the primitives)
$ uv run alp decode incident.alpb --events

# audit a stream: hashes, canonical form, parents, round-trip
$ uv run alp verify incident.alpt

# render anything: English text, an .alpt/.alpb stream, or a bare composition
$ uv run alp render incident.alpt --pdf audit.pdf
$ uv run alp render '$RELATION.CAUSE.INFERRED :ARG0 ($EVENT.PAST ~"deploy 4471") :ARG1 $STATE' --png blame.png

# hash a composition written by hand
$ uv run alp compose '$PROPERTY.HIGH.PUNCTUAL.REQUIRED' --gloss urgency
sid        037fac5ded0722580cd56253a08f173cc7fca8d75834d7789bc43a06ccbe8bfb
...

# the primitive chart as an image
$ uv run alp inventory --png inventory.png
```

`examples/build_conversation.py` regenerates the RFC's Appendix D worked
conversation with real hashes (`--pdf` for the audit document).

## Library

```python
from alp import Composition, Translator, Stream, alpt, render

urgency = Composition.build("PROPERTY", "HIGH", "PUNCTUAL", "REQUIRED", gloss="urgency")
urgency.sid_hex(8)                # '037fac5d'  (matches the RFC's reference implementation)
str(urgency)                      # '$PROPERTY.HIGH.PUNCTUAL.REQUIRED'
urgency.script()                  # ''  (PUA codepoints, §6.3)
urgency.reading()                 # 'a property that is high, instantaneous, required'

s = Stream(sid_width=16)          # SID-128 transport profile
s.join("a000", competence=list(alp.PRIMITIVES.values()))
s.amend("a000", [urgency])
s.assert_("a000", [(urgency, 4)])
s.checkpoint("a000")
frames = s.to_bytes()             # ALP/B
text = alpt.dumps(s)              # ALP/T
assert alpt.loads(text).stream.to_bytes() == frames

render.save_pdf(render.doc_for_stream(s, alpt_text=text), "stream.pdf")
```

## Implementation decisions

The RFC leaves a few things open; these are the choices made here, all
documented in the module docstrings:

* **EIDs are hashed over the body as transmitted at the stream's profile.**
  A receiver can verify an EID with no state.  Changing profile re-hashes
  (`Stream.reprofile`, `alp export --archive` for the SID-256 archive form).
  A stream id is not an event and is zero-padded when widened.
* **Authors are symbols.** `by #sid` is the SID of `$AGENT ~"name"`, so an
  author can be AMENDed into the lexicon like any other symbol.
* **ALP/T extensions** for losslessness: `profile`/`stream` header options,
  `fl`/`sig` lines, `@hex` EID terms, `{k v}` maps, and a `>` raw-payload
  escape.  The RFC's own grammar is a subset.
* **Payload shapes** follow the 1.0 Appendix B table: LIST for ASSERT / AMEND /
  GROUND / ATTEST, a keyed MAP for everything else.
* **The script is drawn procedurally** (no conforming font exists): head shape
  per ontological primitive, modifier marks in their §6.2 class positions,
  roles stacked beneath, residue as a ribbon.  The ASCII transliteration is
  always printed alongside, as §6.5 requires.
* The English front end is the RFC's reference one, deliberately weak; its
  residue rate is the quality metric (§14.4).

## Layout

```
src/alp/        package
docs/           RFC-ALP-001 (v1.1 PDF; v1.0 markdown for history)
examples/       Appendix D generator
tests/          pytest suite
```

MIT licensed, like the specification.
