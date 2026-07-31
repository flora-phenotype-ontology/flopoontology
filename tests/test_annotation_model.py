from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef


ROBOT_AVAILABLE = Path("tools/robot.jar").exists() and shutil.which("java") is not None


def _span(text: str, source: str) -> tuple[int, int]:
    start = text.index(source)
    return start, start + len(source)


def _write_pato(path: Path) -> Path:
    path.write_text(
        "id\tlabel\tslim\n"
        "PATO_0000014\tcolor\tattribute_slim\n"
        "PATO_0000122\tlength\tattribute_slim\n"
        "PATO_0000320\tgreen\tvalue_slim\n"
        "PATO_0000322\tred\tvalue_slim\n"
    )
    return path


def _assertion(
    text: str,
    source_text: str,
    po_id: str,
    pato_id: str,
    **extra,
) -> dict:
    start, end = _span(text, source_text)
    return {
        "po_id": po_id,
        "pato_id": pato_id,
        "source_text": source_text,
        "source_start": start,
        "source_end": end,
        "extractor": "test",
        "composition": {"status": "accept"},
        "gate": {"status": "accepted"},
        **extra,
    }


def _source_records() -> list[dict]:
    first = "Leaves green; pedicels 5-10 mm long in summer; flowers red or green."
    second = "Leaves green."
    third = "Leaves usually red."
    return [
        {
            "source": "flora-A",
            "source_id": "volume-1.xml",
            "source_segment_index": 0,
            "taxon": "Quercus alpha",
            "text": first,
            "assertions": [
                _assertion(first, "Leaves green", "PO_0025034", "PATO_0000320"),
                _assertion(
                    first,
                    "pedicels 5-10 mm long in summer",
                    "PO_0009052",
                    "PATO_0000122",
                    value_low=5,
                    value_high=10,
                    unit="mm",
                    season_contexts=[
                        {
                            "season_term": "FLOPOANN:summer_season",
                            "season_text": "summer",
                            "start": first.index("summer"),
                            "end": first.index("summer") + len("summer"),
                        }
                    ],
                ),
                _assertion(
                    first,
                    "flowers red or green",
                    "PO_0009046",
                    "PATO_0000014",
                    value_operator="one_of",
                    value_terms=["PATO_0000322", "PATO_0000320"],
                ),
            ],
        },
        {
            "source": "flora-B",
            "source_id": "volume-2.xml",
            "source_segment_index": 0,
            "taxon": "Quercus beta",
            "text": second,
            "assertions": [
                _assertion(second, "Leaves green", "PO_0025034", "PATO_0000320")
            ],
        },
        {
            "source": "flora-C",
            "source_id": "volume-3.xml",
            "source_segment_index": 0,
            "taxon": "Quercus gamma",
            "text": third,
            "assertions": [
                _assertion(
                    third,
                    "usually red",
                    "PO_0025034",
                    "PATO_0000322",
                    frequency_qualifier="usually",
                    modality_text="usually",
                )
            ],
        },
    ]


