#!/usr/bin/env python3
"""Publish a verified machine-reviewed anatomy support module into FLOPO.

The publisher keeps machine and human curation provenance distinct.  It accepts only the exact
module/allocation pair named by a conserved support-consensus materialization report, embeds a
replaceable generated block in the RDF/XML release, records stable allocation metadata, and
regenerates the global FLOPO identifier registry from the resulting ontology.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import DCTERMS, OWL, RDF, Graph, Literal, URIRef

from flopo2.ids.registry import build_registry, write_registry_tsv
from flopo2.review.io import sha256_file
from flopo2.verify.materialize_support_consensus import MODULE_IRI
from tools.update_flopo_release import _graph_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
FLOPOANN = "https://w3id.org/flopo/annotation/"
MACHINE_CAMPAIGN = URIRef(FLOPOANN + "machine_review_campaign")
MACHINE_ITEM = URIRef(FLOPOANN + "machine_review_item")
MACHINE_SIGNATURE = URIRef(FLOPOANN + "machine_review_signature")
MACHINE_STATUS = URIRef(FLOPOANN + "machine_review_status")
MACHINE_REVIEWER = URIRef(FLOPOANN + "machine_reviewer")
MACHINE_ADJUDICATOR = URIRef(FLOPOANN + "machine_adjudicator")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO MACHINE-REVIEWED SUPPORT CLASSES -->"
END_MARKER = "  <!-- END GENERATED FLOPO MACHINE-REVIEWED SUPPORT CLASSES -->"
ALLOCATION_FIELDS = (
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


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed machine-support markers in release OWL")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _ensure_flopoann_namespace(text: str) -> str:
    if "xmlns:flopoann=" in text:
        return text
    if text.count("<rdf:RDF") != 1:
        raise ValueError("main FLOPO RDF/XML must contain one rdf:RDF root")
    return text.replace("<rdf:RDF", f'<rdf:RDF\n  xmlns:flopoann="{FLOPOANN}"', 1)


def _read_allocations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != ALLOCATION_FIELDS:
            raise ValueError("support allocation registry has an unsupported schema")
        rows = [{field: str(row.get(field, "") or "") for field in ALLOCATION_FIELDS} for row in reader]
    proposal_keys = [row["proposal_key"] for row in rows]
    flopo_ids = [row["flopo_id"] for row in rows]
    if (
        any(not value for value in proposal_keys)
        or len(proposal_keys) != len(set(proposal_keys))
        or any(not re.fullmatch(r"FLOPO_\d{7}", value) for value in flopo_ids)
        or len(flopo_ids) != len(set(flopo_ids))
    ):
        raise ValueError("support allocations contain blank, duplicate, or invalid identities")
    return rows


def _verify_materialization(
    report_path: Path, allocation_path: Path, module_path: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid support materialization report: {error}") from error
    if report.get("schema_version") != "flopo-support-consensus-materialization-v1":
        raise ValueError("unsupported support materialization report")
    if not report.get("class_conserved") or not report.get("occurrence_conserved"):
        raise ValueError("support materialization is not conserved")
    if not report.get("review_report", {}).get("ok"):
        raise ValueError("support materialization is not backed by a complete campaign")
    for key, path in (("allocations", allocation_path), ("module", module_path)):
        actual = sha256_file(path)
        frozen = report.get("artifacts", {}).get(key, {})
        if (actual.sha256, actual.bytes) != (frozen.get("sha256"), frozen.get("bytes")):
            raise ValueError(f"support {key} artifact hash mismatch")
    allocations = _read_allocations(allocation_path)
    if len(allocations) != int(report.get("accepted_classes", -1)):
        raise ValueError("support allocation count does not match materialization report")
    if sum(int(row["occurrence_count"]) for row in allocations) != int(
        report.get("accepted_occurrences", -1)
    ):
        raise ValueError("support allocation occurrence count drift")
    if any(row["campaign_id"] != report.get("campaign_id") for row in allocations):
        raise ValueError("support allocation campaign binding drift")
    return report, allocations


def _module_fragment(
    module_path: Path, allocations: list[dict[str, str]]
) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    expected_ontology = URIRef(MODULE_IRI)
    if ontology_subjects != {expected_ontology}:
        raise ValueError("support module must have exactly its expected ontology header")
    expected_classes = {OBO + row["flopo_id"] for row in allocations}
    promoted = {
        str(subject)
        for subject in graph.subjects(MACHINE_CAMPAIGN, None)
        if isinstance(subject, URIRef) and str(subject).startswith(OBO + "FLOPO_")
    }
    if promoted != expected_classes:
        raise ValueError("support module classes do not exactly match allocations")
    allocation_by_iri = {OBO + row["flopo_id"]: row for row in allocations}
    for class_iri in sorted(promoted):
        cls = URIRef(class_iri)
        row = allocation_by_iri[class_iri]
        if (cls, RDF.type, OWL.Class) not in graph:
            raise ValueError(f"machine support resource is not an OWL class: {class_iri}")
        exact_literals = (
            (MACHINE_CAMPAIGN, row["campaign_id"]),
            (MACHINE_ITEM, row["item_id"]),
            (MACHINE_SIGNATURE, row["consensus_signature_sha256"]),
            (MACHINE_STATUS, "llm_consensus"),
            (MACHINE_ADJUDICATOR, row["adjudicator_id"]),
        )
        if any((cls, predicate, Literal(value)) not in graph for predicate, value in exact_literals):
            raise ValueError(f"machine support provenance mismatch: {class_iri}")
        reviewers = {str(value) for value in graph.objects(cls, MACHINE_REVIEWER)}
        if reviewers != set(filter(None, row["reviewer_ids"].split("|"))):
            raise ValueError(f"machine reviewer provenance mismatch: {class_iri}")
        if len(reviewers) < 2 or not list(graph.objects(cls, DCTERMS.source)):
            raise ValueError(f"machine support class lacks independent review or source: {class_iri}")
        if list(graph.objects(cls, DCTERMS.contributor)):
            raise ValueError(f"machine support class must not claim a human contributor: {class_iri}")
        comments = " ".join(str(value).casefold() for value in graph.objects(cls, URIRef(OBO + "IAO_0000116")))
        if "not human reviewed" not in comments:
            raise ValueError(f"machine support class lacks explicit review-status warning: {class_iri}")

    release_graph = Graph()
    promoted_nodes = {URIRef(value) for value in promoted}
    for subject, predicate, obj in graph:
        if subject == expected_ontology:
            continue
        if isinstance(subject, URIRef) and subject not in promoted_nodes:
            continue
        release_graph.add((subject, predicate, obj))
    fragment, class_count = _graph_fragment(
        release_graph, node_id_prefix="FLOPOMachineSupport_"
    )
    if class_count != len(promoted):
        raise ValueError("support release fragment contains unexpected FLOPO classes")
    return fragment.strip(), promoted


def _machine_registry_payload(
    path: Path, allocations: list[dict[str, str]]
) -> str:
    existing: list[dict[str, str]] = _read_allocations(path) if path.exists() else []
    by_proposal = {row["proposal_key"]: row for row in existing}
    by_id = {row["flopo_id"]: row for row in existing}
    for row in allocations:
        previous_proposal = by_proposal.get(row["proposal_key"])
        previous_id = by_id.get(row["flopo_id"])
        if previous_proposal is not None and previous_proposal != row:
            raise ValueError(f"support proposal allocation changed: {row['proposal_key']}")
        if previous_id is not None and previous_id != row:
            raise ValueError(f"support FLOPO identifier collision: {row['flopo_id']}")
        by_proposal[row["proposal_key"]] = row
        by_id[row["flopo_id"]] = row
    rows = sorted(by_proposal.values(), key=lambda row: int(row["flopo_id"].split("_")[1]))
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ALLOCATION_FIELDS, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def _temp_path(destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.stem}.",
        suffix=destination.suffix or ".tmp",
    )
    os.close(descriptor)
    return Path(name)


def update_machine_support_release(
    *,
    release_path: Path,
    module_path: Path,
    materialization_report_path: Path,
    allocation_path: Path,
    machine_registry_path: Path,
    flopo_registry_path: Path,
    release_date: str,
) -> dict[str, Any]:
    date.fromisoformat(release_date)
    paths = (
        release_path,
        module_path,
        materialization_report_path,
        allocation_path,
        machine_registry_path,
        flopo_registry_path,
    )
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("machine support publication paths must be distinct")
    report, allocations = _verify_materialization(
        materialization_report_path, allocation_path, module_path
    )
    fragment, classes = _module_fragment(module_path, allocations)
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    for class_iri in classes:
        if class_iri in text:
            raise ValueError(f"allocated support class already occurs outside generated block: {class_iri}")
    text = _ensure_flopoann_namespace(text)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    release_payload = text.replace(closing, block + closing, 1)
    machine_payload = _machine_registry_payload(machine_registry_path, allocations)

    release_temp = _temp_path(release_path)
    machine_temp = _temp_path(machine_registry_path)
    registry_temp = _temp_path(flopo_registry_path)
    try:
        release_temp.write_text(release_payload, encoding="utf-8")
        check = Graph().parse(release_temp.as_posix())
        for class_iri in classes:
            cls = URIRef(class_iri)
            if (cls, RDF.type, OWL.Class) not in check:
                raise ValueError(f"published support class is missing: {class_iri}")
            if list(check.objects(cls, DCTERMS.contributor)):
                raise ValueError(f"published machine class acquired contributor metadata: {class_iri}")
        machine_temp.write_text(machine_payload, encoding="utf-8")
        write_registry_tsv(build_registry(release_temp), registry_temp)
        registry_ids = {
            row["flopo_iri"].rsplit("/", 1)[-1]
            for row in csv.DictReader(
                registry_temp.open(encoding="utf-8", newline=""), delimiter="\t"
            )
        }
        if registry_ids.isdisjoint(row["flopo_id"] for row in allocations):
            raise ValueError("regenerated FLOPO registry omitted all support allocations")
        if not {row["flopo_id"] for row in allocations}.issubset(registry_ids):
            raise ValueError("regenerated FLOPO registry omitted a support allocation")
        os.replace(release_temp, release_path)
        os.replace(machine_temp, machine_registry_path)
        os.replace(registry_temp, flopo_registry_path)
    finally:
        release_temp.unlink(missing_ok=True)
        machine_temp.unlink(missing_ok=True)
        registry_temp.unlink(missing_ok=True)
    return {
        "schema_version": "flopo-machine-support-publication-v1",
        "campaign_id": report["campaign_id"],
        "classes": len(classes),
        "occurrences_covered": sum(int(row["occurrence_count"]) for row in allocations),
        "human_reviewed": False,
        "release": sha256_file(release_path).model_dump(mode="json"),
        "machine_registry": sha256_file(machine_registry_path).model_dump(mode="json"),
        "flopo_registry": sha256_file(flopo_registry_path).model_dump(mode="json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--module", type=Path, required=True)
    parser.add_argument("--materialization-report", type=Path, required=True)
    parser.add_argument("--allocations", type=Path, required=True)
    parser.add_argument(
        "--machine-registry",
        type=Path,
        default=Path("config/flopo_machine_support_id_registry.tsv"),
    )
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    result = update_machine_support_release(
        release_path=args.release,
        module_path=args.module,
        materialization_report_path=args.materialization_report,
        allocation_path=args.allocations,
        machine_registry_path=args.machine_registry,
        flopo_registry_path=args.flopo_registry,
        release_date=args.date,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
