"""Tests for the FLOPO IRI registry — the identifier-stability guarantee.

Uses a small inline OWL fixture (RDF/XML) mirroring the real flopo.owl structure, so the test is
fast and independent of the 27 MB release file. The fixture covers the three signature kinds plus
a deprecated class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flopo2.ids.registry import IdAllocator, RegistryEntry, build_registry, summarize

FIXTURE = """<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
     xmlns:owl="http://www.w3.org/2002/07/owl#"
     xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#"
     xml:base="http://purl.obolibrary.org/obo/flopo.owl">
  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl"/>

  <!-- "E Q" pattern: flower red -->
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0007599">
    <owl:equivalentClass>
      <owl:Restriction>
        <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/BFO_0000051"/>
        <owl:someValuesFrom>
          <owl:Class>
            <owl:intersectionOf rdf:parseType="Collection">
              <rdf:Description rdf:about="http://purl.obolibrary.org/obo/PO_0009046"/>
              <owl:Restriction>
                <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/RO_0000053"/>
                <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000322"/>
              </owl:Restriction>
            </owl:intersectionOf>
          </owl:Class>
        </owl:someValuesFrom>
      </owl:Restriction>
    </owl:equivalentClass>
    <rdfs:label>flower red</rdfs:label>
  </owl:Class>

  <!-- "E phenotype" pattern: stem phenotype -->
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000001">
    <owl:equivalentClass>
      <owl:Restriction>
        <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/BFO_0000051"/>
        <owl:someValuesFrom>
          <owl:Class>
            <owl:intersectionOf rdf:parseType="Collection">
              <owl:Restriction>
                <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/BFO_0000050"/>
                <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PO_0009047"/>
              </owl:Restriction>
              <owl:Restriction>
                <owl:onProperty rdf:resource="http://purl.obolibrary.org/obo/RO_0000053"/>
                <owl:someValuesFrom rdf:resource="http://purl.obolibrary.org/obo/PATO_0000001"/>
              </owl:Restriction>
            </owl:intersectionOf>
          </owl:Class>
        </owl:someValuesFrom>
      </owl:Restriction>
    </owl:equivalentClass>
    <rdfs:label>stem phenotype</rdfs:label>
  </owl:Class>

  <!-- manual / subclass-only class -->
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000000">
    <rdfs:label>flora phenotype</rdfs:label>
  </owl:Class>

  <!-- deprecated nonsensical class -->
  <owl:Class rdf:about="http://purl.obolibrary.org/obo/FLOPO_0000108">
    <owl:deprecated rdf:datatype="http://www.w3.org/2001/XMLSchema#boolean">true</owl:deprecated>
    <rdfs:label>stigma female</rdfs:label>
  </owl:Class>
</rdf:RDF>
"""


def _entries(tmp_path: Path):
    owl = tmp_path / "fix.owl"
    owl.write_text(FIXTURE)
    return build_registry(owl)


def test_signatures_extracted(tmp_path):
    sigs = {e.label: e.signature for e in _entries(tmp_path)}
    assert sigs["flower red"] == "EQ|PO_0009046|PATO_0000322"
    assert sigs["stem phenotype"] == "PHENO|PO_0009047"
    assert sigs["flora phenotype"] == "OTHER"


def test_deprecated_flagged(tmp_path):
    dep = {e.label: e.deprecated for e in _entries(tmp_path)}
    assert dep["stigma female"] is True
    assert dep["flower red"] is False


def test_summary_counts(tmp_path):
    s = summarize(_entries(tmp_path))
    assert s["total_classes"] == 4
    assert s["deprecated"] == 1
    assert s["max_flopo_num"] == 7599
    assert s["patterns"] == {"EQ": 1, "PHENO": 1, "OTHER": 2}


def test_allocator_reuses_existing_iri(tmp_path):
    alloc = IdAllocator(_entries(tmp_path))
    # Known signature must reuse the exact original IRI.
    assert alloc.iri_for("EQ|PO_0009046|PATO_0000322") == (
        "http://purl.obolibrary.org/obo/FLOPO_0007599"
    )


def test_allocator_mints_after_max(tmp_path):
    alloc = IdAllocator(_entries(tmp_path))
    new = alloc.iri_for("EQ|PO_9999999|PATO_9999999")
    # Next free id continues after the max (7599) and never collides with reserved ids.
    assert new == "http://purl.obolibrary.org/obo/FLOPO_0007600"
    # Same new signature is stable within a run.
    assert alloc.iri_for("EQ|PO_9999999|PATO_9999999") == new


def test_allocator_reuses_reviewed_reservation_and_mints_after_it(tmp_path):
    reservation = RegistryEntry(
        iri="http://purl.obolibrary.org/obo/FLOPO_0980611",
        flopo_num=980611,
        label="leaf blue",
        signature="EQ|PO_0025034|PATO_0000318",
        deprecated=False,
    )
    alloc = IdAllocator(_entries(tmp_path), [reservation])

    assert alloc.iri_for(reservation.signature) == reservation.iri
    assert alloc.reused_reservations == {reservation.signature: reservation.iri}
    assert alloc.iri_for("EQ|PO_9999999|PATO_9999999").endswith(
        "FLOPO_0980612"
    )


def test_allocator_rejects_conflicting_reviewed_reservation(tmp_path):
    collision = RegistryEntry(
        iri="http://purl.obolibrary.org/obo/FLOPO_0007599",
        flopo_num=7599,
        label="conflicting class",
        signature="EQ|PO_9999999|PATO_9999999",
        deprecated=False,
    )
    with pytest.raises(ValueError, match="collides with the release registry"):
        IdAllocator(_entries(tmp_path), [collision])
