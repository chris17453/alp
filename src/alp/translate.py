"""English -> composition front end.

Two translators live here.

``Translator`` (default) is *compositional*: a sentence becomes a tree of
primitives with roles, in the spirit of an agglutinative language —

    "We suspect the deploy caused the outage."
        -> $RELATION.CAUSE.INFERRED :ARG0 ($EVENT.PUNCTUAL) :ARG1 ($STATE.NEGATE.BAD)

    "Latency is spiking in the eu region."
        -> $QUANTITY.INCREASE.DURATIVE :SCOPE $PLACE        names bound: SCOPE="eu"

Each noun phrase becomes a node; adjectives and cue words attach to the noun
they qualify; prepositions become roles; causal / conditional connectives
become RELATION nodes or CONDITION roles; the copula turns predicate adjectives
into modifiers on the subject; tense and negation land where they belong.

**English never enters the symbol.**  Proper names and unknown words are not
written into the composition as residue; they are bound as *data* at ASSERT
time (§5.4: "a symbol names a concept; it does not carry data").  The symbol
for "the checkout service" is ``$PROCESS.DURATIVE``; ``checkout`` is a value
attached when the symbol is asserted.  Pass ``names="residue"`` for the RFC's
residue behaviour (§5.5) instead.

``SimpleTranslator`` is the RFC's own Appendix E front end (one head, a bag of
modifiers, everything else residue), kept because the RFC's worked examples
quote its SIDs.

Neither is natural-language understanding.  Both are deterministic, rule-based,
and report what they could not compose.  The residue rate is the quality
metric (§14.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .alpb import Pid
from .composition import Composition
from . import inventory as inv
from .inventory import MAX_MODIFIERS, pid

# ---------------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------------

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
    "release": ("EVENT", ["PUNCTUAL"]),
    "rollback": ("PROCESS", ["PAST"]),
    "escalation": ("PROCESS", ["INCREASE"]),
    "cause": ("RELATION", ["CAUSE"]),
    "dependency": ("RELATION", ["DEPEND"]),
    "operator": ("AGENT", []),
    "engineer": ("AGENT", []),
    "team": ("GROUP", ["AGENT"]),
    "user": ("AGENT", []),
    "customer": ("AGENT", []),
    "agent": ("AGENT", []),
    "model": ("AGENT", []),
    "server": ("ENTITY", []),
    "host": ("ENTITY", []),
    "node": ("ENTITY", []),
    "cluster": ("GROUP", []),
    "database": ("ENTITY", []),
    "region": ("PLACE", []),
    "zone": ("PLACE", []),
    "location": ("PLACE", []),
    "count": ("QUANTITY", []),
    "number": ("QUANTITY", []),
    "rate": ("QUANTITY", ["DURATIVE"]),
    "budget": ("QUANTITY", ["BOUNDED", "COST"]),
    "cost": ("QUANTITY", ["COST"]),
    "price": ("QUANTITY", ["COST"]),
    "risk": ("PROPERTY", ["POSSIBLE", "HARM"]),
    "state": ("STATE", []),
    "status": ("STATE", []),
    "condition": ("STATE", []),
    "window": ("MOMENT", ["DURATIVE", "BOUNDED"]),
    "time": ("MOMENT", []),
    "hour": ("MOMENT", ["BOUNDED"]),
    "day": ("MOMENT", ["BOUNDED"]),
    "week": ("MOMENT", ["BOUNDED"]),
    "capacity": ("QUANTITY", ["BOUNDED"]),
    "scope": ("GROUP", ["BOUNDED"]),
    "impact": ("RELATION", ["CAUSE", "HARM"]),
    "meeting": ("EVENT", ["BOUNDED", "DURATIVE"]),
    "plan": ("SIGN", ["FUTURE", "PROPOSE"]),
    "question": ("SIGN", ["QUERY"]),
    "answer": ("SIGN", ["ASSERT"]),
    "decision": ("EVENT", ["PUNCTUAL", "COMMIT"]),
    "problem": ("STATE", ["BAD"]),
    "issue": ("STATE", ["BAD"]),
    "bug": ("STATE", ["BAD", "NEGATE"]),
    "fix": ("PROCESS", ["GOOD", "END"]),
    "change": ("EVENT", []),
    "request": ("SIGN", ["REQUEST"]),
    "person": ("AGENT", []),
    "people": ("GROUP", ["AGENT"]),
    "thing": ("ENTITY", []),
    "object": ("ENTITY", []),
    "file": ("ENTITY", []),
    "document": ("SIGN", []),
    "data": ("SIGN", []),
    "result": ("STATE", ["AFTER"]),
    "goal": ("STATE", ["DESIRED", "FUTURE"]),
    "limit": ("QUANTITY", ["BOUNDED", "EXTREME"]),
    "threshold": ("QUANTITY", ["BOUNDED"]),
    "memory": ("QUANTITY", ["BOUNDED"]),
    "traffic": ("QUANTITY", ["DURATIVE"]),
    "load": ("QUANTITY", ["DURATIVE"]),
    "queue": ("GROUP", ["BOUNDED"]),
    "backlog": ("GROUP", ["PAST"]),
    "log": ("SIGN", ["PAST", "OBSERVED"]),
    "metric": ("QUANTITY", ["OBSERVED"]),
    "test": ("PROCESS", ["BOUNDED", "OBSERVED"]),
    "check": ("PROCESS", ["BOUNDED", "OBSERVED"]),
    "world": ("PLACE", ["ALL"]),
    "network": ("GROUP", ["ENTITY"]),
    "system": ("GROUP", ["PROCESS"]),
    "language": ("SIGN", ["GROUP"]),
    "symbol": ("SIGN", []),
    "word": ("SIGN", []),
    "idea": ("SIGN", ["BELIEVED"]),
    "truth": ("STATE", ["KNOWN", "AFFIRM"]),
}

# Verbs that become the clause predicate: word -> (head, modifiers).
# The subject is ARG0, the object ARG1.  Causal verbs are handled separately.
VERB_LEXICON: dict[str, tuple[str, list[str]]] = {
    "resolve": ("EVENT", ["END", "GOOD"]),
    "fix": ("PROCESS", ["END", "GOOD"]),
    "repair": ("PROCESS", ["END", "GOOD"]),
    "restart": ("PROCESS", ["BEGIN", "REPEAT"]),
    "start": ("EVENT", ["BEGIN"]),
    "begin": ("EVENT", ["BEGIN"]),
    "stop": ("EVENT", ["END"]),
    "end": ("EVENT", ["END"]),
    "finish": ("EVENT", ["END"]),
    "fail": ("EVENT", ["NEGATE", "BAD"]),
    "crash": ("EVENT", ["NEGATE", "BAD", "PUNCTUAL"]),
    "break": ("EVENT", ["NEGATE", "BAD"]),
    "deploy": ("EVENT", ["PUNCTUAL"]),
    "ship": ("EVENT", ["PUNCTUAL"]),
    "roll": ("PROCESS", ["PAST"]),
    "escalate": ("PROCESS", ["INCREASE"]),
    "page": ("SIGN", ["WARN", "PUNCTUAL"]),
    "notify": ("SIGN", ["ASSERT"]),
    "tell": ("SIGN", ["ASSERT"]),
    "say": ("SIGN", ["ASSERT"]),
    "report": ("SIGN", ["ASSERT", "OBSERVED"]),
    "confirm": ("SIGN", ["ASSERT", "KNOWN"]),
    "verify": ("PROCESS", ["OBSERVED", "KNOWN"]),
    "ask": ("SIGN", ["QUERY"]),
    "request": ("SIGN", ["REQUEST"]),
    "need": ("STATE", ["REQUIRED"]),
    "require": ("STATE", ["REQUIRED"]),
    "want": ("STATE", ["DESIRED"]),
    "propose": ("SIGN", ["PROPOSE"]),
    "suggest": ("SIGN", ["PROPOSE"]),
    "recommend": ("SIGN", ["PROPOSE", "GOOD"]),
    "promise": ("SIGN", ["COMMIT"]),
    "commit": ("SIGN", ["COMMIT"]),
    "refuse": ("SIGN", ["REFUSE"]),
    "decline": ("SIGN", ["REFUSE"]),
    "acknowledge": ("SIGN", ["ACKNOWLEDGE"]),
    "warn": ("SIGN", ["WARN"]),
    "observe": ("EVENT", ["OBSERVED"]),
    "see": ("EVENT", ["OBSERVED"]),
    "measure": ("EVENT", ["OBSERVED"]),
    "detect": ("EVENT", ["OBSERVED", "PUNCTUAL"]),
    "predict": ("SIGN", ["PREDICTED"]),
    "expect": ("SIGN", ["PREDICTED", "BELIEVED"]),
    "know": ("STATE", ["KNOWN"]),
    "believe": ("STATE", ["BELIEVED"]),
    "think": ("STATE", ["BELIEVED"]),
    "suspect": ("STATE", ["INFERRED"]),
    "infer": ("STATE", ["INFERRED"]),
    "dispute": ("STATE", ["CONTESTED"]),
    "increase": ("PROCESS", ["INCREASE"]),
    "rise": ("PROCESS", ["INCREASE"]),
    "grow": ("PROCESS", ["INCREASE"]),
    "spike": ("EVENT", ["INCREASE", "PUNCTUAL"]),
    "decrease": ("PROCESS", ["DECREASE"]),
    "drop": ("PROCESS", ["DECREASE"]),
    "fall": ("PROCESS", ["DECREASE"]),
    "reduce": ("PROCESS", ["DECREASE"]),
    "allow": ("STATE", ["PERMITTED"]),
    "permit": ("STATE", ["PERMITTED"]),
    "forbid": ("STATE", ["FORBIDDEN"]),
    "block": ("STATE", ["FORBIDDEN"]),
    "run": ("PROCESS", ["DURATIVE"]),
    "work": ("PROCESS", ["DURATIVE", "GOOD"]),
    "wait": ("STATE", ["DURATIVE"]),
    "move": ("PROCESS", []),
    "send": ("PROCESS", ["PUNCTUAL"]),
    "receive": ("EVENT", ["PUNCTUAL"]),
    "join": ("EVENT", ["BEGIN"]),
    "leave": ("EVENT", ["END"]),
    "replace": ("EVENT", ["PUNCTUAL", "END", "BEGIN"]),
    "cost": ("QUANTITY", ["COST"]),
    "harm": ("EVENT", ["HARM", "BAD"]),
    "help": ("EVENT", ["BENEFIT", "GOOD"]),
    "affect": ("RELATION", ["CAUSE"]),
    "impact": ("RELATION", ["CAUSE", "HARM"]),
    "mean": ("RELATION", ["CORRELATE"]),
}

# Causal connectives / verbs: word -> causal primitive.  These build
#   $RELATION.<X> :ARG0 <cause side> :ARG1 <effect side>
CAUSAL_VERBS: dict[str, str] = {
    "cause": "CAUSE", "trigger": "TRIGGER", "prevent": "PREVENT", "enable": "ENABLE",
    "depend": "DEPEND", "correlate": "CORRELATE", "lead": "CAUSE", "make": "CAUSE",
    "stop": "PREVENT", "block": "PREVENT", "allow": "ENABLE", "let": "ENABLE",
    "require": "DEPEND",
}

# Cue words that qualify the nearest noun (or the predicate).
CUE_LEXICON: dict[str, str] = {
    "must": "NECESSARY", "shall": "NECESSARY", "required": "REQUIRED", "mandatory": "REQUIRED",
    "may": "POSSIBLE", "might": "POSSIBLE", "could": "POSSIBLE", "can": "POSSIBLE",
    "possible": "POSSIBLE", "possibly": "POSSIBLE", "maybe": "POSSIBLE", "perhaps": "POSSIBLE",
    "should": "DESIRED", "wanted": "DESIRED", "desired": "DESIRED",
    "allowed": "PERMITTED", "permitted": "PERMITTED", "ok": "PERMITTED", "okay": "PERMITTED",
    "forbidden": "FORBIDDEN", "blocked": "FORBIDDEN", "banned": "FORBIDDEN",
    "optional": "OPTIONAL", "hypothetical": "HYPOTHETICAL", "would": "HYPOTHETICAL",
    "true": "AFFIRM", "confirmed": "KNOWN", "certain": "KNOWN",

    "high": "HIGH", "severe": "EXTREME", "critical": "EXTREME", "extreme": "EXTREME",
    "maximum": "EXTREME", "max": "EXTREME", "urgent": "HIGH", "major": "HIGH", "big": "HIGH", "large": "HIGH",
    "huge": "EXTREME", "massive": "EXTREME",
    "low": "LOW", "minor": "LOW", "small": "LOW", "little": "LOW", "slight": "LOW", "minimal": "LOW",
    "moderate": "MID", "medium": "MID", "normal": "MID", "average": "MID",
    "all": "ALL", "every": "ALL", "total": "ALL", "whole": "ALL", "entire": "ALL", "full": "ALL",
    "some": "SOME", "partial": "SOME", "several": "SOME", "few": "SOME", "many": "SOME", "most": "SOME",
    "none": "NONE", "zero": "NONE", "empty": "NONE",
    "rising": "INCREASE", "increasing": "INCREASE", "growing": "INCREASE", "higher": "INCREASE",
    "spiking": "INCREASE", "more": "INCREASE", "up": "INCREASE",
    "falling": "DECREASE", "decreasing": "DECREASE", "dropping": "DECREASE", "less": "DECREASE", "lower": "DECREASE",
    "unbounded": "UNBOUNDED", "unlimited": "UNBOUNDED", "infinite": "UNBOUNDED",
    "bounded": "BOUNDED", "capped": "BOUNDED", "limited": "BOUNDED", "finite": "BOUNDED",

    "was": "PAST", "were": "PAST", "previously": "PAST", "earlier": "PAST", "yesterday": "PAST",
    "ago": "PAST", "old": "PAST", "former": "PAST", "last": "PAST", "did": "PAST", "had": "PAST",
    "now": "NOW", "currently": "NOW", "today": "NOW", "current": "NOW", "present": "NOW",
    "will": "FUTURE", "tomorrow": "FUTURE", "soon": "FUTURE", "upcoming": "FUTURE", "next": "FUTURE",
    "later": "FUTURE", "eventually": "FUTURE", "future": "FUTURE",
    "ongoing": "DURATIVE", "sustained": "DURATIVE", "continuous": "DURATIVE", "still": "DURATIVE",
    "long": "DURATIVE", "always": "DURATIVE", "constantly": "DURATIVE",
    "instant": "PUNCTUAL", "immediately": "PUNCTUAL", "immediate": "PUNCTUAL", "sudden": "PUNCTUAL",
    "suddenly": "PUNCTUAL", "once": "PUNCTUAL", "momentary": "PUNCTUAL",
    "repeated": "REPEAT", "recurring": "REPEAT", "again": "REPEAT", "periodic": "REPEAT",
    "frequently": "REPEAT", "often": "REPEAT", "intermittent": "REPEAT",
    "started": "BEGIN", "began": "BEGIN", "initial": "BEGIN", "first": "BEGIN", "new": "BEGIN",
    "ended": "END", "stopped": "END", "final": "END", "done": "END", "over": "END", "complete": "END",
    "before": "BEFORE", "prior": "BEFORE", "after": "AFTER", "during": "DURING", "while": "DURING",

    "known": "KNOWN", "verified": "KNOWN", "sure": "KNOWN", "definitely": "KNOWN", "clearly": "KNOWN",
    "likely": "BELIEVED", "probably": "BELIEVED", "believed": "BELIEVED",
    "suspected": "INFERRED", "inferred": "INFERRED", "apparently": "INFERRED", "seems": "INFERRED",
    "unknown": "UNKNOWN", "unclear": "UNKNOWN", "unsure": "UNKNOWN", "uncertain": "UNKNOWN",
    "disputed": "CONTESTED", "contested": "CONTESTED", "controversial": "CONTESTED",
    "observed": "OBSERVED", "measured": "OBSERVED", "seen": "OBSERVED", "visible": "OBSERVED",
    "predicted": "PREDICTED", "forecast": "PREDICTED", "expected": "PREDICTED", "projected": "PREDICTED",

    "good": "GOOD", "healthy": "GOOD", "nominal": "GOOD", "fine": "GOOD", "great": "GOOD", "well": "GOOD",
    "correct": "GOOD", "right": "GOOD", "stable": "GOOD",
    "bad": "BAD", "degraded": "BAD", "broken": "BAD", "wrong": "BAD", "poor": "BAD", "slow": "BAD",
    "safe": "SAFE", "secure": "SAFE",
    "harmful": "HARM", "dangerous": "HARM", "damaged": "HARM", "hurt": "HARM",
    "expensive": "COST", "costly": "COST", "cheap": "BENEFIT", "useful": "BENEFIT", "beneficial": "BENEFIT",
    "important": "REQUIRED", "necessary": "NECESSARY", "essential": "NECESSARY",
}

NEGATORS = {"not", "no", "never", "down", "failed", "unavailable", "offline", "without", "nothing", "cannot", "isnt", "isn't", "dont", "don't", "wont", "won't", "nor", "neither"}
COPULA = {"is", "are", "am", "was", "were", "be", "been", "being", "seems", "looks", "remains", "stays", "gets", "got", "become", "became"}
AUXILIARIES = {"do", "does", "did", "has", "have", "had", "will", "would", "can", "could", "may", "might", "must", "shall", "should"}
DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "its", "our", "their", "my", "your", "his", "her", "some", "any", "each"}
PRONOUNS = {"we": "GROUP", "i": "AGENT", "you": "AGENT", "they": "GROUP", "he": "AGENT", "she": "AGENT",
            "it": "ENTITY", "us": "GROUP", "them": "GROUP", "me": "AGENT", "someone": "AGENT", "everyone": "GROUP"}
PREPOSITION_ROLE: dict[str, str] = {
    "in": "SCOPE", "at": "SCOPE", "on": "SCOPE", "within": "SCOPE", "across": "SCOPE", "over": "SCOPE",
    "of": "SCOPE", "about": "SCOPE", "for": "ARG2", "to": "ARG2", "with": "ARG2", "by": "ARG0", "from": "ARG0",
    "per": "MEASURE", "under": "CONDITION", "against": "ARG1", "into": "ARG1",
}
ILLOCUTION: dict[str, str] = {
    "please": "REQUEST", "?": "QUERY", "what": "QUERY", "when": "QUERY", "why": "QUERY",
    "which": "QUERY", "how": "QUERY", "who": "QUERY", "where": "QUERY",
    "propose": "PROPOSE", "suggest": "PROPOSE", "recommend": "PROPOSE",
    "promise": "COMMIT", "warning": "WARN", "caution": "WARN", "ack": "ACKNOWLEDGE", "roger": "ACKNOWLEDGE",
}
CONNECTIVES = {
    "because": "CAUSE", "since": "CAUSE", "as": "CAUSE", "so": "CAUSE_REV", "therefore": "CAUSE_REV",
    "hence": "CAUSE_REV", "thus": "CAUSE_REV", "if": "CONDITION", "unless": "CONDITION_NEG",
    "when": "CONDITION", "whenever": "CONDITION", "and": "AND", "but": "AND", "then": "AND", "or": "AND",
}
FILLERS = {"very", "just", "really", "quite", "also", "too", "there", "here", "yet", "even", "only", "already", "that", "which", "who", "whom", "of", "back", "out", "off", "away"}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z0-9\"'(])")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_'\-]*|[?]|,")


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass
class Translation:
    """One clause and what became of it."""

    source: str
    composition: Composition
    consumed: list[str] = field(default_factory=list)
    unconsumed: list[str] = field(default_factory=list)      # true residue (untranslatable)
    names: dict[str, str] = field(default_factory=dict)      # role path -> bound English name

    @property
    def residue_ratio(self) -> float:
        total = len(self.consumed) + len(self.unconsumed) + len(self.names)
        return 0.0 if total == 0 else (len(self.unconsumed) + len(self.names)) / total

    @property
    def fully_composed(self) -> bool:
        return not self.composition.residue_bearing() and not self.names

    @property
    def value(self) -> Any:
        """The value to bind at ASSERT time: ``true`` or ``{"names": {...}}``."""
        return {"names": dict(self.names)} if self.names else True


@dataclass
class TranslationStats:
    utterances: int
    fully_composed: int
    tokens: int
    residue_tokens: int
    bound_names: int

    @property
    def residue_rate(self) -> float:
        return 0.0 if self.tokens == 0 else (self.residue_tokens + self.bound_names) / self.tokens

    def summary(self) -> str:
        s = (f"{self.utterances} clauses, {self.fully_composed} fully composed from primitives, "
             f"{self.bound_names} names bound as data, {self.residue_tokens} residue tokens, "
             f"English leakage {self.residue_rate * 100:.1f}%")
        if self.residue_rate > 0.25:
            s += "\nleakage above 25%: the inventory / lexicon does not cover this domain well (RFC §5.5)."
        return s


def stats(results: list[Translation]) -> TranslationStats:
    return TranslationStats(
        utterances=len(results),
        fully_composed=sum(1 for r in results if r.fully_composed),
        tokens=sum(len(r.consumed) + len(r.unconsumed) + len(r.names) for r in results),
        residue_tokens=sum(len(r.unconsumed) for r in results),
        bound_names=sum(len(r.names) for r in results),
    )


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out += [s for s in _SENTENCE_SPLIT.split(line) if s.strip()]
    return out


# ---------------------------------------------------------------------------
# Morphology
# ---------------------------------------------------------------------------

def _stem_candidates(w: str) -> list[tuple[str, list[str]]]:
    """(stem, implied modifiers) candidates for an inflected word, most specific first."""
    out: list[tuple[str, list[str]]] = [(w, [])]
    if w.endswith("ies") and len(w) > 4:
        out.append((w[:-3] + "y", []))
    if w.endswith("es") and len(w) > 4:
        out.append((w[:-2], []))
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        out.append((w[:-1], []))
    if w.endswith("ied") and len(w) > 4:
        out.append((w[:-3] + "y", ["PAST"]))
    if w.endswith("ed") and len(w) > 4:
        out.append((w[:-2], ["PAST"]))
        out.append((w[:-1], ["PAST"]))          # resolved -> resolve
        if len(w) > 5 and w[-3] == w[-4]:
            out.append((w[:-3], ["PAST"]))      # stopped -> stop
    if w.endswith("ing") and len(w) > 5:
        out.append((w[:-3], ["DURATIVE"]))
        out.append((w[:-3] + "e", ["DURATIVE"]))  # spiking -> spike
        if len(w) > 6 and w[-4] == w[-5]:
            out.append((w[:-4], ["DURATIVE"]))  # running -> run
    if w.endswith("ly") and len(w) > 4:
        out.append((w[:-2], []))
    if w.endswith("er") and len(w) > 4:
        out.append((w[:-2], []))
    return out


# ---------------------------------------------------------------------------
# Compositional translator
# ---------------------------------------------------------------------------

@dataclass
class _NP:
    head: Pid | None = None
    mods: set = field(default_factory=set)
    names: list[str] = field(default_factory=list)
    roles: dict[int, "_NP"] = field(default_factory=dict)
    words: list[str] = field(default_factory=list)

    def empty(self) -> bool:
        return self.head is None and not self.mods and not self.names and not self.roles


class Translator:
    """Compositional English -> ALP.  See the module docstring."""

    def __init__(self, names: str = "bind", keep_gloss: bool = True,
                 head_lexicon: dict | None = None, verb_lexicon: dict | None = None, cue_lexicon: dict | None = None) -> None:
        if names not in ("bind", "residue", "drop"):
            raise ValueError("names must be bind | residue | drop")
        self.names_mode = names
        self.keep_gloss = keep_gloss
        self.heads = dict(head_lexicon or HEAD_LEXICON)
        self.verbs = dict(verb_lexicon or VERB_LEXICON)
        self.cues = dict(cue_lexicon or CUE_LEXICON)

    # -- lexical lookup ----------------------------------------------------------
    def _lookup(self, w: str) -> tuple[str, Any, list[str]] | None:
        """Classify a word: ('head'|'verb'|'causal'|'cue', payload, implied_mods)."""
        for stem, implied in _stem_candidates(w):
            if stem in self.cues:
                return "cue", self.cues[stem], implied
            if stem in CAUSAL_VERBS and stem != w or (stem in CAUSAL_VERBS and stem not in self.heads):
                return "causal", CAUSAL_VERBS[stem], implied
            if stem in self.heads and (stem == w or not implied or implied == []):
                return "head", self.heads[stem], implied
            if stem in self.verbs:
                return "verb", self.verbs[stem], implied
            if stem in self.heads:
                return "head", self.heads[stem], implied
            if stem in CAUSAL_VERBS:
                return "causal", CAUSAL_VERBS[stem], implied
        return None

    def tokenize(self, text: str) -> list[str]:
        toks = [t.lower() for t in _WORD.findall(text)]
        if "?" in text and "?" not in toks:
            toks.append("?")
        return toks

    # -- clause splitting --------------------------------------------------------------
    def _split_clauses(self, toks: list[str]) -> list[tuple[str | None, list[str]]]:
        """Split on connectives.  Returns [(connective_before_clause, tokens)]."""
        clauses: list[tuple[str | None, list[str]]] = []
        cur: list[str] = []
        conn: str | None = None
        for t in toks:
            if t in CONNECTIVES and cur and t not in ("as",):
                clauses.append((conn, cur))
                cur, conn = [], CONNECTIVES[t]
            elif t == ",":
                if cur and conn in ("CONDITION", "CONDITION_NEG", "CAUSE"):
                    clauses.append((conn, cur))
                    cur, conn = [], None
                continue
            elif t in CONNECTIVES and not cur:
                conn = CONNECTIVES[t]
            else:
                cur.append(t)
        if cur:
            clauses.append((conn, cur))
        return clauses

    # -- clause -> tree -------------------------------------------------------------------
    def _parse_clause(self, toks: list[str]) -> tuple[_NP, list[str], list[str]]:
        """Return (tree, consumed, unconsumed)."""
        consumed: list[str] = []
        unconsumed: list[str] = []
        subject = _NP()
        obj = _NP()
        pred: _NP | None = None           # verb predicate
        causal: str | None = None
        clause_mods: set = set()          # tense / negation / illocution at clause level
        pending_mods: set = set()         # adjectives seen before their noun
        cur = subject
        role_target: tuple[_NP, int] | None = None   # (owner, role code) while inside a PP
        after_copula = False
        after_verb = False
        negate_next = False

        def attach(mods: set, target: _NP) -> None:
            target.mods |= mods

        def new_np_for_pp(owner: _NP, role: int) -> _NP:
            np = _NP()
            owner.roles[role] = np
            return np

        i = 0
        while i < len(toks):
            t = toks[i]
            i += 1
            if t in AUXILIARIES:
                consumed.append(t)
                if t in self.cues:
                    clause_mods.add(pid(self.cues[t]))
                continue
            if t in DETERMINERS or t in FILLERS:
                consumed.append(t)
                continue
            if t in NEGATORS:
                consumed.append(t)
                negate_next = True
                if t in ("down", "failed", "unavailable", "offline", "broken"):
                    clause_mods.add(pid("BAD"))
                continue
            if t in ILLOCUTION:
                consumed.append(t)
                clause_mods.add(pid(ILLOCUTION[t]))
                if t in ("what", "when", "why", "which", "how", "who", "where"):
                    continue
                if t not in self.verbs:
                    continue
            if t in COPULA:
                consumed.append(t)
                if t in ("was", "were"):
                    clause_mods.add(pid("PAST"))
                after_copula = True
                if pending_mods:
                    attach(pending_mods, subject)
                    pending_mods = set()
                cur = subject
                role_target = None
                continue
            if t in PRONOUNS:
                consumed.append(t)
                target = cur
                if target.head is None:
                    target.head = pid(PRONOUNS[t])
                if negate_next:
                    target.mods.add(pid("NEGATE"))
                    negate_next = False
                continue
            if t in PREPOSITION_ROLE:
                consumed.append(t)
                role = inv.ROLES[PREPOSITION_ROLE[t]]
                owner = pred if (pred is not None and after_verb) else (obj if (after_verb and not obj.empty()) else subject)
                if owner is subject and after_copula and t in ("in", "at", "on", "within", "across", "of"):
                    owner = subject
                if pending_mods:
                    attach(pending_mods, cur)
                    pending_mods = set()
                cur = new_np_for_pp(owner, role)
                role_target = (owner, role)
                continue

            hit = self._lookup(t)
            if hit is None:
                # unknown content word: a name, bound as data
                consumed_here = False
                if re.fullmatch(r"[a-z][a-z0-9_'\-]*", t):
                    cur.names.append(t)
                    cur.words.append(t)
                    consumed_here = True
                if not consumed_here:
                    unconsumed.append(t)
                if negate_next:
                    cur.mods.add(pid("NEGATE"))
                    negate_next = False
                continue

            kind, payload, implied = hit
            consumed.append(t)
            if kind == "cue":
                m = {pid(payload)} | {pid(x) for x in implied}
                if negate_next:
                    m.add(pid("NEGATE"))
                    negate_next = False
                if after_copula or after_verb:
                    # predicate adjective -> qualifies the subject (or the object just built)
                    target = obj if (after_verb and not obj.empty()) else (pred if (after_verb and pred is not None and cur is not subject and role_target is None) else subject)
                    if role_target is not None:
                        target = cur
                    attach(m, target)
                else:
                    if cur.head is not None or cur.names:
                        attach(m, cur)
                    else:
                        pending_mods |= m
                continue
            if kind == "head":
                head_name, baseline = payload
                target = cur
                if target.head is not None and not (role_target is not None):
                    # a second noun in the same NP: compound noun -> the later noun is the head,
                    # earlier one becomes SCOPE  ("customer impact" -> impact over customers)
                    prev = _NP(head=target.head, mods=set(target.mods), names=list(target.names))
                    target.head, target.mods, target.names = None, set(), []
                    target.roles[inv.ROLES["SCOPE"]] = prev
                target.head = pid(head_name)
                target.mods |= {pid(x) for x in baseline} | {pid(x) for x in implied} | pending_mods
                pending_mods = set()
                target.words.append(t)
                if negate_next:
                    target.mods.add(pid("NEGATE"))
                    negate_next = False
                if after_copula and target is subject and subject.head is not None and target is not subject:
                    pass
                continue
            if kind == "causal":
                causal = payload
                if implied:
                    clause_mods |= {pid(x) for x in implied}
                if negate_next:
                    clause_mods.add(pid("NEGATE"))
                    negate_next = False
                if pred is not None and not obj.empty():
                    # "we suspect X caused Y": the mental verb's epistemic stance
                    # qualifies the relation; X (the object so far) is the cause.
                    clause_mods |= {m for m in pred.mods if isinstance(m, Pid) and m.cls == inv.CLASS_EPISTEMIC}
                    pred = None
                    subject = obj
                    obj = _NP()
                after_verb = True
                cur = obj
                role_target = None
                continue
            if kind == "verb":
                head_name, baseline = payload
                pred = _NP(head=pid(head_name), mods={pid(x) for x in baseline} | {pid(x) for x in implied} | pending_mods)
                pending_mods = set()
                pred.words.append(t)
                if negate_next:
                    pred.mods.add(pid("NEGATE"))
                    negate_next = False
                after_verb = True
                cur = obj
                role_target = None
                continue

        if pending_mods:
            attach(pending_mods, subject if not subject.empty() or obj.empty() else obj)
        if negate_next:
            (pred or subject).mods.add(pid("NEGATE"))

        # assemble
        if causal is not None:
            rel = _NP(head=pid("RELATION"), mods={pid(causal)} | clause_mods)
            if not subject.empty():
                rel.roles[inv.ROLES["ARG0"]] = subject
            if not obj.empty():
                rel.roles[inv.ROLES["ARG1"]] = obj
            if pred is not None:
                rel.roles.setdefault(inv.ROLES["ARG1"], pred)
            return rel, consumed, unconsumed
        if pred is not None:
            pred.mods |= clause_mods
            # subject-verb-object: mental-state verbs make the object the content (ARG1)
            if not subject.empty():
                pred.roles[inv.ROLES["ARG0"]] = subject
            if not obj.empty():
                pred.roles[inv.ROLES["ARG1"]] = obj
            return pred, consumed, unconsumed
        subject.mods |= clause_mods
        if not obj.empty():
            subject.roles.setdefault(inv.ROLES["ARG1"], obj)
        return subject, consumed, unconsumed

    # -- tree -> Composition ------------------------------------------------------------------
    def _to_node(self, np: _NP, path: str, names: dict[str, str], residue_words: list[str]) -> Composition:
        head = np.head
        if head is None:
            # a bare name or bare modifiers: pick a head by context
            if np.names:
                head = pid("ENTITY")
            elif any(isinstance(m, Pid) and m.cls == inv.CLASS_SCALAR for m in np.mods):
                head = pid("QUANTITY")
            else:
                head = pid("STATE")
        mods = {m for m in np.mods if isinstance(m, Pid) and m.cls != inv.CLASS_ONTOLOGICAL}
        # ontological cues used as modifiers (e.g. GROUP from "team") become the head if none given
        for m in np.mods:
            if isinstance(m, Pid) and m.cls == inv.CLASS_ONTOLOGICAL and np.head is None:
                head = m
        if len(mods) > MAX_MODIFIERS:
            mods = set(sorted(mods, key=lambda p: p.code)[:MAX_MODIFIERS])
        roles = {}
        for code in sorted(np.roles):
            sub = np.roles[code]
            if sub.empty():
                continue
            rpath = f"{path}/{inv.ROLE_NAMES[code]}" if path else inv.ROLE_NAMES[code]
            roles[code] = self._to_node(sub, rpath, names, residue_words)
        residue = None
        if np.names:
            if self.names_mode == "bind":
                names[path or "."] = " ".join(np.names)
            elif self.names_mode == "residue":
                residue = " ".join(np.names)
            residue_words.extend(np.names) if self.names_mode == "drop" else None
        if head.cls == inv.CLASS_ONTOLOGICAL and inv.name_of(head) == "PLACE" and not np.names and not mods and not roles:
            pass
        return Composition(head, frozenset(mods), tuple(roles.items()), residue, None, None)

    # -- public --------------------------------------------------------------------------------------
    def translate(self, text: str) -> list[Translation]:
        """Translate one sentence; may yield several clauses."""
        toks = self.tokenize(text)
        clauses = self._split_clauses(toks)
        gloss = text.strip() if self.keep_gloss else None
        results: list[Translation] = []
        prev: Translation | None = None
        pending_cond: Composition | None = None
        pending_cond_names: dict[str, str] = {}
        for conn, ctoks in clauses:
            tree, consumed, unconsumed = self._parse_clause(ctoks)
            names: dict[str, str] = {}
            dropped: list[str] = []
            comp = self._to_node(tree, "", names, dropped)
            if tree.empty() and not names:
                comp = Composition.build("SIGN", "UNKNOWN")
                if self.names_mode == "residue":
                    comp = Composition.build("SIGN", "UNKNOWN", residue=" ".join(ctoks))
                elif self.names_mode == "bind":
                    names["."] = " ".join(ctoks)
                unconsumed = list(ctoks)
            unconsumed += dropped

            if conn in ("CAUSE", "CAUSE_REV") and prev is not None:
                cause, effect = (comp, prev.composition) if conn == "CAUSE" else (prev.composition, comp)
                cn = {("ARG0/" + k if k != "." else "ARG0"): v for k, v in (names if conn == "CAUSE" else prev.names).items()}
                en = {("ARG1/" + k if k != "." else "ARG1"): v for k, v in (prev.names if conn == "CAUSE" else names).items()}
                rel = Composition.build("RELATION", "CAUSE", roles={"ARG0": cause, "ARG1": effect}, gloss=gloss)
                prev = Translation(text, rel, prev.consumed + consumed, prev.unconsumed + unconsumed, {**cn, **en})
                results[-1] = prev
                continue
            if conn in ("CONDITION", "CONDITION_NEG"):
                cond = comp if conn == "CONDITION" else Composition(comp.head, comp.modifiers | {pid("NEGATE")}, comp.roles)
                if prev is not None:
                    main = prev.composition
                    new = Composition(main.head, main.modifiers, dict(main.roles) | {inv.ROLES["CONDITION"]: cond}, main.residue, None, gloss)
                    cn = {("CONDITION/" + k if k != "." else "CONDITION"): v for k, v in names.items()}
                    prev = Translation(text, new, prev.consumed + consumed, prev.unconsumed + unconsumed, {**prev.names, **cn})
                    results[-1] = prev
                else:
                    pending_cond, pending_cond_names = cond, names
                continue
            if pending_cond is not None:
                comp = Composition(comp.head, comp.modifiers, dict(comp.roles) | {inv.ROLES["CONDITION"]: pending_cond}, comp.residue)
                names.update({("CONDITION/" + k if k != "." else "CONDITION"): v for k, v in pending_cond_names.items()})
                pending_cond = None
            comp = comp.with_gloss(gloss)
            prev = Translation(text, comp, consumed, unconsumed, names)
            results.append(prev)
        return results

    def translate_text(self, text: str) -> list[Translation]:
        out: list[Translation] = []
        for s in split_sentences(text):
            out += self.translate(s)
        return out


# ---------------------------------------------------------------------------
# The RFC's Appendix E reference front end (kept for its quoted SIDs)
# ---------------------------------------------------------------------------

_SIMPLE_ILLOCUTION = {
    "please": "REQUEST", "can": "REQUEST", "would": "REQUEST",
    "?": "QUERY", "what": "QUERY", "when": "QUERY", "why": "QUERY",
    "which": "QUERY", "how": "QUERY", "is": None,
    "warn": "WARN", "warning": "WARN", "caution": "WARN",
    "propose": "PROPOSE", "suggest": "PROPOSE", "recommend": "PROPOSE",
    "commit": "COMMIT", "promise": "COMMIT",
    "refuse": "REFUSE", "decline": "REFUSE", "cannot": "REFUSE",
    "acknowledge": "ACKNOWLEDGE", "ack": "ACKNOWLEDGE", "roger": "ACKNOWLEDGE",
}
_SIMPLE_CUES = dict(CUE_LEXICON, **{
    "not": "NEGATE", "no": "NEGATE", "never": "NEGATE", "down": "NEGATE", "failed": "NEGATE",
    "unavailable": "NEGATE", "want": "DESIRED", "need": "REQUIRED", "spike": "INCREASE",
    "resolved": "END", "because": "CAUSE", "caused": "CAUSE", "due": "CAUSE",
    "prevents": "PREVENT", "prevented": "PREVENT", "enables": "ENABLE", "enabled": "ENABLE",
    "triggered": "TRIGGER", "triggers": "TRIGGER", "depends": "DEPEND", "requires": "DEPEND",
    "correlated": "CORRELATE", "believe": "BELIEVED", "think": "BELIEVED", "suspect": "INFERRED",
    "saw": "OBSERVED", "harm": "HARM", "damage": "HARM", "benefit": "BENEFIT", "start": "BEGIN",
})
_SIMPLE_STOP = {
    "a", "an", "the", "of", "to", "in", "on", "at", "for", "and", "or", "it", "its", "this", "that",
    "there", "be", "been", "being", "as", "with", "by", "from", "we", "i", "you", "they", "he", "she",
    "is", "are", "am", "has", "have", "had", "do", "does", "did", "our", "their", "my", "your", "his",
    "her", "us", "them",
}


class SimpleTranslator:
    """RFC-ALP-001 Appendix E: first head noun wins, cue words become modifiers,
    everything else is residue.  Reproduces the SIDs quoted in the RFC."""

    def __init__(self, keep_residue: bool = True, keep_gloss: bool = True) -> None:
        self.keep_residue = keep_residue
        self.keep_gloss = keep_gloss

    def tokenize(self, text: str) -> list[str]:
        lowered = text.lower()
        marks = ["?"] if "?" in lowered else []
        return re.findall(r"[a-z][a-z0-9_-]*", lowered) + marks

    def translate(self, text: str) -> Translation:
        toks = self.tokenize(text)
        gloss = text.strip() if self.keep_gloss else None
        idx, head = None, None
        for i, t in enumerate(toks):
            if t in HEAD_LEXICON:
                idx, head = i, t
                break
            if t.endswith("s") and t[:-1] in HEAD_LEXICON:
                idx, head = i, t[:-1]
                break
        if head is None:
            comp = Composition.build("SIGN", "UNKNOWN", residue=text.strip() if self.keep_residue else None, gloss=gloss)
            return Translation(text, comp, [], toks)
        head_name, baseline = HEAD_LEXICON[head]
        mods = {pid(n) for n in baseline}
        consumed, unconsumed = [head], []
        for i, t in enumerate(toks):
            if i == idx:
                continue
            if t in _SIMPLE_CUES:
                mods.add(pid(_SIMPLE_CUES[t]))
                consumed.append(t)
            elif t in _SIMPLE_ILLOCUTION:
                if _SIMPLE_ILLOCUTION[t]:
                    mods.add(pid(_SIMPLE_ILLOCUTION[t]))
                consumed.append(t)
            elif t in _SIMPLE_STOP or t in HEAD_LEXICON:
                consumed.append(t)
            else:
                unconsumed.append(t)
        if len(mods) > MAX_MODIFIERS:
            mods = set(sorted(mods)[:MAX_MODIFIERS])
        residue = " ".join(unconsumed) if (self.keep_residue and unconsumed) else None
        comp = Composition(pid(head_name), frozenset(mods), (), residue, None, gloss)
        return Translation(text, comp, consumed, unconsumed)

    def translate_text(self, text: str) -> list[Translation]:
        return [self.translate(s) for s in split_sentences(text)]
