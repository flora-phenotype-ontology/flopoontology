"""Prepare source-explicit leaf-base qualities withheld by broad shape conflict detection.

This pass is deliberately separate from :mod:`recover_leaf_apex_expressions`: a candidate is
eligible only when the nearest explicit terminal-region cue is ``base``.  It proposes an atomic
quality of PO leaf base only when that exact EQ already has an active FLOPO class and an allowed
PO–PATO combination.  The source bearer and attachment are still hypotheses and therefore require
occurrence-level dual-model review.  No corpus or ontology artifact is mutated here.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.extract.leaflet_context import leaflet_context
from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import PhenotypeExpressionCandidate
from flopo2.verify.recover_exact_pato_compounds import BearerResolver
from flopo2.verify.recover_leaf_apex_expressions import (
    LEAF_BEARERS,
    TARGET_REASON,
    _active_eq_pairs,
    _nearest_scope_cue,
)
from flopo2.verify.recover_qualitative_relations import (
    _load_combinations,
    _load_ids,
    _overlaps,
)


CANDIDATE_REASON = "leaf_base_expression_candidate"
EXTRACTOR = "leaf_base_expression_candidate_v1"
LEAF_BASE = "PO_0020040"
BASE_QUALITIES = frozenset(
    {
        "PATO_0001935",  # obtuse
        "PATO_0001982",  # attenuate
    }
)
_APEX_CUE = re.compile(
    r"\b(?:apex|tips?|summits?|sommet|sommets|pointe|pointes|"
    r"extr[ée]mit[ée]|extr[ée]mit[ée]s)\b",
    re.IGNORECASE,
)


def _candidate_for(
    record: dict[str, Any],
    span: dict[str, Any],
    *,
    bearers: BearerResolver,
    po_ids: set[str],
    pato_ids: set[str],
    combinations: dict[tuple[str, str], str],
    active_pairs: set[tuple[str, str]],
) -> tuple[PhenotypeExpressionCandidate | None, str, tuple[str, ...]]:
    text = str(record.get("text", "") or "")
    try:
        start = int(span["start"])
        end = int(span["end"])
    except (KeyError, TypeError, ValueError):
        return None, "invalid_span_offsets", ()
    surface = str(span.get("surface_form", "") or "")
    quality = str(span.get("candidate_pato_id", "") or "")
    if start < 0 or end <= start or end > len(text) or text[start:end] != surface:
        return None, "span_not_verbatim", ()
    if quality not in BASE_QUALITIES:
        return None, "not_target_base_quality", ()
    if LEAF_BASE not in po_ids or quality not in pato_ids:
        return None, "unknown_live_ontology_id", ()
    if (LEAF_BASE, quality) not in active_pairs:
        return None, "no_active_existing_flopo_eq", ()
    if combinations.get((LEAF_BASE, quality), "novel") != "allowed":
        return None, "leaf_base_quality_combination_not_allowed", ()

    scope, cue = _nearest_scope_cue(text, start, end)
    if scope != "base" or cue is None:
        return None, "no_nearest_explicit_base_scope", ()
    parent = bearers.resolve(record, start, end, quality)
    allowed_source_bearers = {*LEAF_BEARERS, LEAF_BASE}
    heading_fallback = (
        not parent.po_id and bearers.heading(record.get("organ")) in LEAF_BEARERS
    )
    if parent.po_id not in allowed_source_bearers and not heading_fallback:
        return None, "source_bearer_not_leaf_or_leaf_lamina", ()
    if leaflet_context(text, start):
        return None, "leaflet_context_bearer", ()

    contextual = baseline._negated_or_hedged(text, start)
    if contextual:
        return None, contextual, ()
    match = next(
        (
            match
            for quality_cue in baseline.QUALITY_PATTERNS
            if quality_cue.pato_id == quality
            for match in quality_cue.pattern.finditer(text)
            if match.start() == start and match.end() == end
        ),
        None,
    )
    if match is not None and (
        baseline._compound_edge(text, match)
        or baseline._adjacent_disjunction(text, start, end)
        or baseline._adjacent_transition(text, match)
    ):
        return None, "adjacent_compound_or_logical_operator", ()
    if any(_overlaps(assertion, start, end) for assertion in record.get("assertions", []) or []):
        return None, "overlapping_existing_assertion", ()

    risk_flags = ["explicit_leaf_base_attachment_requires_review"]
    clause, _clause_start = baseline._clause_at(text, start)
    if _APEX_CUE.search(clause):
        risk_flags.append("competing_apex_cue_in_clause")
    if parent.method == "organ_heading":
        risk_flags.append("parent_leaf_from_organ_heading")
    if heading_fallback:
        risk_flags.append("parent_leaf_heading_behind_explicit_base_cue")

    bearer_start, bearer_end = cue.start(), cue.end()
    expression_start = min(start, bearer_start)
    expression_end = max(end, bearer_end)
    candidate = PhenotypeExpressionCandidate(
        signature={
            "bearer_id": LEAF_BASE,
            "quality_id": quality,
            "value_operator": "atomic",
        },
        bearer_method="explicit_leaf_base_cue",
        bearer_text=text[bearer_start:bearer_end],
        bearer_start=bearer_start,
        bearer_end=bearer_end,
        expression_start=expression_start,
        expression_end=expression_end,
        expression_text=text[expression_start:expression_end],
        clear_unresolved_spans=((start, end),),
    )
    return candidate, "", tuple(risk_flags)


def _immutable_text(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed leaf-base artifact: {path}")
    atomic_write_text(path, payload)


def prepare_leaf_base_review_input(
    *,
    stage_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    exclusions_path: Path,
    report_path: Path,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Create a conserved, source-bound leaf-base candidate review corpus."""

    inputs = {
        stage_path.resolve(),
        po_lexicon.resolve(),
        pato_lexicon.resolve(),
        flopo_registry.resolve(),
        combinations_path.resolve(),
    }
    outputs = {
        review_input_path.resolve(),
        candidate_ledger_path.resolve(),
        exclusions_path.resolve(),
        report_path.resolve(),
    }
    if len(outputs) != 4 or inputs & outputs:
        raise ValueError("all leaf-base inputs and outputs must be distinct")

    po_ids, _ = _load_ids(po_lexicon)
    pato_ids, _ = _load_ids(pato_lexicon)
    combinations = _load_combinations(combinations_path)
    active_pairs = _active_eq_pairs(flopo_registry)
    bearers = BearerResolver(po_lexicon)
    counts: Counter[str] = Counter()
    ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    seen_ranges: set[tuple[str, str, int, int, int]] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", "") or "")
            source_id = str(record.get("source_id", "") or "")
            segment_index = int(record.get("source_segment_index", 0) or 0)
            synthetic: list[dict[str, Any]] = []
            for span in record.get("unresolved_spans", []) or []:
                if (
                    span.get("reason") != TARGET_REASON
                    or span.get("candidate_pato_id") not in BASE_QUALITIES
                ):
                    continue
                counts["target_spans"] += 1
                start = int(span.get("start", -1))
                end = int(span.get("end", -1))
                identity = (source, source_id, segment_index, start, end)
                if identity in seen_ranges:
                    raise ValueError(f"duplicate target span at line {line_number}: {identity}")
                seen_ranges.add(identity)
                candidate, reason, risk_flags = _candidate_for(
                    record,
                    span,
                    bearers=bearers,
                    po_ids=po_ids,
                    pato_ids=pato_ids,
                    combinations=combinations,
                    active_pairs=active_pairs,
                )
                if candidate is None:
                    exclusions.append(
                        {
                            "source": source,
                            "source_id": source_id,
                            "source_segment_index": segment_index,
                            "start": start,
                            "end": end,
                            "surface_form": span.get("surface_form", ""),
                            "candidate_pato_id": span.get("candidate_pato_id", ""),
                            "reason": reason,
                        }
                    )
                    counts[f"excluded:{reason}"] += 1
                    continue
                candidate_id = stable_id("leafbase", (*identity, candidate.signature.model_dump()))
                synthetic.append(
                    {
                        "start": candidate.expression_start,
                        "end": candidate.expression_end,
                        "surface_form": candidate.expression_text,
                        "reason": CANDIDATE_REASON,
                        "candidate_pato_id": candidate.signature.quality_id,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "phenotype_expression_candidate": candidate.model_dump(mode="json"),
                    }
                )
                ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "source": source,
                        "source_id": source_id,
                        "source_segment_index": segment_index,
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "risk_flags": list(risk_flags),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                counts["candidates"] += 1
                counts[f"candidate_quality:{candidate.signature.quality_id}"] += 1
                counts[f"candidate_bearer_method:{candidate.bearer_method}"] += 1
                for risk in risk_flags:
                    counts[f"candidate_risk:{risk}"] += 1
            if synthetic:
                synthetic.sort(key=lambda row: (row["start"], row["end"], row["candidate_id"]))
                text = str(record.get("text", "") or "")
                review_records.append(
                    {
                        "source": source,
                        "source_id": source_id,
                        "source_segment_index": segment_index,
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": record.get("char_start", 0),
                        "char_end": record.get("char_end", len(text)),
                        "text": text,
                        "unresolved_spans": synthetic,
                    }
                )

    if len(ledger) + len(exclusions) != counts["target_spans"]:
        raise ValueError("leaf-base candidate conservation failed")
    _immutable_text(
        review_input_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in review_records),
    )
    _immutable_text(
        candidate_ledger_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ledger),
    )
    _immutable_text(
        exclusions_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in exclusions),
    )
    report = {
        "schema_version": "flopo-expression-candidate-report-v1",
        "candidate_kind": CANDIDATE_REASON,
        "input_scope": TARGET_REASON,
        "target_spans": counts["target_spans"],
        "review_records": len(review_records),
        "candidates": len(ledger),
        "exclusions": len(exclusions),
        "conserved": len(ledger) + len(exclusions) == counts["target_spans"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "po_lexicon": sha256_file(po_lexicon).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "exclusions": sha256_file(exclusions_path).model_dump(mode="json"),
        },
    }
    _immutable_text(report_path, json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_leaf_base_review_input(
        stage_path=args.stage,
        review_input_path=args.review_input,
        candidate_ledger_path=args.ledger,
        exclusions_path=args.exclusions,
        report_path=args.report,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
