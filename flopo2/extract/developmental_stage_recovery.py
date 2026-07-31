"""Developmental-stage context recovery (v3 fan-out, uniquely named module).

This is a *superset* recovery pass for `developmental_stage_context` residuals that the baseline
withheld because a developmental / age / maturity / specimen-state / transition word occurs
somewhere in the same semicolon clause.  The baseline flags at semicolon granularity, but the
downstream disjunction gate and the OWL model both scope at *comma-member* granularity, so many
withheld values sit in a clean comma member with a determinate bearer and no local stage cue.

Two attachment-safe promotion routes are implemented, both grounded in the OWL/PATO semantic
review (`owl-review/SEMANTIC_REVIEW.md`, `owl-review/pato_axes.tsv`) and the corpus review
(`corpus-review/CORPUS_REVIEW.md`):

* **P1 — stage-conditioned bearer quality.**  When an age/maturity cue (young / old / juvenile /
  mature, and *immature* only when it modifies rather than *is* the bearer) directly binds the
  value's own bearer inside the value's comma member, the stage is added as a conjunctive
  ``bearer_context_qualities`` PATO quality:
  ``has_part some (bearer and has_quality some VALUE and has_quality some STAGE)``.
  A temporal transition (``pubescent when young, glabrous when old``) is handled per member:
  each value keeps only *its own* stage, so the reasoner never sees the PATO-disjoint
  glabrous+pubescent conjunction on one bearer.

* **P2 — explicit PO developmental stage.**  Reproductive-phase cues such as ``at anthesis`` or
  ``in bud`` are temporal contexts on the phenotype, not PATO qualities of its bearer.  A direct,
  atomic, same-member attachment is retained in ``developmental_stage_contexts`` and compiled to
  the annotation model's ``present_during_developmental_stage`` OWL restriction.

* **R2 — plain value, stage provably out of scope.**  When the value's comma member has no
  conditioning cue of any kind, has a determinate bearer, is atomic-safe and disjunction-free,
  and the nearest conditioning cue is at least two comma members away (so it cannot scope over
  this value), the value is recovered *without* any stage as ``normalization_status =
  context_override``.

Specimen-state (``when dry`` / ``à l'état sec``), ambiguous reproductive-phase attachment,
transitions whose value member is itself conditioned, and every span without a determinate bearer
are **retained** with a precise residual sub-reason.  No FLOPO id is minted and the immutable input
is never overwritten.

The module reuses the audited primitives from :mod:`flopo2.extract.context_recovery` and
:mod:`flopo2.extract.baseline`; in particular it first defers to the fully regression-tested
``_local_context`` for P1 and only extends it for the ``à l'état jeune`` predicate and coordinated
predicate scoping that the baseline module does not yet recognise.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.extract.baseline import _clause_at
from flopo2.extract.context_recovery import (
    BearerMatch,
    ContextCue,
    DISJUNCTIVE_BRIDGE,
    STRUCTURAL_BRIDGE,
    TRANSITION,
    _assertion,
    _baseline_bearer,
    _candidate_atomic_safe,
    _comma_phrase,
    _lexical_bearer,
    _local_context,
)
from flopo2.verify.missing_bearers import _po_exact_forms, _po_forms

DEV_REASON = "developmental_stage_context"

# --- Age / maturity stage qualities that are safe to conjoin as a bearer context ----------------
# Grounded in owl-review/pato_axes.tsv.  ``immature`` is CONDITIONAL: safe only when it modifies
# the bearer, never when it *is* the bearer head noun (``immature fruit``); enforced below.
STAGE_PATO = {
    "young": "PATO_0000309",
    "old": "PATO_0000308",
    "juvenile": "PATO_0001190",
    "mature": "PATO_0001701",
    "immature": "PATO_0001501",
}

# Extended cue patterns (superset of context_recovery.CONTEXT_CUES) including the French
# ``à l'état jeune`` predicate the baseline module does not model.
_STAGE_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "young",
        re.compile(
            r"(?<!\w)(?:when\s+young|young(?:er|est)?|"
            r"[àa]\s+l['’]état\s+(?:de\s+)?jeune(?:sse)?|au\s+jeune\s+âge|dans\s+le\s+jeune\s+âge|"
            r"lorsqu(?:e|'|’)\s*jeune|jeunes?)(?!\w)",
            re.IGNORECASE,
        ),
        "adjectival_or_predicate",
    ),
    (
        "juvenile",
        re.compile(r"(?<!\w)(?:juvenile|juv[ée]nile)(?!\w)", re.IGNORECASE),
        "adjectival",
    ),
    (
        "immature",
        re.compile(r"(?<!\w)immature(?!\w)", re.IGNORECASE),
        "adjectival",
    ),
    (
        "mature",
        re.compile(
            r"(?<!\w)(?:at\s+maturity|when\s+mature|mature|fully\s+grown|"
            r"[àa]\s+maturit[ée]|au\s+stade\s+mature|[àa]\s+l['’]état\s+adulte)(?!\w)",
            re.IGNORECASE,
        ),
        "adjectival_or_predicate",
    ),
    (
        "old",
        re.compile(
            r"(?<!\w)(?:when\s+old|old(?:er|est)?|vieil(?:le|les)?|vieux|âg[ée](?:e?s?)?)(?!\w)",
            re.IGNORECASE,
        ),
        "adjectival_or_predicate",
    ),
)

# Reproductive/developmental process stages are PO classes and contextualize the phenotype as a
# whole.  They must never be folded into ``bearer_context_qualities``.  The patterns include the
# preposition so bare mentions (``flowering branches`` or ``anthesis completed``) cannot be
# mistaken for a temporal restriction.
PO_STAGE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (
        "anthesis",
        "PO_0007616",
        re.compile(
            r"(?<!\w)(?:at|during)\s+anthesis(?!\w)|"
            r"(?<!\w)(?:[àa]\s+l['’]|au\s+cours\s+de\s+l['’])anth[èe]se(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "flowering",
        "PO_0007016",
        re.compile(
            r"(?<!\w)(?:at|during)\s+flowering(?!\w)|(?<!\w)in\s+flower(?!\w)|"
            r"(?<!\w)(?:[àa]\s+la|pendant\s+la)\s+floraison(?!\w)|"
            r"(?<!\w)en\s+fleurs?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "fruiting",
        "PO_0025500",
        re.compile(
            r"(?<!\w)(?:at|during)\s+(?:the\s+)?fruiting(?:\s+stage)?(?!\w)|"
            r"(?<!\w)in\s+fruit(?!\w)|"
            r"(?<!\w)(?:[àa]\s+la|pendant\s+la)\s+fructification(?!\w)|"
            r"(?<!\w)en\s+fruits?(?!\w)",
            re.IGNORECASE,
        ),
    ),
    (
        "flower_bud",
        "PO_0007615",
        re.compile(r"(?<!\w)(?:in\s+bud|en\s+bouton)(?!\w)", re.IGNORECASE),
    ),
)

# Any conditioning cue that, if present in the value's own comma member, makes the value
# stage/state/phase/transition-conditioned and therefore ineligible for a *plain* R2 recovery.
CONDITIONING_CUE = re.compile(
    r"(?<!\w)(?:"
    r"young(?:er|est)?|old(?:er|est)?|juvenile|juv[ée]nile|immature|mature|"
    r"when\s+young|when\s+old|when\s+mature|at\s+maturity|fully\s+grown|"
    r"jeunes?|vieil(?:le|les)?|vieux|âg[ée](?:e?s?)?|adulte(?:s)?|m[ûu]r(?:e|es|s)?|"
    r"[àa]\s+maturit[ée]|au\s+stade|[àa]\s+l['’]état|"
    # specimen state (RESIDUAL per semantic review)
    r"when\s+dry|when\s+fresh|in\s+sicco|dry|drying|dried|frais|fra[îi]che?|sec|s[èe]che|"
    # reproductive / phenological phase (RESIDUAL per semantic review)
    r"in\s+(?:flower|fruit|bud)|flowering|fruiting|anthesis|en\s+(?:fleur|fruit|bouton)|"
    r"[àa]\s+l['’]anth[èe]se|[àa]\s+la\s+(?:floraison|fructification)|"
    # transitions
    r"later|eventually|becoming|becomes?|turning|turns?|first|at\s+length|then|"
    r"devenant|devient|puis|plus\s+tard|d['’]abord|finalement"
    r")(?!\w)",
    re.IGNORECASE,
)

# H3 (corpus review) + adversarial F2-D: a comparative / "as on young stems" construction where
# the stage word belongs to a compared structure, not the value's bearer.
COMPARATIVE_STAGE = re.compile(
    r"(?<!\w)(?:as\s+(?:on|in)|as\s+[\w'’-]+\s+as|comme\s+(?:sur|chez|dans)|"
    r"aussi\s+[\wÀ-ÖØ-öø-ÿ'’-]+\s+que|resembl(?:e|es|ing)|similar\s+to|"
    r"like|ressembl(?:e|ant)|appearing\s+with|accompany(?:ing)?)(?!\w)",
    re.IGNORECASE,
)

# Adversarial F1-E / F2-B: a caveat parenthetical carrying a stage word or an epistemic hedge that
# scopes the whole following description ("Fruit (immature) ... pubescent"; "Berries (seen only in
# immature stage) ... oblong seeds"; "(encore jeunes)").  ``_postposed_parenthetical_stage`` only
# looks *after* the value, so a pre-posed caveat is otherwise unguarded.
PREPOSED_PAREN_CAVEAT = re.compile(
    r"\([^)]*(?:immature|mature|young|old(?:er|est)?|juvenile|jeunes?|vieux|vieille|"
    r"âg[ée]e?s?|adulte|stade|maturit[ée]|seen\s+only|only\s+in|"
    r"encore\s+jeune|en\s+material|material)[^)]*\)",
    re.IGNORECASE,
)

# Adversarial F2-A: a clause whose leading comma member is headed by a bare stage cue elides that
# stage over every later member ("jeunes 4-mères, elliptiques, ...").
CLAUSE_LEADS_WITH_STAGE = re.compile(
    r"^\s*(?:(?:très|tres|very|assez|souvent|parfois)\s+){0,2}"
    r"(?:jeunes?|young(?:er|est)?|vieux|vieille(?:s)?|old(?:er|est)?|juvenile|"
    r"immature|mature|adulte(?:s)?)"
    r"(?:\s+[A-Za-zÀ-ÖØ-öø-ÿ'’.\d-]+){0,4}\s*[,)]",
    re.IGNORECASE,
)
HEADING_BEARER_METHODS = {
    "organ_heading",
    "reviewed_cross_comma_clause_head",
    "leaf_heading_scoped_rachis",
}

# A bare predicate stage member that would forward/back-scope onto an adjacent value member
# (F2 killer): e.g. ``when young,`` / ``à l'état jeune,`` / ``jeunes,`` occupying a whole member.
BARE_STAGE_MEMBER = re.compile(
    r"^\s*(?:[-–—(]\s*)?(?:(?:very|très|tres|when|lorsqu[e'’]|[àa]\s+l['’]état(?:\s+de)?|"
    r"au\s+stade|at)\s+)*"
    r"(?:young|old|juvenile|immature|mature|jeune|jeunes|vieux|vieille|vieilles|"
    r"âg[ée]e?s?|adulte|adultes|maturit[ée]|jeunesse)"
    r"\s*[)]?\s*$",
    re.IGNORECASE,
)


_REAL_DISJUNCTION = re.compile(r"(?<!\w)(?:or|ou)(?!\w)", re.IGNORECASE)


def _real_disjunction(text: str) -> bool:
    """A genuine ``or``/``ou`` disjunction, ignoring the hedge ``more or less`` / ``plus ou moins``."""

    cleaned = re.sub(r"\bmore\s+or\s+less\b|\bplus\s+ou\s+moins\b", "", text, flags=re.IGNORECASE)
    return bool(_REAL_DISJUNCTION.search(cleaned))


def _member_bounds(text: str, position: int) -> tuple[int, int]:
    phrase, left = _comma_phrase(text, position)
    return left, left + len(phrase)


def _preposed_paren_caveat(text: str, start: int) -> bool:
    """Return whether a stage/hedge caveat parenthetical precedes the value in its clause."""

    clause, clause_left = _clause_at(text, start)
    local = start - clause_left
    return any(
        m.end() <= local for m in PREPOSED_PAREN_CAVEAT.finditer(clause)
    )


def _clause_leads_with_stage(text: str, start: int) -> bool:
    clause, _left = _clause_at(text, start)
    return bool(CLAUSE_LEADS_WITH_STAGE.match(clause))


def _comma_members(text: str, clause_left: int, clause: str) -> list[tuple[int, int]]:
    """Return (start, end) absolute bounds of every comma member in a semicolon clause."""

    commas = [
        m.start()
        for m in re.finditer(",", clause)
        if not (
            m.start() > 0
            and m.end() < len(clause)
            and clause[m.start() - 1].isdigit()
            and clause[m.end()].isdigit()
        )
    ]
    bounds: list[tuple[int, int]] = []
    prev = 0
    for c in [*commas, len(clause)]:
        bounds.append((clause_left + prev, clause_left + c))
        prev = c + 1
    return bounds


def _member_index(bounds: list[tuple[int, int]], position: int) -> int:
    for i, (lo, hi) in enumerate(bounds):
        if lo <= position <= hi:
            return i
    return -1


def _bearer(record: dict, span: dict, po_forms, cand_forms) -> BearerMatch | None:
    return _lexical_bearer(record, span, po_forms, cand_forms) or _baseline_bearer(record, span)


def _bearer_without_stage_term(
    record: dict,
    span: dict,
    po_forms,
    cand_forms,
    cue_start: int,
    cue_end: int,
) -> BearerMatch | None:
    """Resolve the phenotype bearer without letting ``fruit``/``bud`` steal attachment.

    In ``sepals 12 mm wide in fruit``, ``fruit`` is the PO temporal-stage cue, not the structure
    whose width is asserted.  Masking only that cue preserves every character offset while making
    the ordinary audited bearer resolver select the real head (``sepals``).
    """

    text = str(record.get("text", ""))
    masked = {
        **record,
        "text": text[:cue_start] + (" " * (cue_end - cue_start)) + text[cue_end:],
    }
    return _bearer(masked, span, po_forms, cand_forms)


def _extended_predicate_stage(
    text: str,
    start: int,
    end: int,
    pato: str,
    bearer: BearerMatch,
) -> tuple[ContextCue, int, int] | None:
    """Recognise a postposed predicate stage the audited ``_local_context`` misses.

    Only the ``à l'état jeune`` / ``à l'état adulte`` / ``at maturity`` family plus a coordinated
    (`` et `` / `` and ``) bridge between the value and that predicate is admitted, and only when
    the predicate is inside the value's comma member and no structural boundary other than a pure
    coordination separates value and cue.
    """

    lo, hi = _member_bounds(text, start)
    member = text[lo:hi]
    if COMPARATIVE_STAGE.search(member):
        return None
    if DISJUNCTIVE_BRIDGE.search(member) or TRANSITION.search(member):
        return None
    if not _candidate_atomic_safe(text, start, end, pato):
        return None
    # Reject a contradictory / ambiguous member carrying more than one distinct stage
    # ("young leaves pubescent when mature"): the audited matcher rejects these and so must we.
    distinct = {
        STAGE_PATO[name]
        for name, pattern, _k in _STAGE_PATTERNS
        for _m in pattern.finditer(member)
    }
    if len(distinct) > 1:
        return None
    best: tuple[int, ContextCue, int, int] | None = None
    for name, pattern, _kind in _STAGE_PATTERNS:
        for m in pattern.finditer(member):
            cs, ce = lo + m.start(), lo + m.end()
            surface = text[cs:ce]
            # predicate must follow the value and be an explicit "state/maturity" construction
            if cs < end:
                continue
            if not re.match(
                r"^\s*(?:[àa]\s+l['’]état|[àa]\s+maturit[ée]|at\s+maturity|"
                r"when\s+(?:young|old|mature)|au\s+stade)",
                surface,
                re.IGNORECASE,
            ):
                continue
            between = text[end:cs]
            # Allow only whitespace, a single coordinated value, or degree words between the
            # value and the predicate; anything else (of/in/on/nested noun) breaks scope.
            if not re.fullmatch(
                r"\s*(?:(?:et|and|,|;|-|–|—)\s*)?"
                r"(?:(?:très|tres|un\s+peu|slightly|very|densely|densément|"
                r"luisant(?:e|es|s)?|shiny|brillant(?:e|es|s)?|"
                r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+)\s*){0,2}",
                between,
                re.IGNORECASE,
            ):
                continue
            if STRUCTURAL_BRIDGE.search(re.sub(r"\b(?:et|and)\b", " ", between, flags=re.I)):
                # a non-coordination structural word slipped in
                continue
            gap = cs - end
            cue = ContextCue(name, STAGE_PATO[name], "developmental", pattern)
            if best is None or gap < best[0]:
                best = (gap, cue, cs, ce)
    if best is None:
        return None
    # Adversarial F1-A: reject when the value's own bearer is a nested structure separated from
    # the value by a partitive/locative bridge (``rameaux jeunes à moelle blanche`` -> white is the
    # pith's, not the branch's).  Only applies to an explicit in-member bearer noun.
    if bearer.method not in HEADING_BEARER_METHODS:
        if bearer.end <= start:
            bridge = text[bearer.end:start]
        elif end <= bearer.start:
            bridge = text[end:bearer.start]
        else:
            bridge = ""
        if STRUCTURAL_BRIDGE.search(bridge):
            return None
    return best[1], best[2], best[3]


def _immature_is_bearer_head(text: str, cue_start: int, cue_end: int) -> bool:
    """``immature`` is unsafe when it directly heads the bearer NP (``immature fruit``)."""

    after = text[cue_end : cue_end + 32]
    return bool(re.match(r"^\s+[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", after))


def _p1_context(
    record: dict,
    span: dict,
    bearer: BearerMatch,
    text: str,
    start: int,
    end: int,
    pato: str,
) -> tuple[ContextCue, int, int] | None:
    """P1: an age/maturity stage that binds the value's own bearer inside its comma member."""

    # First defer to the fully audited baseline context matcher (inherits every regression guard).
    ctx = _local_context(text, start, end, pato, bearer)
    source = "baseline_local_context"
    if ctx is None:
        ctx = _extended_predicate_stage(text, start, end, pato, bearer)
        source = "extended_predicate_stage"
    if ctx is None:
        return None
    cue, cs, ce = ctx
    if cue.pato_id not in STAGE_PATO.values():
        # Only promote the age/maturity axis here; specimen-state etc. is residual.
        return None
    if cue.pato_id == STAGE_PATO["immature"] and _immature_is_bearer_head(text, cs, ce):
        return None
    # H3 guard: the stage must not sit in a comparative construction nor bind a different noun that
    # lies between it and the value's bearer.
    lo, hi = _member_bounds(text, start)
    if COMPARATIVE_STAGE.search(text[lo:hi]):
        return None
    # Adversarial F1-E: a pre-posed caveat parenthetical (e.g. ``Fruit (immature) ... pubescent``)
    # scopes the whole description; the audited matcher only guards post-posed parentheticals.
    if _preposed_paren_caveat(text, start):
        return None
    return cue, cs, ce, source  # type: ignore[return-value]


