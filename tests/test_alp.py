import math
import subprocess
import sys

import pytest

from alp import alpb, alpt, render
from alp.alpb import Pid, Ref, NonCanonical, REF_SID, REF_SID_FULL
from alp.composition import Composition, CompositionError, parse, verify, SIDMismatch
from alp.events import AttestLevel, Stream, new_stream_id, agent_sid, fold, toposort
from alp.inventory import PRIMITIVES, ROLES, pid, by_class, CLASS_ONTOLOGICAL
from alp.translate import Translator, stats


# -- ALP/B -------------------------------------------------------------------

@pytest.mark.parametrize("v", [0, 23, 24, 255, 256, 65535, 65536, 2**32, -1, -25, -300,
                               1.5, True, False, None, b"", b"xy", "", "héllo", "Å",
                               [1, [2, [3]]], {"b": 1, "a": [Pid(5)]}, Pid(0x0205),
                               Ref(REF_SID_FULL, b"\x01" * 32)])
def test_alpb_roundtrip(v):
    b = alpb.encode(v)
    d = alpb.decode(b)
    if isinstance(v, str):
        assert d == alpb.nfc(v)
    else:
        assert d == v


def test_alpb_nan_and_float():
    b = alpb.encode(float("nan"))
    assert b == b"\xfb\x7f\xf8\x00\x00\x00\x00\x00\x00"
    assert math.isnan(alpb.decode(b))
    assert alpb.decode(alpb.encode(3.25)) == 3.25


def test_alpb_canonical_rejections():
    with pytest.raises(NonCanonical):
        alpb.decode(b"\x18\x05")                      # 5 encoded with 1-byte arg
    with pytest.raises(NonCanonical):
        alpb.decode(b"\xa2\x61b\x01\x61a\x02")        # keys out of order
    with pytest.raises(NonCanonical):
        alpb.decode(b"\xa2\x61a\x01\x61a\x02")        # duplicate keys
    with pytest.raises(NonCanonical):
        alpb.decode(b"\x9f\xff")                      # indefinite length
    with pytest.raises(NonCanonical):
        alpb.decode(b"\x63" + "é".encode())     # non-NFC text


def test_alpb_profile_truncation():
    r = Ref(REF_SID, b"\xab" * 32)
    assert len(alpb.encode(r, 16)) == 17
    assert alpb.decode(alpb.encode(r, 16), 16).data == b"\xab" * 16
    assert len(alpb.encode(r.full(), 16)) == 33   # full refs ignore the profile


def test_uvarint():
    for n in (0, 1, 127, 128, 300, 2**40):
        b = alpb.uvarint_encode(n)
        assert alpb.uvarint_decode(b) == (n, len(b))


# -- inventory / composition ---------------------------------------------------

def test_inventory_size():
    assert len(PRIMITIVES) == 76
    assert pid("NEGATE").codepoint == ""
    assert pid("REF").code == 0x0800


def test_reference_sids_match_rfc_appendix():
    """SIDs computed by the RFC's reference script (Appendix D) must agree."""
    tr = Translator()
    assert tr.translate("the checkout service is down now").composition.sid_hex(8) == "e839ae84"
    assert tr.translate("latency is spiking in the eu region").composition.sid_hex(8) == "19a85458"
    urgency = Composition.build("PROPERTY", "HIGH", "PUNCTUAL", "REQUIRED")
    assert urgency.sid_hex(8) == "037fac5d"
    v2 = Composition.build("PROPERTY", "EXTREME", "PUNCTUAL", "REQUIRED", supersedes=urgency.sid)
    assert v2.sid_hex(8) == "da27c380"
    blast = Composition.build("QUANTITY", "UNBOUNDED", "UNKNOWN", roles={"SCOPE": "GROUP", "MEASURE": "AGENT"})
    assert blast.sid_hex(8) == "7059f133"


def test_canonicalisation_invariants():
    a = Composition.build("PROPERTY", "HIGH", "FUTURE")
    b = Composition.build("PROPERTY", "FUTURE", "HIGH", "HIGH")
    assert a.sid == b.sid                                             # modifier set, idempotent
    left = Composition.build("RELATION", "CAUSE", roles={"ARG0": "EVENT", "ARG1": "STATE"})
    right = Composition.build("RELATION", "CAUSE", roles={"ARG0": "STATE", "ARG1": "EVENT"})
    assert left.sid != right.sid                                      # roles ordered
    assert Composition.build("STATE", "BAD", gloss="x").sid == Composition.build("STATE", "BAD", gloss="y").sid
    assert Composition.build("STATE", "BAD", residue="k").sid != Composition.build("STATE", "BAD").sid
    with pytest.raises(CompositionError):
        Composition.build("HIGH")                                     # non-ontological head
    with pytest.raises(CompositionError):
        Composition.build("STATE", "REF")                             # structural modifier
    deep = Composition.build("STATE")
    with pytest.raises(CompositionError):
        for _ in range(9):
            deep = Composition.build("STATE", roles={"SCOPE": deep})


