"""Freeze exact-colour EQ gaps as runner-bound FLOPO class-review candidates.

The upstream inventory has already separated exact standardized colour compounds from contextual
exclusions.  This bridge groups every retained occurrence by its immutable PO--PATO pair, binds an
exact FLOPO class signature, label, definition, bearer-phenotype parent, and ontology evidence,
then emits a lossless campaign for independent review.  It never allocates a FLOPO identifier or
marks a proposal as human reviewed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from flopo2.review.inventory import (
    _artifact_at,
    _reference_record,
    _temp_path,
    _validate_distinct_paths,
    model_spec,
)
from flopo2.review.io import (
    atomic_write_text,
    sha256_file,
    stable_id,
    write_immutable_json,
    write_jsonl,
)
from flopo2.review.models import (
    CampaignManifest,
    Cluster,
    ContextSample,
    DerivationSpec,
    EvidenceRecord,
    ModelSpec,
    Occurrence,
    PhenotypeExpression,
    PromptSpec,
    ReusableFlopoClassCandidate,
    canonical_json,
    normalized_text,
)


DERIVATION_PROTOCOL = "flopo-exact-colour-eq-gap-class-review-v1"
EXPECTED_INVENTORY_SCHEMA = "flopo-exact-colour-eq-gap-inventory-v1"
CANDIDATE_REPORT_SCHEMA = "flopo-eq-gap-class-candidate-report-v1"
ROOT_PHENOTYPE_SIGNATURE = "OTHER"
ROOT_PHENOTYPE_LABEL = "flora phenotype"


def derivation_spec() -> DerivationSpec:
    descriptor = {"protocol": DERIVATION_PROTOCOL}
    return DerivationSpec(
        protocol=DERIVATION_PROTOCOL,
        descriptor_sha256=hashlib.sha256(canonical_json(descriptor).encode()).hexdigest(),
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error}") from error
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: row must be an object")
            rows.append(row)
    return rows


def _active_phenotype_parents(path: Path) -> tuple[dict[str, str], str, int]:
    parent_rows: dict[str, tuple[int, str]] = {}
    root_row: tuple[int, str] | None = None
    duplicate_signatures = 0
    with path.open(encoding="utf-8", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle, delimiter="\t"), 2):
            if str(row.get("deprecated", "") or "").strip() in {"1", "true", "True"}:
                continue
            iri = str(row.get("flopo_iri", "") or "").strip()
            identifier = iri.rsplit("/", 1)[-1]
            try:
                flopo_number = int(str(row.get("flopo_num", "") or ""))
            except ValueError as error:
                raise ValueError(f"{path}:{number}: invalid flopo_num") from error
            signature = str(row.get("signature", "") or "").strip()
            label = str(row.get("label", "") or "").strip()
            if not identifier.startswith("FLOPO_"):
                raise ValueError(f"{path}:{number}: invalid active FLOPO IRI")
            if signature.startswith("PHENO|PO_"):
                po_id = signature.split("|", 1)[1]
                previous = parent_rows.get(po_id)
                if previous is not None and previous[1] != identifier:
                    duplicate_signatures += 1
                if previous is None or flopo_number > previous[0]:
                    parent_rows[po_id] = (flopo_number, identifier)
            if signature == ROOT_PHENOTYPE_SIGNATURE and label == ROOT_PHENOTYPE_LABEL:
                if root_row is not None and root_row[1] != identifier:
                    duplicate_signatures += 1
                if root_row is None or flopo_number > root_row[0]:
                    root_row = (flopo_number, identifier)
    if root_row is None:
        raise ValueError("active FLOPO registry has no flora phenotype root")
    return (
        {po_id: row[1] for po_id, row in parent_rows.items()},
        root_row[1],
        duplicate_signatures,
    )


def _definition(po_label: str, pato_label: str) -> str:
    return f"A flora phenotype in which a {po_label} has the quality {pato_label}."


def _selected_samples(members: list[Occurrence], limit: int = 8) -> list[Occurrence]:
    if len(members) <= limit:
        return members
    indices = sorted(
        {round(index * (len(members) - 1) / (limit - 1)) for index in range(limit)}
    )
    return [members[index] for index in indices]


def _evidence_payload(occurrence: Occurrence) -> dict[str, Any]:
    candidate = occurrence.reusable_flopo_class_candidate
    if candidate is None:
        raise ValueError(f"{occurrence.occurrence_id}: missing reusable class candidate")
    return {
        "occurrence_id": occurrence.occurrence_id,
        "item_id": occurrence.cluster_id,
        "source": occurrence.source,
        "source_id": occurrence.source_id,
        "source_segment_index": occurrence.source_segment_index,
        "span_start": occurrence.span_start,
        "span_end": occurrence.span_end,
        "surface_form": occurrence.surface_form,
        "context": occurrence.context,
        "semantic_fingerprint": occurrence.semantic_fingerprint,
        "reusable_flopo_class_candidate": candidate.model_dump(mode="json"),
    }


def build_eq_gap_class_inventory(
    *,
    classes_path: Path,
    source_occurrences_path: Path,
    source_report_path: Path,
    flopo_registry_path: Path,
    occurrence_path: Path,
    cluster_path: Path,
    evidence_path: Path,
    report_path: Path,
    manifest_path: Path,
    ontology_paths: Iterable[Path],
    prompt_paths: dict[str, Path],
    models: Iterable[ModelSpec],
    created_at: datetime | None = None,
) -> CampaignManifest:
    """Build an immutable two-reviewer plus adversarial EQ-class campaign."""

    ontology_paths = tuple(ontology_paths)
    source_paths = (source_occurrences_path, source_report_path)
    _validate_distinct_paths(
        classes_path,
        *source_paths,
        occurrence_path,
        cluster_path,
        evidence_path,
        report_path,
        manifest_path,
        *ontology_paths,
        *prompt_paths.values(),
    )
    source_report = json.loads(source_report_path.read_text(encoding="utf-8"))
    if source_report.get("schema_version") != EXPECTED_INVENTORY_SCHEMA:
        raise ValueError("unsupported exact-colour EQ-gap inventory report")
    if not source_report.get("conserved"):
        raise ValueError("exact-colour EQ-gap source inventory is not conserved")
    for key, path in (("classes", classes_path), ("occurrences", source_occurrences_path)):
        expected = source_report.get("artifacts", {}).get(key, {})
        actual = sha256_file(path)
        if (actual.sha256, actual.bytes) != (expected.get("sha256"), expected.get("bytes")):
            raise ValueError(f"exact-colour EQ-gap {key} artifact drift")

    raw_classes = _read_jsonl(classes_path)
    raw_occurrences = _read_jsonl(source_occurrences_path)
    if len(raw_classes) != int(source_report.get("gap_classes", -1)):
        raise ValueError("source EQ-gap class count drift")
    if len(raw_occurrences) != int(source_report.get("gap_occurrences", -1)):
        raise ValueError("source EQ-gap occurrence count drift")
    class_by_pair: dict[tuple[str, str], dict[str, Any]] = {}
    for row in raw_classes:
        pair = (str(row.get("po_id", "")), str(row.get("pato_id", "")))
        if not all(pair) or pair in class_by_pair:
            raise ValueError(f"invalid or duplicate EQ-gap class pair: {pair}")
        if str(row.get("proposed_signature", "")) != f"EQ|{pair[0]}|{pair[1]}":
            raise ValueError(f"{pair}: source EQ signature drift")
        class_by_pair[pair] = row
    raw_members: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_occurrences:
        pair = (str(row.get("po_id", "")), str(row.get("pato_id", "")))
        if pair not in class_by_pair:
            raise ValueError(f"occurrence targets unknown EQ-gap class: {pair}")
        raw_members[pair].append(row)

    phenotype_parents, root_parent, duplicate_parent_signatures = _active_phenotype_parents(
        flopo_registry_path
    )
    ontology_hashes = tuple(sha256_file(path) for path in ontology_paths)
    ontology_evidence = {
        Path(row.path).name: stable_id("evidence", ("ontology", row.path, row.sha256))
        for row in ontology_hashes
    }
    required_authorities = ("flopo.owl", "plant_ontology.obo", "quality.obo")
    if any(name not in ontology_evidence for name in required_authorities):
        raise ValueError(
            "EQ-gap class review requires frozen FLOPO, Plant Ontology, and PATO artifacts"
        )
    authority_ids = tuple(ontology_evidence[name] for name in required_authorities)

    occurrences: list[Occurrence] = []
    clusters: list[Cluster] = []
    parent_fallbacks = 0
    for pair, class_row in sorted(class_by_pair.items()):
        members = sorted(
            raw_members.get(pair, []), key=lambda row: str(row.get("occurrence_id", ""))
        )
        source_ids = [str(row.get("occurrence_id", "")) for row in members]
        if any(not identifier.startswith("eqgapocc_") for identifier in source_ids):
            raise ValueError(f"{pair}: malformed source occurrence identifier")
        membership_hash = hashlib.sha256(canonical_json(source_ids).encode()).hexdigest()
        if len(members) != int(class_row.get("occurrence_count", -1)) or membership_hash != str(
            class_row.get("occurrence_membership_sha256", "")
        ):
            raise ValueError(f"{pair}: source occurrence membership drift")
        po_label = str(class_row.get("po_label", "") or "").strip()
        pato_label = str(class_row.get("pato_label", "") or "").strip()
        label = str(class_row.get("proposed_label", "") or "").strip()
        if not po_label or not pato_label or label != f"{po_label} {pato_label}":
            raise ValueError(f"{pair}: source class label is not canonical")
        parent_id = phenotype_parents.get(pair[0], root_parent)
        parent_fallbacks += int(pair[0] not in phenotype_parents)
        candidate = ReusableFlopoClassCandidate(
            proposal_key=str(class_row.get("class_candidate_id", "")),
            signature=PhenotypeExpression(bearer_id=pair[0], quality_id=pair[1]),
            label=label,
            definition=_definition(po_label, pato_label),
            parent_ids=(parent_id,),
            authoritative_evidence_ids=authority_ids,
            occurrence_count=len(members),
            source_occurrence_membership_sha256=membership_hash,
        )
        semantic_fingerprint = hashlib.sha256(
            canonical_json(
                {"protocol": DERIVATION_PROTOCOL, "candidate": candidate.model_dump(mode="json")}
            ).encode()
        ).hexdigest()
        cluster_id = stable_id(
            "cluster", (DERIVATION_PROTOCOL, candidate.proposal_key, semantic_fingerprint)
        )
        cluster_members: list[Occurrence] = []
        for row in members:
            start = int(row.get("start", -1))
            end = int(row.get("end", -1))
            surface = str(row.get("surface_form", "") or "")
            context = str(row.get("context", "") or "")
            if not (0 <= start < end) or not surface or f"[[{surface}]]" not in context:
                raise ValueError(f"{pair}: malformed source-bound colour occurrence")
            original_id = str(row["occurrence_id"])
            occurrence_id = stable_id("occ", (DERIVATION_PROTOCOL, original_id))
            evidence_id = stable_id(
                "evidence", (occurrence_id, cluster_id, semantic_fingerprint, context)
            )
            occurrence = Occurrence(
                occurrence_id=occurrence_id,
                evidence_id=evidence_id,
                cluster_id=cluster_id,
                semantic_fingerprint=semantic_fingerprint,
                source=str(row.get("source", "") or ""),
                source_id=str(row.get("source_id", "") or ""),
                source_segment_index=int(row.get("source_segment_index", 0) or 0),
                taxon=str(row.get("taxon", "") or ""),
                organ=str(row.get("organ", "") or ""),
                language=str(row.get("language", "") or ""),
                segment_char_start=0,
                segment_char_end=max(end, 0),
                span_start=start,
                span_end=end,
                surface_form=surface,
                normalized_form=normalized_text(surface),
                reason="missing_active_flopo_eq_class",
                candidate_pato_id=pair[1],
                pending_bearer=pair[0],
                extractor=str(row.get("extractor", "") or "exact_colour_eq_gap_inventory_v1"),
                context=context,
                reusable_flopo_class_candidate=candidate,
            )
            occurrences.append(occurrence)
            cluster_members.append(occurrence)
        review_membership = tuple(sorted(row.occurrence_id for row in cluster_members))
        samples = _selected_samples(cluster_members)
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                normalized_form=normalized_text(label),
                reason="missing_active_flopo_eq_class",
                candidate_pato_id=pair[1],
                language="multilingual",
                organ=po_label,
                pending_bearer=pair[0],
                semantic_fingerprint=semantic_fingerprint,
                occurrence_count=len(cluster_members),
                occurrence_membership_sha256=hashlib.sha256(
                    canonical_json(review_membership).encode()
                ).hexdigest(),
                context_samples=tuple(
                    ContextSample(
                        evidence_id=row.evidence_id,
                        occurrence_id=row.occurrence_id,
                        context=row.context,
                        context_sha256=hashlib.sha256(row.context.encode()).hexdigest(),
                    )
                    for row in samples
                ),
                reusable_flopo_class_candidate=candidate,
            )
        )

    occurrences.sort(key=lambda row: (row.cluster_id, row.occurrence_id))
    clusters.sort(key=lambda row: row.cluster_id)
    source_hashes = tuple(sha256_file(path) for path in source_paths)
    prompts = tuple(
        PromptSpec(prompt_id=prompt_id, **sha256_file(path).model_dump())
        for prompt_id, path in sorted(prompt_paths.items())
    )
    model_rows = tuple(models)
    derivation = derivation_spec()
    input_hash = sha256_file(classes_path)
    campaign_seed = {
        "input": input_hash.sha256,
        "ontologies": [row.sha256 for row in ontology_hashes],
        "authorities": [],
        "prompts": [(row.prompt_id, row.sha256) for row in prompts],
        "models": [(row.reviewer_id, row.descriptor_sha256) for row in model_rows],
        "derivation": derivation.descriptor_sha256,
        "sources": [row.sha256 for row in source_hashes],
    }
    campaign_id = stable_id("campaign", campaign_seed)

    if manifest_path.exists():
        existing = CampaignManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        if existing.campaign_id != campaign_id:
            raise FileExistsError(f"refusing to replace immutable manifest: {manifest_path}")
        for expected, path in (
            (existing.occurrences, occurrence_path),
            (existing.clusters, cluster_path),
            (existing.evidence_registry, evidence_path),
        ):
            actual = sha256_file(path)
            if (actual.sha256, actual.bytes) != (expected.sha256, expected.bytes):
                raise ValueError(f"immutable campaign artifact no longer matches manifest: {path}")
        return existing
    for path in (occurrence_path, cluster_path, evidence_path, report_path):
        if path.exists():
            raise FileExistsError(f"refusing to replace pre-existing campaign artifact: {path}")

    evidence_rows = [
        *(
            EvidenceRecord(
                evidence_id=row.evidence_id,
                kind="occurrence",
                occurrence_id=row.occurrence_id,
                item_id=row.cluster_id,
                payload_sha256=hashlib.sha256(
                    canonical_json(_evidence_payload(row)).encode()
                ).hexdigest(),
                locator=(
                    f"{row.source}:{row.source_id}:{row.source_segment_index}:"
                    f"{row.span_start}-{row.span_end}"
                ),
                description="Verbatim flora occurrence supporting an exact-colour EQ class",
            )
            for row in occurrences
        ),
        *(_reference_record(row, "ontology") for row in ontology_hashes),
        *(_reference_record(row, "source_inventory") for row in source_hashes),
    ]
    temporary = {
        occurrence_path: _temp_path(occurrence_path),
        cluster_path: _temp_path(cluster_path),
        evidence_path: _temp_path(evidence_path),
    }
    installed: list[Path] = []
    try:
        write_jsonl(temporary[occurrence_path], occurrences)
        write_jsonl(temporary[cluster_path], clusters)
        write_jsonl(temporary[evidence_path], evidence_rows)
        manifest = CampaignManifest(
            campaign_id=campaign_id,
            created_at=created_at or datetime.now(timezone.utc),
            input=input_hash,
            ontologies=ontology_hashes,
            sources=source_hashes,
            prompts=prompts,
            models=model_rows,
            derivation=derivation,
            occurrences=_artifact_at(temporary[occurrence_path], occurrence_path),
            clusters=_artifact_at(temporary[cluster_path], cluster_path),
            evidence_registry=_artifact_at(temporary[evidence_path], evidence_path),
            starting_occurrences=len(occurrences),
            starting_clusters=len(clusters),
        )
        for destination, source in temporary.items():
            os.replace(source, destination)
            installed.append(destination)
        report = {
            "schema_version": CANDIDATE_REPORT_SCHEMA,
            "campaign_id": manifest.campaign_id,
            "source_inventory_report": sha256_file(source_report_path).model_dump(),
            "source_classes": sha256_file(classes_path).model_dump(),
            "source_occurrences": sha256_file(source_occurrences_path).model_dump(),
            "flopo_registry": sha256_file(flopo_registry_path).model_dump(),
            "candidate_classes": len(clusters),
            "candidate_occurrences": len(occurrences),
            "bearer_parent_fallbacks": parent_fallbacks,
            "duplicate_active_parent_signatures": duplicate_parent_signatures,
            "occurrences": manifest.occurrences.model_dump(),
            "clusters": manifest.clusters.model_dump(),
            "evidence_registry": manifest.evidence_registry.model_dump(),
            "conservation": {
                "class_count_matches_source": len(clusters) == len(raw_classes),
                "occurrence_count_matches_source": len(occurrences) == len(raw_occurrences),
                "all_source_memberships_verified": True,
                "all_candidate_authorities_hash_bound": True,
            },
        }
        atomic_write_text(
            report_path,
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
        write_immutable_json(manifest_path, manifest)
        return manifest
    except BaseException:
        for path in temporary.values():
            path.unlink(missing_ok=True)
        if not manifest_path.exists():
            for path in installed:
                path.unlink(missing_ok=True)
            report_path.unlink(missing_ok=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--source-occurrences", type=Path, required=True)
    parser.add_argument("--source-report", type=Path, required=True)
    parser.add_argument("--flopo-registry", type=Path, required=True)
    parser.add_argument("--occurrences", type=Path, required=True)
    parser.add_argument("--clusters", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ontology", type=Path, action="append", required=True)
    parser.add_argument("--prompt", action="append", required=True)
    parser.add_argument("--models", type=Path, required=True)
    args = parser.parse_args()
    prompt_paths: dict[str, Path] = {}
    for item in args.prompt:
        if "=" not in item:
            parser.error("--prompt expects ID=PATH")
        identifier, path = item.split("=", 1)
        prompt_paths[identifier] = Path(path)
    raw_models = json.loads(args.models.read_text(encoding="utf-8"))
    models = [model_spec(**row) for row in raw_models]
    manifest = build_eq_gap_class_inventory(
        classes_path=args.classes,
        source_occurrences_path=args.source_occurrences,
        source_report_path=args.source_report,
        flopo_registry_path=args.flopo_registry,
        occurrence_path=args.occurrences,
        cluster_path=args.clusters,
        evidence_path=args.evidence,
        report_path=args.report,
        manifest_path=args.manifest,
        ontology_paths=args.ontology,
        prompt_paths=prompt_paths,
        models=models,
    )
    print(manifest.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
