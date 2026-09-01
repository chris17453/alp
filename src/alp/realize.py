"""ALP -> English: a surface realizer.

``realize(composition, value)`` produces one plain English sentence from a
composition tree and the literals bound to it, so a transcript can be read
back without its source.  It is hydration (§8.3): generated surface form that
must never re-enter the stream.

Content words are recovered by *reverse lookup* against the translator's
lexicons: a node's head and modifiers are matched to the noun (or, for a
clause, the verb) whose lexicon entry they best explain — PROCESS.DURATIVE
reads "service", STATE.NEGATE.BAD "outage", AGENT.EXTREME "king",
PROCESS.REPEAT.BEGIN "restart".  Bound names and numbers override.  What the
composition genuinely does not encode ("server" vs "host") comes back as the
generic noun for the head ("thing"), which is the honest result.
"""

from __future__ import annotations

from typing import Any

from .alpb import Pid, Ref
from .composition import Composition, Node
from . import inventory as inv
from .inventory import ROLES, ROLE_NAMES
from . import translate as T

GENERIC_NOUN = {
    "ENTITY": "thing", "PROCESS": "process", "PROPERTY": "property", "RELATION": "relation",
    "QUANTITY": "amount", "AGENT": "someone", "STATE": "state", "PLACE": "place", "MOMENT": "time",
    "SIGN": "message", "EVENT": "event", "GROUP": "group",
}
GENERIC_VERB = {"PROCESS": "run", "EVENT": "happen", "STATE": "be", "SIGN": "say", "RELATION": "relate to",
                "ENTITY": "be", "AGENT": "act", "PROPERTY": "be", "QUANTITY": "be", "PLACE": "be", "MOMENT": "be", "GROUP": "be"}

GRAMMATICAL = {inv.CLASS_MODAL, inv.CLASS_TEMPORAL, inv.CLASS_EPISTEMIC, inv.CLASS_ILLOCUTIONARY,
               inv.CLASS_DEICTIC, inv.CLASS_LOGICAL}          # not part of a lexeme's identity
LEXICAL_MODS = {"NEGATE", "BEGIN", "END", "REPEAT", "DURATIVE", "PUNCTUAL"}   # grammatical classes, but part of lexemes

SCALAR_ADJ = {"NONE": "no", "SOME": "some", "ALL": "all", "LOW": "low", "MID": "moderate", "HIGH": "high",
              "EXTREME": "extreme", "BOUNDED": "limited", "UNBOUNDED": "unlimited", "INCREASE": "rising", "DECREASE": "falling"}
VALENCE_ADJ = {"GOOD": "good", "BAD": "bad", "REQUIRED": "required", "OPTIONAL": "optional", "SAFE": "safe",
               "HARM": "harmful", "COST": "costly", "BENEFIT": "beneficial"}
EPISTEMIC_ADV = {"KNOWN": "certainly", "BELIEVED": "probably", "INFERRED": "apparently", "UNKNOWN": "possibly",
                 "CONTESTED": "disputedly", "PREDICTED": "expectedly"}
MODAL_AUX = {"NECESSARY": "must", "POSSIBLE": "may", "PERMITTED": "may", "FORBIDDEN": "must not",
             "DESIRED": "should", "HYPOTHETICAL": "would"}
TEMPORAL_TAIL = {"REPEAT": "repeatedly", "BEGIN": "at first", "END": "in the end", "DURING": "meanwhile",
                 "BEFORE": "beforehand", "AFTER": "afterwards"}
AFFECT = {"JOY": "glad", "FEAR": "afraid", "ANGER": "angry", "TRUST": "confident", "SURPRISE": "surprised",
          "DISGUST": "disgusted", "SADNESS": "sad", "CALM": "calm"}
CAUSAL_VERB = {"CAUSE": "cause", "ENABLE": "enable", "PREVENT": "prevent", "CORRELATE": "correlate with",
               "DEPEND": "depend on", "TRIGGER": "trigger"}
RELATIONAL_VERB = {"EQUAL": "equal", "GREATER": "be greater than", "LESS": "be less than", "PART": "be part of",
                   "HAS": "have", "MEMBER": "be a kind of", "NEAR": "be near", "INSIDE": "be inside", "OUTSIDE": "be outside",
                   "ABOVE": "be above", "BELOW": "be below", "TOWARD": "head toward"}
