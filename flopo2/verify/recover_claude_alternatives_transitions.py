"""Deterministically recover source-bound qualitative continua and temporal transitions.

The baseline withholds values joined by ``to``/``à`` (``ovate to lanceolate``, ``glabre à
pubescent``) and by transition verbs (``green becoming red``, ``vert devenant rouge``) under
``unsupported_alternative_or_transition``, ``same_attribute_composite_or_transition`` and
``unsupported_same_attribute_neighbor``.  ``recover_residual_logic`` already promotes the
``or``/``and`` constructions of those reasons as FAC unions/intersections; the remaining residue is
dominated by range and transition constructions that are *not* finite unions.

ANNOTATION_MODEL section 3 represents them as a ``qualitative_value_relation``: a non-FAC record
with one controlled interpretation (``continuum`` for ``X to Y``, ``temporal_transition`` for
``X becoming Y``), two source-ordered grounded endpoints, exact connector evidence, and the
common PATO attribute at the top level.  This pass emits such records only when every piece of the
construction is verbatim, exactly grounded, and unambiguously attached:

* both endpoints are closed baseline cues or PATO preferred/EXACT labels of one reviewed attribute
  family (colour, shape, pilosity), distinct, and whole lexical tokens;
* the connector is the only text between them, apart from an optional closed degree cue directly
  before an endpoint (E2: ``narrowly elliptic to broadly ovate``, ``sparsely pubescent to
  glabrous``) that is kept as that endpoint's ``from_operand``/``to_operand`` qualifier; neither
  endpoint is chained to another range or logical connector, or followed by free text (a nested
  noun, locative, stage);
* the bearer is the same explicit local PO occurrence for both endpoints, passing the reviewed
  nested-bearer, subregion, locative and relational safeguards of the explicit-union pass (or a
  mapped organ heading when the construction opens the segment and the clause names no bearer);
* the clause carries no negation, comparison, uncertainty, developmental-stage or specimen-state
  cue (apart from the transition verb itself), and no existing assertion overlaps the relation;
* the bearer/attribute pair is ``allowed`` and every identifier is live in the catalogs; and
* every unresolved span inside the relation is a target-reason span on one of the endpoints.

Anything else stays unresolved.  The module never mints identifiers and never edits the corpus in
place: it writes a delta (one line per touched segment) that :func:`apply_delta` can replay.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from flopo2.annotation.operands import make_operand, parse_qualifier_cue
from flopo2.annotation.provenance import stable_statement_id
from flopo2.extract import baseline
from flopo2.extract.compose import _clause_around
from flopo2.extract.leaflet_context import LEAFLET_PART_BY_LEAF_PART, leaflet_bearer
from flopo2.verify import gates
from flopo2.verify.data_model import _has_real_disjunction
from flopo2.verify.recover_exact_pato_compounds import (
    _RELATIONAL_FLOWER_CATEGORY_BEFORE,
    BearerResolver,
)
from flopo2.verify.recover_explicit_unions import (
    ATTRIBUTE_BY_FAMILY,
    ExactPatoValueLexicon,
    ExactValue,
    LocalBearer,
    UnionCandidate,
    ValueMatch,
    _BEARER_SUBREGION_MODIFIER,
    _BEARER_SUBSET_MODIFIER,
    _LOCATIVE_SCOPE,
    _RELATIONAL_OBJECT_BEFORE_BEARER,
    _RESPECTIVELY,
    _STRICT_FILLER,
    _UNCERTAINTY,
    _UNSUPPORTED_BEARER_NOUN,
    _local_value_context_reason,
    _resolve_explicit_bearer,
)


EXTRACTOR = "deterministic_claude_alternatives_transitions_v1"
TARGET_REASONS = frozenset(
    {
        "unsupported_alternative_or_transition",
        "same_attribute_composite_or_transition",
        "unsupported_same_attribute_neighbor",
        "negated_context",
    }
)
HOLD_REASON = "qualitative_relation_pending_dual_family_review"
_DASHES = "-–—"
_CONTINUUM = re.compile(r"\s+(?P<connector>to|à)\s+", re.IGNORECASE)
_TRANSITION = re.compile(
    r"\s*,?\s*(?P<connector>becoming|turning|devenant)\s+",
    re.IGNORECASE,
)
_CHAIN_BEFORE = re.compile(
    rf"(?:\b(?:to|or|and|à|ou|et|through|becoming|turning|devenant|from|de|nor|ni)"
    rf"\s*[(\[]?\s*|[{_DASHES}/]\s*|\(\s*)$",
    re.IGNORECASE,
)
_CHAIN_AFTER = re.compile(
    rf"^\s*(?:[)\]]\s*)?(?:\b(?:to|or|and|à|ou|et|through|becoming|turning|devenant|then|puis)\b|"
    rf"[{_DASHES}/(])",
    re.IGNORECASE,
)
_UNCERTAIN = re.compile(r"[?]|\b(?:possibly|perhaps|probably|peut[- ][êe]tre)\b", re.IGNORECASE)
_SPECIMEN_STATE = re.compile(
    r"\b(?:dry|dried|drying|fresh|living|alive|herbarium|in\s+sicco|in\s+vivo|sec|s[èe]che?s?|"
    r"frais|fra[îi]che?s?|vivant(?:e|es|s)?|séchage|sechage|l['’]état)\b",
    re.IGNORECASE,
)
_TRANSITION_TRIGGER = re.compile(r"\b(?:becoming|devenant)\b", re.IGNORECASE)

# Closed French equivalents of PATO preferred labels or EXACT synonyms that the closed baseline
# cue list does not cover.  Each form is grounded through the *English* exact form in the PATO
# value lexicon, so it inherits exactly that identifier and attribute family.  Ambiguous French
# forms (``ovale``, ``ovoïde``, ``aigu``, ``arrondi``) are deliberately absent.
FRENCH_EXACT_FORMS = [
    (re.compile(pattern, re.IGNORECASE), english)
    for pattern, english in (
        (r"(?<!\w)(?:obovales?|obov[ée](?:e?s?))(?!\w)", "obovate"),
        (r"(?<!\w)orbiculaires?(?!\w)", "orbicular"),
        (r"(?<!\w)oblanc[ée]ol[ée](?:e?s?)(?!\w)", "oblanceolate"),
        (r"(?<!\w)cun[ée]{2}(?:e?s?)(?!\w)", "cuneate"),
        (r"(?<!\w)tronqu[ée](?:e?s?)(?!\w)", "truncated"),
        (r"(?<!\w)spatul[ée](?:e?s?)(?!\w)", "spatulate"),
        (r"(?<!\w)triangulaires?(?!\w)", "triangular"),
        (r"(?<!\w)r[ée]niformes?(?!\w)", "reniform"),
        (r"(?<!\w)(?:cord[ée](?:e?s?)|cordiformes?)(?!\w)", "cordate"),
        (r"(?<!\w)ov[ée](?:e?s?)(?!\w)", "ovate"),
        (r"(?<!\w)ellipso[ïi]des?(?!\w)", "ellipsoid"),
        (r"(?<!\w)sph[ée]riques?(?!\w)", "spherical"),
        (r"(?<!\w)falciformes?(?!\w)", "falcate"),
        (r"(?<!\w)sagitt[ée](?:e?s?)(?!\w)", "sagittate"),
        (r"(?<!\w)oranges?(?!\w)", "orange"),
        (r"(?<!\w)roses?(?!\w)", "pink"),
        (r"(?<!\w)violet(?:te)?s?(?!\w)", "violet"),
        (r"(?<!\w)pourpres?(?!\w)", "purple"),
        (r"(?<!\w)gris(?:e|es)?(?!\w)", "grey"),
        (r"(?<!\w)bleu(?:e|es|s)?(?!\w)", "blue"),
        (r"(?<!\w)cr[èe]mes?(?!\w)", "cream"),
        (r"(?<!\w)velu(?:e|es|s)?(?!\w)", "hairy"),
        (r"(?<!\w)velout[ée](?:e?s?)(?!\w)", "velutinous"),
    )
]
# Apex/base terminal shapes.  PATO base-shape values (cuneate, truncated, cordate, sagittate)
# describe a base, and a leaf described as ``obtuse to acuminate`` is described by its apex, so
# these endpoints need an apex/base bearer that the closed resolver does not provide.
TERMINAL_SHAPES = frozenset(
    {"PATO_0002228", "PATO_0001935", "PATO_0001982", "PATO_0002091", "PATO_0000389"}
)
BASE_SHAPES = frozenset({"PATO_0001955", "PATO_0000936", "PATO_0000948", "PATO_0001881"})
# Dense coverings mask the surface: a colour range directly after one (``pubescent velouté, gris à
# brun``; ``soyeuses, blanches à grises``) describes the indumentum, not the organ.  Sparse or
# qualified hairs (``sparsely hairy, yellow to orange``) leave the organ colour visible.
_DENSE_INDUMENT_BEFORE = re.compile(
    r"\b(?:velout[ée]\w*|velutin\w*|tomente\w*|tomentos\w*|tomentell\w*|soyeu\w*|silky|"
    r"seric\w*|lanat\w*|laineu\w*|woolly|villos\w*|velvety)\s*,?\s*$",
    re.IGNORECASE,
)
LEAFLET_PART_IDS = frozenset(LEAFLET_PART_BY_LEAF_PART.values())
LEAF_LIKE_BEARERS = frozenset(
    {"PO_0009025", "PO_0020039", "PO_0025060", "PO_0020049", "PO_0000013"}
)
_STAGE_PHRASE_BEFORE_BEARER = re.compile(
    r"\b(?:in|en|at|during|after|before|when|lors\s+de|apr[èe]s|avant)\s+$", re.IGNORECASE
)
_OF_BEFORE_BEARER = re.compile(
    r"\b(?:of|de|des|du|d['’])\s*(?:the\s+|an?\s+|la\s+|le\s+|les\s+|l['’])?$",
    re.IGNORECASE,
)
_COMPARED_TAXON = re.compile(
    r"\b(?:voisin(?:e|es|s)?\s+d[ue']|proche\s+d[ue']|diff[èe]r(?:e|ent)\s+d[ue']|"
    r"close\s+to|near\s+to|allied\s+to|related\s+to|differs?\s+from|distinguished\s+from|"
    r"resembl(?:e|es|ing)|similar\s+to|cf\.)",
    re.IGNORECASE,
)
_EXTRA_SUBSET_BEFORE_BEARER = re.compile(
    r"\b(?:dorsal|ventral|lateral|laterals|median|fruiting|flowering|fertile|sterile|"
    r"juvenile|young|old|mature|older|younger|fructif[èe]res?|aerial|submerged|floating|"
    r"cauline|radical|rosette|central|marginal|peripheral|ray|disc|disk)\s+$",
    re.IGNORECASE,
)
_CLAUSE_TEMPORAL = re.compile(
    r"\b(?:turning|becoming|with\s+age|ageing|aging|en\s+vieillissant|devenant|"
    r"when\s+old|later|fad(?:e|es|ed|ing)|blacken(?:s|ing)?|redden(?:s|ing)?|"
    r"p[âa]lissant(?:e|es|s)?|noircissant(?:e|es|s)?|rougissant(?:e|es|s)?)\b",
    re.IGNORECASE,
)
_POSTPOSED_SUBSET_AFTER_BEARER = re.compile(
    r"^\s+(?:[\wÀ-ÖØ-öø-ÿ'’-]+\s+)?(?:m[ée]dian(?:e|es|s)?|internes?|externes?|"
    r"inf[ée]rieur(?:e|es|s)?|sup[ée]rieur(?:e|es|s)?|lat[ée]ra(?:l|le|les|ux)|"
    r"dorsa(?:l|le|les|ux)|ventra(?:l|le|les|ux)|basa(?:l|le|les|ux)|termina(?:l|le|les|ux)|"
    r"a[ée]rien(?:ne|nes|s)?|submerg[ée](?:e?s?)|fructif[èe]res?|st[ée]riles?|fertiles?|"
    r"m[âa]les?|femelles?|jeunes?|[âa]g[ée](?:e?s?))\b",
    re.IGNORECASE,
)
_HTML_ENTITY = re.compile(r"&#?\w+;")
_WITH_BEFORE_BEARER = re.compile(
    r"\b(?:with|avec)\s+(?:[^\s,;:.]+\s+){0,6}$", re.IGNORECASE
)
_BRANCH_SURFACE = re.compile(r"^(?:branch(?:es)?|rameaux|rameau|ramifications?)$", re.IGNORECASE)
_INFLORESCENCE_BEFORE = re.compile(
    r"\b(?:panicles?|inflorescences?|racemes?|cymes?|thyrses?|corymbs?|panicules?|grappes?|"
    r"cymes?)\b(?:[^.]|\.(?=\s*[a-z0-9]))*$",
    re.IGNORECASE,
)
_NESTED_ATTRIBUTIVE_PART = re.compile(
    r"\b(?:à\s+[^\W\d_]+\s+(?:de|d['’])\s|with\s+(?:an?\s+)?[^\W\d_]+\s+[\d(])",
    re.IGNORECASE,
)
_FRENCH_FAMILY = {
    "obovate": "shape", "orbicular": "shape", "oblanceolate": "shape", "cuneate": "shape",
    "truncated": "shape", "spatulate": "shape", "triangular": "shape", "reniform": "shape",
    "cordate": "shape", "ovate": "shape", "ellipsoid": "shape", "spherical": "shape",
    "falcate": "shape", "sagittate": "shape", "orange": "colour", "pink": "colour",
    "violet": "colour", "purple": "colour", "grey": "colour", "blue": "colour",
    "cream": "colour", "hairy": "pilosity", "velutinous": "pilosity",
}
_FRENCH_TERMINAL_OR_BASE = frozenset({"cuneate", "truncated", "cordate", "sagittate"})
_BLADE_SURFACE = re.compile(r"^(?:blades?|limbes?|lamina|laminae)$", re.IGNORECASE)
_FLORAL_CONTEXT = re.compile(
    r"\b(?:corol(?:la|las|le|les)|calyx|calyces|calices?|p[ée]tales?|petals?|sepals?|"
    r"s[ée]pales?|flowers?|fleurs?|perianths?|p[ée]rianthes?|tubes?|labell(?:um|e)|lips?|"
    r"l[èe]vres?|tepals?|t[ée]pales?)\b",
    re.IGNORECASE,
)


# Closed per-endpoint degree cues (schema extension E2).  An optional intensity word may precede
# the axis degree (``very sparsely``); the whole cue is the endpoint's verbatim qualifier and the
# endpoint text starts at the cue.  Outline shapes take width degrees only, pilosity takes density,
# texture, extent and intensity degrees; colour takes none (``pale``/``dark`` are hue terms).
_INTENSITY_PREFIX = r"(?:(?:very|rather|très|tres|assez)\s+)?"
ENDPOINT_DEGREE_CUES = {
    "shape": re.compile(
        _INTENSITY_PREFIX + r"(?:narrowly|broadly|widely|étroitement|etroitement|largement)",
        re.IGNORECASE,
    ),
    "pilosity": re.compile(
        r"(?:un\s+peu|"
        + _INTENSITY_PREFIX
        + r"(?:densely|sparsely|sparingly|finely|minutely|shortly|slightly|densément|densement|"
        r"éparsement|eparsement|finement|brièvement|brievement|courtement|légèrement|"
        r"legerement|peu))",
        re.IGNORECASE,
    ),
}


def _degree_cue_before(text: str, position: int, family: str) -> tuple[int, int] | None:
    """Span of a closed degree cue that ends one space before ``position`` (a whole word)."""

    pattern = ENDPOINT_DEGREE_CUES.get(family)
    if pattern is None:
        return None
    window_start = max(0, position - 40)
    best: tuple[int, int] | None = None
    for match in pattern.finditer(text, window_start, position):
        if not re.fullmatch(r"\s+", text[match.end() : position]):
            continue
        if match.start() > 0 and (text[match.start() - 1].isalnum() or text[match.start() - 1] in "-‐–"):
            continue
        if best is None or match.start() < best[0]:
            best = (match.start(), match.end())
    return best


def _with_cue(value: ValueMatch, cue: tuple[int, int] | None) -> ValueMatch:
    return value if cue is None else replace(value, start=cue[0])


@dataclass(frozen=True)
class Relation:
    interpretation: str
    left: ValueMatch
    right: ValueMatch
    connector_start: int
    connector_end: int
    left_cue: tuple[int, int] | None = None
    right_cue: tuple[int, int] | None = None

    @property
    def family(self) -> str:
        return self.left.value.family

    @property
    def start(self) -> int:
        return self.left.start

    @property
    def end(self) -> int:
        return self.right.end


@dataclass(frozen=True)
class Outcome:
    status: str
    reason: str
    relation: Relation | None = None
    bearer: LocalBearer | None = None
    bearer_method: str = ""
    targets: tuple[int, ...] = ()


# ---------------------------------------------------------------------------------------------
# Catalogs


def _load_tsv_ids(path: Path) -> tuple[set[str], set[str], dict[str, str]]:
    identifiers: set[str] = set()
    attributes: set[str] = set()
    labels: dict[str, str] = {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            identifier = str(row.get("id", "") or "")
            if not identifier:
                continue
            identifiers.add(identifier)
            labels[identifier] = str(row.get("label", "") or "")
            if "attribute_slim" in str(row.get("slim", "") or "").split("|"):
                attributes.add(identifier)
    return identifiers, attributes, labels


@dataclass
class Catalogs:
    po_ids: set[str]
    pato_ids: set[str]
    attribute_ids: set[str]
    pato_labels: dict[str, str]
    flopo_ids: set[str]
    combos: dict[tuple[str, str], gates.Combination]
    registry: dict[tuple[str, str], tuple[str, bool]]
    signature_registry: dict[str, tuple[str, bool]]
    lexicon: ExactPatoValueLexicon
    bearers: BearerResolver

    @classmethod
    def load(
        cls,
        *,
        po_lexicon: Path = Path("config/po_lexicon.tsv"),
        pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
        flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
        combinations: Path = Path("config/valid_combinations.tsv"),
        pato_obo: Path = Path("ont/quality.obo"),
    ) -> "Catalogs":
        po_ids, _, _ = _load_tsv_ids(po_lexicon)
        pato_ids, attribute_ids, labels = _load_tsv_ids(pato_lexicon)
        return cls(
            po_ids=po_ids,
            pato_ids=pato_ids,
            attribute_ids=attribute_ids,
            pato_labels=labels,
            flopo_ids=gates.load_flopo_ids(flopo_registry),
            combos=gates.load_combinations(combinations),
            registry=gates.load_eq_registry(flopo_registry),
            signature_registry=gates.load_signature_registry(flopo_registry),
            lexicon=ExactPatoValueLexicon.load(pato_obo),
            bearers=BearerResolver(po_lexicon),
        )


# ---------------------------------------------------------------------------------------------
# Value grounding


def clause_values(text: str, start: int, end: int, catalogs: Catalogs) -> list[ValueMatch]:
    """Closed baseline cues plus exact PATO labels; overlapping or ambiguous matches removed."""

    found: list[ValueMatch] = []
    clause = text[start:end]
    for cue in baseline.QUALITY_PATTERNS:
        family = baseline.QUALITY_FAMILY.get(cue.pato_id, "")
        if family not in ATTRIBUTE_BY_FAMILY:
            continue
        for match in cue.pattern.finditer(clause):
            absolute = re.compile(re.escape(match.group(0))).match(text, start + match.start())
            if absolute is None or baseline._compound_edge(text, absolute):
                continue
            found.append(
                ValueMatch(
                    start + match.start(),
                    start + match.end(),
                    ExactValue(
                        cue.pato_id,
                        catalogs.pato_labels.get(cue.pato_id, ""),
                        family,
                        match.group(0).casefold(),
                    ),
                    match.group(0),
                )
            )
    found.extend(catalogs.lexicon.matches(text, start, end))
    for pattern, english in FRENCH_EXACT_FORMS:
        value = catalogs.lexicon.forms.get(english)
        if value is None:
            continue
        for match in pattern.finditer(text, start, end):
            if baseline._compound_edge(text, match):
                continue
            found.append(ValueMatch(match.start(), match.end(), value, match.group(0)))
    by_span: dict[tuple[int, int], set[str]] = defaultdict(set)
    for value in found:
        by_span[(value.start, value.end)].add(value.value.pato_id)
    unique: dict[tuple[int, int], ValueMatch] = {}
    for value in found:
        key = (value.start, value.end)
        if len(by_span[key]) == 1 and key not in unique:
            unique[key] = value
    ambiguous = [key for key, ids in by_span.items() if len(ids) > 1]
    values = [
        value
        for key, value in unique.items()
        if not any(
            other != key and other[0] <= key[0] and key[1] <= other[1]
            for other in list(unique) + ambiguous
        )
        and not any(a[0] < key[1] and key[0] < a[1] for a in ambiguous)
    ]
    return sorted(values, key=lambda value: (value.start, value.end))


def relations_in_clause(text: str, values: list[ValueMatch]) -> list[Relation]:
    relations: list[Relation] = []
    for left, right in zip(values, values[1:]):
        right_cue = _degree_cue_before(text, right.start, right.value.family)
        between_end = right_cue[0] if right_cue is not None else right.start
        between = text[left.end : between_end]
        left_cue = _degree_cue_before(text, left.start, left.value.family)
        for interpretation, pattern in (
            ("continuum", _CONTINUUM),
            ("temporal_transition", _TRANSITION),
        ):
            match = pattern.fullmatch(between)
            if match is None:
                continue
            relations.append(
                Relation(
                    interpretation,
                    _with_cue(left, left_cue),
                    _with_cue(right, right_cue),
                    left.end + match.start("connector"),
                    left.end + match.end("connector"),
                    left_cue,
                    right_cue,
                )
            )
    return relations


def endpoint_operand(text: str, value: ValueMatch, cue: tuple[int, int] | None, index: int) -> dict:
    """``from_operand``/``to_operand`` for a degree-modified endpoint (E2)."""

    assert cue is not None
    parsed = parse_qualifier_cue(text[cue[0] : cue[1]])
    return make_operand(
        index,
        value.value.pato_id,
        text,
        value.start,
        value.end,
        qualifier_start=cue[0],
        qualifier_end=cue[1],
        degree_qualifier=parsed["degree_qualifier"],
    )


# ---------------------------------------------------------------------------------------------
# Admission


def _masked(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _context_reason(text: str, relation: Relation) -> str:
    clause, clause_start = baseline._clause_at(text, relation.start)
    probe = text
    if relation.interpretation == "temporal_transition":
        probe = _masked(text, relation.connector_start, relation.connector_end)
    proxy = UnionCandidate(
        (relation.left, relation.right), (relation.connector_start,), relation.start, relation.end
    )
    for value in (relation.left, relation.right):
        contextual = _local_value_context_reason(probe, proxy, value)
        if contextual:
            return contextual
    probe_clause = probe[clause_start : clause_start + len(clause)]
    if relation.interpretation == "temporal_transition" and _TRANSITION_TRIGGER.search(
        probe_clause
    ):
        return "multiple_transitions_in_clause"
    if _COMPARED_TAXON.search(text[max(0, clause_start - 200) : clause_start + len(clause)]):
        return "compared_taxon_context"
    if _HTML_ENTITY.search(text[max(0, clause_start - 12) : clause_start + len(clause)]):
        return "html_entity_in_clause"
    if relation.interpretation == "continuum" and _CLAUSE_TEMPORAL.search(clause):
        return "temporal_cue_in_clause"
    if _SPECIMEN_STATE.search(clause):
        return "specimen_state_context"
    if _UNCERTAIN.search(clause):
        return "uncertain_context"
    if baseline._unmodelled_bearer_category(text, relation.start):
        return "unmodelled_bearer_category"
    if _RELATIONAL_FLOWER_CATEGORY_BEFORE.search(text[max(0, relation.start - 300) : relation.start]):
        return "relational_bearer_context"
    return ""


def _structure_reason(text: str, relation: Relation, values: list[ValueMatch]) -> str:
    left, right = relation.left, relation.right
    if left.value.family != right.value.family:
        return "mixed_attribute_families"
    if left.value.pato_id == right.value.pato_id:
        return "identical_endpoints"
    clause, clause_start = baseline._clause_at(text, relation.start)
    before = text[max(clause_start, left.start - 24) : left.start]
    after = text[right.end : min(clause_start + len(clause), right.end + 24)]
    if _CHAIN_BEFORE.search(before):
        return "chained_or_mixed_connector_before"
    if _CHAIN_AFTER.match(after):
        return "chained_or_mixed_connector_after"
    if baseline._cross_comma_value_alternative(text, right.end):
        return "following_comma_alternative"
    return ""


def _target_indexes(record: dict, relation: Relation) -> tuple[tuple[int, ...], str]:
    targets: list[int] = []
    for index, span in enumerate(record.get("unresolved_spans", []) or []):
        start = int(span.get("start", -1))
        end = int(span.get("end", -1))
        if not (start < relation.end and relation.start < end):
            continue
        inside = next(
            (
                value
                for value in (relation.left, relation.right)
                if value.start <= start and end <= value.end
            ),
            None,
        )
        if (
            span.get("reason") not in TARGET_REASONS
            or inside is None
            or str(span.get("candidate_pato_id", "")) != inside.value.pato_id
        ):
            return (), "unrelated_unresolved_span_in_relation"
        targets.append(index)
    if not targets:
        return (), "no_target_span"
    return tuple(targets), ""


def _overlaps_existing(record: dict, relation: Relation) -> bool:
    for assertion in record.get("assertions", []) or []:
        spans = [(assertion.get("source_start"), assertion.get("source_end"))]
        for start, end in spans:
            if isinstance(start, int) and isinstance(end, int):
                if start < relation.end and relation.start < end:
                    return True
    return False


def _raw_family_cue(text: str, start: int, end: int, family: str, *, outline: bool) -> bool:
    """Any same-family cue in ``text[start:end]``, including inside compounds and unsupported
    family terms (``yellow-green``, ``yellowish``, ``obovate``); terminal/base shapes are
    ignored beside an outline relation."""

    if end <= start:
        return False
    window = text[start:end]
    for cue in baseline.QUALITY_PATTERNS:
        if baseline.QUALITY_FAMILY.get(cue.pato_id) != family:
            continue
        if outline and cue.pato_id in TERMINAL_SHAPES | BASE_SHAPES:
            continue
        if cue.pattern.search(window):
            return True
    unsupported = baseline.UNSUPPORTED_FAMILY_TERMS.get(family)
    if unsupported is not None and unsupported.search(window):
        return True
    for pattern, english in FRENCH_EXACT_FORMS:
        if _FRENCH_FAMILY.get(english) != family or not pattern.search(window):
            continue
        if outline and english in _FRENCH_TERMINAL_OR_BASE:
            continue
        return True
    return False


def _operand_context_reason(
    text: str,
    relation: Relation,
    bearer: LocalBearer,
    values: Iterable[ValueMatch],
) -> str:
    """Operand safeguards of the explicit-union pass, adapted to a two-endpoint relation.

    As in the union pass: no uncertainty, no degree/colour modifier between the bearer (or the
    previous delimiter) and the first endpoint, no unsupported same-family neighbour, and no free
    text between the second endpoint and the next delimiter.  One refinement: a nearby
    same-family *terminal* shape (``elliptic to obovate, acute to acuminate``) describes the apex,
    a different aspect than an outline continuum, and does not make the outline incomplete.
    """

    left, right = relation.left, relation.right
    uncertainty_end = max(relation.end, bearer.end if bearer.end >= 0 else relation.end)
    if _UNCERTAINTY.search(text[relation.start : min(len(text), uncertainty_end + 2)]):
        return "uncertain_alternative"
    previous_delimiter = max((text.rfind(mark, 0, left.start) for mark in ",;:."), default=-1)
    prefix_start = previous_delimiter + 1
    if bearer.end <= left.start:
        prefix_start = max(prefix_start, bearer.end)
    if not _STRICT_FILLER.fullmatch(text[prefix_start : left.start]):
        return "modified_first_operand"
    family_pattern = baseline.UNSUPPORTED_FAMILY_TERMS.get(relation.family)
    if family_pattern is not None:
        hard_start = max((text.rfind(mark, 0, left.start) for mark in ";:."), default=-1) + 1
        if bearer.end <= left.start:
            hard_start = max(hard_start, bearer.end)
        if family_pattern.search(text[hard_start : left.start]):
            return "unsupported_same_attribute_preceding_value"
    outline = not ({left.value.pato_id, right.value.pato_id} & (TERMINAL_SHAPES | BASE_SHAPES))
    for other in values:
        if other in (left, right) or other.value.family != relation.family:
            continue
        if outline and other.value.pato_id in TERMINAL_SHAPES | BASE_SHAPES:
            continue
        before_distance = relation.start - other.end
        after_distance = other.start - relation.end
        if 0 <= before_distance <= 40 or 0 <= after_distance <= 56:
            between = text[min(other.end, relation.end) : max(other.start, relation.start)]
            if "," in between and not re.search(r"[;:.]", between):
                return "nearby_unincluded_same_attribute_value"
    clause, clause_start = baseline._clause_at(text, relation.start)
    scan_start = max(clause_start, bearer.end if 0 <= bearer.end <= left.start else clause_start)
    if _raw_family_cue(text, scan_start, left.start, relation.family, outline=outline):
        return "preceding_same_family_value"
    if 0 <= bearer.end <= left.start:
        between = text[bearer.end : left.start]
        if between.count(")") > between.count("(") or between.count("]") > between.count("["):
            return "parenthetical_bearer"
    after_member = re.match(r"\s*,([^,;:.]*)", text[relation.end : clause_start + len(clause)])
    if after_member and _raw_family_cue(
        text,
        relation.end + after_member.start(1),
        relation.end + after_member.end(1),
        relation.family,
        outline=outline,
    ):
        return "following_same_family_value"
    delimiter = re.search(r"[,;:.]", text[right.end :])
    boundary = right.end + delimiter.start() if delimiter else len(text)
    suffix = text[right.end : boundary]
    if bearer.start >= right.end and bearer.end <= boundary:
        suffix = suffix[: bearer.start - right.end] + suffix[bearer.end - right.end :]
    if not _STRICT_FILLER.fullmatch(suffix):
        return "qualified_or_incomplete_final_operand"
    return ""


def _bearer_scope_reason(text: str, relation: Relation, bearer: LocalBearer) -> str:
    """Bearer-scope safeguards of the explicit-union pass with a comma-member-local locative.

    The union pass rejects any locative within 56/72 characters, which also vetoes relations
    whose neighbouring comma member has its own attached locative (``cuneate at base, elliptic
    to obovate``).  The relation itself cannot carry a locative (its suffix must be empty), so
    only a locative in the immediately preceding comma member is treated as possibly scoping a
    colour or pilosity relation (``glabrous outside, pubescent to tomentose``).
    """

    distance = max(bearer.start - relation.end, relation.start - bearer.end, 0)
    if distance > 96:
        return "distant_local_bearer"
    span_text = text[min(relation.start, bearer.start) : max(relation.end, bearer.end)]
    if _UNSUPPORTED_BEARER_NOUN.search(span_text):
        return "unsupported_subregion_or_bearer"
    clause, clause_start = baseline._clause_at(text, relation.start)
    if _UNSUPPORTED_BEARER_NOUN.search(text[clause_start : relation.start]):
        return "unsupported_preceding_subregion_or_bearer"
    bearer_prefix = text[max(clause_start, bearer.start - 32) : bearer.start]
    relational_prefix = text[max(clause_start, bearer.start - 128) : bearer.start]
    if _RELATIONAL_OBJECT_BEFORE_BEARER.search(relational_prefix):
        return "intervening_relational_object_bearer"
    if _BEARER_SUBREGION_MODIFIER.search(bearer_prefix):
        return "qualified_bearer_subregion"
    if _BEARER_SUBSET_MODIFIER.search(bearer_prefix) or _EXTRA_SUBSET_BEFORE_BEARER.search(
        bearer_prefix
    ):
        return "qualified_bearer_subset"
    if _STAGE_PHRASE_BEFORE_BEARER.search(bearer_prefix):
        return "stage_or_relational_phrase_bearer"
    if _OF_BEFORE_BEARER.search(bearer_prefix):
        return "bearer_is_complement_of_another_noun"
    if bearer.end <= relation.start and _POSTPOSED_SUBSET_AFTER_BEARER.match(
        text[bearer.end : relation.start]
    ):
        return "postposed_bearer_subset"
    if bearer.start >= relation.end and re.search(r"[,;:.]", text[relation.end : bearer.start]):
        return "postposed_bearer_after_delimiter"
    if relation.family != "shape":
        member_end = text.rfind(",", clause_start, relation.start)
        if member_end >= 0:
            member_start = max(text.rfind(",", clause_start, member_end), clause_start - 1) + 1
            if _LOCATIVE_SCOPE.search(text[member_start:member_end]):
                return "locative_subregion_scope"
    if _RESPECTIVELY.match(text[relation.end : relation.end + 72]):
        return "respectively_scoped_values"
    return ""


def _ambiguous_bearers_in_scope(text: str, relation: Relation, selected: LocalBearer) -> bool:
    """Nested-bearer guard of the explicit-union pass, bounded by the local clause.

    The union helper scans 96 characters regardless of ``;``/``:``, so ``petiole 2 cm; blade
    ovate to elliptic`` is rejected because of the previous member's petiole.  Here the window
    starts after the last semicolon/colon/sentence boundary before the selected bearer; any
    second distinct non-nested PO bearer inside that scope still rejects the relation.
    """

    clause, clause_start = baseline._clause_at(text, relation.start)
    colon = text.rfind(":", clause_start, min(selected.start, relation.start))
    scope_start = max(clause_start, colon + 1)
    window_start = max(scope_start, min(selected.start, relation.start) - 96)
    window_end = max(relation.end, selected.end)
    occurrences: set[tuple[str, int, int]] = set()
    for po_id, pattern in baseline.LOCAL_BEARER_PATTERNS:
        for match in pattern.finditer(text, window_start, window_end):
            occurrences.add((po_id, match.start(), match.end()))
    non_nested = {
        row
        for row in occurrences
        if not any(
            other != row
            and other[1] <= row[1]
            and row[2] <= other[2]
            and (other[2] - other[1]) > (row[2] - row[1])
            for other in occurrences
        )
    }
    return len({row[0] for row in non_nested}) > 1


def _heading_bearer(record: dict, relation: Relation, catalogs: Catalogs) -> LocalBearer | None:
    """Organ heading only for a segment-initial construction whose clause names no bearer."""

    text = str(record.get("text", "") or "")
    if text[: relation.start].strip(" \t\r\n"):
        return None
    heading = catalogs.bearers.heading(record.get("organ"))
    if not heading:
        return None
    return LocalBearer(heading, "organ_heading", str(record.get("organ", "") or ""), -1, -1)


def _heading_suffix_reason(text: str, relation: Relation, values: list[ValueMatch]) -> str:
    delimiter = re.search(r"[,;:.]", text[relation.end :])
    boundary = relation.end + delimiter.start() if delimiter else len(text)
    if text[relation.end : boundary].strip():
        return "qualified_or_incomplete_final_operand"
    family = relation.family
    for other in values:
        if other.value.family != family or other in (relation.left, relation.right):
            continue
        if 0 <= other.start - relation.end <= 56:
            between = text[relation.end : other.start]
            if "," in between and not re.search(r"[;:.]", between):
                return "nearby_unincluded_same_attribute_value"
    return ""


def evaluate(record: dict, relation: Relation, values: list[ValueMatch], catalogs: Catalogs) -> Outcome:
    text = str(record.get("text", "") or "")
    reason = _structure_reason(text, relation, values)
    if reason:
        return Outcome("retained", reason, relation)
    targets, reason = _target_indexes(record, relation)
    if reason:
        return Outcome("retained", reason, relation)
    reason = _context_reason(text, relation)
    if reason:
        return Outcome("retained", reason, relation)
    if _overlaps_existing(record, relation):
        return Outcome("retained", "overlapping_existing_assertion", relation)

    left_bearer = _resolve_explicit_bearer(record, relation.left)
    right_bearer = _resolve_explicit_bearer(record, relation.right)
    if not left_bearer.po_id and not right_bearer.po_id and (
        left_bearer.method == right_bearer.method == "heading_only_or_missing"
    ):
        bearer = _heading_bearer(record, relation, catalogs)
        if bearer is None:
            return Outcome("retained", "heading_only_or_missing_bearer", relation)
        reason = _heading_suffix_reason(text, relation, values)
        if reason:
            return Outcome("retained", reason, relation)
    else:
        if not left_bearer.po_id or not right_bearer.po_id:
            return Outcome("retained", "bearer_unresolved_for_an_endpoint", relation)
        if left_bearer.occurrence_key != right_bearer.occurrence_key:
            return Outcome("retained", "different_explicit_bearers", relation)
        bearer = left_bearer
        if bearer.method not in {"explicit_local", "contextual_local"}:
            return Outcome("retained", f"bearer_{bearer.method}", relation)
        if _ambiguous_bearers_in_scope(text, relation, bearer):
            return Outcome("retained", "multiple_local_bearers", relation)
        reason = _operand_context_reason(text, relation, bearer, values)
        if reason:
            return Outcome("retained", reason, relation)
        if relation.family != "shape" and 0 <= bearer.end <= relation.start and _NESTED_ATTRIBUTIVE_PART.search(
            text[bearer.end : relation.start]
        ):
            # ``folioles 5, à pétiolule de 1 mm, éparsement pubescent à glabre``: the relation
            # describes the attributive part (pétiolule), not the named bearer.
            return Outcome("retained", "nested_attributive_part_before_relation", relation)
        if bearer.start >= 0 and _WITH_BEFORE_BEARER.search(
            text[max(0, bearer.start - 60) : bearer.start]
        ):
            # ``leaves ..., with long petioles, glabrous to hispidulous``: the bearer is the
            # complement of ``with``; the relation may describe the governing organ.
            return Outcome("retained", "bearer_is_with_complement", relation)
        if _BRANCH_SURFACE.match(bearer.surface_form) and _INFLORESCENCE_BEFORE.search(
            text[max(0, bearer.start - 160) : bearer.start]
        ):
            # ``panicles ...; branches glabrous to shortly hairy``: inflorescence branches.
            return Outcome("retained", "branch_in_inflorescence_context", relation)
        if _BLADE_SURFACE.match(bearer.surface_form):
            window = text[max(0, bearer.start - 160) : relation.end]
            if _FLORAL_CONTEXT.search(window):
                return Outcome("retained", "blade_in_floral_context", relation)
        # The explicit-union safeguards treat blade/limbe nouns as unsupported; a blade that is
        # itself the selected bearer is masked so it cannot veto its own attachment.
        probe = text[: bearer.start] + "x" * (bearer.end - bearer.start) + text[bearer.end :]
        reason = _bearer_scope_reason(probe, relation, bearer)
        if reason:
            return Outcome("retained", reason, relation)

    if relation.family == "colour":
        # ``Ovaire densément pubescent velouté, gris à brun``: a colour range directly after a
        # dense indument term describes the hairs (indumentum), not the organ surface.
        scope_start = max((text.rfind(mark, 0, relation.start) for mark in ";:."), default=-1) + 1
        if bearer.start >= 0 and bearer.end <= relation.start:
            scope_start = max(scope_start, bearer.end)
        if _DENSE_INDUMENT_BEFORE.search(text[scope_start : relation.start]):
            return Outcome("retained", "colour_after_indument_term", relation)
    endpoint_ids = {relation.left.value.pato_id, relation.right.value.pato_id}
    if endpoint_ids & BASE_SHAPES:
        return Outcome("retained", "base_shape_endpoint_needs_base_bearer", relation)
    if endpoint_ids & TERMINAL_SHAPES and bearer.po_id in LEAF_LIKE_BEARERS:
        return Outcome("retained", "terminal_shape_endpoint_on_leaf_bearer", relation)
    # Leaf-part bearers in a leaflet description are re-borne on the FLOPO leaflet part; the
    # combination check below then decides whether that bearer x attribute pair is admissible.
    leaflet_part = leaflet_bearer(bearer.po_id, text, relation.start)
    if leaflet_part != bearer.po_id:
        bearer = replace(bearer, po_id=leaflet_part)
    attribute = ATTRIBUTE_BY_FAMILY[relation.family]
    if bearer.po_id.startswith("PO_") and bearer.po_id not in catalogs.po_ids:
        return Outcome("retained", "unknown_bearer_id", relation)
    if bearer.po_id.startswith("FLOPO_") and bearer.po_id not in catalogs.flopo_ids:
        return Outcome("retained", "unknown_bearer_id", relation)
    if attribute not in catalogs.attribute_ids:
        return Outcome("retained", "top_level_not_pato_attribute", relation)
    for value in (relation.left, relation.right):
        if value.value.pato_id not in catalogs.pato_ids:
            return Outcome("retained", "unknown_endpoint_id", relation)
    combo = catalogs.combos.get((bearer.po_id, attribute))
    if combo is None or combo.status != "allowed":
        return Outcome("retained", "bearer_attribute_combination_not_allowed", relation)
    return Outcome("recovered", "exact_source_bound_relation", relation, bearer, bearer.method, targets)


# ---------------------------------------------------------------------------------------------
# Assertion construction


def build_assertion(
    record: dict,
    outcome: Outcome,
    catalogs: Catalogs,
    *,
    hold_for_review: bool = True,
) -> tuple[dict, dict]:
    """Return ``(assertion, source_statement)`` for one recovered relation."""

    relation = outcome.relation
    bearer = outcome.bearer
    assert relation is not None and bearer is not None
    text = str(record.get("text", "") or "")
    attribute = ATTRIBUTE_BY_FAMILY[relation.family]
    explicit = bearer.start >= 0
    source_start = min(relation.start, bearer.start) if explicit else relation.start
    source_end = max(relation.end, bearer.end) if explicit else relation.end
    verbatim = text[source_start:source_end]
    statement_id = stable_statement_id(record, source_start, source_end, verbatim)
    char_start = int(record.get("char_start", 0) or 0)
    statement = {
        "document_end": char_start + source_end,
        "document_start": char_start + source_start,
        "end": source_end,
        "language": str(record.get("language", "") or ""),
        "start": source_start,
        "statement_id": statement_id,
        "verbatim_text": verbatim,
    }
    provenance = [
        f"claude_rule:{relation.interpretation}:{text[relation.connector_start:relation.connector_end].casefold()}",
        "endpoints: closed baseline cue or PATO preferred/EXACT label; same attribute family",
        f"bearer_method:{outcome.bearer_method}",
    ]
    if explicit:
        provenance.append(
            f"same explicit PO bearer occurrence: {bearer.surface_form} [{bearer.start},{bearer.end})"
        )
    else:
        provenance.append("bearer:organ_heading")
    if bearer.po_id in LEAFLET_PART_IDS:
        provenance.append(f"leaflet_context_bearer:{bearer.po_id}")
    provenance.append("qualitative relation record; no FAC IRI, union, or FLOPO class minted")
    if relation.left_cue is not None or relation.right_cue is not None:
        provenance.append("endpoint_qualifiers:E2")
    assertion: dict[str, Any] = {
        "po_id": bearer.po_id,
        "pato_id": attribute,
        "negated": False,
        "negation_scope": "",
        "organ": record.get("organ", ""),
        "source_text": verbatim,
        "source_start": source_start,
        "source_end": source_end,
        "bearer_start": bearer.start if explicit else None,
        "bearer_end": bearer.end if explicit else None,
        "modality_start": None,
        "modality_end": None,
        "extractor": EXTRACTOR,
        "value_low": None,
        "value_high": None,
        "value_low_inclusive": True,
        "value_high_inclusive": True,
        "unit": "",
        "value_text": "",
        "trait": "",
        "modifier": "",
        "cardinality": "",
        "confidence": None,
        "raw_entity_text": bearer.surface_form if explicit else "",
        "raw_quality_text": text[relation.start : relation.end],
        "entity_mention_id": "",
        "quality_mention_ids": [],
        "value_operator": "atomic",
        "bearer_context_qualities": [],
        "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
        "normalization_status": "compositional",
        "mapping_provenance": provenance,
        "source_statement_id": statement_id,
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
        "value_terms": [],
        "qualitative_value_relation": {
            "connector_end": relation.connector_end,
            "connector_start": relation.connector_start,
            "connector_text": text[relation.connector_start : relation.connector_end],
            "from_end": relation.left.end,
            "from_start": relation.left.start,
            "from_text": text[relation.left.start : relation.left.end],
            "from_value": relation.left.value.pato_id,
            "interpretation": relation.interpretation,
            "to_end": relation.right.end,
            "to_start": relation.right.start,
            "to_text": text[relation.right.start : relation.right.end],
            "to_value": relation.right.value.pato_id,
        },
        "composition": {
            "status": "accept",
            "confidence": 1.0,
            "reasons": [EXTRACTOR],
            "entity_label": "",
            "quality_label": catalogs.pato_labels.get(attribute, ""),
            "clause": verbatim,
        },
    }
    qualitative = assertion["qualitative_value_relation"]
    if relation.left_cue is not None:
        qualitative["from_operand"] = endpoint_operand(text, relation.left, relation.left_cue, 0)
    if relation.right_cue is not None:
        qualitative["to_operand"] = endpoint_operand(text, relation.right, relation.right_cue, 1)
    decision = gates.check_assertion(
        text,
        assertion,
        catalogs.combos,
        catalogs.registry,
        catalogs.signature_registry,
        catalogs.attribute_ids,
        pato_catalog_ids=catalogs.pato_ids,
        flopo_catalog_ids=catalogs.flopo_ids,
        po_catalog_ids=catalogs.po_ids,
    )
    gate = {
        "status": decision.status,
        "reasons": list(decision.reasons),
        "po_pato_status": decision.po_pato_status,
        "flopo_iri": decision.flopo_iri,
        "flopo_status": decision.flopo_status,
        "flopo_signature": decision.flopo_signature,
        "review_priority": decision.review_priority,
        "confidence": decision.confidence,
        "verifier_status": "",
        "verifier_reasons": [],
        "floratraiter_status": "",
        "floratraiter_reasons": [],
    }
    if hold_for_review and gate["status"] == "accepted":
        gate["status"] = "review"
        gate["reasons"] = [*gate["reasons"], HOLD_REASON]
        gate["review_priority"] = max(int(gate["review_priority"] or 0), 20)
    assertion["gate"] = gate
    return assertion, statement


# ---------------------------------------------------------------------------------------------
# Record / file drivers


def _statement_disjunction_reason(text: str, outcome: Outcome, *, hold_for_review: bool) -> str:
    """Keep the data-model invariant that an atomic-operator record carries no ``or``/``ou``.

    A relation is recorded with ``value_operator=atomic``.  If the retained statement (bearer up
    to the second endpoint) contains a disjunction, the bearer's scope is itself uncertain
    (``folioles 1-21, ovées à oblongues ou obovées, glabres à pubescentes``).  Admitted records
    are checked against the whole clause, as the validator does for accepted assertions.
    """

    relation, bearer = outcome.relation, outcome.bearer
    assert relation is not None and bearer is not None
    start = min(relation.start, bearer.start) if bearer.start >= 0 else relation.start
    end = max(relation.end, bearer.end) if bearer.start >= 0 else relation.end
    source_text = text[start:end]
    if _has_real_disjunction(source_text):
        return "disjunction_inside_statement"
    if not hold_for_review and _has_real_disjunction(
        _clause_around(text, source_text, start, end)
    ):
        return "disjunction_in_clause_blocks_admission"
    return ""


def recover_record(
    record: dict, catalogs: Catalogs, *, hold_for_review: bool = True
) -> tuple[dict | None, list[Outcome]]:
    """Return a delta line (or ``None``) and every evaluated outcome for one segment."""

    text = str(record.get("text", "") or "")
    unresolved = record.get("unresolved_spans", []) or []
    target_positions = [
        int(span.get("start", -1)) for span in unresolved if span.get("reason") in TARGET_REASONS
    ]
    if not target_positions:
        return None, []
    clauses: set[tuple[int, int]] = set()
    for position in target_positions:
        clause, clause_start = baseline._clause_at(text, position)
        clauses.add((clause_start, clause_start + len(clause)))
    outcomes: list[Outcome] = []
    used: set[int] = set()
    add_assertions: list[dict] = []
    add_statements: dict[str, dict] = {}
    existing_statements = {
        str(row.get("statement_id", "")) for row in record.get("source_statements", []) or []
    }
    for clause_start, clause_end in sorted(clauses):
        values = clause_values(text, clause_start, clause_end, catalogs)
        for relation in relations_in_clause(text, values):
            outcome = evaluate(record, relation, values, catalogs)
            if outcome.status == "recovered" and used.intersection(outcome.targets):
                outcome = Outcome("retained", "target_already_used", relation)
            if outcome.status == "recovered":
                reason = _statement_disjunction_reason(
                    text, outcome, hold_for_review=hold_for_review
                )
                if reason:
                    outcome = Outcome("retained", reason, relation)
            outcomes.append(outcome)
            if outcome.status != "recovered":
                continue
            used.update(outcome.targets)
            assertion, statement = build_assertion(
                record, outcome, catalogs, hold_for_review=hold_for_review
            )
            add_assertions.append(assertion)
            if statement["statement_id"] not in existing_statements:
                add_statements[statement["statement_id"]] = statement
    if not add_assertions:
        return None, outcomes
    delta = {
        "key": segment_key(record),
        "add_source_statements": list(add_statements.values()),
        "add_assertions": add_assertions,
        "remove_unresolved": [
            {
                "start": int(unresolved[index]["start"]),
                "end": int(unresolved[index]["end"]),
                "reason": unresolved[index]["reason"],
                "surface_form": unresolved[index]["surface_form"],
            }
            for index in sorted(used)
        ],
    }
    return delta, outcomes


def segment_key(record: dict) -> dict[str, Any]:
    return {
        "source": record.get("source", ""),
        "source_id": record.get("source_id", ""),
        "source_segment_index": record.get("source_segment_index", 0),
        "taxon": record.get("taxon", ""),
        "organ": record.get("organ", ""),
        "char_start": record.get("char_start", 0),
        "char_end": record.get("char_end", 0),
    }


def _key_tuple(key: dict[str, Any]) -> tuple:
    return tuple(
        key.get(name)
        for name in (
            "source",
            "source_id",
            "source_segment_index",
            "taxon",
            "organ",
            "char_start",
            "char_end",
        )
    )


def recover_file(
    input_path: Path,
    delta_path: Path,
    *,
    catalogs: Catalogs,
    hold_for_review: bool = True,
    outcomes_path: Path | None = None,
) -> dict[str, Any]:
    counts: Counter[str] = Counter()
    by_language: Counter[str] = Counter()
    by_interpretation: Counter[str] = Counter()
    by_family: Counter[str] = Counter()
    by_reason_resolved: Counter[str] = Counter()
    target_spans: Counter[str] = Counter()
    delta_path.parent.mkdir(parents=True, exist_ok=True)
    outcome_rows = []
    with Path(input_path).open(encoding="utf-8") as source, delta_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            for span in record.get("unresolved_spans", []) or []:
                if span.get("reason") in TARGET_REASONS:
                    target_spans[span["reason"]] += 1
            delta, outcomes = recover_record(record, catalogs, hold_for_review=hold_for_review)
            for outcome in outcomes:
                counts[f"{outcome.status}:{outcome.reason}"] += 1
                if outcomes_path is not None and outcome.relation is not None:
                    text = record["text"]
                    relation = outcome.relation
                    outcome_rows.append(
                        {
                            "status": outcome.status,
                            "reason": outcome.reason,
                            "language": record.get("language", ""),
                            "interpretation": relation.interpretation,
                            "family": relation.family,
                            "expression": text[relation.start : relation.end],
                            "context": text[max(0, relation.start - 60) : relation.end + 40],
                        }
                    )
            if delta is None:
                continue
            output.write(json.dumps(delta, ensure_ascii=False, sort_keys=True) + "\n")
            counts["segments_touched"] += 1
            counts["assertions_added"] += len(delta["add_assertions"])
            counts["spans_resolved"] += len(delta["remove_unresolved"])
            by_language[str(record.get("language", ""))] += len(delta["remove_unresolved"])
            for span in delta["remove_unresolved"]:
                by_reason_resolved[span["reason"]] += 1
            for assertion in delta["add_assertions"]:
                relation = assertion["qualitative_value_relation"]
                by_interpretation[relation["interpretation"]] += 1
                by_family[assertion["pato_id"]] += 1
                counts[f"gate:{assertion['gate']['status']}"] += 1
    if outcomes_path is not None:
        outcomes_path.parent.mkdir(parents=True, exist_ok=True)
        with outcomes_path.open("w", encoding="utf-8", newline="") as handle:
            fields = ["status", "reason", "language", "interpretation", "family", "expression", "context"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for row in outcome_rows:
                writer.writerow({k: str(v).replace("\t", " ").replace("\n", " ") for k, v in row.items()})
    return {
        "input": str(input_path),
        "delta": str(delta_path),
        "extractor": EXTRACTOR,
        "hold_for_review": hold_for_review,
        "target_spans": dict(sorted(target_spans.items())),
        "spans_resolved_by_reason": dict(sorted(by_reason_resolved.items())),
        "spans_resolved_by_language": dict(sorted(by_language.items())),
        "assertions_by_interpretation": dict(sorted(by_interpretation.items())),
        "assertions_by_attribute": dict(sorted(by_family.items())),
        "counts": dict(sorted(counts.items())),
    }


# ---------------------------------------------------------------------------------------------
# Delta application


def apply_delta_to_record(record: dict, delta: dict) -> dict:
    """Return a patched copy of ``record``; fail closed on any unmatched removal or reference."""

    result = dict(record)
    statements = list(record.get("source_statements", []) or [])
    known = {str(row.get("statement_id", "")) for row in statements}
    for statement in delta.get("add_source_statements", []) or []:
        if statement["statement_id"] not in known:
            statements.append(statement)
            known.add(statement["statement_id"])
    for assertion in delta.get("add_assertions", []) or []:
        if assertion.get("source_statement_id") not in known:
            raise ValueError(f"assertion references unknown statement: {assertion.get('source_statement_id')}")
    remove = {
        (int(row["start"]), int(row["end"]), row["reason"], row["surface_form"])
        for row in delta.get("remove_unresolved", []) or []
    }
    kept = []
    removed = set()
    for span in record.get("unresolved_spans", []) or []:
        key = (int(span.get("start", -1)), int(span.get("end", -1)), span.get("reason"), span.get("surface_form"))
        if key in remove:
            removed.add(key)
            continue
        kept.append(span)
    if removed != remove:
        raise ValueError(f"delta removes unresolved spans absent from segment: {sorted(remove - removed)}")
    result["source_statements"] = statements
    result["assertions"] = [*(record.get("assertions", []) or []), *delta.get("add_assertions", [])]
    result["unresolved_spans"] = kept
    return result


def apply_delta(input_path: Path, delta_path: Path, output_path: Path) -> dict[str, int]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("delta output must be distinct from its input")
    deltas: dict[tuple, dict] = {}
    with Path(delta_path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                delta = json.loads(line)
                key = _key_tuple(delta["key"])
                if key in deltas:
                    raise ValueError(f"duplicate delta key: {key}")
                deltas[key] = delta
    applied = 0
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            delta = deltas.get(_key_tuple(segment_key(record)))
            if delta is not None:
                record = apply_delta_to_record(record, delta)
                applied += 1
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
    if applied != len(deltas):
        raise ValueError(f"applied {applied} of {len(deltas)} delta lines")
    return {"delta_lines": len(deltas), "applied": applied}


# ---------------------------------------------------------------------------------------------
# Review sample


def wilson_interval(successes: int, total: int, z: float = 1.959964) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total)) / denominator
    return centre - margin, centre + margin


def draw_sample(
    delta_path: Path,
    input_path: Path,
    *,
    size: int = 150,
    seed: int = 20260918,
) -> list[dict[str, Any]]:
    """Stratified (language x interpretation x attribute) seeded sample of recovered relations."""

    wanted: dict[tuple, list[dict]] = {}
    with Path(delta_path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                delta = json.loads(line)
                wanted[_key_tuple(delta["key"])] = delta["add_assertions"]
    rows: list[dict[str, Any]] = []
    with Path(input_path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            assertions = wanted.get(_key_tuple(segment_key(record)))
            if not assertions:
                continue
            text = record["text"]
            for assertion in assertions:
                relation = assertion["qualitative_value_relation"]
                start = int(assertion["source_start"])
                end = int(assertion["source_end"])
                rows.append(
                    {
                        "stratum": (
                            record.get("language", ""),
                            relation["interpretation"],
                            assertion["pato_id"],
                        ),
                        "span": f"{record['source']}:{record['source_id']}:"
                        f"{record['source_segment_index']}:{start}-{end}",
                        "text_window": text[max(0, start - 80) : min(len(text), end + 60)],
                        "assertion_summary": (
                            f"{assertion['po_id']} ({assertion.get('raw_entity_text') or record.get('organ')}) "
                            f"{assertion['pato_id']} {relation['interpretation']}: "
                            f"{relation['from_text']}={relation['from_value']} "
                            f"{relation['connector_text']} "
                            f"{relation['to_text']}={relation['to_value']}"
                        ),
                    }
                )
    rng = random.Random(seed)
    strata: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        strata[row["stratum"]].append(row)
    for members in strata.values():
        members.sort(key=lambda row: row["span"])
        rng.shuffle(members)
    ordered = sorted(strata)
    selected: list[dict] = []
    cursor = 0
    while len(selected) < min(size, len(rows)):
        progressed = False
        for stratum in ordered:
            if cursor < len(strata[stratum]) and len(selected) < size:
                selected.append(strata[stratum][cursor])
                progressed = True
        if not progressed:
            break
        cursor += 1
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("recover")
    run.add_argument("input", type=Path)
    run.add_argument("--delta", type=Path, required=True)
    run.add_argument("--report", type=Path)
    run.add_argument("--outcomes", type=Path)
    run.add_argument(
        "--admit",
        action="store_true",
        help="keep the computed gate status instead of holding relations for dual-family review",
    )
    apply = sub.add_parser("apply")
    apply.add_argument("input", type=Path)
    apply.add_argument("--delta", type=Path, required=True)
    apply.add_argument("-o", "--output", type=Path, required=True)
    sample = sub.add_parser("sample")
    sample.add_argument("input", type=Path)
    sample.add_argument("--delta", type=Path, required=True)
    sample.add_argument("-o", "--output", type=Path, required=True)
    sample.add_argument("--size", type=int, default=150)
    sample.add_argument("--seed", type=int, default=20260918)
    args = parser.parse_args()
    if args.command == "recover":
        report = recover_file(
            args.input,
            args.delta,
            catalogs=Catalogs.load(),
            hold_for_review=not args.admit,
            outcomes_path=args.outcomes,
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if args.report:
            args.report.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
    elif args.command == "apply":
        print(json.dumps(apply_delta(args.input, args.delta, args.output)))
    else:
        rows = draw_sample(args.delta, args.input, size=args.size, seed=args.seed)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as handle:
            fields = ["span", "text_window", "assertion_summary", "verdict", "note"]
            writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {
                        "span": row["span"],
                        "text_window": row["text_window"].replace("\t", " ").replace("\n", " "),
                        "assertion_summary": row["assertion_summary"],
                        "verdict": "",
                        "note": "",
                    }
                )
        print(json.dumps({"sample": len(rows), "output": str(args.output)}))


if __name__ == "__main__":
    main()