def _clause_has_disjunction(text: str, start: int) -> bool:
    clause, _left = _clause_at(text, start)
    return _real_disjunction(clause)


def _po_stage_context(
    text: str,
    start: int,
    end: int,
    pato: str,
) -> tuple[str, str, int, int] | None:
    """Return one directly attached PO stage cue in the value's comma member.

    A transition, disjunction, comparison, or intervening lexical material makes temporal scope
    underdetermined and is deliberately retained for review.  This precision-first route handles
    only expressions such as ``erect at anthesis`` and ``yellow in bud``.
    """

    lo, hi = _member_bounds(text, start)
    member = text[lo:hi]
    if (
        not _candidate_atomic_safe(text, start, end, pato)
        or _real_disjunction(member)
        or TRANSITION.search(member)
        or COMPARATIVE_STAGE.search(member)
        or PREPOSED_PAREN_CAVEAT.search(member)
    ):
        return None
    matches: list[tuple[int, int, str, str]] = []
    for name, stage_term, pattern in PO_STAGE_PATTERNS:
        for match in pattern.finditer(member):
            matches.append((lo + match.start(), lo + match.end(), name, stage_term))
    if len(matches) != 1:
        return None
    cue_start, cue_end, name, stage_term = matches[0]
    if cue_start >= end:
        bridge = text[end:cue_start]
    elif cue_end <= start:
        bridge = text[cue_end:start]
    else:
        return None
    if len(bridge) > 40 or not re.fullmatch(
        r"\s*(?:(?:usually|often|habituellement|généralement|generalement)\s+)?",
        bridge,
        re.IGNORECASE,
    ):
        return None
    return name, stage_term, cue_start, cue_end


