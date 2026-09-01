#!/usr/bin/env python3
"""Generate the worked conversation of RFC-ALP-001 Appendix D.

A two-agent incident exchange exercising every event type, including a
mid-stream model substitution, a concurrent fork, and a repair.  All SIDs and
EIDs are really computed.  Output: ALP/T on stdout; ``--alpb``, ``--png`` and
``--pdf`` write the other projections.

    uv run python examples/build_conversation.py > conversation.alpt
    uv run python examples/build_conversation.py --pdf conversation.pdf
"""

from __future__ import annotations

import argparse
import sys

from alp import Composition, Stream, alpt, new_stream_id, render
from alp.events import AttestLevel
from alp.inventory import PRIMITIVES
from alp.translate import SimpleTranslator

CLOCK = 1788186000


def build(width: int = 16) -> tuple[Stream, dict[bytes, str]]:
    tr = SimpleTranslator()   # the RFC's own front end, so SIDs match Appendix D
    s = Stream(new_stream_id("rfc-alp-001 appendix d"), width)
    notes: dict[bytes, str] = {}
    inventory = list(PRIMITIVES.values())

    def at(offset: int) -> int:
        return CLOCK + offset

    outage = tr.translate("the checkout service is down now").composition.with_gloss(
        "checkout service is not running, as of now")
    latency = tr.translate("latency is spiking in the eu region").composition.with_gloss(
        "latency rising, eu region")
    deploy = Composition.build("EVENT", "PUNCTUAL", "PAST", residue="deploy 4471")
    blame = Composition.build("RELATION", "CAUSE", "INFERRED", "CONTESTED",
                              roles={"ARG0": deploy, "ARG1": outage.sid},
                              gloss="deploy 4471 is the suspected but disputed cause of the outage")
    reversed_blame = Composition.build("RELATION", "CAUSE", "INFERRED", "CONTESTED",
                                       roles={"ARG0": outage.sid, "ARG1": deploy},
                                       gloss="the outage is the suspected cause of deploy 4471 (arguments swapped, a different symbol)")
    urgency_v1 = Composition.build("PROPERTY", "HIGH", "PUNCTUAL", "REQUIRED",
                                   gloss="operator priority, high, needs action now")
    urgency_v2 = Composition.build("PROPERTY", "EXTREME", "PUNCTUAL", "REQUIRED", supersedes=urgency_v1.sid,
                                   gloss="operator priority at the ceiling, pages on-call immediately")
    blast = Composition.build("QUANTITY", "UNBOUNDED", "UNKNOWN", roles={"SCOPE": "GROUP", "MEASURE": "AGENT"},
                              gloss="unbounded and unestablished count of affected users")
    rollback = Composition.build("PROCESS", "PAST", "PERMITTED", roles={"ARG1": "STATE"},
                                 gloss="returning to a prior state is allowed")
    resolved = Composition.build("EVENT", "END", "NOW", "OBSERVED", roles={"SCOPE": outage.sid},
                                 gloss="the outage has ended, directly observed")

    def note(e, text):
        notes[e.eid] = text
        return e

    e01 = note(s.join("a000", competence=inventory, timestamp=at(0)),
               "a000 joins holding the closed inventory. Note it attests the inventory, not a vocabulary.")
    e02 = s.join("b000", competence=inventory, timestamp=at(2))
    e03 = note(s.amend("a000", [outage, latency], timestamp=at(6)),
               "Two symbols minted. b000 has never seen either and needs no round trip: it reads them from the composition.")
    e04 = s.assert_("a000", [(outage, True), (latency, "p99 4200ms")], timestamp=at(8))
    e05 = s.attest("b000", [(outage, AttestLevel.HELD), (latency, AttestLevel.HELD)], timestamp=at(10))
    e06 = note(s.amend("b000", [blast], timestamp=at(14)),
               "b000 mints independently. No coordination, no renumbering, no collision.")
    e07 = s.assert_("b000", [(blast, "unknown")], timestamp=at(16))
    e08 = note(s.amend("a000", [blame], parents=[e07.eid_ref], timestamp=at(20)),
               "Ordered roles. The next event shows why that matters.")
    e09 = note(s.amend("b000", [reversed_blame], parents=[e07.eid_ref], timestamp=at(21)),
               "Concurrent with the previous event: both name e07 as parent, neither observed the other. "
               "Swapping ARG0 and ARG1 yields a different SID, per section 5.3.")
    e10 = note(s.amend("a000", [urgency_v1], parents=[e08.eid_ref, e09.eid_ref], timestamp=at(26)),
               "This event merges the fork by naming both concurrent events as parents.")
    e11 = s.assert_("a000", [(urgency_v1, 3)], timestamp=at(28))
    e12 = note(s.reground("b000", urgency_v1, [e11.eid_ref],
                          "b000 pages on-call at level 3; a000 appears to page at 4 only",
                          proposal=urgency_v2, timestamp=at(34)),
               "Repair. Both agents decode the symbol correctly and still disagree about what it means. "
               "This is the residual problem of section 10, surfaced rather than hidden.")
    e13 = note(s.amend("a000", [urgency_v2], timestamp=at(38)),
               "Supersession, not redefinition. urgency_v1 remains decodable forever; e11 above still reads correctly.")
    e14 = note(s.checkpoint("a000", timestamp=at(42)),
               "Checkpoint so a replacement model can join without replaying history.")
    e15 = s.leave("b000", "model substitution", timestamp=at(46))
    e16 = note(s.join("b001", competence=inventory, caps={"resume": alpt.fmt_term(e14.payload["digest"])}, timestamp=at(48)),
               "b000 is replaced by a different model. It acquires the 76 primitives once, and every symbol in the "
               "stream, past and future, becomes readable.")
    e17 = note(s.expand("b001", [blame], timestamp=at(52)),
               "The one thing composition does not cover: blame carries residue (\"deploy 4471\"), "
               "which is English and therefore not derivable.")
    e18 = s.ground("a000", [blame], timestamp=at(54))
    e19 = s.attest("b001", [(blame, AttestLevel.HELD)], timestamp=at(56))
    e20 = s.amend("a000", [rollback], timestamp=at(60))
    e21 = s.assert_("a000", [(rollback, True)], timestamp=at(62))
    e22 = s.amend("b001", [resolved], timestamp=at(70))
    e23 = note(s.assert_("b001", [(resolved, True)], timestamp=at(72)),
               "Stream ends. Every event above remains interpretable by anything holding inventory version 1, "
               "with no registry and no live participant.")
    return s, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--profile", type=int, default=16, help="SID width in bytes (32/16/12/8)")
    ap.add_argument("--alpb", help="write ALP/B frames")
    ap.add_argument("--png", help="write a PNG audit image")
    ap.add_argument("--pdf", help="write a PDF audit document")
    ap.add_argument("--quiet", action="store_true", help="do not print ALP/T")
    args = ap.parse_args(argv)
    s, notes = build(args.profile)
    text = alpt.dumps(s, notes=notes)
    assert alpt.loads(text).stream.to_bytes() == s.to_bytes()
    if not args.quiet:
        sys.stdout.write(text)
    if args.alpb:
        open(args.alpb, "wb").write(s.to_bytes())
    if args.png or args.pdf:
        doc = render.doc_for_stream(s, title="RFC-ALP-001 Appendix D — worked conversation", alpt_text=text)
        if args.png:
            render.save_png(doc, args.png)
        if args.pdf:
            render.save_pdf(doc, args.pdf, title="RFC-ALP-001 Appendix D")
    return 0


if __name__ == "__main__":
    sys.exit(main())
