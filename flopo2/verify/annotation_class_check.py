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

The same run checks each **taxon**: can one plant have all the accepted statements of the taxon
at once? "Petals absent" and "petals white" cannot. ELK passes over negation, so the question is
put in a form it reads. For an absence class N = not (has part some X) the run adds a class for
the presence, P(N) = has part some X, and a marker class M(N) declared disjoint with P(N); the
taxon class is the conjunction of the taxon's positive classes and the markers of its absences.
It is unsatisfiable exactly when the positive statements entail a presence the taxon denies;
the run also states that a plant part that is described is present (plant anatomical entity
SubClassOf has quality some present), so that "leaves absent" contradicts "leaves glabrous". A
second run on the pairs (one positive class and one marker) of those taxa names the two
statements. They are

* listed in ``<source>-taxon-contradictions.tsv``, and
* set to ``review`` with the reason ``contradiction_within_taxon``, in that taxon only.

Only accepted statements without a frequency ("rarely absent") take part. A complete OWL
reasoner on one taxon at a time is the direct way to ask this and was tried
(``tools/TaxonConsistency.java``, docs/km-classification.md): HermiT needs about 15 s per taxon
and KM does not finish, because the part of PO and PATO that one taxon depends on still has
5,000 to 11,000 axioms.

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
TAXON_REASON = "contradiction_within_taxon"
CHECK = "http://phenomebrowser.net/flopo/annotation-class-check/"
OBO = "http://purl.obolibrary.org/obo/"
_CLASS_IRI = re.compile(r"http://phenomebrowser\.net/flopo/annotation-class/FAC_[0-9a-f]+")
_STRICT_FREQUENCIES = {"", "unspecified", "universal"}
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


def _in_taxon_check(assertion: dict) -> bool:
    """Statements said of every plant of the taxon: accepted, asserted, without a frequency."""

    return (
        (assertion.get("gate") or {}).get("status") == "accepted"
        and (assertion.get("frequency_qualifier") or "") in _STRICT_FREQUENCIES
        and (assertion.get("epistemic_modality") or "asserted") == "asserted"
    )


def _is_absence(assertion: dict) -> bool:
    return bool(assertion.get("negated")) and (assertion.get("negation_scope") or "absence") == "absence"


def write_class_definitions(
    annotated: Path, out: Path, chunk: int = 20000, taxa: dict | None = None, absences: dict | None = None
) -> dict[str, dict]:
    """Write ``EquivalentClasses(class, definition)`` of every annotation class of the corpus as
    N-Triples (valid Turtle); return ``{class IRI: {label, example, statements}}``.

    With ``taxa`` and ``absences`` (empty dicts) also collect, for the taxon check,
    ``taxa[taxon] = {"present": {class: text}, "absent": {class: text}}`` and one assertion per
    absence class."""

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
                if taxa is not None and record.get("taxon") and _in_taxon_check(assertion):
                    kind = "absent" if _is_absence(assertion) else "present"
                    taxon = taxa.setdefault(record["taxon"], {"present": {}, "absent": {}})
                    taxon[kind].setdefault(iri, assertion.get("source_text", "")[:120])
                    if kind == "absent" and absences is not None:
                        absences.setdefault(iri, assertion)
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


def _marker(absence_class: str) -> str:
    return CHECK + "not-present/" + absence_class.rsplit("/", 1)[-1]


