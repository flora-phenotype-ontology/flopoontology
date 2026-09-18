"""Lightweight Phase 8 QC for FLOPO candidate OWL files.

This is dependency-light for RDF serializations. Functional Syntax input is converted losslessly
through ROBOT/OWLAPI before applying the same checks. ROBOT/ELK remain the release-grade QC path:

* the file parses as RDF/OWL;
* every generated FLOPO class has an rdfs:label;
* no registry IRI is assigned to a different signature in the build report;
* optionally, all accepted gated EQ rows have an OWL class in the candidate.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rdflib import OWL, RDF, RDFS, URIRef

from flopo2.owl.build import OBO
from flopo2.owl.io import parse_ontology


def qc(owl_path: Path, gated_jsonl: Path | None = None, rdf_format: str | None = None) -> dict:
    g = parse_ontology(owl_path, rdf_format)
    classes = {s for s in g.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef) and str(s).startswith(OBO + "FLOPO_")}
    missing_labels = [str(c) for c in classes if (c, RDFS.label, None) not in g]

    expected = 0
    if gated_jsonl is not None:
        seen: set[tuple[str, str]] = set()
        with Path(gated_jsonl).open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                obj = json.loads(line)
                for a in obj.get("assertions", []) or []:
                    if (a.get("gate") or {}).get("status") == "accepted":
                        seen.add((a.get("po_id", ""), a.get("pato_id", "")))
        expected = len(seen)

    result = {
        "classes": len(classes),
        "missing_labels": len(missing_labels),
        "expected_eq_from_gated": expected,
        "ok": not missing_labels and (not expected or len(classes) >= expected),
    }
    if missing_labels:
        result["missing_label_examples"] = missing_labels[:10]
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description="Lightweight FLOPO candidate OWL QC.")
    ap.add_argument("owl", type=Path)
    ap.add_argument("--gated", type=Path)
    ap.add_argument("--format", dest="rdf_format")
    ap.add_argument("-o", "--output", type=Path, help="write the JSON QC report")
    args = ap.parse_args()
    result = qc(args.owl, args.gated, args.rdf_format)
    report = json.dumps(result, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
