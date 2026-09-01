"""The closed primitive inventory (RFC-ALP-001 §4) and role codes (§5.3).

Inventory **version 2**.  Version 1 is the RFC's 76 primitives in 9 classes.
Version 2 keeps every v1 code unchanged and adds, per the RFC's own rule that
extension is a version bump (§4.1):

  class 0x09 RELATIONAL   relation types beyond causation: equal, greater, part, has, near, inside…
  class 0x0A DEICTIC      pointing: self, addressee, this, that, which, same, other, each, any, generic
  class 0x0B LOGICAL      and, or, xor, iff, implies, only, except
  class 0x0C AFFECT       joy, fear, anger, trust, surprise, disgust, sadness, calm
  class 0x08 +            literal markers NUM, STR, TIME, UNIT, EREF (structural; values are bound, §5.4)
  roles 0x07-0x0C         LOC, TIME, MANNER, PURPOSE, SOURCE, GOAL

Why these and not a bigger vocabulary: the head set stays at 12 kinds of
thing, and everything specific (people, numbers, measurements, dates, places
by name) is a *literal bound to a role* rather than a primitive.  The
primitives are for what can be composed; literals are for what can only be
named or counted.

PIDs are two-byte codes: class byte, member byte.  Codes double as Unicode PUA
offsets for the script (§6.3).  ``V1_PRIMITIVES`` is the RFC's original set.
"""

from __future__ import annotations

from .alpb import Pid

INVENTORY_VERSION = 2
PROTOCOL_VERSION = 1

# -- classes ------------------------------------------------------------------
CLASS_ONTOLOGICAL = 0x00
CLASS_MODAL = 0x01
CLASS_SCALAR = 0x02
CLASS_TEMPORAL = 0x03
CLASS_CAUSAL = 0x04
CLASS_EPISTEMIC = 0x05
CLASS_ILLOCUTIONARY = 0x06
CLASS_VALENCE = 0x07
CLASS_STRUCTURAL = 0x08
CLASS_RELATIONAL = 0x09
CLASS_DEICTIC = 0x0A
CLASS_LOGICAL = 0x0B
CLASS_AFFECT = 0x0C

CLASS_NAMES = {
    CLASS_ONTOLOGICAL: "ontological",
    CLASS_MODAL: "modal",
    CLASS_SCALAR: "scalar",
    CLASS_TEMPORAL: "temporal",
    CLASS_CAUSAL: "causal",
    CLASS_EPISTEMIC: "epistemic",
    CLASS_ILLOCUTIONARY: "illocutionary",
    CLASS_VALENCE: "valence",
    CLASS_STRUCTURAL: "structural",
    CLASS_RELATIONAL: "relational",
    CLASS_DEICTIC: "deictic",
    CLASS_LOGICAL: "logical",
    CLASS_AFFECT: "affect",
}

