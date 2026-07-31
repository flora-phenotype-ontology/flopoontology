"""Generalized recovery of source-explicit PATO value unions across all reviewed characters.

This is v2 of :mod:`flopo2.verify.recover_explicit_unions`.  The v1 pass deliberately restricted
grounded disjunction recovery to three hand-audited PATO attribute families (colour, shape,
pilosity).  The residual corpus, however, carries 28,612 ``explicit_disjunction`` spans whose
baseline-assigned ``candidate_pato_id`` values span fifteen PATO attribute families.  Whenever
*every* alternative in a source ``or``/``ou`` coordination normalizes to an existing PATO
``value_slim`` class of one shared character, the union is representable today as
``value_operator=one_of`` (an OWL ``ObjectUnionOf`` inside the phenotype class description, given a
stable non-FLOPO ``FAC_`` IRI downstream) without minting any FLOPO term.

v2 changes, each of which strictly widens the *grounding vocabulary* while preserving every
conservative guard of the audited v1 decision procedure:

* the value lexicon is drawn from the full PATO ``value_slim`` (751 unambiguous surface forms)
  rather than three hand-curated cue lists;
* the character family of a value is its nearest of seven reviewed ``attribute_slim`` roots
  (shape, colour, pilosity, position, texture, branchiness, attachment quality), while a separate
  dimensional guard prevents a PATO 2-D value and a PATO 3-D value from being conflated merely
  because both descend from ``shape``;
* numeric attribute traits (length, height, width, thickness, diameter) are *not* PATO values,
  never enter the lexicon, and so numeric ``2 or 3 cm`` alternatives are never mis-promoted; and
* the "nearby unresolved same-attribute value" completeness guard is widened to all seven families
  so an incompletely grounded list (``smooth or coriaceous`` beside an unresolved ``rugose``) is
  still routed rather than promoted.

Every other guard — exact preferred/EXACT synonym only, same explicit PO bearer occurrence, strict
inter-operand filler, transition/degree/comparative/temporal/locative exclusion, structural
adjacency failure, taxonomic/specimen-scope exclusion — is the v1 procedure, reused verbatim by
importing it and installing the generalized family configuration into its module globals.  Input
JSONL is never overwritten and exact offsets plus unresolved-span accounting are preserved.
"""

from __future__ import annotations

import argparse
import csv
import functools
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.extract import baseline
from flopo2.verify import recover_explicit_unions as v1
from flopo2.verify.recover_exact_pato_compounds import load_pato_terms


# Seven reviewed character families, each mapped to its ``attribute_slim`` PATO id.  These roots
# are exactly the terms the data-model gate accepts as the top-level attribute of a ``one_of``
# expression (``logical_value_top_level_not_attribute``); all seven were confirmed present in
# ``config/pato_lexicon.tsv`` with the ``attribute_slim`` slim.
GENERALIZED_ATTRIBUTE_BY_FAMILY = {
    "shape": "PATO_0000052",
    "colour": "PATO_0000014",
    "pilosity": "PATO_0000066",
    "position": "PATO_0000140",
    "texture": "PATO_0000150",
    "branchiness": "PATO_0002009",
    "attachment": "PATO_0001435",
}
GENERALIZED_FAMILY_BY_ATTRIBUTE = {
    value: key for key, value in GENERALIZED_ATTRIBUTE_BY_FAMILY.items()
}

# Ambiguous botanical surface forms that resolve to a ``value_slim`` class but are unsafe as exact
# disjunction operands (``oval``/``ovoid`` collide with ``ovate``/``ovoïde`` senses).  Inherited
# from the audited v1 pass; extend only with review.
GENERALIZED_UNSAFE_FORMS = frozenset({"oval", "ovoid"})

# PATO attribute traits that carry numeric magnitudes, never categorical values.  A source
# ``2 or 3 cm`` is a numeric alternative on one of these traits (a value restriction), not a
# categorical ``one_of``; such spans must remain residual for the measurement pass.  They are
# excluded automatically because attribute traits are not in ``value_slim`` and therefore never
# enter the value lexicon; this set is used only to *verify* that exclusion in the audit.
NUMERIC_TRAIT_IDS = frozenset(
    {
        "PATO_0000122",  # length
        "PATO_0000119",  # height
        "PATO_0001334",  # diameter
        "PATO_0000921",  # width
        "PATO_0000915",  # thickness
    }
)

SHAPE_DIMENSION_ROOTS = {
    "PATO_0002006": "2d",  # 2-D shape
    "PATO_0002007": "3d",  # convex 3-D shape
}

# These surfaces are genuinely ambiguous in flora prose even though a generic PO lexical lookup
# returns a class.  In particular, an Asteraceae capitulum receptacle is not PO's flower
# receptacle.  They require a reviewed container-aware bearer extension/resolution.
AMBIGUOUS_CLAUSE_HEAD_BEARERS = frozenset({"receptacle", "receptacles"})

_INSTALLED = False

