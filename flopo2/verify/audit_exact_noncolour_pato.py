"""Manually reviewed audit of two exact non-colour whole-token PATO forms.

The compound inventory contains 28 occurrences of ``lanceolate-triangular`` and
``semi-erect``.  Both strings denote existing atomic PATO classes, but lexical identity is
not enough to make a flora assertion: the complete clause must support one exact PO bearer
and the token must not be an operand of an alternative/range, negated, temporal, relative,
or attached to an unsupported subpart.

This module makes the bounded manual review reproducible.  It reads the untouched canonical
JSONL, validates every reviewed offset and decision, and writes only isolated audit and
integration-proposal artifacts.  It never edits the canonical input and never mints a FLOPO
identifier.  Safe proposals receive the stable FAC identifier of their OWL class expression;
an already existing FLOPO class is recorded as a separate normalization target when present.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from flopo2.annotation.provenance import stable_statement_id
from flopo2.extract import baseline
from flopo2.owl.annotation_class import (
    annotation_class_iri,
    canonical_signature_json,
)


EXPECTED_CANONICAL_SHA256 = "b51e68716e0ef77a1ea8e0318d38d3d6cc09c564cf602008ea22b4745f0c0f40"
EXPECTED_CANONICAL_ROWS = 116_322
EXPECTED_TARGET_ROWS = 28
EXTRACTOR = "manual_exact_noncolour_pato_audit_20260718"

TARGET_PATOS = {
    "lanceolate-triangular": "PATO_0002338",
    "semi-erect": "PATO_0002260",
}


@dataclass(frozen=True)
class Review:
    """One human decision, keyed to an exact source occurrence."""

    disposition: str
    reason: str
    po_id: str
    bearer_surface: str
    bearer_start: int
    bearer_end: int
    bearer_relation: str
    context_flags: tuple[str, ...]
    rationale: str


def _review(
    disposition: str,
    reason: str,
    *,
    po_id: str = "",
    bearer_surface: str = "",
    bearer_start: int = -1,
    bearer_end: int = -1,
    bearer_relation: str = "missing",
    flags: tuple[str, ...] = (),
    rationale: str,
) -> Review:
    return Review(
        disposition,
        reason,
        po_id,
        bearer_surface,
        bearer_start,
        bearer_end,
        bearer_relation,
        flags,
        rationale,
    )


# These decisions were made by reading every complete clause in the canonical source.  Keys are
# (whole token, source_id, token start).  A superclass bearer is allowed only for a defensible
# is-a normalization (lateral sepal -> sepal).  A part-of relation is never generalized (for
# example bract limb -> bract or corolla lobe -> corolla).
REVIEWS: dict[tuple[str, str, int], Review] = {
    ("semi-erect", "83051", 2): _review(
        "reject",
        "coordinated_alternative_list",
        po_id="PO_0000003",
        bearer_surface="herb",
        bearer_start=123,
        bearer_end=127,
        bearer_relation="exact_lexical_bearer",
        flags=("coordinate_alternative_list",),
        rationale=(
            "The whole-plant bearer is explicit, but semi-erect is one member of the "
            "coordinated semi-erect/decumbent/prostrate growth-form alternatives."
        ),
    ),
    ("semi-erect", "84202", 31): _review(
        "reject",
        "modal_alternative",
        po_id="PO_0000003",
        bearer_surface="shrub",
        bearer_start=42,
        bearer_end=47,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative", "frequency_modality:rarely"),
        rationale=(
            "Semi-erect is a rarely occurring alternative to scrambling or climbing, not an "
            "unqualified atomic whole-plant assertion."
        ),
    ),
    ("lanceolate-triangular", "84249", 262): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0020041",
        bearer_surface="Stipules",
        bearer_start=244,
        bearer_end=252,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale=(
            "The exact stipule bearer is present, but lanceolate-triangular is contrasted with "
            "oblong-triangular for the larger stipules by an explicit 'or'."
        ),
    ),
    ("lanceolate-triangular", "85166", 1067): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="lobes",
        bearer_start=1061,
        bearer_end=1066,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The quality inheres in unnamed lobes.  No exact PO lobe bearer is available and a "
            "lobe cannot be generalized by part-of to an unstated whole organ."
        ),
    ),
    ("lanceolate-triangular", "85306", 915): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0009055",
        bearer_surface="bracts",
        bearer_start=880,
        bearer_end=886,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale=(
            "The exact bract bearer is present, but the source says broadly ovate-triangular or "
            "lanceolate-triangular."
        ),
    ),
    ("lanceolate-triangular", "85310", 112): _review(
        "safe_atomic",
        "accepted_exact_bearer",
        po_id="PO_0009055",
        bearer_surface="bracts",
        bearer_start=105,
        bearer_end=111,
        bearer_relation="exact_lexical_bearer",
        rationale=(
            "Lanceolate-triangular directly characterizes the explicit bracts; the later "
            "pedicel is only the object of an insertion relation."
        ),
    ),
    ("lanceolate-triangular", "85328", 586): _review(
        "safe_atomic",
        "accepted_exact_bearer",
        po_id="PO_0009055",
        bearer_surface="bracts",
        bearer_start=579,
        bearer_end=585,
        bearer_relation="exact_lexical_bearer",
        rationale="Lanceolate-triangular directly and unconditionally characterizes the bracts.",
    ),
    ("semi-erect", "85334", 19): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0000003",
        bearer_surface="shrub",
        bearer_start=42,
        bearer_end=47,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale="Semi-erect is explicitly stated as an alternative to scandent for the shrub.",
    ),
    ("semi-erect", "87439", 27): _review(
        "reject",
        "missing_exact_po_bearer",
        flags=("missing_exact_po_bearer",),
        rationale=(
            "The clause calls the taxon a semi-erect perennial but contains no explicit PO "
            "anatomical bearer; 'perennial' is a life-history characterization, not a bearer."
        ),
    ),
    ("lanceolate-triangular", "88496", 437): _review(
        "safe_atomic",
        "accepted_exact_bearer",
        po_id="PO_0020041",
        bearer_surface="stipules",
        bearer_start=428,
        bearer_end=436,
        bearer_relation="exact_lexical_bearer",
        rationale="Lanceolate-triangular directly and unconditionally characterizes the stipules.",
    ),
    ("lanceolate-triangular", "89628", 1394): _review(
        "reject",
        "missing_exact_po_bearer",
        bearer_surface="rostellum",
        bearer_start=1384,
        bearer_end=1393,
        bearer_relation="unmapped_structure_not_generalizable",
        flags=("missing_exact_po_bearer", "different_nearby_structure"),
        rationale=(
            "The quality applies to the rostellum, for which this PO vocabulary has no exact "
            "bearer.  The preceding stigma is a different structure and cannot receive it."
        ),
    ),
    ("lanceolate-triangular", "92902", 455): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="lobes",
        bearer_start=439,
        bearer_end=444,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The quality applies to four unnamed lobes.  A part-of inference to an unstated "
            "whole floral organ would not identify the actual bearer."
        ),
    ),
    ("lanceolate-triangular", "97052", 889): _review(
        "safe_atomic",
        "accepted_sound_is_a_superclass_bearer",
        po_id="PO_0009031",
        bearer_surface="Lateral sepals",
        bearer_start=874,
        bearer_end=888,
        bearer_relation="sound_is_a_superclass",
        rationale=(
            "A lateral sepal is a sepal, so PO:0009031 is a sound is-a superclass bearer.  The "
            "exact qualified source phrase is retained.  This is unlike a lobe-to-whole-organ "
            "part-of generalization, which is rejected."
        ),
    ),
    ("lanceolate-triangular", "97138", 1060): _review(
        "reject",
        "qualitative_range",
        po_id="PO_0009055",
        bearer_surface="Bracts",
        bearer_start=1053,
        bearer_end=1059,
        bearer_relation="exact_lexical_bearer",
        flags=("to_range",),
        rationale=(
            "The exact bract bearer is present, but lanceolate-triangular is an endpoint of the "
            "qualitative range 'lanceolate-triangular to subulate'."
        ),
    ),
    ("semi-erect", "99317", 58): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0004542",
        bearer_surface="rhizome",
        bearer_start=69,
        bearer_end=76,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale="The rhizome is explicitly described as creeping or semi-erect.",
    ),
    ("lanceolate-triangular", "104614", 448): _review(
        "safe_atomic",
        "accepted_exact_bearer",
        po_id="PO_0020041",
        bearer_surface="stipules",
        bearer_start=439,
        bearer_end=447,
        bearer_relation="exact_lexical_bearer",
        rationale="Lanceolate-triangular directly and unconditionally characterizes the stipules.",
    ),
    ("lanceolate-triangular", "104673", 922): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="lobes",
        bearer_start=916,
        bearer_end=921,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The bearer is an unnamed lobe.  It cannot be replaced with a whole floral organ "
            "through part-of generalization."
        ),
    ),
    ("lanceolate-triangular", "105687", 772): _review(
        "reject",
        "unsupported_subpart_and_relative_comparison",
        bearer_surface="upper lobes",
        bearer_start=752,
        bearer_end=763,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer", "relative_comparison"),
        rationale=(
            "The quality applies to upper lobes with no exact PO bearer, and the clause also "
            "contains the relative statement 'longer than the tube'.  Neither licenses a "
            "whole-organ assertion."
        ),
    ),
    ("lanceolate-triangular", "106497", 981): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="mid-lobe",
        bearer_start=953,
        bearer_end=961,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The exact bearer is a mid-lobe, not its containing organ; part-of cannot be used "
            "as an is-a bearer normalization."
        ),
    ),
    ("lanceolate-triangular", "108705", 933): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="lobes",
        bearer_start=915,
        bearer_end=920,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The shape applies to unnamed lobes.  The later phrase 'in dry state' modifies "
            "venation and is not used to rescue or reject the shape; the missing lobe bearer is "
            "independently decisive."
        ),
    ),
    ("lanceolate-triangular", "110282", 707): _review(
        "reject",
        "qualitative_range_and_unsupported_subpart",
        bearer_surface="lobes",
        bearer_start=678,
        bearer_end=683,
        bearer_relation="part_of_not_generalizable",
        flags=("to_range", "unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "Lanceolate-triangular is an endpoint of 'narrowly triangular to "
            "lanceolate-triangular', and the bearer is an unsupported lobe."
        ),
    ),
    ("lanceolate-triangular", "112409", 465): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="limb",
        bearer_start=487,
        bearer_end=491,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The quality directly characterizes the bract's limb, not the bract.  Although the "
            "bract (PO:0009055) is explicit, a limb is part of it rather than a subtype, so the "
            "quality must not be generalized to the bract."
        ),
    ),
    ("lanceolate-triangular", "113125", 507): _review(
        "reject",
        "ambiguous_narrow_synonym_bearer",
        bearer_surface="lower and middle pinnae",
        bearer_start=474,
        bearer_end=497,
        bearer_relation="ambiguous_narrow_synonym_not_generalizable",
        flags=("qualified_bearer_subset", "ambiguous_narrow_po_synonym"),
        rationale=(
            "PO lists pinna/pinnae only as NARROW synonyms of leaflet.  In this fern the pinnae "
            "are themselves divided, so treating them as unqualified leaflets is not a sound "
            "exact-bearer normalization; the lower/middle subset is also explicit."
        ),
    ),
    ("lanceolate-triangular", "113175", 788): _review(
        "reject",
        "unsupported_subpart_bearer",
        bearer_surface="lobes",
        bearer_start=782,
        bearer_end=787,
        bearer_relation="part_of_not_generalizable",
        flags=("unsupported_subpart", "missing_exact_po_bearer"),
        rationale=(
            "The quality applies to lobes of deeply pinnatifid pinnae.  Those lobes cannot be "
            "replaced by the pinna or leaf through a part-of generalization."
        ),
    ),
    ("semi-erect", "114598", 57): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0000003",
        bearer_surface="herb",
        bearer_start=15,
        bearer_end=19,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative", "alternative_bearer_wording"),
        rationale=(
            "The visible herb bearer maps to whole plant (and the source also offers subshrub), "
            "but the growth form itself is explicitly 'erect or semi-erect'."
        ),
    ),
    ("semi-erect", "118217", 67): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0009047",
        bearer_surface="stems",
        bearer_start=52,
        bearer_end=57,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale="The stems are explicitly described as erect or semi-erect.",
    ),
    ("semi-erect", "118219", 90): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0009047",
        bearer_surface="stems",
        bearer_start=75,
        bearer_end=80,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale="The stems are explicitly described as erect or semi-erect.",
    ),
    ("semi-erect", "118532", 10): _review(
        "reject",
        "explicit_alternative",
        po_id="PO_0000003",
        bearer_surface="shrub",
        bearer_start=33,
        bearer_end=38,
        bearer_relation="exact_lexical_bearer",
        flags=("explicit_alternative",),
        rationale="Semi-erect is explicitly stated as an alternative to scandent for the shrub.",
    ),
}


TSV_FIELDS = [
    "row_number",
    "canonical_line_number",
    "compound",
    "pato_id",
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "language",
    "token_start",
    "token_end",
    "token_text",
    "token_exact",
    "document_start",
    "document_end",
    "clause_start",
    "clause_end",
    "clause",
    "po_id",
    "bearer_surface",
    "bearer_start",
    "bearer_end",
    "bearer_relation",
    "context_flags",
    "disposition",
    "reason",
    "manual_review",
    "decision_rationale",
    "integration_disposition",
    "requires_applier",
    "applier_status",
    "proposed_source_statement_id",
    "proposed_value_operator",
    "proposed_po_id",
    "proposed_pato_id",
    "proposed_source_start",
    "proposed_source_end",
    "proposed_source_text",
    "phenotype_class_iri",
    "existing_flopo_iri",
]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_id_sort(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)


def _load_targets(path: Path) -> list[dict]:
    rows = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            compound = str(row.get("compound", "") or "").casefold()
            if compound in TARGET_PATOS:
                row["compound"] = compound
                rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            _source_id_sort(str(row.get("source_id", ""))),
            int(row.get("offset", [-1])[0]),
            str(row.get("compound", "")),
        ),
    )


def _load_canonical(path: Path, target_keys: set[tuple[str, str]]) -> tuple[int, dict]:
    records: dict[tuple[str, str], list[tuple[int, dict]]] = defaultdict(list)
    row_count = 0
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row_count += 1
            record = json.loads(line)
            key = (str(record.get("source", "") or ""), str(record.get("source_id", "") or ""))
            if key in target_keys:
                records[key].append((line_number, record))
    return row_count, records


def _load_flopo_signatures(path: Path) -> dict[str, str]:
    if not Path(path).exists():
        return {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("signature", "") or ""): str(row.get("flopo_iri", "") or "")
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("signature") and row.get("flopo_iri")
        }


def _functional_expression(po_id: str, pato_id: str) -> str:
    obo = "http://purl.obolibrary.org/obo/"
    return (
        "ObjectIntersectionOf("
        "<http://semanticscience.org/resource/SIO_010056> "
        f"ObjectSomeValuesFrom(<{obo}BFO_0000051> ObjectIntersectionOf(<{obo}{po_id}> "
        f"ObjectSomeValuesFrom(<{obo}RO_0000053> <{obo}{pato_id}>))))"
    )


def _proposal(
    record: dict,
    review: Review,
    compound: str,
    start: int,
    end: int,
    clause: str,
    clause_start: int,
    flopo_signatures: dict[str, str],
) -> dict:
    pato_id = TARGET_PATOS[compound]
    statement_id = stable_statement_id(record, start, end, compound)
    assertion = {
        "po_id": review.po_id,
        "pato_id": pato_id,
        "negated": False,
        "organ": str(record.get("organ", "") or ""),
        "source_text": compound,
        "source_start": start,
        "source_end": end,
        "extractor": EXTRACTOR,
        "value_operator": "atomic",
        "value_terms": [],
        "normalization_status": "reviewed",
        "mapping_provenance": [
            f"exact whole-token PATO match: {compound} -> {pato_id}",
            (
                f"{review.bearer_relation}: {review.bearer_surface} "
                f"[{review.bearer_start},{review.bearer_end}) -> {review.po_id}"
            ),
        ],
        "source_statement_id": statement_id,
        "frequency_qualifier": "unspecified",
        "epistemic_modality": "asserted",
        "value_qualifier": "exact",
        "degree_qualifier": "unmodified",
        "modality_text": "",
        "season_contexts": [],
        "season_operator": "atomic",
    }
    assertion["phenotype_class_iri"] = annotation_class_iri(assertion)
    signature = f"EQ|{review.po_id}|{pato_id}"
    return {
        "source": str(record.get("source", "") or ""),
        "source_id": str(record.get("source_id", "") or ""),
        "source_segment_index": record.get("source_segment_index", 0),
        "taxon": str(record.get("taxon", "") or ""),
        "language": str(record.get("language", "") or ""),
        "source_statement": {
            "statement_id": statement_id,
            "verbatim_text": compound,
            "start": start,
            "end": end,
            "document_start": int(record.get("char_start", 0) or 0) + start,
            "document_end": int(record.get("char_start", 0) or 0) + end,
            "language": str(record.get("language", "") or ""),
        },
        "source_context": {
            "verbatim_text": clause,
            "start": clause_start,
            "end": clause_start + len(clause),
        },
        "assertion": assertion,
        "canonical_expression_signature": json.loads(canonical_signature_json(assertion)),
        "functional_class_expression": _functional_expression(review.po_id, pato_id),
        "flopo_signature": signature,
        "existing_flopo_iri": flopo_signatures.get(signature, ""),
        "flopo_status": (
            "existing_reusable_class"
            if signature in flopo_signatures
            else "missing_reusable_combination_requires_separate_review"
        ),
    }


def _write_tsv(path: Path, rows: Iterable[dict]) -> None:
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


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_markdown(path: Path, report: dict) -> None:
    counts = report["counts"]
    text = f"""# Exact non-colour PATO audit