def write_taxon_classes(taxa: dict, absences: dict, out: Path) -> dict[str, str]:
    """For every taxon with an absence and a positive statement write the taxon class (module
    docstring); return ``{taxon class IRI: taxon}``."""

    from rdflib import OWL, RDF, RDFS, Graph, URIRef

    from flopo2.owl import assertions
    from flopo2.verify import gates

    attributes = gates.load_pato_attribute_terms(Path("config/pato_lexicon.tsv"))
    nodes = assertions._Nodes()
    graph = Graph()
    graph.add((URIRef(CHECK + "taxa"), RDF.type, OWL.Ontology))
    checked = {name: taxon for name, taxon in sorted(taxa.items()) if taxon["absent"] and taxon["present"]}
    # Absence is "no part that has the quality present" (PATO:0000467). A part that is described
    # at all is present: without this axiom "leaves absent" contradicts "leaves present" only,
    # not "leaves glabrous".
    exists = assertions._some(graph, nodes, assertions.HAS_QUALITY, URIRef(OBO + "PATO_0000467"))
    graph.add((URIRef(OBO + "PATO_0000467"), RDF.type, OWL.Class))
    graph.add((URIRef(OBO + "PO_0025131"), RDF.type, OWL.Class))
    graph.add((URIRef(OBO + "PO_0025131"), RDFS.subClassOf, exists))
    usable: set[str] = set()
    for iri in sorted({iri for taxon in checked.values() for iri in taxon["absent"]}):
        try:
            presence = assertions._phenotype_expression(
                graph, nodes, {**absences[iri], "negated": False, "negation_scope": ""}, attributes)[0]
        except (KeyError, ValueError):
            continue
        present, marker = URIRef(CHECK + "present/" + iri.rsplit("/", 1)[-1]), URIRef(_marker(iri))
        for name in (present, marker):
            graph.add((name, RDF.type, OWL.Class))
        graph.add((present, OWL.equivalentClass, presence))
        graph.add((marker, OWL.disjointWith, present))
        usable.add(iri)
    taxon_classes: dict[str, str] = {}
    for index, (name, taxon) in enumerate(checked.items()):
        markers = [URIRef(_marker(iri)) for iri in sorted(taxon["absent"]) if iri in usable]
        if not markers:
            continue
        iri = URIRef(f"{CHECK}taxon/{index}")
        members = [URIRef(i) for i in sorted(taxon["present"])] + markers
        for member in members:
            graph.add((member, RDF.type, OWL.Class))
        graph.add((iri, RDF.type, OWL.Class))
        graph.add((iri, OWL.equivalentClass, assertions._intersection(graph, nodes, members)))
        taxon_classes[str(iri)] = name
    out.write_bytes(graph.serialize(format="nt", encoding="utf-8"))
    return taxon_classes


def write_pair_classes(taxa: dict, suspects: set[str], unsatisfiable: set[str], out: Path) -> dict[str, tuple[str, str]]:
    """One class per (positive class, absence) of the suspect taxa; ``{pair IRI: (positive,
    absence)}``. A positive class that is unsatisfiable by itself contradicts nothing else."""

    from rdflib import OWL, RDF, BNode, Graph, URIRef
    from rdflib.collection import Collection

    graph = Graph()
    graph.add((URIRef(CHECK + "pairs"), RDF.type, OWL.Ontology))
    pairs: dict[str, tuple[str, str]] = {}
    for name in sorted(suspects):
        for present in sorted(set(taxa[name]["present"]) - unsatisfiable):
            for absent in sorted(taxa[name]["absent"]):
                iri = CHECK + "pair/" + hashlib.sha1(f"{present}|{absent}".encode()).hexdigest()[:24]
                if iri in pairs:
                    continue
                pairs[iri] = (present, absent)
                expression, members = BNode(), BNode()
                Collection(graph, members, [URIRef(present), URIRef(_marker(absent))])
                graph.add((expression, RDF.type, OWL.Class))
                graph.add((expression, OWL.intersectionOf, members))
                graph.add((URIRef(iri), RDF.type, OWL.Class))
                graph.add((URIRef(iri), OWL.equivalentClass, expression))
    out.write_bytes(graph.serialize(format="nt", encoding="utf-8"))
    return pairs


