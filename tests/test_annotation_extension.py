from __future__ import annotations

import copy
import json

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef


def _disjunction() -> dict:
    return {
        "po_id": "PO_0009046",
        "pato_id": "PATO_0000014",
        "value_operator": "one_of",
        "value_terms": ["PATO_0000322", "PATO_0000320"],
        "source_text": "red or green",
        "source_start": 8,
        "source_end": 20,
    }


def test_annotation_class_identity_is_logical_not_source_scoped():
    from flopo2.owl.annotation_class import annotation_class_iri

    first = _disjunction()
    second = copy.deepcopy(first)
    second["value_terms"].reverse()
    second.update(
        {
            "source_text": "usually green or red",
            "source_start": 50,
            "source_end": 70,
            "frequency_qualifier": "usually",
            "modality_text": "usually",
            "confidence": 0.61,
            "extractor": "another-extractor",
        }
    )
    assert annotation_class_iri(first) == annotation_class_iri(second)

    different_bearer = copy.deepcopy(first)
    different_bearer["po_id"] = "PO_0025034"
    assert annotation_class_iri(first) != annotation_class_iri(different_bearer)

    numeric = {
        "po_id": "PO_0009052",
        "pato_id": "PATO_0000122",
        "value_low": 5,
        "value_high": 10,
        "unit": "mm",
    }
    normalized_numeric = {
        **numeric,
        "value_low": "5.0",
        "value_high": "10.00",
        "unit": "UO:0000016",
        "source_text": "usually 5–10 millimetres",
        "frequency_qualifier": "usually",
    }
    assert annotation_class_iri(numeric) == annotation_class_iri(normalized_numeric)


def test_bearer_context_quality_is_part_of_fac_identity_without_changing_empty_identity():
    from flopo2.owl.annotation_class import (
        annotation_class_iri,
        annotation_class_signature,
    )

    baseline = {"po_id": "PO_0009025", "pato_id": "PATO_0000320"}
    explicit_empty = {**baseline, "bearer_context_qualities": []}
    young = {**baseline, "bearer_context_qualities": ["PATO:0000309"]}
    reordered_duplicate = {
        **baseline,
        "bearer_context_qualities": ["PATO_0000309", "PATO:0000309"],
    }

    assert annotation_class_iri(baseline) == annotation_class_iri(explicit_empty)
    assert annotation_class_iri(young) != annotation_class_iri(baseline)
    assert annotation_class_iri(young) == annotation_class_iri(reordered_duplicate)
    assert annotation_class_signature(baseline).get("bearer_context_qualities") is None
    assert annotation_class_signature(young)["bearer_context_qualities"] == [
        "http://purl.obolibrary.org/obo/PATO_0000309"
    ]


def test_bearer_context_quality_rejects_non_pato_and_primary_duplicates():
    import pytest

    from flopo2.owl.annotation_class import annotation_class_iri

    with pytest.raises(ValueError, match="must be a PATO class"):
        annotation_class_iri(
            {
                "po_id": "PO_0009025",
                "pato_id": "PATO_0000320",
                "bearer_context_qualities": ["PO_0009025"],
            }
        )
    with pytest.raises(ValueError, match="duplicates the primary"):
        annotation_class_iri(
            {
                "po_id": "PO_0009025",
                "pato_id": "PATO_0000320",
                "bearer_context_qualities": ["PATO:0000320"],
            }
        )


def test_bearer_context_quality_compiles_inside_same_bearer(tmp_path):
    from rdflib import OWL, RDF, Graph, URIRef

    from flopo2.owl.annotation_class import annotation_class_iri
    from flopo2.owl.annotation_extension import build_annotation_extension

    assertion = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000320",
        "bearer_context_qualities": ["PATO_0000309"],
        "source_text": "Young leaves green",
        "source_start": 0,
        "source_end": 18,
    }
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "one.xml",
                "taxon": "Planta exemplar",
                "text": "Young leaves green.",
                "assertions": [assertion],
            }
        )
        + "\n"
    )
    extension = tmp_path / "extension.ttl"
    build_annotation_extension(
        source,
        extension,
        include_imports=False,
        output_format="turtle",
    )
    graph = Graph().parse(extension)
    has_quality = URIRef("http://purl.obolibrary.org/obo/RO_0000053")
    fillers = {
        value
        for restriction in graph.subjects(OWL.onProperty, has_quality)
        for value in graph.objects(restriction, OWL.someValuesFrom)
    }
    assert URIRef("http://purl.obolibrary.org/obo/PATO_0000320") in fillers
    assert URIRef("http://purl.obolibrary.org/obo/PATO_0000309") in fillers
    assert (
        URIRef(annotation_class_iri(assertion)),
        RDF.type,
        OWL.Class,
    ) in graph


