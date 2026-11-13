"""Check the annotation classes of a flora for contradictions with ELK.

Every annotated statement that can be a class has an OWL definition (its ``phenotype_class_iri``,
compiled by :mod:`flopo2.owl.assertions`). A definition can contradict the ontologies it is built
from: "leaf apex acute" grounded to PATO's *acute*, a quality of processes, describes nothing.
This check merges the definitions of one flora with the classification closure of the FLOPO
release (FLOPO, PO, PATO and the plant GO import, as ``tools/classify_flopo_release.py`` builds
it) and classifies the result with ELK through ROBOT. A class ELK finds unsatisfiable is

* listed in ``<source>-unsatisfiable.tsv`` with the statements that use it, and
* no longer ``accepted``: its assertions get gate status ``review`` with the reason
  ``unsatisfiable_annotation_class``.

ELK reads the EL part of the definitions; unions, complements and number ranges are passed over,
so the check is sound but not complete (docs/km-classification.md). It is skipped, with a note,
when Java or ROBOT is missing.

    python -m flopo2.verify.annotation_class_check eflora-mfoc
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REASON = "unsatisfiable_annotation_class"
CACHE = Path("local-corpora/cache")
INPUTS = {
    "flopo": Path("ontology/flopo.owl"),
    "po": Path("ont/plant_ontology.obo"),
    "pato": Path("ont/quality.obo"),
    "go": Path("ontology/imports/go_import.owl"),
}
_UNSATISFIABLE = re.compile(r"unsatisfiable:\s*(\S+)")


def classification_closure(cache: Path = CACHE) -> Path:
    """The merged FLOPO + PO + PATO + GO input of the release classification, built once per
    state of the four files."""

    from rdflib import Graph

    from tools import classify_flopo_release as release

    state = "|".join(f"{p}:{p.stat().st_size}:{int(p.stat().st_mtime)}" for p in INPUTS.values())
    target = cache / f"classification-closure-{hashlib.sha256(state.encode()).hexdigest()[:16]}.owl"
    if target.exists():
        return target
    cache.mkdir(parents=True, exist_ok=True)
    robot = release._robot_command(Path(release.__file__).resolve().parents[1])
    with tempfile.TemporaryDirectory(dir=cache, prefix="closure-") as work:
        merged = release.prepare_classification_input(
            Graph().parse(INPUTS["flopo"].as_posix()), Path(work), INPUTS["po"], INPUTS["pato"], INPUTS["go"], robot
        )
        os.replace(merged, target)
    for old in cache.glob("classification-closure-*.owl"):
        if old != target:
            old.unlink(missing_ok=True)
    return target


def write_class_definitions(annotated: Path, out: Path, chunk: int = 20000) -> dict[str, dict]:
    """Write ``EquivalentClasses(class, definition)`` of every annotation class of the corpus as
    N-Triples (valid Turtle); return ``{class IRI: {label, example, statements}}``."""

    from rdflib import OWL, RDF, Graph, URIRef

    from flopo2.owl import assertions
    from flopo2.verify import gates

    attributes = gates.load_pato_attribute_terms(Path("config/pato_lexicon.tsv"))
    nodes = assertions._Nodes()
    classes: dict[str, dict] = {}
    graph = Graph()
    with annotated.open(encoding="utf-8") as source, out.open("wb") as sink:
        sink.write(b"<http://phenomebrowser.net/flopo/annotation-class-check> "
                   b"<http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://www.w3.org/2002/07/owl#Ontology> .\n")
        for line in source:
            record = json.loads(line)
            for assertion in record.get("assertions") or []:
                iri = assertion.get("phenotype_class_iri")
                if not iri:
                    continue
                entry = classes.get(iri)
                if entry is not None:
                    entry["statements"] += 1
                    continue
                composition = assertion.get("composition") or {}
                classes[iri] = {
                    "label": f"{composition.get('entity_label', '')}: {composition.get('quality_label', '')}",
                    "bearer": assertion.get("po_id", ""), "quality": assertion.get("pato_id", ""),
                    "values": "|".join(assertion.get("value_terms") or []),
                    "example": assertion.get("source_text", "")[:120], "source_id": record.get("source_id", ""),
                    "statements": 1,
                }
                try:
                    expression = assertions._phenotype_expression(graph, nodes, assertion, attributes)[0]
                except ValueError:
                    continue  # not compilable: reported by the data-model validation
                graph.add((URIRef(iri), RDF.type, OWL.Class))
                graph.add((URIRef(iri), OWL.equivalentClass, expression))
                if len(graph) > chunk * 20:
                    sink.write(graph.serialize(format="nt", encoding="utf-8"))
                    graph = Graph()
        sink.write(graph.serialize(format="nt", encoding="utf-8"))
    return classes


def unsatisfiable_classes(definitions: Path, work: Path, heap: str = "24g") -> tuple[set[str] | None, str]:
    """``(unsatisfiable class IRIs, note)``; ``(None, why)`` when the check could not run."""

    from tools import classify_flopo_release as release

    try:
        robot = release._robot_command(Path(release.__file__).resolve().parents[1])
        closure = classification_closure()
    except (RuntimeError, OSError) as exc:
        return None, f"skipped: {exc}"
    env = {**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{heap}"}
    done = subprocess.run(
        [*robot, "merge", "--input", str(closure), "--input", str(definitions),
         "reason", "--reasoner", "ELK", "--output", str(work / "classified.ofn")],
        capture_output=True, text=True, check=False, env=env,
    )
    output = done.stdout + done.stderr
    found = set(_UNSATISFIABLE.findall(output))
    if "owlapi/error#" in output or "Entity not properly recognized" in output:
        return None, "failed: a class definition could not be read by OWLAPI"
    if done.returncode and not found:
        return None, "failed: " + " ".join(output.split())[-300:]
    return found, ""


def demote(annotated: Path, unsatisfiable: set[str]) -> int:
    """Set accepted assertions of unsatisfiable classes to review; rewrite the file only then."""

    def affected(assertion: dict) -> bool:
        gate = assertion.get("gate") or {}
        return assertion.get("phenotype_class_iri") in unsatisfiable and (
            gate.get("status") == "accepted" or REASON not in (gate.get("reasons") or [])
        )

    changed = 0
    fresh = annotated.with_name(annotated.name + ".unsat-check")
    with annotated.open(encoding="utf-8") as source, fresh.open("w", encoding="utf-8") as sink:
        for line in source:
            if not any(iri in line for iri in unsatisfiable):
                sink.write(line)
                continue
            record = json.loads(line)
            for assertion in record.get("assertions") or []:
                if affected(assertion):
                    gate = assertion.setdefault("gate", {})
                    gate["reasons"] = [*(gate.get("reasons") or []), REASON]
                    if gate.get("status") == "accepted":
                        gate["status"] = "review"
                    changed += 1
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
    if changed:
        os.replace(fresh, annotated)
    else:
        fresh.unlink()
    return changed


def check(source: str, annotated: Path | None = None, derived: Path | None = None) -> dict:
    derived = derived or Path("local-corpora") / source / "derived"
    annotated = annotated or derived / f"{source}-annotated.jsonl"
    report_path = derived / f"{source}-unsatisfiable.tsv"
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE, prefix=f"unsat-{source}-") as tmp:
        work = Path(tmp)
        classes = write_class_definitions(annotated, work / "definitions.ttl")
        found, note = unsatisfiable_classes(work / "definitions.ttl", work)
    result = {"source": source, "classes": len(classes), "unsatisfiable": None, "statements": 0,
              "marked": 0, "note": note, "report": str(report_path)}
    if found is None:
        return result
    found &= set(classes)
    rows = sorted(({"class": iri, **classes[iri]} for iri in found), key=lambda r: -r["statements"])
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=[
            "class", "label", "bearer", "quality", "values", "statements", "example", "source_id"])
        writer.writeheader()
        writer.writerows(rows)
    result.update({"unsatisfiable": len(found), "statements": sum(r["statements"] for r in rows),
                   "marked": demote(annotated, found) if found else 0})
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--annotated", type=Path, help="another annotated file (one source only)")
    parser.add_argument("--derived", type=Path, help="where the report goes (one source only)")
    args = parser.parse_args(argv)
    for source in args.sources:
        print(json.dumps(check(source, args.annotated, args.derived)), flush=True)


if __name__ == "__main__":
    main()
