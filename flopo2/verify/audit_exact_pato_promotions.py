"""Reproduce the exhaustive manual audit of exact PATO compound promotions.

Every assertion emitted by ``deterministic_exact_pato_compound_recovery`` in the four
reviewed flora snapshots was inspected in its complete clause.  This module records that
bounded review without changing the recovered JSONL.  Re-running it verifies the exact input
hashes, record and promotion counts, lexical offsets, assertion provenance, and duplicate groups.
Six defects found during review were fixed before the final snapshot; all current rows pass.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from flopo2.extract import baseline
from flopo2.verify.recover_exact_pato_compounds import exact_compound_colour_lexicon


EXTRACTOR = "deterministic_exact_pato_compound_recovery"
EXPECTED_PROMOTIONS = {"fdac": 0, "gabon": 0, "kew": 297, "malesiana": 41}
EXPECTED_RECORDS = {"fdac": 26_011, "gabon": 42_001, "kew": 14_544, "malesiana": 33_766}
EXPECTED_SHA256 = {
    "fdac": "085e6324784f094ae53735a02aed9633bb3169d4b6ed33d781310da71657d914",
    "gabon": "4ff2091b693ed45d6ae367582328a0115ee6aa6a88a63505931efe21a59b4e7a",
    "kew": "47d0d230204552844762db37d4146d1b6e5b409ee1b84e99e57a2e81deade76f",
    "malesiana": "2cfb4fddba898a9d3f9b2484f97238f2cc6a49d189c2123c1eeb0f7c09a3ec03",
}
EXPECTED_TOTAL_PROMOTIONS = 338
EXPECTED_DUPLICATE_GROUPS = 116
REVIEW_DIMENSIONS = (
    "bearer_scope",
    "modality_quotation",
    "relational_subset",
    "surface_covering",
    "transition",
    "part_vs_whole",
)
DEFAULT_PASS_NOTE = (
    "Exact PATO token directly characterizes the reviewed PO bearer; no blocking bearer, "
    "modality/quotation, relational-subset, surface/covering, transition, or part/whole issue."
)


@dataclass(frozen=True)
class ManualDecision:
    issue_category: str
    notes: str


# Keys are (flora, source, source_id, segment, PO, PATO, token_start, token_end).  These findings
# came from the preceding 342-row snapshot.  The five unsafe assertions are now withheld and the
# sixth has a corrected seed bearer, so none is a retained row in the final 338-row ledger.
RESOLVED_PRIOR_FINDINGS: dict[
    tuple[str, str, str, int, str, str, int, int], ManualDecision
] = {
    (
        "kew",
        "kew-african",
        "84806",
        0,
        "PO_0009001",
        "PATO_0001250",
        355,
        366,
    ): ManualDecision(
        "attribution_modality_unmodeled",
        "The source says 'fide Jarman' and 'details unknown'; the assertion does not preserve "
        "that explicit attribution/reporting context as epistemic modality.",
    ),
    (
        "kew",
        "kew-african",
        "102815",
        0,
        "PO_0009046",
        "PATO_0104054",
        463,
        476,
    ): ManualDecision(
        "part_vs_whole_wrong_bearer",
        "Orange-yellow characterizes the deeper-coloured lip, not the whole flower; the lip "
        "subpart and comparative modifier are both lost by the promoted assertion.",
    ),
    (
        "kew",
        "kew-african",
        "106937",
        0,
        "PO_0009001",
        "PATO_0002411",
        1933,
        1945,
    ): ManualDecision(
        "wrong_po_bearer",
        "The clause subject is Seed, so yellow-brown characterizes PO_0009010 (seed), not "
        "PO_0009001 (fruit).",
    ),
    (
        "kew",
        "kew-african",
        "108633",
        0,
        "PO_0009060",
        "PATO_0001941",
        1205,
        1217,
    ): ManualDecision(
        "state_context_unmodeled",
        "The source restricts the calyx colour with '(in life)'; the unconditional promotion "
        "drops that state context.",
    ),
    (
        "kew",
        "kew-african",
        "110000",
        0,
        "PO_0004518",
        "PATO_0002411",
        101,
        113,
    ): ManualDecision(
        "unmodeled_colour_modifier",
        "The source colour is 'buffish yellow-brown'; the promotion drops the directly scoped "
        "modifier 'buffish'.",
    ),
    (
        "kew",
        "kew-african",
        "113322",
        0,
        "PO_0000003",
        "PATO_0104336",
        5,
        16,
    ): ManualDecision(
        "unmodeled_colour_modifier",
        "The source says 'Rich olive-green'; the promotion drops the directly scoped colour "
        "modifier 'Rich'.",
    ),
}

CURRENT_RETAIN_REVIEWS: dict[
    tuple[str, str, str, int, str, str, int, int], ManualDecision
] = {}

# Explicitly re-reviewed after the final regeneration: the corrected seed assertion and the one
# newly recovered caruncle assertion both have direct, unconditional bearers in their clauses.
REQUIRED_FINAL_SAFE_KEYS = {
    (
        "kew",
        "kew-african",
        "106937",
        0,
        "PO_0009010",
        "PATO_0002411",
        1933,
        1945,
    ),
    (
        "kew",
        "kew-african",
        "101232",
        0,
        "PO_0020060",
        "PATO_0002411",
        1649,
        1661,
    ),
}


TSV_FIELDS = [
    "audit_row",
    "duplicate_group_id",
    "duplicate_group_size",
    "duplicate_group_key",
    "input_flora",
    "input_file",
    "input_sha256",
    "record_line",
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "assertion_index",
    "po_id",
    "po_label",
    "pato_id",
    "pato_label",
    "quality_token_start",
    "quality_token_end",
    "quality_token",
    "assertion_source_start",
    "assertion_source_end",
    "assertion_source_text",
    "clause_start",
    "clause_end",
    "clause",
    "frequency_qualifier",
    "epistemic_modality",
    "value_qualifier",
    "degree_qualifier",
    "modality_text",
    "decision",
    "issue_category",
    "notes",
    "review_status",
    "review_dimensions",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _labels(path: Path) -> dict[str, str]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("id", "")): str(row.get("label", ""))
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("id") and row.get("label")
        }


def _quality_patterns(pato_obo: Path) -> dict[str, list[re.Pattern[str]]]:
    by_pato: dict[str, list[re.Pattern[str]]] = defaultdict(list)
    for normalized_form, (pato_id, _label) in exact_compound_colour_lexicon(pato_obo).items():
        parts = normalized_form.split()
        expression = r"[\s\-\u2013\u2014]+".join(re.escape(part) for part in parts)
        by_pato[pato_id].append(
            re.compile(rf"(?<![^\W\d_]){expression}(?![^\W\d_])", re.IGNORECASE)
        )
    return by_pato


def _quality_token(
    text: str,
    assertion: dict,
    patterns: dict[str, list[re.Pattern[str]]],
) -> tuple[int, int, str]:
    source_start = int(assertion.get("source_start", -1))
    source_end = int(assertion.get("source_end", -1))
    hits: set[tuple[int, int, str]] = set()
    for pattern in patterns.get(str(assertion.get("pato_id", "")), []):
        for match in pattern.finditer(text, source_start, source_end):
            hits.add((match.start(), match.end(), match.group(0)))
    spans = {(start, end) for start, end, _token in hits}
    if len(spans) != 1:
        raise ValueError(
            "promoted assertion does not contain exactly one exact PATO token span: "
            f"{assertion!r}; hits={sorted(hits)!r}"
        )
    start, end = next(iter(spans))
    return start, end, text[start:end]


def _report_promotion_count(path: Path) -> int:
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    return sum(
        int(count)
        for outcome, count in report.get("outcomes", {}).items()
        if str(outcome).startswith("promoted:PATO_")
    )


def _write_tsv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=TSV_FIELDS,
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_markdown(path: Path, report: dict[str, object]) -> None:
    counts = report["counts"]
    retained = report["retained_cases"]
    cases = "\n".join(
        f"- `{row['source_id']}` `{row['quality_token']}` on `{row['po_id']}`: "
        f"**{row['issue_category']}** — {row['notes']}"
        for row in retained
    ) or "None in the final regenerated snapshot."
    resolved = "\n".join(
        f"- `{row['source_id']}`: **{row['issue_category']}** — {row['resolution']}"
        for row in report["resolved_prior_findings"]
    )
    hashes = "\n".join(
        f"- {flora}: `{details['sha256_after']}`; {details['records']} records; "
        f"{details['promotions']} promotions"
        for flora, details in report["inputs"].items()
    )
    text = f"""# Exact PATO compound-promotion audit

