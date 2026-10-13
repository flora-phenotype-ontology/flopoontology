#!/usr/bin/env python3
"""Assert the classified hierarchy of FLOPO classes in flopo.owl (asserted-hierarchy release).

Most FLOPO classes are defined only by ``EquivalentClasses`` axioms over PO and PATO, so their
place in the hierarchy exists only after reasoning with both imports.  Browsers that show the
asserted hierarchy (BioPortal) or that cannot load the imports (AberOWL when ``po.owl``/``pato.owl``
fail to load) then show tens of thousands of classes in one flat list.  As in ODK releases, the
main release file therefore carries the reasoner's direct named superclasses as asserted axioms.

This final pass reads ``ontology/flopo-inferred.owl`` (``tools/classify_flopo_release.py``) and
writes, for every live FLOPO class, the direct inferred named superclasses that ``flopo.owl`` does
not already assert, into one generated block.  It replaces the bearer-phenotype block of
``tools/update_flopo_bearer_parents.py`` (those axioms are entailed by the materialized ones).
Run order: bearer parents, classify, this pass, classify again (the result is unchanged).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef

from tools import update_flopo_bearer_parents as bearer

OBO = "http://purl.obolibrary.org/obo/"
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO INFERRED SUPERCLASSES -->"
END_MARKER = "  <!-- END GENERATED FLOPO INFERRED SUPERCLASSES -->"


def _without_block(text: str) -> str:
    if text.count(BEGIN_MARKER) != text.count(END_MARKER) or text.count(BEGIN_MARKER) > 1:
        raise ValueError("malformed inferred-superclass markers")
    pattern = re.compile(rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL)
    return pattern.sub("\n", text, count=1)


def inferred_additions(release: Path, inferred: Path) -> dict[str, list[str]]:
    asserted_graph = Graph().parse(release.as_posix())
    inferred_graph = Graph().parse(inferred.as_posix())
    additions: dict[str, list[str]] = {}
    for cls in set(inferred_graph.subjects(RDF.type, OWL.Class)):
        if not isinstance(cls, URIRef) or not str(cls).startswith(OBO + "FLOPO_"):
            continue
        if (cls, OWL.deprecated, Literal(True)) in asserted_graph:
            continue
        direct = {o for o in inferred_graph.objects(cls, RDFS.subClassOf) if isinstance(o, URIRef) and o != OWL.Thing}
        have = {o for o in asserted_graph.objects(cls, RDFS.subClassOf) if isinstance(o, URIRef)}
        missing = sorted(str(o) for o in direct - have)
        if missing:
            additions[str(cls)] = missing
    return additions


def update_release(release: Path, inferred: Path) -> int:
    text = bearer._without_block(_without_block(release.read_text(encoding="utf-8")))
    release.write_text(text, encoding="utf-8")
    additions = inferred_additions(release, inferred)
    lines = [BEGIN_MARKER]
    for child, parents in sorted(additions.items()):
        lines.append(f'  <rdf:Description rdf:about="{child}">')
        lines += [f'    <rdfs:subClassOf rdf:resource="{parent}"/>' for parent in parents]
        lines.append("  </rdf:Description>")
    lines.append(END_MARKER)
    text = text.replace("</rdf:RDF>", "\n".join(lines) + "\n</rdf:RDF>", 1)
    release.write_text(text, encoding="utf-8")
    return sum(len(p) for p in additions.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--inferred", type=Path, default=Path("ontology/flopo-inferred.owl"))
    args = parser.parse_args()
    print(f"asserted {update_release(args.release, args.inferred)} inferred direct superclass axioms")


if __name__ == "__main__":
    main()
