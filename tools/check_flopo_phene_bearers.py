#!/usr/bin/env python3
"""Release check with the bearer axioms: can a plant have each FLOPO phenotype?

``ontology/flopo-bearer-axioms.ofn`` (``tools/build_flopo_phene_bearers.py``) states, for every
phenotype class P with defining property Y, the consequence of the functional 'phenotype of'
that ELK does not draw by itself:

    'has phenotype' some P  SubClassOf  Y

This check

1. requires that the file is the one built from the release (same version, same axioms), and
2. classifies the release with the Plant Ontology, PATO and the plant GO import, as the release
   classification does, together with the file and one probe class per phenotype class,
   ``probe(P) SubClassOf 'has phenotype' some P``, with ELK. An unsatisfiable probe is a
   phenotype no plant can have: its defining property contradicts itself or that of a class
   asserted above it. The release requires that there is none.

    python -m tools.check_flopo_phene_bearers [--release ontology/flopo.owl]
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
from flopo2.owl.io import serialize_ontology
from tools import build_flopo_phene_bearers as bearers
from tools import classify_flopo_release as release_tools

PROBE = "http://purl.obolibrary.org/obo/flopo/phene-bearer-check#"
_UNSATISFIABLE = re.compile(r"unsatisfiable:\s*(\S+)")
_IMPORT = re.compile(r"^Import\(<[^>]+>\)\n", re.MULTILINE)


def probes_for(classes) -> tuple[Graph, dict[str, str]]:
    """One class per phenotype class that has the phenotype; ``(graph, {probe IRI: class IRI})``."""

    graph = Graph()
    graph.add((URIRef(PROBE.rstrip("#")), RDF.type, OWL.Ontology))
    graph.add((phene.HAS_PHENOTYPE, RDF.type, OWL.ObjectProperty))
    probes: dict[str, str] = {}
    for cls in sorted(classes):
        probe = URIRef(PROBE + str(cls).rsplit("/", 1)[-1])
        has = BNode()
        graph.add((has, RDF.type, OWL.Restriction))
        graph.add((has, OWL.onProperty, phene.HAS_PHENOTYPE))
        graph.add((has, OWL.someValuesFrom, cls))
        graph.add((cls, RDF.type, OWL.Class))
        graph.add((probe, RDF.type, OWL.Class))
        graph.add((probe, RDFS.subClassOf, has))
        probes[str(probe)] = str(cls)
    return graph, probes


def with_bearers(graph: Graph) -> dict[str, str]:
    """Add the bearer axioms and the probes to a graph (small inputs, tests)."""

    classes = phene.phene_classes(graph)
    phene.declare_relations(graph)
    phene.bearer_axioms(graph, out=graph)
    probe_graph, probes = probes_for(classes)
    for triple in probe_graph:
        graph.add(triple)
    return probes


def is_current(release: Path, bridge: Path, work: Path) -> tuple[bool, dict]:
    """Whether the bridge file is exactly what the release gives."""

    graph, stats = bearers.build(release)
    fresh = work / "fresh.ofn"
    serialize_ontology(graph, fresh, "ofn")
    return bridge.is_file() and fresh.read_bytes() == bridge.read_bytes(), stats


def check(release: Path, bridge: Path, po: Path, pato: Path, go: Path, heap: str = "16g") -> dict:
    source = Graph().parse(release.as_posix())
    probe_graph, probes = probes_for(phene.phene_classes(source))
    robot = release_tools._robot_command(Path(release_tools.__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory(prefix="flopo-phene-bearers-") as directory:
        work = Path(directory)
        current, stats = is_current(release, bridge, work)
        if not current:
            return {**stats, "current": False, "unsatisfiable_bearers": [], "other_unsatisfiable": []}
        merged = release_tools.prepare_classification_input(source, work, po, pato, go, robot)
        local_bridge = work / "bridge.ofn"  # the import is the release, which is merged from its file
        local_bridge.write_text(_IMPORT.sub("", bridge.read_text(encoding="utf-8")), encoding="utf-8")
        probe_path = work / "probes.ttl"
        probe_graph.serialize(probe_path.as_posix(), format="turtle")
        done = subprocess.run(
            [*robot, "merge", "--input", str(merged), "--input", str(local_bridge), "--input", str(probe_path),
             "reason", "--reasoner", "ELK", "--output", str(work / "classified.ofn")],
            capture_output=True, text=True, check=False, env={**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{heap}"},
        )
    output = done.stdout + done.stderr
    found = set(_UNSATISFIABLE.findall(output))
    if "owlapi/error#" in output:
        raise RuntimeError("a bearer axiom could not be read by OWLAPI")
    if done.returncode and not found:
        raise RuntimeError("ELK run failed: " + " ".join(output.split())[-400:])
    return {
        **stats, "current": True,
        "unsatisfiable_bearers": sorted(probes[iri] for iri in found if iri in probes),
        "other_unsatisfiable": sorted(iri for iri in found if iri not in probes),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--bridge", type=Path, default=bearers.OUTPUT)
    parser.add_argument("--po", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--go", type=Path, default=Path("ontology/imports/go_import.owl"))
    args = parser.parse_args()
    result = check(args.release, args.bridge, args.po, args.pato, args.go)
    if not result["current"]:
        print(f"{args.bridge} is not what {args.release} (version {result['version']}) gives: "
              "run python -m tools.build_flopo_phene_bearers")
        raise SystemExit(1)
    print(f"{args.bridge}: version {result['version']}, {result['axioms']} bearer axioms of {result['classes']} "
          f"phenotype classes; {len(result['unsatisfiable_bearers'])} phenotypes that no plant can have")
    for cls in result["unsatisfiable_bearers"][:50]:
        print("  " + cls)
    for iri in result["other_unsatisfiable"][:20]:
        print("  also unsatisfiable: " + iri)
    raise SystemExit(1 if result["unsatisfiable_bearers"] or result["other_unsatisfiable"] else 0)


if __name__ == "__main__":
    main()