def test_transliteration_roundtrip():
    inner = Composition.build("EVENT", "PAST", "PUNCTUAL", residue='deploy "4471"')
    c = Composition.build("RELATION", "CAUSE", "INFERRED", roles={"ARG0": inner, "ARG1": Composition.build("STATE").sid})
    p = parse(c.transliterate())
    assert p.sid == c.sid
    assert Composition.from_map(alpb.decode(c.transport())).sid == c.sid
    with pytest.raises(SIDMismatch):
        verify(c, b"\x00" * 8)


def test_script_sequence():
    c = Composition.build("PROPERTY", "HIGH", roles={"SCOPE": "GROUP"}, residue="x")
    names = [p.code for p in c.primitives()]
    assert names == [0x0002, 0x0205, 0x000B, 0x0804]


# -- translator -------------------------------------------------------------------

def test_translator_residue_and_stats():
    tr = Translator()
    rs = tr.translate_text("The checkout service is down now. Zorp blib.")
    assert rs[0].composition.residue == "checkout"
    assert rs[1].composition.head == pid("SIGN")
    st = stats(rs)
    assert st.utterances == 2 and st.residue_tokens > 0


# -- events / stream ----------------------------------------------------------------

def _demo_stream(width):
    tr = Translator()
    rs = tr.translate_text("Urgency is high. The checkout service is down now.")
    comps = [r.composition for r in rs]
    s = Stream(new_stream_id("t"), width)
    s.join("a000", competence=list(PRIMITIVES.values()), timestamp=1)
    s.amend("a000", comps, timestamp=2)
    s.assert_("a000", [(comps[0], 3), (comps[1], True)], timestamp=3)
    s.attest("b000", [(comps[0], AttestLevel.HELD), (pid("ENTITY"), AttestLevel.DEMONSTRATED)], timestamp=4)
    s.reground("b000", comps[0], [s.events[2].eid_ref], "we page at 3", timestamp=5)
    s.expand("b000", [comps[1]], timestamp=6)
    s.error("a000", 6, "slow", timestamp=7)
    s.leave("b000", "bye", timestamp=8)
    s.checkpoint("a000", timestamp=9)
    return s, comps


@pytest.mark.parametrize("width", [32, 16, 12, 8])
def test_stream_binary_and_text_roundtrip(width):
    s, comps = _demo_stream(width)
    data = s.to_bytes()
    s2 = Stream.from_bytes(data)                    # profile sniffed
    assert s2.sid_width == width
    assert s2.to_bytes() == data
    assert [e.eid for e in s2.ordered()] == [e.eid for e in s.ordered()]
    assert s2.state.digest() == s.state.digest()
    assert s2.verify() == []
    txt = alpt.dumps(s)
    d = alpt.loads(txt)
    assert d.stream.to_bytes() == data              # ALP/T is a lossless projection
    assert alpt.dumps(d.stream) == txt


def test_reprofile_to_archive():
    s, _ = _demo_stream(16)
    a = s.reprofile(32)
    assert a.sid_width == 32 and len(a) == len(s)
    assert a.verify() == []
    assert set(a.lexicon()) == set(s.lexicon())


def test_fold_is_idempotent_and_order_independent():
    s, comps = _demo_stream(32)
    evs = s.ordered()
    st1 = fold(evs)
    st2 = fold(reversed(evs))
    st3 = fold(evs + evs)
    assert st1.assertions == st2.assertions == st3.assertions
    assert st1.digest() == st2.digest() == st3.digest()
    assert set(st1.lexicon) == {c.sid for c in comps}


