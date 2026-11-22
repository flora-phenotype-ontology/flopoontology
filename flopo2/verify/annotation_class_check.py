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

A phenotype class is a phene, a quality of the plant: ``'flora phenotype' and 'phenotype of'
some Y``, where Y is the defining property (``has part some (leaf and has characteristic some
glabrous)``; flopo2/owl/phene.py). 'phenotype of' is functional and the inverse of 'has
phenotype', so a plant that has the phene of Y is a Y, and a plant with two phenes has both
defining properties. That step is outside OWL EL. The run states it once per class, in a form ELK
reads (the bearer axiom):

    'has phenotype' some C  SubClassOf  Y

The same run checks each **taxon**: can one plant have all the accepted statements of the taxon
at once? "Petals absent" and "petals white" cannot. The taxon is a class T with ``T SubClassOf
'has phenotype' some C`` for each of its classes, as in the published data. ELK passes over
negation, so for an absence class N, whose defining property is ``not P``, the bearer axiom is
``'has phenotype' some N SubClassOf M(N)`` with a marker class M(N) declared disjoint with the
presence P. T is unsatisfiable exactly when the positive statements entail a presence the taxon
denies.

The absence of a part X is N = not (has part some (part of some X)) (Gkoutos, Schofield and
Hoehndorf 2018, doi:10.1093/bib/bbx035), so P = has part some (part of some X): "leaves absent"
contradicts "leaf blade ovate" as well, because a leaf blade is part of a leaf. OWL EL cannot say
that part of is reflexive; the run states it for each absent part (X SubClassOf part of some X),
so that "leaves absent" also contradicts "leaves glabrous". For the other negated classes (a part
without a quality) the run states that a plant part that is described is present (plant
anatomical entity SubClassOf has quality some present). A
second run on the pairs (a plant with one positive class and one absence) of those taxa names
the two statements. They are

* listed in ``<source>-taxon-contradictions.tsv``, and
* set to ``review`` with the reason ``contradiction_within_taxon``, in that taxon only.

Only accepted statements without a frequency ("rarely absent") take part. A complete OWL
reasoner on one taxon at a time asks the same question of the axioms as published, with the
functional property and without the bearer axioms: ``tools/PheneTaxonConsistency.java`` (HermiT
on a locality module per taxon, about a second each; docs/phene-consistency.md). The tests
compare the two on the same cases.

ELK reads the EL part of the definitions; unions, complements and number ranges are passed over,
so the check is sound but not complete (docs/km-classification.md). A class with a number range
("awn 3-5 mm long") would be lost whole; it gets a second bearer axiom without the number
(``'has phenotype' some C SubClassOf has part some awn``), so that it contradicts "awns absent". It is skipped, with a note,
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
    annotated: Path, out: Path, chunk: int = 20000, taxa: dict | None = None, absences: dict | None = None,
    bearers: bool = True,
) -> dict[str, dict]:
    """Write ``EquivalentClasses(class, definition)`` of every annotation class of the corpus as
    N-Triples (valid Turtle); return ``{class IRI: {label, example, statements}}``.

    With ``bearers`` the bearer axiom of every class that is not an absence is written as well
    (module docstring); without, the file holds the definitions as they are published.

    With ``taxa`` and ``absences`` (empty dicts) also collect, for the taxon check,
    ``taxa[taxon] = {"present": {class: text}, "absent": {class: text}}`` and one assertion per
    absence class."""

    from rdflib import OWL, RDF, RDFS, Graph, URIRef

    from flopo2.owl import assertions, phene
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
                    expression, numeric = assertions._phenotype_expression(graph, nodes, assertion, attributes)[:2]
                except ValueError:
                    continue  # not compilable: reported by the data-model validation
                graph.add((URIRef(iri), RDF.type, OWL.Class))
                graph.add((URIRef(iri), OWL.equivalentClass, expression))
                if bearers and not _is_absence(assertion):  # an absence gets its marker in the taxon check
                    graph.add((_bearer_of(graph, iri), RDFS.subClassOf, phene.phene_body(graph, expression)))
                    if numeric:  # ELK passes over a number range: state the part without it
                        part = _without_numbers(graph, phene.phene_body(graph, expression))
                        if part is not None:
                            graph.add((_bearer_of(graph, iri), RDFS.subClassOf, part))
                if len(graph) > chunk * 20:
                    sink.write(graph.serialize(format="nt", encoding="utf-8"))
                    graph = Graph()
        sink.write(graph.serialize(format="nt", encoding="utf-8"))
    return classes


def _bearer_of(graph, cls: str):
    """``'has phenotype' some cls``: the plants that have the phene (a fresh node per axiom)."""

    from rdflib import OWL, RDF, BNode, URIRef

    from flopo2.owl import phene

    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, phene.HAS_PHENOTYPE))
    graph.add((node, OWL.someValuesFrom, URIRef(cls)))
    graph.add((phene.HAS_PHENOTYPE, RDF.type, OWL.ObjectProperty))
    return node