ROLE_PREP = {"LOC": "in", "TIME": "at", "SOURCE": "from", "GOAL": "to", "PURPOSE": "for", "MANNER": "with",
             "SCOPE": "of", "ARG2": "to"}
IRREGULAR_PAST = {"go": "went", "get": "got", "see": "saw", "say": "said", "meet": "met", "know": "knew", "think": "thought",
                  "give": "gave", "write": "wrote", "rise": "rose", "fall": "fell", "run": "ran", "break": "broke", "send": "sent",
                  "tell": "told", "take": "took", "make": "made", "find": "found", "leave": "left", "bring": "brought",
                  "build": "built", "come": "came", "keep": "kept", "lose": "lost", "pay": "paid", "sell": "sold", "hold": "held",
                  "feel": "felt", "begin": "began", "grow": "grew", "win": "won", "sit": "sat", "stand": "stood", "speak": "spoke",
                  "drive": "drove", "fly": "flew", "eat": "ate", "drink": "drank", "sleep": "slept", "buy": "bought",
                  "catch": "caught", "teach": "taught", "fight": "fought", "lead": "led", "feed": "fed", "mean": "meant",
                  "spend": "spent", "be": "was", "have": "had", "do": "did", "put": "put", "read": "read", "cut": "cut",
                  "let": "let", "set": "set", "hit": "hit", "shut": "shut", "ship": "shipped", "stop": "stopped", "plan": "planned",
                  "drop": "dropped", "restart": "restarted", "fix": "fixed", "fail": "failed", "crash": "crashed", "need": "needed",
                  "want": "wanted", "suspect": "suspected", "trust": "trusted", "deploy": "deployed", "repair": "repaired",
                  "resolve": "resolved", "escalate": "escalated", "page": "paged", "notify": "notified", "confirm": "confirmed",
                  "verify": "verified", "ask": "asked", "request": "requested", "propose": "proposed", "suggest": "suggested",
                  "recommend": "recommended", "promise": "promised", "commit": "committed", "refuse": "refused", "decline": "declined",
                  "acknowledge": "acknowledged", "warn": "warned", "observe": "observed", "measure": "measured", "detect": "detected",
                  "predict": "predicted", "expect": "expected", "believe": "believed", "infer": "inferred", "dispute": "disputed",
                  "increase": "increased", "decrease": "decreased", "reduce": "reduced", "allow": "allowed", "permit": "permitted",
                  "forbid": "forbade", "block": "blocked", "work": "worked", "wait": "waited", "move": "moved", "receive": "received",
                  "join": "joined", "replace": "replaced", "cost": "cost", "harm": "harmed", "help": "helped", "affect": "affected",
                  "impact": "impacted", "die": "died", "live": "lived", "love": "loved", "hate": "hated", "open": "opened",
                  "close": "closed", "kill": "killed", "save": "saved", "try": "tried", "call": "called", "show": "showed",
                  "learn": "learned", "remember": "remembered", "decide": "decided", "agree": "agreed", "arrive": "arrived",
                  "return": "returned", "walk": "walked", "talk": "talked", "look": "looked", "watch": "watched", "hear": "heard",
                  "listen": "listened", "hope": "hoped", "fear": "feared", "doubt": "doubted", "wonder": "wondered", "roll": "rolled",
                  "start": "started", "end": "ended", "finish": "finished", "understand": "understood", "forget": "forgot",
                  "choose": "chose", "use": "used", "turn": "turned", "play": "played", "handle": "handled"}


# ---------------------------------------------------------------------------
# reverse lexicon
# ---------------------------------------------------------------------------

def _lexical_mods(c: Composition) -> set[str]:
    out = set()
    for m in c.modifiers:
        if isinstance(m, Pid):
            n = inv.name_of(m)
            if m.cls not in GRAMMATICAL or n in LEXICAL_MODS:
                out.add(n)
    return out


def _best(entries: dict[str, tuple[str, list[str]]], head: str, mods: set[str], generic: str) -> tuple[str, set[str]]:
    """The entry whose (head, baseline) best explains (head, mods).  Returns (word, mods it covered)."""
    best, best_score, covered = generic, 0.0, set()
    for idx, (word, (h, baseline)) in enumerate(entries.items()):
        if h != head:
            continue
        b = set(baseline)
        if not b <= mods:
            continue                                  # an entry must not claim modifiers the node lacks
        if not b:
            continue                                  # empty baselines never beat the generic word
        score = len(b) - idx * 1e-4                   # earlier (core-domain) entries win ties
        if score > best_score:
            best, best_score, covered = word, score, b
    return best, covered


