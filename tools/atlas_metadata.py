"""Machine-readable description of an atlas data release (FAIR metadata).

    python -m tools.atlas_metadata RELEASE_DIR

Reads ``release.json`` and ``downloads/downloads.json`` of the release and the list of data
versions (``deploy/atlas/data-releases.tsv``) and writes, into ``downloads/`` (and the first two
also into ``web/``, where they are served at the root of the site):

``void.ttl``
    The dataset in VoID and DCAT 3: title, licence, creator, version and previous version, the
    SPARQL endpoint, the IRI space, vocabularies, one subset per named graph with its size and
    dump file, one distribution per download file with size and checksum, and the sources.
``dataset.jsonld``
    The same in schema.org terms (``Dataset``), for dataset search engines; ``index.html`` of the
    release embeds it.
``tsv/csv-metadata.json``
    The columns of every TSV table as CSV on the Web (CSVW) metadata, from the column lists of
    ``tools.atlas_downloads``.
``CITATION.cff``, ``LICENSE.txt``
    How to cite the release, and the licence of the data.

Versions. A data version is one build of the RDF: its name is the date and time of the build
(``20261119-1826``), its IRI ``http://phenomebrowser.net/flopo/release/<version>``. A release
that changes only the website keeps the data version of the release it is built on. The dataset
as such, whatever its version, is ``http://phenomebrowser.net/flopo/dataset``.

Licence. The annotations are CC BY 4.0. FLOPO is CC0. The sentences quoted from the floras are
not relicensed: rights in them stay with their sources.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path

BASE = "http://phenomebrowser.net/flopo/"
DATASET = BASE + "dataset"
LICENSE = "https://creativecommons.org/licenses/by/4.0/"
LICENSE_NAME = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
CREATOR = ("https://orcid.org/0000-0001-8149-5890", "Robert Hoehndorf", "Robert", "Hoehndorf")
PUBLISHER = "Bio-Ontology Research Group, King Abdullah University of Science and Technology (KAUST)"
REPOSITORY = "https://github.com/flora-phenotype-ontology/flopoontology"
TITLE = "FLOPO Trait Atlas"
DESCRIPTION = (
    "Plant traits from the descriptions in floras, as ontology annotations. Every statement of a "
    "flora about a plant (leaves glabrous; petals white or pink; fruit 3-5 cm) is an annotation "
    "with a plant part (Plant Ontology) and a quality (PATO or the Flora Phenotype Ontology, "
    "FLOPO), linked to the taxon (IPNI, World Checklist of Vascular Plants) and to the sentence "
    "it was read from. The annotations are made automatically and checked by rules and a reasoner."
)
RIGHTS = (
    "The annotations are licensed CC BY 4.0. The Flora Phenotype Ontology is CC0 1.0. The "
    "sentences quoted from the sources are included so that annotations can be checked; rights in "
    "them remain with the sources and are not covered by this licence."
)
KEYWORDS = ["plant traits", "phenotype", "flora", "morphology", "ontology", "FLOPO", "Plant Ontology",
            "PATO", "biodiversity", "linked data"]
# vocabularies the data uses (void:vocabulary)
VOCABULARIES = [
    "http://purl.obolibrary.org/obo/flopo.owl", "http://purl.obolibrary.org/obo/po.owl",
    "http://purl.obolibrary.org/obo/pato.owl", "http://purl.obolibrary.org/obo/uo.owl",
    "http://purl.obolibrary.org/obo/ro.owl", "http://purl.obolibrary.org/obo/eco.owl",
    "http://www.w3.org/ns/prov#", "http://semanticscience.org/resource/", "http://purl.org/dc/terms/",
    "http://www.w3.org/2004/02/skos/core#", "http://www.w3.org/2002/07/owl#",
    "http://www.opengis.net/ont/geosparql#", BASE + "browse#", BASE + "annotation/",
]
REFERENCES = ["https://doi.org/10.1186/s13326-016-0107-8", "https://doi.org/10.1093/bib/bbx035"]
FLOPO_AUTHORS = [('Hoehndorf', 'R'), ('Alshahrani', 'M'), ('Gkoutos', 'GV'), ('Gosline', 'G'), ('Groom', 'Q'), ('Hamann', 'T'), ('Kattge', 'J'), ('de Oliveira', 'SM'), ('Schmidt', 'M'), ('Sierra', 'S'), ('Smets', 'E'), ('Vos', 'RA'), ('Weiland', 'C')]
HISTORY = Path("deploy/atlas/data-releases.tsv")
MEDIA = {"nquads": "application/n-quads", "ntriples": "application/n-triples", "tsv": "text/tab-separated-values"}
XSD_TYPE = {"number": "decimal", "bool": "boolean"}


def data_version(stamp: str) -> str:
    """``20261119-1826-dedup`` -> ``20261119-1826``: the build time names the version."""

    match = re.match(r"\d{8}-\d{4}", stamp)
    if not match:
        raise SystemExit(f"not a release stamp: {stamp!r}")
    return match.group(0)


def version_date(version: str) -> str:
    return f"{version[:4]}-{version[4:6]}-{version[6:8]}"


def load_history(path: Path = HISTORY) -> list[dict]:
    """Data versions, oldest first: ``version``, ``date``, ``triples``, ``changes``."""

    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return [row for row in csv.DictReader(handle, delimiter="\t") if row.get("version")]


def history_with(version: str, triples: int, path: Path = HISTORY) -> list[dict]:
    """The history up to and including this version; a version not yet listed is added, without
    a note (write the note in the file, the next build shows it)."""

    rows = load_history(path)
    if not any(row["version"] == version for row in rows):
        rows.append({"version": version, "date": version_date(version), "triples": str(triples), "changes": ""})
    for row in rows:  # the note of a version may be written before its triples are counted
        if row["version"] == version and not row.get("triples"):
            row["triples"] = str(triples)
    rows.sort(key=lambda row: row["version"])
    return [row for row in rows if row["version"] <= version]


def release_iri(version: str) -> str:
    return f"{BASE}release/{version}"


def void(meta: dict, listing: dict, history: list[dict]) -> str:
    from rdflib import RDF, Graph, Literal, Namespace, URIRef
    from rdflib.namespace import DCTERMS, FOAF, PROV, XSD

    VOID = Namespace("http://rdfs.org/ns/void#")
    DCAT = Namespace("http://www.w3.org/ns/dcat#")
    SPDX = Namespace("http://spdx.org/rdf/terms#")
    PAV = Namespace("http://purl.org/pav/")
    g = Graph()
    for prefix, ns in (("void", VOID), ("dcat", DCAT), ("dcterms", DCTERMS), ("foaf", FOAF), ("prov", PROV),
                       ("spdx", SPDX), ("pav", PAV), ("xsd", XSD)):
        g.bind(prefix, ns)
    version = data_version(listing["release"])
    dataset, release = URIRef(DATASET), URIRef(release_iri(version))
    creator, publisher = URIRef(CREATOR[0]), URIRef(BASE + "dataset#publisher")
    g.add((creator, RDF.type, FOAF.Person))
    g.add((creator, FOAF.name, Literal(CREATOR[1])))
    g.add((publisher, RDF.type, FOAF.Organization))
    g.add((publisher, FOAF.name, Literal(PUBLISHER)))

    def describe(node) -> None:
        for kind in (VOID.Dataset, DCAT.Dataset):
            g.add((node, RDF.type, kind))
        g.add((node, DCTERMS.description, Literal(DESCRIPTION, lang="en")))
        g.add((node, DCTERMS.creator, creator))
        g.add((node, DCTERMS.publisher, publisher))
        g.add((node, DCTERMS.license, URIRef(LICENSE)))
        g.add((node, DCTERMS.rights, Literal(RIGHTS, lang="en")))
        g.add((node, DCAT.landingPage, URIRef(BASE)))
        g.add((node, FOAF.homepage, URIRef(BASE)))
        for word in KEYWORDS:
            g.add((node, DCAT.keyword, Literal(word, lang="en")))
        for reference in REFERENCES:
            g.add((node, DCTERMS.references, URIRef(reference)))

    describe(dataset)
    g.add((dataset, DCTERMS.title, Literal(TITLE, lang="en")))
    g.add((dataset, DCAT.hasCurrentVersion, release))
    g.add((dataset, DCTERMS.issued, Literal(history[0]["date"], datatype=XSD.date)))
    g.add((dataset, DCTERMS.modified, Literal(version_date(version), datatype=XSD.date)))
    g.add((dataset, DCAT.contactPoint, URIRef(REPOSITORY + "/issues")))
    g.add((dataset, DCTERMS.source, URIRef(REPOSITORY)))
    for row in history:
        g.add((dataset, DCAT.hasVersion, URIRef(release_iri(row["version"]))))
    previous = None
    for row in history:
        node = URIRef(release_iri(row["version"]))
        g.add((node, RDF.type, DCAT.Dataset))
        g.add((node, DCAT.isVersionOf, dataset))
        g.add((node, DCAT.version, Literal(row["version"])))
        g.add((node, PAV.version, Literal(row["version"])))
        g.add((node, DCTERMS.issued, Literal(row["date"], datatype=XSD.date)))
        if row.get("changes"):
            g.add((node, DCAT.versionNotes, Literal(row["changes"], lang="en")))
        if previous is not None:
            g.add((node, DCAT.previousVersion, previous))
            g.add((node, PROV.wasRevisionOf, previous))
        previous = node

    describe(release)
    g.add((release, DCTERMS.title, Literal(f"{TITLE}, version {version}", lang="en")))
    g.add((release, DCTERMS.identifier, Literal(release_iri(version))))
    g.add((release, DCTERMS.bibliographicCitation, Literal(citation_text(version))))
    g.add((release, VOID.sparqlEndpoint, URIRef(BASE + "sparql")))
    g.add((release, VOID.uriSpace, Literal(BASE)))
    g.add((release, VOID.triples, Literal(int(meta["triples"]))))
    g.add((release, VOID.uriLookupEndpoint, URIRef(BASE + "sparql?query=DESCRIBE+")))
    for vocabulary in VOCABULARIES:
        g.add((release, VOID.vocabulary, URIRef(vocabulary)))
    if meta.get("commit"):
        g.add((release, PROV.wasGeneratedBy, URIRef(f"{REPOSITORY}/commit/{meta.get('base_commit') or meta['commit']}")))
    for key, source in sorted(listing["sources"].items()):
        node = URIRef(f"{BASE}saudi-flora/source/{key}")
        g.add((release, DCTERMS.source, node))
        g.add((release, PROV.wasDerivedFrom, node))
        g.add((node, DCTERMS.title, Literal(source["title"])))
    rows = {f["table"]: f["rows"] for f in listing["files"] if f["format"] == "tsv" and not f.get("source")}
    for table, cls in (("traits", "TraitRecord"), ("taxa", "Taxon"), ("occurrences", "Occurrence")):
        count = rows.get(table) or sum(f["rows"] for f in listing["files"] if f.get("table") == table and f.get("source"))
        if count:
            part = URIRef(f"{release}#{cls}")
            g.add((release, VOID.classPartition, part))
            g.add((part, VOID["class"], URIRef(f"{BASE}browse#{cls}")))
            g.add((part, VOID.entities, Literal(int(count))))
    for f in listing["files"]:
        url = URIRef(f"{BASE}downloads/{f['path']}")
        g.add((release, DCAT.distribution, url))
        g.add((url, RDF.type, DCAT.Distribution))
        g.add((url, DCAT.downloadURL, url))
        g.add((url, DCAT.mediaType, URIRef("https://www.iana.org/assignments/media-types/" + MEDIA[f["format"]])))
        g.add((url, DCAT.compressFormat, URIRef("https://www.iana.org/assignments/media-types/application/gzip")))
        g.add((url, DCAT.byteSize, Literal(int(f["bytes"]), datatype=XSD.nonNegativeInteger)))
        g.add((url, DCTERMS.license, URIRef(LICENSE)))
        checksum = URIRef(f"{url}#sha256")
        g.add((url, SPDX.checksum, checksum))
        g.add((checksum, RDF.type, SPDX.Checksum))
        g.add((checksum, SPDX.algorithm, SPDX.checksumAlgorithm_sha256))
        g.add((checksum, SPDX.checksumValue, Literal(f["sha256"])))
        if f["format"] == "tsv":
            table = listing["tables"][f["table"]]
            g.add((url, DCTERMS.title, Literal(table["title"] + (f" ({f['source']})" if f.get("source") else ""), lang="en")))
            g.add((url, DCTERMS.conformsTo, URIRef(f"{BASE}downloads/tsv/csv-metadata.json")))
            continue
        if f["format"] == "ntriples":  # several graphs in one file, without their names
            g.add((url, DCTERMS.title, Literal(f["title"], lang="en")))
            g.add((url, VOID.triples, Literal(int(f["triples"]))))
            continue
        graph = URIRef(f["graph"])  # the named graph is the subset; its dump is the file
        g.add((release, VOID.subset, graph))
        g.add((release, VOID.dataDump, url))
        g.add((graph, RDF.type, VOID.Dataset))
        g.add((graph, VOID.dataDump, url))
        g.add((graph, VOID.triples, Literal(int(f["triples"]))))
        note = (listing["graph_kinds"].get(f.get("kind")) if f.get("source") else listing["shared_graphs"].get(f.get("kind"))) or ""
        if note:
            g.add((graph, DCTERMS.description, Literal(note, lang="en")))
        if f.get("source") in listing["sources"]:
            g.add((graph, DCTERMS.source, URIRef(f"{BASE}saudi-flora/source/{f['source']}")))
        g.add((url, DCTERMS.title, Literal(f"Graph {f['graph']}", lang="en")))
    return g.serialize(format="turtle")


def citation_text(version: str) -> str:
    return (f"{CREATOR[1]} and the Bio-Ontology Research Group. {TITLE}, version {version} "
            f"({version_date(version)}). {release_iri(version)}")


def jsonld(meta: dict, listing: dict, history: list[dict]) -> dict:
    version = data_version(listing["release"])
    picks = [f for f in listing["files"] if f["path"] in ("tsv/traits-all.tsv.gz", "tsv/taxa.tsv.gz", "tsv/terms.tsv.gz")]
    return {
        "@context": "https://schema.org/",
        "@type": "Dataset",
        "@id": release_iri(version),
        "name": TITLE,
        "description": DESCRIPTION,
        "url": BASE,
        "identifier": release_iri(version),
        "version": version,
        "datePublished": version_date(version),
        "dateCreated": history[0]["date"],
        "license": LICENSE,
        "isAccessibleForFree": True,
        "keywords": KEYWORDS,
        "creator": {"@type": "Person", "@id": CREATOR[0], "name": CREATOR[1], "givenName": CREATOR[2],
                    "familyName": CREATOR[3]},
        "publisher": {"@type": "Organization", "name": PUBLISHER},
        "citation": REFERENCES,
        "isBasedOn": [source["title"] for _key, source in sorted(listing["sources"].items())],
        "usageInfo": RIGHTS,
        "subjectOf": {"@type": "DataDownload", "name": "VoID and DCAT description", "encodingFormat": "text/turtle",
                      "contentUrl": BASE + "void.ttl"},
        "distribution": [
            {"@type": "DataDownload", "name": "All files, with a guide to the columns", "encodingFormat": "text/html",
             "contentUrl": BASE + "#/downloads"},
            *({"@type": "DataDownload", "name": listing["tables"][f["table"]]["title"],
               "encodingFormat": "text/tab-separated-values", "contentUrl": f"{BASE}downloads/{f['path']}",
               "contentSize": str(f["bytes"]), "sha256": f["sha256"]} for f in picks),
            {"@type": "DataDownload", "name": "SPARQL endpoint", "encodingFormat": "application/sparql-results+json",
             "contentUrl": BASE + "sparql"},
        ],
    }


def csvw() -> dict:
    """The TSV tables as CSVW metadata; the column lists are those of ``tools.atlas_downloads``."""

    from tools.atlas_downloads import TABLES

    def columns(spec):
        for name, prop, kind, description in spec:
            base = {"dc:description": description}
            if prop:
                base["propertyUrl"] = prop
            if kind == "term":
                yield {"name": name + "_id", "titles": name + "_id", "datatype": "string", **base,
                       "dc:description": description + " Identifier (CURIE); several are joined with '|'."}
                yield {"name": name + "_label", "titles": name + "_label", "datatype": "string",
                       "dc:description": "Name of " + name + "_id."}
            else:
                datatype = XSD_TYPE.get(kind, "anyURI" if kind in ("subject", "iri") else "string")
                yield {"name": name, "titles": name, "datatype": datatype, **base}

    tables = []
    for key, (title, description, spec) in TABLES.items():
        url = f"{key}.tsv.gz" if key != "traits" else "traits-all.tsv.gz"
        tables.append({
            "url": url, "dc:title": title, "dc:description": description
            + (" The files traits-<source>.tsv.gz hold the same columns for one source each." if key == "traits" else ""),
            "tableSchema": {"columns": list(columns(spec)),
                            **({"primaryKey": spec[0][0]} if spec[0][2] == "subject" else {})},
        })
    return {
        "@context": ["http://www.w3.org/ns/csvw", {"@language": "en"}],
        "dc:title": TITLE + ": tables", "dc:license": {"@id": LICENSE},
        "dialect": {"delimiter": "\t", "header": True, "encoding": "utf-8", "quoteChar": None},
        "notes": "The files are gzip-compressed. Empty cells are missing values.",
        "tables": tables,
    }


def citation_cff(version: str) -> str:
    return "\n".join([
        "cff-version: 1.2.0",
        'message: "If you use this dataset, please cite it and the FLOPO paper."',
        "type: dataset",
        f'title: "{TITLE}"',
        f'version: "{version}"',
        f"date-released: {version_date(version)}",
        f'url: "{release_iri(version)}"',
        f'repository-code: "{REPOSITORY}"',
        "license: CC-BY-4.0",
        "authors:",
        f'  - family-names: "{CREATOR[3]}"',
        f'    given-names: "{CREATOR[2]}"',
        f'    orcid: "{CREATOR[0]}"',
        "references:",
        "  - type: article",
        '    title: "The flora phenotype ontology (FLOPO): tool for integrating morphological traits and phenotypes of vascular plants"',
        '    journal: "Journal of Biomedical Semantics"',
        "    year: 2016",
        "    volume: 7",
        "    start: 65",
        '    doi: "10.1186/s13326-016-0107-8"',
        "    authors:",
        *(line for family, given in FLOPO_AUTHORS for line in (f'      - family-names: "{family}"', f'        given-names: "{given}"')),
        "",
    ])


def license_text(version: str) -> str:
    return f"""{TITLE}, version {version}