def test_concurrent_events_and_tiebreak():
    s = Stream(new_stream_id("c"), 32)
    root = s.emit("JOIN", "a", {"competence": [], "caps": {}}, timestamp=1)
    x = s.emit("ASSERT", "a", [[Ref(REF_SID, b"\x01" * 32), 1]], parents=[root.eid_ref], timestamp=2)
    y = s.emit("ASSERT", "b", [[Ref(REF_SID, b"\x01" * 32), 2]], parents=[root.eid_ref], timestamp=2)
    assert set(s.frontier) == {x.eid_ref, y.eid_ref}
    order = toposort(s.events)
    assert order[0] is root and sorted([x.eid, y.eid]) == [order[1].eid, order[2].eid]
    winner = max([x, y], key=lambda e: e.eid)
    assert s.state.assertions[b"\x01" * 32] == winner.payload[0][1]


def test_alpt_sid_mismatch_detected():
    s, _ = _demo_stream(32)
    txt = alpt.dumps(s).replace("$PROPERTY.HIGH.PUNCTUAL.REQUIRED", "$PROPERTY.LOW.PUNCTUAL.REQUIRED", 1)
    with pytest.raises(alpt.ALPTError):
        alpt.loads(txt)


def test_alpt_parse_composition_forms():
    c = alpt.parse_composition('$MOMENT.FUTURE.PUNCTUAL.BOUNDED = "deadline"')
    assert c.gloss == "deadline" and c.sid_hex(8) == Composition.build("MOMENT", "FUTURE", "PUNCTUAL", "BOUNDED").sid_hex(8)
    c2 = alpt.parse_composition(f"!{c.sid_hex()} {c.transliterate()}")
    assert c2.sid == c.sid


# -- render -----------------------------------------------------------------------------

def test_render_png_and_pdf(tmp_path):
    comps = [Composition(p) for p in by_class(CLASS_ONTOLOGICAL)]
    comps.append(Composition.build("RELATION", "CAUSE", "INFERRED",
                                   roles={"ARG0": Composition.build("EVENT", "PAST", residue="deploy"), "ARG1": "STATE"}))
    img = render.render_block(comps[-1])
    assert img.width > 100 and img.height > 100
    doc = render.doc_for_compositions(comps, title="t")
    out = render.save_png(doc, str(tmp_path / "a.png"))
    assert (tmp_path / "a.png").stat().st_size > 1000
    pdf = render.render_pdf(doc)
    assert pdf.startswith(b"%PDF")
    s, _ = _demo_stream(16)
    render.save_pdf(render.doc_for_stream(s, alpt_text=alpt.dumps(s)), str(tmp_path / "s.pdf"))
    assert (tmp_path / "s.pdf").stat().st_size > 1000


# -- CLI -------------------------------------------------------------------------------

def _alp(*args, input=None):
    return subprocess.run([sys.executable, "-m", "alp.cli", *args], input=input, capture_output=True, text=True)


def test_cli_pipeline(tmp_path):
    r = _alp("translate", "urgency is high", "--stats")
    assert r.returncode == 0 and "037fac5d" in r.stdout
    alpb_path = tmp_path / "x.alpb"
    r = _alp("encode", "-f", "-", "-o", str(alpb_path), "--stream", "s", "--clock", "100",
             "--png", str(tmp_path / "x.png"), "--pdf", str(tmp_path / "x.pdf"), "--stats",
             input="The checkout service is down now.\nUrgency is high.")
    assert r.returncode == 0, r.stderr
    assert alpb_path.exists() and (tmp_path / "x.png").exists() and (tmp_path / "x.pdf").exists()
    r = _alp("export", str(alpb_path), "-o", str(tmp_path / "x.alpt"))
    assert r.returncode == 0
    r = _alp("import", str(tmp_path / "x.alpt"), "-o", str(tmp_path / "y.alpb"))
    assert r.returncode == 0
    assert (tmp_path / "y.alpb").read_bytes() == alpb_path.read_bytes()
    r = _alp("verify", str(tmp_path / "x.alpt"))
    assert r.returncode == 0 and r.stdout.startswith("ok")
    r = _alp("decode", str(alpb_path))
    assert "Urgency is high." in r.stdout
    r = _alp("decode", str(alpb_path), "--readings")
    assert "a property that is high" in r.stdout
    r = _alp("compose", "$PROPERTY.HIGH.PUNCTUAL.REQUIRED")
    assert "037fac5d" in r.stdout
    r = _alp("render", str(tmp_path / "x.alpt"), "--pdf", str(tmp_path / "audit.pdf"))
    assert r.returncode == 0 and (tmp_path / "audit.pdf").exists()
    r = _alp("inventory")
    assert "76 primitives" in r.stdout
