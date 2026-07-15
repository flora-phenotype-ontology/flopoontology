#!/usr/bin/env python3
"""Build the approved FLOPO top-level and botanical support-class module."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection


OBO = Namespace("http://purl.obolibrary.org/obo/")
MODULE = URIRef(OBO + "flopo-botanical-extension.owl")
PATO = URIRef(OBO + "pato.owl")
PO = URIRef(OBO + "po.owl")
GO_MODULE = URIRef(OBO + "flopo/imports/go_import.owl")
FLOPO_ROOT = URIRef(OBO + "FLOPO_0000000")
HAS_PART = URIRef(OBO + "BFO_0000051")
PART_OF = URIRef(OBO + "BFO_0000050")
HAS_MEMBER_PART = URIRef(OBO + "BFO_0000115")
HAS_CHARACTERISTIC = URIRef(OBO + "RO_0000053")
PARTICIPATES_IN = URIRef(OBO + "RO_0000056")
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
PATO_CHARACTERISTIC = URIRef(OBO + "PATO_0000001")
PATO_PROCESS_CHARACTERISTIC = URIRef(OBO + "PATO_0001236")
GO_BIOLOGICAL_PROCESS = URIRef(OBO + "GO_0008150")
CONTRIBUTOR = URIRef("https://orcid.org/0000-0001-8149-5890")

EXISTING_KEYS = {
    "TOP:flora_phenotype": "FLOPO_0000000",
    "TOP:whole_plant_phenotype": "FLOPO_0000089",
    "TOP:plant_substance_phenotype": "FLOPO_0900047",
    "LOCAL:trifoliolate_leaf": "FLOPO_0900067",
    "LOCAL:latex_phenotype": "FLOPO_0900048",
    "LOCAL:whole_plant_growth_form": "FLOPO_0900032",
}


def iri(curie: str) -> URIRef:
    return URIRef(OBO + curie.replace(":", "_", 1))


def _rows(path: Path, key: str) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    indexed = {row[key]: row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {key} in {path}")
    return indexed


def _copy_bnode_subgraph(source: Graph, target: Graph, subject) -> None:
    for predicate, obj in source.predicate_objects(subject):
        target.add((subject, predicate, obj))
        if isinstance(obj, BNode):
            _copy_bnode_subgraph(source, target, obj)


def _remove_orphan_bnode_subgraphs(graph: Graph) -> None:
    """Drop copied anonymous expressions after their named linking axiom was replaced."""

    reachable = {
        obj
        for subject, _predicate, obj in graph
        if isinstance(subject, URIRef) and isinstance(obj, BNode)
    }
    # Anonymous subclass expressions can themselves be roots of a GCI.
    reachable.update(
        subject
        for subject in graph.subjects(RDFS.subClassOf, None)
        if isinstance(subject, BNode)
    )
    frontier = list(reachable)
    while frontier:
        subject = frontier.pop()
        for _subject, _predicate, obj in graph.triples((subject, None, None)):
            if isinstance(obj, BNode) and obj not in reachable:
                reachable.add(obj)
                frontier.append(obj)
    all_bnodes = {
        node
        for triple in graph
        for node in triple
        if isinstance(node, BNode)
    }
    for orphan in all_bnodes - reachable:
        graph.remove((orphan, None, None))


def _restriction(
    graph: Graph,
    prop: URIRef,
    *,
    some: URIRef | BNode | None = None,
    only: URIRef | BNode | None = None,
    exactly: int | None = None,
    on_class: URIRef | None = None,
    name: str,
) -> BNode:
    node = BNode(name)
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, prop))
    supplied = sum(value is not None for value in (some, only, exactly))
    if supplied != 1:
        raise ValueError("restriction needs exactly one quantifier")
    if some is not None:
        graph.add((node, OWL.someValuesFrom, some))
    elif only is not None:
        graph.add((node, OWL.allValuesFrom, only))
    else:
        graph.add(
            (
                node,
                OWL.qualifiedCardinality,
                Literal(exactly, datatype=XSD.nonNegativeInteger),
            )
        )
        if on_class is None:
            raise ValueError("qualified cardinality needs owl:onClass")
        graph.add((node, OWL.onClass, on_class))
    return node


def _intersection(graph: Graph, members: list[URIRef | BNode], name: str) -> BNode:
    node = BNode(name)
    head = BNode(f"{name}_list")
    Collection(graph, head, members)
    graph.add((node, RDF.type, OWL.Class))
    graph.add((node, OWL.intersectionOf, head))
    return node


def _phenotype_target(graph: Graph, target: URIRef, name: str) -> BNode:
    part_of = _restriction(
        graph,
        PART_OF,
        some=target,
        name=f"{name}_part_of",
    )
    characteristic = _restriction(
        graph,
        HAS_CHARACTERISTIC,
        some=PATO_CHARACTERISTIC,
        name=f"{name}_characteristic",
    )
    filler = _intersection(graph, [part_of, characteristic], f"{name}_filler")
    return _restriction(graph, HAS_PART, some=filler, name=f"{name}_outer")


def _entity_quality(
    graph: Graph,
    entity: URIRef,
    quality: URIRef,
    name: str,
    extra_entity_restrictions: list[BNode] | None = None,
) -> BNode:
    characteristic = _restriction(
        graph,
        HAS_CHARACTERISTIC,
        some=quality,
        name=f"{name}_characteristic",
    )
    members: list[URIRef | BNode] = [entity, characteristic]
    members.extend(extra_entity_restrictions or [])
    filler = _intersection(graph, members, f"{name}_filler")
    return _restriction(graph, HAS_PART, some=filler, name=f"{name}_outer")


def _process_target(graph: Graph, bearer: URIRef, name: str) -> BNode:
    process_characteristic = _restriction(
        graph,
        HAS_CHARACTERISTIC,
        some=PATO_PROCESS_CHARACTERISTIC,
        name=f"{name}_process_characteristic",
    )
    process = _intersection(
        graph,
        [GO_BIOLOGICAL_PROCESS, process_characteristic],
        f"{name}_process",
    )
    participation = _restriction(
        graph,
        PARTICIPATES_IN,
        some=process,
        name=f"{name}_participation",
    )
    filler = _intersection(graph, [bearer, participation], f"{name}_filler")
    return _restriction(graph, HAS_PART, some=filler, name=f"{name}_outer")


def _source_urls(
    proposal: dict[str, str], evidence: dict[str, dict[str, str]]
) -> set[URIRef]:
    urls: set[URIRef] = set()
    for token in proposal["evidence"].replace(";", "|").split("|"):
        token = token.strip()
        if token in evidence and evidence[token]["url"]:
            urls.add(URIRef(evidence[token]["url"]))
        elif token.startswith("http://") or token.startswith("https://"):
            urls.add(URIRef(token))
    return urls


def build_module(
    release_path: Path,
    proposals_path: Path,
    id_registry_path: Path,
    evidence_path: Path,
    release_date: str,
) -> tuple[Graph, set[URIRef]]:
    proposals = _rows(proposals_path, "proposal_key")
    id_rows = _rows(id_registry_path, "proposal_key")
    evidence = _rows(evidence_path, "evidence_id")
    accepted_keys = {
        key
        for key, row in proposals.items()
        if row["action"]
        not in {
            "reuse_imported_support_root",
            "reuse_imported_support_branch",
            "add_pinned_support_module",
            "new_extension_policy",
        }
    }
    available_keys = set(id_rows) | set(EXISTING_KEYS)
    if accepted_keys != available_keys:
        raise ValueError(
            "proposal/identifier mismatch: "
            f"missing={sorted(accepted_keys - available_keys)}, "
            f"extra={sorted(available_keys - accepted_keys)}"
        )

    ids = {key: iri(row["flopo_id"]) for key, row in id_rows.items()}
    ids.update({key: iri(curie) for key, curie in EXISTING_KEYS.items()})
    assigned = [str(value) for value in ids.values()]
    if len(assigned) != len(set(assigned)):
        raise ValueError("duplicate FLOPO identifier assignment")
    for key, row in id_rows.items():
        if proposals[key]["preferred_label"] != row["label"]:
            raise ValueError(f"label mismatch for {key}")

    source = Graph()
    source.parse(release_path.as_posix())
    graph = Graph()
    graph.bind("dcterms", DCTERMS)
    graph.bind("obo", OBO)
    graph.bind("owl", OWL)
    graph.bind("rdf", RDF)
    graph.bind("rdfs", RDFS)
    graph.add((MODULE, RDF.type, OWL.Ontology))
    graph.add((MODULE, OWL.imports, PATO))
    graph.add((MODULE, OWL.imports, PO))
    graph.add((MODULE, OWL.imports, GO_MODULE))
    graph.add((MODULE, RDFS.label, Literal("FLOPO botanical extension module", lang="en")))
    graph.add((MODULE, DCTERMS.modified, Literal(release_date, datatype=XSD.date)))
    graph.add(
        (
            MODULE,
            DCTERMS.license,
            URIRef("https://creativecommons.org/publicdomain/zero/1.0/"),
        )
    )

    modified_existing = {ids[key] for key in EXISTING_KEYS}
    for cls in modified_existing:
        _copy_bnode_subgraph(source, graph, cls)

    def annotate(key: str, *, new: bool) -> URIRef:
        row = proposals[key]
        cls = ids[key]
        graph.add((cls, RDF.type, OWL.Class))
        graph.set((cls, RDFS.label, Literal(row["preferred_label"], lang="en")))
        graph.set((cls, IAO_DEFINITION, Literal(row["textual_definition"], lang="en")))
        graph.add((cls, DCTERMS.contributor, CONTRIBUTOR))
        date_property = DCTERMS.created if new else DCTERMS.modified
        graph.set((cls, date_property, Literal(release_date, datatype=XSD.date)))
        graph.add(
            (
                cls,
                IAO_EDITOR_NOTE,
                Literal(
                    f"Approved FLOPO botanical proposal {key}; local supporting classes "
                    "remain biologically parented beneath PO or PATO rather than beneath a "
                    "provenance-only extension class.",
                    lang="en",
                ),
            )
        )
        for url in _source_urls(row, evidence):
            graph.add((cls, DCTERMS.source, url))
        return cls

    # New bearer-centric phenotype hierarchy.
    continuant = annotate("TOP:continuant_target_phenotype", new=True)
    graph.add((continuant, RDFS.subClassOf, FLOPO_ROOT))

    anatomical = annotate("TOP:anatomical_entity_phenotype", new=True)
    graph.add((anatomical, RDFS.subClassOf, continuant))
    graph.add(
        (
            anatomical,
            OWL.equivalentClass,
            _phenotype_target(graph, iri("PO:0025131"), "anatomical_entity_phenotype"),
        )
    )

    plant_structure = annotate("TOP:plant_structure_phenotype", new=True)
    graph.add((plant_structure, RDFS.subClassOf, anatomical))
    graph.add(
        (
            plant_structure,
            OWL.equivalentClass,
            _phenotype_target(graph, iri("PO:0009011"), "plant_structure_phenotype"),
        )
    )

    anatomical_space = annotate("TOP:plant_anatomical_space_phenotype", new=True)
    graph.add((anatomical_space, RDFS.subClassOf, continuant))
    graph.add(
        (
            anatomical_space,
            OWL.equivalentClass,
            _phenotype_target(graph, iri("PO:0025117"), "anatomical_space_phenotype"),
        )
    )

    aggregate = annotate("TOP:plant_material_aggregate_phenotype", new=True)
    graph.add((aggregate, RDFS.subClassOf, anatomical))

    occurrent = annotate("TOP:occurrent_target_phenotype", new=True)
    graph.add((occurrent, RDFS.subClassOf, FLOPO_ROOT))

    process = annotate("TOP:plant_process_phenotype", new=True)
    graph.add((process, RDFS.subClassOf, occurrent))
    graph.add(
        (
            process,
            OWL.equivalentClass,
            _process_target(graph, iri("PO:0025131"), "plant_process_phenotype"),
        )
    )

    # Replace the legacy constraint whose owl:Thing filler, combined with reflexive
    # has_part, accidentally made every process with a process characteristic impossible.
    # The repaired GCI forbids only a plant anatomical bearer from directly carrying a
    # PATO process characteristic; the characteristic may correctly inhere in a GO process.
    invalid_bearer_characteristic = _restriction(
        graph,
        HAS_CHARACTERISTIC,
        some=PATO_PROCESS_CHARACTERISTIC,
        name="invalid_process_characteristic_on_plant_bearer",
    )
    invalid_bearer = _intersection(
        graph,
        [iri("PO:0025131"), invalid_bearer_characteristic],
        "invalid_process_characteristic_bearer",
    )
    invalid_phenotype = _restriction(
        graph,
        HAS_PART,
        some=invalid_bearer,
        name="invalid_process_characteristic_phenotype",
    )
    graph.add((invalid_phenotype, RDFS.subClassOf, OWL.Nothing))

    # Existing hierarchy roots receive their approved structural parents.
    root = annotate("TOP:flora_phenotype", new=False)
    graph.set((root, RDFS.label, Literal("flora phenotype", lang="en")))

    whole_plant = annotate("TOP:whole_plant_phenotype", new=False)
    graph.remove((whole_plant, RDFS.subClassOf, None))
    graph.add((whole_plant, RDFS.subClassOf, anatomical))

    plant_substance = annotate("TOP:plant_substance_phenotype", new=False)
    graph.remove((plant_substance, RDFS.subClassOf, None))
    graph.add((plant_substance, RDFS.subClassOf, anatomical))

    # FLOPO-local qualities and their composed phenotypes.
    trifoliolate_quality = annotate("LOCAL:trifoliolate_quality", new=True)
    graph.add((trifoliolate_quality, RDFS.subClassOf, iri("PATO:0001555")))

    bifoliolate_quality = annotate("LOCAL:bifoliolate_quality", new=True)
    graph.add((bifoliolate_quality, RDFS.subClassOf, iri("PATO:0001555")))

    trifoliolate_leaf = annotate("LOCAL:trifoliolate_leaf", new=False)
    graph.remove((trifoliolate_leaf, RDFS.subClassOf, None))
    graph.remove((trifoliolate_leaf, OWL.equivalentClass, None))
    graph.add((trifoliolate_leaf, RDFS.subClassOf, iri("FLOPO:0000004")))
    trifoliolate_count = _restriction(
        graph,
        HAS_PART,
        exactly=3,
        on_class=iri("PO:0020049"),
        name="trifoliolate_leaflet_count",
    )
    graph.add(
        (
            trifoliolate_leaf,
            OWL.equivalentClass,
            _entity_quality(
                graph,
                iri("PO:0025034"),
                trifoliolate_quality,
                "trifoliolate_leaf",
                [trifoliolate_count],
            ),
        )
    )

    bifoliolate_leaf = annotate("LOCAL:bifoliolate_leaf", new=True)
    graph.add((bifoliolate_leaf, RDFS.subClassOf, iri("FLOPO:0000004")))
    bifoliolate_count = _restriction(
        graph,
        HAS_PART,
        exactly=2,
        on_class=iri("PO:0020049"),
        name="bifoliolate_leaflet_count",
    )
    graph.add(
        (
            bifoliolate_leaf,
            OWL.equivalentClass,
            _entity_quality(
                graph,
                iri("PO:0025034"),
                bifoliolate_quality,
                "bifoliolate_leaf",
                [bifoliolate_count],
            ),
        )
    )

    stinging = annotate("LOCAL:stinging_disposition", new=True)
    graph.add((stinging, RDFS.subClassOf, iri("PATO:0001727")))

    stinging_trichome = annotate("LOCAL:stinging_trichome", new=True)
    graph.add((stinging_trichome, RDFS.subClassOf, iri("FLOPO:0000355")))
    graph.add(
        (
            stinging_trichome,
            OWL.equivalentClass,
            _entity_quality(
                graph,
                iri("PO:0000282"),
                stinging,
                "stinging_trichome",
            ),
        )
    )

    # Local entities and their phenotype branches.
    foliage = annotate("LOCAL:foliage_entity", new=True)
    graph.add((foliage, RDFS.subClassOf, iri("PO:0025131")))
    graph.add(
        (
            foliage,
            RDFS.subClassOf,
            _restriction(
                graph,
                HAS_MEMBER_PART,
                some=iri("PO:0025034"),
                name="foliage_has_leaf_member",
            ),
        )
    )
    graph.add(
        (
            foliage,
            RDFS.subClassOf,
            _restriction(
                graph,
                HAS_MEMBER_PART,
                only=iri("PO:0025034"),
                name="foliage_only_leaf_members",
            ),
        )
    )

    foliage_phenotype = annotate("LOCAL:foliage_phenotype", new=True)
    graph.add((foliage_phenotype, RDFS.subClassOf, aggregate))
    graph.add(
        (
            foliage_phenotype,
            OWL.equivalentClass,
            _phenotype_target(graph, foliage, "foliage_phenotype"),
        )
    )

    plant_latex = annotate("LOCAL:plant_latex_entity", new=True)
    graph.add((plant_latex, RDFS.subClassOf, iri("PO:0025161")))

    latex_phenotype = annotate("LOCAL:latex_phenotype", new=False)
    graph.remove((latex_phenotype, RDFS.subClassOf, None))
    graph.remove((latex_phenotype, OWL.equivalentClass, None))
    graph.add((latex_phenotype, RDFS.subClassOf, plant_substance))
    graph.add(
        (
            latex_phenotype,
            OWL.equivalentClass,
            _phenotype_target(graph, plant_latex, "latex_phenotype"),
        )
    )

    growth_form = annotate("LOCAL:whole_plant_growth_form", new=False)
    graph.add((growth_form, RDFS.subClassOf, whole_plant))

    _remove_orphan_bnode_subgraphs(graph)

    return graph, modified_existing


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--proposals",
        type=Path,
        default=Path("curation/flopo_top_level_and_local_extension_proposals.tsv"),
    )
    parser.add_argument(
        "--id-registry",
        type=Path,
        default=Path("config/flopo_botanical_id_registry.tsv"),
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=Path("curation/botanical_evidence.tsv"),
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("ontology/flopo-botanical-extension.ttl"),
    )
    parser.add_argument("--date", default="2026-07-15")
    args = parser.parse_args()
    graph, modified = build_module(
        args.release,
        args.proposals,
        args.id_registry,
        args.evidence,
        args.date,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(str(graph.serialize(format="turtle")).rstrip() + "\n", encoding="utf-8")
    print(f"classes {len(set(graph.subjects(RDF.type, OWL.Class)))}")
    print(f"modified_existing {len(modified)}")
    print(f"output {args.out}")


if __name__ == "__main__":
    main()