# -- primitives: name -> (code, sense) ----------------------------------------
_TABLE: list[tuple[str, int, str]] = [
    # 0x00 ontological
    ("ENTITY", 0x0000, "A thing that persists"),
    ("PROCESS", 0x0001, "Something that unfolds"),
    ("PROPERTY", 0x0002, "An attribute borne by something"),
    ("RELATION", 0x0003, "A tie between two or more things"),
    ("QUANTITY", 0x0004, "A measurable magnitude"),
    ("AGENT", 0x0005, "An entity capable of action"),
    ("STATE", 0x0006, "A condition holding at a time"),
    ("PLACE", 0x0007, "A location or region"),
    ("MOMENT", 0x0008, "A time or interval as an object"),
    ("SIGN", 0x0009, "Information, a message, a representation"),
    ("EVENT", 0x000A, "A bounded occurrence"),
    ("GROUP", 0x000B, "A set or collection"),
    # 0x01 modal
    ("AFFIRM", 0x0100, "Holds"),
    ("NEGATE", 0x0101, "Does not hold"),
    ("POSSIBLE", 0x0102, "May hold"),
    ("NECESSARY", 0x0103, "Must hold"),
    ("DESIRED", 0x0104, "Wanted to hold"),
    ("HYPOTHETICAL", 0x0105, "Entertained, not asserted"),
    ("PERMITTED", 0x0106, "Allowed to hold"),
    ("FORBIDDEN", 0x0107, "Not allowed to hold"),
    # 0x02 scalar
    ("NONE", 0x0200, "Zero"),
    ("SOME", 0x0201, "Nonzero, partial"),
    ("ALL", 0x0202, "Total"),
    ("LOW", 0x0203, "Low on the relevant scale"),
    ("MID", 0x0204, "Middling"),
    ("HIGH", 0x0205, "High"),
    ("EXTREME", 0x0206, "At or beyond the limit"),
    ("BOUNDED", 0x0207, "Has limits"),
    ("UNBOUNDED", 0x0208, "Has none"),
    ("INCREASE", 0x0209, "Rising"),
    ("DECREASE", 0x020A, "Falling"),
    # 0x03 temporal
    ("PAST", 0x0300, "Before now"),
    ("NOW", 0x0301, "At present"),
    ("FUTURE", 0x0302, "After now"),
    ("DURATIVE", 0x0303, "Extended in time"),
    ("PUNCTUAL", 0x0304, "Instantaneous"),
    ("BEFORE", 0x0305, "Prior to a reference"),
    ("DURING", 0x0306, "Concurrent with a reference"),
    ("AFTER", 0x0307, "Subsequent to a reference"),
    ("REPEAT", 0x0308, "Recurring"),
    ("BEGIN", 0x0309, "Onset"),
    ("END", 0x030A, "Cessation"),
    # 0x04 causal
    ("CAUSE", 0x0400, "Brings about"),
    ("ENABLE", 0x0401, "Makes possible"),
    ("PREVENT", 0x0402, "Makes impossible"),
    ("CORRELATE", 0x0403, "Co-varies, causation unclaimed"),
    ("DEPEND", 0x0404, "Requires as precondition"),
    ("TRIGGER", 0x0405, "Initiates on occurrence"),
    # 0x05 epistemic
    ("KNOWN", 0x0500, "Established"),
    ("BELIEVED", 0x0501, "Held without proof"),
    ("INFERRED", 0x0502, "Derived by reasoning"),
    ("UNKNOWN", 0x0503, "Not established"),
    ("CONTESTED", 0x0504, "Disputed between parties"),
    ("OBSERVED", 0x0505, "Directly witnessed"),
    ("PREDICTED", 0x0506, "Projected forward"),
    # 0x06 illocutionary
    ("ASSERT", 0x0600, "Puts forward as true"),
    ("REQUEST", 0x0601, "Asks for action"),
    ("COMMIT", 0x0602, "Binds the speaker"),
    ("QUERY", 0x0603, "Asks for information"),
    ("WARN", 0x0604, "Flags hazard"),
    ("REFUSE", 0x0605, "Declines"),
    ("PROPOSE", 0x0606, "Offers for consideration"),
    ("ACKNOWLEDGE", 0x0607, "Registers receipt"),
    # 0x07 valence / deontic
    ("GOOD", 0x0700, "Positively valued"),
    ("BAD", 0x0701, "Negatively valued"),
    ("REQUIRED", 0x0702, "Obligatory"),
    ("OPTIONAL", 0x0703, "Discretionary"),
    ("SAFE", 0x0704, "Without hazard"),
    ("HARM", 0x0705, "Damage or injury"),
    ("COST", 0x0706, "Expenditure"),
    ("BENEFIT", 0x0707, "Gain"),
    # 0x08 structural
    ("REF", 0x0800, "Points at an existing SID"),
    ("SCOPE_OPEN", 0x0801, "Begins a nested composition"),
    ("SCOPE_CLOSE", 0x0802, "Ends one"),
    ("SUPERSEDE", 0x0803, "Marks the supersession link"),
    ("RESIDUE", 0x0804, "Marks untranslated meaning"),
]
V1_COUNT = len(_TABLE)
assert V1_COUNT == 76

_TABLE_V2: list[tuple[str, int, str]] = [
    # 0x08 structural: literal markers (the value itself is bound at ASSERT, §5.4)
    ("NUM", 0x0805, "A bound number follows"),
    ("STR", 0x0806, "A bound name or text follows"),
    ("TIME", 0x0807, "A bound instant or date follows"),
    ("UNIT", 0x0808, "A bound unit of measure follows"),
    ("EREF", 0x0809, "Points at an existing EID (an earlier utterance)"),
    # 0x09 relational
    ("EQUAL", 0x0900, "Same as, equal to"),
    ("GREATER", 0x0901, "More than, above on a scale"),
    ("LESS", 0x0902, "Less than, below on a scale"),
    ("PART", 0x0903, "Is a part of"),
    ("HAS", 0x0904, "Possesses, contains, owns"),
    ("MEMBER", 0x0905, "Is a member or instance of"),
    ("NEAR", 0x0906, "Close to"),
    ("INSIDE", 0x0907, "Within"),
    ("OUTSIDE", 0x0908, "Beyond, external to"),
    ("ABOVE", 0x0909, "Spatially over"),
    ("BELOW", 0x090A, "Spatially under"),
    ("TOWARD", 0x090B, "Directed at"),
    # 0x0A deictic
    ("SELF", 0x0A00, "The speaker"),
    ("ADDRESSEE", 0x0A01, "The one spoken to"),
    ("THIS", 0x0A02, "The proximal referent"),
    ("THAT", 0x0A03, "The distal referent"),
    ("WHICH", 0x0A04, "The queried variable"),
    ("SAME", 0x0A05, "The one already mentioned"),
    ("OTHER", 0x0A06, "A different one"),
    ("EACH", 0x0A07, "Distributively, every one"),
    ("ANY", 0x0A08, "An arbitrary one"),
    ("GENERIC", 0x0A09, "The kind, not an instance"),
    # 0x0B logical
    ("AND", 0x0B00, "Conjunction"),
    ("OR", 0x0B01, "Inclusive disjunction"),
    ("XOR", 0x0B02, "Exactly one of"),
    ("IFF", 0x0B03, "If and only if"),
    ("IMPLIES", 0x0B04, "Entails"),
    ("ONLY", 0x0B05, "Exclusively"),
    ("EXCEPT", 0x0B06, "With the exclusion of"),
    # 0x0C affect
    ("JOY", 0x0C00, "Gladness"),
    ("FEAR", 0x0C01, "Fear, anxiety"),
    ("ANGER", 0x0C02, "Anger"),
    ("TRUST", 0x0C03, "Trust, confidence in"),
    ("SURPRISE", 0x0C04, "Surprise"),
    ("DISGUST", 0x0C05, "Aversion"),
    ("SADNESS", 0x0C06, "Sorrow, loss"),
    ("CALM", 0x0C07, "Ease, absence of arousal"),
]
_TABLE = _TABLE + _TABLE_V2