def _r2_plain_ok(
    text: str,
    start: int,
    end: int,
    pato: str,
    bearer: BearerMatch,
) -> tuple[bool, str]:
    """R2: value's member is unconditioned and the nearest cue is >= 2 members away."""

    clause, clause_left = _clause_at(text, start)
    lo, hi = _member_bounds(text, start)
    member = text[lo:hi]
    if not _candidate_atomic_safe(text, start, end, pato):
        return False, "r2_not_atomic_safe"
    if DISJUNCTIVE_BRIDGE.search(member) or TRANSITION.search(member):
        return False, "r2_member_logic"
    if CONDITIONING_CUE.search(member):
        return False, "r2_member_conditioned"
    if COMPARATIVE_STAGE.search(member):
        return False, "r2_member_comparative"
    # Adversarial F1-E/F2-B: a stage/hedge caveat parenthetical earlier in the clause scopes this
    # value; a plain recovery would drop that stage.
    if _preposed_paren_caveat(text, start):
        return False, "r2_preposed_paren_caveat"
    # Adversarial F3-x: a transition clause has shifting stage scope; keep plain recovery out of it
    # (the transitioning property and its alternatives belong to the transition/disjunction leads).
    if TRANSITION.search(clause):
        return False, "r2_transition_clause"
    # A real disjunction anywhere in the clause means the value may be one alternative of an
    # enumerated ``A, B or C`` value list (``globuleux, cucumiformes, piriformes ou oblongs``); a
    # forward alternative is not caught by the bearer->value source-text check.  That is the
    # explicit-disjunction lead's domain, so keep the whole clause residual here.
    if _real_disjunction(clause):
        return False, "r2_disjunction_clause"
    # Adversarial F2-A: a clause led by a bare stage cue elides that stage over every later member,
    # so a bare continuation value (no own in-member bearer noun) inherits it.
    if _clause_leads_with_stage(text, start) and bearer.method in HEADING_BEARER_METHODS:
        return False, "r2_leading_stage_scope"
    bounds = _comma_members(text, clause_left, clause)
    vi = _member_index(bounds, start)
    if vi < 0:
        return False, "r2_no_member"
    nearest = 99
    for i, (mlo, mhi) in enumerate(bounds):
        if i == vi:
            continue
        if CONDITIONING_CUE.search(text[mlo:mhi]):
            nearest = min(nearest, abs(i - vi))
    if nearest >= 99:
        # No conditioning cue anywhere in the clause -> the baseline flag came from a cue outside
        # this comma clause (rare) or a cue our lexicon does not model; treat as unconditioned.
        return True, "r2_no_local_cue"
    if nearest >= 2:
        return True, "r2_cue_two_members_away"
    # nearest == 1: an immediately adjacent member carries a cue; hold for review unless that
    # member is plainly not a forward-scoping bare stage predicate.
    for i, (mlo, mhi) in enumerate(bounds):
        if abs(i - vi) == 1 and BARE_STAGE_MEMBER.match(text[mlo:mhi]):
            return False, "r2_adjacent_bare_stage_predicate"
    return False, "r2_adjacent_cue_review"


