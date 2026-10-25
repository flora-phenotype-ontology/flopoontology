"""Annotate FLOPO EQ classes as traits (attributes) or phenotypes (values).

This is an annotation, never an asserted logical partition: a phenotype value is
still a subclass of its trait. Supporting vocabulary and broad phenotype groupings
are explicitly accounted for without falsely treating them as measured traits.
"""

from __future__ import annotations
import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from rdflib import OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from flopo2.ids.registry import _signature_of
from tools.update_flopo_release import _graph_fragment

OBO = "http://purl.obolibrary.org/obo/"
ANN = Namespace("http://phenomebrowser.net/flopo/annotation/")
OIO = Namespace("http://www.geneontology.org/formats/oboInOwl#")
PROPERTY = ANN.traitOrPhenotype
BASIS = ANN.traitPhenotypeBasis
HAS_QUALITY = URIRef(OBO + "RO_0000053")
MARKER = "FLOPO TRAIT PHENOTYPE ANNOTATIONS"


def pato_subsets(path):
    subsets = defaultdict(set)
    parents = defaultdict(set)
    current = ""
    for line in Path(path).open():
        line = line.strip()
        if line.startswith("["):
            current = ""
        elif line.startswith("id: PATO:"):
            current = OBO + line[4:].replace(":", "_")
        elif current and line.startswith("subset: "):
            subsets[current].add(line[8:])
        elif current and line.startswith("is_a: "):
            parents[current].add(OBO + line.split()[1].replace(":", "_"))
    return subsets, parents


def local_value_ids(root):
    result = set()
    for filename in [
        "config/flopo_flora_value_terms.tsv",
        "config/flopo_botanical_concept_id_registry.tsv",
        "config/flopo_botanical_id_registry.tsv",
        "config/flopo_growth_form_id_registry.tsv",
        "config/flopo_value_id_registry.tsv",
    ]:
        p = root / filename
        if not p.exists():
            continue
        for r in csv.DictReader(p.open(), delimiter="\t"):
            if (
                "flora_value_terms" in filename
                or "flopo_value_id_registry" in filename
                or r.get("kind") == "supporting_quality"
            ):
                result.add(OBO + r["flopo_id"].replace(":", "_"))
    # The colour backbone explicitly enumerates local values, but its top levels
    # inherit directly from the colour attribute and have no PATO value-tagged ancestor.
    for filename in [
        "config/flopo_colour_backbone_id_registry.tsv",
        "config/botanical_colour_id_registry.tsv",
    ]:
        path = root / filename
        if not path.exists():
            continue
        for row in csv.DictReader(path.open(), delimiter="\t"):
            term = row.get("ontology_id", "")
            if term.startswith("FLOPO:"):
                result.add(OBO + term.replace(":", "_"))
    return result


def quality_role(q, subsets, parents, local_values):
    if q in local_values:
        return "phenotype", "explicit_local_quality_value"
    tags = subsets.get(q, set())
    if "attribute_slim" in tags and "value_slim" in tags:
        return "", "conflicting_PATO_tags"
    if "value_slim" in tags:
        return "phenotype", "PATO:value_slim"
    if "attribute_slim" in tags:
        return "trait", "PATO:attribute_slim"
    # A more specific descendant of an attribute is not automatically an attribute.
    # Inheritance is used only to recognize descendants of tagged values.
    seen = {q}
    pending = [q]
    while pending:
        n = pending.pop()
        for parent in parents.get(n, ()):
            if parent in seen:
                continue
            seen.add(parent)
            pending.append(parent)
            if "value_slim" in subsets.get(parent, set()):
                return "phenotype", "descendant_of_PATO_value"
    return "", "quality_without_attribute_or_value_tag"


def expression_qualities(graph, cls):
    pending = list(graph.objects(cls, OWL.equivalentClass))
    seen = set()
    qualities = set()
    specific = False

    def inspect_filler(filler, visited):
        nonlocal specific
        if filler in visited:
            return
        visited.add(filler)
        # A complex filler is not automatically a value: a union of attributes
        # still specifies no phenotype value. Inspect its actual operands.
        heads = [*graph.objects(filler, OWL.unionOf), *graph.objects(filler, OWL.intersectionOf)]
        if heads:
            for head in heads:
                for member in graph.items(head):
                    inspect_filler(member, visited)
        elif any(graph.objects(filler, OWL.complementOf)):
            specific = True
        elif any(graph.objects(filler, OWL.onProperty)) or any(
            graph.objects(filler, OWL.withRestrictions)
        ):
            # Restricted measurements or relational value specifications.
            specific = True
        elif isinstance(filler, URIRef) and "#expr_" not in str(filler):
            qualities.add(str(filler))

    while pending:
        n = pending.pop()
        if n in seen:
            continue
        seen.add(n)
        if (n, OWL.onProperty, HAS_QUALITY) in graph:
            for q in graph.objects(n, OWL.someValuesFrom):
                inspect_filler(q, set())
        if any(graph.objects(n, OWL.complementOf)):
            specific = True
        for predicate in [
            OWL.someValuesFrom,
            OWL.intersectionOf,
            OWL.unionOf,
            OWL.complementOf,
            RDF.first,
            RDF.rest,
        ]:
            pending.extend(
                o
                for o in graph.objects(n, predicate)
                if isinstance(o, (BNode, URIRef)) and o != RDF.nil
            )
    return qualities, specific


