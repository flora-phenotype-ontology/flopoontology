"""Promote curator-approved PO--PATO combinations into a FLOPO extension module.

The full candidate contains both reused release classes and newly allocated classes.  This
module extracts only the new classes required by an explicit curator approval table, including
their complete anonymous OWL class descriptions and links to supporting flora assertions.  It
therefore provides a small, reviewable source artifact that can be embedded into ``flopo.owl``
without reserializing the whole release.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, URIRef
from rdflib.namespace import XSD

from flopo2.ids.registry import (
    RegistryEntry,
    build_registry,
    load_registry,
    write_registry_tsv,
)
from flopo2.owl.assertions import FLOPOANN
from flopo2.owl.build import (
    ANNOTATION_PROPERTIES,
    FLOPO_SUPPORT_COUNT,
    HAS_PART,
    HAS_QUALITY,
    PART_OF,
    SUPPORTED_BY_ASSERTION,
)
from flopo2.owl.io import parse_ontology
from flopo2.owl.top_level import load_po_parents, phenotype_parent_for_po

OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-reviewed-combinations.owl")
FLOPO_ONTOLOGY = URIRef(OBO + "flopo.owl")
FLOPO_ROOT = URIRef(OBO + "FLOPO_0000000")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")
LICENSE = URIRef("https://creativecommons.org/publicdomain/zero/1.0/")
FLOPO_RE = re.compile(r"^http://purl\.obolibrary\.org/obo/FLOPO_(\d+)$")


@dataclass(frozen=True)
class Approval:
    po_id: str
    pato_id: str
    reviewer: str
    review_date: str

    @property
    def eq_signature(self) -> str:
        return f"EQ|{self.po_id}|{self.pato_id}"

    @property
    def pheno_signature(self) -> str:
        return f"PHENO|{self.po_id}"


def _load_approvals(path: Path) -> list[Approval]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError("approval table is empty")

    approvals: list[Approval] = []
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        if row.get("review_status", "").strip().lower() != "approved":
            raise ValueError(f"approval row {row_number} is not approved")
        pair = (row.get("po_id", "").strip(), row.get("pato_id", "").strip())
        if not all(pair):
            raise ValueError(f"approval row {row_number} lacks a PO or PATO identifier")
        if pair in seen:
            raise ValueError(f"duplicate approved PO--PATO pair: {pair!r}")
        seen.add(pair)
        reviewer = row.get("reviewer", "").strip()
        review_date = row.get("review_date", "").strip()
        if not reviewer or not review_date:
            raise ValueError(f"approval row {row_number} lacks reviewer provenance")
        approvals.append(Approval(*pair, reviewer, review_date))
    return approvals


def _entries_by_signature(
    entries: list[RegistryEntry], *, context: str, reject_duplicates: bool = True
) -> dict[str, RegistryEntry]:
    result: dict[str, RegistryEntry] = {}
    for entry in entries:
        if entry.signature == "OTHER":
            continue
        if entry.signature in result and reject_duplicates:
            raise ValueError(f"duplicate {context} signature: {entry.signature}")
        # The historical release has two duplicate logical signatures. IdAllocator preserves
        # its established behavior by selecting the last (highest-numbered) registry row.
        result[entry.signature] = entry
    return result


def _copy_bnode_closure(source: Graph, target: Graph, subject: URIRef | BNode) -> None:
    """Copy outbound triples and recursively copy every referenced anonymous expression."""

    pending: list[URIRef | BNode] = [subject]
    visited: set[URIRef | BNode] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        for triple in source.triples((current, None, None)):
            target.add(triple)
            if isinstance(triple[2], BNode):
                pending.append(triple[2])


def _validate_contiguous_allocation(
    baseline: list[RegistryEntry], new_entries: list[RegistryEntry]
) -> None:
    expected_start = max((entry.flopo_num for entry in baseline), default=-1) + 1
    observed = sorted(entry.flopo_num for entry in new_entries)
    expected = list(range(expected_start, expected_start + len(new_entries)))
    if observed != expected:
        raise ValueError(
            "new FLOPO identifiers are not the next contiguous reserved range: "
            f"expected {expected[:1]}..{expected[-1:]}, observed {observed[:1]}..{observed[-1:]}"
        )


def build_reviewed_extension(
    candidate_path: Path,
    registry_path: Path,
    approvals_path: Path,
    output_path: Path,
    release_date: str,
    *,
    po_path: Path = Path("ont/plant_ontology.obo"),
    reservations_path: Path | None = None,
    expected_approved: int | None = None,
    expected_new_eq: int | None = None,
    expected_new_pheno: int | None = None,
) -> dict[str, object]:
    """Build an OWL module containing exactly the newly approved reusable vocabulary."""

    approvals = _load_approvals(approvals_path)
    if expected_approved is not None and len(approvals) != expected_approved:
        raise ValueError(f"expected {expected_approved} approvals, found {len(approvals)}")

    baseline = load_registry(registry_path)
    baseline_iris = {entry.iri for entry in baseline}
    baseline_by_signature = _entries_by_signature(
        baseline, context="release registry", reject_duplicates=False
    )
    candidate_entries = build_registry(candidate_path)
    candidate_by_signature = _entries_by_signature(candidate_entries, context="candidate")

    approved_eq = {approval.eq_signature for approval in approvals}
    approved_pheno = {approval.pheno_signature for approval in approvals}
    missing = approved_eq - candidate_by_signature.keys()
    if missing:
        raise ValueError(f"approved combinations missing from candidate: {sorted(missing)!r}")

    new_entries = [entry for entry in candidate_entries if entry.iri not in baseline_iris]
    new_eq = [entry for entry in new_entries if entry.signature.startswith("EQ|")]
    new_pheno = [entry for entry in new_entries if entry.signature.startswith("PHENO|")]
    unexpected_kinds = [
        entry for entry in new_entries if entry not in new_eq and entry not in new_pheno
    ]
    if unexpected_kinds:
        raise ValueError(
            "candidate minted unsupported signature kinds: "
            f"{[entry.signature for entry in unexpected_kinds]!r}"
        )
    unexpected_eq = {entry.signature for entry in new_eq} - approved_eq
    if unexpected_eq:
        raise ValueError(f"candidate contains unapproved new EQ classes: {sorted(unexpected_eq)!r}")
    unexpected_pheno = {entry.signature for entry in new_pheno} - approved_pheno
    if unexpected_pheno:
        raise ValueError(
            f"candidate contains unapproved new phenotype parents: {sorted(unexpected_pheno)!r}"
        )
    if expected_new_eq is not None and len(new_eq) != expected_new_eq:
        raise ValueError(f"expected {expected_new_eq} new EQ classes, found {len(new_eq)}")
    if expected_new_pheno is not None and len(new_pheno) != expected_new_pheno:
        raise ValueError(
            f"expected {expected_new_pheno} new phenotype parents, found {len(new_pheno)}"
        )
    _validate_contiguous_allocation(baseline, new_entries)
    po_parents = load_po_parents(po_path)

    candidate = parse_ontology(candidate_path)
    module = Graph()
    module.bind("dcterms", DCTERMS)
    module.bind("flopoann", FLOPOANN)
    module.bind("obo", OBO)
    module.bind("owl", OWL)
    module.bind("rdf", RDF)
    module.bind("rdfs", RDFS)
    module.bind("xsd", XSD)

    module.add((MODULE, RDF.type, OWL.Ontology))
    module.add((MODULE, OWL.versionInfo, Literal(release_date)))
    module.add(
        (
            MODULE,
            DCTERMS.title,
            Literal("Curator-approved FLOPO PO--PATO combinations", lang="en"),
        )
    )
    module.add(
        (
            MODULE,
            DCTERMS.description,
            Literal(
                "Reusable flora phenotypes promoted after explicit curator review of "
                "PO--PATO combinations and their extracted source evidence.",
                lang="en",
            ),
        )
    )
    module.add((MODULE, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
    module.add((MODULE, DCTERMS.license, LICENSE))

    reviewers = {approval.reviewer for approval in approvals}
    review_dates = {approval.review_date for approval in approvals}
    if review_dates != {release_date}:
        raise ValueError(
            f"release date {release_date} does not match approval dates {sorted(review_dates)!r}"
        )
    for reviewer in sorted(reviewers):
        module.add((MODULE, DCTERMS.contributor, URIRef(reviewer)))

    source_value = Literal(approvals_path.as_posix())
    promoted_pheno_parents: dict[str, str] = {}
    for entry in new_entries:
        cls = URIRef(entry.iri)
        _copy_bnode_closure(candidate, module, cls)
        if entry.signature.startswith("PHENO|"):
            bearer = entry.signature.split("|", 1)[1]
            expected_parent = URIRef(OBO + phenotype_parent_for_po(bearer, po_parents))
            named_parents = {
                parent
                for parent in module.objects(cls, RDFS.subClassOf)
                if isinstance(parent, URIRef)
            }
            if named_parents != {FLOPO_ROOT}:
                raise ValueError(
                    f"new phenotype parent {entry.iri} must have exactly the candidate "
                    f"root parent before reclassification; found {sorted(map(str, named_parents))!r}"
                )
            module.remove((cls, RDFS.subClassOf, FLOPO_ROOT))
            module.add((cls, RDFS.subClassOf, expected_parent))
            promoted_pheno_parents[entry.iri] = str(expected_parent)
        for reviewer in sorted(reviewers):
            module.add((cls, DCTERMS.contributor, URIRef(reviewer)))
        module.add((cls, DCTERMS.created, Literal(release_date, datatype=XSD.date)))
        module.add((cls, DCTERMS.source, source_value))

    # The extension is independently parseable and OWL-DL checkable without copying imported
    # PO/PATO annotations. Declare every named class used by its class axioms; existing FLOPO
    # parents are declaration-only and are distinguished from promoted definitions by the latter's
    for prop in (HAS_PART, PART_OF, HAS_QUALITY):
        module.add((prop, RDF.type, OWL.ObjectProperty))
    for prop in (
        *ANNOTATION_PROPERTIES,
        FLOPO_SUPPORT_COUNT,
        SUPPORTED_BY_ASSERTION,
        DCTERMS.contributor,
        DCTERMS.created,
        DCTERMS.source,
    ):
        module.add((prop, RDF.type, OWL.AnnotationProperty))

    class_positions = (
        RDFS.subClassOf,
        OWL.equivalentClass,
        OWL.someValuesFrom,
        OWL.allValuesFrom,
        RDF.first,
    )
    referenced_classes = {
        value
        for predicate in class_positions
        for value in module.objects(None, predicate)
        if isinstance(value, URIRef)
    }
    for referenced_class in referenced_classes:
        module.add((referenced_class, RDF.type, OWL.Class))
        for label in candidate.objects(referenced_class, RDFS.label):
            module.add((referenced_class, RDFS.label, label))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    module.serialize(output_path.as_posix(), format="turtle")
    if reservations_path is not None:
        write_registry_tsv(new_entries, reservations_path)

    existing_approved = sum(
        candidate_by_signature[signature].iri in baseline_iris for signature in approved_eq
    )
    new_numbers = sorted(entry.flopo_num for entry in new_entries)
    return {
        "approved_pairs": len(approvals),
        "existing_approved_eq": existing_approved,
        "new_eq": len(new_eq),
        "new_pheno": len(new_pheno),
        "total_new": len(new_entries),
        "first_flopo_num": new_numbers[0] if new_numbers else None,
        "last_flopo_num": new_numbers[-1] if new_numbers else None,
        "new_pheno_parents": promoted_pheno_parents,
        "output": str(output_path),
        "reservations": str(reservations_path) if reservations_path is not None else None,
        "baseline_signatures": len(baseline_by_signature),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path, help="pre-allocation FLOPO candidate OWL")
    parser.add_argument(
        "--registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument(
        "--approvals",
        type=Path,
        default=Path("curation/gabon-annotation-v4-po-pato-approvals.tsv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ontology/flopo-reviewed-combinations.ttl"),
    )
    parser.add_argument(
        "--reservations-output",
        type=Path,
        default=Path("config/flopo_reviewed_id_reservations.tsv"),
        help="Reserve reviewed IDs until they enter the released registry",
    )
    parser.add_argument(
        "--po", type=Path, default=Path("ont/plant_ontology.obo")
    )
    parser.add_argument("--date", required=True)
    parser.add_argument("--expected-approved", type=int)
    parser.add_argument("--expected-new-eq", type=int)
    parser.add_argument("--expected-new-pheno", type=int)
    args = parser.parse_args()
    stats = build_reviewed_extension(
        args.candidate,
        args.registry,
        args.approvals,
        args.output,
        args.date,
        po_path=args.po,
        reservations_path=args.reservations_output,
        expected_approved=args.expected_approved,
        expected_new_eq=args.expected_new_eq,
        expected_new_pheno=args.expected_new_pheno,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