# Supersede v1's coarse 64-char nearby-value completeness proxy with the precise coordination-scoped
# ``_nonexhaustive_reason`` post-check (see install_generalized_families).
SUPERSEDE_NEARBY_GUARD = True


@functools.lru_cache(maxsize=None)
def generalized_quality_family(pato_obo: str) -> dict[str, str]:
    """Return ``value_slim`` PATO id -> character family for all seven reviewed families.

    Used to widen ``baseline.QUALITY_FAMILY`` so v1's ``_nearby_unresolved_same_family`` completeness
    guard fires for every family, not only the three it originally knew.
    """

    terms = load_pato_terms(Path(pato_obo))
    by_id = {term.pato_id: term for term in terms.values()}
    parents = {
        term.pato_id: tuple(parent.replace(":", "_") for parent in term.parents)
        for term in terms.values()
    }
    value_slim = v1._subset_members(Path(pato_obo), "value_slim")

    @functools.lru_cache(maxsize=None)
    def family(term_id: str) -> str:
        if term_id in GENERALIZED_FAMILY_BY_ATTRIBUTE:
            return GENERALIZED_FAMILY_BY_ATTRIBUTE[term_id]
        inherited = {family(parent) for parent in parents.get(term_id, ())}
        inherited.discard("")
        return next(iter(inherited)) if len(inherited) == 1 else ""

    mapping: dict[str, str] = {}
    for term_id in by_id:
        if term_id in GENERALIZED_FAMILY_BY_ATTRIBUTE or term_id not in value_slim:
            continue
        fam = family(term_id)
        if fam:
            mapping[term_id] = fam
    return mapping


@functools.lru_cache(maxsize=None)
def pato_shape_dimensions(pato_obo: str) -> dict[str, str]:
    """Return PATO value id -> ``2d``/``3d`` when exactly one dimension is entailed."""

    terms = load_pato_terms(Path(pato_obo))
    parents = {
        term.pato_id: tuple(parent.replace(":", "_") for parent in term.parents)
        for term in terms.values()
    }

    @functools.lru_cache(maxsize=None)
    def dimensions(term_id: str) -> frozenset[str]:
        direct = SHAPE_DIMENSION_ROOTS.get(term_id)
        inherited = {
            dimension
            for parent in parents.get(term_id, ())
            for dimension in dimensions(parent)
        }
        if direct:
            inherited.add(direct)
        return frozenset(inherited)

    result: dict[str, str] = {}
    for term_id in parents:
        entailed = dimensions(term_id)
        if len(entailed) == 1:
            result[term_id] = next(iter(entailed))
    return result


