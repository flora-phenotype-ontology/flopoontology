"""Prepare contextual exact-PATO compound colours for dual-model attachment review.

The deterministic exact-colour pass correctly retained source tokens when local bearer or context
guards were inconclusive.  This pass revisits those retained tokens without weakening their lexical
grounding: the complete token must still normalize, by dash/space normalization only, to one
unambiguous PATO colour preferred label or EXACT synonym.  A candidate is emitted only for an
existing active FLOPO EQ pair and an allowed PO–PATO combination.  Context and bearer-scope guard
results are preserved as risk flags for occurrence-level review.  No source or ontology artifact is
mutated here.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from flopo2.review.io import atomic_write_text, sha256_file, stable_id
from flopo2.review.models import PhenotypeExpressionCandidate
from flopo2.verify.recover_exact_pato_compounds import (
    BearerResolver,
    _colour_modifier_start,
    _nearby_context_reason,
    _unsafe_bearer_scope,
    exact_compound_colour_lexicon,
    find_exact_compounds,
)
from flopo2.verify.recover_leaf_apex_expressions import _active_eq_pairs
from flopo2.verify.recover_qualitative_relations import (
    _load_combinations,
    _load_ids,
    _overlaps,
)


CANDIDATE_REASON = "contextual_exact_pato_colour_compound_candidate"
EXTRACTOR = "contextual_exact_pato_colour_compound_candidate_v1"
TARGET_REASON = "hyphenated_or_slash_compound"
_HARD_CONTEXT_EXCLUSIONS = frozenset(
    {
        "developmental_stage_context",
        "negated_context",
        "comparative_context",
    }
)


def _bearer_offsets(
    text: str,
    surface: str,
    expression_start: int,
) -> tuple[str, int | None, int | None]:
    if not surface:
        return "", None, None
    matches = list(re.finditer(re.escape(surface), text, re.IGNORECASE))
    if not matches:
        return "", None, None
    selected = min(matches, key=lambda match: abs(match.start() - expression_start))
    return text[selected.start() : selected.end()], selected.start(), selected.end()


def _candidate_for(
    record: dict[str, Any],
    compound: Any,
    *,
    bearers: BearerResolver,
    po_ids: set[str],
    pato_ids: set[str],
    combinations: dict[tuple[str, str], str],
    active_pairs: set[tuple[str, str]],
) -> tuple[PhenotypeExpressionCandidate | None, str, tuple[str, ...]]:
    text = str(record.get("text", "") or "")
    unresolved = record.get("unresolved_spans", []) or []
    if (
        compound.start < 0
        or compound.end <= compound.start
        or compound.end > len(text)
        or not text[compound.start : compound.end]
    ):
        return None, "invalid_compound_offsets", ()
    if compound.pato_id not in pato_ids:
        return None, "unknown_live_pato_id", ()

    clear: list[tuple[int, int]] = []
    for index in compound.unresolved_indexes:
        if index < 0 or index >= len(unresolved):
            return None, "invalid_clear_target_index", ()
        span = unresolved[index]
        try:
            start, end = int(span["start"]), int(span["end"])
        except (KeyError, TypeError, ValueError):
            return None, "invalid_clear_target_offsets", ()
        if (
            span.get("reason") != TARGET_REASON
            or not (compound.start <= start < end <= compound.end)
            or text[start:end] != str(span.get("surface_form", "") or "")
        ):
            return None, "clear_target_not_exact_current_compound_span", ()
        clear.append((start, end))
    if not clear:
        return None, "no_exact_current_clear_target", ()
    if len(clear) != len(set(clear)):
        return None, "duplicate_clear_target", ()

    contextual = _nearby_context_reason(text, compound.start, compound.end)
    if contextual in _HARD_CONTEXT_EXCLUSIONS:
        return None, contextual, ()
    if _colour_modifier_start(text, compound.start) < compound.start:
        return None, "unmodeled_colour_modifier", ()
    bearer = bearers.resolve(record, compound.start, compound.end, compound.pato_id)
    if not bearer.po_id:
        return None, f"bearer_{bearer.method or 'missing'}", ()
    if bearer.po_id not in po_ids:
        return None, "unknown_live_po_id", ()
    if (bearer.po_id, compound.pato_id) not in active_pairs:
        return None, "no_active_existing_flopo_eq", ()
    if combinations.get((bearer.po_id, compound.pato_id), "novel") != "allowed":
        return None, "bearer_colour_combination_not_allowed", ()
    if any(
        _overlaps(assertion, compound.start, compound.end)
        for assertion in record.get("assertions", []) or []
    ):
        return None, "overlapping_existing_assertion", ()

    risk_flags = ["contextual_exact_colour_attachment"]
    if contextual:
        risk_flags.append(f"prior_context_guard:{contextual}")
    unsafe_scope = _unsafe_bearer_scope(
        text,
        compound.start,
        compound.end,
        bearer,
    )
    if unsafe_scope:
        risk_flags.append(f"prior_bearer_scope:{unsafe_scope[0]}")
    if bearer.method == "organ_heading":
        risk_flags.append("organ_heading_bearer")

    bearer_text, bearer_start, bearer_end = _bearer_offsets(
        text,
        bearer.surface_form,
        compound.start,
    )
    candidate = PhenotypeExpressionCandidate(
        signature={
            "bearer_id": bearer.po_id,
            "quality_id": compound.pato_id,
            "value_operator": "atomic",
        },
        bearer_method=bearer.method,
        bearer_text=bearer_text,
        bearer_start=bearer_start,
        bearer_end=bearer_end,
        expression_start=compound.start,
        expression_end=compound.end,
        expression_text=text[compound.start : compound.end],
        clear_unresolved_spans=tuple(sorted(clear)),
    )
    return candidate, "", tuple(risk_flags)


def _immutable_text(path: Path, payload: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed exact-colour artifact: {path}")
    atomic_write_text(path, payload)


def prepare_contextual_exact_colour_review(
    *,
    stage_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    exclusions_path: Path,
    report_path: Path,
    pato_obo: Path = Path("ont/quality.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Build a conserved exact-colour candidate inventory over a frozen stage."""

    inputs = {
        stage_path.resolve(),
        pato_obo.resolve(),
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
        raise ValueError("all exact-colour inputs and outputs must be distinct")

    po_ids, _ = _load_ids(po_lexicon)
    pato_ids, _ = _load_ids(pato_lexicon)
    combinations = _load_combinations(combinations_path)
    active_pairs = _active_eq_pairs(flopo_registry)
    bearers = BearerResolver(po_lexicon)
    lexicon = exact_compound_colour_lexicon(pato_obo)
    counts: Counter[str] = Counter()
    ledger: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    review_records: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int, int, str]] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            source = str(record.get("source", "") or "")
            source_id = str(record.get("source_id", "") or "")
            segment_index = int(record.get("source_segment_index", 0) or 0)
            synthetic: list[dict[str, Any]] = []
            for compound in find_exact_compounds(record, lexicon):
                counts["target_compounds"] += 1
                identity = (
                    source,
                    source_id,
                    segment_index,
                    compound.start,
                    compound.end,
                    compound.pato_id,
                )
                if identity in seen:
                    raise ValueError(f"duplicate exact compound at line {line_number}: {identity}")
                seen.add(identity)
                candidate, reason, risk_flags = _candidate_for(
                    record,
                    compound,
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
                            "start": compound.start,
                            "end": compound.end,
                            "surface_form": str(record.get("text", ""))[
                                compound.start : compound.end
                            ],
                            "candidate_pato_id": compound.pato_id,
                            "reason": reason,
                        }
                    )
                    counts[f"excluded:{reason}"] += 1
                    continue
                candidate_id = stable_id("exactcolour", identity)
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
                        "lexical_form": compound.lexical_form,
                        "pato_label": compound.pato_label,
                        "risk_flags": list(risk_flags),
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                counts["candidates"] += 1
                counts["candidate_clear_targets"] += len(candidate.clear_unresolved_spans)
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

    if len(ledger) + len(exclusions) != counts["target_compounds"]:
        raise ValueError("exact-colour candidate conservation failed")
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
        "input_scope": f"{TARGET_REASON}:exact_pato_colour",
        "target_compounds": counts["target_compounds"],
        "review_records": len(review_records),
        "candidates": len(ledger),
        "exclusions": len(exclusions),
        "conserved": len(ledger) + len(exclusions) == counts["target_compounds"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage": sha256_file(stage_path).model_dump(mode="json"),
            "pato_obo": sha256_file(pato_obo).model_dump(mode="json"),
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
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_contextual_exact_colour_review(
        stage_path=args.stage,
        review_input_path=args.review_input,
        candidate_ledger_path=args.ledger,
        exclusions_path=args.exclusions,
        report_path=args.report,
        pato_obo=args.pato_obo,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
        flopo_registry=args.flopo_registry,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
