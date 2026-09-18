"""OBO QC fixes: obsolete-label prefix and missing-definition generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from rdflib import OWL, RDFS, XSD, Graph, Literal, URIRef

from flopo2.ids.registry import build_registry
from flopo2.owl.obo_fix import (
    CURATED_DEFINITIONS,
    DCTERMS_SOURCE,
    IAO_DEF,
    OBO,
    CuratedDefinition,
    axiom_definition,
    fix,
    load_curated_definitions,
    missing_definitions,
    obsolete_label,
    prefix_obsolete_labels,
    strip_obsolete_prefix,
)
from flopo2.owl.sssom import load_flopo_labels
from tools.update_flopo_obo_qc_release import BEGIN_MARKER, update_release

ROOT = Path(__file__).resolve().parents[1]

PREFIXES = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix obo: <http://purl.obolibrary.org/obo/> .
@prefix pato: <http://purl.obolibrary.org/obo/pato#> .
"""

# Mirrors the release's non-registry ("OTHER") EQ variants: towards, part_of, count, range.
AXIOMS = PREFIXES + """
obo:FLOPO_0014367 a owl:Class ; rdfs:label "petal fused"@en ;
  owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
    owl:someValuesFrom [ owl:intersectionOf ( obo:PO_0009032
      [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ; owl:someValuesFrom
        [ owl:intersectionOf ( obo:PATO_0000642
          [ a owl:Restriction ; owl:onProperty pato:towards ;
            owl:someValuesFrom obo:PO_0009032 ] ) ] ] ) ] ] .
obo:FLOPO_0980068 a owl:Class ; rdfs:label "pedicel ciliatedness"@en ;
  owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
    owl:someValuesFrom [ owl:intersectionOf (
      [ a owl:Restriction ; owl:onProperty obo:BFO_0000050 ; owl:someValuesFrom obo:PO_0009052 ]
      [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ;
        owl:someValuesFrom obo:PATO_0001408 ] ) ] ] .
obo:FLOPO_0907301 a owl:Class ; rdfs:label "petal amount 1"@en ;
  owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
    owl:someValuesFrom [ owl:intersectionOf ( obo:PO_0009032
      [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ; owl:someValuesFrom
        [ owl:intersectionOf ( obo:PATO_0000070
          [ a owl:Restriction ; owl:onProperty obo:FLOPO_0907302 ;
            owl:hasValue "1"^^xsd:integer ] ) ] ] ) ] ] .
obo:FLOPO_0907309 a owl:Class ; rdfs:label "stamen amount <=10"@en ;
  owl:equivalentClass [ a owl:Restriction ; owl:onProperty obo:BFO_0000051 ;
    owl:someValuesFrom [ owl:intersectionOf ( obo:PO_0009029
      [ a owl:Restriction ; owl:onProperty obo:RO_0000053 ; owl:someValuesFrom
        [ owl:intersectionOf ( obo:PATO_0000070
          [ a owl:Restriction ; owl:onProperty obo:FLOPO_0907302 ; owl:someValuesFrom
            [ a rdfs:Datatype ; owl:onDatatype xsd:integer ;
              owl:withRestrictions ( [ xsd:maxInclusive "10"^^xsd:integer ] ) ] ] ) ] ] ) ] ] .
obo:FLOPO_0907302 a owl:DatatypeProperty ; rdfs:label "hasValue"@en .
obo:FLOPO_0900000 a owl:Class ; rdfs:label "inflorescence type"@en .
obo:FLOPO_0000001 a owl:Class ; rdfs:label "caruncle up"^^xsd:string ;
  owl:deprecated "true"^^xsd:boolean .
obo:FLOPO_0000002 a owl:Class ; rdfs:label "obsolete calyx pubescent"@en ;
  owl:deprecated "true"^^xsd:boolean .
"""

LABELS = {
    "PO_0009032": "petal",
    "PO_0009052": "inflorescence flower pedicel",
    "PO_0009029": "stamen",
    "PATO_0000642": "fused with",
    "PATO_0001408": "ciliated",
    "PATO_0000070": "amount",
}


def _graph() -> Graph:
    return Graph().parse(data=AXIOMS, format="turtle")


def _u(local: str) -> URIRef:
    return URIRef(OBO + local)


def test_obsolete_label_is_idempotent_and_reversible():
    assert obsolete_label("caruncle up") == "obsolete caruncle up"
    assert obsolete_label("obsolete caruncle up") == "obsolete caruncle up"
    assert obsolete_label("Obsolete X") == "Obsolete X"
    assert strip_obsolete_prefix("obsolete caruncle up") == "caruncle up"
    assert strip_obsolete_prefix("caruncle up") == "caruncle up"