_NOUNS = {k: v for k, v in T.HEAD_LEXICON.items() if k not in ("thing", "object", "person", "people", "way")}
_VERBS = dict(T.VERB_LEXICON)


def noun_for(c: Composition) -> tuple[str, set[str]]:
    head = inv.name_of(c.head)
    return _best(_NOUNS, head, _lexical_mods(c), GENERIC_NOUN[head])


def verb_for(c: Composition) -> tuple[str, set[str]]:
    head = inv.name_of(c.head)
    mods = _lexical_mods(c)
    names = _names(c)
    if "PAST" in names:                                # "roll(back)": PAST can be part of the lexeme
        w, cov = _best(_VERBS, head, mods | {"PAST"}, GENERIC_VERB[head])
        if "PAST" in cov:
            return w, cov
    return _best(_VERBS, head, mods, GENERIC_VERB[head])


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _names(c: Composition) -> set[str]:
    return {inv.name_of(x) for x in c.modifiers if isinstance(x, Pid)}


def _bound(value: Any, path: str) -> Any:
    if isinstance(value, dict) and "bind" in value:
        return value["bind"].get(path if path else ".")
    return None


def _sub(path: str, role: str) -> str:
    return f"{path}/{role}" if path else role


def _lit(lit: Any) -> str:
    if isinstance(lit, Ref):
        return "that"
    if isinstance(lit, dict):
        parts = []
        if "n" in lit:
            parts.append(f"{lit['n']:g}" if isinstance(lit["n"], float) else str(lit["n"]))
        if "u" in lit:
            parts.append(lit["u"])
        if "t" in lit:
            parts.append(lit["t"])
        return " ".join(parts)
    if isinstance(lit, (int, float)):
        return f"{lit:g}" if isinstance(lit, float) else str(lit)
    s = str(lit)
    if s.islower():
        return " ".join(w.upper() if len(w) <= 3 else w.capitalize() for w in s.split())
    return s


def _plural(n: str) -> str:
    if n.endswith(("s", "x", "ch", "sh")):
        return n + "es"
    if n.endswith("y") and n[-2:-1] not in "aeiou":
        return n[:-1] + "ies"
    return n + "s"


def _person(np: Composition | None) -> tuple[int, bool]:
    """(person, plural) of a subject NP."""
    if np is None or not isinstance(np, Composition):
        return 3, False
    m = _names(np)
    head = inv.name_of(np.head)
    if "SELF" in m:
        return 1, head == "GROUP"
    if "ADDRESSEE" in m:
        return 2, False
    return 3, False


def _conjugate(verb: str, tense: str, negate: bool, aux: str | None, person: int, plural: bool) -> str:
    base, *rest = verb.split(" ", 1)
    tail = (" " + rest[0]) if rest else ""
    if aux:
        return f"{aux}{' not' if negate and 'not' not in aux else ''} {base}{tail}"
    if base == "be":
        if tense == "PAST":
            form = "were" if plural or person == 2 else "was"
        elif tense == "FUTURE":
            form = "will be"
        else:
            form = "am" if person == 1 and not plural else "are" if plural or person == 2 else "is"
        return f"{form}{' not' if negate else ''}{tail}"
    if tense == "PAST":
        if negate:
            return f"did not {base}{tail}"
        return IRREGULAR_PAST.get(base, base + ("d" if base.endswith("e") else "ed")) + tail
    if tense == "FUTURE":
        return f"will{' not' if negate else ''} {base}{tail}"
    if negate:
        return f"{'do' if person != 3 or plural else 'does'} not {base}{tail}"
    if person == 3 and not plural:
        third = {"have": "has", "do": "does", "go": "goes"}.get(base)
        if third is None:
            third = base + ("es" if base.endswith(("s", "x", "ch", "sh", "o")) else "ies" if base.endswith("y") and base[-2] not in "aeiou" else "s")
        return third + tail
    return base + tail


# ---------------------------------------------------------------------------
# noun phrases
# ---------------------------------------------------------------------------