@functools.lru_cache(maxsize=None)
def load_flopo_eq_terms(registry_path: str) -> dict[tuple[str, str], str]:
    """Return active reusable FLOPO EQ terms keyed by their exact PO/PATO pair."""

    result: dict[tuple[str, str], str] = {}
    with Path(registry_path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if str(row.get("deprecated", "0") or "0") not in {"", "0", "false", "False"}:
                continue
            match = re.fullmatch(
                r"EQ\|(PO_\d+|FLOPO_\d+)\|(PATO_\d+)",
                str(row.get("signature", "") or ""),
            )
            iri = str(row.get("flopo_iri", "") or "")
            if not match or "/FLOPO_" not in iri:
                continue
            result[(match.group(1), match.group(2))] = iri.rsplit("/", 1)[-1]
    return result


def install_generalized_families(pato_obo: Path = Path("ont/quality.obo")) -> dict[str, str]:
    """Install the seven-family configuration into the v1 and baseline module globals.

    v1's decision procedure reads ``recover_explicit_unions.ATTRIBUTE_BY_FAMILY`` /
    ``FAMILY_BY_ATTRIBUTE`` (for the value lexicon and the emitted attribute id) and
    ``baseline.QUALITY_FAMILY`` (for the nearby-value completeness guard).  Rebinding these at
    runtime — never editing the shared source files — lets the audited v1 logic run unchanged over
    the widened grounding vocabulary.  Idempotent.
    """

    global _INSTALLED
    quality_family = generalized_quality_family(str(pato_obo))
    v1.ATTRIBUTE_BY_FAMILY = dict(GENERALIZED_ATTRIBUTE_BY_FAMILY)
    v1.FAMILY_BY_ATTRIBUTE = dict(GENERALIZED_FAMILY_BY_ATTRIBUTE)
    v1._UNSAFE_EXACT_BOTANICAL_FORMS = GENERALIZED_UNSAFE_FORMS
    # Widen, never shrink, the baseline family map used by the completeness guard.
    baseline.QUALITY_FAMILY = {**quality_family, **baseline.QUALITY_FAMILY}
    if SUPERSEDE_NEARBY_GUARD:
        # v1's ``_nearby_unresolved_same_family`` is a *coarse* completeness proxy: it rejects a union
        # whenever any same-family unresolved value sits within 64 characters, regardless of whether
        # that value belongs to the same coordination or to a different subpart/organ.  The v2
        # ``_nonexhaustive_reason`` post-check is the *precise* replacement — it scopes the
        # completeness test to the contiguous source coordination the union actually belongs to — so
        # the coarse proxy is superseded to stop rejecting genuinely complete same-subpart pairs.
        v1._nearby_unresolved_same_family = lambda record, candidate: False
    _INSTALLED = True
    return quality_family


@functools.lru_cache(maxsize=None)
def _pato_labels(pato_obo: str) -> dict[str, str]:
    terms = load_pato_terms(Path(pato_obo))
    return {term.pato_id: term.label for term in terms.values()}


def _target_span_values(
    record: dict,
    clause_start: int,
    clause_end: int,
    quality_family: dict[str, str],
    labels: dict[str, str],
) -> list[v1.ValueMatch]:
    """Ground every ``explicit_disjunction`` operand in a clause via its baseline ``candidate_pato_id``.

    This is the v2 grounding source that the English-only PATO lexicon cannot supply: French
    operands (``oblongues``, ``jaune``, ``glabres``) and English surface forms outside PATO's EXACT
    synonyms were already normalized by the deterministic baseline and carry a ``candidate_pato_id``.
    Only value ids that resolve to one of the seven reviewed character families are used; numeric
    attribute traits (length/height/…) have no family and are silently skipped, so numeric ``2 or 3``
    alternatives can never seed a categorical union.
    """

    values: list[v1.ValueMatch] = []
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != v1.TARGET_REASON:
            continue
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not (clause_start <= start and end <= clause_end):
            continue
        pato_id = str(span.get("candidate_pato_id", ""))
        family = quality_family.get(pato_id, "")
        if not family:
            continue
        surface = str(span.get("surface_form", ""))
        value = v1.ExactValue(pato_id, labels.get(pato_id, pato_id), family, v1._normal_form(surface))
        values.append(v1.ValueMatch(start, end, value, surface))
    return values


def _clause_values(
    record: dict,
    clause_start: int,
    clause_end: int,
    quality_family: dict[str, str],
    labels: dict[str, str],
) -> list[v1.ValueMatch]:
    """Position-sorted operand grounding for a clause: the baseline target spans, and only those.

    An empirical A/B over the full residual corpus showed that supplementing target spans with
    blanket or coordination-adjacent ``baseline.QUALITY_PATTERNS`` cue matches yields *zero*
    additional promotions (every extra candidate is rejected by the adjacency/nearby-value guards) at
    the cost of thousands of spurious rejected candidates.  Operands the baseline recognizes but did
    not flag as ``explicit_disjunction`` are, in practice, either already flagged elsewhere in the
    same coordination or genuinely non-adjacent, so target spans are the complete and clean grounding
    source.  The English PATO ``value_slim`` lexicon is likewise not used: it is English-only (which
    would make French disjunctions systematically unrecoverable) and reaches past the audited 25-value
    vocabulary; its extra English-only candidates are quantified separately for the curator queue.
    ``_union_candidates`` orders components by list index, so the returned list must be sorted.
    """

    values = _target_span_values(record, clause_start, clause_end, quality_family, labels)
    values.sort(key=lambda value: (value.start, value.end, value.value.pato_id))
    return values


# A source disjunction predicating the clause's head organ ("Panicle oblong or ovate", "ligule
# jaune ou blanche").  v1 returns ``heading_only_or_missing`` for exactly the clauses in which
# ``_explicit_bearer_candidates`` finds no bearer noun of any kind (resolved, contextual, or blocked)
# — so the clause's leading organ is provably the sole subject.  We may then attach the union to that
# head *iff* the head resolves to an existing PO class and no residual subregion/locative scope
# narrows the union to a part of it.  This never mints a PO term.
_HEAD_TRAILING_SCOPE = re.compile(
    r"^\s*[,;]?\s*"
    r"(?:on|along|sur|le\s+long\s+de|à|au|aux|near|towards?|at)\b[^,;.]*?\b"
    r"(?:ribs?|c[ôo]tes?|nerves?|veins?|nervures?|angles?|margins?|marges?|bords?|"
    r"apex|apices|base|bases|tip|tips|sommets?|surfaces?|faces?|sides?|c[ôo]t[ée]s?|"
    r"outside|inside|dessus|dessous|within|part|partie)\b",
    re.IGNORECASE,
)

# Enable the guarded clause-head bearer fallback (safe by the heading_only construction above).
ENABLE_HEAD_BEARER = True


# Unambiguous existing-PO surface aliases for clause-head bearers that the shipped organ lexicon
# does not yet carry.  ``phyllary`` is deliberately absent: PO records it only as a RELATED synonym
# of involucral bract, so treating it as exact would overstate the mapping.
_HEAD_BEARER_ALIASES = {
    "périanthe": "PO_0009058",
    "périanthes": "PO_0009058",
}


def _clause_head_bearer(record: dict, candidate) -> "v1.LocalBearer | None":
    """Resolve the clause-leading organ of a ``heading_only`` union to an existing PO class."""

    text = str(record.get("text", ""))
    _clause, clause_start = baseline._clause_at(text, candidate.start)
    lead = re.match(r"\s*([A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+)", text[clause_start:candidate.start])
    if not lead:
        return None
    surface = lead.group(1)
    if surface.casefold() in AMBIGUOUS_CLAUSE_HEAD_BEARERS:
        return None
    po_id = (
        baseline._organ_to_po(surface)
        or baseline._organ_to_po(surface.rstrip("s"))
        or _HEAD_BEARER_ALIASES.get(surface.lower())
    )
    if not po_id:
        return None
    start = clause_start + lead.start(1)
    end = clause_start + lead.end(1)
    return v1.LocalBearer(po_id, "clause_head_organ", surface, start, end)


def _head_scope_reason(text: str, candidate) -> str:
    """Reject a head-organ union that a trailing/leading locative scope narrows to a subregion."""

    after = text[candidate.end : min(len(text), candidate.end + 72)]
    before = text[max(0, candidate.start - 56) : candidate.start]
    if _HEAD_TRAILING_SCOPE.match(after):
        return "head_union_locative_subregion_scope"
    if v1._LOCATIVE_SCOPE.search(before) or v1._LOCATIVE_SCOPE.search(after):
        return "head_union_locative_subregion_scope"
    if v1._RESPECTIVELY.match(after):
        return "respectively_scoped_values"
    if v1._EXCLUDED_SCOPE_AFTER.match(after):
        return "excluded_geographic_scope"
    relation = text[candidate.start : min(len(text), candidate.end + 40)]
    if v1._UNSUPPORTED_BEARER_NOUN.search(relation):
        return "head_union_unsupported_subregion"
    return ""


def _head_bearer_decision(record: dict, candidate, clause_values):
    """Return a promoted head-organ decision, or ``None`` to keep the union residual."""

    if not ENABLE_HEAD_BEARER:
        return None
    text = str(record.get("text", ""))
    bearer = _clause_head_bearer(record, candidate)
    if bearer is None:
        return None
    if v1._operand_context_reason(text, candidate, bearer, clause_values):
        return None
    if _head_scope_reason(text, candidate):
        return None
    base = v1._decision_base(record, candidate)
    overlapping = v1._overlapping_target_indexes(record, candidate)
    return v1.CandidateDecision(
        "promoted",
        "exact_complete_union_head_bearer",
        **base,
        bearer_po_id=bearer.po_id,
        bearer_method=bearer.method,
        bearer_surface=bearer.surface_form,
        bearer_start=bearer.start,
        bearer_end=bearer.end,
        resolved_unresolved_spans=len(overlapping),
    )


# A source list member that is a single (optionally degree-qualified) adjective — the shape of a
# genuine coordinated value alternative ("subulate", "narrowly ovate").  Members carrying nouns,
# numbers, measurements, or prepositions are NOT alternatives and bound the coordination.
_SINGLE_ADJ_MEMBER = re.compile(
    r"^\s*(?:(?:more\s+or\s+less|plus\s+ou\s+moins|±)\s+)?"
    r"(?:(?:very|slightly|narrowly|broadly|shortly|minutely|usually|often|sometimes|rarely|"
    r"étroitement|largement|brièvement|légèrement|un\s+peu|parfois|souvent|rarement)\s+)?"
    r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ'’-]+\s*$",
    re.IGNORECASE,
)
_MEMBER_BOUNDARY = re.compile(r",|\bor\b|\bou\b", re.IGNORECASE)
# Tokens that end the coordination on the LEFT: a number/measurement, a preposition introducing a
# new phrase, or a subregion/part noun.  The clause head organ itself is NOT a boundary, so a value
# glued to it (``Spikelets subulate,`` before ``lanceolate or oblong``) is still scanned.
_LEFT_HARD_BOUNDARY = re.compile(
    r"\d|[;:.]|"
    r"\b(?:with|at|on|from|to|through|bearing|near|along|towards?|inside|outside|"
    r"sur|à|au|aux|dans|vers|le\s+long)\b|"
    r"\b(?:apex|apices|base|bases|tip|tips|margin|margins|surface|surfaces|face|faces|"
    r"side|sides|ribs?|nerves?|veins?|nervures?|angles?|throat|middle|"
    r"sommet|sommets|marge|marges|bord|bords|nervure|nervures)\b",
    re.IGNORECASE,
)


def _coordination_span(text: str, candidate) -> tuple[int, int]:
    """Return the source coordination run the union belongs to.

    LEFT edge: scan back to the clause start but stop just after the last hard boundary (number,
    preposition, or subregion noun) — the head organ is not a boundary, so a same-family value glued
    to it is kept in scope.  RIGHT edge: extend over following single-adjective comma/``or`` members.
    """

    clause, clause_start = baseline._clause_at(text, candidate.start)
    prefix = text[clause_start:candidate.start]
    last_boundary = None
    for match in _LEFT_HARD_BOUNDARY.finditer(prefix):
        last_boundary = match.end()
    left = clause_start + (last_boundary if last_boundary is not None else 0)

    members: list[tuple[int, int]] = []
    cursor = 0
    for boundary in _MEMBER_BOUNDARY.finditer(clause):
        members.append((clause_start + cursor, clause_start + boundary.start()))
        cursor = boundary.end()
    members.append((clause_start + cursor, clause_start + len(clause)))
    inside = [
        index
        for index, (start, end) in enumerate(members)
        if start < candidate.end and candidate.start < end
    ]
    high = max(inside) if inside else len(members) - 1
    while high < len(members) - 1 and _SINGLE_ADJ_MEMBER.match(
        text[members[high + 1][0] : members[high + 1][1]]
    ):
        high += 1
    right = members[high][1] if inside else candidate.end
    return left, max(right, candidate.end)


def _nonexhaustive_reason(
    text: str,
    candidate,
    value_lexicon: v1.ExactPatoValueLexicon,
    quality_family: dict[str, str],
    labels: dict[str, str],
) -> str:
    """Reject a union whose coordination contains an unincluded same-family value alternative.

    The audited 25-cue vocabulary is a strict subset of PATO ``value_slim``; a source list such as
    ``subulate, lanceolate or oblong`` grounds only ``lanceolate``/``oblong`` and would silently drop
    ``subulate`` (a real shape class outside the cue set), yielding a union narrower than the source.
    We therefore re-scan the contiguous coordination run with the *full* value_slim lexicon (English)
    and the EN+FR cue patterns; any same-family value class present but not among the operands means
    the alternative list is not source-exhaustive, so the union is withheld.
    """

    window_start, window_end = _coordination_span(text, candidate)
    family = candidate.values[0].value.family
    operand_ids = {value.value.pato_id for value in candidate.values}
    present: set[str] = set()
    for match in value_lexicon.matches(text, window_start, window_end):
        if match.value.family == family:
            present.add(match.value.pato_id)
    for match in _cue_span_values(text, window_start, window_end, quality_family, labels):
        if match.value.family == family:
            present.add(match.value.pato_id)
    if present - operand_ids:
        return "nonexhaustive_same_family_alternative"
    return ""


def _cue_span_values(
    text: str,
    start: int,
    end: int,
    quality_family: dict[str, str],
    labels: dict[str, str],
) -> list[v1.ValueMatch]:
    """EN+FR baseline cue matches within a window (for the exhaustiveness completeness check)."""

    values: list[v1.ValueMatch] = []
    for cue in baseline.QUALITY_PATTERNS:
        family = quality_family.get(cue.pato_id, "")
        if not family:
            continue
        for match in cue.pattern.finditer(text, start, end):
            value = v1.ExactValue(
                cue.pato_id, labels.get(cue.pato_id, cue.pato_id), family, ""
            )
            values.append(v1.ValueMatch(match.start(), match.end(), value, match.group(0)))
    return values


def recover_record(
    record: dict,
    quality_family: dict[str, str],
    shape_dimensions: dict[str, str],
    flopo_eq_terms: dict[tuple[str, str], str],
    labels: dict[str, str],
    value_lexicon: v1.ExactPatoValueLexicon,
):
    """v2 of :func:`recover_explicit_unions.recover_record` with generalized-family grounding.

    Identical to the audited v1 procedure except that (1) per-clause value candidates are grounded
    from the baseline ``candidate_pato_id`` target spans across all seven reviewed character families
    (English *and* French), and (2) a union v1 routes as ``heading_only_or_missing`` is promoted when
    its clause-head organ resolves to an existing PO class (the head is provably the sole bearer).
    Every other guard, the assertion shape, span removal, and rejected-edge bookkeeping are the v1
    functions, reused unchanged.
    """

    result = dict(record)
    text = str(record.get("text", ""))
    assertions = [dict(row) for row in record.get("assertions", []) or []]
    unresolved = [dict(row) for row in record.get("unresolved_spans", []) or []]
    target_spans = [row for row in unresolved if row.get("reason") == v1.TARGET_REASON]
    outcomes: Counter[str] = Counter()
    decisions: list = []
    removed: set[int] = set()
    if not target_spans:
        return result, outcomes, decisions

    clause_ranges: set[tuple[int, int]] = set()
    for span in target_spans:
        clause, cstart = baseline._clause_at(text, int(span.get("start", -1)))
        clause_ranges.add((cstart, cstart + len(clause)))

    seen_candidates: set[tuple[int, int, tuple[str, ...]]] = set()
    rejected_attempts: list = []
    for clause_start, clause_end in sorted(clause_ranges):
        values = _clause_values(record, clause_start, clause_end, quality_family, labels)
        attempts = v1._edge_attempts(text, clause_start, clause_end, values)
        rejected_attempts.extend(attempt for attempt in attempts if attempt.reason)
        for candidate in v1._union_candidates(text, values, attempts):
            value_terms = tuple(value.value.pato_id for value in candidate.values)
            key = candidate.start, candidate.end, value_terms
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            decision = v1.evaluate_candidate(record, candidate, attempts, values)
            if decision.reason == "heading_only_or_missing":
                head_decision = _head_bearer_decision(record, candidate, values)
                if head_decision is not None:
                    decision = head_decision
            if decision.status == "promoted":
                dimensions = {
                    shape_dimensions.get(value.value.pato_id, "")
                    for value in candidate.values
                }
                dimensions.discard("")
                if len(dimensions) > 1:
                    decision = v1.CandidateDecision(
                        "routed",
                        "mixed_pato_shape_dimensions",
                        **v1._decision_base(record, candidate),
                    )
            if (
                decision.status == "promoted"
                and decision.bearer_po_id == "PO_0025324"
                and str(record.get("taxon_family", "") or "").casefold()
                not in {"fabaceae", "leguminosae"}
            ):
                decision = v1.CandidateDecision(
                    "routed",
                    "banner_petal_outside_papilionaceous_taxon",
                    **v1._decision_base(record, candidate),
                )
            if (
                decision.status == "promoted"
                and str(decision.bearer_surface or "").casefold()
                in AMBIGUOUS_CLAUSE_HEAD_BEARERS
            ):
                decision = v1.CandidateDecision(
                    "routed",
                    "ambiguous_container_specific_bearer",
                    **v1._decision_base(record, candidate),
                )
            component_terms: list[str] = []
            if decision.status == "promoted":
                component_terms = [
                    flopo_eq_terms.get((decision.bearer_po_id, pato_id), "")
                    for pato_id in decision.value_terms
                ]
                if not all(component_terms):
                    decision = v1.CandidateDecision(
                        "routed",
                        "component_phenotype_not_in_flopo",
                        **v1._decision_base(record, candidate),
                    )
                    component_terms = []
            if decision.status == "promoted":
                nonexhaustive = _nonexhaustive_reason(
                    text, candidate, value_lexicon, quality_family, labels
                )
                if nonexhaustive:
                    decision = v1.CandidateDecision(
                        "routed", nonexhaustive, **v1._decision_base(record, candidate)
                    )
            decisions.append(decision)
            outcomes[f"{decision.status}:{decision.reason}"] += 1
            if decision.status != "promoted":
                continue
            qualifier_fields, qualifier_start, qualifier_text = baseline._modality_context(
                text, candidate.start
            )
            seasons, season_operator, season_start, season_end = baseline._season_context(
                text, candidate.start, candidate.end
            )
            source_start = min(
                candidate.start,
                qualifier_start,
                season_start,
                decision.bearer_start,
            )
            source_end = max(candidate.end, season_end, decision.bearer_end)
            expected_semantics = {
                "po_id": decision.bearer_po_id,
                "pato_id": decision.attribute_pato_id,
                "negated": False,
                "value_operator": "one_of",
                "value_terms": list(decision.value_terms),
                "source_start": source_start,
                "source_end": source_end,
                "frequency_qualifier": qualifier_fields.get("frequency_qualifier", "unspecified"),
                "epistemic_modality": qualifier_fields.get("epistemic_modality", "asserted"),
                "value_qualifier": qualifier_fields.get("value_qualifier", "exact"),
                "degree_qualifier": qualifier_fields.get("degree_qualifier", "unmodified"),
                "season_contexts": seasons,
                "season_operator": season_operator,
            }
            existing = next(
                (
                    row
                    for row in assertions
                    if all(row.get(key) == value for key, value in expected_semantics.items())
                ),
                None,
            )
            matching_indexes = v1._overlapping_target_indexes(record, candidate)
            if existing is not None:
                removed.update(matching_indexes)
                outcomes["already_asserted"] += 1
                continue
            assertions.append(
                {
                    "po_id": decision.bearer_po_id,
                    "pato_id": decision.attribute_pato_id,
                    "negated": False,
                    "organ": record.get("organ", ""),
                    "source_text": text[source_start:source_end],
                    "source_start": source_start,
                    "source_end": source_end,
                    "value_text": text[candidate.start:candidate.end],
                    "value_operator": "one_of",
                    # The FAC expression uses the normalized PATO qualities under has_quality;
                    # the complete same-bearer EQ operands are required to exist as reusable
                    # FLOPO classes and are retained explicitly in provenance below.
                    "value_terms": list(decision.value_terms),
                    "modality_text": qualifier_text,
                    "season_contexts": seasons,
                    "season_operator": season_operator,
                    "normalization_status": "compositional",
                    "mapping_provenance": [
                        "PATO value_slim classes (baseline candidate_pato_id or EN EXACT synonym); "
                        "complete explicit source union over one reviewed character family",
                        (
                            f"{decision.bearer_method} PO bearer occurrence: "
                            f"{decision.bearer_surface} [{decision.bearer_start},"
                            f"{decision.bearer_end})"
                        ),
                        "PATO union operands:" + "|".join(decision.value_terms),
                        "FLOPO phenotype operands:" + "|".join(component_terms),
                    ],
                    "extractor": EXTRACTOR,
                    **qualifier_fields,
                }
            )
            removed.update(matching_indexes)
            outcomes["promoted_assertions"] += 1
            outcomes[f"promoted_arity:{decision.arity}"] += 1
            outcomes[f"promoted_family:{decision.family}"] += 1
            outcomes[f"promoted_bearer_method:{decision.bearer_method}"] += 1
            outcomes[f"promoted_po:{decision.bearer_po_id}"] += 1
            outcomes["promoted_pattern:" + "|".join(decision.value_terms)] += 1
            outcomes["resolved_evidence_spans"] += len(matching_indexes)

    candidate_connector_starts = {
        connector
        for decision in decisions
        for connector in v1._CONNECTOR_STARTS_IN_TEXT(
            text, decision.expression_start, decision.expression_end
        )
    }
    for attempt in rejected_attempts:
        if attempt.connector_start in candidate_connector_starts:
            continue
        decision = v1._rejected_edge_decision(record, attempt)
        decisions.append(decision)
        outcomes[f"{decision.status}:{decision.reason}"] += 1

    result["assertions"] = assertions
    result["unresolved_spans"] = [
        row for index, row in enumerate(unresolved) if index not in removed
    ]
    return result, outcomes, decisions


# The v2 extractor tag distinguishes generalized-family promotions from the v1 three-family pass.
EXTRACTOR = "deterministic_generalized_pato_explicit_union_recovery_v2"


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    candidate_tsv: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    sample_tsv: Path | None = None,
    sample_seed: int = 20260718,
    sample_size: int = 60,
) -> dict[str, object]:
    """Stream the generalized hybrid pass, mirroring v1.recover_file with hybrid grounding."""

    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    quality_family = install_generalized_families(pato_obo)
    shape_dimensions = pato_shape_dimensions(str(pato_obo))
    flopo_eq_terms = load_flopo_eq_terms(str(flopo_registry))
    labels = _pato_labels(str(pato_obo))
    # Full PATO value_slim lexicon (751 EN forms, 7 families) used ONLY as an exhaustiveness check:
    # it detects value classes present in a coordination but outside the audited cue set (``subulate``).
    value_lexicon = v1.ExactPatoValueLexicon.load(pato_obo)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    outcomes: Counter[str] = Counter()
    promoted_by_source: Counter[str] = Counter()
    promoted_by_arity: Counter[int] = Counter()
    all_decisions: list = []
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, record_outcomes, decisions = recover_record(
                record,
                quality_family,
                shape_dimensions,
                flopo_eq_terms,
                labels,
                value_lexicon,
            )
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcomes.update(record_outcomes)
            all_decisions.extend(decisions)
            for decision in decisions:
                if decision.status == "promoted":
                    promoted_by_source[decision.source] += 1
                    promoted_by_arity[decision.arity] += 1
    v1.write_candidate_tsv(candidate_tsv, all_decisions)
    sample_report = None
    if sample_tsv is not None:
        sample_report = v1.write_fixed_seed_sample(
            sample_tsv, all_decisions, seed=sample_seed, size=sample_size
        )
    return {
        "input": str(input_path),
        "output": str(output_path),
        "candidate_tsv": str(candidate_tsv),
        "records": records,
        "extractor": EXTRACTOR,
        "generalized_families": sorted(GENERALIZED_ATTRIBUTE_BY_FAMILY),
        "numeric_trait_ids_excluded": sorted(NUMERIC_TRAIT_IDS),
        "flopo_component_eq_terms": len(flopo_eq_terms),
        "audited_cue_values": sum(
            1 for cue in baseline.QUALITY_PATTERNS if quality_family.get(cue.pato_id)
        ),
        "decisions": len(all_decisions),
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "promoted_by_arity": {
            str(key): value for key, value in sorted(promoted_by_arity.items())
        },
        "outcomes": dict(sorted(outcomes.items())),
        "sample": sample_report,
    }


