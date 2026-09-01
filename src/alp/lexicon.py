"""Lexicon utilities: synonymy-fork detection (RFC-ALP-001 v1.1 §12.6).

Two agents can compose different, equally well-formed trees for the same
concept.  Both hash differently and the lexicon forks silently.  The RFC
leaves this open; the mitigations it lists are all partial.  This module
implements the cheap one that is actually buildable: a *near-duplicate scan*
over a lexicon that surfaces candidate forks for a human or a REGROUND.

Similarity is structural — same head, Jaccard overlap of modifier sets, and
matching role heads — never textual.  Glosses are not consulted (they are not
part of the symbol).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from . import inventory as inv
from .alpb import Pid
from .composition import Composition, Node


def _flat_mods(c: Composition) -> set:
    return {m for m in c.modifiers if isinstance(m, Pid)}


def _role_sig(n: Node) -> tuple:
    if isinstance(n, Pid):
        return ("pid", n.code)
    if isinstance(n, Composition):
        return ("comp", n.head.code, tuple(sorted(m.code for m in _flat_mods(n))))
    return ("sid", bytes(n)[:8])


def similarity(a: Composition, b: Composition) -> float:
    """0..1.  1 only for identical structure (which would be the same SID)."""
    if a.head != b.head:
        return 0.0
    ma, mb = _flat_mods(a), _flat_mods(b)
    if ma or mb:
        jac = len(ma & mb) / len(ma | mb)
    else:
        jac = 1.0
    ra = {code: _role_sig(n) for code, n in a.roles}
    rb = {code: _role_sig(n) for code, n in b.roles}
    if ra or rb:
        keys = set(ra) | set(rb)
        role_score = sum(1 for k in keys if ra.get(k) == rb.get(k)) / len(keys)
    else:
        role_score = 1.0
    res = 1.0 if (a.residue or None) == (b.residue or None) else 0.5
    return 0.55 * jac + 0.35 * role_score + 0.10 * res


@dataclass
class Fork:
    a: Composition
    b: Composition
    score: float

    def describe(self) -> str:
        return (f"{self.score:.2f}  !{self.a.sid_hex(8)} {self.a.transliterate(8)}\n"
                f"      !{self.b.sid_hex(8)} {self.b.transliterate(8)}")


def find_forks(comps: Iterable[Composition], threshold: float = 0.7) -> list[Fork]:
    """Pairs of distinct symbols that look like the same concept composed differently."""
    items = list({c.sid: c for c in comps}.values())
    out: list[Fork] = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if a.supersedes == b.sid or b.supersedes == a.sid:
                continue   # a declared refinement, not a fork
            s = similarity(a, b)
            if s >= threshold:
                out.append(Fork(a, b, s))
    out.sort(key=lambda f: -f.score)
    return out


def head_groups(comps: Iterable[Composition]) -> dict[str, list[Composition]]:
    groups: dict[str, list[Composition]] = {}
    for c in comps:
        groups.setdefault(inv.name_of(c.head), []).append(c)
    return groups
