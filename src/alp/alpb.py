"""ALP/B: canonical tag-length-value binary encoding (RFC-ALP-001 §4).

The encoding is CBOR-shaped (RFC 8949) but not CBOR-compatible: the major
types differ (REF replaces CBOR's tag type, SIMPLE keeps the float/bool slots).

    tag byte := MMMAAAAA   3-bit major, 5-bit argument
    argument 0..23 immediate; 24/25/26/27 => 1/2/4/8 following big-endian bytes

Python value model
------------------
    UINT / NINT  -> int
    BYTES        -> bytes
    TEXT         -> str          (NFC-normalized on encode)
    LIST         -> list
    MAP          -> dict         (keys sorted bytewise on encoded form)
    REF 0..3     -> Ref   (SID / EID reference)
    REF 4        -> Pid   (two-byte primitive identifier, §4.2)
    SIMPLE       -> bool | None | float

Canonical form (§4.2) is enforced on both encode and decode.  A decoder that
sees non-canonical input raises ``NonCanonical`` (E_NONCANONICAL).
"""

from __future__ import annotations

import math
import struct
import unicodedata
from dataclasses import dataclass
from typing import Any

# Major types ---------------------------------------------------------------
UINT, NINT, BYTES, TEXT, LIST, MAP, REF, SIMPLE = range(8)

# REF argument kinds (§4.1.1)
REF_SID = 0        # SID, profile width
REF_EID = 1        # EID, profile width
REF_SID_FULL = 2   # SID, always 32 bytes
REF_EID_FULL = 3   # EID, always 32 bytes
REF_PID = 4        # primitive identifier, two bytes (new in 1.1)

SIMPLE_FALSE, SIMPLE_TRUE, SIMPLE_NULL, SIMPLE_F64 = 20, 21, 22, 27

HASH_LEN = 32


class ALPBError(ValueError):
    """Base class for ALP/B decode errors."""


class NonCanonical(ALPBError):
    """E_NONCANONICAL: the bytes decode, but not in canonical form."""


class Truncated(ALPBError):
    """Input ended before the value was complete."""


@dataclass(frozen=True, slots=True)
class Ref:
    """A SID or EID reference.

    ``kind`` is one of REF_SID / REF_EID / REF_SID_FULL / REF_EID_FULL.
    ``data`` is always the full 32-byte hash when we hold it; the encoder
    truncates to the negotiated profile width for kinds 0 and 1.  A Ref decoded
    from a truncated wire form holds only the bytes that were on the wire.
    """

    kind: int
    data: bytes

    def __post_init__(self) -> None:
        if self.kind not in (REF_SID, REF_EID, REF_SID_FULL, REF_EID_FULL):
            raise ValueError(f"bad ref kind {self.kind}")
        if not isinstance(self.data, (bytes, bytearray)):
            raise TypeError("Ref.data must be bytes")
        object.__setattr__(self, "data", bytes(self.data))

    @property
    def is_sid(self) -> bool:
        return self.kind in (REF_SID, REF_SID_FULL)

    @property
    def is_eid(self) -> bool:
        return self.kind in (REF_EID, REF_EID_FULL)

    @property
    def hex(self) -> str:
        return self.data.hex()

    def full(self) -> "Ref":
        """Return the same reference marked as full-width (32 bytes)."""
        return Ref(REF_SID_FULL if self.is_sid else REF_EID_FULL, self.data)

    def profiled(self) -> "Ref":
        """Return the same reference marked as profile-width."""
        return Ref(REF_SID if self.is_sid else REF_EID, self.data)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        k = {0: "sid", 1: "eid", 2: "SID", 3: "EID"}[self.kind]
        return f"Ref({k}:{self.data.hex()[:16]}…)"