def test_scoped_negation_changes_fac_identity_and_owl_scope(tmp_path):
    from flopo2.owl.annotation_class import annotation_class_iri, annotation_class_signature
    from flopo2.owl.annotation_extension import build_annotation_extension

    base = {
        "po_id": "PO_0009025",
        "pato_id": "PATO_0000453",
        "negated": True,
        "source_text": "not glabrous",
    }
    quality = {**base, "negation_scope": "quality"}
    absence = {**base, "negation_scope": "absence"}
    assert annotation_class_iri(quality) != annotation_class_iri(absence)
    assert annotation_class_signature(quality)["negation_scope"] == "quality"

    source = tmp_path / "negated.jsonl"
    source.write_text(
        "\n".join(
            json.dumps(
                {
                    "source": "flora-test",
                    "source_id": f"{scope}.xml",
                    "taxon": "Planta exemplar",
                    "text": "Leaves not glabrous.",
                    "assertions": [{**row, "source_start": 7, "source_end": 19}],
                }
            )
            for scope, row in (("quality", quality), ("absence", absence))
        )
        + "\n"
    )
    extension = tmp_path / "negated.ttl"
    build_annotation_extension(source, extension, include_imports=False, output_format="turtle")
    graph = Graph().parse(extension)
    has_part = URIRef("http://purl.obolibrary.org/obo/BFO_0000051")
    has_quality = URIRef("http://purl.obolibrary.org/obo/RO_0000053")
    complement_targets = list(graph.objects(None, OWL.complementOf))
    assert any((target, OWL.onProperty, has_quality) in graph for target in complement_targets)
    assert any((target, OWL.onProperty, has_part) in graph for target in complement_targets)


def test_developmental_stage_context_is_fac_only_and_temporal(tmp_path):
    from flopo2.owl.annotation_class import annotation_class_iri, annotation_class_signature
    from flopo2.owl.annotation_extension import build_annotation_extension

    baseline = {"po_id": "PO_0009046", "pato_id": "PATO_0000322"}
    staged = {
        **baseline,
        "developmental_stage_contexts": [
            {
                "stage_term": "PO_0007016",
                "stage_text": "at flowering",
                "temporal_relation": "present_during",
            }
        ],
    }
    assert annotation_class_iri(staged) != annotation_class_iri(baseline)
    assert "developmental_stage_restrictions" not in annotation_class_signature(baseline)
    assert annotation_class_signature(staged)["developmental_stage_restrictions"][0][
        "fillers"
    ] == [{"term": "http://purl.obolibrary.org/obo/PO_0007016"}]

    source = tmp_path / "staged.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "stage.xml",
                "taxon": "Planta exemplar",
                "text": "Flowers red at flowering.",
                "assertions": [
                    {
                        **staged,
                        "source_text": "red at flowering",
                        "source_start": 8,
                        "source_end": 24,
                    }
                ],
            }
        )
        + "\n"
    )
    extension = tmp_path / "staged.ttl"
    stats = build_annotation_extension(
        source, extension, include_imports=False, output_format="turtle"
    )
    graph = Graph().parse(extension)
    present_during = URIRef(
        "https://w3id.org/flopo/annotation/present_during_developmental_stage"
    )
    stage = URIRef("http://purl.obolibrary.org/obo/PO_0007016")
    assert stats["developmental_stage_classes"] == 1
    assert any(
        (restriction, OWL.someValuesFrom, stage) in graph
        for restriction in graph.subjects(OWL.onProperty, present_during)
    )