def np(c: Composition, value: Any = True, path: str = "", case: str = "subj") -> str:
    m = _names(c)
    head = inv.name_of(c.head)
    bound = _bound(value, path)

    # pronouns
    if "SELF" in m and bound is None:
        return ("we" if head == "GROUP" else "I") if case == "subj" else ("us" if head == "GROUP" else "me")
    if "ADDRESSEE" in m and bound is None:
        return "you"
    if head == "AGENT" and "NONE" in m:
        return "nobody"
    if head == "ENTITY" and "NONE" in m:
        return "nothing"
    if isinstance(bound, Ref):
        return "it" if case != "subj" else "it"

    # measured / numbered things: "12 servers", "4200 ms"
    number = None
    roles = dict(c.roles)
    mb = _bound(value, _sub(path, "MEASURE")) if ROLES["MEASURE"] in roles else None
    if isinstance(bound, (int, float, dict)) and not isinstance(bound, Ref):
        number = bound
    elif mb is not None and not isinstance(mb, str):
        number = mb

    noun, covered = noun_for(c)
    if head == "MOMENT" and isinstance(bound, str):
        return _lit(bound)
    if head == "MOMENT" and isinstance(bound, dict) and "t" in bound:
        return bound["t"]
    if number is not None and head in ("STATE", "QUANTITY") and not (_names(c) - {"NONE"}) and not c.roles or \
            (number is not None and head == "STATE" and set(dict(c.roles)) <= {ROLES["MEASURE"]} and not _names(c)):
        return _lit(number)

    adjs = []
    for x, adj in list(SCALAR_ADJ.items()) + list(VALENCE_ADJ.items()):
        if x in m and x not in covered and x not in ("NONE",):
            adjs.append(adj)
    if "NEGATE" in m and "NEGATE" not in covered:
        adjs.insert(0, "failed")
    if any(a in m for a in AFFECT) and path != "":
        adjs.append(next(AFFECT[a] for a in AFFECT if a in m))

    det = "the"
    for d, w in (("THIS", "this"), ("THAT", "that"), ("WHICH", "which"), ("SAME", "the same"), ("OTHER", "another"),
                 ("EACH", "every"), ("ANY", "any"), ("GENERIC", "any"), ("ALL", "all the")):
        if d in m:
            det = w
            break
    if number is not None:
        core = f"{_lit(number)} {noun if head in ('QUANTITY', 'MOMENT') and isinstance(number, dict) and 'u' in number else _plural(noun) if (isinstance(number, (int, float)) and number != 1) else noun}"
        if head == "QUANTITY" and isinstance(number, dict) and "u" in number:
            core = _lit(number)
        det = None
    elif isinstance(bound, str):
        name = _lit(bound)
        if head in ("ENTITY", "AGENT", "PLACE", "GROUP") and not adjs:
            core, det = name, None
        else:
            core = f"{name} {noun}"
    else:
        core = noun
    words = adjs + [core]
    phrase = " ".join(words)
    if det:
        phrase = f"{det} {phrase}"
    # relative clause (SCOPE filled by a clause) and other roles
    tails = []
    for code, node in c.roles:
        rn = ROLE_NAMES[code]
        if rn in ("ARG0", "ARG1", "MEASURE"):
            continue
        if rn == "SCOPE" and isinstance(node, Composition) and is_clause(node):
            tails.append("that " + clause(node, value, _sub(path, rn), drop_subject=True))
        elif rn == "CONDITION":
            tails.append("if " + clause(node, value, _sub(path, rn)) if isinstance(node, Composition) else "if " + node_text(node, value, _sub(path, rn)))
        else:
            tails.append(f"{ROLE_PREP.get(rn, rn.lower())} {node_text(node, value, _sub(path, rn), 'obj')}")
    return " ".join([phrase] + tails)


def node_text(n: Node, value: Any, path: str, case: str = "obj") -> str:
    if isinstance(n, Pid):
        return GENERIC_NOUN.get(inv.name_of(n), inv.name_of(n).lower()) if n.cls == inv.CLASS_ONTOLOGICAL else inv.name_of(n).lower()
    if isinstance(n, Composition):
        if is_clause(n):
            return clause(n, value, path)
        return np(n, value, path, case)
    return "that"


def is_clause(c: Composition) -> bool:
    roles = dict(c.roles)
    head = inv.name_of(c.head)
    if head == "RELATION":
        return True
    if head == "GROUP" and ({"OR", "AND", "XOR"} & _names(c)) and ROLES["ARG0"] in roles:
        return True
    return (ROLES["ARG0"] in roles or ROLES["ARG1"] in roles) and head in ("PROCESS", "EVENT", "STATE", "SIGN")


