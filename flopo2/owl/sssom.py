"""Generate lightweight SSSOM mappings from FLOPO classes to TO/OBA targets.

The release build can run without network access: target ontologies are local OBO files. Exact
normalized label matches are emitted as ``skos:exactMatch``; broader lexical heuristics are left to
curation rather than silently creating weak mappings.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from rdflib import OWL, RDF, RDFS, URIRef

from flopo2.owl.build import OBO
from flopo2.owl.io import parse_ontology

SKOS_EXACT = "skos:exactMatch"
FLOPO_PREFIX = OBO + "FLOPO_"


@dataclass(frozen=True)
class TargetTerm:
    curie: str
    label: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def load_obo_labels(path: Path) -> dict[str, TargetTerm]:
    terms: dict[str, TargetTerm] = {}
    curie = ""
    label = ""
    obsolete = False
    in_term = False

    def flush() -> None:
        if in_term and curie and label and not obsolete:
            terms[_norm(label)] = TargetTerm(curie, label)

    with Path(path).open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line == "[Term]":
                flush()
                curie, label, obsolete, in_term = "", "", False, True
                continue
            if line.startswith("[") and line != "[Term]":
                flush()
                curie, label, obsolete, in_term = "", "", False, False
                continue
            if not in_term:
                continue
            if line.startswith("id: "):
                curie = line[4:].strip()
            elif line.startswith("name: "):
                label = line[6:].strip()
            elif line == "is_obsolete: true":
                obsolete = True
        flush()
    return terms


def load_flopo_labels(owl_path: Path) -> dict[str, str]:
    g = parse_ontology(owl_path)
    out: dict[str, str] = {}
    for cls in g.subjects(RDF.type, OWL.Class):
        if isinstance(cls, URIRef) and str(cls).startswith(FLOPO_PREFIX):
            label = next((str(o) for o in g.objects(cls, RDFS.label)), "")
            if label:
                out[str(cls).replace(OBO, "")] = label
    return out


def generate_mappings(owl_path: Path, targets: dict[str, Path], out_path: Path) -> dict:
    flopo = load_flopo_labels(owl_path)
    target_indexes = {prefix: load_obo_labels(path) for prefix, path in targets.items() if path.exists()}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for flopo_id, label in sorted(flopo.items()):
        normalized = _norm(label)
        for prefix, terms in sorted(target_indexes.items()):
            target = terms.get(normalized)
            if target is None:
                continue
            rows.append({
                "subject_id": flopo_id,
                "subject_label": label,
                "predicate_id": SKOS_EXACT,
                "object_id": target.curie,
                "object_label": target.label,
                "mapping_justification": "semapv:LexicalMatching",
                "confidence": "1.0",
                "mapping_tool": "flopo2.owl.sssom",
                "comment": f"Exact normalized label match against {prefix}.",
            })

    with out_path.open("w", encoding="utf-8", newline="") as fh:
        fh.write("# curie_map:\n")
        fh.write("#   FLOPO: http://purl.obolibrary.org/obo/FLOPO_\n")
        fh.write("#   TO: http://purl.obolibrary.org/obo/TO_\n")
        fh.write("#   OBA: http://purl.obolibrary.org/obo/OBA_\n")
        fh.write("#   skos: http://www.w3.org/2004/02/skos/core#\n")
        fh.write("#   semapv: https://w3id.org/semapv/vocab/\n")
        writer = csv.DictWriter(
            fh,
            delimiter="\t",
            lineterminator="\n",
            fieldnames=[
                "subject_id",
                "subject_label",
                "predicate_id",
                "object_id",
                "object_label",
                "mapping_justification",
                "confidence",
                "mapping_tool",
                "comment",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)
    return {
        "flopo_classes": len(flopo),
        "targets_loaded": {prefix: len(idx) for prefix, idx in target_indexes.items()},
        "mappings": len(rows),
        "out": str(out_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate FLOPO→TO/OBA SSSOM mappings by exact labels.")
    ap.add_argument("owl", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("ontology/flopo-v2-mappings.sssom.tsv"))
    ap.add_argument("--to", type=Path, default=Path("ont/trait.obo"))
    ap.add_argument("--oba", type=Path, default=Path("ont/oba.obo"))
    args = ap.parse_args()
    result = generate_mappings(args.owl, {"TO": args.to, "OBA": args.oba}, args.out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
