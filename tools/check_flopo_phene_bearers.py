#!/usr/bin/env python3
"""Release check: can a plant have each FLOPO phenotype, and each one together with its parents?

A FLOPO phenotype class is a phene (``flopo2/owl/phene.py``):

    P EquivalentTo: 'flora phenotype' and 'phenotype of' some Y

Because 'phenotype of' is functional and the inverse of 'has phenotype', a plant that has the
phene P has the defining property Y, and a plant that has P has every superclass of P as well,
with its defining property. That step needs a reasoner for all of OWL 2 DL. This check states it
in OWL 2 EL, once per class (the bearer axiom):

    'has phenotype' some P  SubClassOf  Y

and adds one probe class per phenotype class, ``probe(P) SubClassOf 'has phenotype' some P``. It
then classifies FLOPO with the Plant Ontology, PATO and the plant GO import, as the release
classification does, with ELK. An unsatisfiable probe is a phenotype no plant can have: its
defining property contradicts itself or that of a class above it (an asserted parent whose
bearer cannot be the same plant). The release requires that there is none.

    python -m tools.check_flopo_phene_bearers [--release ontology/flopo.owl] [--out bearers.ttl]

``--out`` keeps the bearer axioms (Turtle, to be read together with the release).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path

from rdflib import OWL, RDF, RDFS, BNode, Graph, URIRef

from flopo2.owl import phene
from tools import classify_flopo_release as release_tools

PROBE = "http://purl.obolibrary.org/obo/flopo/phene-bearer-check#"
_UNSATISFIABLE = re.compile(r"unsatisfiable:\s*(\S+)")


def with_bearers(graph: Graph) -> dict[str, str]:
    """Add the bearer axioms and the probes to the graph; ``{probe IRI: class IRI}``."""

    phene.declare_relations(graph)
    probes: dict[str, str] = {}
    classes = phene.phene_classes(graph)
    phene.bearer_axioms(graph, out=graph)
    for cls in sorted(classes):
        probe = URIRef(PROBE + str(cls).rsplit("/", 1)[-1])
        has = BNode()
        graph.add((has, RDF.type, OWL.Restriction))
        graph.add((has, OWL.onProperty, phene.HAS_PHENOTYPE))
        graph.add((has, OWL.someValuesFrom, cls))
        graph.add((probe, RDF.type, OWL.Class))
        graph.add((probe, RDFS.subClassOf, has))
        probes[str(probe)] = str(cls)
    return probes


def check(release: Path, po: Path, pato: Path, go: Path, out: Path | None = None, heap: str = "16g") -> dict:
    graph = Graph().parse(release.as_posix())
    before = len(graph)
    probes = with_bearers(graph)
    if out is not None:
        bridge = Graph()
        with_bearers_only = Graph().parse(release.as_posix())
        phene.bearer_axioms(with_bearers_only, out=bridge)
        # the expressions are those of the release: write them with the axioms that use them
        for node in list(bridge.objects(None, RDFS.subClassOf)):
            _copy_expression(with_bearers_only, bridge, node)
        bridge.serialize(out.as_posix(), format="turtle")
    robot = release_tools._robot_command(Path(release_tools.__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory(prefix="flopo-phene-bearers-") as directory:
        work = Path(directory)
        merged = release_tools.prepare_classification_input(graph, work, po, pato, go, robot)
        done = subprocess.run(
            [*robot, "reason", "--reasoner", "ELK", "--input", str(merged), "--output", str(work / "classified.ofn")],
            capture_output=True, text=True, check=False, env={**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{heap}"},
        )
    output = done.stdout + done.stderr
    found = set(_UNSATISFIABLE.findall(output))
    if "owlapi/error#" in output:
        raise RuntimeError("a bearer axiom could not be read by OWLAPI")
    if done.returncode and not found:
        raise RuntimeError("ELK run failed: " + " ".join(output.split())[-400:])
    return {
        "phenotype_classes": len(probes),
        "bearer_axioms": sum(len(v) for v in phene.phene_classes(graph).values()),
        "triples_added": len(graph) - before,
        "unsatisfiable_bearers": sorted(probes[iri] for iri in found if iri in probes),
        "other_unsatisfiable": sorted(iri for iri in found if iri not in probes),
    }


def _copy_expression(source: Graph, target: Graph, node, seen: set | None = None) -> None:
    seen = seen if seen is not None else set()
    if not isinstance(node, BNode) or node in seen:
        return
    seen.add(node)
    for predicate, value in source.predicate_objects(node):
        target.add((node, predicate, value))
        _copy_expression(source, target, value, seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--go", type=Path, default=Path("ontology/imports/go_import.owl"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    result = check(args.release, args.po, args.pato, args.go, args.out)
    print(f"{result['phenotype_classes']} phenotype classes, {result['bearer_axioms']} bearer axioms; "
          f"{len(result['unsatisfiable_bearers'])} phenotypes that no plant can have")
    for cls in result["unsatisfiable_bearers"][:50]:
        print("  " + cls)
    for iri in result["other_unsatisfiable"][:20]:
        print("  also unsatisfiable: " + iri)
    raise SystemExit(1 if result["unsatisfiable_bearers"] or result["other_unsatisfiable"] else 0)


if __name__ == "__main__":
    main()
