#!/usr/bin/env python3
"""Mint FLOPO value-extension classes from reviewed candidate values."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, URIRef

OBO = "http://purl.obolibrary.org/obo/"
IAO_DEF = URIRef(OBO + "IAO_0000115")
IAO_EDITOR_NOTE = URIRef(OBO + "IAO_0000116")
FLOPO_ONTOLOGY = URIRef(OBO + "flopo-value-extensions.owl")
PATO_ONTOLOGY = URIRef(OBO + "pato.owl")
PATO_QUALITY = URIRef(OBO + "PATO_0000001")
HAS_QUALITY_COMPONENT = URIRef(str(FLOPO_ONTOLOGY) + "#has_quality_component")


def next_flopo_id(registry: Path, start_floor: int = 980084) -> int:
    max_id = 0
    if registry.exists():
        with registry.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                iri = row.get("flopo_iri") or row.get("iri") or ""
                match = re.search(r"FLOPO_(\d+)", iri)
                if match:
                    max_id = max(max_id, int(match.group(1)))
    return max(max_id + 1, start_floor)


def flopo_number(flopo_id: str) -> int:
    match = re.fullmatch(r"FLOPO_(\d+)", flopo_id)
    if not match:
        raise ValueError(f"invalid FLOPO identifier: {flopo_id}")
    return int(match.group(1))


def iri(curie: str) -> URIRef:
    return URIRef(OBO + curie)


def pipe_values(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def rdf_list(graph: Graph, prefix: str, values: list[URIRef]) -> BNode | URIRef:
    """Create a deterministic RDF collection and return its head."""
    if not values:
        return RDF.nil
    nodes = [BNode(f"{prefix}_{index}") for index in range(len(values))]
    for index, (node, value) in enumerate(zip(nodes, values)):
        graph.add((node, RDF.first, value))
        graph.add((node, RDF.rest, nodes[index + 1] if index + 1 < len(nodes) else RDF.nil))
    return nodes[0]


def load_rows_by_id(path: Path, id_field: str = "flopo_id") -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    out = {row[id_field]: row for row in rows}
    if len(out) != len(rows):
        raise ValueError(f"duplicate {id_field} in {path}")
    return out


def load_pato_labels(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            row["id"]: row["label"]
            for row in csv.DictReader(handle, delimiter="\t")
        }


def load_value_id_registry(path: Path) -> dict[tuple[str, str], dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle, delimiter="\t"))
    rows = {(row["candidate_id"], row["label"]): row for row in raw_rows}
    if len(rows) != len(raw_rows):
        raise ValueError(f"duplicate candidate_id/label pair in {path}")
    ids = [row["flopo_id"] for row in raw_rows]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate flopo_id in {path}")
    for row in rows.values():
        flopo_number(row["flopo_id"])
    return rows


def write_value_id_registry(
    path: Path,
    rows: dict[tuple[str, str], dict[str, str]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda row: flopo_number(row["flopo_id"]))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["candidate_id", "flopo_id", "label"],
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(ordered)


def source_iri(source: str) -> URIRef:
    if source.startswith("DOI:"):
        return URIRef("https://doi.org/" + source.removeprefix("DOI:"))
    return URIRef(source)


def value_definition(
    label: str,
    parent_labels: list[str],
    contexts: str,
    *,
    composite: bool = False,
) -> str:
    parents = ", ".join(parent_labels)
    if composite:
        return (
            f"A composite botanical phenotype value denoting {label}, used in flora descriptions; "
            f"its component qualities are {parents}."
        )
    if parents:
        return (
            f"A botanical phenotype value denoting {label}, used in flora descriptions. "
            f"This FLOPO extension value is classified under the PATO value class(es): {parents}."
        )
    return f"A botanical phenotype value denoting {label}, used in flora descriptions."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, default=Path("config/flopo_value_candidates.tsv"))
    ap.add_argument("--registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    ap.add_argument(
        "--value-id-registry",
        type=Path,
        default=Path("config/flopo_value_id_registry.tsv"),
        help="Stable candidate-to-FLOPO identifier assignments for categorical values.",
    )
    ap.add_argument(
        "--pato-mappings",
        type=Path,
        default=Path("config/flopo_value_pato_mappings.tsv"),
    )
    ap.add_argument(
        "--axioms",
        type=Path,
        default=Path("config/flopo_value_axioms.tsv"),
    )
    ap.add_argument(
        "--pato-lexicon",
        type=Path,
        default=Path("config/pato_lexicon.tsv"),
    )
    ap.add_argument("--template-out", type=Path, default=Path("ontology/flopo-value-extensions.tsv"))
    ap.add_argument("--ttl-out", type=Path, default=Path("ontology/flopo-value-extensions.ttl"))
    ap.add_argument("--status", default="candidate")
    args = ap.parse_args()

    pato_mappings = load_rows_by_id(args.pato_mappings)
    axiom_overrides = load_rows_by_id(args.axioms)
    pato_labels = load_pato_labels(args.pato_lexicon)
    value_ids = load_value_id_registry(args.value_id_registry)
    rows = []
    candidate_ids: set[str] = set()
    current = max(
        next_flopo_id(args.registry),
        max((flopo_number(row["flopo_id"]) for row in value_ids.values()), default=0) + 1,
    )
    reserved_value_ids = {row["flopo_id"] for row in value_ids.values()}

    def assigned_flopo_id(candidate_id: str, label: str, preferred: str = "") -> str:
        nonlocal current
        if not candidate_id:
            raise ValueError(f"missing candidate_id for value {label!r}")
        key = (candidate_id, label)
        existing = value_ids.get(key)
        if existing:
            if preferred and existing["flopo_id"] != preferred:
                raise ValueError(
                    f"identifier mismatch for {candidate_id}: "
                    f"{existing['flopo_id']} != {preferred}"
                )
            return existing["flopo_id"]
        if preferred:
            flopo_id = preferred
            flopo_number(flopo_id)
            if flopo_id in reserved_value_ids:
                raise ValueError(f"value identifier already assigned: {flopo_id}")
        else:
            flopo_id = f"FLOPO_{current:07d}"
            while flopo_id in reserved_value_ids:
                current += 1
                flopo_id = f"FLOPO_{current:07d}"
            current += 1
        value_ids[key] = {
            "candidate_id": candidate_id,
            "flopo_id": flopo_id,
            "label": label,
        }
        reserved_value_ids.add(flopo_id)
        return flopo_id

    with args.candidates.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["status"] != args.status:
                continue
            parents = [p for p in row["suggested_parent_pato_ids"].split("|") if p]
            if not parents:
                continue
            flopo_id = assigned_flopo_id(row["candidate_id"], row["value_label"])
            candidate_ids.add(flopo_id)
            if flopo_id in pato_mappings:
                continue
            parent_labels = [p for p in row["suggested_parent_pato_labels"].split("|") if p]
            composite = len(parents) > 1
            output_row = {
                "flopo_id": flopo_id,
                "flopo_iri": OBO + flopo_id,
                "label": row["value_label"],
                "definition": value_definition(
                    row["value_label"],
                    parent_labels,
                    row["quality_contexts"],
                    composite=composite,
                ),
                "parent_pato_ids": "PATO_0000001" if composite else "|".join(parents),
                "parent_pato_labels": "quality" if composite else "|".join(parent_labels),
                "frequency": row["frequency"],
                "quality_contexts": row["quality_contexts"],
                "examples": row["examples"],
                "candidate_id": row["candidate_id"],
                "axiom_type": "components" if composite else "subclass",
                "logical_target_ids": "|".join(parents),
                "sources": "",
            }
            if flopo_id in axiom_overrides:
                override = axiom_overrides[flopo_id]
                if override["label"] != output_row["label"]:
                    raise ValueError(
                        f"label mismatch for {flopo_id}: "
                        f"{override['label']!r} != {output_row['label']!r}"
                    )
                parent_ids = pipe_values(override["parent_ids"])
                output_row.update({
                    "definition": override["definition"],
                    "parent_pato_ids": "|".join(parent_ids),
                    "parent_pato_labels": "|".join(
                        pato_labels.get(parent, parent) for parent in parent_ids
                    ),
                    "axiom_type": override["axiom_type"],
                    "logical_target_ids": override["logical_target_ids"],
                    "sources": override["sources"],
                })
            rows.append(output_row)

    missing_mappings = set(pato_mappings) - candidate_ids
    if missing_mappings:
        raise ValueError(f"PATO mappings do not match candidates: {sorted(missing_mappings)}")

    # A curated axiom may introduce a component needed only as a union operand.
    for flopo_id, override in axiom_overrides.items():
        if flopo_id in candidate_ids:
            continue
        assigned_flopo_id(override["candidate_id"], override["label"], preferred=flopo_id)
        parent_ids = pipe_values(override["parent_ids"])
        rows.append({
            "flopo_id": flopo_id,
            "flopo_iri": OBO + flopo_id,
            "label": override["label"],
            "definition": override["definition"],
            "parent_pato_ids": "|".join(parent_ids),
            "parent_pato_labels": "|".join(
                pato_labels.get(parent, parent) for parent in parent_ids
            ),
            "frequency": override["frequency"],
            "quality_contexts": override["quality_contexts"],
            "examples": override["examples"],
            "candidate_id": override["candidate_id"],
            "axiom_type": override["axiom_type"],
            "logical_target_ids": override["logical_target_ids"],
            "sources": override["sources"],
        })

    rows.sort(key=lambda row: int(row["flopo_id"].removeprefix("FLOPO_")))
    local_ids = {row["flopo_id"] for row in rows}
    for row in rows:
        if row["axiom_type"] not in {"components", "related", "subclass", "union"}:
            raise ValueError(f"unsupported axiom type for {row['flopo_id']}: {row['axiom_type']}")
        targets = pipe_values(row["logical_target_ids"])
        if row["axiom_type"] == "union" and len(targets) < 2:
            raise ValueError(f"union {row['flopo_id']} needs at least two operands")
        missing_local = [
            target for target in targets
            if target.startswith("FLOPO_") and target not in local_ids
        ]
        if missing_local:
            raise ValueError(f"unknown local operands for {row['flopo_id']}: {missing_local}")

    write_value_id_registry(args.value_id_registry, value_ids)

    args.template_out.parent.mkdir(parents=True, exist_ok=True)
    with args.template_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "flopo_id", "flopo_iri", "label", "definition",
            "parent_pato_ids", "parent_pato_labels", "frequency",
            "quality_contexts", "examples", "candidate_id", "axiom_type",
            "logical_target_ids", "sources",
        ], delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    template_text = args.template_out.read_text(encoding="utf-8")
    args.template_out.write_text(
        "\n".join(line + '""' if line.endswith("\t") else line for line in template_text.splitlines())
        + "\n",
        encoding="utf-8",
    )

    graph = Graph()
    graph.bind("owl", OWL)
    graph.bind("rdfs", RDFS)
    graph.bind("obo", OBO)
    graph.bind("dcterms", DCTERMS)
    graph.add((FLOPO_ONTOLOGY, RDF.type, OWL.Ontology))
    graph.add((FLOPO_ONTOLOGY, OWL.imports, PATO_ONTOLOGY))
    # Keep this module valid OWL 2 DL when tooling validates it without resolving
    # the PATO import.  These declarations do not duplicate PATO's semantics;
    # they only type the external entities used by this graph.
    for prop in (
        IAO_DEF,
        IAO_EDITOR_NOTE,
        DCTERMS.title,
        DCTERMS.description,
        DCTERMS.license,
        DCTERMS.modified,
        DCTERMS.source,
    ):
        graph.add((prop, RDF.type, OWL.AnnotationProperty))
    referenced_classes = {
        target
        for row in rows
        for field in ("parent_pato_ids", "logical_target_ids")
        for target in pipe_values(row[field])
    }
    referenced_classes.add("PATO_0000001")
    for curie in referenced_classes:
        graph.add((iri(curie), RDF.type, OWL.Class))
    graph.add((FLOPO_ONTOLOGY, RDFS.label, Literal("FLOPO value extension module", lang="en")))
    graph.add((FLOPO_ONTOLOGY, DCTERMS.title, Literal("FLOPO value extension module", lang="en")))
    graph.add((FLOPO_ONTOLOGY, DCTERMS.description, Literal(
        "Curated botanical phenotype values retained in FLOPO after exact reusable qualities are mapped to PATO.",
        lang="en",
    )))
    graph.add((
        FLOPO_ONTOLOGY,
        DCTERMS.license,
        URIRef("https://creativecommons.org/publicdomain/zero/1.0/"),
    ))
    graph.add((FLOPO_ONTOLOGY, IAO_EDITOR_NOTE, Literal(
        "Generated from curated flora value strings that still lack exact PATO classes. "
        "Values replaced by permanent PATO terms are omitted; disjunctive values use explicit OWL unions.",
        lang="en",
    )))
    graph.add((HAS_QUALITY_COMPONENT, RDF.type, OWL.ObjectProperty))
    graph.add((HAS_QUALITY_COMPONENT, RDFS.label, Literal("has quality component", lang="en")))
    graph.add((HAS_QUALITY_COMPONENT, IAO_DEF, Literal(
        "Relates a composite FLOPO botanical value to a quality that constitutes one of its explicitly conjoined components.",
        lang="en",
    )))
    graph.add((HAS_QUALITY_COMPONENT, RDFS.domain, PATO_QUALITY))
    graph.add((HAS_QUALITY_COMPONENT, RDFS.range, PATO_QUALITY))
    for row in rows:
        cls = URIRef(row["flopo_iri"])
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, RDFS.label, Literal(row["label"], lang="en")))
        graph.add((cls, IAO_DEF, Literal(row["definition"], lang="en")))
        editor_note = (
            f"Examples: {row['examples']}. Source frequency in current candidate set: {row['frequency']}."
        )
        if row["axiom_type"] == "union":
            editor_note += (
                " The source wording leaves the alternatives unresolved; the class is therefore "
                "defined as their disjunction, not as their conjunction."
            )
        graph.add((cls, IAO_EDITOR_NOTE, Literal(
            editor_note,
            lang="en",
        )))
        for source in pipe_values(row["sources"]):
            graph.add((cls, DCTERMS.source, source_iri(source)))
        for parent in pipe_values(row["parent_pato_ids"]):
            if parent:
                graph.add((cls, RDFS.subClassOf, iri(parent)))
        if row["axiom_type"] == "union":
            union = BNode(f"{row['flopo_id']}_union")
            members = rdf_list(
                graph,
                f"{row['flopo_id']}_union_member",
                [iri(target) for target in pipe_values(row["logical_target_ids"])],
            )
            graph.add((union, OWL.unionOf, members))
            graph.add((cls, OWL.equivalentClass, union))
        elif row["axiom_type"] == "components":
            for index, target in enumerate(pipe_values(row["logical_target_ids"])):
                restriction = BNode(f"{row['flopo_id']}_component_{index}")
                graph.add((restriction, RDF.type, OWL.Restriction))
                graph.add((restriction, OWL.onProperty, HAS_QUALITY_COMPONENT))
                graph.add((restriction, OWL.someValuesFrom, iri(target)))
                graph.add((cls, RDFS.subClassOf, restriction))
        elif row["axiom_type"] == "related":
            for target in pipe_values(row["logical_target_ids"]):
                graph.add((cls, RDFS.seeAlso, iri(target)))
    turtle = str(graph.serialize(format="turtle")).rstrip() + "\n"
    args.ttl_out.write_text(turtle, encoding="utf-8")
    print(f"wrote {len(rows)} local value classes")
    print(f"mapped_to_pato {len(pato_mappings)}")
    print(f"first_id {rows[0]['flopo_id'] if rows else ''}")
    print(f"last_id {rows[-1]['flopo_id'] if rows else ''}")
    print(f"value_id_registry {args.value_id_registry}")
    print(f"template {args.template_out}")
    print(f"ttl {args.ttl_out}")


if __name__ == "__main__":
    main()
