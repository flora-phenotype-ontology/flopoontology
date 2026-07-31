#!/usr/bin/env python3
"""Embed the curated FLOPO value module in the main release OWL file.

The released ontology is RDF/XML and large enough that parsing and reserializing the
whole graph would create an unreviewable diff.  This command serializes only the
generated value axioms, places them in a marked block before the closing ``rdf:RDF``
tag, and updates the release date.  Re-running it replaces that block in place.
"""

from __future__ import annotations

import argparse
import re
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from rdflib import DCTERMS, OWL, RDF, RDFS, BNode, Graph, Literal, Namespace, URIRef
from rdflib.compare import to_canonical_graph

OBO = Namespace("http://purl.obolibrary.org/obo/")
OBO_IN_OWL = Namespace("http://www.geneontology.org/formats/oboInOwl#")
VALUE_ONTOLOGY = URIRef(OBO + "flopo-value-extensions.owl")
BEGIN_MARKER = "  <!-- BEGIN GENERATED FLOPO VALUE EXTENSION -->"
END_MARKER = "  <!-- END GENERATED FLOPO VALUE EXTENSION -->"
PREDICATE_PREFIXES = {
    str(RDF): "rdf",
    str(RDFS): "rdfs",
    str(OWL): "owl",
    str(DCTERMS): "dcterms",
    str(OBO): "obo",
    str(OBO_IN_OWL): "oboInOwl",
    "https://w3id.org/flopo/annotation/": "flopoann",
}


def _without_generated_block(text: str) -> str:
    begin_count = text.count(BEGIN_MARKER)
    end_count = text.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise ValueError("malformed generated value-extension markers in release OWL")
    if not begin_count:
        return text
    pattern = re.compile(
        rf"\n?{re.escape(BEGIN_MARKER)}.*?{re.escape(END_MARKER)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n", text, count=1)


def _graph_fragment(
    source: Graph, *, node_id_prefix: str = "FLOPOValue_"
) -> tuple[str, int]:
    """Serialize one small RDF graph as a deterministic RDF/XML body fragment."""

    local_classes = {
        cls
        for cls in source.subjects(RDF.type, OWL.Class)
        if isinstance(cls, URIRef) and str(cls).startswith(str(OBO) + "FLOPO_")
    }
    canonical = to_canonical_graph(source)

    def node_key(node) -> tuple[str, str]:
        return ("0" if isinstance(node, URIRef) else "1", str(node))

    def predicate_qname(predicate: URIRef) -> str:
        value = str(predicate)
        for namespace, prefix in PREDICATE_PREFIXES.items():
            if value.startswith(namespace):
                return f"{prefix}:{value.removeprefix(namespace)}"
        raise ValueError(f"predicate namespace is not declared by ontology/flopo.owl: {predicate}")

    def node_attribute(node) -> str:
        if isinstance(node, URIRef):
            return f"rdf:about={quoteattr(str(node))}"
        if isinstance(node, BNode):
            return f"rdf:nodeID={quoteattr(node_id_prefix + str(node))}"
        raise ValueError(f"unsupported RDF subject: {node!r}")

    def object_xml(predicate: URIRef, obj) -> str:
        qname = predicate_qname(predicate)
        if isinstance(obj, URIRef):
            return f"    <{qname} rdf:resource={quoteattr(str(obj))}/>"
        if isinstance(obj, BNode):
            return f"    <{qname} rdf:nodeID={quoteattr(node_id_prefix + str(obj))}/>"
        if isinstance(obj, Literal):
            attribute = ""
            if obj.language:
                attribute = f" xml:lang={quoteattr(obj.language)}"
            elif obj.datatype:
                attribute = f" rdf:datatype={quoteattr(str(obj.datatype))}"
            return f"    <{qname}{attribute}>{escape(str(obj))}</{qname}>"
        raise ValueError(f"unsupported RDF object: {obj!r}")

    lines: list[str] = []
    subjects = sorted(set(canonical.subjects()), key=node_key)
    for subject in subjects:
        lines.append(f"  <rdf:Description {node_attribute(subject)}>")
        statements = sorted(
            canonical.predicate_objects(subject),
            key=lambda pair: (str(pair[0]), *node_key(pair[1])),
        )
        lines.extend(object_xml(predicate, obj) for predicate, obj in statements)
        lines.append("  </rdf:Description>")
    return "\n".join(lines), len(local_classes)


def _extension_fragment(
    extension_path: Path, *, node_id_prefix: str = "FLOPOValue_"
) -> tuple[str, int]:
    source = Graph()
    source.parse(extension_path.as_posix())
    fragment_graph = Graph()
    for triple in source:
        if triple[0] != VALUE_ONTOLOGY:
            fragment_graph.add(triple)
    return _graph_fragment(fragment_graph, node_id_prefix=node_id_prefix)


def _update_release_metadata(text: str, release_date: str) -> str:
    version_iri_pattern = re.compile(
        r'(owl:versionIRI rdf:resource="http://purl\.obolibrary\.org/obo/'
        r'flopo/releases/)\d{4}-\d{2}-\d{2}(/flopo\.owl"/>)'
    )
    text, version_iri_count = version_iri_pattern.subn(
        rf"\g<1>{release_date}\g<2>", text, count=1
    )
    text, version_info_count = re.subn(
        r"<owl:versionInfo>[^<]+</owl:versionInfo>",
        f"<owl:versionInfo>{release_date}</owl:versionInfo>",
        text,
        count=1,
    )
    if version_iri_count != 1 or version_info_count != 1:
        raise ValueError("main FLOPO ontology must contain one versionIRI and versionInfo")

    modified = (
        '    <dcterms:modified rdf:datatype="http://www.w3.org/2001/XMLSchema#date">'
        f"{release_date}</dcterms:modified>"
    )
    if "<dcterms:modified" in text:
        text, modified_count = re.subn(
            r"    <dcterms:modified\b[^>]*>.*?</dcterms:modified>",
            modified,
            text,
            count=1,
        )
        if modified_count != 1:
            raise ValueError("could not update dcterms:modified")
    else:
        version_info = f"    <owl:versionInfo>{release_date}</owl:versionInfo>"
        text = text.replace(version_info, version_info + "\n" + modified, 1)
    return text


def update_release(release_path: Path, extension_path: Path, release_date: str) -> int:
    text = _without_generated_block(release_path.read_text(encoding="utf-8"))
    text = _update_release_metadata(text, release_date)
    fragment, class_count = _extension_fragment(extension_path)
    closing = "</rdf:RDF>"
    if text.count(closing) != 1:
        raise ValueError("main FLOPO RDF/XML must contain one closing rdf:RDF tag")
    block = f"{BEGIN_MARKER}\n{fragment}\n{END_MARKER}\n"
    text = text.replace(closing, block + closing, 1)
    release_path.write_text(text, encoding="utf-8")

    check = Graph()
    check.parse(release_path.as_posix())
    if (VALUE_ONTOLOGY, RDF.type, OWL.Ontology) in check:
        raise ValueError("extension ontology header leaked into the main FLOPO ontology")
    return class_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument(
        "--extension",
        type=Path,
        default=Path("ontology/flopo-value-extensions.ttl"),
    )
    parser.add_argument("--date", default=datetime.now(UTC).date().isoformat())
    args = parser.parse_args()
    count = update_release(args.release, args.extension, args.date)
    print(f"embedded {count} FLOPO value classes in {args.release}")
    print(f"release_date {args.date}")


if __name__ == "__main__":
    main()