def test_prefix_obsolete_labels_keeps_datatype_and_does_not_double_prefix():
    g = _graph()
    deprecated = {_u("FLOPO_0000001"), _u("FLOPO_0000002")}
    assert prefix_obsolete_labels(g, deprecated) == 1
    assert prefix_obsolete_labels(g, deprecated) == 0
    assert set(g.objects(_u("FLOPO_0000001"), RDFS.label)) == {
        Literal("obsolete caruncle up", datatype=XSD.string)
    }
    assert set(g.objects(_u("FLOPO_0000002"), RDFS.label)) == {
        Literal("obsolete calyx pubescent", lang="en")
    }


@pytest.mark.parametrize(
    ("local", "expected"),
    [
        ("FLOPO_0014367",
         "A phenotype in which a(n) petal exhibits the quality of being fused with a(n) petal."),
        ("FLOPO_0980068", "A phenotype in which a part of a(n) inflorescence flower pedicel "
                          "exhibits the quality of being ciliated."),
        ("FLOPO_0907301", "A phenotype in which a(n) petal exhibits a(n) amount quality with "
                          "value 1."),
        ("FLOPO_0907309", "A phenotype in which a(n) stamen exhibits a(n) amount quality with "
                          "value at most 10."),
    ],
)
def test_axiom_definition_variants(local, expected):
    assert axiom_definition(_graph(), _u(local), LABELS) == expected


def test_axiom_definition_needs_labels_and_axiom():
    assert axiom_definition(_graph(), _u("FLOPO_0014367"), {}) is None
    assert axiom_definition(_graph(), _u("FLOPO_0900000"), LABELS) is None


def test_missing_definitions_order_and_guards():
    g = _graph()
    g.add((_u("FLOPO_0907303"), IAO_DEF, Literal("existing")))
    curated = {
        "FLOPO_0900000": CuratedDefinition(
            "inflorescence type", "An inflorescence phenotype ...", (_u("PO_0009049"),)
        ),
        "FLOPO_0000001": CuratedDefinition("caruncle up", "never used", (_u("PO_1"),)),
    }
    out = missing_definitions(g, {}, LABELS, {}, curated)
    assert out[_u("FLOPO_0900000")] == ("An inflorescence phenotype ...", (_u("PO_0009049"),))
    assert out[_u("FLOPO_0014367")][1] == ()  # axiom-generated, no curated source
    assert _u("FLOPO_0000001") not in out  # deprecated classes get no definition
    assert _u("FLOPO_0907302") not in out  # property without curated row: left for review

    bad = {"FLOPO_0900000": CuratedDefinition("fruit type", "x", (_u("PO_1"),))}
    with pytest.raises(ValueError, match="does not match"):
        missing_definitions(g, {}, LABELS, {}, bad)


def test_curated_definitions_table_is_genus_differentia_with_sources():
    rows = load_curated_definitions(ROOT / CURATED_DEFINITIONS)
    assert len(rows) == 69
    texts = [row.definition for row in rows.values()]
    assert len(set(texts)) == len(texts)
    for flopo_id, row in rows.items():
        assert re.fullmatch(r"FLOPO_\d{7}", flopo_id)
        assert re.match(r"An? \S", row.definition) and row.definition.endswith(".")
        # not a paraphrase of the label: the label itself must not appear as a phrase
        assert not re.search(rf"\b{re.escape(row.label.casefold())}\b", row.definition.casefold())
        assert row.sources and all(
            isinstance(s, URIRef) or str(s).startswith("Raunkiaer") for s in row.sources
        )


def _write_labels(path: Path, rows: dict[str, str]) -> Path:
    path.write_text("id\tlabel\n" + "".join(f"{k}\t{v}\n" for k, v in rows.items()))
    return path


