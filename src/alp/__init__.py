"""alp — Agent Lexicon Protocol (RFC-ALP-001 v1.1) toolkit.

    from alp import Composition, Translator, Stream, alpt

    c = Composition.build("PROPERTY", "HIGH", "PUNCTUAL", "REQUIRED", gloss="urgency")
    c.sid_hex(8)          # '037fac5d'
    str(c)                # '$PROPERTY.HIGH.PUNCTUAL.REQUIRED'

    s = Stream(sid_width=16)
    s.amend("a000", [c])
    data = s.to_bytes()   # ALP/B frames
    text = alpt.dumps(s)  # ALP/T projection
"""

from .alpb import Pid, Ref, encode, decode, NonCanonical, ALPBError
from .inventory import INVENTORY_VERSION, PROTOCOL_VERSION, PRIMITIVES, ROLES, pid
from .composition import Composition, CompositionError, SIDMismatch, parse as parse_transliteration
from .translate import Translator, Translation, TranslationStats, stats, split_sentences
from .events import (
    Event, EventType, Flag, AttestLevel, ErrorCode, Stream, State, fold, toposort,
    agent_sid, agent_symbol, new_stream_id, read_frames, write_frames,
)
from . import alpt, render

__version__ = "0.1.0"

__all__ = [
    "Pid", "Ref", "encode", "decode", "NonCanonical", "ALPBError",
    "INVENTORY_VERSION", "PROTOCOL_VERSION", "PRIMITIVES", "ROLES", "pid",
    "Composition", "CompositionError", "SIDMismatch", "parse_transliteration",
    "Translator", "Translation", "TranslationStats", "stats", "split_sentences",
    "Event", "EventType", "Flag", "AttestLevel", "ErrorCode", "Stream", "State", "fold", "toposort",
    "agent_sid", "agent_symbol", "new_stream_id", "read_frames", "write_frames",
    "alpt", "render", "__version__",
]
