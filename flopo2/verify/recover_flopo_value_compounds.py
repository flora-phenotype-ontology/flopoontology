"""Recover guarded hyphen compounds that exactly denote existing FLOPO value classes.

The residual compound corpus is dominated by intermediate shapes, indument, colour blends,
transitions, and bearer/subregion constructions.  Those are not mechanically decomposed.  This
pass handles only an audited list of whole-token composite-colour values already present in
FLOPO, reusing the conservative source/bearer guards from
``recover_exact_pato_compounds``.  The resulting annotation keeps PATO colour as its trait and the
FLOPO value in ``value_terms``; arbitrary source expressions therefore receive FAC identifiers,
not new FLOPO identifiers.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

from flopo2.extract import baseline
from flopo2.verify import recover_exact_pato_compounds as exact


COLOUR_ATTRIBUTE = "PATO_0000014"
DASHES = "-–—"

# Existing, non-deprecated, reviewed FLOPO composite-colour value classes.  ``white-hairy`` and
# ``green-striped`` are deliberately excluded: in the source corpus they denote indument/pattern
# scope rather than a whole-organ atomic colour.
FLOPO_VALUE_FORMS = {
    "purple brown": "FLOPO_0980381",
    "purplish brown": "FLOPO_0980138",
    "creamy white": "FLOPO_0980098",
    "golden yellow": "FLOPO_0980185",
    "greenish brown": "FLOPO_0980295",
    "creamy yellow": "FLOPO_0980139",
    "creamy green": "FLOPO_0980356",
    "pinkish red": "FLOPO_0980338",
    "reddish green": "FLOPO_0980247",
    "apricot yellow": "FLOPO_0980167",
    "silvery green": "FLOPO_0980407",
    "pinkish green": "FLOPO_0980313",
    "greenish red": "FLOPO_0980336",
}

_PATTERN_NOUN = re.compile(
    r"\b(?:strip(?:e|es|ed|ing|s)|streak\w*|fleck\w*|mottl\w*|spot\w*|blotch\w*|"
    r"band(?:ed|ing|s)?|veined|veins?|nerv\w*|variegat\w*|marbl\w*|marking\w*|"
    r"ray(?:ed|s)?|patch\w*|dot(?:ted|s)?)\b",
    re.IGNORECASE,
)
_WITH_BEFORE = re.compile(r"\b(?:with|avec|à|a)\b", re.IGNORECASE)


def _normal_form(text: str) -> str:
    return re.sub(rf"[\s{re.escape(DASHES)}]+", " ", text.casefold()).strip()


def _pattern_or_subregion_scope(text: str, start: int, end: int) -> bool:
    """Reject a colour that qualifies a stripe/marking rather than the resolved bearer."""

    clause, clause_start = baseline._clause_at(text, start)
    local_end = end - clause_start
    after = clause[local_end : local_end + 60]
    before = clause[max(0, start - clause_start - 40) : start - clause_start]
    if _PATTERN_NOUN.search(after):
        return True
    return bool(_WITH_BEFORE.search(before) and _PATTERN_NOUN.search(after[:80]))


def flopo_value_lexicon(registry: Path) -> dict[str, tuple[str, str]]:
    """Return normalized form -> (FLOPO id, label) for audited live value classes."""

    with Path(registry).open(encoding="utf-8", newline="") as handle:
        by_id = {
            row["flopo_iri"].rsplit("/", 1)[-1]: row
            for row in csv.DictReader(handle, delimiter="\t")
        }
    lexicon: dict[str, tuple[str, str]] = {}
    for form, flopo_id in FLOPO_VALUE_FORMS.items():
        row = by_id.get(flopo_id)
        if row and row.get("deprecated", "0") == "0":
            lexicon[_normal_form(form)] = (flopo_id, row["label"])
    return lexicon


def _restore_spans(recovered: dict, original: dict, start: int, end: int) -> None:
    current = list(recovered.get("unresolved_spans", []) or [])
    seen = {
        (row.get("start"), row.get("end"), row.get("surface_form"), row.get("reason"))
        for row in current
    }
    for row in original.get("unresolved_spans", []) or []:
        if (
            row.get("reason") == "hyphenated_or_slash_compound"
            and int(row.get("start", -1)) < end
            and int(row.get("end", -1)) > start
        ):
            key = (row.get("start"), row.get("end"), row.get("surface_form"), row.get("reason"))
            if key not in seen:
                current.append(dict(row))
                seen.add(key)
    recovered["unresolved_spans"] = sorted(
        current, key=lambda row: (int(row.get("start", 0)), int(row.get("end", 0)))
    )


def recover_record(
    record: dict,
    lexicon: dict[str, tuple[str, str]],
    bearers: exact.BearerResolver,
) -> tuple[dict, Counter[str]]:
    """Recover one record and normalize FLOPO values into the schema's value slot."""

    recovered, outcomes = exact.recover_record(record, lexicon, bearers)
    value_ids = {flopo_id for flopo_id, _label in lexicon.values()}
    text = str(record.get("text", "") or "")
    kept: list[dict] = []
    for assertion in recovered.get("assertions", []) or []:
        flopo_value = assertion.get("pato_id", "")
        is_new = (
            flopo_value in value_ids
            and assertion.get("extractor") == "deterministic_exact_pato_compound_recovery"
        )
        if not is_new:
            kept.append(assertion)
            continue
        start = int(assertion["source_start"])
        end = int(assertion["source_end"])
        if _pattern_or_subregion_scope(text, start, end):
            outcomes["retained:strict_pattern_or_marking_scope"] += 1
            outcomes[f"promoted:{flopo_value}"] -= 1
            outcomes["resolved_evidence_spans"] -= 1
            _restore_spans(recovered, record, start, end)
            continue
        assertion["pato_id"] = COLOUR_ATTRIBUTE
        assertion["value_operator"] = "atomic"
        assertion["value_terms"] = [flopo_value]
        assertion["normalization_status"] = "compositional"
        assertion["extractor"] = "deterministic_flopo_value_compound_recovery"
        assertion["mapping_provenance"] = [
            "existing non-deprecated FLOPO composite-colour value; whole-token exact form; "
            "dash/space normalization only",
            *list(assertion.get("mapping_provenance", []) or [])[1:],
        ]
        kept.append(assertion)
    recovered["assertions"] = kept
    recovered.pop("annotation_extension_iri", None)
    return recovered, outcomes