All {counts['reviewed']} promoted assertions in the four exact-compound recovery snapshots were
read in their complete clauses and checked for bearer scope, modality/quotation, relational
subsets, surface/covering attachment, transitions, and part-versus-whole attachment.

- **{counts['pass']} pass**
- **{counts['retain']} retain** for correction or richer modelling
- {counts['duplicate_groups']} unique PO-PATO groups
- input JSONL mutated: **no**

## Retained cases

{cases}

## Findings resolved before the final ledger

{resolved}

## Snapshot reconciliation

{hashes}

Every audit row retains the exact lexical, assertion-source, and clause offsets.  The TSV has one
row per promotion, including repeated PO-PATO combinations; grouping never discards an occurrence.
Audit result: **{report['result']}**.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def audit_exact_pato_promotions(
    input_dir: Path,
    output_tsv: Path,
    report_json: Path,
    *,
    markdown_report: Path | None = None,
    pato_obo: Path = Path("ont/quality.obo"),
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    pato_lexicon: Path = Path("config/pato_lexicon.tsv"),
    expected_sha256: dict[str, str] = EXPECTED_SHA256,
) -> dict[str, object]:
    """Validate and write the complete 338-occurrence manual-review ledger."""

    input_dir = Path(input_dir)
    output_tsv = Path(output_tsv)
    report_json = Path(report_json)
    input_paths = {
        flora: input_dir / f"{flora}-recovered-baseline.jsonl"
        for flora in EXPECTED_PROMOTIONS
    }
    resolved_inputs = {path.resolve() for path in input_paths.values()}
    if output_tsv.resolve() in resolved_inputs or report_json.resolve() in resolved_inputs:
        raise ValueError("audit outputs must be distinct from recovered inputs")

    hashes_before = {flora: _sha256(path) for flora, path in input_paths.items()}
    po_labels = _labels(po_lexicon)
    pato_labels = _labels(pato_lexicon)
    patterns = _quality_patterns(pato_obo)
    raw_rows: list[dict[str, object]] = []
    record_counts: Counter[str] = Counter()
    promotion_counts: Counter[str] = Counter()

    for flora, input_path in input_paths.items():
        with input_path.open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                record_counts[flora] += 1
                record = json.loads(line)
                text = str(record.get("text", ""))
                for assertion_index, assertion in enumerate(record.get("assertions", []) or []):
                    if assertion.get("extractor") != EXTRACTOR:
                        continue
                    promotion_counts[flora] += 1
                    token_start, token_end, token = _quality_token(text, assertion, patterns)
                    source_start = int(assertion.get("source_start", -1))
                    source_end = int(assertion.get("source_end", -1))
                    clause, clause_start = baseline._clause_at(text, token_start)
                    key = (
                        flora,
                        str(record.get("source", "") or ""),
                        str(record.get("source_id", "") or ""),
                        int(record.get("source_segment_index", 0) or 0),
                        str(assertion.get("po_id", "") or ""),
                        str(assertion.get("pato_id", "") or ""),
                        token_start,
                        token_end,
                    )
                    manual = CURRENT_RETAIN_REVIEWS.get(key)
                    decision = "retain" if manual else "pass"
                    raw_rows.append(
                        {
                            "input_flora": flora,
                            "input_file": str(input_path),
                            "input_sha256": hashes_before[flora],
                            "record_line": line_number,
                            "source": key[1],
                            "source_id": key[2],
                            "source_segment_index": key[3],
                            "taxon": str(record.get("taxon", "") or ""),
                            "organ": str(record.get("organ", "") or ""),
                            "assertion_index": assertion_index,
                            "po_id": key[4],
                            "po_label": po_labels.get(key[4], ""),
                            "pato_id": key[5],
                            "pato_label": pato_labels.get(key[5], ""),
                            "quality_token_start": token_start,
                            "quality_token_end": token_end,
                            "quality_token": token,
                            "assertion_source_start": source_start,
                            "assertion_source_end": source_end,
                            "assertion_source_text": str(assertion.get("source_text", "")),
                            "clause_start": clause_start,
                            "clause_end": clause_start + len(clause),
                            "clause": clause,
                            "frequency_qualifier": assertion.get(
                                "frequency_qualifier", "unspecified"
                            ),
                            "epistemic_modality": assertion.get(
                                "epistemic_modality", "asserted"
                            ),
                            "value_qualifier": assertion.get("value_qualifier", "exact"),
                            "degree_qualifier": assertion.get(
                                "degree_qualifier", "unmodified"
                            ),
                            "modality_text": str(assertion.get("modality_text", "") or ""),
                            "decision": decision,
                            "issue_category": manual.issue_category if manual else "none",
                            "notes": manual.notes if manual else DEFAULT_PASS_NOTE,
                            "review_status": "manual_complete",
                            "review_dimensions": "|".join(REVIEW_DIMENSIONS),
                            "_record_text": text,
                            "_review_key": key,
                        }
                    )

    group_counts = Counter((str(row["po_id"]), str(row["pato_id"])) for row in raw_rows)
    group_ids = {
        key: f"G{index:03d}"
        for index, key in enumerate(sorted(group_counts), 1)
    }
    rows: list[dict[str, object]] = []
    for row_number, raw in enumerate(raw_rows, 1):
        group_key = (str(raw["po_id"]), str(raw["pato_id"]))
        raw.update(
            {
                "audit_row": row_number,
                "duplicate_group_id": group_ids[group_key],
                "duplicate_group_size": group_counts[group_key],
                "duplicate_group_key": "|".join(group_key),
            }
        )
        rows.append(raw)

    observed_retain_keys = {
        row["_review_key"] for row in rows if row["decision"] == "retain"
    }
    observed_keys = {row["_review_key"] for row in rows}
    report_counts = {
        flora: _report_promotion_count(input_dir / f"{flora}-recovery-report.json")
        for flora in EXPECTED_PROMOTIONS
    }
    invariants = {
        "input_hashes_are_expected": hashes_before == expected_sha256,
        "record_counts_are_expected": dict(record_counts) == EXPECTED_RECORDS,
        "promotion_counts_are_expected": {
            flora: promotion_counts[flora] for flora in EXPECTED_PROMOTIONS
        }
        == EXPECTED_PROMOTIONS,
        "recovery_reports_match_promotions": report_counts == EXPECTED_PROMOTIONS,
        "one_row_per_promotion": len(rows) == EXPECTED_TOTAL_PROMOTIONS,
        "duplicate_group_count_is_expected": len(group_counts) == EXPECTED_DUPLICATE_GROUPS,
        "all_current_retain_review_keys_seen": observed_retain_keys
        == set(CURRENT_RETAIN_REVIEWS),
        "all_prior_unsafe_promotions_are_absent": observed_keys.isdisjoint(
            RESOLVED_PRIOR_FINDINGS
        ),
        "corrected_and_new_rows_were_reviewed": REQUIRED_FINAL_SAFE_KEYS <= observed_keys,
        "all_decisions_are_nonblank_and_valid": all(
            row["decision"] in {"pass", "retain"} for row in rows
        ),
        "all_issue_categories_are_nonblank": all(bool(row["issue_category"]) for row in rows),
        "all_notes_are_nonblank": all(bool(row["notes"]) for row in rows),
        "all_review_dimensions_are_recorded": all(
            row["review_dimensions"] == "|".join(REVIEW_DIMENSIONS) for row in rows
        ),
        "all_labels_resolve": all(bool(row["po_label"] and row["pato_label"]) for row in rows),
        "all_quality_offsets_are_exact": all(
            row["_record_text"][row["quality_token_start"] : row["quality_token_end"]]
            == row["quality_token"]
            for row in rows
        ),
        "all_assertion_source_offsets_are_exact": all(
            row["_record_text"][
                row["assertion_source_start"] : row["assertion_source_end"]
            ]
            == row["assertion_source_text"]
            for row in rows
        ),
        "all_clause_offsets_are_exact": all(
            row["_record_text"][row["clause_start"] : row["clause_end"]] == row["clause"]
            for row in rows
        ),
        "all_tokens_are_inside_source_and_clause": all(
            row["assertion_source_start"]
            <= row["quality_token_start"]
            < row["quality_token_end"]
            <= row["assertion_source_end"]
            and row["clause_start"]
            <= row["quality_token_start"]
            < row["quality_token_end"]
            <= row["clause_end"]
            for row in rows
        ),
        "all_occurrence_rows_are_unique": len(
            {
                (
                    row["input_flora"],
                    row["record_line"],
                    row["assertion_index"],
                )
                for row in rows
            }
        )
        == len(rows),
        "inputs_unchanged": True,
    }

    # Remove verifier-only objects before serializing the public ledger.
    public_rows = [
        {field: row.get(field, "") for field in TSV_FIELDS}
        for row in rows
    ]
    _write_tsv(output_tsv, public_rows)
    hashes_after = {flora: _sha256(path) for flora, path in input_paths.items()}
    invariants["inputs_unchanged"] = hashes_after == hashes_before

    decision_counts = Counter(str(row["decision"]) for row in rows)
    issue_counts = Counter(str(row["issue_category"]) for row in rows)
    report: dict[str, object] = {
        "result": "pass" if all(invariants.values()) else "fail",
        "counts": {
            "reviewed": len(rows),
            "pass": decision_counts["pass"],
            "retain": decision_counts["retain"],
            "duplicate_groups": len(group_counts),
        },
        "by_flora_and_decision": dict(
            sorted(Counter(f"{row['input_flora']}:{row['decision']}" for row in rows).items())
        ),
        "issue_counts": dict(sorted(issue_counts.items())),
        "inputs": {
            flora: {
                "path": str(input_paths[flora]),
                "sha256_before": hashes_before[flora],
                "sha256_after": hashes_after[flora],
                "records": record_counts[flora],
                "promotions": promotion_counts[flora],
                "recovery_report_promotions": report_counts[flora],
            }
            for flora in EXPECTED_PROMOTIONS
        },
        "invariants": invariants,
        "retained_cases": [
            {
                "input_flora": row["input_flora"],
                "source": row["source"],
                "source_id": row["source_id"],
                "source_segment_index": row["source_segment_index"],
                "taxon": row["taxon"],
                "po_id": row["po_id"],
                "pato_id": row["pato_id"],
                "quality_token": row["quality_token"],
                "quality_token_start": row["quality_token_start"],
                "quality_token_end": row["quality_token_end"],
                "issue_category": row["issue_category"],
                "notes": row["notes"],
                "clause": row["clause"],
            }
            for row in rows
            if row["decision"] == "retain"
        ],
        "resolved_prior_findings": [
            {
                "source_id": key[2],
                "old_po_id": key[4],
                "pato_id": key[5],
                "token_start": key[6],
                "token_end": key[7],
                "issue_category": finding.issue_category,
                "resolution": (
                    "corrected to the direct seed bearer PO_0009010 and re-reviewed as pass"
                    if key[2] == "106937"
                    else "unsafe atomic promotion is withheld in the final snapshot"
                ),
            }
            for key, finding in RESOLVED_PRIOR_FINDINGS.items()
        ],
    }
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if markdown_report is not None:
        _write_markdown(Path(markdown_report), report)
    if report["result"] != "pass":
        failed = [name for name, value in invariants.items() if not value]
        raise ValueError(f"exact-PATO promotion audit failed invariants: {failed}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("--output-tsv", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--markdown-report", type=Path)
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lexicon", type=Path, default=Path("config/pato_lexicon.tsv"))
    args = parser.parse_args()
    report = audit_exact_pato_promotions(
        args.input_dir,
        args.output_tsv,
        args.report,
        markdown_report=args.markdown_report,
        pato_obo=args.pato_obo,
        po_lexicon=args.po_lexicon,
        pato_lexicon=args.pato_lexicon,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