def unsatisfiable_classes(
    definitions: Path | list[Path], work: Path, heap: str = "24g"
) -> tuple[set[str] | None, str]:
    """``(unsatisfiable class IRIs, note)``; ``(None, why)`` when the check could not run."""

    from tools import classify_flopo_release as release

    try:
        robot = release._robot_command(Path(release.__file__).resolve().parents[1])
        closure = classification_closure()
    except (RuntimeError, OSError) as exc:
        return None, f"skipped: {exc}"
    env = {**os.environ, "JAVA_TOOL_OPTIONS": f"-Xmx{heap}"}
    done = subprocess.run(
        [*robot, "merge", "--input", str(closure),
         *(part for path in ([definitions] if isinstance(definitions, Path) else definitions)
           for part in ("--input", str(path))),
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


def demote(annotated: Path, unsatisfiable: set[str], reason: str = REASON,
           in_taxa: dict[str, set[str]] | None = None) -> int:
    """Set accepted assertions of the given classes to review; rewrite the file only then. With
    ``in_taxa`` (``{taxon: classes}``) only the statements of those taxa are meant."""

    def affected(assertion: dict, classes: set[str]) -> bool:
        gate = assertion.get("gate") or {}
        return assertion.get("phenotype_class_iri") in classes and (
            gate.get("status") == "accepted" or reason not in (gate.get("reasons") or [])
        )

    changed = 0
    fresh = annotated.with_name(annotated.name + ".unsat-check")
    with annotated.open(encoding="utf-8") as source, fresh.open("w", encoding="utf-8") as sink:
        for line in source:
            if unsatisfiable.isdisjoint(_CLASS_IRI.findall(line)):
                sink.write(line)
                continue
            record = json.loads(line)
            classes = unsatisfiable if in_taxa is None else in_taxa.get(record.get("taxon") or "", set())
            for assertion in record.get("assertions") or []:
                if affected(assertion, classes):
                    gate = assertion.setdefault("gate", {})
                    gate["reasons"] = [*(gate.get("reasons") or []), reason]
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
        taxa: dict[str, dict] = {}
        absences: dict[str, dict] = {}
        inputs = [work / "definitions.ttl", work / "taxa.ttl"]
        classes = write_class_definitions(annotated, inputs[0], taxa=taxa, absences=absences)
        taxon_classes = write_taxon_classes(taxa, absences, inputs[1])
        everything, note = unsatisfiable_classes(inputs, work)
        found = None if everything is None else everything & set(classes)
        contradictions = None
        if everything is not None:
            suspects = {taxon_classes[iri] for iri in everything if iri in taxon_classes}
            contradictions = []
            if suspects:
                pairs = write_pair_classes(taxa, suspects, found, work / "pairs.ttl")
                second, pair_note = unsatisfiable_classes([*inputs, work / "pairs.ttl"], work)
                if second is None:
                    contradictions, note = None, f"taxon check {pair_note}"
                else:
                    contradictions = _contradictions(taxa, suspects, found, pairs, second)
    result = {"source": source, "classes": len(classes), "unsatisfiable": None, "statements": 0,
              "marked": 0, "taxa_checked": len(taxon_classes), "taxon_contradictions": None,
              "taxon_statements_marked": 0, "note": note, "report": str(report_path)}
    if found is None:
        return result
    if contradictions is not None:
        result.update(_report_contradictions(
            contradictions, classes, annotated, derived / f"{source}-taxon-contradictions.tsv"))
    rows = sorted(({"class": iri, **classes[iri]} for iri in found), key=lambda r: -r["statements"])
    with report_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=[
            "class", "label", "bearer", "quality", "values", "statements", "example", "source_id"])
        writer.writeheader()
        writer.writerows(rows)
    result.update({"unsatisfiable": len(found), "statements": sum(r["statements"] for r in rows),
                   "marked": demote(annotated, found) if found else 0})
    return result


def _contradictions(taxa: dict, suspects: set[str], unsatisfiable: set[str], pairs: dict,
                    second: set[str]) -> list[dict]:
    """Rows ``{taxon, present, absent, present_text, absent_text}`` of the suspect taxa."""

    contradicting = {pair for iri, pair in pairs.items() if iri in second}
    rows = []
    for name in sorted(suspects):
        taxon = taxa[name]
        hits = [(p, a) for p in sorted(taxon["present"]) for a in sorted(taxon["absent"]) if (p, a) in contradicting]
        if not hits and not set(taxon["present"]) & unsatisfiable:
            # no single statement contradicts an absence: several do together
            hits = [("", a) for a in sorted(taxon["absent"])]
        rows.extend({"taxon": name, "present": p, "absent": a, "present_text": taxon["present"].get(p, ""),
                     "absent_text": taxon["absent"][a]} for p, a in hits)
    return rows


def _report_contradictions(rows: list[dict], classes: dict, annotated: Path, report: Path) -> dict:
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=[
            "taxon", "absent_label", "absent_text", "present_label", "present_text", "absent", "present"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "absent_label": classes.get(row["absent"], {}).get("label", ""),
                             "present_label": classes.get(row["present"], {}).get("label", "")})
    in_taxa: dict[str, set[str]] = {}
    for row in rows:
        in_taxa.setdefault(row["taxon"], set()).update(i for i in (row["present"], row["absent"]) if i)
    marked = demote(annotated, set().union(*in_taxa.values()), TAXON_REASON, in_taxa) if in_taxa else 0
    return {"taxon_contradictions": len(in_taxa), "taxon_statements_marked": marked,
            "taxon_report": str(report)}


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
