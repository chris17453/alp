"""The closed primitive inventory (RFC-ALP-001 v1.1 §4) and role codes (§5.3).

76 primitives across 9 classes.  PIDs are two-byte codes: class byte, member
byte.  Codes double as Unicode PUA offsets for the script (§6.3).
"""

from __future__ import annotations

from .alpb import Pid

INVENTORY_VERSION = 1
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

PRIMITIVES: dict[str, Pid] = {name: Pid(code) for name, code, _ in _TABLE}
SENSES: dict[Pid, str] = {Pid(code): sense for _, code, sense in _TABLE}
NAMES: dict[Pid, str] = {Pid(code): name for name, code, _ in _TABLE}

assert len(PRIMITIVES) == 76

# -- roles --------------------------------------------------------------------
ROLES: dict[str, int] = {
    "ARG0": 0x01, "ARG1": 0x02, "ARG2": 0x03,
    "SCOPE": 0x04, "MEASURE": 0x05, "CONDITION": 0x06,
}
ROLE_NAMES: dict[int, str] = {v: k for k, v in ROLES.items()}
ROLE_SENSES: dict[str, str] = {
    "ARG0": "Agent, cause, or first argument",
    "ARG1": "Patient, effect, or second argument",
    "ARG2": "Instrument, recipient, third argument",
    "SCOPE": "The domain over which the head applies",
    "MEASURE": "Unit or scale reference",
    "CONDITION": "Precondition on the head",
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
    lines.append(f"\n{len(_TABLE)} primitives, inventory version {INVENTORY_VERSION}")
    lines.append("\nroles")
    for rname, rcode in ROLES.items():
        lines.append(f"  0x{rcode:02X}  {rname:<10} {ROLE_SENSES[rname]}")
    return "\n".join(lines)