def test_fix_adds_obsolete_prefix_definitions_and_single_version(tmp_path):
    src = tmp_path / "in.owl"
    _graph().serialize(src.as_posix(), format="pretty-xml")
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tsignature\n")
    curated = tmp_path / "curated.tsv"
    curated.write_text(
        "flopo_id\tlabel\tdefinition\tsources\n"
        "FLOPO_0900000\tinflorescence type\tAn inflorescence phenotype that characterizes "
        "branching.\tPO:0009049|Some citation.\n"
    )
    po = _write_labels(tmp_path / "po.tsv", {k: v for k, v in LABELS.items() if "PO_" in k})
    pato = _write_labels(tmp_path / "pato.tsv", {k: v for k, v in LABELS.items() if "PATO" in k})
    out = tmp_path / "out.owl"
    stats = fix(src, registry, po, pato, "2026-01-01", out, curated)
    stats2 = fix(out, registry, po, pato, "2026-02-02", out, curated)
    g = Graph().parse(out.as_posix())
    assert stats["obsolete_labels_prefixed"] == 1 and stats2["obsolete_labels_prefixed"] == 0
    assert stats2["definitions_added"] == 0
    assert str(g.value(_u("FLOPO_0000001"), RDFS.label)) == "obsolete caruncle up"
    assert set(g.objects(_u("FLOPO_0900000"), DCTERMS_SOURCE)) == {
        _u("PO_0009049"), Literal("Some citation.")
    }
    assert len(set(g.objects(URIRef(OBO + "flopo.owl"), OWL.versionIRI))) == 1


def test_registry_and_sssom_treat_prefixed_obsolete_classes_as_deprecated(tmp_path):
    owl = tmp_path / "flopo.owl"
    g = _graph()
    prefix_obsolete_labels(g, {_u("FLOPO_0000001")})
    g.serialize(owl.as_posix(), format="pretty-xml")
    entry = {e.iri: e for e in build_registry(owl)}[OBO + "FLOPO_0000001"]
    assert entry.deprecated and entry.label == "obsolete caruncle up"
    labels = load_flopo_labels(owl)
    assert "FLOPO_0000001" not in labels and "FLOPO_0000002" not in labels
    assert labels["FLOPO_0014367"] == "petal fused"


RELEASE_BODY = """<?xml version="1.0" encoding="utf-8"?>
<rdf:RDF
  xmlns:dcterms="http://purl.org/dc/terms/"
  xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
  xmlns:owl="http://www.w3.org/2002/07/owl#"
  xmlns:obo="http://purl.obolibrary.org/obo/"
  xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
    <rdfs:label xml:lang="en">caruncle up</rdfs:label>
    <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
  </owl:Class>
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0900000">
    <rdfs:label xml:lang="en">inflorescence type</rdfs:label>
  </owl:Class>
{block}</rdf:RDF>
"""
GENERATED_OBSOLETE = """  <!-- BEGIN GENERATED FLOPO TEST -->
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000003">
    <rdfs:label xml:lang="en">stale label</rdfs:label>
    <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
  </owl:Class>
  <!-- END GENERATED FLOPO TEST -->
"""


def _release_inputs(tmp_path: Path) -> dict[str, Path]:
    registry = tmp_path / "registry.tsv"
    registry.write_text("flopo_iri\tsignature\n")
    curated = tmp_path / "curated.tsv"
    curated.write_text(
        "flopo_id\tlabel\tdefinition\tsources\n"
        "FLOPO_0900000\tinflorescence type\tAn inflorescence phenotype that characterizes "
        "branching & flowers.\tPO:0009049|https://example.org/g#x\n"
    )
    empty = _write_labels(tmp_path / "lex.tsv", {})
    return {"registry": registry, "curated": curated, "po_lex": empty, "pato_lex": empty}


def test_release_text_patch_is_idempotent_and_preserves_body(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(RELEASE_BODY.format(block=""), encoding="utf-8")
    inputs = _release_inputs(tmp_path)
    stats = update_release(release, release, **inputs)
    first = release.read_text(encoding="utf-8")
    stats2 = update_release(release, release, **inputs)
    assert release.read_text(encoding="utf-8") == first
    assert stats["obsolete_labels_prefixed"] == 1 and stats2["obsolete_labels_prefixed"] == 0
    assert stats2["definitions_added"] == 1 and first.count(BEGIN_MARKER) == 1
    assert '<rdfs:label xml:lang="en">obsolete caruncle up</rdfs:label>' in first
    assert "branching &amp; flowers." in first
    g = Graph().parse(release.as_posix())
    assert set(g.objects(_u("FLOPO_0900000"), DCTERMS_SOURCE)) == {
        _u("PO_0009049"), URIRef("https://example.org/g#x")
    }


def test_release_text_patch_refuses_to_edit_generated_blocks(tmp_path):
    release = tmp_path / "flopo.owl"
    release.write_text(RELEASE_BODY.format(block=GENERATED_OBSOLETE), encoding="utf-8")
    with pytest.raises(ValueError, match="generated blocks"):
        update_release(release, tmp_path / "out.owl", **_release_inputs(tmp_path))
