from __future__ import annotations

import csv
import re
import subprocess
import sys
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib.collection import Collection


OBO = "http://purl.obolibrary.org/obo/"


def test_value_extension_replaces_pato_terms_and_models_unions(tmp_path):
    candidates = tmp_path / "candidates.tsv"
    candidates.write_text(
        "candidate_id\tvalue_label\tfrequency\tstatus\tsuggested_parent_pato_ids\t"
        "suggested_parent_pato_labels\tquality_contexts\texamples\tnotes\n"
        "VALUE_cream\tcreamy\t2\tcandidate\tPATO_0000323\twhite\tflower color\tcream flowers\t\n"
        "VALUE_greenish\tgreenish\t1\tcandidate\tPATO_0000320\tgreen\tflower color\tgreenish flowers\t\n"
        "VALUE_red_yellow\tred and yellow\t1\tcandidate\tPATO_0000322|PATO_0000324\t"
        "red|yellow\tflower color\tred and yellow flowers\t\n",
        encoding="utf-8",
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\n", encoding="utf-8")
    mappings = tmp_path / "mappings.tsv"
    mappings.write_text(
        "flopo_id\tlabel\tpato_id\tpato_label\tprovenance\n"
        "FLOPO_0980084\tcreamy\tPATO_0104031\tcream\thttps://example.org/review\n",
        encoding="utf-8",
    )
    axioms = tmp_path / "axioms.tsv"
    with axioms.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow([
            "flopo_id", "label", "axiom_type", "parent_ids", "logical_target_ids",
            "definition", "sources", "frequency", "quality_contexts", "examples",
            "candidate_id",
        ])
        writer.writerow([
            "FLOPO_0980085", "greenish", "subclass", "PATO_0000014", "",
            "A predominantly green botanical color.", "https://example.org/source",
            "", "", "", "",
        ])
        writer.writerow([
            "FLOPO_0980087", "greenish or reddish orange", "union", "PATO_0000014",
            "FLOPO_0980085|FLOPO_0980088", "A disjunctive botanical color value.",
            "https://example.org/review", "1", "flower color", "example", "VALUE_union",
        ])
        writer.writerow([
            "FLOPO_0980088", "reddish orange", "subclass", "PATO_0000014", "",
            "A reddish-orange botanical color.", "https://example.org/source", "1",
            "flower color", "example", "VALUE_reddish_orange",
        ])
    pato = tmp_path / "pato.tsv"
    pato.write_text(
        "id\tlabel\tsynonyms\tslim\n"
        "PATO_0000014\tcolor\tcolour\tattribute_slim\n"
        "PATO_0104031\tcream\tcreamy\tvalue_slim\n",
        encoding="utf-8",
    )
    template = tmp_path / "values.tsv"
    ttl = tmp_path / "values.ttl"
    value_ids = tmp_path / "value-ids.tsv"

    command = [
        sys.executable,
        "tools/build_flopo_value_extension.py",
        "--candidates", str(candidates),
        "--registry", str(registry),
        "--value-id-registry", str(value_ids),
        "--pato-mappings", str(mappings),
        "--axioms", str(axioms),
        "--pato-lexicon", str(pato),
        "--template-out", str(template),
        "--ttl-out", str(ttl),
    ]
    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "mapped_to_pato 1" in result.stdout

    with template.open(encoding="utf-8", newline="") as handle:
        rows = {row["flopo_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    assert "FLOPO_0980084" not in rows
    assert rows["FLOPO_0980086"]["axiom_type"] == "components"
    assert rows["FLOPO_0980087"]["axiom_type"] == "union"

    graph = Graph()
    graph.parse(ttl)
    union_class = URIRef(OBO + "FLOPO_0980087")
    color = URIRef(OBO + "PATO_0000014")
    assert (union_class, RDFS.subClassOf, color) in graph
    assert (union_class, RDFS.subClassOf, URIRef(OBO + "FLOPO_0980085")) not in graph
    expression = next(graph.objects(union_class, OWL.equivalentClass))
    members = next(graph.objects(expression, OWL.unionOf))
    assert set(Collection(graph, members)) == {
        URIRef(OBO + "FLOPO_0980085"),
        URIRef(OBO + "FLOPO_0980088"),
    }
    assert (URIRef(OBO + "FLOPO_0980088"), RDF.type, OWL.Class) in graph

    composite = URIRef(OBO + "FLOPO_0980086")
    red = URIRef(OBO + "PATO_0000322")
    yellow = URIRef(OBO + "PATO_0000324")
    assert (composite, RDFS.subClassOf, red) not in graph
    assert (composite, RDFS.subClassOf, yellow) not in graph
    restrictions = [
        node for node in graph.objects(composite, RDFS.subClassOf)
        if (node, RDF.type, OWL.Restriction) in graph
    ]
    assert {next(graph.objects(node, OWL.someValuesFrom)) for node in restrictions} == {red, yellow}

    # Once these classes are added to the main FLOPO registry, rebuilding must
    # reuse their identifiers instead of starting a new range above its maximum.
    first_template = template.read_text(encoding="utf-8")
    first_ttl = ttl.read_text(encoding="utf-8")
    registry.write_text(
        "flopo_iri\nhttp://purl.obolibrary.org/obo/FLOPO_0999999\n",
        encoding="utf-8",
    )
    subprocess.run(command, check=True, capture_output=True, text=True)
    assert template.read_text(encoding="utf-8") == first_template
    assert ttl.read_text(encoding="utf-8") == first_ttl


def test_pr615_pato_terms_are_in_grounding_lexicon():
    from flopo2.extract.ground import Lexicon

    lexicon = Lexicon.load("config/pato_lexicon.tsv")
    assert lexicon.ground("deep yellow") == "PATO_0104005"
    assert lexicon.ground("creamy") == "PATO_0104031"
    assert lexicon.ground("blue-grey") == "PATO_0104305"
    assert lexicon.ground("felted") == "PATO_0104242"


def test_all_real_or_values_are_exact_unions_and_pato_replacements_are_omitted():
    expected_unions = {
        "FLOPO_0980187": {"PATO_0000323", "PATO_0104031", "PATO_0000324"},
        "FLOPO_0980196": {"PATO_0000322", "PATO_0000324"},
        "FLOPO_0980199": {"FLOPO_0980085", "FLOPO_0980097"},
        "FLOPO_0980207": {"PATO_0001943", "PATO_0104064"},
        "FLOPO_0980286": {"PATO_0104031", "PATO_0000323"},
        "FLOPO_0980343": {"PATO_0000318", "PATO_0001943"},
        "FLOPO_0980346": {"PATO_0000324", "FLOPO_0980416"},
    }

    with open("ontology/flopo-value-extensions.tsv", encoding="utf-8", newline="") as handle:
        rows = {row["flopo_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    actual_unions = {
        flopo_id: set(row["logical_target_ids"].split("|"))
        for flopo_id, row in rows.items()
        if row["axiom_type"] == "union"
    }
    assert actual_unions == expected_unions

    with open("config/flopo_value_candidates.tsv", encoding="utf-8", newline="") as handle:
        or_labels = {
            row["value_label"]
            for row in csv.DictReader(handle, delimiter="\t")
            if row["status"] == "candidate" and re.search(r"\bor\b", row["value_label"])
        }
    assert {rows[flopo_id]["label"] for flopo_id in actual_unions} == or_labels

    graph = Graph()
    graph.parse("ontology/flopo-value-extensions.ttl")
    for flopo_id, expected_operands in expected_unions.items():
        cls = URIRef(OBO + flopo_id)
        expression = next(graph.objects(cls, OWL.equivalentClass))
        members = next(graph.objects(expression, OWL.unionOf))
        assert set(Collection(graph, members)) == {
            URIRef(OBO + operand) for operand in expected_operands
        }

    release = Graph()
    release.parse("ontology/flopo.owl")
    for flopo_id, expected_operands in expected_unions.items():
        cls = URIRef(OBO + flopo_id)
        expression = next(release.objects(cls, OWL.equivalentClass))
        members = next(release.objects(expression, OWL.unionOf))
        assert set(Collection(release, members)) == {
            URIRef(OBO + operand) for operand in expected_operands
        }

    with open("config/flopo_value_pato_mappings.tsv", encoding="utf-8", newline="") as handle:
        mappings = list(csv.DictReader(handle, delimiter="\t"))
    assert len(mappings) == 38
    assert not ({row["flopo_id"] for row in mappings} & set(rows))
    release_classes = {
        str(cls).removeprefix(OBO)
        for cls in release.subjects(RDF.type, OWL.Class)
        if str(cls).startswith(OBO + "FLOPO_")
    }
    assert set(rows) <= release_classes
    assert not ({row["flopo_id"] for row in mappings} & release_classes)
    ttl_text = Path("ontology/flopo-value-extensions.ttl").read_text(encoding="utf-8")
    assert all(row["flopo_id"] not in ttl_text for row in mappings)

    with open("config/flopo_id_registry.tsv", encoding="utf-8", newline="") as handle:
        registered = {
            row["flopo_iri"].removeprefix(OBO)
            for row in csv.DictReader(handle, delimiter="\t")
        }
    assert set(rows) <= registered

    pato_source = Path("ont/quality.obo").read_text(encoding="utf-8")
    mapped_pato_ids = {row["pato_id"] for row in mappings}
    mapped_pato_ids.update({"PATO_0104242", "PATO_0104307"})
    assert all(f"id: {pato_id.replace('_', ':', 1)}" in pato_source for pato_id in mapped_pato_ids)


def test_release_embedding_is_idempotent(tmp_path):
    from tools.update_flopo_release import BEGIN_MARKER, VALUE_ONTOLOGY, update_release

    release_path = tmp_path / "flopo.owl"
    release_path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<rdf:RDF xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:obo="http://purl.obolibrary.org/obo/" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#" '
        'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#">\n'
        '  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">\n'
        '    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/'
        'flopo/releases/2026-06-29/flopo.owl"/>\n'
        '    <owl:versionInfo>2026-06-29</owl:versionInfo>\n'
        '  </owl:Ontology>\n'
        '</rdf:RDF>\n',
        encoding="utf-8",
    )
    extension = Path("ontology/flopo-value-extensions.ttl")
    assert update_release(release_path, extension, "2026-07-13") == 295
    first = release_path.read_text(encoding="utf-8")
    assert update_release(release_path, extension, "2026-07-13") == 295
    assert release_path.read_text(encoding="utf-8") == first
    assert first.count(BEGIN_MARKER) == 1
    assert "flopo/releases/2026-07-13/flopo.owl" in first

    graph = Graph()
    graph.parse(release_path)
    assert (VALUE_ONTOLOGY, RDF.type, OWL.Ontology) not in graph
    assert (URIRef(OBO + "FLOPO_0980187"), OWL.equivalentClass, None) in graph
