"""Prepare exact bilingual one-missing-endpoint shape compounds for machine review.

The baseline emits only the component it recognizes when a French/English compound's other
component is absent from its cue vocabulary.  This pass reconstructs complete two-word tokens and
binds the missing endpoint only through a small, hash-bound bilingual glossary map.  It retains all
strict isolation, bearer, overlap, and combination guards from the first shape-compound campaign.
The bilingual mappings are proposals until two independent model families verify each occurrence.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from flopo2.review.io import sha256_file, stable_id
from flopo2.verify.recover_exact_pato_compounds import BearerResolver, _compound_bounds
from flopo2.verify.recover_shape_compound_relations import (
    GROSS_OUTLINE_VALUES,
    SHAPE_ATTRIBUTE,
    TARGET_REASON,
    _candidate_for_group,
    _load_combinations,
    _load_ids,
    _segment_key,
    _span_key,
    _validate_target_span,
    _write_immutable_report,
    _write_immutable_rows,
)


REVIEW_REASON = "bilingual_shape_compound_continuum_candidate"
EXTRACTOR = "bilingual_shape_compound_continuum_candidate_v1"
_TWO_COMPONENTS = re.compile(
    r"^(?P<left>[^\W\d_]+)\s*(?P<dash>[-\u2013\u2014])\s*(?P<right>[^\W\d_]+)$",
    re.UNICODE,
)

# The French base forms must be present as >=0.92 glossary mappings below.  These generated
# inflections are ordinary adjective agreement only; no additional lexical sense is introduced.
_FRENCH_INFLECTIONS = {
    "oblong": ("oblong", "oblongs", "oblongue", "oblongues"),
    "elliptique": ("elliptique", "elliptiques"),
    "linéaire": ("linéaire", "linéaires"),
    "lancéolé": ("lancéolé", "lancéolée", "lancéolés", "lancéolées"),
    "ovale": ("ovale", "ovales"),
}
_EXPECTED_FRENCH = {
    "oblong": "PATO_0000946",
    "elliptique": "PATO_0000947",
    "lineaire": "PATO_0001199",
    "lanceole": "PATO_0001877",
    "ovale": "PATO_0001891",
}
_FRENCH_AUTHORITY_KEY = {
    "oblong": "oblong",
    "elliptique": "elliptique",
    "linéaire": "lineaire",
    "lancéolé": "lanceole",
    "ovale": "ovale",
}
_ENGLISH_FORMS = {
    "oblong": "PATO_0000946",
    "elliptic": "PATO_0000947",
    "elliptical": "PATO_0000947",
    "linear": "PATO_0001199",
    "lanceolate": "PATO_0001877",
    "ovate": "PATO_0001891",
}


def _bilingual_forms(
    terminology_path: Path,
    pato_lexicon_path: Path,
) -> dict[tuple[str, str], tuple[str, str]]:
    """Return (language, inflected form) -> (PATO id, evidence locator)."""

    pato_rows: dict[str, dict[str, str]] = {}
    with pato_lexicon_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            pato_rows[str(row.get("id", "") or "")] = row
    for form, identifier in _ENGLISH_FORMS.items():
        row = pato_rows.get(identifier)
        lexical = {
            str(row.get("label", "") or "").casefold(),
            *(value.casefold() for value in str(row.get("synonyms", "") or "").split("|") if value),
        } if row else set()
        if form not in lexical:
            raise ValueError(f"English shape form {form!r} is not bound to {identifier}")

    french_rows: dict[str, dict[str, str]] = {}
    with terminology_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            normalized = str(row.get("normalized_form", "") or "").casefold()
            if (
                row.get("language") == "fr"
                and row.get("source_id") == "english_french_lexicon"
                and normalized in _EXPECTED_FRENCH
                and row.get("target_id") == _EXPECTED_FRENCH[normalized]
                and row.get("mapping_relation") in {"skos:exactMatch", "skos:closeMatch"}
                and float(row.get("mapping_confidence", 0) or 0) >= 0.92
            ):
                if normalized in french_rows:
                    raise ValueError(f"duplicate bilingual glossary mapping for {normalized}")
                french_rows[normalized] = row
    if set(french_rows) != set(_EXPECTED_FRENCH):
        missing = sorted(set(_EXPECTED_FRENCH) - set(french_rows))
        raise ValueError(f"missing required bilingual glossary mappings: {missing}")

    forms: dict[tuple[str, str], tuple[str, str]] = {
        ("en", form): (identifier, f"pato_lexicon:{identifier}")
        for form, identifier in _ENGLISH_FORMS.items()
    }
    for base, inflections in _FRENCH_INFLECTIONS.items():
        authority_key = _FRENCH_AUTHORITY_KEY[base]
        row = french_rows[authority_key]
        identifier = _EXPECTED_FRENCH[authority_key]
        locator = f"botanical_terminology:{row['term_id']}"
        for form in inflections:
            key = ("fr", form.casefold())
            if key in forms and forms[key][0] != identifier:
                raise ValueError(f"conflicting bilingual form mapping: {key}")
            forms[key] = (identifier, locator)
    return forms


def _components(
    text: str, start: int, end: int
) -> tuple[tuple[int, int, str], tuple[int, int, str]] | None:
    token = text[start:end]
    match = _TWO_COMPONENTS.fullmatch(token)
    if match is None:
        return None
    return (
        (start + match.start("left"), start + match.end("left"), match.group("left")),
        (start + match.start("right"), start + match.end("right"), match.group("right")),
    )


def prepare_bilingual_shape_compound_review(
    *,
    stage_path: Path,
    review_input_path: Path,
    candidate_ledger_path: Path,
    span_ledger_path: Path,
    report_path: Path,
    terminology_path: Path = Path("config/botanical_terminology.tsv"),
    po_lexicon_path: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon_path: Path = Path("config/pato_lexicon.tsv"),
    combinations_path: Path = Path("config/valid_combinations.tsv"),
) -> dict[str, Any]:
    """Extract strict one-missing-endpoint candidates and conserve their full scope."""

    paths = (
        stage_path,
        review_input_path,
        candidate_ledger_path,
        span_ledger_path,
        report_path,
        terminology_path,
        po_lexicon_path,
        pato_lexicon_path,
        combinations_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("bilingual shape inputs and outputs must resolve to distinct paths")
    form_map = _bilingual_forms(terminology_path, pato_lexicon_path)
    resolver = BearerResolver(po_lexicon_path)
    pato_ids, pato_attributes = _load_ids(pato_lexicon_path)
    combinations = _load_combinations(combinations_path)
    counts: Counter[str] = Counter()
    candidate_records: list[dict[str, Any]] = []
    candidate_ledger: list[dict[str, Any]] = []
    span_ledger: list[dict[str, Any]] = []
    seen_keys: set[tuple[Any, ...]] = set()

    with stage_path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            text = str(record.get("text", "") or "")
            language = str(record.get("language", "") or "").casefold()
            targets = [
                span
                for span in (record.get("unresolved_spans", []) or [])
                if isinstance(span, dict) and span.get("reason") == TARGET_REASON
            ]
            groups: defaultdict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
            for span in targets:
                _validate_target_span(record, span)
                key = _span_key(record, span)
                if key in seen_keys:
                    raise ValueError(f"duplicate physical target span: {key}")
                seen_keys.add(key)
                groups[_compound_bounds(text, int(span["start"]), int(span["end"]))].append(
                    span
                )

            synthetic_review_spans: list[dict[str, Any]] = []
            for (expression_start, expression_end), members in sorted(groups.items()):
                if len(members) != 1:
                    continue
                real = members[0]
                counts["target_spans"] += 1
                key = _span_key(record, real)
                reason = ""
                candidate = None
                evidence: list[str] = []
                components = _components(text, expression_start, expression_end)
                if language not in {"en", "fr"}:
                    reason = "unsupported_language"
                elif components is None:
                    reason = "not_exactly_two_lexical_components"
                else:
                    mapped = [form_map.get((language, value.casefold())) for _, _, value in components]
                    if any(value is None for value in mapped):
                        reason = "component_not_in_frozen_bilingual_map"
                    else:
                        assert mapped[0] is not None and mapped[1] is not None
                        endpoint_ids = (mapped[0][0], mapped[1][0])
                        evidence = [mapped[0][1], mapped[1][1]]
                        real_start, real_end = int(real["start"]), int(real["end"])
                        matching_components = [
                            index
                            for index, (start, end, _value) in enumerate(components)
                            if start <= real_start and real_end <= end
                            and endpoint_ids[index] == real.get("candidate_pato_id")
                        ]
                        if len(matching_components) != 1:
                            reason = "baseline_span_does_not_match_mapped_component"
                        elif endpoint_ids[0] == endpoint_ids[1] or any(
                            identifier not in GROSS_OUTLINE_VALUES
                            for identifier in endpoint_ids
                        ):
                            reason = "not_two_distinct_gross_outline_values"
                        else:
                            missing_index = 1 - matching_components[0]
                            missing_start, missing_end, missing_text = components[missing_index]
                            synthetic = {
                                "start": missing_start,
                                "end": missing_end,
                                "surface_form": missing_text,
                                "reason": TARGET_REASON,
                                "candidate_pato_id": endpoint_ids[missing_index],
                                "extractor": "frozen_bilingual_glossary_binding",
                            }
                            probe = dict(record)
                            probe["unresolved_spans"] = [
                                *(record.get("unresolved_spans", []) or []),
                                synthetic,
                            ]
                            candidate, reason = _candidate_for_group(
                                probe,
                                [real, synthetic],
                                expression_start,
                                expression_end,
                                resolver=resolver,
                                pato_ids=pato_ids,
                                pato_attributes=pato_attributes,
                                combinations=combinations,
                            )
                            if candidate is not None:
                                candidate = candidate.model_copy(
                                    update={
                                        "clear_unresolved_spans": (
                                            (int(real["start"]), int(real["end"])),
                                        )
                                    }
                                )
                if candidate is None:
                    reason = reason or "candidate_construction_failed"
                    span_ledger.append(
                        {
                            "source": key[0],
                            "source_id": key[1],
                            "source_segment_index": key[2],
                            "taxon": key[3],
                            "start": key[4],
                            "end": key[5],
                            "surface_form": key[6],
                            "candidate_pato_id": key[7],
                            "status": "excluded",
                            "reason": reason,
                            "candidate_id": "",
                        }
                    )
                    counts[f"excluded:{reason}"] += 1
                    continue

                candidate_id = stable_id(
                    "bilshape",
                    (
                        *_segment_key(record),
                        candidate.expression_start,
                        candidate.expression_end,
                        candidate.signature.model_dump(mode="json"),
                    ),
                )
                synthetic_review_spans.append(
                    {
                        "start": candidate.expression_start,
                        "end": candidate.expression_end,
                        "surface_form": candidate.expression_text,
                        "reason": REVIEW_REASON,
                        "candidate_pato_id": SHAPE_ATTRIBUTE,
                        "pending_bearer": candidate.signature.bearer_id,
                        "extractor": EXTRACTOR,
                        "candidate_id": candidate_id,
                        "qualitative_relation_candidate": candidate.model_dump(mode="json"),
                    }
                )
                candidate_ledger.append(
                    {
                        "candidate_id": candidate_id,
                        "source": record.get("source", ""),
                        "source_id": record.get("source_id", ""),
                        "source_segment_index": int(
                            record.get("source_segment_index", 0) or 0
                        ),
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": language,
                        "component_mapping_evidence": evidence,
                        "candidate": candidate.model_dump(mode="json"),
                    }
                )
                span_ledger.append(
                    {
                        "source": key[0],
                        "source_id": key[1],
                        "source_segment_index": key[2],
                        "taxon": key[3],
                        "start": key[4],
                        "end": key[5],
                        "surface_form": key[6],
                        "candidate_pato_id": key[7],
                        "status": "candidate",
                        "reason": REVIEW_REASON,
                        "candidate_id": candidate_id,
                    }
                )
                counts["candidates"] += 1
                counts["candidate_spans"] += 1
                counts[f"candidate_language:{language}"] += 1
                counts[f"candidate_bearer_method:{candidate.bearer_method}"] += 1

            if synthetic_review_spans:
                synthetic_review_spans.sort(key=lambda span: (span["start"], span["end"]))
                candidate_records.append(
                    {
                        "source": record.get("source", ""),
                        "source_id": record.get("source_id", ""),
                        "source_segment_index": int(
                            record.get("source_segment_index", 0) or 0
                        ),
                        "taxon": record.get("taxon", ""),
                        "organ": record.get("organ", ""),
                        "language": record.get("language", ""),
                        "char_start": int(record.get("char_start", 0) or 0),
                        "char_end": int(record.get("char_end", len(text)) or len(text)),
                        "text": text,
                        "assertions": record.get("assertions", []) or [],
                        "term_mentions": record.get("term_mentions", []) or [],
                        "unresolved_spans": synthetic_review_spans,
                    }
                )

    statuses = Counter(row["status"] for row in span_ledger)
    if len(span_ledger) != counts["target_spans"]:
        raise ValueError("bilingual span ledger does not conserve all one-target compounds")
    if counts["candidate_spans"] != counts["candidates"]:
        raise ValueError("every bilingual candidate must clear exactly one current span")
    if statuses["candidate"] + statuses["excluded"] != counts["target_spans"]:
        raise ValueError("bilingual dispositions are not exhaustive")

    candidate_records.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
        )
    )
    candidate_ledger.sort(key=lambda row: row["candidate_id"])
    span_ledger.sort(
        key=lambda row: (
            row["source"],
            row["source_id"],
            row["source_segment_index"],
            row["taxon"],
            row["start"],
            row["end"],
        )
    )
    _write_immutable_rows(review_input_path, candidate_records)
    _write_immutable_rows(candidate_ledger_path, candidate_ledger)
    _write_immutable_rows(span_ledger_path, span_ledger)
    report = {
        "schema_version": "flopo-qualitative-candidate-report-v1",
        "input_scope": f"{TARGET_REASON}:exactly_one_current_component",
        "candidate_kind": REVIEW_REASON,
        "candidates": counts["candidates"],
        "exclusions": statuses["excluded"],
        "target_spans": counts["target_spans"],
        "candidate_spans": statuses["candidate"],
        "conserved": len(span_ledger) == counts["target_spans"],
        "counts": dict(sorted(counts.items())),
        "artifacts": {
            "stage13": sha256_file(stage_path).model_dump(mode="json"),
            "review_input": sha256_file(review_input_path).model_dump(mode="json"),
            "candidate_ledger": sha256_file(candidate_ledger_path).model_dump(mode="json"),
            "span_ledger": sha256_file(span_ledger_path).model_dump(mode="json"),
            "terminology": sha256_file(terminology_path).model_dump(mode="json"),
            "po_lexicon": sha256_file(po_lexicon_path).model_dump(mode="json"),
            "pato_lexicon": sha256_file(pato_lexicon_path).model_dump(mode="json"),
            "combinations": sha256_file(combinations_path).model_dump(mode="json"),
        },
    }
    _write_immutable_report(report_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--review-input", type=Path, required=True)
    parser.add_argument("--candidate-ledger", type=Path, required=True)
    parser.add_argument("--span-ledger", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--terminology", type=Path, default=Path("config/botanical_terminology.tsv")
    )
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument(
        "--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv")
    )
    parser.add_argument(
        "--combinations", type=Path, default=Path("config/valid_combinations.tsv")
    )
    args = parser.parse_args()
    report = prepare_bilingual_shape_compound_review(
        stage_path=args.stage,
        review_input_path=args.review_input,
        candidate_ledger_path=args.candidate_ledger,
        span_ledger_path=args.span_ledger,
        report_path=args.report,
        terminology_path=args.terminology,
        po_lexicon_path=args.po_lexicon,
        pato_lexicon_path=args.pato_lexicon,
        combinations_path=args.combinations,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
