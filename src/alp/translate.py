"""English -> composition front end (RFC-ALP-001 v1.1 Appendix E).

Deterministic and rule-based.  It maps English head nouns to ontological
primitives via a lexicon, harvests modifiers from cue words, and hands the
result to ``Composition`` for canonicalization and hashing.

What it is not: natural language understanding.  No parser, no word-sense
disambiguation, no coreference.  Input outside the lexicon becomes *residue*
(§5.5) — English carried verbatim inside the hash — and a high residue rate
means the translation did not happen.  ``TranslationStats`` reports it; treat
it as the quality metric the RFC asks for (§14.4).

Ported from the standalone reference script ``alp_translate.py``; the lexicon
tables are unchanged so SIDs agree with the RFC's worked conversation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .composition import Composition
from .inventory import MAX_MODIFIERS, pid

# Head noun -> (ontological primitive, baseline modifiers)
HEAD_LEXICON: dict[str, tuple[str, list[str]]] = {
    "urgency": ("PROPERTY", ["HIGH", "PUNCTUAL", "REQUIRED"]),
    "priority": ("PROPERTY", ["BOUNDED"]),
    "deadline": ("MOMENT", ["FUTURE", "PUNCTUAL", "BOUNDED"]),
    "outage": ("STATE", ["NEGATE", "BAD"]),
    "incident": ("EVENT", ["BAD", "NOW"]),
    "failure": ("EVENT", ["NEGATE", "BAD"]),
    "latency": ("QUANTITY", ["DURATIVE"]),
    "throughput": ("QUANTITY", ["DURATIVE"]),
    "error": ("EVENT", ["BAD"]),
    "warning": ("SIGN", ["WARN"]),
    "alert": ("SIGN", ["WARN", "NOW"]),
    "signal": ("SIGN", []),
    "message": ("SIGN", []),
    "report": ("SIGN", ["OBSERVED"]),
    "service": ("PROCESS", ["DURATIVE"]),
    "process": ("PROCESS", []),
    "job": ("PROCESS", ["BOUNDED"]),
    "task": ("PROCESS", ["BOUNDED"]),
    "deployment": ("EVENT", ["PUNCTUAL"]),
    "deploy": ("EVENT", ["PUNCTUAL"]),
    "rollback": ("PROCESS", ["PAST"]),
    "escalation": ("PROCESS", ["INCREASE"]),
    "cause": ("RELATION", ["CAUSE"]),
    "dependency": ("RELATION", ["DEPEND"]),
    "operator": ("AGENT", []),
    "engineer": ("AGENT", []),
    "team": ("GROUP", ["AGENT"]),
    "user": ("AGENT", []),
    "customer": ("AGENT", []),
    "server": ("ENTITY", []),
    "host": ("ENTITY", []),
    "cluster": ("GROUP", []),
    "database": ("ENTITY", []),
    "region": ("PLACE", []),
    "count": ("QUANTITY", []),
    "rate": ("QUANTITY", ["DURATIVE"]),
    "budget": ("QUANTITY", ["BOUNDED", "COST"]),
    "cost": ("QUANTITY", ["COST"]),
    "risk": ("PROPERTY", ["POSSIBLE", "HARM"]),
    "state": ("STATE", []),
    "status": ("STATE", []),
    "condition": ("STATE", []),
    "window": ("MOMENT", ["DURATIVE", "BOUNDED"]),
    "time": ("MOMENT", []),
    "capacity": ("QUANTITY", ["BOUNDED"]),
    "scope": ("GROUP", ["BOUNDED"]),
    "impact": ("RELATION", ["CAUSE", "HARM"]),
    "meeting": ("EVENT", ["BOUNDED", "DURATIVE"]),
    "plan": ("SIGN", ["FUTURE", "PROPOSE"]),
    "question": ("SIGN", ["QUERY"]),
    "answer": ("SIGN", ["ASSERT"]),
    "decision": ("EVENT", ["PUNCTUAL", "COMMIT"]),
    "problem": ("STATE", ["BAD"]),
    "bug": ("STATE", ["BAD", "NEGATE"]),
    "fix": ("PROCESS", ["GOOD", "END"]),
    "change": ("EVENT", []),
    "request": ("SIGN", ["REQUEST"]),
    "location": ("PLACE", []),
    "person": ("AGENT", []),
    "people": ("GROUP", ["AGENT"]),
    "thing": ("ENTITY", []),
    "object": ("ENTITY", []),
    "file": ("ENTITY", ["SIGN"]),
    "document": ("SIGN", []),
    "data": ("SIGN", []),
    "result": ("STATE", ["AFTER"]),
}

# Cue word -> modifier primitive.  Modifiers are a set, so order is irrelevant.
CUE_LEXICON: dict[str, str] = {
    "not": "NEGATE", "no": "NEGATE", "never": "NEGATE",
    "down": "NEGATE", "failed": "NEGATE", "unavailable": "NEGATE",
    "must": "NECESSARY", "shall": "NECESSARY", "required": "REQUIRED",
    "may": "POSSIBLE", "might": "POSSIBLE", "could": "POSSIBLE",
    "possible": "POSSIBLE", "possibly": "POSSIBLE",
    "should": "DESIRED", "want": "DESIRED", "need": "REQUIRED",
    "allowed": "PERMITTED", "permitted": "PERMITTED",
    "forbidden": "FORBIDDEN", "blocked": "FORBIDDEN",
    "optional": "OPTIONAL",

    "high": "HIGH", "severe": "EXTREME", "critical": "EXTREME",
    "extreme": "EXTREME", "maximum": "EXTREME", "urgent": "HIGH",
    "low": "LOW", "minor": "LOW", "small": "LOW",
    "moderate": "MID", "medium": "MID",
    "all": "ALL", "every": "ALL", "total": "ALL",
    "some": "SOME", "partial": "SOME", "several": "SOME",
    "none": "NONE", "zero": "NONE",
    "rising": "INCREASE", "increasing": "INCREASE", "growing": "INCREASE",
    "spike": "INCREASE", "spiking": "INCREASE", "more": "INCREASE",
    "falling": "DECREASE", "decreasing": "DECREASE", "dropping": "DECREASE", "less": "DECREASE",
    "unbounded": "UNBOUNDED", "unlimited": "UNBOUNDED",
    "bounded": "BOUNDED", "capped": "BOUNDED", "limited": "BOUNDED",

    "was": "PAST", "were": "PAST", "previously": "PAST", "earlier": "PAST", "yesterday": "PAST",
    "now": "NOW", "currently": "NOW", "today": "NOW", "ongoing": "DURATIVE",
    "will": "FUTURE", "tomorrow": "FUTURE", "soon": "FUTURE",
    "upcoming": "FUTURE", "next": "FUTURE",
    "sustained": "DURATIVE", "continuous": "DURATIVE",
    "instant": "PUNCTUAL", "immediately": "PUNCTUAL", "immediate": "PUNCTUAL",
    "repeated": "REPEAT", "recurring": "REPEAT", "again": "REPEAT",
    "started": "BEGIN", "began": "BEGIN", "start": "BEGIN",
    "ended": "END", "stopped": "END", "resolved": "END", "finished": "END",
    "before": "BEFORE", "after": "AFTER", "during": "DURING", "while": "DURING",

    "because": "CAUSE", "caused": "CAUSE", "due": "CAUSE",
    "prevents": "PREVENT", "prevented": "PREVENT",
    "enables": "ENABLE", "enabled": "ENABLE",
    "triggered": "TRIGGER", "triggers": "TRIGGER",
    "depends": "DEPEND", "requires": "DEPEND",
    "correlated": "CORRELATE",

    "confirmed": "KNOWN", "known": "KNOWN", "verified": "KNOWN",
    "believe": "BELIEVED", "think": "BELIEVED", "likely": "BELIEVED",
    "suspect": "INFERRED", "suspected": "INFERRED", "inferred": "INFERRED",
    "apparently": "INFERRED",
    "unknown": "UNKNOWN", "unclear": "UNKNOWN", "unsure": "UNKNOWN",
    "disputed": "CONTESTED", "contested": "CONTESTED",
    "observed": "OBSERVED", "measured": "OBSERVED", "saw": "OBSERVED",
    "predicted": "PREDICTED", "forecast": "PREDICTED",
    "expected": "PREDICTED",

    "good": "GOOD", "healthy": "GOOD", "nominal": "GOOD", "fine": "GOOD",
    "bad": "BAD", "degraded": "BAD", "broken": "BAD",
    "safe": "SAFE", "harm": "HARM", "damage": "HARM", "dangerous": "HARM",
    "expensive": "COST", "benefit": "BENEFIT",
}

ILLOCUTION_CUES: dict[str, str | None] = {
    "please": "REQUEST", "can": "REQUEST", "would": "REQUEST",
    "?": "QUERY", "what": "QUERY", "when": "QUERY", "why": "QUERY",
    "which": "QUERY", "how": "QUERY", "who": "QUERY", "is": None,
    "warn": "WARN", "caution": "WARN",
    "propose": "PROPOSE", "suggest": "PROPOSE", "recommend": "PROPOSE",
    "commit": "COMMIT", "promise": "COMMIT",
    "refuse": "REFUSE", "decline": "REFUSE", "cannot": "REFUSE",
    "acknowledge": "ACKNOWLEDGE", "ack": "ACKNOWLEDGE", "roger": "ACKNOWLEDGE",
}

STOPWORDS = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or",
    "it", "its", "this", "that", "there", "be", "been", "being", "as",
    "with", "by", "from", "we", "i", "you", "they", "he", "she",
    "is", "are", "am", "has", "have", "had", "do", "does", "did",
    "our", "their", "my", "your", "his", "her", "us", "them", "so", "but",
    "if", "then", "than", "very", "just", "about",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


@dataclass
class Translation:
    """One English utterance and what became of it."""

    source: str
    composition: Composition
    consumed: list[str] = field(default_factory=list)
    unconsumed: list[str] = field(default_factory=list)

    @property
    def residue_ratio(self) -> float:
        total = len(self.consumed) + len(self.unconsumed)
        return 0.0 if total == 0 else len(self.unconsumed) / total

    @property
    def fully_composed(self) -> bool:
        return self.composition.residue is None


@dataclass
class TranslationStats:
    utterances: int
    fully_composed: int
    tokens: int
    residue_tokens: int

    @property
    def residue_rate(self) -> float:
        return 0.0 if self.tokens == 0 else self.residue_tokens / self.tokens

    def summary(self) -> str:
        s = (f"{self.utterances} utterances, {self.fully_composed} fully composed, "
             f"token residue rate {self.residue_rate * 100:.1f}%")
        if self.residue_rate > 0.25:
            s += ("\nresidue above 25%: the inventory does not cover this domain well. "
                  "See RFC §5.5.")
        return s


def stats(results: list[Translation]) -> TranslationStats:
    return TranslationStats(
        utterances=len(results),
        fully_composed=sum(1 for r in results if r.fully_composed),
        tokens=sum(len(r.consumed) + len(r.unconsumed) for r in results),
        residue_tokens=sum(len(r.unconsumed) for r in results),
    )


def split_sentences(text: str) -> list[str]:
    """Split a paragraph into utterances.  One line = one utterance minimum."""
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out += [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]
    return out


class Translator:
    """English to composition.  Rule-based, lossy, deterministic."""

    def __init__(
        self,
        head_lexicon: dict[str, tuple[str, list[str]]] | None = None,
        cue_lexicon: dict[str, str] | None = None,
        keep_residue: bool = True,
        keep_gloss: bool = True,
    ) -> None:
        self.head_lexicon = dict(head_lexicon or HEAD_LEXICON)
        self.cue_lexicon = dict(cue_lexicon or CUE_LEXICON)
        self.keep_residue = keep_residue
        self.keep_gloss = keep_gloss

    def tokenize(self, text: str) -> list[str]:
        lowered = text.lower()
        marks = ["?"] if "?" in lowered else []
        words = re.findall(r"[a-z][a-z0-9_-]*", lowered)
        return words + marks

    def find_head(self, tokens: list[str]) -> tuple[int | None, str | None]:
        """First lexicon hit wins.  Crude, and deliberately so."""
        for index, token in enumerate(tokens):
            if token in self.head_lexicon:
                return index, token
            if token.endswith("s") and token[:-1] in self.head_lexicon:
                return index, token[:-1]
            if token.endswith("es") and token[:-2] in self.head_lexicon:
                return index, token[:-2]
        return None, None

    def translate(self, text: str) -> Translation:
        tokens = self.tokenize(text)
        index, head_word = self.find_head(tokens)
        gloss = text.strip() if self.keep_gloss else None

        if head_word is None:
            comp = Composition.build(
                "SIGN", "UNKNOWN",
                residue=text.strip() if self.keep_residue else None,
                gloss=gloss,
            )
            return Translation(text, comp, [], tokens)

        head_name, baseline = self.head_lexicon[head_word]
        modifiers = {pid(n) for n in baseline}
        consumed = [head_word]
        unconsumed: list[str] = []

        for position, token in enumerate(tokens):
            if position == index:
                continue
            if token in self.cue_lexicon:
                modifiers.add(pid(self.cue_lexicon[token]))
                consumed.append(token)
            elif token in ILLOCUTION_CUES:
                if ILLOCUTION_CUES[token]:
                    modifiers.add(pid(ILLOCUTION_CUES[token]))
                consumed.append(token)
            elif token in STOPWORDS or token in self.head_lexicon:
                consumed.append(token)
            else:
                unconsumed.append(token)

        if len(modifiers) > MAX_MODIFIERS:
            modifiers = set(sorted(modifiers)[:MAX_MODIFIERS])

        residue = " ".join(unconsumed) if (self.keep_residue and unconsumed) else None
        comp = Composition(pid(head_name), frozenset(modifiers), (), residue, None, gloss)
        return Translation(text, comp, consumed, unconsumed)

    def translate_text(self, text: str) -> list[Translation]:
        return [self.translate(u) for u in split_sentences(text)]