@pytest.mark.skipif(not ROBOT_AVAILABLE, reason="ROBOT/OWLAPI is not available")
def test_extracted_disjunction_passes_gate_and_is_an_ofn_object_union(tmp_path):
    from flopo2.extract.baseline import extract_segment_with_unresolved
    from flopo2.owl.annotation_extension import build_annotation_extension
    from flopo2.owl.assertions import build_assertion_ontology
    from flopo2.owl.io import parse_ontology
    from flopo2.verify.gates import (
        gate_segment,
        load_combinations,
        load_pato_attribute_terms,
    )

    record = {
        "source": "flora-test",
        "source_id": "one.xml",
        "taxon": "Quercus alpha",
        "organ": "flowers",
        "language": "en",
        "text": "Flowers red or green.",
    }
    assertions, unresolved = extract_segment_with_unresolved(record)
    assert unresolved == []
    assert len(assertions) == 1
    assertions[0]["composition"] = {"status": "accept"}
    record["assertions"] = assertions
    gated = gate_segment(
        record,
        load_combinations(),
        attribute_pato_ids=load_pato_attribute_terms(),
    )
    assertion = gated["assertions"][0]
    assert assertion["gate"]["status"] == "accepted"
    assert assertion["value_operator"] == "one_of"
    assert assertion["value_terms"] == ["PATO_0000322", "PATO_0000320"]

    source = tmp_path / "gated.jsonl"
    source.write_text(json.dumps(gated) + "\n")
    output = tmp_path / "annotation-extension.ofn"
    annotated = tmp_path / "annotated.jsonl"
    stats = build_annotation_extension(
        source,
        output,
        annotated_jsonl=annotated,
        output_format="ofn",
    )

    assert stats["disjunctive_classes"] == 1
    assert stats["annotation_classes"] == 1
    rendered = output.read_text()
    assert "ObjectUnionOf(" in rendered
    assert "Import(<https://w3id.org/flopo/annotation>)" in rendered
    assert "PATO_0000322" in rendered
    assert "PATO_0000320" in rendered
    graph = parse_ontology(output)
    ontology = URIRef(stats["ontology_iri"])
    assert (ontology, OWL.imports, URIRef("https://w3id.org/flopo/annotation")) in graph
    assert list(graph.subjects(OWL.unionOf, None))

    source_output = tmp_path / "source-assertions.ofn"
    source_stats = build_assertion_ontology(annotated, source_output, output_format="ofn")
    source_rendered = source_output.read_text()
    assert source_stats["annotation_classes"] == 1
    assert "ObjectUnionOf(" not in source_rendered
    assert "Import(<https://w3id.org/flopo/annotation-extension>)" in source_rendered


def _write_records(path: Path, records: list[dict] | None = None) -> Path:
    rows = records or _source_records()
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    return path


def test_annotation_vocabulary_parses_and_aligns_to_sio_and_envo():
    from flopo2.owl.assertions import FLOPOANN, SIO

    graph = Graph().parse("ontology/flopo-annotation-model.ttl")
    assert (FLOPOANN.SourceStatement, RDFS.subClassOf, SIO.SIO_001183) in graph
    assert (
        FLOPOANN.SeasonContext,
        RDFS.subClassOf,
        URIRef("http://purl.obolibrary.org/obo/ENVO_03000096"),
    ) in graph
    assert (FLOPOANN.present_during, RDF.type, OWL.ObjectProperty) in graph
    assert (FLOPOANN.phenotype_class, RDF.type, OWL.AnnotationProperty) in graph


def test_source_statement_ids_are_source_scoped_and_shared_within_one_span():
    from flopo2.annotation.provenance import ensure_source_statements

    base = {
        "source": "flora-A",
        "source_id": "one.xml",
        "source_segment_index": 4,
        "text": "Leaves green.",
        "assertions": [
            {"source_text": "Leaves green", "source_start": 0, "source_end": 12},
            {"source_text": "Leaves green", "source_start": 0, "source_end": 12},
        ],
    }
    first = ensure_source_statements(base)
    second = ensure_source_statements({**base, "source_id": "two.xml"})

    assert len(first["source_statements"]) == 1
    assert first["assertions"][0]["source_statement_id"] == first["assertions"][1][
        "source_statement_id"
    ]
    assert first["source_statements"][0]["verbatim_text"] == "Leaves green"
    assert first["source_statements"][0]["statement_id"] != second["source_statements"][0][
        "statement_id"
    ]


def test_provenance_normalizer_retains_explicit_unlinked_statements():
    from flopo2.annotation.provenance import ensure_source_statements

    record = {
        "source": "flora-A",
        "source_id": "one.xml",
        "source_segment_index": 0,
        "text": "Leaves green. Bark grey.",
        "source_statements": [
            {
                "statement_id": "curated-bark-statement",
                "verbatim_text": "Bark grey",
                "start": 14,
                "end": 23,
            }
        ],
        "assertions": [
            {"source_text": "Leaves green", "source_start": 0, "source_end": 12}
        ],
    }
    normalized = ensure_source_statements(record)
    assert [statement["verbatim_text"] for statement in normalized["source_statements"]] == [
        "Bark grey",
        "Leaves green",
    ]