def _has_number(graph, node, seen: set | None = None) -> bool:
    """Does the expression hold a restriction on a number (a datatype with facets)?"""

    from rdflib import OWL, BNode

    seen = set() if seen is None else seen
    if not isinstance(node, BNode) or node in seen:
        return False
    seen.add(node)
    if graph.value(node, OWL.withRestrictions) is not None or graph.value(node, OWL.onDataRange) is not None:
        return True
    return any(_has_number(graph, target, seen) for target in graph.objects(node, None))


def _without_numbers(graph, body):
    """``has part some (E and ... )`` without the conjuncts that hold a number: "awn 3-5 mm long"
    gives "has part some awn". None when the defining property is not of that form. A conjunct
    less is a weaker statement, so the axiom is entailed by the bearer axiom of the class."""

    from rdflib import OWL, RDF, BNode
    from rdflib.collection import Collection

    from flopo2.owl import phene

    if not isinstance(body, BNode) or (body, OWL.onProperty, phene.HAS_PART) not in graph:
        return None
    filler = graph.value(body, OWL.someValuesFrom)
    members = graph.value(filler, OWL.intersectionOf) if isinstance(filler, BNode) else None
    if members is None:
        return None
    kept = [item for item in Collection(graph, members) if not _has_number(graph, item)]
    if not kept:
        return None
    if len(kept) == 1:
        target = kept[0]
    else:
        target, head = BNode(), BNode()
        graph.add((target, RDF.type, OWL.Class))
        graph.add((target, OWL.intersectionOf, head))
        Collection(graph, head, kept)
    node = BNode()
    graph.add((node, RDF.type, OWL.Restriction))
    graph.add((node, OWL.onProperty, phene.HAS_PART))
    graph.add((node, OWL.someValuesFrom, target))
    return node


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
    reflexive: set[str] = set()
    for iri in sorted({iri for taxon in checked.values() for iri in taxon["absent"]}):
        try:
            absence = absences[iri]
            if assertions.is_absence_of_part(absence):
                presence = assertions.presence_of_part(graph, nodes, absence)
                key = json.dumps([absence.get(k) for k in ("po_id", "bearer_container", "bearer_whole")], sort_keys=True)
                if key not in reflexive:  # X SubClassOf part of some X, for this X
                    reflexive.add(key)
                    po = assertions._curie_iri(absence.get("po_id"))
                    part = assertions._intersection(graph, nodes, assertions._bearer_classes(graph, nodes, absence, po))
                    whole = assertions._intersection(graph, nodes, assertions._bearer_classes(graph, nodes, absence, po))
                    if not isinstance(part, URIRef):
                        graph.add((part, RDF.type, OWL.Class))
                    graph.add((part, RDFS.subClassOf, assertions._some(graph, nodes, assertions.PART_OF, whole)))
            else:
                presence = assertions.defining_property(
                    graph, nodes, {**absence, "negated": False, "negation_scope": ""}, attributes)[0]
        except (KeyError, ValueError):
            continue
        present, marker = URIRef(CHECK + "present/" + iri.rsplit("/", 1)[-1]), URIRef(_marker(iri))
        for name in (present, marker):
            graph.add((name, RDF.type, OWL.Class))
        graph.add((present, OWL.equivalentClass, presence))
        graph.add((marker, OWL.disjointWith, present))
        graph.add((_bearer_of(graph, iri), RDFS.subClassOf, marker))  # the bearer axiom of an absence
        usable.add(iri)
    taxon_classes: dict[str, str] = {}
    for index, (name, taxon) in enumerate(checked.items()):
        absent = [i for i in sorted(taxon["absent"]) if i in usable]
        if not absent:
            continue
        iri = URIRef(f"{CHECK}taxon/{index}")
        graph.add((iri, RDF.type, OWL.Class))
        for member in [*sorted(taxon["present"]), *absent]:  # as published: T has the phene
            graph.add((URIRef(member), RDF.type, OWL.Class))
            graph.add((iri, RDFS.subClassOf, _bearer_of(graph, member)))
        taxon_classes[str(iri)] = name
    out.write_bytes(graph.serialize(format="nt", encoding="utf-8"))
    return taxon_classes


def write_pair_classes(taxa: dict, suspects: set[str], unsatisfiable: set[str], out: Path) -> dict[str, tuple[str, str]]:
    """One class per (positive class, absence) of the suspect taxa; ``{pair IRI: (positive,
    absence)}``. A positive class that is unsatisfiable by itself contradicts nothing else."""

    from rdflib import OWL, RDF, RDFS, Graph, URIRef

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
                graph.add((URIRef(iri), RDF.type, OWL.Class))  # a plant with both phenes
                for member in (present, absent):
                    graph.add((URIRef(iri), RDFS.subClassOf, _bearer_of(graph, member)))
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