def test_unqualified_accepted_negation_is_a_flora_universal_axiom(tmp_path):
    from flopo2.owl.assertions import FLOPOANN, build_assertion_ontology

    text = "Leaves not glabrous."
    source = tmp_path / "negated-source.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "negated.xml",
                "taxon": "Planta exemplar",
                "text": text,
                "assertions": [
                    {
                        "po_id": "PO_0009025",
                        "pato_id": "PATO_0000453",
                        "negated": True,
                        "negation_scope": "quality",
                        "source_text": "not glabrous",
                        "source_start": 7,
                        "source_end": 19,
                        "extractor": "test",
                        "composition": {"status": "accept"},
                        "gate": {"status": "accepted"},
                    }
                ],
            }
        )
        + "\n"
    )
    output = tmp_path / "source.ttl"
    stats = build_assertion_ontology(source, output, include_imports=False)
    graph = Graph().parse(output)
    assert stats["strict_axioms"] == 1
    assert Literal("strict_taxon_axiom") in graph.objects(None, FLOPOANN.logical_status)
    assert list(graph.triples((None, RDFS.subClassOf, None)))


def test_annotation_extension_deduplicates_and_source_module_links_by_iri(tmp_path):
    from flopo2.owl.annotation_class import ANNOTATION_CLASS_BASE
    from flopo2.owl.annotation_extension import build_annotation_extension
    from flopo2.owl.assertions import FLOPOANN, build_assertion_ontology

    text = "Flowers red or green. Usually flowers are green or red."
    first = _disjunction()
    first.update(
        {
            "extractor": "test",
            "composition": {"status": "accept"},
            "gate": {"status": "accepted"},
        }
    )
    second = copy.deepcopy(first)
    second.update(
        {
            "value_terms": ["PATO_0000320", "PATO_0000322"],
            "source_text": "green or red",
            "source_start": 42,
            "source_end": 54,
            "frequency_qualifier": "usually",
            "modality_text": "Usually",
        }
    )
    source = tmp_path / "source.jsonl"
    source.write_text(
        json.dumps(
            {
                "source": "flora-test",
                "source_id": "one.xml",
                "taxon": "Planta exemplar",
                "text": text,
                "assertions": [first, second],
            }
        )
        + "\n"
    )
    annotated = tmp_path / "annotated.jsonl"
    registry = tmp_path / "registry.tsv"
    extension = tmp_path / "extension.ttl"
    stats = build_annotation_extension(
        source,
        extension,
        annotated_jsonl=annotated,
        registry_tsv=registry,
        include_imports=False,
        output_format="turtle",
    )
    assert stats["assertions"] == 2
    assert stats["annotation_classes"] == 1
    assert stats["reused_class_links"] == 1

    rows = [json.loads(line) for line in annotated.read_text().splitlines()]
    class_iris = {
        assertion["phenotype_class_iri"] for assertion in rows[0]["assertions"]
    }
    assert len(class_iris) == 1
    class_iri = class_iris.pop()
    assert class_iri.startswith(ANNOTATION_CLASS_BASE + "FAC_")
    assert "http://purl.obolibrary.org/obo/FLOPO_" not in class_iri
    assert len(registry.read_text().splitlines()) == 2

    extension_graph = Graph().parse(extension)
    phenotype_class = URIRef(class_iri)
    assert (phenotype_class, RDF.type, OWL.Class) in extension_graph
    assert list(extension_graph.objects(phenotype_class, OWL.equivalentClass))
    assert list(extension_graph.subjects(OWL.unionOf, None))

    source_module = tmp_path / "source-module.ttl"
    source_stats = build_assertion_ontology(
        annotated,
        source_module,
        include_imports=False,
        output_format="turtle",
    )
    source_graph = Graph().parse(source_module)
    assert source_stats["annotation_classes"] == 1
    assert source_stats["reused_annotation_class_links"] == 1
    assert len(list(source_graph.triples((None, FLOPOANN.phenotype_class, phenotype_class)))) == 2
    assert (phenotype_class, RDF.type, OWL.NamedIndividual) not in source_graph
    assert not list(source_graph.subjects(OWL.unionOf, None))
