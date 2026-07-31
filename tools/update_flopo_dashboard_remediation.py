#!/usr/bin/env python3
"""Embed the reviewed OBO Dashboard semantic remediations in flopo.owl."""

from __future__ import annotations

import argparse
import re
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from rdflib import OWL, RDF, XSD, Graph, Literal, URIRef

from tools.update_flopo_botanical_release import _remove_named_owl_class
from tools.update_flopo_release import _extension_fragment, _update_release_metadata

OBO = "http://purl.obolibrary.org/obo/"
MODULE = URIRef(OBO + "flopo-dashboard-remediation.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO DASHBOARD REMEDIATION -->"
END_MARKER = "  <!-- END GENERATED FLOPO DASHBOARD REMEDIATION -->"
LEGACY_GO_IMPORT = OBO + "flopo/imports/go_import.owl"
GO_IMPORT = (
    "https://raw.githubusercontent.com/flora-phenotype-ontology/"
    "flopoontology/master/ontology/imports/go_import.owl"
)
EXPECTED_CLASSES = {
    OBO + class_id
    for class_id in (
        "FLOPO_0000467",
        "FLOPO_0001692",
        "FLOPO_0002893",
        "FLOPO_0900053",
        "FLOPO_0900054",
        "FLOPO_0900055",
        "FLOPO_0900056",
        "FLOPO_0980057",
        "FLOPO_0980059",
        "FLOPO_0980063",
    )
}
EXPECTED_REPLACEMENTS = {
    OBO + "FLOPO_0980057": OBO + "FLOPO_0002893",
    OBO + "FLOPO_0980059": OBO + "FLOPO_0001692",
    OBO + "FLOPO_0900053": OBO + "FLOPO_0000467",
}
IAO_DEFINITION = URIRef(OBO + "IAO_0000115")
TERM_REPLACED_BY = URIRef(OBO + "IAO_0100001")


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated Dashboard-remediation markers")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?", re.DOTALL
    )
    return pattern.sub("\n", text, count=1)


def _module_fragment(module_path: Path) -> tuple[str, set[str]]:
    graph = Graph().parse(module_path.as_posix())
    ontology_subjects = set(graph.subjects(RDF.type, OWL.Ontology))
    if ontology_subjects != {MODULE}:
        raise ValueError("remediation module must have exactly its expected ontology header")
    classes = {
        str(cls)
        for cls in graph.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(OBO + "FLOPO_")
    }
    if classes != EXPECTED_CLASSES:
        raise ValueError("remediation module does not contain the expected ten classes")
    for old, replacement in EXPECTED_REPLACEMENTS.items():
        old_iri = URIRef(old)
        if (old_iri, OWL.deprecated, Literal(True, datatype=XSD.boolean)) not in graph:
            raise ValueError(f"replacement source is not deprecated: {old}")
        if (old_iri, TERM_REPLACED_BY, URIRef(replacement)) not in graph:
            raise ValueError(f"replacement link is missing: {old}")
        if (old_iri, OWL.equivalentClass, None) in graph:
            raise ValueError(f"obsolete class retained logical definition: {old}")

    fragment, _class_count = _extension_fragment(
        module_path, node_id_prefix="FLOPODashboard_"
    )
    header_pattern = re.compile(
        rf"  <rdf:Description rdf:about={re.escape(chr(34) + str(MODULE) + chr(34))}>"
        rf".*?  </rdf:Description>\n?",
        re.DOTALL,
    )
    fragment = header_pattern.sub("", fragment)
    if str(MODULE) in fragment:
        raise ValueError("remediation ontology header leaked into release fragment")
    return fragment.strip(), classes


def _replace_broken_go_import(text: str) -> str:
    text = text.replace(
        f'<owl:imports rdf:resource="{LEGACY_GO_IMPORT}"/>',
        f'<owl:imports rdf:resource="{GO_IMPORT}"/>',
    )
    if GO_IMPORT not in text:
        ontology_start = re.search(r"  <owl:Ontology\b[^>]*>\n", text)
        if ontology_start is None:
            raise ValueError("could not locate main owl:Ontology element")
        import_line = f'    <owl:imports rdf:resource="{GO_IMPORT}"/>\n'
        text = text[: ontology_start.end()] + import_line + text[ontology_start.end() :]
    if LEGACY_GO_IMPORT in text or text.count(GO_IMPORT) != 1:
        raise ValueError("GO import replacement was not unique")
    return text


RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
OWL_NS = "http://www.w3.org/2002/07/owl#"
RDF_ABOUT = f"{{{RDF_NS}}}about"
RDF_RESOURCE = f"{{{RDF_NS}}}resource"
RDF_DESCRIPTION = f"{{{RDF_NS}}}Description"
RDF_TYPE = f"{{{RDF_NS}}}type"
OWL_CLASS = f"{{{OWL_NS}}}Class"
OWL_DEPRECATED = f"{{{OWL_NS}}}deprecated"
OWL_EQUIVALENT_CLASS = f"{{{OWL_NS}}}equivalentClass"
IAO_DEFINITION_TAG = f"{{{OBO}}}IAO_0000115"
TERM_REPLACED_BY_TAG = f"{{{OBO}}}IAO_0100001"


def _validate_release(release_path: Path) -> None:
    """Stream the large RDF/XML release and enforce the remediation invariants."""

    definitions: dict[str, str] = {}
    records: dict[str, dict[str, object]] = {}
    for _event, element in ET.iterparse(release_path, events=("end",)):
        if element.tag not in {OWL_CLASS, RDF_DESCRIPTION}:
            continue
        class_iri = element.get(RDF_ABOUT)
        if element.tag == RDF_DESCRIPTION and not any(
            child.tag == RDF_TYPE and child.get(RDF_RESOURCE) == OWL_NS + "Class"
            for child in element
        ):
            element.clear()
            continue
        if not class_iri or not class_iri.startswith(OBO + "FLOPO_"):
            element.clear()
            continue

        deprecated = any(
            child.tag == OWL_DEPRECATED
            and (child.text or "").strip().casefold() == "true"
            for child in element
        )
        replacement = next(
            (
                child.get(RDF_RESOURCE)
                for child in element
                if child.tag == TERM_REPLACED_BY_TAG
            ),
            None,
        )
        has_equivalent_class = any(
            child.tag == OWL_EQUIVALENT_CLASS for child in element
        )
        definition = next(
            (
                "".join(child.itertext())
                for child in element
                if child.tag == IAO_DEFINITION_TAG
            ),
            None,
        )
        records[class_iri] = {
            "deprecated": deprecated,
            "replacement": replacement,
            "has_equivalent_class": has_equivalent_class,
        }
        if definition and not deprecated:
            normalized = " ".join(definition.split()).casefold()
            if normalized in definitions:
                raise ValueError(
                    "duplicate live FLOPO definition on "
                    f"{definitions[normalized]} and {class_iri}"
                )
            definitions[normalized] = class_iri
        element.clear()

    for old, replacement in EXPECTED_REPLACEMENTS.items():
        record = records.get(old)
        if record is None:
            raise ValueError(f"old class disappeared from the release: {old}")
        if not record["deprecated"]:
            raise ValueError(f"old class was not deprecated: {old}")
        if record["replacement"] != replacement:
            raise ValueError(f"old class lacks its replacement: {old}")
        if record["has_equivalent_class"]:
            raise ValueError(f"old class retained logic: {old}")


def update_release(release_path: Path, module_path: Path, release_date: str) -> int:
    original = release_path.read_text(encoding="utf-8")
    had_generated_block = BEGIN_MARKER in original
    text = _without_generated_block(original)
    fragment, classes = _module_fragment(module_path)
    for class_iri in sorted(classes):
        text, removed = _remove_named_owl_class(text, class_iri)
        if not removed and not had_generated_block:
            raise ValueError(f"class to remediate is absent from the release: {class_iri}")
    text = _replace_broken_go_import(text)
    text = _update_release_metadata(text, release_date)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    release_path.write_text(text.replace(closing, block + closing, 1), encoding="utf-8")

    if str(MODULE) in release_path.read_text(encoding="utf-8"):
        raise ValueError("remediation ontology header leaked into flopo.owl")
    _validate_release(release_path)
    return len(classes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--module",
        type=Path,
        default=Path("ontology/flopo-dashboard-remediation.ttl"),
    )
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.module, args.date)
    print(f"remediated {count} FLOPO classes")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