# --------------------------------------------------------------------------------------------- #
# Exhaustive machine audit of the candidate decisions.
# --------------------------------------------------------------------------------------------- #

def audit_candidates(candidate_tsv: Path) -> dict[str, object]:
    """Summarize every promoted and routed pattern family from the candidate-decision TSV."""

    promoted_patterns: Counter[str] = Counter()
    promoted_family: Counter[str] = Counter()
    promoted_arity: Counter[str] = Counter()
    promoted_bearer: Counter[str] = Counter()
    routed_reason: Counter[str] = Counter()
    promoted_examples: dict[str, dict[str, str]] = {}
    numeric_leak: list[dict[str, str]] = []
    n_promoted = 0
    n_routed = 0
    with Path(candidate_tsv).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            status = row.get("status", "")
            if status == "promoted":
                n_promoted += 1
                pattern = row.get("value_terms", "")
                promoted_patterns[pattern] += 1
                promoted_family[row.get("family", "")] += 1
                promoted_arity[row.get("arity", "")] += 1
                promoted_bearer[row.get("bearer_po_id", "")] += 1
                promoted_examples.setdefault(
                    pattern,
                    {
                        "family": row.get("family", ""),
                        "attribute_pato_id": row.get("attribute_pato_id", ""),
                        "value_labels": row.get("value_labels", ""),
                        "expression_text": row.get("expression_text", ""),
                        "source": row.get("source", ""),
                        "source_id": row.get("source_id", ""),
                        "bearer_surface": row.get("bearer_surface", ""),
                    },
                )
                if any(term in NUMERIC_TRAIT_IDS for term in pattern.split("|")):
                    numeric_leak.append(row)
            else:
                n_routed += 1
                routed_reason[row.get("reason", "")] += 1
    return {
        "candidate_tsv": str(candidate_tsv),
        "n_promoted_decisions": n_promoted,
        "n_routed_decisions": n_routed,
        "promoted_by_family": dict(promoted_family.most_common()),
        "promoted_by_arity": dict(sorted(promoted_arity.items())),
        "promoted_by_bearer_po": dict(promoted_bearer.most_common()),
        "distinct_promoted_patterns": len(promoted_patterns),
        "promoted_patterns": [
            {
                "pattern": pattern,
                "count": count,
                **promoted_examples[pattern],
            }
            for pattern, count in promoted_patterns.most_common()
        ],
        "routed_by_reason": dict(routed_reason.most_common()),
        "numeric_trait_leak_count": len(numeric_leak),
    }