Licence: {LICENSE_NAME}
{LICENSE}

You may copy, redistribute and adapt the data for any purpose, provided you give credit, link to
the licence and say whether you changed the data. Credit, for example:

  {citation_text(version)}

What the licence covers
  The annotations: the trait records, their ontology classes, the annotation classes and taxon
  axioms, the merged ranges, the taxon matching, and the tables made from them.

What it does not cover
  - The Flora Phenotype Ontology (graph "flopo") is released under CC0 1.0.
  - The Plant Ontology, PATO and the other ontologies keep their own licences.
  - The sentences quoted from the floras (column "text" and "context" of the tables, the source
    statements of the RDF) are included so that every annotation can be checked against its
    source. Rights in them remain with the floras they come from.
  - Taxon names and identifiers come from IPNI, the World Checklist of Vascular Plants and World
    Flora Online, under their terms.

The data are made automatically and contain errors; they come without warranty.
"""


def _write(path: Path, text: str) -> None:
    """Replace the file. Never write through it: a release that only changes the website shares
    the files of ``downloads/`` with its base release by hard links."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fresh = path.with_name(path.name + ".new")
    fresh.write_text(text, encoding="utf-8")
    os.replace(fresh, path)


def build(release: Path, history_path: Path = HISTORY) -> dict:
    meta = json.loads((release / "release.json").read_text())
    listing = json.loads((release / "downloads" / "downloads.json").read_text())
    version = data_version(listing["release"])
    history = history_with(version, meta["triples"], history_path)
    description = json.dumps(jsonld(meta, listing, history), ensure_ascii=False, indent=1)
    turtle = void(meta, listing, history)
    for folder in ("downloads", "web"):
        _write(release / folder / "void.ttl", turtle)
        _write(release / folder / "dataset.jsonld", description + "\n")
    _write(release / "downloads" / "tsv" / "csv-metadata.json", json.dumps(csvw(), ensure_ascii=False, indent=1) + "\n")
    _write(release / "downloads" / "CITATION.cff", citation_cff(version))
    _write(release / "downloads" / "LICENSE.txt", license_text(version))
    _write(release / "web" / "versions.json", json.dumps(
        {"version": version, "iri": release_iri(version), "license": LICENSE, "license_name": LICENSE_NAME,
         "citation": citation_text(version), "history": history[::-1]}, ensure_ascii=False, indent=1) + "\n")
    index = release / "web" / "index.html"
    if index.exists():  # for dataset search engines, which read the page and not the files beside it
        page = index.read_text(encoding="utf-8")
        block = f'<script type="application/ld+json" id="dataset-jsonld">{description.replace("</", "<\\/")}</script>'
        page = re.sub(r'<script type="application/ld\+json" id="dataset-jsonld">.*?</script>\n?', "", page, flags=re.S)
        _write(index, page.replace("</head>", block + "\n</head>", 1))
    return {"version": version, "versions": len(history), "triples": turtle.count(" .\n")}


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    print(json.dumps(build(Path(args[0]))))


if __name__ == "__main__":
    main()
