#!/usr/bin/env python3
"""Two agents actually running the protocol.

A and B share a stream.  A speaks English through the translator; B holds
only the inventory.  Along the way: inline AMEND so B needs no round trip,
an ASSERT that references a symbol B has never seen (buffered, EXPAND,
GROUND, applied), a round-trip challenge earning DEMONSTRATED, a REGROUND
repair with a superseding symbol, a CHECKPOINT that B verifies, and B
replacing its model with one that lacks the affect class.

    uv run python examples/two_agents.py            # prints the transcript
    uv run python examples/two_agents.py --alpt out.alpt --png out.png
"""

from __future__ import annotations

import argparse
import sys

from alp import Composition, Stream, Translator, alpt, render
from alp.events import AttestLevel, new_stream_id
from alp.inventory import PRIMITIVES, CLASS_AFFECT
from alp.peer import Peer, PeerConfig, wire

T0 = 1788190000


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--alpt")
    ap.add_argument("--alpb")
    ap.add_argument("--png")
    ap.add_argument("--pdf")
    args = ap.parse_args(argv)

    sid = new_stream_id("two-agents")
    cfg = PeerConfig(checkpoint_every=8)
    a = Peer("alice", Stream(sid, 16), config=cfg)
    b = Peer("bob", Stream(sid, 16), config=cfg)
    pump = wire(a, b)
    tr = Translator()
    t = [T0]

    def tick() -> int:
        t[0] += 2
        return t[0]

    a.join(timestamp=tick()); b.join(timestamp=tick()); pump()

    # 1. A talks; symbols are AMENDed inline so B reads them from their composition
    for sent in ["The checkout service is down now.", "Latency is 4200ms in the eu region.",
                 "We suspect the deploy caused the outage."]:
        for tr_ in tr.translate(sent):
            a.assert_([(tr_.composition, tr_.value)], timestamp=tick())
        pump()

    # 2. A asserts about a symbol whose composition it never sent (only its SID):
    #    B buffers the event, asks, A grounds, B applies.
    secret = Composition.build("PROPERTY", "HIGH", "PUNCTUAL", "REQUIRED", gloss="urgency")
    a.know(secret)                                                  # A knows it privately
    a.assert_([(secret, 4)], timestamp=tick(), inline=False)
    pump()

    # 3. B challenges A over two symbols (ACQUIRE with a challenge list)
    known = list(b.lexicon.values())[:2]
    b._emit(b.stream.acquire("bob", offer=[], challenge=[(c, 1) for c in known], timestamp=tick()))
    pump()

    # 4. Repair: B reads urgency 4 as "page immediately"; proposes a superseding symbol
    v2 = Composition.build("PROPERTY", "EXTREME", "PUNCTUAL", "REQUIRED", supersedes=secret.sid,
                           gloss="operator priority at the ceiling: pages on-call immediately")
    ev_assert = [e for e in b.stream.events if e.type.name == "ASSERT"][-1]
    b.reground(secret, [ev_assert.eid_ref], "bob pages on-call at 4; alice appears to page at 3", proposal=v2, timestamp=tick())
    pump()

    # 5. Checkpoint from A; B verifies the digest independently
    a.checkpoint(timestamp=tick()); pump()

    # 6. B swaps its model for one without the affect class, re-attests, declines
    b.replace_model([p for p in PRIMITIVES.values() if p.cls != CLASS_AFFECT], timestamp=tick()); pump()
    for tr_ in tr.translate("I am afraid the database has no memory."):
        a.assert_([(tr_.composition, tr_.value)], timestamp=tick())
    pump()

    # -- report ---------------------------------------------------------------
    same = a.stream.state.digest() == b.stream.state.digest()
    print(f"events: alice={len(a.stream)} bob={len(b.stream)}  lexicon: {len(a.lexicon)}/{len(b.lexicon)}  "
          f"converged: {same}  pending@bob: {len(b.pending)}  declined@bob: {len(b.declined)}")
    print()
    for line in a.log + b.log:
        print(line)
    print()
    print("bob's hydration of the state:")
    for line in b.hydrate():
        print("  " + line)
    text = alpt.dumps(b.stream)
    if args.alpt:
        open(args.alpt, "w").write(text)
    if args.alpb:
        open(args.alpb, "wb").write(b.stream.to_bytes())
    if args.png or args.pdf:
        doc = render.doc_for_stream(b.stream, title="two agents — bob's view", alpt_text=text)
        if args.png:
            render.save_png(doc, args.png)
        if args.pdf:
            render.save_pdf(doc, args.pdf, title="two agents")
    return 0 if same else 1


if __name__ == "__main__":
    sys.exit(main())