All {counts['reviewed']} occurrences of the two exact whole-token forms were manually reviewed
against the untouched canonical JSONL.  Five occurrences are safe atomic assertions and 23 are
rejected.  No ``semi-erect`` occurrence is safe; all five safe rows are
``lanceolate-triangular``.

## Safe integration proposals

- 5 source assertions
- {counts['safe_unique_expressions']} distinct FAC annotation class expressions
- {counts['safe_existing_flopo_occurrences']} occurrences normalize to an existing FLOPO class
- {counts['safe_missing_flopo_occurrences']} occurrences have a reusable PO-PATO combination not
  currently present in the FLOPO registry; this audit proposes them for separate FLOPO review but
  does not mint identifiers
- all 5 safe rows are **not applied** and require a separate canonical-data applier

The safe bearer normalizations are exact lexical matches except for *lateral sepal* ->
``PO_0009031`` (*sepal*), which is a sound is-a superclass normalization.  No part-of subpart was
generalized to a whole organ.

## Validation

- canonical rows: {report['canonical']['rows']}
- canonical SHA-256: ``{report['canonical']['sha256_after']}``
- canonical unchanged during audit: {str(report['invariants']['canonical_unchanged']).lower()}
- result: **{report['result']}**

The decision TSV retains the exact token, complete clause, bearer offsets, context blockers, and
manual rationale for every row.  The proposal JSONL contains only the five safe assertions, their
stable source-statement IDs, FAC IRIs, OWL class expressions, and existing-FLOPO normalization
where one already exists.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def audit_exact_noncolour_pato(
    compound_spans: Path,
    canonical_jsonl: Path,
    decisions_tsv: Path,
    proposals_jsonl: Path,
    report_json: Path,
    *,
    markdown_report: Path | None = None,
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    expected_canonical_sha256: str = EXPECTED_CANONICAL_SHA256,
    expected_canonical_rows: int = EXPECTED_CANONICAL_ROWS,
) -> dict:
    """Validate the complete bounded review and write isolated audit artifacts."""

    compound_spans = Path(compound_spans)
    canonical_jsonl = Path(canonical_jsonl)
    hash_before = _sha256(canonical_jsonl)
    targets = _load_targets(compound_spans)
    target_keys = {
        (str(row.get("source", "") or ""), str(row.get("source_id", "") or ""))
        for row in targets
    }
    canonical_rows, canonical = _load_canonical(canonical_jsonl, target_keys)
    flopo_signatures = _load_flopo_signatures(flopo_registry)

    invariants = {
        "canonical_hash_is_expected": hash_before == expected_canonical_sha256,
        "canonical_row_count_is_expected": canonical_rows == expected_canonical_rows,
        "target_occurrence_count_is_28": len(targets) == EXPECTED_TARGET_ROWS,
        "manual_review_keys_match_targets": True,
        "target_forms_have_expected_pato": True,
        "each_target_has_one_canonical_record": True,
        "all_token_offsets_are_exact": True,
        "all_clauses_retain_exact_token": True,
        "all_bearer_offsets_are_exact": True,
        "all_safe_rows_have_supported_po_bearer": True,
        "safe_rows_have_no_context_blocker": True,
        "rejected_rows_have_context_blocker_or_missing_bearer": True,
        "only_safe_rows_have_proposals": True,
        "all_safe_proposals_satisfy_trait_assertion_schema": True,
        "all_source_statement_offsets_are_exact": True,
        "all_annotation_ids_are_outside_flopo_namespace": True,
        "no_flopo_ids_minted": True,
        "canonical_unchanged": True,
    }
    observed_review_keys = {
        (
            str(row.get("compound", "") or ""),
            str(row.get("source_id", "") or ""),
            int(row.get("offset", [-1])[0]),
        )
        for row in targets
    }
    invariants["manual_review_keys_match_targets"] = observed_review_keys == set(REVIEWS)

    decision_rows: list[dict] = []
    proposals: list[dict] = []
    for row_number, target in enumerate(targets, 1):
        compound = str(target["compound"])
        source_id = str(target.get("source_id", "") or "")
        start, end = (int(value) for value in target.get("offset", [-1, -1]))
        key = (compound, source_id, start)
        review = REVIEWS.get(key)
        if review is None:
            raise ValueError(f"target occurrence lacks manual review: {key!r}")
        pato_id = TARGET_PATOS[compound]
        if target.get("mapped_pato_id") not in (None, "", pato_id):
            invariants["target_forms_have_expected_pato"] = False

        candidate_records = []
        for line_number, record in canonical.get(
            (str(target.get("source", "") or ""), source_id), []
        ):
            text = str(record.get("text", "") or "")
            if 0 <= start <= end <= len(text) and text[start:end].casefold() == compound:
                candidate_records.append((line_number, record))
        if len(candidate_records) != 1:
            invariants["each_target_has_one_canonical_record"] = False
            raise ValueError(f"target does not resolve to exactly one canonical record: {key!r}")
        line_number, record = candidate_records[0]
        text = str(record.get("text", "") or "")
        token = text[start:end]
        token_exact = token == compound
        invariants["all_token_offsets_are_exact"] &= token_exact
        clause, clause_start = baseline._clause_at(text, start)
        clause_end = clause_start + len(clause)
        invariants["all_clauses_retain_exact_token"] &= (
            clause_start <= start <= end <= clause_end
            and clause[start - clause_start : end - clause_start] == token
        )

        if review.bearer_surface:
            bearer_exact = (
                0 <= review.bearer_start <= review.bearer_end <= len(text)
                and text[review.bearer_start : review.bearer_end] == review.bearer_surface
            )
            invariants["all_bearer_offsets_are_exact"] &= bearer_exact
        else:
            invariants["all_bearer_offsets_are_exact"] &= (
                review.bearer_start == -1 and review.bearer_end == -1
            )

        is_safe = review.disposition == "safe_atomic"
        invariants["all_safe_rows_have_supported_po_bearer"] &= (
            not is_safe
            or (
                bool(review.po_id)
                and review.bearer_relation
                in {"exact_lexical_bearer", "sound_is_a_superclass"}
            )
        )
        invariants["safe_rows_have_no_context_blocker"] &= not is_safe or not review.context_flags
        invariants["rejected_rows_have_context_blocker_or_missing_bearer"] &= (
            is_safe or bool(review.context_flags) or not review.po_id
        )

        proposal = None
        if is_safe:
            proposal = _proposal(
                record,
                review,
                compound,
                start,
                end,
                clause,
                clause_start,
                flopo_signatures,
            )
            proposals.append(proposal)
            try:
                # Use the same wire-to-LinkML adapter as the canonical data-model validator.
                from flopo2.verify.data_model import _pydantic_assertion

                _pydantic_assertion(proposal["assertion"])
            except Exception:
                invariants["all_safe_proposals_satisfy_trait_assertion_schema"] = False
            statement = proposal["source_statement"]
            invariants["all_source_statement_offsets_are_exact"] &= (
                text[statement["start"] : statement["end"]] == statement["verbatim_text"]
            )
            class_iri = proposal["assertion"]["phenotype_class_iri"]
            invariants["all_annotation_ids_are_outside_flopo_namespace"] &= (
                class_iri.startswith("https://w3id.org/flopo/annotation-class/FAC_")
                and "FLOPO_" not in class_iri
            )

        decision_rows.append(
            {
                "row_number": row_number,
                "canonical_line_number": line_number,
                "compound": compound,
                "pato_id": pato_id,
                "source": str(record.get("source", "") or ""),
                "source_id": source_id,
                "source_segment_index": record.get("source_segment_index", 0),
                "taxon": str(record.get("taxon", "") or ""),
                "organ": str(record.get("organ", "") or ""),
                "language": str(record.get("language", "") or ""),
                "token_start": start,
                "token_end": end,
                "token_text": token,
                "token_exact": str(token_exact).lower(),
                "document_start": int(record.get("char_start", 0) or 0) + start,
                "document_end": int(record.get("char_start", 0) or 0) + end,
                "clause_start": clause_start,
                "clause_end": clause_end,
                "clause": clause,
                "po_id": review.po_id,
                "bearer_surface": review.bearer_surface,
                "bearer_start": review.bearer_start if review.bearer_start >= 0 else "",
                "bearer_end": review.bearer_end if review.bearer_end >= 0 else "",
                "bearer_relation": review.bearer_relation,
                "context_flags": "|".join(review.context_flags),
                "disposition": review.disposition,
                "reason": review.reason,
                "manual_review": "reviewed",
                "decision_rationale": review.rationale,
                "integration_disposition": (
                    "safe_for_applier" if proposal else "review_rejected"
                ),
                "requires_applier": "true" if proposal else "false",
                "applier_status": "not_applied" if proposal else "not_applicable",
                "proposed_source_statement_id": (
                    proposal["source_statement"]["statement_id"] if proposal else ""
                ),
                "proposed_value_operator": "atomic" if proposal else "",
                "proposed_po_id": review.po_id if proposal else "",
                "proposed_pato_id": pato_id if proposal else "",
                "proposed_source_start": start if proposal else "",
                "proposed_source_end": end if proposal else "",
                "proposed_source_text": token if proposal else "",
                "phenotype_class_iri": (
                    proposal["assertion"]["phenotype_class_iri"] if proposal else ""
                ),
                "existing_flopo_iri": proposal["existing_flopo_iri"] if proposal else "",
            }
        )

    invariants["only_safe_rows_have_proposals"] = len(proposals) == sum(
        row["disposition"] == "safe_atomic" for row in decision_rows
    )
    hash_after = _sha256(canonical_jsonl)
    invariants["canonical_unchanged"] = hash_before == hash_after

    dispositions = Counter(row["disposition"] for row in decision_rows)
    by_form = Counter(
        f"{row['compound']}:{row['disposition']}" for row in decision_rows
    )
    rejection_reasons = Counter(
        row["reason"] for row in decision_rows if row["disposition"] == "reject"
    )
    safe_expression_iris = {
        proposal["assertion"]["phenotype_class_iri"] for proposal in proposals
    }
    safe_signatures = Counter(proposal["flopo_signature"] for proposal in proposals)
    existing_occurrences = sum(bool(proposal["existing_flopo_iri"]) for proposal in proposals)
    report = {
        "inputs": {
            "compound_spans": str(compound_spans),
            "canonical_jsonl": str(canonical_jsonl),
            "flopo_registry": str(flopo_registry),
        },
        "outputs": {
            "decisions_tsv": str(decisions_tsv),
            "proposals_jsonl": str(proposals_jsonl),
            "report_json": str(report_json),
            "markdown_report": str(markdown_report) if markdown_report else "",
        },
        "canonical": {
            "expected_rows": expected_canonical_rows,
            "rows": canonical_rows,
            "expected_sha256": expected_canonical_sha256,
            "sha256_before": hash_before,
            "sha256_after": hash_after,
        },
        "target_mapping": TARGET_PATOS,
        "counts": {
            "reviewed": len(decision_rows),
            "safe_atomic": dispositions["safe_atomic"],
            "rejected": dispositions["reject"],
            "safe_unique_expressions": len(safe_expression_iris),
            "safe_unique_po_pato_signatures": len(safe_signatures),
            "safe_existing_flopo_occurrences": existing_occurrences,
            "safe_missing_flopo_occurrences": len(proposals) - existing_occurrences,
            "safe_existing_flopo_signatures": len(
                {
                    proposal["flopo_signature"]
                    for proposal in proposals
                    if proposal["existing_flopo_iri"]
                }
            ),
            "safe_missing_flopo_signatures": len(
                {
                    proposal["flopo_signature"]
                    for proposal in proposals
                    if not proposal["existing_flopo_iri"]
                }
            ),
        },
        "by_form_and_disposition": dict(sorted(by_form.items())),
        "rejection_reasons": dict(sorted(rejection_reasons.items())),
        "safe_po_pato_signatures": dict(sorted(safe_signatures.items())),
        "safe_fac_iris": sorted(safe_expression_iris),
        "missing_reusable_flopo_signatures_for_separate_review": sorted(
            {
                proposal["flopo_signature"]
                for proposal in proposals
                if not proposal["existing_flopo_iri"]
            }
        ),
        "manual_review_policy": {
            "sound_is_a_superclass_allowed": True,
            "part_of_generalization_allowed": False,
            "all_rows_manually_reviewed": True,
        },
        "integration": {
            "canonical_mutated": False,
            "safe_rows_require_applier": bool(proposals),
            "safe_rows_applied": 0,
            "safe_rows_waiting_for_applier": len(proposals),
            "rejected_rows_must_not_be_applied": dispositions["reject"],
        },
        "invariants": invariants,
        "result": "pass" if all(invariants.values()) else "fail",
    }

    _write_tsv(decisions_tsv, decision_rows)
    _write_jsonl(proposals_jsonl, proposals)
    report_json.parent.mkdir(parents=True, exist_ok=True)
    report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if markdown_report is not None:
        _write_markdown(markdown_report, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compound_spans", type=Path)
    parser.add_argument("canonical_jsonl", type=Path)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--proposals", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--markdown-report", type=Path)
    parser.add_argument("--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--expected-canonical-sha256", default=EXPECTED_CANONICAL_SHA256)
    parser.add_argument("--expected-canonical-rows", type=int, default=EXPECTED_CANONICAL_ROWS)
    args = parser.parse_args()
    report = audit_exact_noncolour_pato(
        args.compound_spans,
        args.canonical_jsonl,
        args.decisions,
        args.proposals,
        args.report,
        markdown_report=args.markdown_report,
        flopo_registry=args.flopo_registry,
        expected_canonical_sha256=args.expected_canonical_sha256,
        expected_canonical_rows=args.expected_canonical_rows,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