# ---------------------------------------------------------------------------
# clauses
# ---------------------------------------------------------------------------

def clause(c: Composition, value: Any = True, path: str = "", drop_subject: bool = False) -> str:
    m = _names(c)
    head = inv.name_of(c.head)
    roles = dict(c.roles)
    tense = "PAST" if "PAST" in m else "FUTURE" if "FUTURE" in m else "PRESENT"
    aux = next((MODAL_AUX[x] for x in MODAL_AUX if x in m), None)
    adv = next((EPISTEMIC_ADV[x] for x in EPISTEMIC_ADV if x in m), None)
    subj_node = roles.get(ROLES["ARG0"])
    obj_node = roles.get(ROLES["ARG1"])
    subj = None if drop_subject else (node_text(subj_node, value, _sub(path, "ARG0"), "subj") if subj_node is not None else None)
    obj = node_text(obj_node, value, _sub(path, "ARG1"), "obj") if obj_node is not None else None
    person, plural = _person(subj_node if isinstance(subj_node, Composition) else None)
    tails = []
    for code, node in c.roles:
        rn = ROLE_NAMES[code]
        if rn in ("ARG0", "ARG1"):
            continue
        if rn == "CONDITION":
            tails.append("if " + (clause(node, value, _sub(path, rn)) if isinstance(node, Composition) and is_clause(node) else node_text(node, value, _sub(path, rn))))
        elif rn == "MEASURE":
            if is_clause(c) and _bound(value, _sub(path, rn)) is not None:
                tails.append(_lit(_bound(value, _sub(path, rn))))
        else:
            prep = ROLE_PREP.get(rn, rn.lower())
            if rn == "TIME":
                b = _bound(value, _sub(path, rn))
                prep = "on" if isinstance(b, str) and ":" not in b and "-" not in b else "after" if "AFTER" in m else "at"
            tails.append(f"{prep} {node_text(node, value, _sub(path, rn), 'obj')}")
    lex_covered = (verb_for(c)[1] if is_clause(c) else noun_for(c)[1])
    for x, w in TEMPORAL_TAIL.items():
        if x in m and x not in lex_covered and not (x == "AFTER" and ROLES["TIME"] in roles):
            tails.append(w)
    if "NOW" in m:
        tails.append("now")

    negate = "NEGATE" in m
    if head == "RELATION":
        verb = next((CAUSAL_VERB[x] for x in CAUSAL_VERB if x in m), None) or next((RELATIONAL_VERB[x] for x in RELATIONAL_VERB if x in m), "relate to")
        vp = _conjugate(verb, tense, negate, aux, person, plural)
        core = " ".join(x for x in [subj or "it", adv, vp, obj or "something"] if x)
    elif head == "GROUP" and ({"OR", "AND", "XOR"} & m) and obj is not None:
        joiner = "or" if "OR" in m else "either … or" if "XOR" in m else "and"
        core = f"{subj or ''} {joiner} {obj}".strip()
    elif head == "AGENT" and any(a in m for a in AFFECT) and ("SELF" in m or "ADDRESSEE" in m):
        who = "I am" if "SELF" in m else "you are"
        core = f"{who} {next(AFFECT[a] for a in AFFECT if a in m)}" + (f" that {obj}" if obj else "")
    elif head == "SIGN" and "MEMBER" in m and isinstance(_bound(value, path), str):
        core = f"{'my' if 'SELF' in m else 'your' if 'ADDRESSEE' in m else 'the'} name is {_lit(_bound(value, path))}"
    elif is_clause(c) or ("REQUEST" in m and path == "" and head in ("PROCESS", "EVENT", "SIGN")):
        verb, covered = verb_for(c)
        lex_neg = negate and "NEGATE" in covered
        vp = _conjugate(verb, tense, negate and not lex_neg, aux, person, plural)
        if subj is None and (drop_subject or "REQUEST" in m or subj_node is None):
            # relative clause ("that restarts the service") or imperative ("restart the server")
            bare = verb if drop_subject is False else _conjugate(verb, tense, negate and not lex_neg, aux, 3, False)
            lead = "please " if ("REQUEST" in m and path == "") else ""
            core = " ".join(x for x in [lead + bare, obj] if x)
        else:
            core = " ".join(x for x in [subj, adv, vp, obj] if x)
        # residual adjectives that the verb did not cover
        extra = [SCALAR_ADJ[x] for x in SCALAR_ADJ if x in m and x not in covered and x not in ("NONE",)]
        extra += [VALENCE_ADJ[x] for x in VALENCE_ADJ if x in m and x not in covered and "NEGATE" not in covered]
        if extra and head == "STATE":
            core += " and is " + ", ".join(extra)
    else:
        # predicative: "<np> is <adjective>"
        noun, covered = noun_for(c)
        keep = lambda x: isinstance(x, Pid) and (x.cls not in (inv.CLASS_SCALAR, inv.CLASS_VALENCE, inv.CLASS_AFFECT, inv.CLASS_EPISTEMIC, inv.CLASS_MODAL)
                                                or inv.name_of(x) in covered or inv.name_of(x) in ("NONE", "NEGATE"))
        base = Composition(c.head, frozenset(x for x in c.modifiers if keep(x)),
                           tuple((k, v) for k, v in c.roles if k == ROLES["MEASURE"]))
        preds = [SCALAR_ADJ[x] for x in SCALAR_ADJ if x in m and x != "NONE" and x not in covered]
        preds += [VALENCE_ADJ[x] for x in VALENCE_ADJ if x in m and x not in covered]
        preds += [AFFECT[a] for a in AFFECT if a in m]
        preds += [{"NECESSARY": "necessary", "POSSIBLE": "possible", "PERMITTED": "permitted", "FORBIDDEN": "forbidden",
                   "DESIRED": "wanted", "HYPOTHETICAL": "hypothetical"}[x] for x in MODAL_AUX if x in m]
        if "KNOWN" in m:
            preds.append("certain")
        if "UNKNOWN" in m:
            preds.append("unknown")
        if not preds and covered & set(SCALAR_ADJ):
            preds = [SCALAR_ADJ[x] for x in SCALAR_ADJ if x in covered][:1]
        bound_here = _bound(value, path)
        if head in ("QUANTITY", "PROPERTY") and isinstance(bound_here, (int, float, dict)) and not isinstance(bound_here, Ref):
            # "the latency is 4200 ms": the measurement is the predicate
            subject_text = np(base, True, path, "subj")
            preds = [_lit(bound_here)] + preds
        else:
            subject_text = np(base, value, path, "subj")
        if preds:
            be = _conjugate("be", tense, negate and "NEGATE" not in covered and "NEGATE" not in _lexical_mods(base), None, *_person(base))
            core = f"{subject_text} {be} {' and '.join(preds)}"
        else:
            core = subject_text
    return " ".join([core] + tails)