PRIMITIVES: dict[str, Pid] = {name: Pid(code) for name, code, _ in _TABLE}
SENSES: dict[Pid, str] = {Pid(code): sense for _, code, sense in _TABLE}
NAMES: dict[Pid, str] = {Pid(code): name for name, code, _ in _TABLE}
V1_PRIMITIVES: dict[str, Pid] = {name: Pid(code) for name, code, _ in _TABLE[:V1_COUNT]}
LITERAL_MARKERS = {PRIMITIVES[n] for n in ("NUM", "STR", "TIME", "UNIT", "EREF")}

# -- roles --------------------------------------------------------------------
ROLES: dict[str, int] = {
    "ARG0": 0x01, "ARG1": 0x02, "ARG2": 0x03,
    "SCOPE": 0x04, "MEASURE": 0x05, "CONDITION": 0x06,
    # v2
    "LOC": 0x07, "TIME": 0x08, "MANNER": 0x09, "PURPOSE": 0x0A, "SOURCE": 0x0B, "GOAL": 0x0C,
}
ROLE_NAMES: dict[int, str] = {v: k for k, v in ROLES.items()}
ROLE_SENSES: dict[str, str] = {
    "ARG0": "Agent, cause, or first argument",
    "ARG1": "Patient, effect, or second argument",
    "ARG2": "Instrument, recipient, third argument",
    "SCOPE": "The domain over which the head applies",
    "MEASURE": "Unit, scale, or amount",
    "CONDITION": "Precondition on the head",
    "LOC": "Where",
    "TIME": "When",
    "MANNER": "How, by what means",
    "PURPOSE": "What for",
    "SOURCE": "From where or whom",
    "GOAL": "To where or whom",
}

MAX_DEPTH = 8
MAX_MODIFIERS = 12


def pid(name: str) -> Pid:
    """Look up a primitive by name.  Raises ValueError for unknown names."""
    try:
        return PRIMITIVES[name.upper()]
    except KeyError:
        raise ValueError(f"not a primitive in inventory {INVENTORY_VERSION}: {name}") from None


def name_of(p: Pid) -> str:
    return NAMES.get(p, f"PID_{p.code:04X}")


def is_known(p: Pid) -> bool:
    return p in NAMES


def by_class(cls: int) -> list[Pid]:
    return [p for p in NAMES if p.cls == cls]


def role_code(name_or_code: str | int) -> int:
    if isinstance(name_or_code, int):
        if name_or_code not in ROLE_NAMES:
            raise ValueError(f"unknown role code {name_or_code}")
        return name_or_code
    try:
        return ROLES[name_or_code.upper()]
    except KeyError:
        raise ValueError(f"unknown role {name_or_code}") from None


def script_text(pids: list[Pid]) -> str:
    """Render a PID sequence as PUA script codepoints (§6.3)."""
    return "".join(p.codepoint for p in pids)


def inventory_table() -> str:
    """Human-readable inventory dump."""
    lines = []
    current = None
    for name, code, sense in _TABLE:
        cls = code >> 8
        if cls != current:
            current = cls
            lines.append(f"\nclass 0x{cls:02X}  {CLASS_NAMES[cls]}")
        lines.append(f"  0x{code:04X}  U+{0xE000 + code:04X}  {name:<12} {sense}")
    lines.append(f"\n{len(_TABLE)} primitives ({V1_COUNT} in v1 + {len(_TABLE) - V1_COUNT} in v2), inventory version {INVENTORY_VERSION}")
    lines.append("\nroles")
    for rname, rcode in ROLES.items():
        lines.append(f"  0x{rcode:02X}  {rname:<10} {ROLE_SENSES[rname]}")
    return "\n".join(lines)