def recover_dev_record(
    record: dict,
    po_forms,
    cand_forms,
) -> tuple[dict, list[dict], list[dict]]:
    """Return (out_record, audit_rows, proposal_rows) adding P1/P2/R2 promotions to a copy."""

    out = dict(record)
    assertions = [dict(a) for a in record.get("assertions", []) or []]
    seen = {
        (
            a.get("po_id", ""),
            a.get("pato_id", ""),
            a.get("source_start"),
            a.get("source_end"),
            tuple(sorted(a.get("bearer_context_qualities", []) or [])),
            tuple(
                sorted(
                    str(context.get("stage_term", ""))
                    for context in (a.get("developmental_stage_contexts", []) or [])
                )
            ),
        )
        for a in assertions
    }
    retained: list[dict] = []
    audit: list[dict] = []
    proposals: list[dict] = []
    text = record.get("text", "")

    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != DEV_REASON:
            retained.append(span)
            continue
        start, end = int(span["start"]), int(span["end"])
        pato = str(span.get("candidate_pato_id", "") or "")
        p2 = _po_stage_context(text, start, end, pato)
        if p2 is not None:
            _stage_name, _stage_term, stage_start, stage_end = p2
            bearer = _bearer_without_stage_term(
                record, span, po_forms, cand_forms, stage_start, stage_end
            )
        else:
            bearer = _bearer(record, span, po_forms, cand_forms)
        disposition = "retained_no_bearer" if bearer is None else "retained"
        stage_pato = ""
        stage_po = ""
        method = ""
        assertion: dict | None = None

        if bearer is not None:
            if p2 is not None:
                stage_name, stage_term, cs, ce = p2
                candidate = _assertion(record, span, bearer, context=None)
                source_start = min(int(candidate["source_start"]), cs)
                source_end = max(int(candidate["source_end"]), ce)
                candidate.update(
                    {
                        "source_start": source_start,
                        "source_end": source_end,
                        "source_text": text[source_start:source_end],
                        "developmental_stage_contexts": [
                            {
                                "stage_term": stage_term,
                                "stage_text": text[cs:ce],
                                "start": cs,
                                "end": ce,
                                "temporal_relation": "present_during",
                            }
                        ],
                        "developmental_stage_operator": "atomic",
                        "normalization_status": "compositional",
                    }
                )
                candidate["mapping_provenance"].append(
                    f"developmental_stage:P2:{stage_name}:{stage_term}"
                )
                if _real_disjunction(candidate.get("source_text", "")):
                    disposition = "p2_source_text_disjunction"
                else:
                    assertion = candidate
                    disposition = "recovered_po_developmental_stage"
                    stage_po = stage_term
                    method = f"P2:{stage_name}:{bearer.method}"

            p1 = None if assertion is not None else _p1_context(
                record, span, bearer, text, start, end, pato
            )
            if p1 is not None and _clause_has_disjunction(text, start):
                # Keep a stage-conditioned value out of a disjunctive clause (disjunction lead).
                p1 = None
                disposition = "p1_disjunction_clause"
            if p1 is not None:
                cue, cs, ce, source = p1
                candidate = _assertion(record, span, bearer, context=(cue, cs, ce))
                # The stored evidence span must not entangle the value with a disjunction series
                # (the bearer may sit before an ``A or B`` shape list); that is the disjunction
                # lead's domain and would misrepresent an atomic value.
                if _real_disjunction(candidate.get("source_text", "")):
                    disposition = "p1_source_text_disjunction"
                else:
                    assertion = candidate
                    assertion["mapping_provenance"].append(f"dev_stage_route:P1:{source}")
                    disposition = "recovered_bearer_stage_quality"
                    stage_pato = cue.pato_id
                    method = f"P1:{source}:{bearer.method}"
            elif assertion is None:
                ok, why = _r2_plain_ok(text, start, end, pato, bearer)
                if ok:
                    candidate = _assertion(record, span, bearer, context=None)
                    if _real_disjunction(candidate.get("source_text", "")):
                        disposition = "r2_source_text_disjunction"
                    else:
                        assertion = candidate
                        assertion["mapping_provenance"].append(f"dev_stage_route:R2:{why}")
                        disposition = "recovered_plain_stage_out_of_scope"
                        method = f"R2:{why}:{bearer.method}"
                else:
                    disposition = why

        if assertion is not None:
            key = (
                assertion["po_id"],
                assertion["pato_id"],
                assertion["source_start"],
                assertion["source_end"],
                tuple(sorted(assertion.get("bearer_context_qualities", []) or [])),
                tuple(
                    sorted(
                        str(context.get("stage_term", ""))
                        for context in (assertion.get("developmental_stage_contexts", []) or [])
                    )
                ),
            )
            if key in seen:
                disposition = "duplicate_existing_assertion"
                assertion = None
            else:
                seen.add(key)
                assertions.append(assertion)
                proposals.append(
                    {
                        "source": record.get("source", ""),
                        "source_id": record.get("source_id", ""),
                        "source_segment_index": record.get("source_segment_index", 0),
                        "taxon": record.get("taxon", ""),
                        "span_start": start,
                        "span_end": end,
                        "surface_form": span.get("surface_form", ""),
                        "candidate_pato_id": pato,
                        "route": "P2" if stage_po else "P1" if stage_pato else "R2",
                        "assertion": assertion,
                    }
                )

        if not disposition.startswith("recovered"):
            retained.append(span)

        clause, _left = _clause_at(text, start)
        audit.append(
            {
                "source": record.get("source", ""),
                "source_id": record.get("source_id", ""),
                "source_segment_index": record.get("source_segment_index", 0),
                "taxon": record.get("taxon", ""),
                "organ": record.get("organ", ""),
                "language": record.get("language", ""),
                "surface_form": span.get("surface_form", ""),
                "candidate_pato_id": pato,
                "bearer_po_id": bearer.po_id if bearer else "",
                "bearer_method": bearer.method if bearer else "",
                "stage_pato": stage_pato,
                "stage_po": stage_po,
                "disposition": disposition,
                "method": method,
                "clause": re.sub(r"\s+", " ", clause).strip(),
            }
        )

    out["assertions"] = assertions
    out["unresolved_spans"] = retained
    out.pop("annotation_extension_iri", None)
    return out, audit, proposals


