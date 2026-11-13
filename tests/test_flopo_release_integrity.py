"""The release files must be readable as OWL: every class expression is complete and typed.

The 2026-11-08 release shipped two classes whose definitions pointed at blank nodes the file did
not contain ('whole plant herbaceous' had lost its definition), and every release since 2026-07-31
used RO:0002180 in cardinality restrictions without declaring it. OWLAPI reads both as
``http://org.semanticweb.owlapi/error#ErrorN`` classes, which the hierarchy pass then asserted as
superclasses.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ONTOLOGY = Path(__file__).resolve().parents[1] / "ontology"
ERROR_IRI = "http://org.semanticweb.owlapi/error#"


@pytest.mark.parametrize("name", ["flopo.owl", "flopo-inferred.owl", "flopo-light.owl"])
def test_no_owlapi_error_classes(name):
    assert ERROR_IRI not in (ONTOLOGY / name).read_text(encoding="utf-8")


def test_every_referenced_blank_node_is_defined():
    text = (ONTOLOGY / "flopo.owl").read_text(encoding="utf-8")
    defined = set(re.findall(r'<[A-Za-z:]+ rdf:nodeID="([^"]+)">', text))
    referenced = set(re.findall(r'<[A-Za-z:]+ rdf:nodeID="([^"]+)"/>', text))
    assert not sorted(referenced - defined)[:5]


def test_properties_of_cardinality_restrictions_are_declared():
    text = (ONTOLOGY / "flopo.owl").read_text(encoding="utf-8")
    used = set()
    for body in re.findall(r"<(?:owl:Restriction|rdf:Description)[^>]*>(.*?)</(?:owl:Restriction|rdf:Description)>", text, re.S):
        if "ardinality" in body:
            used |= set(re.findall(r'<owl:onProperty rdf:resource="([^"]+)"/>', body))
    assert used, "the bi- and trifoliolate leaf classes use cardinality restrictions"
    for prop in sorted(used):
        declared = re.search(
            rf'<owl:ObjectProperty rdf:about="{re.escape(prop)}"|'
            rf'<rdf:Description rdf:about="{re.escape(prop)}">(?:(?!</rdf:Description>).)*owl#ObjectProperty',
            text, re.S,
        )
        assert declared, f"{prop} is used in a cardinality restriction but not declared an object property"
