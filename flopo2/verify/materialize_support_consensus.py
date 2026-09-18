"""Materialize independently reviewed FLOPO-local anatomy classes into an OWL module.

Only complete, conserved campaigns with exact two-family agreement and an independent adversarial
``no_blocker`` verdict are actionable.  Identifiers are allocated by the runner after consensus;
models can neither choose nor reserve an identifier.  The generated module records machine review
provenance explicitly and never assigns human review status, a curator, or an ORCID.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from flopo2.review.io import atomic_write_text, read_jsonl, sha256_file
from flopo2.review.models import (
    CampaignManifest,
    ConsensusDecision,
    ProposedSignature,
    SupportClassCandidate,
    canonical_json,
)
from flopo2.review.report import campaign_report
from flopo2.review.validation import load_validation_context


MODULE_IRI = "http://purl.obolibrary.org/obo/flopo-machine-reviewed-support.owl"
OBO = "http://purl.obolibrary.org/obo/"


def _write_immutable(path: Path, payload: str, label: str) -> None:
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(f"refusing to replace changed {label}: {path}")
    atomic_write_text(path, payload)


def _artifact_matches(record: dict[str, Any], path: Path, label: str) -> None:
    actual = sha256_file(path)
    if (actual.sha256, actual.bytes) != (record.get("sha256"), record.get("bytes")):
        raise ValueError(f"support candidate artifact hash mismatch: {label}")


def _verify_candidate_report(
    path: Path,
    manifest: CampaignManifest,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
) -> dict[str, Any]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid support candidate report {path}: {error}") from error
    if report.get("schema_version") != "flopo-support-class-candidate-report-v1":
        raise ValueError("unsupported support candidate report")
    conservation = report.get("conservation", {})
    if not all(
        conservation.get(key)
        for key in (
            "eligible_plus_excluded_equals_local_proposals",
            "occurrence_counts_match_group_inventory",
            "all_authority_files_hash_verified",
        )
    ):
        raise ValueError("support candidate extraction is not conserved")
    if report.get("campaign_id") != manifest.campaign_id:
        raise ValueError("support candidate report belongs to another campaign")
    _artifact_matches(report["curation"], Path(manifest.input.path), "curation")
    if (report["curation"]["sha256"], report["curation"]["bytes"]) != (
        manifest.input.sha256,
        manifest.input.bytes,
    ):
        raise ValueError("support campaign input does not match candidate curation")
    for expected, actual_path, key in (
        (manifest.occurrences, occurrence_path, "occurrences"),
        (manifest.clusters, cluster_path, "clusters"),
        (manifest.evidence_registry, evidence_path, "evidence_registry"),
    ):
        if (report[key]["sha256"], report[key]["bytes"]) != (
            expected.sha256,
            expected.bytes,
        ):
            raise ValueError(f"support candidate report {key} binding drift")
        _artifact_matches(report[key], actual_path, key)
    source_rows = {
        (row.path, row.sha256, row.bytes) for row in manifest.sources
    }
    report_sources = {
        (
            report[key]["path"],
            report[key]["sha256"],
            report[key]["bytes"],
        )
        for key in ("bearer_occurrences", "evidence_map", "evidence_catalog")
    }
    if report_sources != source_rows:
        raise ValueError("support candidate source inventory binding drift")
    if int(report.get("eligible_classes", -1)) != manifest.starting_clusters:
        raise ValueError("support candidate class count does not match campaign")
    if int(report.get("eligible_occurrences", -1)) != manifest.starting_occurrences:
        raise ValueError("support candidate occurrence count does not match campaign")
    return report


def _load_evidence_urls(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get("evidence_id", "") or "").strip(): str(row.get("url", "") or "").strip()
            for row in csv.DictReader(handle, delimiter="\t")
        }


def _max_flopo_number(registry_path: Path) -> tuple[int, set[str]]:
    maximum = -1
    identifiers: set[str] = set()
    with registry_path.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle, delimiter="\t"), 2):
            iri = str(row.get("flopo_iri", "") or "").strip()
            raw_number = str(row.get("flopo_num", "") or "").strip()
            if not iri or not raw_number:
                raise ValueError(f"{registry_path}:{number}: incomplete registry row")
            try:
                value = int(raw_number)
            except ValueError as error:
                raise ValueError(f"{registry_path}:{number}: invalid flopo_num") from error
            maximum = max(maximum, value)
            identifiers.add(iri.rsplit("/", 1)[-1])
    return maximum, identifiers


def _literal(value: str, *, language: str | None = None) -> str:
    encoded = json.dumps(value, ensure_ascii=False)
    return f"{encoded}@{language}" if language else encoded


def _module_text(
    allocations: list[dict[str, Any]],
    *,
    release_date: str,
    evidence_urls: dict[str, str],
) -> str:
    lines = [
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix obo: <http://purl.obolibrary.org/obo/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix flopoann: <https://w3id.org/flopo/annotation/> .",
        "",
        f"<{MODULE_IRI}> a owl:Ontology ;",
        "    owl:imports <http://purl.obolibrary.org/obo/po.owl> ;",
        f"    dcterms:created {_literal(release_date)}^^xsd:date ;",
        "    dcterms:license <https://creativecommons.org/publicdomain/zero/1.0/> ;",
        f"    rdfs:label {_literal('Machine-reviewed FLOPO anatomy support classes', language='en')} .",
        "",
        "obo:BFO_0000050 a owl:ObjectProperty .",
        "obo:IAO_0000115 a owl:AnnotationProperty .",
        "obo:IAO_0000116 a owl:AnnotationProperty .",
        "flopoann:machine_review_campaign a owl:AnnotationProperty .",
        "flopoann:machine_review_item a owl:AnnotationProperty .",
        "flopoann:machine_review_signature a owl:AnnotationProperty .",
        "flopoann:machine_review_status a owl:AnnotationProperty .",
        "flopoann:machine_reviewer a owl:AnnotationProperty .",
        "flopoann:machine_adjudicator a owl:AnnotationProperty .",
        "",
    ]
    for row in allocations:
        candidate = SupportClassCandidate.model_validate(row["candidate"])
        signature = candidate.signature
        subject = f"obo:{row['flopo_id']}"
        predicates = [
            "a owl:Class",
            f"rdfs:label {_literal(signature.label, language='en')}",
            f"obo:IAO_0000115 {_literal(signature.definition, language='en')}",
            *(
                f"rdfs:subClassOf obo:{identifier}" for identifier in signature.parent_ids
            ),
            *(
                "rdfs:subClassOf [ a owl:Restriction ; "
                f"owl:onProperty obo:BFO_0000050 ; owl:someValuesFrom obo:{identifier} ]"
                for identifier in signature.part_of_ids
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
            f"flopoann:machine_adjudicator {_literal(row['adjudicator_id'])}",
            (
                "obo:IAO_0000116 "
                + _literal(
                    "Provisional FLOPO-local anatomy bridge admitted by independent machine "
                    "review and adversarial validation; not human reviewed.",
                    language="en",
                )
            ),
        ]
        for evidence_id in candidate.source_register_ids:
            url = evidence_urls.get(evidence_id, "")
            if url:
                predicates.append(f"dcterms:source <{url}>")
        lines.append(subject + " " + " ;\n    ".join(predicates) + " .")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def materialize_support_consensus(
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
) -> dict[str, Any]:
    date.fromisoformat(release_date)
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
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("support materialization inputs and outputs must be distinct")
    manifest = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    candidate_report = _verify_candidate_report(
        candidate_report_path,
        manifest,
        occurrence_path,
        cluster_path,
        evidence_path,
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
        raise ValueError("support-class review campaign is incomplete or unconserved")
    context = load_validation_context(
        manifest,
        occurrence_path=occurrence_path,
        cluster_path=cluster_path,
        evidence_path=evidence_path,
    )
    decisions = {row.item_id: row for row in read_jsonl(consensus_path, ConsensusDecision)}
    accepted: list[tuple[ConsensusDecision, SupportClassCandidate]] = []
    held: list[dict[str, Any]] = []
    for item_id, cluster in sorted(context.clusters.items()):
        decision = decisions[item_id]
        candidate = cluster.support_class_candidate
        if candidate is None:
            raise ValueError(f"{item_id}: support campaign item has no runner candidate")
        actionable = (
            decision.status == "llm_consensus"
            and decision.disposition == "reusable_flopo_support_class"
            and decision.validation_passed
            and decision.adjudicator_id is not None
        )
        if actionable:
            signature = ProposedSignature.model_validate_json(decision.normalized_signature or "")
            if (
                signature.kind != "reusable_flopo_support_class"
                or signature.support_class != candidate.signature
            ):
                raise ValueError(f"{item_id}: support consensus signature drift")
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

    maximum, existing_ids = _max_flopo_number(flopo_registry_path)
    allocations: list[dict[str, Any]] = []
    for offset, (decision, candidate) in enumerate(
        sorted(accepted, key=lambda row: row[1].proposal_key), 1
    ):
        flopo_id = f"FLOPO_{maximum + offset:07d}"
        if flopo_id in existing_ids:
            raise ValueError(f"allocated identifier already exists: {flopo_id}")
        allocations.append(
            {
                "proposal_key": candidate.proposal_key,
                "flopo_id": flopo_id,
                "label": candidate.signature.label,
                "signature_sha256": hashlib.sha256(
                    canonical_json(candidate.signature.model_dump(mode="json")).encode()
                ).hexdigest(),
                "campaign_id": decision.campaign_id,
                "item_id": decision.item_id,
                "consensus_signature_sha256": decision.signature_sha256,
                "reviewer_ids": list(decision.reviewer_ids),
                "adjudicator_id": decision.adjudicator_id,
                "occurrence_count": candidate.occurrence_count,
                "candidate": candidate.model_dump(mode="json"),
            }
        )

    allocation_fields = (
        "proposal_key",
        "flopo_id",
        "label",
        "signature_sha256",
        "campaign_id",
        "item_id",
        "consensus_signature_sha256",
        "reviewer_ids",
        "adjudicator_id",
        "occurrence_count",
    )
    allocation_lines = ["\t".join(allocation_fields)]
    for row in allocations:
        allocation_lines.append(
            "\t".join(
                "|".join(row[field]) if field == "reviewer_ids" else str(row[field] or "")
                for field in allocation_fields
            )
        )
    _write_immutable(
        allocation_path, "\n".join(allocation_lines) + "\n", "support allocation registry"
    )
    evidence_catalog_path = Path(candidate_report["evidence_catalog"]["path"])
    module = _module_text(
        allocations,
        release_date=release_date,
        evidence_urls=_load_evidence_urls(evidence_catalog_path),
    )
    _write_immutable(module_path, module, "support-class OWL module")
    held_payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in held
    )
    _write_immutable(held_path, held_payload, "support-class held ledger")
    result = {
        "schema_version": "flopo-support-consensus-materialization-v1",
        "campaign_id": manifest.campaign_id,
        "starting_classes": manifest.starting_clusters,
        "starting_occurrences": manifest.starting_occurrences,
        "accepted_classes": len(allocations),
        "accepted_occurrences": sum(row["occurrence_count"] for row in allocations),
        "held_classes": len(held),
        "held_occurrences": sum(row["occurrence_count"] for row in held),
        "class_conserved": len(allocations) + len(held) == manifest.starting_clusters,
        "occurrence_conserved": (
            sum(row["occurrence_count"] for row in allocations)
            + sum(row["occurrence_count"] for row in held)
            == manifest.starting_occurrences
        ),
        "review_report": review_report,
        "candidate_report_sha256": sha256_file(candidate_report_path).sha256,
        "candidate_exclusions": candidate_report["excluded_classes"],
        "artifacts": {
            "allocations": sha256_file(allocation_path).model_dump(mode="json"),
            "module": sha256_file(module_path).model_dump(mode="json"),
            "held": sha256_file(held_path).model_dump(mode="json"),
            "flopo_registry": sha256_file(flopo_registry_path).model_dump(mode="json"),
        },
    }
    _write_immutable(
        report_path,
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        "support materialization report",
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
    parser.add_argument("--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--allocations", type=Path, required=True)
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--held", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    result = materialize_support_consensus(
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
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