# ---------------------------------------------------------------------------
# sentences
# ---------------------------------------------------------------------------

def realize(c: Composition, value: Any = True) -> str:
    m = _names(c)
    head = inv.name_of(c.head)
    roles = dict(c.roles)
    if head == "SIGN" and "ACKNOWLEDGE" in m:
        if ROLES["ARG1"] in roles:
            inner = realize(roles[ROLES["ARG1"]], _rebase(value, "ARG1"))
            if "BEGIN" in m and "ADDRESSEE" in m:
                return "Hello, " + inner[0].lower() + inner[1:]
            return inner
        if "ADDRESSEE" in m and "BEGIN" in m:
            return "Hello."
        if "ADDRESSEE" in m and "END" in m:
            return "Goodbye."
        if "BENEFIT" in m:
            return "Thank you."
        if "SADNESS" in m:
            return "Sorry."
        if "AFFIRM" in m:
            return "Yes."
        if "NEGATE" in m:
            return "No."
        return "Noted."
    body = clause(c, value, "")
    pre, post = "", ""
    if "QUERY" in m or "WHICH" in m:
        post = "?"
    if "WARN" in m and head != "SIGN":
        pre = "warning: "
    if "REFUSE" in m:
        pre = "no — "
    if "PROPOSE" in m and head != "SIGN":
        pre = "proposal: "
    s = (pre + body).strip()
    s = s[0].upper() + s[1:]
    s = s.replace(" ,", ",").replace("  ", " ")
    if not s.endswith((".", "?", "!")):
        s += post or "."
    elif post and s.endswith("."):
        s = s[:-1] + post
    return s


def _rebase(value: Any, prefix: str) -> Any:
    if not (isinstance(value, dict) and "bind" in value):
        return value
    out = {}
    for k, v in value["bind"].items():
        if k == prefix:
            out["."] = v
        elif k.startswith(prefix + "/"):
            out[k[len(prefix) + 1:]] = v
    return {"bind": out} if out else True