def test_legacy_normalized_modality_recovers_the_exact_source_cue():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "Pétales environ 4 mm de longueur."
    record = {
        "source": "flora-A",
        "source_id": "one.xml",
        "text": text,
        "assertions": [
            {
                "source_text": "environ 4 mm de longueur",
                "source_start": 8,
                "source_end": 32,
                "modifier": "approximately",
                "modality_text": "approximately",
            }
        ],
    }
    assertion = ensure_source_statements(record)["assertions"][0]
    assert assertion["value_qualifier"] == "approximately"
    assert assertion["modality_text"] == "environ"


def test_provenance_statement_expands_to_bearer_modality_and_stage():
    from flopo2.annotation.provenance import ensure_source_statements

    text = "Leaflets normally not acuminate at flowering."
    flowering_start = text.index("flowering")
    record = {
        "source": "flora-A",
        "source_id": "qualified.xml",
        "text": text,
        "assertions": [
            {
                "source_text": "not acuminate",
                "source_start": text.index("not"),
                "source_end": text.index("not") + len("not acuminate"),
                "raw_entity_text": "Leaflets",
                "frequency_qualifier": "usually",
                "modality_text": "normally",
                "developmental_stage_contexts": [
                    {
                        "stage_term": "PO_0007016",
                        "stage_text": "flowering",
                        "start": flowering_start,
                        "end": flowering_start + len("flowering"),
                    }
                ],
            }
        ],
    }

    normalized = ensure_source_statements(record)
    statement = normalized["source_statements"][0]
    assert statement["verbatim_text"] == "Leaflets normally not acuminate at flowering"
    assert statement["start"] == 0
    assert statement["end"] == text.index(".")


def test_legacy_jsonl_upgrade_streams_lossless_source_statements(tmp_path):
    from flopo2.annotation import upgrade_jsonl

    source = _write_records(tmp_path / "legacy.jsonl")
    output = tmp_path / "upgraded.jsonl"
    stats = upgrade_jsonl(source, output, limit=2)
    records = [json.loads(line) for line in output.read_text().splitlines()]

    assert stats == {
        "segments": 2,
        "assertions": 4,
        "source_statements": 4,
        "qualified_assertions": 0,
        "seasonal_assertions": 1,
        "input": str(source),
        "output": str(output),
    }
    assert len(records) == 2
    assert records[0]["source_segment_index"] == 0
    assert all(
        assertion["source_statement_id"]
        in {statement["statement_id"] for statement in record["source_statements"]}
        for record in records
        for assertion in record["assertions"]
    )


def test_linkml_contract_has_structured_provenance_modality_and_season():
    from flopo2.schema.flopo_trait_models import (
        FrequencyQualifier,
        SeasonContext,
        SourceStatement,
        TraitAssertion,
        TraitExtraction,
    )

    statement = SourceStatement(
        statement_id="statement-1", verbatim_text="usually green in summer", start=0, end=23
    )
    assertion = TraitAssertion(
        anatomical_entity="PO:0025034",
        quality="PATO:0000320",
        source_text="usually green in summer",
        source_statement_id="statement-1",
        frequency_qualifier=FrequencyQualifier.usually,
        modality_text="usually",
        season_contexts=[
            SeasonContext(
                season_term="FLOPOANN:summer_season",
                season_text="summer",
                start=17,
                end=23,
            )
        ],
    )
    extraction = TraitExtraction(source_statements=[statement], assertions=[assertion])
    assert extraction.assertions[0].source_statement_id == "statement-1"
    assert extraction.assertions[0].frequency_qualifier == "usually"
    assert extraction.assertions[0].season_contexts[0].season_term.endswith("summer_season")


