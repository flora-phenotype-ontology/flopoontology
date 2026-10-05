#!/usr/bin/env python3
"""Remove orphaned blank-node descriptions from the RDF/XML release.

The extension release tools serialize every anonymous class expression of a module as its own
top-level ``<rdf:Description rdf:nodeID="...">`` element.  When a later tool replaces a class that
an earlier module declared (``tools.update_flopo_botanical_release._remove_named_owl_class``), only
the named class element is removed; the expression nodes it pointed to stay behind, unreferenced.
They are not axioms, but they keep dead references (for example to withdrawn PATO requests) in the
file and confuse RDF-level checks.

A top-level blank node is an orphan when nothing refers to it and it does not itself carry an
axiom (a general class axiom, an axiom annotation, a disjointness or a negative assertion).
Orphans are removed repeatedly until none remain, so whole dead expression trees disappear.
"""

from __future__ import annotations

import argparse
import re
from collections import Counter
from pathlib import Path

ELEMENT = re.compile(
    r'^  <rdf:Description rdf:nodeID="([^"]+)">\n.*?^  </rdf:Description>\n', re.DOTALL | re.MULTILINE
)
NODE_ID = re.compile(r'rdf:nodeID="([^"]+)"')
AXIOM_MARKERS = (
    "<rdfs:subClassOf",
    "<owl:equivalentClass",
    "<owl:disjointWith",
    "<owl:annotatedSource",
    "<owl:members",
    "<owl:distinctMembers",
    "<owl:sourceIndividual",
)


def prune(text: str) -> tuple[str, int]:
    removed_total = 0
    while True:
        # A node is used if its identifier occurs anywhere besides its own top-level element
        # (as a reference, or as a second inline description of the same node).
        occurrences = Counter(NODE_ID.findall(text))
        spans = []
        for match in ELEMENT.finditer(text):
            node, body = match.group(1), match.group(0)
            if occurrences[node] > 1 or any(marker in body for marker in AXIOM_MARKERS):
                continue
            spans.append(match.span())
        if not spans:
            return text, removed_total
        pieces, last = [], 0
        for start, end in spans:
            pieces.append(text[last:start])
            last = end
        pieces.append(text[last:])
        text = "".join(pieces)
        removed_total += len(spans)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release", type=Path, nargs="?", default=Path("ontology/flopo.owl"))
    parser.add_argument("--check", action="store_true", help="report only; exit 1 if orphans exist")
    args = parser.parse_args()
    text = args.release.read_text(encoding="utf-8")
    pruned, removed = prune(text)
    print(f"orphaned blank-node descriptions: {removed}")
    if args.check:
        raise SystemExit(1 if removed else 0)
    if removed:
        args.release.write_text(pruned, encoding="utf-8")


if __name__ == "__main__":
    main()