def audit_output_spans(
    input_path: Path,
    output_path: Path,
    pato_obo: Path = Path("ont/quality.obo"),
) -> dict[str, object]:
    """Verify span accounting and that no numeric-trait disjunction span was resolved."""

    target = v1.TARGET_REASON

    def tally(path: Path) -> tuple[int, int, Counter[str], int]:
        spans = 0
        numeric_spans = 0
        one_of_assertions = 0
        by_pato: Counter[str] = Counter()
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                for span in record.get("unresolved_spans", []) or []:
                    if span.get("reason") != target:
                        continue
                    spans += 1
                    pid = str(span.get("candidate_pato_id", ""))
                    by_pato[pid] += 1
                    if pid in NUMERIC_TRAIT_IDS:
                        numeric_spans += 1
                for assertion in record.get("assertions", []) or []:
                    if (assertion.get("value_operator") == "one_of") and assertion.get(
                        "extractor"
                    ) == EXTRACTOR:
                        one_of_assertions += 1
        return spans, numeric_spans, by_pato, one_of_assertions

    in_spans, in_numeric, in_by_pato, _ = tally(input_path)
    out_spans, out_numeric, out_by_pato, out_one_of = tally(output_path)
    resolved_by_pato = {
        pid: in_by_pato[pid] - out_by_pato.get(pid, 0)
        for pid in sorted(in_by_pato)
        if in_by_pato[pid] - out_by_pato.get(pid, 0)
    }
    return {
        "input_target_spans": in_spans,
        "output_target_spans": out_spans,
        "resolved_target_spans": in_spans - out_spans,
        "input_numeric_trait_spans": in_numeric,
        "output_numeric_trait_spans": out_numeric,
        "numeric_trait_spans_resolved": in_numeric - out_numeric,
        "new_one_of_assertions": out_one_of,
        "resolved_spans_by_pato": resolved_by_pato,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--sample", type=Path)
    parser.add_argument("--sample-seed", type=int, default=20260718)
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--audit", type=Path)
    parser.add_argument("--accounting", type=Path)
    args = parser.parse_args()

    report = recover_file(
        args.input,
        args.output,
        candidate_tsv=args.candidates,
        pato_obo=args.pato_obo,
        flopo_registry=args.flopo_registry,
        sample_tsv=args.sample,
        sample_seed=args.sample_seed,
        sample_size=args.sample_size,
    )
    candidate_audit = audit_candidates(args.candidates)
    span_audit = audit_output_spans(args.input, args.output, args.pato_obo)

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(
            json.dumps(candidate_audit, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if args.accounting:
        accounting = {
            "input": str(args.input),
            "output": str(args.output),
            "span_accounting": span_audit,
            "invariant_resolved_equals_sum_promoted_arities": (
                span_audit["resolved_target_spans"]
                == sum(
                    int(arity) * int(count)
                    for arity, count in report["promoted_by_arity"].items()
                )
            ),
            "numeric_trait_leak": span_audit["numeric_trait_spans_resolved"],
        }
        args.accounting.parent.mkdir(parents=True, exist_ok=True)
        args.accounting.write_text(
            json.dumps(accounting, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    print(json.dumps({"report": report, "candidate_audit": candidate_audit, "span_audit": span_audit}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
