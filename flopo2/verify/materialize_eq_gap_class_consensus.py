"""Materialize exact-colour EQ classes after complete independent machine review.

Only runner-owned candidates with exact two-family agreement and an independent adversarial
``no_blocker`` verdict receive identifiers.  The output is a standalone OWL module plus an
allocation ledger; it does not mutate the released ontology or claim human curation.

With ``--tiebreak FILE --tiebreak-rule two_of_three`` the materializer instead admits items the
campaign held when a third, family-independent machine reviewer and at least one campaign
reviewer agree exactly (see :mod:`flopo2.review.tiebreak`).  Classes already allocated by an
earlier run are passed with ``--prior-allocations``: their identifiers are reserved, they are not
re-emitted, and new identifiers continue after the highest reserved number.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import (
    CampaignManifest,
    ConsensusDecision,
    EvidenceRecord,
    ProposedSignature,
    ReusableFlopoClassCandidate,
    canonical_json,
)
from flopo2.review.report import campaign_report
from flopo2.review.tiebreak import TIEBREAK_RULES, TiebreakResolution, resolve_tiebreak
from flopo2.review.validation import load_validation_context


MODULE_IRI = "http://purl.obolibrary.org/obo/flopo-machine-reviewed-eq.owl"
ALLOCATION_FIELDS = (
    "proposal_key",
    "flopo_id",
    "label",
    "eq_signature",
    "signature_sha256",
    "campaign_id",
    "item_id",
    "consensus_signature_sha256",
    "reviewer_ids",
    "adjudicator_id",
    "occurrence_count",
)
TIEBREAK_ALLOCATION_FIELDS = (*ALLOCATION_FIELDS, "admission_rule", "curator_override")
ADVERSARIAL_EDITOR_NOTE = (
    "Provisional exact PO-PATO phenotype class admitted by independent machine "
    "review and adversarial validation; occurrence annotations require separate "
    "review and this class is not human reviewed."
)
TIEBREAK_EDITOR_NOTE = (
    "Provisional exact PO-PATO phenotype class admitted under the two-of-three exact "
    "machine-review agreement rule: a third, independent machine reviewer and at least one "
    "campaign reviewer proposed the identical class, and deterministic gates passed; no "
    "adversarial verdict was required. Occurrence annotations require separate review and "
    "this class is not human reviewed."
)
CURATOR_OVERRIDE_EDITOR_NOTE = (
    "Provisional exact PO-PATO phenotype class admitted under the two-of-three exact "
    "machine-review agreement rule. An automated adversarial machine review had blocked this "
    "class; adversary block overridden by {curator_override}. Occurrence annotations "
    "require separate review and this class is not human reviewed."
)


def _write_immutable(path: Path, payload: str, label: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed {label}: {path}")
    atomic_write_text(path, payload)


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"EQ-class candidate artifact hash mismatch: {label}")


def _verify_candidate_report(
    path: Path,
    *,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    registry_path: Path,
) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid EQ-class candidate report {path}: {error}") from error
    if report.get("schema_version") != "flopo-eq-gap-class-candidate-report-v1":
        raise ValueError("unsupported EQ-class candidate report")
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("EQ-class candidate report belongs to another campaign")
    conservation = report.get("conservation", {})
    required = (
        "class_count_matches_source",
        "occurrence_count_matches_source",
        "all_source_memberships_verified",
        "all_candidate_authorities_hash_bound",
    )
    if not all(conservation.get(key) for key in required):
        raise ValueError("EQ-class candidate extraction is not conserved")
    for expected, actual_path, key in (
        (manifest.occurrences, occurrence_path, "occurrences"),
        (manifest.clusters, cluster_path, "clusters"),
        (manifest.evidence_registry, evidence_path, "evidence_registry"),
    ):
        bound = report.get(key, {})
        if (bound.get("sha256"), bound.get("bytes")) != (
            expected.sha256,
            expected.bytes,
        ):
            raise ValueError(f"EQ-class candidate report {key} binding drift")
        _artifact_matches(bound, actual_path, key)
    classes = report.get("source_classes", {})
    if (classes.get("sha256"), classes.get("bytes")) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("EQ-class campaign input does not match source classes")
    source_records = {(row.sha256, row.bytes) for row in manifest.sources}
    report_sources = {
        (
            report[key].get("sha256"),
            report[key].get("bytes"),
        )
        for key in ("source_occurrences", "source_inventory_report")
    }
    if report_sources != source_records:
        raise ValueError("EQ-class source inventory binding drift")
    _artifact_matches(report.get("flopo_registry", {}), registry_path, "FLOPO registry")
    registry_hash = sha256_file(registry_path)
    if (registry_hash.sha256, registry_hash.bytes) not in {
        (row.sha256, row.bytes) for row in manifest.ontologies
    }:
        raise ValueError("EQ-class FLOPO registry is not a frozen ontology input")
    if int(report.get("candidate_classes", -1)) != manifest.starting_clusters:
        raise ValueError("EQ-class candidate count does not match campaign")
    if int(report.get("candidate_occurrences", -1)) != manifest.starting_occurrences:
        raise ValueError("EQ-class occurrence count does not match campaign")
    return report


def _registry_state(path: Path) -> tuple[int, set[str], set[str]]:
    maximum = -1
    identifiers: set[str] = set()
    active_signatures: set[str] = set()
    with path.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle, delimiter="\t"), 2):
            iri = str(row.get("flopo_iri", "") or "").strip()
            raw_number = str(row.get("flopo_num", "") or "").strip()
            signature = str(row.get("signature", "") or "").strip()
            if not iri or not raw_number or not signature:
                raise ValueError(f"{path}:{number}: incomplete registry row")
            try:
                value = int(raw_number)
            except ValueError as error:
                raise ValueError(f"{path}:{number}: invalid flopo_num") from error
            identifier = iri.rsplit("/", 1)[-1]
            if not identifier.startswith("FLOPO_") or identifier in identifiers:
                raise ValueError(f"{path}:{number}: invalid or duplicate FLOPO identifier")
            maximum = max(maximum, value)
            identifiers.add(identifier)
            if str(row.get("deprecated", "") or "").strip() not in {"1", "true", "True"}:
                active_signatures.add(signature)
    return maximum, identifiers, active_signatures


def _prior_allocations(paths: tuple[Path, ...], campaign_id: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in paths:
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if tuple(reader.fieldnames or ())[: len(ALLOCATION_FIELDS)] != ALLOCATION_FIELDS:
                raise ValueError(f"{path}: unsupported EQ allocation ledger schema")
            for row in reader:
                if row["campaign_id"] != campaign_id:
                    raise ValueError(f"{path}: prior allocation belongs to another campaign")
                rows.append(row)
    for key in ("flopo_id", "item_id", "eq_signature"):
        values = [row[key] for row in rows]
        if len(values) != len(set(values)):
            raise ValueError(f"prior allocations repeat {key}")
    return rows


def _literal(value: str, *, language: str | None = None) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    return f"{encoded}@{language}" if language else encoded


def _evidence_locators(path: Path) -> dict[str, str]:
    return {
        row.evidence_id: row.locator
        for row in read_jsonl(path, EvidenceRecord)
        if row.kind == "ontology"
    }


def _module_text(
    allocations: list[dict[str, Any]],
    *,
    release_date: str,
    evidence_locators: dict[str, str],
) -> str:
    lines = [
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix flopoann: <https://w3id.org/flopo/annotation/> .",
        "@prefix obo: <http://purl.obolibrary.org/obo/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{MODULE_IRI}> a owl:Ontology ;",
        "    owl:imports <http://purl.obolibrary.org/obo/po.owl>,",
        "        <http://purl.obolibrary.org/obo/pato.owl> ;",
        f"    dcterms:created {_literal(release_date)}^^xsd:date ;",
        "    dcterms:license <https://creativecommons.org/publicdomain/zero/1.0/> ;",
        f"    rdfs:label {_literal('Machine-reviewed FLOPO exact-colour EQ classes', language='en')} .",
        "",
        "obo:BFO_0000051 a owl:ObjectProperty .",
        "obo:RO_0000053 a owl:ObjectProperty .",
        "obo:IAO_0000115 a owl:AnnotationProperty .",
        "obo:IAO_0000116 a owl:AnnotationProperty .",
        "flopoann:machine_adjudicator a owl:AnnotationProperty .",
        "flopoann:machine_evidence a owl:AnnotationProperty .",
        "flopoann:machine_review_campaign a owl:AnnotationProperty .",
        "flopoann:machine_review_item a owl:AnnotationProperty .",
        "flopoann:machine_review_signature a owl:AnnotationProperty .",
        "flopoann:machine_review_status a owl:AnnotationProperty .",
        "flopoann:machine_reviewer a owl:AnnotationProperty .",
        *(
            ["flopoann:machine_review_rule a owl:AnnotationProperty ."]
            if any(row.get("admission_rule") for row in allocations)
            else []
        ),
        *(
            ["flopoann:curator_override a owl:AnnotationProperty ."]
            if any(row.get("curator_override") for row in allocations)
            else []
        ),
        "",
    ]
    for row in allocations:
        candidate = ReusableFlopoClassCandidate.model_validate(row["candidate"])
        expression = candidate.signature
        predicates = [
            "a owl:Class",
            f"rdfs:label {_literal(candidate.label, language='en')}",
            f"obo:IAO_0000115 {_literal(candidate.definition, language='en')}",
            *(f"rdfs:subClassOf obo:{identifier}" for identifier in candidate.parent_ids),
            (
                "owl:equivalentClass [ a owl:Restriction ; "
                "owl:onProperty obo:BFO_0000051 ; "
                "owl:someValuesFrom [ owl:intersectionOf ( "
                f"obo:{expression.bearer_id} [ a owl:Restriction ; "
                "owl:onProperty obo:RO_0000053 ; "
                f"owl:someValuesFrom obo:{expression.quality_id} ] ) ] ]"
            ),
            f"dcterms:created {_literal(release_date)}^^xsd:date",
            f"flopoann:machine_review_campaign {_literal(row['campaign_id'])}",
            f"flopoann:machine_review_item {_literal(row['item_id'])}",
            f"flopoann:machine_review_signature {_literal(row['consensus_signature_sha256'])}",
            'flopoann:machine_review_status "llm_consensus"',
            *(
                f"flopoann:machine_reviewer {_literal(identifier)}"
                for identifier in row["reviewer_ids"]
            ),
            *(
                [f"flopoann:machine_review_rule {_literal(row['admission_rule'])}"]
                if row.get("admission_rule")
                else [f"flopoann:machine_adjudicator {_literal(row['adjudicator_id'])}"]
            ),
            *(
                f"flopoann:machine_evidence {_literal(identifier)}"
                for identifier in candidate.authoritative_evidence_ids
            ),
            *(
                f"dcterms:source {_literal(evidence_locators[identifier])}"
                for identifier in candidate.authoritative_evidence_ids
                if identifier in evidence_locators
            ),
            *(
                [f"flopoann:curator_override {_literal(row['curator_override'])}"]
                if row.get("curator_override")
                else []
            ),
            (
                "obo:IAO_0000116 "
                + _literal(
                    CURATOR_OVERRIDE_EDITOR_NOTE.format(
                        curator_override=row.get("curator_override")
                    )
                    if row.get("curator_override")
                    else TIEBREAK_EDITOR_NOTE
                    if row.get("admission_rule")
                    else ADVERSARIAL_EDITOR_NOTE,
                    language="en",
                )
            ),
        ]
        lines.append(f"obo:{row['flopo_id']} " + " ;\n    ".join(predicates) + " .")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def materialize_eq_gap_class_consensus(
    *,
    manifest_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    consensus_path: Path,
    ledger_path: Path,
    candidate_report_path: Path,
    flopo_registry_path: Path,
    allocation_path: Path,
    module_path: Path,
    held_path: Path,
    report_path: Path,
    release_date: str,
    tiebreak_path: Path | None = None,
    tiebreak_rule: str | None = None,
    review_paths: tuple[Path, ...] = (),
    adjudication_paths: tuple[Path, ...] = (),
    prior_allocation_paths: tuple[Path, ...] = (),
    curator_overrides: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    date.fromisoformat(release_date)
    if (tiebreak_path is None) != (tiebreak_rule is None):
        raise ValueError("--tiebreak and --tiebreak-rule must be supplied together")
    if tiebreak_rule is not None and tiebreak_rule not in TIEBREAK_RULES:
        raise ValueError(f"unsupported tie-break rule: {tiebreak_rule}")
    if prior_allocation_paths and tiebreak_path is None:
        raise ValueError("prior allocations are only meaningful for a tie-break run")
    if curator_overrides and tiebreak_path is None:
        raise ValueError("curator overrides are only meaningful for a tie-break run")
    paths = (
        manifest_path,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
        candidate_report_path,
        flopo_registry_path,
        allocation_path,
        module_path,
        held_path,
        report_path,
        *((tiebreak_path,) if tiebreak_path is not None else ()),
        *review_paths,
        *adjudication_paths,
        *prior_allocation_paths,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("EQ-class materialization inputs and outputs must be distinct")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidate_report = _verify_candidate_report(
        candidate_report_path,
        manifest=manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
        registry_path=flopo_registry_path,
    )
    review_report = campaign_report(
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
        consensus_path,
        ledger_path,
    )
    if not review_report["ok"]:
        raise ValueError("EQ-class review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    tiebreak: TiebreakResolution | None = None
    if tiebreak_path is not None and tiebreak_rule is not None:
        tiebreak = resolve_tiebreak(
            tiebreak_path=tiebreak_path,
            rule=tiebreak_rule,
            manifest=manifest,
            context=context,
            base_decisions=decisions,
            review_paths=review_paths,
            adjudication_paths=adjudication_paths,
            admissible_dispositions=frozenset({"reusable_flopo_class"}),
            curator_overrides=curator_overrides,
        )
    prior = _prior_allocations(prior_allocation_paths, manifest.campaign_id)
    prior_items = {row["item_id"] for row in prior}
    accepted: list[tuple[ConsensusDecision, ReusableFlopoClassCandidate]] = []
    held: list[dict[str, Any]] = []
    prior_occurrences = 0
    for item_id, cluster in sorted(context.clusters.items()):
        candidate = cluster.reusable_flopo_class_candidate
        if candidate is None:
            raise ValueError(f"{item_id}: EQ-class campaign item has no runner candidate")
        decision = decisions[item_id]
        base_actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "reusable_flopo_class"
            and decision.validation_passed
            and decision.adjudicator_id is not None
        )
        if prior:
            if base_actionable != (item_id in prior_items):
                raise ValueError(f"{item_id}: prior allocations do not match campaign consensus")
            if base_actionable:
                prior_occurrences += candidate.occurrence_count
                continue
        actionable = base_actionable
        if tiebreak is not None and item_id in tiebreak.admitted:
            decision = tiebreak.admitted[item_id]
            actionable = True
        if actionable:
            signature = ProposedSignature.model_validate_json(
                decision.normalized_signature or ""
            )
            if (
                signature.kind != "reusable_flopo_class"
                or signature.expression != candidate.signature
                or signature.label != candidate.label
                or signature.definition != candidate.definition
                or signature.parent_ids != candidate.parent_ids
                or signature.authoritative_evidence_ids
                != candidate.authoritative_evidence_ids
            ):
                raise ValueError(f"{item_id}: EQ-class consensus signature drift")
            accepted.append((decision, candidate))
        else:
            held.append(
                {
                    "campaign_id": manifest.campaign_id,
                    "item_id": item_id,
                    "proposal_key": candidate.proposal_key,
                    "occurrence_count": candidate.occurrence_count,
                    "candidate": candidate.model_dump(mode="json"),
                    "consensus": decision.model_dump(mode="json", exclude_none=True),
                }
            )

    maximum, existing_ids, active_signatures = _registry_state(flopo_registry_path)
    for row in prior:
        existing_ids.add(row["flopo_id"])
        active_signatures.add(row["eq_signature"])
        maximum = max(maximum, int(row["flopo_id"].split("_", 1)[1]))
    allocations: list[dict[str, Any]] = []
    for offset, (decision, candidate) in enumerate(
        sorted(accepted, key=lambda row: row[1].proposal_key), 1
    ):
        expression = candidate.signature
        eq_signature = f"EQ|{expression.bearer_id}|{expression.quality_id}"
        if eq_signature in active_signatures:
            raise ValueError(f"accepted EQ signature is no longer missing: {eq_signature}")
        flopo_id = f"FLOPO_{maximum + offset:07d}"
        if flopo_id in existing_ids:
            raise ValueError(f"allocated identifier already exists: {flopo_id}")
        allocations.append(
            {
                "proposal_key": candidate.proposal_key,
                "flopo_id": flopo_id,
                "label": candidate.label,
                "eq_signature": eq_signature,
                "signature_sha256": hashlib.sha256(
                    canonical_json(candidate.model_dump(mode="json")).encode()
                ).hexdigest(),
                "campaign_id": decision.campaign_id,
                "item_id": decision.item_id,
                "consensus_signature_sha256": decision.signature_sha256,
                "reviewer_ids": list(decision.reviewer_ids),
                "adjudicator_id": decision.adjudicator_id,
                "occurrence_count": candidate.occurrence_count,
                "candidate": candidate.model_dump(mode="json"),
                **(
                    {"admission_rule": decision.reasons[0]}
                    if decision.adjudicator_id is None
                    else {}
                ),
                **(
                    {
                        "curator_override": next(
                            reason.split(":", 1)[1]
                            for reason in decision.reasons
                            if reason.startswith("curator_override_adversarial_block:")
                        )
                    }
                    if any(
                        reason.startswith("curator_override_adversarial_block:")
                        for reason in decision.reasons
                    )
                    else {}
                ),
            }
        )

    fields = TIEBREAK_ALLOCATION_FIELDS if tiebreak is not None else ALLOCATION_FIELDS
    allocation_lines = ["\t".join(fields)]
    for row in allocations:
        allocation_lines.append(
            "\t".join(
                "|".join(row[field])
                if field == "reviewer_ids"
                else str(row.get(field) or "")
                for field in fields
            )
        )
    _write_immutable(allocation_path, "\n".join(allocation_lines) + "\n", "EQ allocation ledger")
    _write_immutable(
        module_path,
        _module_text(
            allocations,
            release_date=release_date,
            evidence_locators=_evidence_locators(evidence_path),
        ),
        "EQ-class OWL module",
    )
    _write_immutable(
        held_path,
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in held),
        "EQ-class held ledger",
    )
    result = {
        "schema_version": "flopo-eq-class-consensus-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "starting_classes": manifest.starting_clusters,
        "starting_occurrences": manifest.starting_occurrences,
        "accepted_classes": len(allocations),
        "accepted_candidate_occurrences": sum(row["occurrence_count"] for row in allocations),
        "held_classes": len(held),
        "held_candidate_occurrences": sum(row["occurrence_count"] for row in held),
        "class_conserved": len(allocations) + len(held) + len(prior)
        == manifest.starting_clusters,
        "occurrence_conserved": (
            sum(row["occurrence_count"] for row in allocations)
            + sum(row["occurrence_count"] for row in held)
            + prior_occurrences
            == manifest.starting_occurrences
        ),
        "occurrence_annotations_admitted": 0,
        "review_report": review_report,
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "candidate_inventory": {
            "bearer_parent_fallbacks": candidate_report["bearer_parent_fallbacks"],
            "duplicate_active_parent_signatures": candidate_report[
                "duplicate_active_parent_signatures"
            ],
        },
        "artifacts": {
            "allocations": sha256_file(allocation_path).model_dump(mode="json"),
            "module": sha256_file(module_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry_path).model_dump(mode="json"),
        },
    }
    if tiebreak is not None:
        result["prior_allocated_classes"] = len(prior)
        result["prior_allocated_candidate_occurrences"] = prior_occurrences
        result["tiebreak"] = {
            **tiebreak.summary(),
            "tiebreak_file": sha256_file(tiebreak_path).model_dump(mode="json"),
            "reviews": [sha256_file(path).model_dump(mode="json") for path in review_paths],
            "adjudications": [
                sha256_file(path).model_dump(mode="json") for path in adjudication_paths
            ],
            "prior_allocations": [
                sha256_file(path).model_dump(mode="json") for path in prior_allocation_paths
            ],
            "reviewer_ids": sorted(
                {identifier for row in allocations for identifier in row["reviewer_ids"]}
            ),
            "held_items": {item: list(reasons) for item, reasons in sorted(tiebreak.held.items())},
        }
    _write_immutable(
        report_path,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "EQ-class materialization report",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--consensus", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--candidate-report", type=Path, required=True)
    parser.add_argument("--flopo-registry", type=Path, required=True)
    parser.add_argument("--allocations", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--tiebreak", type=Path, default=None)
    parser.add_argument("--tiebreak-rule", choices=sorted(TIEBREAK_RULES), default=None)
    parser.add_argument("--review", type=Path, action="append", default=[])
    parser.add_argument("--adjudication", type=Path, action="append", default=[])
    parser.add_argument("--prior-allocations", type=Path, action="append", default=[])
    parser.add_argument(
        "--curator-override",
        metavar="ITEM_ID=NOTE",
        action="append",
        default=[],
        help=(
            "Admit ITEM_ID despite an existing adversarial block, recording NOTE (e.g. "
            "'curator 2026-09-18') as the override provenance. Repeatable. Only meaningful "
            "with --tiebreak; every other deterministic gate still applies."
        ),
    )
    args = parser.parse_args()
    curator_overrides: dict[str, str] = {}
    for entry in args.curator_override:
        item_id, sep, note = entry.partition("=")
        if not sep or not item_id or not note:
            raise SystemExit(f"--curator-override must be ITEM_ID=NOTE, got: {entry!r}")
        if item_id in curator_overrides:
            raise SystemExit(f"--curator-override repeats item_id: {item_id}")
        curator_overrides[item_id] = note
    result = materialize_eq_gap_class_consensus(
        manifest_path=args.manifest,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        consensus_path=args.consensus,
        ledger_path=args.ledger,
        candidate_report_path=args.candidate_report,
        flopo_registry_path=args.flopo_registry,
        allocation_path=args.allocations,
        module_path=args.module,
        held_path=args.held,
        report_path=args.report,
        release_date=args.date,
        tiebreak_path=args.tiebreak,
        tiebreak_rule=args.tiebreak_rule,
        review_paths=tuple(args.review),
        adjudication_paths=tuple(args.adjudication),
        prior_allocation_paths=tuple(args.prior_allocations),
        curator_overrides=curator_overrides,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
