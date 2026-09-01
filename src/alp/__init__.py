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

from . import alpt, lexicon, render, script
from .alpb import ALPBError, NonCanonical, Pid, Ref, decode, encode
from .composition import Composition, CompositionError, SIDMismatch
from .composition import parse as parse_transliteration
from .events import (
    AttestLevel,
    ErrorCode,
    Event,
    EventType,
    Flag,
    State,
    Stream,
    agent_sid,
    agent_symbol,
    fold,
    new_stream_id,
    read_frames,
    toposort,
    write_frames,
)
from .inventory import INVENTORY_VERSION, PRIMITIVES, PROTOCOL_VERSION, ROLES, pid
from .translate import SimpleTranslator, Translation, TranslationStats, Translator, split_sentences, stats

__version__ = "0.1.0"

__all__ = [
    "Pid", "Ref", "encode", "decode", "NonCanonical", "ALPBError",
    "INVENTORY_VERSION", "PROTOCOL_VERSION", "PRIMITIVES", "ROLES", "pid",
    "Composition", "CompositionError", "SIDMismatch", "parse_transliteration",
    "Translator", "SimpleTranslator", "Translation", "TranslationStats", "stats", "split_sentences",
    "Event", "EventType", "Flag", "AttestLevel", "ErrorCode", "Stream", "State", "fold", "toposort",
    "agent_sid", "agent_symbol", "new_stream_id", "read_frames", "write_frames",
    "alpt", "render", "lexicon", "script", "__version__",
]
