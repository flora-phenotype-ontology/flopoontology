"""The numeric bridge of the FLOPO value spaces (ontology/flopo-value-ranges.ofn,
docs/odp/17-value-defined-by-a-measure.md): a full OWL reasoner derives the value word from a
measurement or a count, and the neighbours stated are those the ranges give."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from rdflib import OWL, RDF, Graph, URIRef

from tools import build_flopo_value_space_extension as vs

BRIDGE = Path("ontology/flopo-value-ranges.ofn")
MODULE = Path("ontology/flopo-value-space-extension.ttl")
PROBE = Path("tests/data/flopo-value-ranges-probe.ofn")
ROBOT = Path("tools/robot.jar")
NS = vs.BRIDGE + "#"
OBO = "http://purl.obolibrary.org/obo/"
UNSATISFIABLE = ("ProbeOppositeAndWhorled", "ProbeZeroPerNode")


def reason(tmp_path: Path, probe_text: str) -> tuple[str, str]:
    probe = tmp_path / "probe.ofn"
    probe.write_text(probe_text, encoding="utf-8")
    out = tmp_path / "out.ofn"
    done = subprocess.run(
        ["java", "-jar", str(ROBOT), "merge", "-i", str(BRIDGE), "-i", str(probe),
         "reason", "--reasoner", "hermit", "-o", str(out)], capture_output=True, text=True, timeout=900)
    return (out.read_text(encoding="utf-8") if out.exists() else ""), done.stdout + done.stderr


def test_the_generated_files_are_those_of_the_specification():
    assert BRIDGE.read_text(encoding="utf-8") == vs.bridge_text()
    built, stored = vs.build_module(), Graph().parse(MODULE.as_posix())
    assert set(built) == set(stored)


def test_every_temporary_class_and_relation_has_a_definition_a_source_and_a_parent_or_domain():
    graph = Graph().parse(MODULE.as_posix())
    definition, xref = URIRef(OBO + "IAO_0000115"), URIRef("http://www.geneontology.org/formats/oboInOwl#hasDbXref")
    terms = [vs._iri(row["id"]) for row in (*vs.RELATIONS, *vs.ATTRIBUTES)]
    assert len(terms) == 7
    for term in terms:
        assert graph.value(term, definition) and graph.value(term, xref), term
    for row in vs.RELATIONS:
        prop = vs._iri(row["id"])
        if row["kind"] == "data":
            assert (prop, RDF.type, OWL.FunctionalProperty) in graph
            assert str(graph.value(prop, URIRef("http://www.w3.org/2000/01/rdf-schema#domain"))) == OBO + "PATO_0000001"


def test_neighbours_are_symmetric_and_never_between_a_range_and_one_inside_it():
    pairs = vs.neighbours()
    label = {row["id"]: row["label"] for row in (*vs.MEASURED, *vs.COUNTED)}
    named = {frozenset((label[a], label[b])) for a, b in pairs}
    assert frozenset(("linear", "lanceolate")) in named and frozenset(("opposite", "whorled")) in named
    assert frozenset(("lanceolate", "elliptic")) in named  # the two uses of "lanceolate" in the 1962 chart
    assert frozenset(("lanceolate", "ovate")) not in named  # the manual's lanceolate is a narrow ovate
    assert frozenset(("alternate placement", "whorled")) not in named
    graph = Graph().parse(MODULE.as_posix())
    neighbour = vs._iri(vs.NEIGHBOUR)
    stated = set(graph.subject_objects(neighbour))
    assert stated == {(vs._iri(a), vs._iri(b)) for a, b in pairs} | {(vs._iri(b), vs._iri(a)) for a, b in pairs}


@pytest.mark.skipif(not ROBOT.exists() or shutil.which("java") is None, reason="needs java and tools/robot.jar")
def test_measurements_and_counts_classify_under_the_value_word(tmp_path):
    text = PROBE.read_text(encoding="utf-8")
    result, log = reason(tmp_path, text)
    for name in UNSATISFIABLE:  # two counts at once; a count below the range of the relation
        assert "unsatisfiable: " + NS + name in log
    result, log = reason(tmp_path, "\n".join(
        line for line in text.splitlines() if not any(name in line for name in UNSATISFIABLE)))
    assert "unsatisfiable" not in log

    def follows(sub: str, sup: str) -> bool:
        return f"SubClassOf(:{sub} :{sup})" in result or f"SubClassOf(<{NS}{sub}> <{NS}{sup}>)" in result

    assert follows("ProbeRatio4WidestAt03", "ProbeIsLanceolate")  # widest at 0.3 of the length, 4 times as long as wide
    assert follows("ProbeRatio4WidestAt03", "ProbeIsOvate")       # the manual's lanceolate is a narrow ovate
    assert follows("ProbeRatio12to20", "ProbeIsLinear")           # "12-20 times as long as wide"
    assert not follows("ProbeRatio2to3", "ProbeIsLinear")
    assert not follows("ProbeRatio2to3", "ProbeIsLanceolate")     # the ratio alone does not say where the blade is widest
    assert follows("ProbeApex60", "ProbeIsAcute") and follows("ProbeBase120", "ProbeIsObtuse")
    assert follows("ProbeAxisWith2PerNode", "ProbeIsOpposite") and follows("ProbeAxisWith4PerNode", "ProbeIsWhorled")
    assert not follows("ProbeAxisWith4PerNode", "ProbeIsOpposite")