def classification(graph, cls, subsets, parents, local_values):
    if any(str(v).lower() in {"true", "1"} for v in graph.objects(cls, OWL.deprecated)):
        return "", "obsolete"
    sig = _signature_of(graph, cls)
    if sig.startswith("PHENO|"):
        return "", "phenotype_grouping"
    if sig.startswith("EQ|"):
        q = OBO + sig.split("|")[2]
        return quality_role(q, subsets, parents, local_values)
    qualities, specific = expression_qualities(graph, cls)
    if specific:
        return "phenotype", "specified_value_expression"
    if qualities:
        roles = [quality_role(q, subsets, parents, local_values) for q in qualities]
        if all(r[0] == "trait" for r in roles):
            return "trait", "multiple_PATO_attributes"
        if all(r[0] == "phenotype" for r in roles):
            return "phenotype", "multiple_quality_values"
        return "", "mixed_or_unresolved_quality_roles"
    if str(cls) in local_values:
        return "", "supporting_quality_class"
    return "", "no_EQ_quality_definition"


def build_annotations(graph, subsets, parents, local_values):
    out = Graph()
    rows = []
    for prop, label, definition in [
        (
            PROPERTY,
            "trait or phenotype",
            "Classifies an EQ class as trait when its quality is a PATO attribute, or phenotype when its quality is a specified value. This annotation does not make traits and phenotypes logically disjoint.",
        ),
        (
            BASIS,
            "trait or phenotype classification basis",
            "The PATO subset or expression evidence for the annotation, or the reason no binary annotation was assigned.",
        ),
    ]:
        out.add((prop, RDF.type, OWL.AnnotationProperty))
        out.add((prop, RDFS.label, Literal(label)))
        out.add((prop, URIRef(OBO + "IAO_0000115"), Literal(definition, lang="en")))
    for cls in sorted(set(graph.subjects(RDF.type, OWL.Class)), key=str):
        if not isinstance(cls, URIRef) or not str(cls).startswith(OBO + "FLOPO_"):
            continue
        role, basis = classification(graph, cls, subsets, parents, local_values)
        if role:
            out.add((cls, PROPERTY, Literal(role)))
        out.add((cls, BASIS, Literal(basis)))
        rows.append(
            {
                "flopo_id": str(cls).removeprefix(OBO),
                "label": str(next(graph.objects(cls, RDFS.label), "")),
                "trait_or_phenotype": role,
                "basis": basis,
            }
        )
    return out, rows


def update(
    release, root=Path("."), report=Path("curation/flopo-trait-phenotype-classification.tsv")
):
    text = release.read_text()
    begin = f"  <!-- BEGIN GENERATED {MARKER} -->"
    end = f"  <!-- END GENERATED {MARKER} -->"
    if text.count(begin) != text.count(end) or text.count(begin) > 1:
        raise ValueError("Malformed classification annotation markers")
    text = re.sub(
        r"\n?" + re.escape(begin) + ".*?" + re.escape(end) + r"\n?", "\n", text, flags=re.S
    )
    graph = Graph().parse(data=text, format="xml")
    subsets, parents = pato_subsets(root / "ont/quality.obo")
    for s, o in graph.subject_objects(OIO.inSubset):
        subsets[str(s)].add(str(o).rsplit("#", 1)[-1])
    for s, o in graph.subject_objects(RDFS.subClassOf):
        if isinstance(o, URIRef):
            parents[str(s)].add(str(o))
    module, rows = build_annotations(graph, subsets, parents, local_value_ids(root))
    fragment, _ = _graph_fragment(module, canonicalize=False)
    release.write_text(
        text.replace("</rdf:RDF>", begin + "\n" + fragment + "\n" + end + "\n</rdf:RDF>")
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w") as f:
        w = csv.DictWriter(f, list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return dict(Counter(r["trait_or_phenotype"] or "unclassified_or_not_applicable" for r in rows))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    args = p.parse_args()
    print(json.dumps(update(args.release), sort_keys=True))


if __name__ == "__main__":
    main()
