#!/usr/bin/env python3
"""Publish verified machine-reviewed exact-colour EQ classes into FLOPO.

Follows ``update_flopo_machine_support_release.py``: every published class must come from the
exact module/allocation pair named by a conserved EQ-class consensus materialization report.
Several materializations of the same campaign may be published together (the original
two-family + adversarial admissions and later tie-break runs); a tie-break run must declare the
earlier allocation ledger it reserved identifiers after.  The classes are embedded in a
replaceable generated block of the RDF/XML release, allocation metadata is recorded in a
dedicated machine registry, the exact source modules are retained beside the release, and the
global FLOPO identifier registry is regenerated from the resulting ontology.

Machine provenance stays distinct from curation: no contributor, curator ORCID, or
human-review claim is written.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any

from rdflib import DCTERMS, OWL, RDF, Graph, Literal, URIRef

from flopo2.ids.registry import build_registry, write_registry_tsv
from flopo2.review.io import sha256_file
from flopo2.review.tiebreak import TIEBREAK_RULES
from flopo2.verify.materialize_eq_gap_class_consensus import (
    ALLOCATION_FIELDS,
    MODULE_IRI,
    TIEBREAK_ALLOCATION_FIELDS,
)
from tools.update_flopo_machine_support_release import (
    MACHINE_ADJUDICATOR,
    MACHINE_CAMPAIGN,
    MACHINE_ITEM,
    MACHINE_REVIEWER,
    MACHINE_SIGNATURE,
    MACHINE_STATUS,
    _ensure_flopoann_namespace,
    _temp_path,
)
from tools.update_flopo_release import _graph_fragment, _update_release_metadata


OBO = "http://purl.obolibrary.org/obo/"
FLOPOANN = "https://w3id.org/flopo/annotation/"
MACHINE_RULE = URIRef(FLOPOANN + "machine_review_rule")
CURATOR_OVERRIDE = URIRef(FLOPOANN + "curator_override")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO MACHINE-REVIEWED EQ CLASSES -->"
END_MARKER = "  <!-- END GENERATED FLOPO MACHINE-REVIEWED EQ CLASSES -->"
ADVERSARIAL_RULE = "two_family_exact_agreement_adversarial_no_blocker"
# Historical allocation ledgers use one of three header shapes: the base (adversarial-only)
# run, the original tie-break run (before the curator-override column existed), or the current
# tie-break run (which may additionally record a curator override of an adversarial block). The
# persistent machine registry (``_machine_registry_payload``) is always written in the widest
# (current) shape; older rows read back from a narrower file get an empty ``curator_override``.
OLD_TIEBREAK_FIELDS = (*ALLOCATION_FIELDS, "admission_rule")
REGISTRY_FIELDS = TIEBREAK_ALLOCATION_FIELDS
TIEBREAK_RULE_NAMES = frozenset(TIEBREAK_RULES.values())


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed machine-reviewed EQ markers in release OWL")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _read_allocations(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        header = tuple(reader.fieldnames or ())
        if header not in {ALLOCATION_FIELDS, OLD_TIEBREAK_FIELDS, REGISTRY_FIELDS}:
            raise ValueError(f"{path}: unsupported EQ allocation schema")
        rows = []
        for row in reader:
            record = {field: str(row.get(field, "") or "") for field in REGISTRY_FIELDS}
            if not record["admission_rule"]:
                if not record["adjudicator_id"]:
                    raise ValueError(f"{path}: allocation lacks an adjudicator or admission rule")
                record["admission_rule"] = ADVERSARIAL_RULE
            rows.append(record)
    for key in ("proposal_key", "flopo_id", "item_id", "eq_signature"):
        values = [row[key] for row in rows]
        if any(not value for value in values) or len(values) != len(set(values)):
            raise ValueError(f"{path}: EQ allocations contain blank or duplicate {key}")
    if any(not re.fullmatch(r"FLOPO_\d{7}", row["flopo_id"]) for row in rows):
        raise ValueError(f"{path}: EQ allocations contain an invalid FLOPO identifier")
    return rows


def _verify_materialization(
    report_path: Path, allocation_path: Path, module_path: Path
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"invalid EQ materialization report: {error}") from error
    if report.get("schema_version") != "flopo-eq-class-consensus-materialization-v1":
        raise ValueError("unsupported EQ materialization report")
    if not report.get("class_conserved") or not report.get("occurrence_conserved"):
        raise ValueError("EQ materialization is not conserved")
    if not report.get("review_report", {}).get("ok"):
        raise ValueError("EQ materialization is not backed by a complete campaign")
    if report.get("occurrence_annotations_admitted") != 0:
        raise ValueError("EQ class materialization must not admit occurrence annotations")
    for key, path in (("allocations", allocation_path), ("module", module_path)):
        actual = sha256_file(path)
        frozen = report.get("artifacts", {}).get(key, {})
        if (actual.sha256, actual.bytes) != (frozen.get("sha256"), frozen.get("bytes")):
            raise ValueError(f"EQ {key} artifact hash mismatch")
    allocations = _read_allocations(allocation_path)
    if len(allocations) != int(report.get("accepted_classes", -1)):
        raise ValueError("EQ allocation count does not match materialization report")
    if sum(int(row["occurrence_count"]) for row in allocations) != int(
        report.get("accepted_candidate_occurrences", -1)
    ):
        raise ValueError("EQ allocation occurrence count drift")
    if any(row["campaign_id"] != report.get("campaign_id") for row in allocations):
        raise ValueError("EQ allocation campaign binding drift")
    tiebreak = report.get("tiebreak")
    for row in allocations:
        if row["admission_rule"] == ADVERSARIAL_RULE:
            if tiebreak is not None:
                raise ValueError("tie-break materialization re-emitted an adversarial admission")
        elif (
            tiebreak is None
            or row["admission_rule"] not in TIEBREAK_RULE_NAMES
            or row["admission_rule"] != tiebreak.get("admission_reason")
        ):
            raise ValueError(f"EQ allocation admission rule is not backed by its report: {row['flopo_id']}")
    return report, allocations


def _module_graph(
    module_path: Path, allocations: list[dict[str, str]]
) -> tuple[Graph, set[str]]:
    graph = Graph().parse(module_path.as_posix(), format="turtle")
    expected_ontology = URIRef(MODULE_IRI)
    if set(graph.subjects(RDF.type, OWL.Ontology)) != {expected_ontology}:
        raise ValueError("EQ module must have exactly its expected ontology header")
    expected_classes = {OBO + row["flopo_id"] for row in allocations}
    promoted = {
        str(subject)
        for subject in graph.subjects(MACHINE_CAMPAIGN, None)
        if isinstance(subject, URIRef) and str(subject).startswith(OBO + "FLOPO_")
    }
    if promoted != expected_classes:
        raise ValueError("EQ module classes do not exactly match allocations")
    by_iri = {OBO + row["flopo_id"]: row for row in allocations}
    for class_iri in sorted(promoted):
        cls = URIRef(class_iri)
        row = by_iri[class_iri]
        if (cls, RDF.type, OWL.Class) not in graph:
            raise ValueError(f"machine EQ resource is not an OWL class: {class_iri}")
        if len(list(graph.objects(cls, OWL.equivalentClass))) != 1:
            raise ValueError(f"machine EQ class lacks exactly one logical definition: {class_iri}")
        exact_literals = [
            (MACHINE_CAMPAIGN, row["campaign_id"]),
            (MACHINE_ITEM, row["item_id"]),
            (MACHINE_SIGNATURE, row["consensus_signature_sha256"]),
            (MACHINE_STATUS, "llm_consensus"),
        ]
        reviewers = {str(value) for value in graph.objects(cls, MACHINE_REVIEWER)}
        if reviewers != set(filter(None, row["reviewer_ids"].split("|"))):
            raise ValueError(f"machine reviewer provenance mismatch: {class_iri}")
        if row["admission_rule"] == ADVERSARIAL_RULE:
            exact_literals.append((MACHINE_ADJUDICATOR, row["adjudicator_id"]))
            if len(reviewers) < 2 or list(graph.objects(cls, MACHINE_RULE)):
                raise ValueError(f"adversarial EQ admission has wrong review provenance: {class_iri}")
        else:
            exact_literals.append((MACHINE_RULE, row["admission_rule"]))
            if len(reviewers) < 3 or list(graph.objects(cls, MACHINE_ADJUDICATOR)):
                raise ValueError(f"tie-break EQ admission must name three reviewers: {class_iri}")
        if any((cls, predicate, Literal(value)) not in graph for predicate, value in exact_literals):
            raise ValueError(f"machine EQ provenance mismatch: {class_iri}")
        if not list(graph.objects(cls, DCTERMS.source)):
            raise ValueError(f"machine EQ class lacks a source: {class_iri}")
        if list(graph.objects(cls, DCTERMS.contributor)):
            raise ValueError(f"machine EQ class must not claim a human contributor: {class_iri}")
        comments = " ".join(
            str(value).casefold() for value in graph.objects(cls, URIRef(OBO + "IAO_0000116"))
        )
        if "not human reviewed" not in comments:
            raise ValueError(f"machine EQ class lacks explicit review-status warning: {class_iri}")
        if row["curator_override"]:
            if (cls, CURATOR_OVERRIDE, Literal(row["curator_override"])) not in graph:
                raise ValueError(f"curator override provenance mismatch: {class_iri}")
            if "overridden by" not in comments:
                raise ValueError(
                    f"curator-overridden EQ class lacks an override note: {class_iri}"
                )
        elif list(graph.objects(cls, CURATOR_OVERRIDE)):
            raise ValueError(f"EQ class claims a curator override its allocation lacks: {class_iri}")

    release_graph = Graph()
    promoted_nodes = {URIRef(value) for value in promoted}
    for subject, predicate, obj in graph:
        if subject == expected_ontology:
            continue
        if isinstance(subject, URIRef) and subject not in promoted_nodes:
            continue
        release_graph.add((subject, predicate, obj))
    return release_graph, promoted


def _verify_chain(
    materializations: list[tuple[dict[str, Any], list[dict[str, str]], Path]],
) -> None:
    """Every tie-break run must reserve IDs after exactly the earlier published ledgers."""

    published: dict[tuple[str, int], Path] = {}
    for report, _allocations, allocation_path in materializations:
        tiebreak = report.get("tiebreak")
        if tiebreak is not None:
            prior = {
                (row.get("sha256"), int(row.get("bytes", -1)))
                for row in tiebreak.get("prior_allocations", [])
            }
            if not prior.issubset(published):
                raise ValueError(
                    f"{allocation_path}: tie-break prior allocations are not published earlier"
                )
        digest = sha256_file(allocation_path)
        published[(digest.sha256, digest.bytes)] = allocation_path


def _machine_registry_payload(path: Path, allocations: list[dict[str, str]]) -> str:
    existing = _read_allocations(path) if path.exists() else []
    by_proposal = {row["proposal_key"]: row for row in existing}
    by_id = {row["flopo_id"]: row for row in existing}
    for row in allocations:
        previous_proposal = by_proposal.get(row["proposal_key"])
        previous_id = by_id.get(row["flopo_id"])
        if previous_proposal is not None and previous_proposal != row:
            raise ValueError(f"EQ proposal allocation changed: {row['proposal_key']}")
        if previous_id is not None and previous_id != row:
            raise ValueError(f"EQ FLOPO identifier collision: {row['flopo_id']}")
        by_proposal[row["proposal_key"]] = row
        by_id[row["flopo_id"]] = row
    rows = sorted(by_proposal.values(), key=lambda row: int(row["flopo_id"].split("_")[1]))
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=REGISTRY_FIELDS, delimiter="\t", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def update_machine_reviewed_eq_release(
    *,
    release_path: Path,
    materializations: list[tuple[Path, Path, Path]],
    machine_registry_path: Path,
    flopo_registry_path: Path,
    retained_module_dir: Path | None,
    release_date: str,
) -> dict[str, Any]:
    """Publish ``(report, allocations, module)`` triples, in allocation order."""

    date.fromisoformat(release_date)
    if not materializations:
        raise ValueError("at least one EQ materialization is required")
    paths = [release_path, machine_registry_path, flopo_registry_path]
    for triple in materializations:
        paths.extend(triple)
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("machine EQ publication paths must be distinct")

    verified = []
    allocations: list[dict[str, str]] = []
    release_graph = Graph()
    classes: set[str] = set()
    for report_path, allocation_path, module_path in materializations:
        report, rows = _verify_materialization(report_path, allocation_path, module_path)
        graph, promoted = _module_graph(module_path, rows)
        if promoted & classes:
            raise ValueError("EQ materializations allocate overlapping identifiers")
        verified.append((report, rows, allocation_path))
        allocations.extend(rows)
        classes |= promoted
        for triple in graph:
            release_graph.add(triple)
    _verify_chain(verified)
    for key in ("proposal_key", "eq_signature", "item_id"):
        values = [(row["campaign_id"], row[key]) for row in allocations]
        if len(values) != len(set(values)):
            raise ValueError(f"EQ materializations repeat {key}")
    fragment, class_count = _graph_fragment(release_graph, node_id_prefix="FLOPOMachineEQ_")
    if class_count != len(classes):
        raise ValueError("EQ release fragment contains unexpected FLOPO classes")

    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    for class_iri in classes:
        if f'"{class_iri}"' in text:
            raise ValueError(f"allocated EQ class already occurs outside generated block: {class_iri}")
    text = _ensure_flopoann_namespace(text)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment.strip()}\n{END_MARKER}\n"
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
                raise ValueError(f"published EQ class is missing: {class_iri}")
            if list(check.objects(cls, DCTERMS.contributor)):
                raise ValueError(f"published machine class acquired contributor metadata: {class_iri}")
        machine_temp.write_text(machine_payload, encoding="utf-8")
        write_registry_tsv(build_registry(release_temp), registry_temp)
        with registry_temp.open(encoding="utf-8", newline="") as handle:
            registry_rows = list(csv.DictReader(handle, delimiter="\t"))
        by_id = {row["flopo_iri"].rsplit("/", 1)[-1]: row for row in registry_rows}
        for row in allocations:
            published = by_id.get(row["flopo_id"])
            if published is None:
                raise ValueError(f"regenerated FLOPO registry omitted {row['flopo_id']}")
            if published["signature"] != row["eq_signature"]:
                raise ValueError(
                    f"regenerated signature drift for {row['flopo_id']}: {published['signature']}"
                )
        active = [
            row["signature"]
            for row in registry_rows
            if row["deprecated"] not in {"1", "true", "True"}
            and row["signature"].startswith("EQ|")
        ]
        new_signatures = {row["eq_signature"] for row in allocations}
        if any(active.count(signature) != 1 for signature in new_signatures):
            raise ValueError("published EQ signature duplicates an active FLOPO class")
        os.replace(release_temp, release_path)
        os.replace(machine_temp, machine_registry_path)
        os.replace(registry_temp, flopo_registry_path)
    finally:
        release_temp.unlink(missing_ok=True)
        machine_temp.unlink(missing_ok=True)
        registry_temp.unlink(missing_ok=True)

    retained = []
    if retained_module_dir is not None:
        retained_module_dir.mkdir(parents=True, exist_ok=True)
        names = [f"flopo-{module_path.name}" for _r, _a, module_path in materializations]
        if len(names) != len(set(names)):
            raise ValueError("retained EQ module names collide")
        for name, (_report_path, _allocation_path, module_path) in zip(names, materializations):
            target = retained_module_dir / name
            target.write_bytes(module_path.read_bytes())
            retained.append(sha256_file(target).model_dump(mode="json"))
    rules: dict[str, int] = {}
    for row in allocations:
        rules[row["admission_rule"]] = rules.get(row["admission_rule"], 0) + 1
    return {
        "schema_version": "flopo-machine-reviewed-eq-publication-v1",
        "campaign_ids": sorted({row["campaign_id"] for row in allocations}),
        "classes": len(classes),
        "classes_by_admission_rule": dict(sorted(rules.items())),
        "flopo_id_range": [
            min(row["flopo_id"] for row in allocations),
            max(row["flopo_id"] for row in allocations),
        ],
        "candidate_occurrences_covered": sum(int(row["occurrence_count"]) for row in allocations),
        "human_reviewed": False,
        "release": sha256_file(release_path).model_dump(mode="json"),
        "machine_registry": sha256_file(machine_registry_path).model_dump(mode="json"),
        "flopo_registry": sha256_file(flopo_registry_path).model_dump(mode="json"),
        "retained_modules": retained,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--materialization",
        nargs=3,
        action="append",
        type=Path,
        required=True,
        metavar=("REPORT", "ALLOCATIONS", "MODULE"),
        help="A verified EQ-class materialization; repeat in allocation order.",
    )
    parser.add_argument(
        "--machine-registry",
        type=Path,
        default=Path("config/flopo_machine_eq_id_registry.tsv"),
    )
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--retained-module-dir", type=Path, default=Path("ontology"))
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()
    result = update_machine_reviewed_eq_release(
        release_path=args.release,
        materializations=[tuple(item) for item in args.materialization],
        machine_registry_path=args.machine_registry,
        flopo_registry_path=args.flopo_registry,
        retained_module_dir=args.retained_module_dir,
        release_date=args.date,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