def complete_taxon_check(
    annotated: Path, work: Path, threads: int = 4, timeout: int = 120, heap: str = "12g",
    every_taxon: bool = True,
) -> tuple[dict[str, dict] | None, str]:
    """The taxon question put to HermiT, a reasoner for all of OWL 2 DL, on the definitions as
    published (no bearer axioms, no markers): ``({taxon: {status, conflict, axioms, ms}}, note)``.

    One taxon at a time, on the locality module of its classes (``tools/PheneTaxonConsistency
    .java``). ``status`` is consistent, inconsistent, timeout or error; ``conflict`` the classes of
    a smallest contradicting set. With ``every_taxon`` false only taxa with an absence and a
    positive statement are asked, the taxa the ELK check asks."""

    import shutil

    from tools import classify_flopo_release as release

    root = Path(release.__file__).resolve().parents[1]
    program, jar = root / "tools" / "PheneTaxonConsistency.java", root / "tools" / "robot.jar"
    if shutil.which("java") is None or not jar.is_file():
        return None, "skipped: Java or tools/robot.jar is missing"
    taxa: dict[str, dict] = {}
    write_class_definitions(annotated, work / "published.ttl", taxa=taxa, absences={}, bearers=False)
    names = sorted(name for name, taxon in taxa.items()
                   if every_taxon or (taxon["absent"] and taxon["present"]))
    with (work / "taxa.tsv").open("w", encoding="utf-8") as handle:
        for index, name in enumerate(names):
            classes = sorted(set(taxa[name]["present"]) | set(taxa[name]["absent"]))
            handle.write(f"{index}\t{' '.join(classes)}\n")
    done = subprocess.run(
        ["java", f"-Xmx{heap}", "-cp", str(jar), str(program), str(classification_closure()),
         str(work / "published.ttl"), str(work / "taxa.tsv"), str(work / "consistency.tsv"),
         str(threads), str(timeout)],
        capture_output=True, text=True, check=False,
    )
    result_path = work / "consistency.tsv"
    if done.returncode or not result_path.exists():
        return None, "failed: " + " ".join((done.stderr or done.stdout).split())[-300:]
    result: dict[str, dict] = {}
    for line in result_path.read_text(encoding="utf-8").splitlines():
        index, status, detail, axioms, ms = line.split("\t")
        result[names[int(index)]] = {
            "status": status, "conflict": detail.split() if status == "inconsistent" else [],
            "detail": detail if status == "error" else "", "axioms": int(axioms), "ms": int(ms),
        }
    return result, ""


def complete_report(source: str, annotated: Path | None = None, derived: Path | None = None,
                    every_taxon: bool = True) -> dict:
    """Run the complete check of one flora and write ``<source>-taxon-consistency.tsv`` (the
    taxa that are not consistent). Nothing is marked: the ELK check does that."""

    derived = derived or Path("local-corpora") / source / "derived"
    annotated = annotated or derived / f"{source}-annotated.jsonl"
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE, prefix=f"complete-{source}-") as tmp:
        found, note = complete_taxon_check(annotated, Path(tmp), every_taxon=every_taxon)
    summary = {"source": source, "taxa": 0, "inconsistent": None, "timeout": 0, "error": 0, "note": note}
    if found is None:
        return summary
    report = derived / f"{source}-taxon-consistency.tsv"
    with report.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["taxon", "status", "conflicting_classes", "module_axioms", "milliseconds"])
        for name, row in sorted(found.items()):
            if row["status"] != "consistent":
                writer.writerow([name, row["status"], " ".join(row["conflict"]) or row["detail"], row["axioms"], row["ms"]])
    times = sorted(row["ms"] for row in found.values())
    summary.update({
        "taxa": len(found), "inconsistent": sum(r["status"] == "inconsistent" for r in found.values()),
        "timeout": sum(r["status"] == "timeout" for r in found.values()),
        "error": sum(r["status"] == "error" for r in found.values()),
        "median_ms": times[len(times) // 2] if times else 0, "max_ms": times[-1] if times else 0,
        "report": str(report),
    })
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="+")
    parser.add_argument("--annotated", type=Path, help="another annotated file (one source only)")
    parser.add_argument("--derived", type=Path, help="where the report goes (one source only)")
    parser.add_argument("--complete", action="store_true",
                        help="ask HermiT, one taxon at a time, on the published axioms; report only")
    parser.add_argument("--with-absence-only", action="store_true",
                        help="with --complete: only the taxa the ELK check asks")
    args = parser.parse_args(argv)
    for source in args.sources:
        if args.complete:
            print(json.dumps(complete_report(source, args.annotated, args.derived,
                                             every_taxon=not args.with_absence_only)), flush=True)
        else:
            print(json.dumps(check(source, args.annotated, args.derived)), flush=True)


if __name__ == "__main__":
    main()