def recover_file(
    input_path: Path,
    output_path: Path,
    *,
    po_lexicon: Path = Path("config/po_lexicon.tsv"),
    registry: Path = Path("config/flopo_id_registry.tsv"),
) -> dict[str, object]:
    if Path(input_path).resolve() == Path(output_path).resolve():
        raise ValueError("recovery output must be distinct from its input")
    lexicon = flopo_value_lexicon(registry)
    bearers = exact.BearerResolver(po_lexicon)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = 0
    outcomes: Counter[str] = Counter()
    promoted_by_source: Counter[str] = Counter()
    with Path(input_path).open(encoding="utf-8") as source, Path(output_path).open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            recovered, record_outcomes = recover_record(record, lexicon, bearers)
            output.write(json.dumps(recovered, ensure_ascii=False) + "\n")
            records += 1
            outcomes.update(record_outcomes)
            promoted = sum(
                count for key, count in record_outcomes.items() if key.startswith("promoted:")
            )
            if promoted:
                promoted_by_source[str(record.get("source", ""))] += promoted
    return {
        "input": str(input_path),
        "output": str(output_path),
        "records": records,
        "flopo_value_forms": len(lexicon),
        "promoted_by_source": dict(sorted(promoted_by_source.items())),
        "outcomes": dict(sorted(outcomes.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--po-lexicon", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = recover_file(
        args.input,
        args.output,
        po_lexicon=args.po_lexicon,
        registry=args.registry,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
