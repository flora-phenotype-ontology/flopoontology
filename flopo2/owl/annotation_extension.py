"""Build the identified OWL class-expression extension used by FLOPO annotations.

The extension is deliberately outside the OBO FLOPO term namespace.  It names every distinct
OWL phenotype class expression with a stable ``https://w3id.org/flopo/annotation-class/FAC_*``
IRI.  Flora assertions and observation data can consequently annotate with one IRI while this
ontology retains the complete logical definition.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from rdflib import DCTERMS, OWL, RDF, RDFS, XSD, Graph, Literal, URIRef

from flopo2.owl.annotation_class import (
    ANNOTATION_EXTENSION_ONTOLOGY,
    annotation_class_digest,
    canonical_signature_json,
    ensure_annotation_class_iri,
)
from flopo2.owl.assertions import (
    ANNOTATION_ONTOLOGY,
    FLOPOANN,
    FLOPO_ONTOLOGY,
    _Nodes,
    _declare_vocabulary,
    _load_attributes,
    _phenotype_expression,
)
from flopo2.owl.io import serialize_ontology


LICENSE = URIRef("https://creativecommons.org/publicdomain/zero/1.0/")
EXPRESSION_DIGEST = FLOPOANN.expression_digest
CANONICAL_SIGNATURE = FLOPOANN.canonical_expression_signature
SUPPORT_COUNT = FLOPOANN.supporting_assertion_count


def _load_labels(path: Path, id_column: str = "id") -> dict[str, str]:
    if not Path(path).exists():
        return {}
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return {
            str(row.get(id_column, "")).rsplit("/", 1)[-1].replace(":", "_"): row.get(
                "label", ""
            )
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get(id_column) and row.get("label")
        }


def _label(assertion: dict, po_labels: dict[str, str], pato_labels: dict[str, str]) -> str:
    bearer_id = str(assertion.get("po_id", "") or "").replace(":", "_")
    bearer = po_labels.get(bearer_id, bearer_id)
    values = list(
        dict.fromkeys(assertion.get("value_terms", []) or assertion.get("value_term_ids", []) or [])
    )
    operator = assertion.get("value_operator", "atomic") or "atomic"
    if assertion.get("value_low") is not None or assertion.get("value_high") is not None:
        low = assertion.get("value_low")
        high = assertion.get("value_high")
        if low is not None and high is not None:
            if low == high:
                value = str(low)
            else:
                left = "[" if assertion.get("value_low_inclusive", True) else "("
                right = "]" if assertion.get("value_high_inclusive", True) else ")"
                value = f"{left}{low}–{high}{right}"
        elif low is not None:
            operator = "≥" if assertion.get("value_low_inclusive", True) else ">"
            value = f"{operator}{low}"
        else:
            operator = "≤" if assertion.get("value_high_inclusive", True) else "<"
            value = f"{operator}{high}"
        quality_id = str(assertion.get("pato_id", "") or "").replace(":", "_")
        quality = pato_labels.get(quality_id, quality_id)
        phrase = f"{quality} {value} {assertion.get('unit', '')}".strip()
    elif values:
        labels = [
            pato_labels.get(str(value).replace(":", "_"), str(value)) for value in values
        ]
        joiner = " or " if operator == "one_of" else " and "
        phrase = joiner.join(labels)
    else:
        quality_id = str(assertion.get("pato_id", "") or "").replace(":", "_")
        phrase = pato_labels.get(quality_id, quality_id)
    if assertion.get("negated", False):
        scope = assertion.get("negation_scope", "absence") or "absence"
        phrase = f"bearer not ({phrase})" if scope == "quality" else f"no bearer with ({phrase})"
    contexts = [
        pato_labels.get(str(value).replace(":", "_"), str(value))
        for value in assertion.get("bearer_context_qualities", []) or []
    ]
    context_phrase = " and ".join(contexts)
    if context_phrase:
        phrase = f"{phrase} while bearer is {context_phrase}"
    stages = [
        str(context.get("stage_term", "") or "")
        for context in assertion.get("developmental_stage_contexts", []) or []
    ]
    if stages:
        joiner = " or " if assertion.get("developmental_stage_operator") == "one_of" else " and "
        phrase = f"{phrase} present during {joiner.join(stages)}"
    return f"{bearer} {phrase} annotation phenotype".strip()


def _write_registry(
    path: Path,
    representatives: dict[str, dict],
    support: Counter[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "phenotype_class_iri",
        "annotation_class_id",
        "expression_sha256",
        "supporting_assertion_count",
        "canonical_expression_signature",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for class_iri, assertion in sorted(representatives.items()):
            writer.writerow(
                {
                    "phenotype_class_iri": class_iri,
                    "annotation_class_id": class_iri.rsplit("/", 1)[-1],
                    "expression_sha256": annotation_class_digest(assertion),
                    "supporting_assertion_count": support[class_iri],
                    "canonical_expression_signature": canonical_signature_json(assertion),
                }
            )


def build_annotation_extension(
    input_jsonl: Path,
    output_owl: Path,
    *,
    annotated_jsonl: Path | None = None,
    registry_tsv: Path | None = None,
    po_lex: Path = Path("config/po_lexicon.tsv"),
    pato_lex: Path = Path("config/pato_lexicon.tsv"),
    flopo_registry: Path = Path("config/flopo_id_registry.tsv"),
    version: str = "candidate",
    output_format: str = "ofn",
    include_imports: bool = True,
) -> dict[str, object]:
    """Identify assertions, write their extension ontology, and optionally emit linked JSONL."""

    input_jsonl = Path(input_jsonl)
    if annotated_jsonl is not None and input_jsonl.resolve() == Path(annotated_jsonl).resolve():
        raise ValueError("annotated JSONL output must be distinct from its input")

    representatives: dict[str, dict] = {}
    signatures: dict[str, str] = {}
    support: Counter[str] = Counter()
    assertions = records = 0
    annotated_handle = None
    if annotated_jsonl is not None:
        Path(annotated_jsonl).parent.mkdir(parents=True, exist_ok=True)
        annotated_handle = Path(annotated_jsonl).open("w", encoding="utf-8")
    try:
        with input_jsonl.open(encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                record["annotation_extension_iri"] = ANNOTATION_EXTENSION_ONTOLOGY
                for assertion in record.get("assertions", []) or []:
                    if str(assertion.get("cardinality", "") or "").strip():
                        raise ValueError(
                            "cannot identify an annotation class while cardinality remains "
                            "outside the OWL phenotype expression"
                        )
                    class_iri = ensure_annotation_class_iri(assertion)
                    signature = canonical_signature_json(assertion)
                    if class_iri in signatures and signatures[class_iri] != signature:
                        raise ValueError(f"annotation-class digest collision at {class_iri}")
                    signatures[class_iri] = signature
                    representatives.setdefault(class_iri, assertion.copy())
                    support[class_iri] += 1
                    assertions += 1
                if annotated_handle is not None:
                    annotated_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                records += 1
    finally:
        if annotated_handle is not None:
            annotated_handle.close()

    graph = Graph()
    graph.bind("dcterms", DCTERMS)
    graph.bind("flopoann", FLOPOANN)
    graph.bind("owl", OWL)
    ontology = URIRef(ANNOTATION_EXTENSION_ONTOLOGY)
    graph.add((ontology, RDF.type, OWL.Ontology))
    graph.add((ontology, OWL.versionInfo, Literal(version)))
    graph.add((ontology, DCTERMS.title, Literal("FLOPO annotation class extension", lang="en")))
    graph.add(
        (
            ontology,
            DCTERMS.description,
            Literal(
                "Identified OWL phenotype class expressions referenced by flora assertions "
                "and observation annotations; these identifiers are not FLOPO terms.",
                lang="en",
            ),
        )
    )
    graph.add((ontology, DCTERMS.license, LICENSE))
    if include_imports:
        graph.add((ontology, OWL.imports, FLOPO_ONTOLOGY))
        graph.add((ontology, OWL.imports, ANNOTATION_ONTOLOGY))
    _declare_vocabulary(graph)
    for prop in (
        DCTERMS.description,
        DCTERMS.identifier,
        EXPRESSION_DIGEST,
        CANONICAL_SIGNATURE,
        SUPPORT_COUNT,
    ):
        graph.add((prop, RDF.type, OWL.AnnotationProperty))

    nodes = _Nodes()
    attribute_ids = _load_attributes(pato_lex)
    po_labels = _load_labels(po_lex)
    po_labels.update(_load_labels(flopo_registry, "flopo_iri"))
    pato_labels = _load_labels(pato_lex)
    numeric = seasonal = developmental = disjunctive = 0
    for class_iri, assertion in sorted(representatives.items()):
        cls = URIRef(class_iri)
        expression, is_numeric, is_seasonal, is_disjunctive = _phenotype_expression(
            graph, nodes, assertion, attribute_ids
        )
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((cls, OWL.equivalentClass, expression))
        graph.add((cls, RDFS.label, Literal(_label(assertion, po_labels, pato_labels), lang="en")))
        graph.add((cls, RDFS.isDefinedBy, ontology))
        graph.add((cls, DCTERMS.identifier, Literal(class_iri.rsplit("/", 1)[-1])))
        graph.add((cls, EXPRESSION_DIGEST, Literal(annotation_class_digest(assertion))))
        graph.add((cls, CANONICAL_SIGNATURE, Literal(canonical_signature_json(assertion))))
        graph.add((cls, SUPPORT_COUNT, Literal(support[class_iri], datatype=XSD.integer)))
        numeric += int(is_numeric)
        seasonal += int(is_seasonal)
        developmental += int(bool(assertion.get("developmental_stage_contexts", []) or []))
        disjunctive += int(is_disjunctive)

    output_owl.parent.mkdir(parents=True, exist_ok=True)
    serialize_ontology(graph, output_owl, output_format)
    if registry_tsv is not None:
        _write_registry(Path(registry_tsv), representatives, support)
    return {
        "records": records,
        "assertions": assertions,
        "annotation_classes": len(representatives),
        "reused_class_links": assertions - len(representatives),
        "numeric_classes": numeric,
        "seasonal_classes": seasonal,
        "developmental_stage_classes": developmental,
        "disjunctive_classes": disjunctive,
        "ontology_iri": ANNOTATION_EXTENSION_ONTOLOGY,
        "triples": len(graph),
        "output": str(output_owl),
        "annotated_jsonl": str(annotated_jsonl) if annotated_jsonl is not None else None,
        "registry_tsv": str(registry_tsv) if registry_tsv is not None else None,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--annotated-jsonl", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--po-lex", type=Path, default=Path("config/po_lexicon.tsv"))
    parser.add_argument("--pato-lex", type=Path, default=Path("config/pato_lexicon.tsv"))
    parser.add_argument(
        "--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--version", default="candidate")
    parser.add_argument(
        "--format",
        choices=["ofn", "turtle", "xml", "pretty-xml", "nt", "json-ld"],
        default=None,
    )
    parser.add_argument("--no-imports", action="store_true")
    args = parser.parse_args()
    stats = build_annotation_extension(
        args.input,
        args.output,
        annotated_jsonl=args.annotated_jsonl,
        registry_tsv=args.registry,
        po_lex=args.po_lex,
        pato_lex=args.pato_lex,
        flopo_registry=args.flopo_registry,
        version=args.version,
        output_format=args.format
        or ("ofn" if args.output.suffix.lower() == ".ofn" else "turtle"),
        include_imports=not args.no_imports,
    )
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