def test_source_owl_retains_provenance_and_keeps_qualified_claims_meta_level(tmp_path):
    from flopo2.owl.assertions import (
        FLOPOANN,
        SIO,
        SIO_HAS_VALUE,
        build_assertion_ontology,
    )

    source = _write_records(tmp_path / "traits.jsonl")
    pato = _write_pato(tmp_path / "pato.tsv")
    out = tmp_path / "assertions.ttl"
    stats = build_assertion_ontology(source, out, pato_lex=pato, include_imports=False)
    graph = Graph().parse(out)

    assert stats["source_statements"] == 5
    assert stats["assertions"] == 5
    assert stats["strict_axioms"] == 4
    assert stats["qualified_or_nonlogical"] == 1
    assert stats["numeric_descriptions"] == 1
    assert stats["seasonal_descriptions"] == 1
    assert stats["disjunctive_descriptions"] == 1

    identical = [
        subject
        for subject in graph.subjects(SIO_HAS_VALUE, Literal("Leaves green"))
        if (subject, RDF.type, FLOPOANN.SourceStatement) in graph
    ]
    assert len(identical) == 2
    assert len(set(identical)) == 2
    assert all((statement, URIRef("http://www.w3.org/ns/prov#wasDerivedFrom"), None) in graph for statement in identical)

    usually_assertion = next(
        graph.subjects(FLOPOANN.has_frequency_qualifier, FLOPOANN.usually)
    )
    gamma_taxon = next(graph.objects(usually_assertion, FLOPOANN.refers_to_taxon))
    assert not list(graph.objects(gamma_taxon, RDFS.subClassOf))
    assert (
        usually_assertion,
        FLOPOANN.logical_status,
        Literal("qualified_meta_assertion"),
    ) in graph
    assert (usually_assertion, FLOPOANN.modality_cue, Literal("usually")) in graph

    axiom_nodes = set(graph.subjects(RDF.type, OWL.Axiom))
    assert len(axiom_nodes) == 4
    assert all(list(graph.objects(axiom, FLOPOANN.source_statement)) for axiom in axiom_nodes)
    assert all(list(graph.objects(axiom, FLOPOANN.formal_assertion)) for axiom in axiom_nodes)
    assert not list(graph.subjects(RDF.type, SIO.SIO_001054))  # measuring
    assert not list(graph.subjects(RDF.type, SIO.SIO_000070))  # measurement value


def test_numeric_and_seasonal_constraints_are_inside_owl_class_descriptions(tmp_path):
    from flopo2.owl.annotation_extension import build_annotation_extension
    from flopo2.owl.assertions import FLOPOANN

    source = _write_records(tmp_path / "traits.jsonl")
    out = tmp_path / "annotation-extension.ttl"
    stats = build_annotation_extension(
        source,
        out,
        pato_lex=_write_pato(tmp_path / "pato.tsv"),
        include_imports=False,
        output_format="turtle",
    )
    graph = Graph().parse(out)

    assert stats["assertions"] == 5
    assert stats["annotation_classes"] == 4
    assert stats["reused_class_links"] == 1

    magnitude_restriction = next(
        graph.subjects(OWL.onProperty, FLOPOANN.has_magnitude)
    )
    data_range = next(graph.objects(magnitude_restriction, OWL.someValuesFrom))
    assert (data_range, OWL.onDatatype, URIRef(str(URIRef("http://www.w3.org/2001/XMLSchema#decimal")))) in graph
    assert list(graph.objects(data_range, OWL.withRestrictions))
    assert list(graph.subjects(OWL.onProperty, FLOPOANN.has_value_unit))
    assert list(graph.subjects(OWL.onProperty, FLOPOANN.present_during))
    assert list(graph.subjects(OWL.unionOf, None))


