"""Phase 7 validity gates for FLOPO 2.0 candidate assertions.

Phase 6 checks whether a source span supports an entity-quality binding. Phase 7 decides whether a
candidate is eligible for database promotion:

* source span must still be verbatim in the segment;
* Phase 6 composition status must be accepted;
* the PO x PATO pair must be allowed by ``config/valid_combinations.tsv``;
* blocklisted pairs are rejected; novel pairs go to curation instead of ontology promotion.

The output keeps every assertion with gate provenance so the database loader can retain accepted,
review, and blocked rows without losing evidence.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract.compose import _clause_around
from flopo2.extract.measurement import is_supported_length_unit
from flopo2.ids.registry import load_registry

VerifierFn = Callable[[dict, str], tuple[str, list[str]] | None]

MANUAL_REVIEW_PATO_IDS = {
    # Process-duration acute, not botanical organ shape.
    "PATO_0000389": "pato_acute_process_duration_manual_review",
    # Sexual-puberty maturity, not botanical pilosity/pubescence.
    "PATO_0000455": "pato_puberty_maturity_manual_review",
    # Usually caused by morphology words such as "attenuated"/"atténué" grounding
    # to PATO:reduced virulence instead of PATO:attenuate. Keep residual cases out
    # of promotion, but retain evidence for later curation.
    "PATO_0002147": "pato_reduced_virulence_manual_review",
}

NEGATION_EVIDENCE = re.compile(
    r"(?<!\w)(?:not|never|no|without|lacking|non|ne|n['’]|pas|jamais|ni|sans|"
    r"d[ée]pourvu(?:e|es|s)?|absent(?:e|es|s)?)(?!\w)|"
    r"\b(?:unbranched|unarmed|unlobed|unstalked|unwinged|unawned|unspotted|"
    r"unmarked|unridged|unveined|unhairy)\b",
    re.IGNORECASE,
)
# Finite (``ne dépasse pas``) as well as participial (``ne dépassant pas``) French comparators are
# both upper-bound cues; the shared verb group covers dépasser/atteindre/excéder in either form.
_FR_BOUND_VERB = (
    r"(?:d[ée]passant|d[ée]passe(?:nt)?|atteignant|atteignent|atteint|"
    r"exc[ée]dant|exc[ée]de(?:nt)?)"
)
UPPER_BOUND_EVIDENCE = re.compile(
    r"(?<!\w)(?:up\s+to|at\s+most|no\s+more\s+than|"
    r"not\s+(?:more\s+than|exceeding|over|longer\s+than|surpassing)|"
    r"maximum|max\.?)(?!\w)|"
    r"jusqu['’]?\s*[aà]|pas\s+plus\s+de|au\s+plus|"
    r"(?:ne|n['’])\s*[^,;:.]{0,36}\b" + _FR_BOUND_VERB + r"[^,;:.]{0,20}\bpas\b|"
    r"(?:ne|n['’])\s*" + _FR_BOUND_VERB + r"\s+pas",
    re.IGNORECASE,
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


@dataclass(frozen=True)
class Combination:
    status: str
    source: str = ""
    example_label: str = ""

    @property
    def curator_reviewed(self) -> bool:
        return self.source.startswith("curator_review_")


@dataclass(frozen=True)
class GateDecision:
    status: str
    reasons: tuple[str, ...]
    po_pato_status: str
    flopo_iri: str
    flopo_status: str
    flopo_signature: str
    review_priority: int
    confidence: float
    verifier_status: str = ""
    verifier_reasons: tuple[str, ...] = ()
    floratraiter_status: str = ""
    floratraiter_reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


def load_combinations(path: Path = Path("config/valid_combinations.tsv")) -> dict[tuple[str, str], Combination]:
    combos: dict[tuple[str, str], Combination] = {}
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            combos[(row["po_id"], row["pato_id"])] = Combination(
                status=row.get("status", ""),
                source=row.get("source", ""),
                example_label=row.get("example_label", ""),
            )
    return combos


def load_eq_registry(path: Path = Path("config/flopo_id_registry.tsv")) -> dict[tuple[str, str], tuple[str, bool]]:
    """Return (PO, PATO) -> (FLOPO IRI, deprecated) for existing EQ classes."""
    out: dict[tuple[str, str], tuple[str, bool]] = {}
    if not Path(path).exists():
        return out
    for entry in load_registry(path):
        parts = entry.signature.split("|")
        if len(parts) == 3 and parts[0] == "EQ":
            out[(parts[1], parts[2])] = (entry.iri, entry.deprecated)
    return out


def load_signature_registry(path: Path = Path("config/flopo_id_registry.tsv")) -> dict[str, tuple[str, bool]]:
    if not Path(path).exists():
        return {}
    return {
        entry.signature: (entry.iri, entry.deprecated)
        for entry in load_registry(path)
        if entry.signature != "OTHER"
    }


def assertion_signature(assertion: dict) -> str:
    po_id = assertion.get("po_id", "")
    pato_id = assertion.get("pato_id", "")
    operator = assertion.get("value_operator", "atomic") or "atomic"
    values = sorted(set(assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or []))
    if operator == "atomic" and len(values) == 1:
        return f"EQ|{po_id}|{values[0]}"
    if operator in {"one_of", "all_of"} and values:
        return f"EQV|{po_id}|{operator.upper()}|{'&'.join(values)}"
    return f"EQ|{po_id}|{pato_id}"


def load_pato_attribute_terms(path: Path = Path("config/pato_lexicon.tsv")) -> set[str]:
    """Return PATO ids tagged as attributes rather than specific value qualities."""
    out: set[str] = set()
    if not Path(path).exists():
        return out
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            if "attribute_slim" in (row.get("slim") or "").split("|"):
                out.add(row["id"])
    return out


def load_catalog_ids(path: Path) -> set[str]:
    if not Path(path).exists():
        return set()
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return {row.get("id", "") for row in csv.DictReader(fh, delimiter="\t") if row.get("id")}


def load_flopo_ids(path: Path = Path("config/flopo_id_registry.tsv")) -> set[str]:
    if not Path(path).exists():
        return set()
    out: set[str] = set()
    with Path(path).open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            iri = row.get("flopo_iri", "")
            if "/FLOPO_" in iri:
                out.add(iri.rsplit("/", 1)[-1])
    return out


def _has_real_disjunction(source_text: str) -> bool:
    source_text = re.sub(
        r"\bmore\s+or\s+less\b|\bplus\s+ou\s+moins\b",
        "",
        _norm(source_text),
    )
    return re.search(r"\b(?:or|ou)\b", source_text) is not None


def _priority(reasons: list[str], flopo_status: str, verifier_status: str = "",
              floratraiter_status: str = "") -> int:
    priority = 0
    if "po_pato_blocklisted" in reasons or "source_span_not_verbatim" in reasons:
        priority += 100
    if "composition_not_accepted" in reasons:
        priority += 80
    if "po_pato_novel" in reasons:
        priority += 60
    if "pato_reduced_virulence_manual_review" in reasons:
        priority += 75
    if "pato_attribute_trait_manual_review" in reasons:
        priority += 55
    if flopo_status == "new_class_candidate":
        priority += 50
    elif flopo_status == "existing_deprecated":
        priority += 90
    if verifier_status in {"disagree", "review"}:
        priority += 70
    if floratraiter_status in {"disagree", "review"}:
        priority += 50
    return priority


def check_assertion(
    segment_text: str,
    assertion: dict,
    combos: dict[tuple[str, str], Combination],
    registry: dict[tuple[str, str], tuple[str, bool]] | None = None,
    signature_registry: dict[str, tuple[str, bool]] | None = None,
    attribute_pato_ids: set[str] | None = None,
    verifier: VerifierFn | None = None,
    floratraiter: VerifierFn | None = None,
    taxon_provenance: str | None = None,
    pato_catalog_ids: set[str] | None = None,
    flopo_catalog_ids: set[str] | None = None,
) -> GateDecision:
    reasons: list[str] = []
    score = 1.0
    key = (assertion.get("po_id", ""), assertion.get("pato_id", ""))
    operator = assertion.get("value_operator", "atomic") or "atomic"
    value_terms = tuple(
        dict.fromkeys(assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or [])
    )
    flopo_signature = assertion_signature(assertion)
    source_text = assertion.get("source_text", "") or ""
    if not source_text or source_text not in segment_text:
        reasons.append("source_span_not_verbatim")
        score -= 0.45
    source_start = assertion.get("source_start")
    source_end = assertion.get("source_end")
    if source_start is not None or source_end is not None:
        if (
            not isinstance(source_start, int)
            or isinstance(source_start, bool)
            or not isinstance(source_end, int)
            or isinstance(source_end, bool)
            or source_start < 0
            or source_end < source_start
            or source_end > len(segment_text)
            or segment_text[source_start:source_end] != source_text
        ):
            reasons.append("invalid_source_offsets")
            score -= 0.45
    elif source_text and segment_text.count(source_text) > 1:
        reasons.append("ambiguous_source_span_without_offsets")
        score -= 0.25

    # Model extractors sometimes truncate their evidence immediately before an alternative,
    # e.g. source_text="Leaves simple" for "Leaves simple or compound". Inspect the exact
    # offset-derived comma/semicolon/sentence clause as well as the submitted span so an atomic
    # assertion cannot evade the disjunction gate by shortening its evidence.
    source_context = _clause_around(
        segment_text,
        source_text,
        source_start if isinstance(source_start, int) and not isinstance(source_start, bool) else None,
        source_end if isinstance(source_end, int) and not isinstance(source_end, bool) else None,
    )

    if taxon_provenance is not None and not str(taxon_provenance).strip():
        reasons.append("missing_taxon_provenance")
        score -= 0.25

    negated = bool(assertion.get("negated", False))
    negation_scope = str(assertion.get("negation_scope", "") or "").strip()
    if negated and negation_scope not in {"quality", "absence"}:
        reasons.append(
            "missing_negation_scope" if not negation_scope else "invalid_negation_scope"
        )
        score -= 0.5
    elif not negated and negation_scope:
        reasons.append("negation_scope_without_negation")
        score -= 0.5
    if negated and not NEGATION_EVIDENCE.search(source_text):
        reasons.append("negation_cue_not_in_source_span")
        score -= 0.5
    if str(assertion.get("cardinality", "") or "").strip():
        reasons.append("cardinality_not_supported_by_owl")
        score -= 0.35
    # Frequency and epistemic qualifiers are carried by the formal assertion record. They do not
    # weaken a taxon SubClassOf axiom: the source-assertion OWL builder emits qualified claims only
    # at the meta level. Consequently a modifier is representable and is not itself a review reason.

    value_low = assertion.get("value_low")
    value_high = assertion.get("value_high")
    bounds = [value for value in (value_low, value_high) if value is not None]
    finite_bounds = True
    for value in bounds:
        try:
            finite_bounds = finite_bounds and math.isfinite(float(value))
        except (TypeError, ValueError):
            finite_bounds = False
    if bounds and not finite_bounds:
        reasons.append("nonfinite_measurement")
        score -= 0.5
    elif value_low is not None and value_high is not None and float(value_low) > float(value_high):
        reasons.append("reversed_measurement_range")
        score -= 0.5
    unit = str(assertion.get("unit", "") or "").strip()
    if bounds and attribute_pato_ids and assertion.get("pato_id", "") not in attribute_pato_ids:
        reasons.append("numeric_quality_not_pato_attribute")
        score -= 0.5
    if bounds and not unit:
        reasons.append("measurement_missing_unit")
        score -= 0.5
    elif bounds and not is_supported_length_unit(unit):
        reasons.append("unsupported_measurement_unit")
        score -= 0.5
    elif unit and not bounds:
        reasons.append("measurement_unit_without_value")
        score -= 0.5
    if value_low is None and value_high is not None and not UPPER_BOUND_EVIDENCE.search(source_text):
        reasons.append("upper_bound_cue_not_in_source_span")
        score -= 0.5
    for flag_name, bound in (
        ("value_low_inclusive", value_low),
        ("value_high_inclusive", value_high),
    ):
        flag = assertion.get(flag_name, True)
        if not isinstance(flag, bool):
            reasons.append("invalid_bound_inclusivity")
            score -= 0.5
        elif flag is False and bound is None:
            reasons.append("bound_inclusivity_without_bound")
            score -= 0.5
    # Finite, unit-bearing bounds are phenotype value restrictions in a flora source TBox. They
    # are not measurement events, and the source-assertion OWL builder now preserves them. A
    # strict bound (value_*_inclusive False) renders xsd:maxExclusive/minExclusive downstream.

    stage_contexts = assertion.get("developmental_stage_contexts", []) or []
    stage_operator = assertion.get("developmental_stage_operator", "atomic") or "atomic"
    if stage_operator not in {"atomic", "all_of", "one_of"}:
        reasons.append("invalid_developmental_stage_operator")
        score -= 0.5
    elif stage_operator in {"all_of", "one_of"} and len(stage_contexts) < 2:
        reasons.append("developmental_stage_operator_missing_components")
        score -= 0.5
    elif stage_operator == "atomic" and len(stage_contexts) > 1:
        reasons.append("atomic_developmental_stage_has_multiple_contexts")
        score -= 0.5
    for context in stage_contexts:
        if not isinstance(context, dict):
            reasons.append("invalid_developmental_stage_context")
            score -= 0.5
            continue
        term = str(context.get("stage_term", "") or "").replace(":", "_")
        if not re.fullmatch(r"(?:PO|FLOPO)_\d+", term):
            reasons.append("invalid_developmental_stage_term")
            score -= 0.5
        if (context.get("temporal_relation", "present_during") or "present_during") != "present_during":
            reasons.append("invalid_developmental_stage_relation")
            score -= 0.5
        stage_text = str(context.get("stage_text", "") or "")
        start = context.get("start")
        end = context.get("end")
        if not stage_text or stage_text not in segment_text:
            reasons.append("developmental_stage_text_not_verbatim")
            score -= 0.45
        elif start is not None or end is not None:
            if (
                not isinstance(start, int)
                or isinstance(start, bool)
                or not isinstance(end, int)
                or isinstance(end, bool)
                or start < 0
                or end < start
                or end > len(segment_text)
                or segment_text[start:end] != stage_text
            ):
                reasons.append("invalid_developmental_stage_offsets")
                score -= 0.45

    composition = assertion.get("composition") or {}
    comp_status = composition.get("status", "")
    if comp_status and comp_status != "accept":
        reasons.append("composition_not_accepted")
        score -= 0.35

    if operator not in {"atomic", "all_of", "one_of"}:
        reasons.append("invalid_value_operator")
        score -= 0.5
    elif operator in {"all_of", "one_of"} and len(value_terms) < 2:
        reasons.append("logical_value_missing_components")
        score -= 0.5
    elif operator == "atomic" and len(value_terms) > 1:
        reasons.append("atomic_value_has_multiple_components")
        score -= 0.5
    elif operator == "one_of" and not _has_real_disjunction(source_context):
        reasons.append("disjunction_not_supported_by_source")
        score -= 0.4
    if operator == "atomic" and _has_real_disjunction(source_context):
        reasons.append(
            "atomic_source_contains_disjunction"
            if _has_real_disjunction(source_text)
            else "atomic_clause_contains_disjunction"
        )
        score -= 0.35
    if (
        operator == "atomic"
        and len(value_terms) == 1
        and attribute_pato_ids
        and assertion.get("pato_id", "") != value_terms[0]
        and assertion.get("pato_id", "") not in attribute_pato_ids
    ):
        reasons.append("atomic_value_top_level_incompatible")
        score -= 0.4
    if (
        operator in {"one_of", "all_of"}
        and attribute_pato_ids
        and assertion.get("pato_id", "") not in attribute_pato_ids
    ):
        reasons.append("logical_value_top_level_not_attribute")
        score -= 0.4
    if any(not term.startswith(("PATO_", "FLOPO_")) for term in value_terms):
        reasons.append("invalid_value_term_namespace")
        score -= 0.5
    for term in value_terms:
        if term.startswith("PATO_") and pato_catalog_ids and term not in pato_catalog_ids:
            reasons.append("unknown_value_pato_id")
            score -= 0.5
        if term.startswith("FLOPO_") and flopo_catalog_ids and term not in flopo_catalog_ids:
            reasons.append("unknown_value_flopo_id")
            score -= 0.5

    combo = combos.get(key)
    po_pato_status = combo.status if combo else "novel"
    if po_pato_status in {"blocked", "blocklisted", "invalid"}:
        reasons.append("po_pato_blocklisted")
        score = 0.0
    elif po_pato_status == "novel":
        reasons.append("po_pato_novel")
        score -= 0.25
    elif po_pato_status != "allowed":
        reasons.append(f"po_pato_{po_pato_status or 'unknown'}")
        score -= 0.25

    for pato_id in dict.fromkeys((assertion.get("pato_id", ""), *value_terms)):
        manual_review_reason = MANUAL_REVIEW_PATO_IDS.get(pato_id)
        if manual_review_reason and manual_review_reason not in reasons:
            reasons.append(manual_review_reason)
            score -= 0.35

    flopo_iri = ""
    annotation_extension_only = bool(
        negated
        or operator == "one_of"
        or assertion.get("season_contexts", [])
        or stage_contexts
    )
    flopo_status = "annotation_extension_only" if annotation_extension_only else "new_class_candidate"
    if not annotation_extension_only:
        signature_hit = signature_registry.get(flopo_signature) if signature_registry else None
        pair_hit = registry.get(key) if registry and not value_terms else None
        if signature_hit or pair_hit:
            flopo_iri, deprecated = signature_hit or pair_hit
            flopo_status = "existing_deprecated" if deprecated else "existing"
            if deprecated:
                reasons.append("existing_flopo_deprecated")
                score -= 0.25

    if (
        attribute_pato_ids
        and assertion.get("pato_id", "") in attribute_pato_ids
        and flopo_status == "new_class_candidate"
        and not value_terms
        and not (combo and getattr(combo, "curator_reviewed", False))
    ):
        reasons.append("pato_attribute_trait_manual_review")
        score -= 0.25

    verifier_status = ""
    verifier_reasons: list[str] = []
    if verifier is not None:
        result = verifier(assertion, segment_text)
        if result is not None:
            verifier_status, verifier_reasons = result
            if verifier_status in {"disagree", "review"}:
                reasons.append("verifier_disagrees")
                score -= 0.25

    floratraiter_status = ""
    floratraiter_reasons: list[str] = []
    if floratraiter is not None:
        result = floratraiter(assertion, segment_text)
        if result is not None:
            floratraiter_status, floratraiter_reasons = result
            if floratraiter_status in {"disagree", "review"}:
                reasons.append("floratraiter_disagrees")
                score -= 0.20

    score = max(0.0, min(1.0, score))
    blocking_value_reasons = {
        "invalid_value_operator",
        "logical_value_missing_components",
        "disjunction_not_supported_by_source",
        "invalid_value_term_namespace",
        "unknown_value_pato_id",
        "unknown_value_flopo_id",
        "atomic_value_has_multiple_components",
        "atomic_value_top_level_incompatible",
        "measurement_missing_unit",
        "unsupported_measurement_unit",
        "measurement_unit_without_value",
        "nonfinite_measurement",
        "reversed_measurement_range",
        "numeric_quality_not_pato_attribute",
        "invalid_source_offsets",
        "missing_negation_scope",
        "invalid_negation_scope",
        "negation_scope_without_negation",
        "negation_cue_not_in_source_span",
        "upper_bound_cue_not_in_source_span",
        "invalid_bound_inclusivity",
        "bound_inclusivity_without_bound",
        "invalid_developmental_stage_operator",
        "developmental_stage_operator_missing_components",
        "atomic_developmental_stage_has_multiple_contexts",
        "invalid_developmental_stage_context",
        "invalid_developmental_stage_term",
        "invalid_developmental_stage_relation",
        "developmental_stage_text_not_verbatim",
        "invalid_developmental_stage_offsets",
    }
    if (
        "po_pato_blocklisted" in reasons
        or "source_span_not_verbatim" in reasons
        or blocking_value_reasons.intersection(reasons)
    ):
        status = "blocked"
    elif reasons:
        status = "review"
    else:
        status = "accepted"
    return GateDecision(
        status=status,
        reasons=tuple(reasons),
        po_pato_status=po_pato_status,
        flopo_iri=flopo_iri,
        flopo_status=flopo_status,
        flopo_signature=flopo_signature,
        review_priority=_priority(reasons, flopo_status, verifier_status, floratraiter_status),
        confidence=round(score, 3),
        verifier_status=verifier_status,
        verifier_reasons=tuple(verifier_reasons),
        floratraiter_status=floratraiter_status,
        floratraiter_reasons=tuple(floratraiter_reasons),
    )


def gate_segment(
    obj: dict,
    combos: dict[tuple[str, str], Combination],
    registry: dict[tuple[str, str], tuple[str, bool]] | None = None,
    signature_registry: dict[str, tuple[str, bool]] | None = None,
    attribute_pato_ids: set[str] | None = None,
    verifier: VerifierFn | None = None,
    floratraiter: VerifierFn | None = None,
    pato_catalog_ids: set[str] | None = None,
    flopo_catalog_ids: set[str] | None = None,
) -> dict:
    assertions = []
    text = obj.get("text", "")
    input_assertions = obj.get("assertions")
    from_composition_audit = input_assertions is None and isinstance(obj.get("decisions"), list)
    if from_composition_audit:
        input_assertions = []
        for composition_decision in obj.get("decisions", []):
            if not isinstance(composition_decision, dict):
                continue
            source_assertion = composition_decision.get("assertion")
            if not isinstance(source_assertion, dict):
                continue
            row = dict(source_assertion)
            if "value_terms" not in row and "value_term_ids" in row:
                row["value_terms"] = row.pop("value_term_ids")
            row["composition"] = {
                key: composition_decision.get(key)
                for key in (
                    "status",
                    "confidence",
                    "reasons",
                    "entity_label",
                    "quality_label",
                    "clause",
                )
            }
            input_assertions.append(row)
    for idx, assertion in enumerate(input_assertions or []):
        decision = check_assertion(
            text,
            assertion,
            combos,
            registry,
            signature_registry,
            attribute_pato_ids,
            verifier,
            floratraiter,
            obj.get("taxon") if "taxon" in obj else None,
            pato_catalog_ids,
            flopo_catalog_ids,
        )
        row = dict(assertion)
        row["gate"] = asdict(decision)
        row["gate"]["assertion_index"] = idx
        assertions.append(row)
    out = dict(obj)
    if from_composition_audit:
        # Each normalized assertion retains its complete composition decision. Avoid storing the
        # same evidence twice in the gated artifact and its SQLite projection.
        out.pop("decisions", None)
    out["assertions"] = assertions
    return ensure_source_statements(out)


def _write_split(handle, obj: dict, status: str) -> int:
    rows = [a for a in obj.get("assertions", []) or [] if (a.get("gate") or {}).get("status") == status]
    unresolved = obj.get("unresolved_spans", []) or []
    if not rows and not (unresolved and status in {"accepted", "review"}):
        return 0
    rec = dict(obj)
    rec["assertions"] = rows
    handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return len(rows)


def run_file(
    input_path: Path,
    out_path: Path,
    combinations_path: Path = Path("config/valid_combinations.tsv"),
    accepted_out: Path | None = None,
    review_out: Path | None = None,
    blocked_out: Path | None = None,
    registry_path: Path = Path("config/flopo_id_registry.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    limit: int | None = None,
) -> dict:
    combos = load_combinations(combinations_path)
    registry = load_eq_registry(registry_path)
    signature_registry = load_signature_registry(registry_path)
    attribute_pato_ids = load_pato_attribute_terms(pato_lexicon_path)
    pato_catalog_ids = load_catalog_ids(pato_lexicon_path)
    flopo_catalog_ids = load_flopo_ids(registry_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for p in (accepted_out, review_out, blocked_out):
        if p:
            p.parent.mkdir(parents=True, exist_ok=True)

    segments = 0
    statuses: Counter[str] = Counter()
    unresolved_spans = 0
    source_positions: Counter[tuple[str, str]] = Counter()
    with (
        Path(input_path).open(encoding="utf-8") as inp,
        out_path.open("w", encoding="utf-8") as out_fh,
        (accepted_out.open("w", encoding="utf-8") if accepted_out else nullcontext()) as accepted_fh,
        (review_out.open("w", encoding="utf-8") if review_out else nullcontext()) as review_fh,
        (blocked_out.open("w", encoding="utf-8") if blocked_out else nullcontext()) as blocked_fh,
    ):
        for line in inp:
            if limit is not None and segments >= limit:
                break
            if not line.strip():
                continue
            raw_obj = json.loads(line)
            source_key = (raw_obj.get("source", ""), raw_obj.get("source_id", ""))
            raw_obj.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            obj = gate_segment(
                raw_obj,
                combos,
                registry,
                signature_registry,
                attribute_pato_ids,
                pato_catalog_ids=pato_catalog_ids,
                flopo_catalog_ids=flopo_catalog_ids,
            )
            out_fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            for assertion in obj.get("assertions", []) or []:
                statuses[(assertion.get("gate") or {}).get("status", "unknown")] += 1
            unresolved_spans += len(obj.get("unresolved_spans", []) or [])
            if accepted_fh is not None:
                _write_split(accepted_fh, obj, "accepted")
            if review_fh is not None:
                _write_split(review_fh, obj, "review")
            if blocked_fh is not None:
                _write_split(blocked_fh, obj, "blocked")
            segments += 1

    return {
        "segments": segments,
        "assertions": sum(statuses.values()),
        "unresolved_spans": unresolved_spans,
        "statuses": dict(statuses),
        "combinations": len(combos),
        "registry_eq": len(registry),
        "attribute_pato_terms": len(attribute_pato_ids),
    }


# Imported late so the public gate helpers above remain easy to read.
from contextlib import nullcontext  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 7 validity gates.")
    ap.add_argument(
        "input",
        type=Path,
        help="Phase 6 split JSONL or complete composition-audit JSONL",
    )
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/gated_assertions.jsonl"))
    ap.add_argument("--combinations", type=Path, default=Path("config/valid_combinations.tsv"))
    ap.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    ap.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    ap.add_argument("--accepted-out", type=Path)
    ap.add_argument("--review-out", type=Path)
    ap.add_argument("--blocked-out", type=Path)
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()
    summary = run_file(
        args.input,
        args.out,
        combinations_path=args.combinations,
        registry_path=args.registry,
        pato_lexicon_path=args.pato_lexicon,
        accepted_out=args.accepted_out,
        review_out=args.review_out,
        blocked_out=args.blocked_out,
        limit=args.limit,
    )
    print(json.dumps({**summary, "out": str(args.out)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