AUDIT_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "language",
    "surface_form",
    "candidate_pato_id",
    "bearer_po_id",
    "bearer_method",
    "stage_pato",
    "stage_po",
    "disposition",
    "method",
    "clause",
)


def recover_file(
    input_path: Path,
    recovered_path: Path,
    audit_path: Path,
    proposals_path: Path,
    accounting_path: Path,
    *,
    po_obo: Path = Path("ont/plant_ontology.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    reviewed_bearers: Path = Path("config/reviewed_local_bearers.tsv"),
) -> dict:
    paths = [Path(p).resolve() for p in (input_path, recovered_path, audit_path, proposals_path)]
    if len(set(paths)) != len(paths):
        raise ValueError("input, recovered, audit, and proposal paths must all be distinct")
    po_forms = _po_exact_forms(po_obo, reviewed_bearers)
    cand_forms = _po_forms(po_lexicon, reviewed_bearers)
    for p in (recovered_path, audit_path, proposals_path, accounting_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    disp = Counter()
    by_source = Counter()
    by_route = Counter()
    dev_spans = 0
    records_in = 0
    records_out = 0
    records_with_dev_span = 0
    with (
        Path(input_path).open(encoding="utf-8") as src,
        Path(recovered_path).open("w", encoding="utf-8") as rec_out,
        Path(audit_path).open("w", encoding="utf-8", newline="") as aud_out,
        Path(proposals_path).open("w", encoding="utf-8") as prop_out,
    ):
        writer = csv.DictWriter(aud_out, fieldnames=AUDIT_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for line in src:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            records_in += 1
            has_dev = any(
                s.get("reason") == DEV_REASON for s in record.get("unresolved_spans") or []
            )
            if not has_dev:
                rec_out.write(line + "\n")
                records_out += 1
                continue
            records_with_dev_span += 1
            out, audit, proposals = recover_dev_record(record, po_forms, cand_forms)
            rec_out.write(json.dumps(out, ensure_ascii=False) + "\n")
            records_out += 1
            for row in audit:
                writer.writerow(row)
                disp[row["disposition"]] += 1
                dev_spans += 1
                if row["disposition"].startswith("recovered"):
                    by_source[row["source"]] += 1
            for p in proposals:
                prop_out.write(json.dumps(p, ensure_ascii=False) + "\n")
                by_route[p["route"]] += 1

    promoted = sum(v for k, v in disp.items() if k.startswith("recovered"))
    remaining = dev_spans - promoted
    accounting = {
        "input": str(input_path),
        "dev_span_total_input": dev_spans,
        "records_input": records_in,
        "records_output": records_out,
        "records_with_dev_span": records_with_dev_span,
        "promoted_total": promoted,
        "remaining_total": remaining,
        "identity_ok": dev_spans == promoted + remaining,
        "promoted_by_route": dict(by_route),
        "promoted_by_source": dict(sorted(by_source.items())),
        "dispositions": dict(disp.most_common()),
        "recovered_jsonl": str(recovered_path),
        "audit_tsv": str(audit_path),
        "proposals_jsonl": str(proposals_path),
    }
    Path(accounting_path).write_text(
        json.dumps(accounting, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return accounting


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--recovered", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--accounting", type=Path, required=True)
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--reviewed-bearers", type=Path, default=Path("config/reviewed_local_bearers.tsv")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            recover_file(
                args.input,
                args.recovered,
                args.audit,
                args.proposals,
                args.accounting,
                po_obo=args.po_obo,
                po_lexicon=args.po_lexicon,
                reviewed_bearers=args.reviewed_bearers,
            ),
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