@dataclass(frozen=True, slots=True, order=True)
class Pid:
    """A primitive identifier: class byte << 8 | member byte (§4.2)."""

    code: int

    def __post_init__(self) -> None:
        if not 0 <= self.code <= 0xFFFF:
            raise ValueError(f"PID out of range: {self.code:#x}")

    @property
    def cls(self) -> int:
        return (self.code >> 8) & 0xFF

    @property
    def member(self) -> int:
        return self.code & 0xFF

    @property
    def codepoint(self) -> str:
        """Script codepoint: U+E000 + PID (§6.3)."""
        return chr(0xE000 + self.code)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Pid({self.code:#06x})"


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _head(major: int, arg: int) -> bytes:
    """Encode a tag byte plus shortest-fit argument."""
    if arg < 0:
        raise ValueError("negative argument")
    m = major << 5
    if arg < 24:
        return bytes((m | arg,))
    if arg < 0x100:
        return bytes((m | 24, arg))
    if arg < 0x10000:
        return bytes((m | 25,)) + arg.to_bytes(2, "big")
    if arg < 0x1_0000_0000:
        return bytes((m | 26,)) + arg.to_bytes(4, "big")
    if arg < 0x1_0000_0000_0000_0000:
        return bytes((m | 27,)) + arg.to_bytes(8, "big")
    raise ValueError("integer too large for ALP/B (max 64-bit)")


def nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)


class Encoder:
    """Canonical encoder.

    ``sid_width`` is the negotiated truncation profile in bytes (§3.4).  It
    only affects Refs of kind REF_SID / REF_EID; full-width kinds always emit
    32 bytes.
    """

    def __init__(self, sid_width: int = HASH_LEN) -> None:
        if sid_width not in (8, 12, 16, 32):
            raise ValueError("sid_width must be one of 8, 12, 16, 32")
        self.sid_width = sid_width

    def encode(self, value: Any) -> bytes:
        out = bytearray()
        self._enc(value, out)
        return bytes(out)

    def _enc(self, v: Any, out: bytearray) -> None:
        # bool must be tested before int (bool is an int subclass)
        if v is True:
            out += _head(SIMPLE, SIMPLE_TRUE)
        elif v is False:
            out += _head(SIMPLE, SIMPLE_FALSE)
        elif v is None:
            out += _head(SIMPLE, SIMPLE_NULL)
        elif isinstance(v, int):
            if v >= 0:
                out += _head(UINT, v)
            else:
                out += _head(NINT, -1 - v)
        elif isinstance(v, float):
            if math.isnan(v):
                out += bytes((SIMPLE << 5 | SIMPLE_F64,)) + b"\x7f\xf8\x00\x00\x00\x00\x00\x00"
            else:
                out += bytes((SIMPLE << 5 | SIMPLE_F64,)) + struct.pack(">d", v)
        elif isinstance(v, (bytes, bytearray, memoryview)):
            b = bytes(v)
            out += _head(BYTES, len(b)) + b
        elif isinstance(v, str):
            b = nfc(v).encode("utf-8")
            out += _head(TEXT, len(b)) + b
        elif isinstance(v, Pid):
            out += _head(REF, REF_PID) + v.code.to_bytes(2, "big")
        elif isinstance(v, Ref):
            width = HASH_LEN if v.kind in (REF_SID_FULL, REF_EID_FULL) else self.sid_width
            data = v.data
            if len(data) < width:
                raise ValueError(
                    f"ref holds {len(data)} bytes, profile requires {width}"
                )
            out += _head(REF, v.kind) + data[:width]
        elif isinstance(v, (list, tuple)):
            out += _head(LIST, len(v))
            for item in v:
                self._enc(item, out)
        elif isinstance(v, dict):
            items = []
            seen = set()
            for k, val in v.items():
                kb = self.encode(k)
                if kb in seen:
                    raise ValueError("duplicate map key after canonicalization")
                seen.add(kb)
                items.append((kb, val))
            items.sort(key=lambda kv: kv[0])
            out += _head(MAP, len(items))
            for kb, val in items:
                out += kb
                self._enc(val, out)
        else:
            raise TypeError(f"cannot encode {type(v).__name__} in ALP/B")


def encode(value: Any, sid_width: int = HASH_LEN) -> bytes:
    return Encoder(sid_width).encode(value)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

class Decoder:
    def __init__(self, data: bytes, sid_width: int = HASH_LEN, strict: bool = True) -> None:
        self.buf = bytes(data)
        self.pos = 0
        self.sid_width = sid_width
        self.strict = strict

    # -- primitives ---------------------------------------------------------
    def _take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise Truncated(f"need {n} bytes at offset {self.pos}, have {len(self.buf) - self.pos}")
        b = self.buf[self.pos : self.pos + n]
        self.pos += n
        return b

    def _read_head(self) -> tuple[int, int]:
        """Read a tag byte and its argument.  SIMPLE is handled by the caller."""
        tag = self._take(1)[0]
        major, ai = tag >> 5, tag & 0x1F
        if major == SIMPLE:
            return major, ai
        if ai < 24:
            return major, ai
        if ai == 31:
            raise NonCanonical("indefinite-length encoding is forbidden")
        if ai > 27:
            raise ALPBError(f"reserved additional info {ai}")
        n = 1 << (ai - 24)
        arg = int.from_bytes(self._take(n), "big")
        if self.strict:
            limit = (24, 0x100, 0x10000, 0x1_0000_0000)[ai - 24]
            if arg < limit:
                raise NonCanonical(f"argument {arg} not in shortest form")
        return major, arg

    # -- values -------------------------------------------------------------
    def decode(self) -> Any:
        major, arg = self._read_head()
        if major == UINT:
            return arg
        if major == NINT:
            return -1 - arg
        if major == BYTES:
            return self._take(arg)
        if major == TEXT:
            raw = self._take(arg)
            try:
                s = raw.decode("utf-8")
            except UnicodeDecodeError as e:
                raise ALPBError(f"invalid UTF-8: {e}") from None
            if self.strict and unicodedata.normalize("NFC", s) != s:
                raise NonCanonical("text is not NFC-normalized")
            return s
        if major == LIST:
            return [self.decode() for _ in range(arg)]
        if major == MAP:
            result: dict = {}
            prev_key: bytes | None = None
            for _ in range(arg):
                start = self.pos
                k = self.decode()
                kb = self.buf[start : self.pos]
                if self.strict and prev_key is not None:
                    if kb == prev_key:
                        raise NonCanonical("duplicate map key")
                    if kb < prev_key:
                        raise NonCanonical("map keys not sorted")
                prev_key = kb
                if isinstance(k, (list, dict)):
                    raise ALPBError("unhashable map key")
                result[k] = self.decode()
            return result
        if major == REF:
            if arg == REF_PID:
                return Pid(int.from_bytes(self._take(2), "big"))
            if arg not in (REF_SID, REF_EID, REF_SID_FULL, REF_EID_FULL):
                raise ALPBError(f"unknown REF kind {arg}")
            width = HASH_LEN if arg >= 2 else self.sid_width
            return Ref(arg, self._take(width))
        if major == SIMPLE:
            ai = arg
            if ai == SIMPLE_FALSE:
                return False
            if ai == SIMPLE_TRUE:
                return True
            if ai == SIMPLE_NULL:
                return None
            if ai == SIMPLE_F64:
                raw = self._take(8)
                f = struct.unpack(">d", raw)[0]
                if self.strict and math.isnan(f) and raw != b"\x7f\xf8\x00\x00\x00\x00\x00\x00":
                    raise NonCanonical("non-canonical NaN")
                return f
            if ai in (24, 25, 26):
                raise NonCanonical("only f64 floats are permitted")
            if ai == 31:
                raise NonCanonical("indefinite-length encoding is forbidden")
            raise ALPBError(f"unknown simple value {ai}")
        raise ALPBError(f"bad major type {major}")  # pragma: no cover

    def at_end(self) -> bool:
        return self.pos >= len(self.buf)


def decode(data: bytes, sid_width: int = HASH_LEN, strict: bool = True) -> Any:
    """Decode exactly one value; trailing bytes are an error."""
    d = Decoder(data, sid_width, strict)
    v = d.decode()
    if not d.at_end():
        raise ALPBError(f"{len(data) - d.pos} trailing bytes after value")
    return v


def decode_prefix(data: bytes, sid_width: int = HASH_LEN, strict: bool = True) -> tuple[Any, int]:
    """Decode one value and return (value, bytes_consumed)."""
    d = Decoder(data, sid_width, strict)
    v = d.decode()
    return v, d.pos


# ---------------------------------------------------------------------------
# uvarint (LEB128) used for frame length prefixes (§4.3)
# ---------------------------------------------------------------------------

def uvarint_encode(n: int) -> bytes:
    if n < 0:
        raise ValueError("uvarint must be non-negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def uvarint_decode(buf: bytes, pos: int = 0) -> tuple[int, int]:
    shift = 0
    n = 0
    while True:
        if pos >= len(buf):
            raise Truncated("uvarint")
        b = buf[pos]
        pos += 1
        n |= (b & 0x7F) << shift
        if not b & 0x80:
            return n, pos
        shift += 7
        if shift > 63:
            raise ALPBError("uvarint too long")