def test_sqlite_retains_statement_foreign_keys_and_structured_qualifiers(tmp_path):
    from flopo2.db.load import load_jsonl
    from flopo2.verify.data_model import validate_sqlite

    source = _write_records(tmp_path / "traits.jsonl")
    db = tmp_path / "traits.sqlite"
    loaded = load_jsonl(db, source)
    report = validate_sqlite(db, loaded)
    assert report["ok"]
    assert loaded["source_statements"] == 5
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_statement").fetchone()[0] == 5
        assert connection.execute(
            "SELECT frequency_qualifier, modality_text FROM trait_assertion "
            "WHERE frequency_qualifier='usually'"
        ).fetchone() == ("usually", "usually")
        assert connection.execute(
            "SELECT COUNT(*) FROM trait_assertion AS a JOIN source_statement AS s "
            "ON s.statement_id=a.source_statement_id"
        ).fetchone()[0] == 5


def test_disjunction_stays_out_of_flopo_vocabulary_but_in_annotation_extension(tmp_path):
    from flopo2.owl.annotation_extension import build_annotation_extension
    from flopo2.owl.assertions import build_assertion_ontology
    from flopo2.owl.build import build_ontology

    text = "flowers red or green"
    record = {
        "source": "flora-A",
        "source_id": "one.xml",
        "taxon": "Quercus alpha",
        "text": text,
        "assertions": [
            _assertion(
                text,
                text,
                "PO_0009046",
                "PATO_0000014",
                value_operator="one_of",
                value_terms=["PATO_0000322", "PATO_0000320"],
            )
        ],
    }
    gated = _write_records(tmp_path / "gated.jsonl", [record])
    pato = _write_pato(tmp_path / "pato.tsv")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\nPO_0009046\tflower\n")
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n")

    flopo_out = tmp_path / "flopo.ttl"
    stats = build_ontology(gated, flopo_out, registry, po, pato)
    flopo_graph = Graph().parse(flopo_out)
    assert "EQ|PO_0009046|PATO_0000014" in stats["minted_iris"]
    assert not list(flopo_graph.subjects(OWL.unionOf, None))

    extension_out = tmp_path / "annotation-extension.ttl"
    annotated = tmp_path / "annotated.jsonl"
    extension_stats = build_annotation_extension(
        gated,
        extension_out,
        annotated_jsonl=annotated,
        pato_lex=pato,
        po_lex=po,
        flopo_registry=registry,
        include_imports=False,
        output_format="turtle",
    )
    extension_graph = Graph().parse(extension_out)
    assert extension_stats["annotation_classes"] == 1
    assert list(extension_graph.subjects(OWL.unionOf, None))
    fac_classes = [
        cls
        for cls in extension_graph.subjects(RDF.type, OWL.Class)
        if str(cls).startswith("https://w3id.org/flopo/annotation-class/FAC_")
    ]
    assert len(fac_classes) == 1

    source_out = tmp_path / "source.ttl"
    build_assertion_ontology(annotated, source_out, pato_lex=pato, include_imports=False)
    source_graph = Graph().parse(source_out)
    assert not list(source_graph.subjects(OWL.unionOf, None))
    assert list(
        source_graph.triples(
            (None, URIRef("https://w3id.org/flopo/annotation/phenotype_class"), fac_classes[0])
        )
    )


@pytest.mark.skipif(
    not Path("tools/robot.jar").exists() or shutil.which("java") is None,
    reason="ROBOT/HermiT is not available",
)
def test_source_module_is_owl2_dl_and_reasoner_consistent(tmp_path):
    from flopo2.owl.assertions import build_assertion_ontology

    source = _write_records(tmp_path / "traits.jsonl")
    out = tmp_path / "assertions.ttl"
    build_assertion_ontology(
        source,
        out,
        pato_lex=_write_pato(tmp_path / "pato.tsv"),
        include_imports=False,
    )
    profile = tmp_path / "profile.txt"
    subprocess.run(
        [
            "java",
            "-jar",
            "tools/robot.jar",
            "validate-profile",
            "--profile",
            "DL",
            "--input",
            str(out),
            "--output",
            str(profile),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "in profile" in profile.read_text()
    subprocess.run(
        [
            "java",
            "-jar",
            "tools/robot.jar",
            "reason",
            "--reasoner",
            "HermiT",
            "--input",
            str(out),
            "--output",
            str(tmp_path / "reasoned.owl"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
