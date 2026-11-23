"""Write the bulk downloads of an atlas release: every graph as gzipped N-Quads, and flat tables.

    python -m tools.atlas_downloads RELEASE_DIR [--jobs 8]

Writes ``RELEASE_DIR/downloads/``:

- ``rdf/<graph file>.nq.gz``: the release's N-Quads files, one per named graph, compressed;
- ``rdf/plain-records.nt.gz``: the flat records, places, taxa and term names as N-Triples
  (no named graphs, no blank nodes, no OWL), for stores that take triples only;
- ``tsv/traits-<source>.tsv.gz``: one row per trait record of a source (``fb:TraitRecord`` of its
  index graph), and ``tsv/traits-all.tsv.gz`` with every source;
- ``tsv/occurrences.tsv.gz``, ``tsv/growth-traits.tsv.gz``, ``tsv/taxa.tsv.gz``,
  ``tsv/taxon-names.tsv.gz``, ``tsv/terms.tsv.gz``;
- ``README.txt``: what the files are and what every column means;
- ``SHA256SUMS.txt`` and ``downloads.json`` (the list the Downloads page of the website shows).

The tables are read from the release's own N-Quads, so they say what the endpoint says. The column
lists below are the single description of the tables: the files, README.txt and the web page are
all written from them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pyoxigraph as ox

BASE = "http://phenomebrowser.net/flopo/"
FB = BASE + "browse#"
OBO = "http://purl.obolibrary.org/obo/"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT = "http://purl.org/dc/terms/"
SKOS_NOTATION = "http://www.w3.org/2004/02/skos/core#notation"

# (column, property, kind, description). Kinds: "term" writes a CURIE column <name>_id and its
# label column <name>_label; "local" the last part of an IRI; "iri", "text", "number", "bool"
# the value as it is. Several values of one record are joined with "|".
TRAIT_COLUMNS = [
    ("record", None, "subject", "IRI of the trait record. It resolves, and it is the subject of the record's triples in the RDF files."),
    ("source", FB + "source", "local", "Key of the flora or database the statement comes from (see the list of sources)."),
    ("taxon", FB + "taxon", "iri", "IRI of the taxon. 'taxon/ipni-<id>' is keyed by the IPNI identifier of the accepted name in Kew's World Checklist of Vascular Plants; groups outside that checklist (mosses, algae, lichens) keep a World Flora Online key, 'taxon/wfo-<id>'."),
    ("taxon_name", None, "taxon_name", "Accepted scientific name of the taxon, without author."),
    ("family", None, "taxon_family", "Family of the taxon."),
    ("ipni_id", None, "taxon_ipni", "IPNI identifier of the accepted name (https://www.ipni.org/n/<id>), when there is one."),
    ("status", FB + "status", "text", "Result of the automatic checks: 'accepted' (passed), 'review' (kept, flagged for a curator) or 'blocked' (failed a check; kept for the record, not to be used as a trait)."),
    ("annotation", RDFS_LABEL, "text", "The annotation in words, for example 'leaf glabrous' or 'petal length 3-5 mm'."),
    ("negated", FB + "negated", "bool", "true when the source says the plant does not have this: 'stipules absent', 'not fragrant'."),
    ("entity", FB + "bearer", "term", "The plant part (or whole plant) that has the trait: a Plant Ontology class, or a FLOPO class for parts the Plant Ontology lacks."),
    ("quality", FB + "quality", "term", "The trait value: a PATO quality, or a FLOPO value class where PATO has none. Several values (joined with '|', in no particular order) are alternatives or the two ends of a range of forms; see value_operator and relation."),
    ("value_operator", FB + "valueOperator", "text", "'one_of' when the values in quality are alternatives ('white or pink'). In OWL this is a union."),
    ("attribute", FB + "attribute", "term", "The kind of trait the value belongs to (PATO attribute such as colour, shape, length), when the record states a value of it."),
    ("relation", FB + "relation", "text", "How two values are related when the source joins them: 'continuum' ('ovate to oblong'), 'temporal_transition' ('white turning pink'), 'taxon_level_alternatives'."),
    ("from_value", FB + "fromValue", "term", "First value of the relation."),
    ("to_value", FB + "toValue", "term", "Second value of the relation."),
    ("from_degree", FB + "fromDegree", "text", "Degree word on the first value ('broadly', 'narrowly', 'slightly')."),
    ("to_degree", FB + "toDegree", "text", "Degree word on the second value."),
    ("low", FB + "low", "number", "Lower end of the usual numeric range, in the unit given. Feet, inches, yards and decimetres of the sources are converted to SI units."),
    ("high", FB + "high", "number", "Upper end of the usual numeric range. A single number has low = high; 'to 8 m' has only high."),
    ("low_exclusive", FB + "lowExclusive", "bool", "true when the lower bound itself is excluded ('more than 2 mm')."),
    ("high_exclusive", FB + "highExclusive", "bool", "true when the upper bound itself is excluded ('less than 1 mm')."),
    ("min_extreme", FB + "minExtreme", "number", "Rare minimum given in brackets: 2 in '(2-)3-8(-11) cm'."),
    ("max_extreme", FB + "maxExtreme", "number", "Rare maximum given in brackets: 11 in '(2-)3-8(-11) cm'."),
    ("unit", FB + "unit", "term", "Unit of the numbers, as a Units Ontology (UO) class. Counts use UO:0000189 'count unit'."),
    ("unit_symbol", FB + "unitSymbol", "text", "The unit as written: mm, cm, m."),
    ("source_unit", FB + "sourceUnit", "text", "The unit of the source, when it was converted (for example ft)."),
    ("unit_factor", FB + "unitFactor", "number", "Factor by which the source's numbers were multiplied in that conversion."),
    ("qualifier", FB + "qualifier", "text", "How exact the value is: 'approximately' for 'about', 'c.', '±', 'sub-'."),
    ("frequency", FB + "frequency", "text", "How often the source says the trait holds: usually, often, sometimes, occasionally, rarely."),
    ("alternative_frequencies", FB + "alternative", "alternatives", "For alternatives with their own frequency ('dioecious or rarely monoecious'): value=frequency pairs, for example 'PATO:0001340=rarely'."),
    ("stage", FB + "stage", "term", "Developmental stage at which the trait holds ('in fruit', 'at anthesis'): a Plant Ontology stage."),
    ("bearer_state", FB + "bearerState", "term", "Quality that restricts which parts are meant: 'young' in 'young stems', 'basal' in 'basal leaves'."),
    ("positioned_part", FB + "positionedPart", "term", "The class that FLOPO or the Plant Ontology has for the part in its position: 'basal leaf' for a leaf with the state 'basal'."),
    ("stated_bearer", FB + "statedBearer", "term", "The organ the source names, when the trait is located in a region of it ('leaf' in 'leaves hairy beneath')."),
    ("scope", FB + "scope", "term", "That region of the stated organ (for example the abaxial surface)."),
    ("container", FB + "container", "term", "For counts per part: the part that contains the counted part ('fruit' in 'seeds 2 per fruit')."),
    ("collection_size", FB + "collectionSize", "number", "Size of the group the parts come in: 2 for 'leaves in pairs'."),
    ("whole", FB + "whole", "term", "The whole the part belongs to, when the source restricts it ('male flower' in 'calyx of male flowers')."),
    ("whole_quality", FB + "wholeQuality", "term", "Quality of that whole ('male')."),
    ("carrier", FB + "carrier", "term", "The structure that has the quality with respect to the stated part: the shoot axis in 'leaves alternate', the calyx in 'sepals connate'. Derived from the part and the value, not read from the source."),
    ("carrier_kind", FB + "carrierKind", "text", "'arrangement' (the parts on the axis that bears them) or 'set' (the like members of a whorl among themselves)."),
    ("part_quality", FB + "partQuality", "term", "Quality of a part that the entity is said to have ('leaves with white hairs': white)."),
    ("towards", FB + "towards", "term", "The other part in a comparison or relation ('corolla tube' in 'shorter than the corolla tube')."),
    ("comparison", FB + "comparison", "text", "Words of the comparison, as in the source."),
    ("ratio_low", FB + "ratioLow", "number", "Lower end of a ratio: 2 in '2-3 times as long as the calyx'."),
    ("ratio_high", FB + "ratioHigh", "number", "Upper end of that ratio."),
    ("ratio_numerator", FB + "ratioNumerator", "term", "For a ratio of two dimensions of one part ('2-3 times as long as wide'): the first dimension (length)."),
    ("ratio_denominator", FB + "ratioDenominator", "term", "The second dimension of that ratio (width)."),
    ("count_word", FB + "countWord", "text", "A count given as a word ('many', 'few') where the source gives no number."),
    ("count_position", FB + "countPosition", "text", "Where a count applies ('each_side' for 'veins 4-6 on each side of the midrib')."),
    ("count_landmark", FB + "countLandmark", "term", "The part that position refers to (the midrib)."),
    ("specimen_condition", FB + "specimenCondition", "text", "Condition of the specimen for which the trait is stated: 'dried' ('black when dry'), 'moistened', 'fresh'."),
    ("union_scope", FB + "unionScope", "text", "'across_attributes' when the alternatives are not values of one attribute ('simple or branched')."),
    ("flopo_class", FB + "flopoClass", "term", "The named FLOPO phenotype class for this part and quality, when FLOPO has one."),
    ("annotation_class", FB + "phenotypeClass", "iri", "IRI of the OWL class that states the firm content of the record (part, quality, numbers, alternatives, negation). Its definition is in the annotation-classes RDF file and at the IRI itself."),
    ("organ_group", FB + "organGroup", "local", "Group of plant parts the website files the record under (organ-leaf, organ-flower, ...)."),
    ("trait_group", FB + "traitGroup", "local", "Group of traits the website files the record under (trait-colour, trait-shape, ...)."),
    ("evidence", FB + "evidence", "term", "The kind of evidence for the record, as a class of the Evidence and Conclusion Ontology. ECO:0007319: a statement by the author of the flora, used in an automatic assertion (not reviewed by a person). The statement itself is in source_text."),
    ("source_text", FB + "text", "text", "The words of the source that the annotation was made from."),
    ("context", FB + "context", "text", "The sentence of the source around those words."),
]

OCCURRENCE_COLUMNS = [
    ("occurrence", None, "subject", "IRI of the place record."),
    ("source", FB + "source", "local", "Key of the flora the record comes from."),
    ("taxon", FB + "taxon", "iri", "IRI of the taxon."),
    ("taxon_name", None, "taxon_name", "Accepted scientific name of the taxon."),
    ("family", None, "taxon_family", "Family of the taxon."),
    ("ipni_id", None, "taxon_ipni", "IPNI identifier of the accepted name."),
    ("locality", FB + "locality", "text", "Name of the place, standardized where it could be."),
    ("verbatim_locality", FB + "verbatimLocality", "text", "The place as the source writes it, when different (for example 'Que.')."),
    ("feature_type", FB + "featureType", "text", "Kind of place: country, state, province, mountain, island, ..."),
    ("region", FB + "region", "local", "ISO 3166-2 code of the Saudi region, for the Saudi sources."),
    ("basis", FB + "basis", "text", "'stated' when the source names the place, 'inferred' when it follows from what the source says."),
    ("latitude", FB + "lat", "number", "Latitude of the place from a gazetteer (decimal degrees, WGS 84), where one was matched. It locates the named place, not a specimen."),
    ("longitude", FB + "lon", "number", "Longitude of the place."),
]

GROWTH_COLUMNS = [
    ("record", None, "subject", "IRI of the record."),
    ("source", FB + "source", "local", "Key of the flora the record comes from."),
    ("taxon", FB + "taxon", "iri", "IRI of the taxon."),
    ("taxon_name", None, "taxon_name", "Accepted scientific name of the taxon."),
    ("family", None, "taxon_family", "Family of the taxon."),
    ("ipni_id", None, "taxon_ipni", "IPNI identifier of the accepted name."),
    ("trait", FB + "trait", "text", "The trait as the source tabulates it: flowering, and for the Saudi guides growth and cultivation traits."),
    ("value", FB + "value", "text", "The value as text."),
    ("month", FB + "month", "number", "Month or months (1-12), for flowering and other seasonal traits."),
    ("low", FB + "low", "number", "Lower end of a numeric value."),
    ("high", FB + "high", "number", "Upper end of a numeric value."),
    ("unit", FB + "unit", "text", "Unit of the numbers."),
    ("label", RDFS_LABEL, "text", "The record in words."),
]

TAXON_COLUMNS = [
    ("taxon", None, "subject", "IRI of the taxon."),
    ("name", RDFS_LABEL, "text", "Accepted scientific name, without author."),
    ("authorship", FB + "authorship", "text", "Author of the name."),
    ("family", FB + "family", "text", "Family."),
    ("order", FB + "order", "text", "Order."),
    ("ipni_id", FB + "ipni", "text", "IPNI identifier of the accepted name."),
    ("wfo_id", FB + "wfo", "text", "World Flora Online identifier, where one was recorded."),
    ("replaces", DCT + "replaces", "iri", "Earlier IRIs of the taxon (keyed by World Flora Online) that this one replaces."),
    ("elevation_min_m", FB + "elevationMin", "number", "Lowest elevation the sources give, in metres."),
    ("elevation_max_m", FB + "elevationMax", "number", "Highest elevation the sources give, in metres."),
    ("trait_records", None, "count", "Number of trait records of the taxon, over all sources."),
]

NAME_COLUMNS = [
    ("taxon", None, "taxon_of_name", "IRI of the taxon the name was matched to."),
    ("source", FB + "source", "local", "Key of the flora that prints the name."),
    ("printed_name", FB + "name", "text", "The name as the flora prints it."),
    ("name_status", FB + "nameStatus", "text", "Status of the printed name in the checklist it was matched in (Accepted, Synonym, ...)."),
    ("standard_name", FB + "standardName", "text", "The matched checklist name, when it is spelled differently from the printed one."),
    ("ipni_id", FB + "ipni", "text", "IPNI identifier of the printed name itself (the taxon carries the accepted name's)."),
    ("pages", FB + "page", "text", "Pages of the source, for the printed guides."),
]

TERM_COLUMNS = [
    ("id", None, "curie", "Identifier of the ontology class as used in the tables, for example PO:0025034."),
    ("iri", None, "subject", "Its IRI."),
    ("label", RDFS_LABEL, "text", "Its name."),
    ("organ_group", FB + "organGroup", "local", "Group of plant parts it belongs to on the website."),
    ("trait_group", FB + "traitGroup", "local", "Group of traits it belongs to on the website."),
]

TABLES = {
    "traits": ("Trait records", "One row per trait record: a statement of a flora as an annotation.", TRAIT_COLUMNS),
    "occurrences": ("Places", "One row per place a source gives for a taxon.", OCCURRENCE_COLUMNS),
    "growth-traits": ("Flowering time and growth", "One row per tabulated flowering, growth or cultivation value.", GROWTH_COLUMNS),
    "taxa": ("Taxa", "One row per taxon.", TAXON_COLUMNS),
    "taxon-names": ("Printed names", "One row per name a flora prints, with the taxon it was matched to.", NAME_COLUMNS),
    "terms": ("Ontology terms", "One row per ontology class used in the records, with its name.", TERM_COLUMNS),
}

GRAPH_KINDS = {
    "assertions": "Annotations in full: every source statement with its place in the text, each annotation with its parts, its link to an OWL annotation class, the taxon axiom, and how it was made (PROV-O).",
    "index": "The same records in a flat form (the fb: properties the website and the TSV tables use), and the transcribed statements that are not yet annotations, with the reason.",
    "places": "Where the source says the taxa grow, and flowering times.",
}
SHARED_GRAPHS = {
    "annotation-classes": "OWL definitions of all annotation classes: each is equivalent to a class expression over the Plant Ontology, PATO and FLOPO.",
    "merged": "Numeric traits of a taxon merged over sources into one range, with the records that went into it.",
    "conflicts": "Pairs of records of one taxon that state mutually exclusive values.",
    "taxa": "The taxa: accepted name, family, IPNI and WFO identifiers, and the names each source prints.",
    "vocab": "Names and groups of the ontology classes used, and the list of sources.",
    "flopo": "The Flora Phenotype Ontology with its inferred class hierarchy (flopo-inferred.owl).",
}


def curie(iri: str) -> str:
    if iri.startswith(OBO):
        return iri[len(OBO):].replace("_", ":", 1)
    return iri


def local(iri: str) -> str:
    return re.split(r"[/#]", iri.rstrip("/"))[-1]


def clean(text: str) -> str:
    return re.sub(r"[\t\r\n]+", " ", text).strip()


def subjects(path: Path) -> dict[str, dict[str, list[str]]]:
    """Every subject of an N-Quads file with its property values (as strings), in file order."""

    out: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    if path.stat().st_size == 0:
        return out
    for q in ox.parse(path=str(path), format=ox.RdfFormat.N_QUADS):
        if isinstance(q.subject, ox.BlankNode):
            continue
        out[q.subject.value][q.predicate.value].append(q.object.value)
    return out


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _as_number(text: str) -> float:
    try:
        return float(text)
    except ValueError:
        return 0.0


class Lookup:
    """Names of terms and taxa, read once and shared with the worker processes."""

    def __init__(self, release: Path, graphs: list[dict]):
        by_name = {g["graph"].rsplit("/graph/", 1)[-1]: release / g["file"] for g in graphs}
        self.labels: dict[str, str] = {}
        self.vocab = subjects(by_name["vocab"])
        for iri, props in self.vocab.items():
            if props.get(RDFS_LABEL):
                self.labels[iri] = props[RDFS_LABEL][0]
        flopo = next((release / g["file"] for g in graphs if g["file"].endswith("-flopo.nq")), None)
        if flopo:  # names of FLOPO phenotype classes, which the vocabulary graph does not list
            for q in ox.parse(path=str(flopo), format=ox.RdfFormat.N_QUADS):
                if q.predicate.value == RDFS_LABEL and not isinstance(q.subject, ox.BlankNode):
                    self.labels.setdefault(q.subject.value, q.object.value)
        self.taxa = subjects(by_name["taxa"])

    def taxon(self, iri: str, prop: str) -> str:
        values = self.taxa.get(iri, {}).get(prop) or []
        return values[0] if values else ""


LOOKUP: Lookup | None = None


def _cells(subject: str, props: dict, columns, extra=None) -> list[str]:
    row = []
    taxon = props[FB + "taxon"][0] if props.get(FB + "taxon") else ""
    for name, prop, kind, _ in columns:
        values = sorted(props.get(prop, [])) if prop else []
        if kind == "number":
            values.sort(key=_as_number)
        if kind == "subject":
            row.append(subject)
        elif kind == "curie":
            row.append(curie(subject))
        elif kind == "term":
            row.append("|".join(curie(v) for v in values))
            row.append("|".join(clean(LOOKUP.labels.get(v, "")) for v in values))
        elif kind == "local":
            row.append("|".join(local(v) for v in values))
        elif kind == "taxon_name":
            row.append(LOOKUP.taxon(taxon, RDFS_LABEL))
        elif kind == "taxon_family":
            row.append(LOOKUP.taxon(taxon, FB + "family"))
        elif kind == "taxon_ipni":
            row.append(LOOKUP.taxon(taxon, FB + "ipni"))
        elif kind == "bool":
            row.append("|".join(values))
        elif kind in ("alternatives", "taxon_of_name", "count"):
            row.append(extra[name] if extra else "")
        else:
            row.append("|".join(clean(v) for v in values))
    return row


def header(columns) -> list[str]:
    out = []
    for name, _, kind, _ in columns:
        out.extend([name + "_id", name + "_label"] if kind == "term" else [name])
    return out


class Gz:
    """A gzipped TSV written through pigz."""

    def __init__(self, path: Path, columns):
        self.path, self.rows = path, 0
        self.out = path.open("wb")
        self.proc = subprocess.Popen(["pigz", "-6", "-p", "4"], stdin=subprocess.PIPE, stdout=self.out)
        self.write(header(columns), count=False)

    def write(self, row: list[str], count: bool = True) -> None:
        self.proc.stdin.write(("\t".join(row) + "\n").encode())
        self.rows += count

    def close(self) -> int:
        self.proc.stdin.close()
        if self.proc.wait():
            raise SystemExit(f"pigz failed on {self.path}")
        self.out.close()
        return self.rows


PLAIN_KINDS = ("index", "places", "taxa", "vocab")
PLAIN_NAME = "plain-records.nt.gz"
_BLANK = r"^_:| _:[^ ]+ <[^ ]+> \.$"


def plain_triples(release: Path, graphs: list[dict], target: Path) -> int:
    """The flat graphs as one N-Triples file: graph names dropped, triples with a blank node left out.

    These graphs (flat records, places, taxa, term names) use no OWL constructs, so the file can be
    read without knowing OWL and loaded into a store that makes its own named graphs."""

    paths = [str(release / g["file"]) for g in graphs
             if g["graph"].rsplit("/", 1)[-1] in PLAIN_KINDS and (release / g["file"]).stat().st_size]
    script = (f"cat \"$@\" | LC_ALL=C grep -v -E '{_BLANK}' | LC_ALL=C sed -E 's/ <[^ >]+> \\.$/ ./' "
              f"| tee >(wc -l > \"$OUT.count\") | pigz -6 -p 6 > \"$OUT\"")
    env = dict(os.environ, OUT=str(target))
    subprocess.run(["bash", "-o", "pipefail", "-c", script, "plain", *paths], check=True, env=env)
    count = Path(str(target) + ".count")
    for _ in range(50):  # the counting process may end a moment after the pipeline
        if count.exists() and count.read_text().strip():
            break
        time.sleep(0.1)
    lines = int(count.read_text().strip())
    count.unlink()
    return lines


def source_tables(task: tuple[str, str | None, str | None, str]) -> dict:
    """Tables of one source: its trait records, and its part of the place and growth tables."""

    source, index, places, tsv = task
    out = {"source": source, "taxa": {}}
    data = subjects(Path(index)) if index else {}
    if index:
        gz = Gz(Path(tsv) / f"traits-{source}.tsv.gz", TRAIT_COLUMNS)
        counts: dict[str, int] = defaultdict(int)
        for subject, props in data.items():
            if FB + "TraitRecord" not in props.get(RDF_TYPE, []):
                continue
            pairs = []
            for node in props.get(FB + "alternative", []):
                alt = data.get(node, {})
                if alt.get(FB + "quality") and alt.get(FB + "frequency"):
                    pairs.append(f"{curie(alt[FB + 'quality'][0])}={alt[FB + 'frequency'][0]}")
            gz.write(_cells(subject, props, TRAIT_COLUMNS, {"alternative_frequencies": "|".join(sorted(pairs))}))
            if props.get(FB + "taxon"):
                counts[props[FB + "taxon"][0]] += 1
        out["traits"] = gz.close()
        out["taxa"] = dict(counts)
    # Place and growth records are in the places graph; the Saudi guide's growth table is in its index.
    other = subjects(Path(places)) if places else {}
    for kind, rdf_type, columns in (("occurrences", "Occurrence", OCCURRENCE_COLUMNS), ("growth-traits", "GrowthTrait", GROWTH_COLUMNS)):
        gz = Gz(Path(tsv) / f".{kind}-{source}.part.gz", columns)
        for records in (other, data):
            for subject, props in records.items():
                if FB + rdf_type in props.get(RDF_TYPE, []):
                    gz.write(_cells(subject, props, columns))
        out[kind] = gz.close()
    return out


def _concatenate(parts: list[Path], target: Path) -> None:
    """One gzipped table from several that share a header line."""

    script = "{ pigz -dc \"$1\" | head -n 1; shift; for f; do pigz -dc \"$f\" | tail -n +2; done; } | pigz -6 -p 8"
    with target.open("wb") as out:
        subprocess.run(["bash", "-c", script, "bash", parts[0], *parts], stdout=out, check=True)


def readme(meta: dict, files: list[dict], sources: dict[str, dict]) -> str:
    lines = [
        "FLOPO Trait Atlas: data downloads",
        "=================================",
        "",
        f"Release {meta['stamp']}. Website, queries and documentation: http://phenomebrowser.net/flopo/",
        "",
        "The atlas holds plant trait statements from floras, each annotated with the Flora Phenotype",
        "Ontology (FLOPO), the Plant Ontology (PO) and the quality ontology PATO, for taxa named after",
        "IPNI / Kew's World Checklist of Vascular Plants. This directory has everything the website and",
        "its SPARQL endpoint hold, in two forms: RDF (complete) and TSV tables (the records, flat).",
        "",
        "The annotations were made automatically (language-model transcription of the flora text,",
        "then rule-based mapping to ontology classes and automatic checks). They contain errors. The",
        "status column says what the checks decided; the source text is kept with every record so",
        "that each annotation can be checked.",
        "",
        "Licence: the annotations are CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/);",
        "LICENSE.txt has the terms and the credit line, CITATION.cff the citation. FLOPO is CC0. The",
        "quoted source text (text, context, and the source statements in the RDF) is not covered: it",
        "remains under the rights of the floras it comes from.",
        "",
        "Metadata: void.ttl describes this version for programs (VoID and DCAT: licence, version and",
        "previous version, every graph and file with size and checksum, the sources); dataset.jsonld",
        "is the same in schema.org terms; tsv/csv-metadata.json gives the columns of the tables as",
        "CSV on the Web. The version is the build time of the data; its permanent address is",
        "http://phenomebrowser.net/flopo/release/<version>.",
        "",
        "RDF (rdf/)",
        "----------",
        "",
        "N-Quads, gzip-compressed, one file per named graph. Graph names are",
        "http://phenomebrowser.net/flopo/saudi-flora/graph/<name>. Blank-node labels are distinct",
        "between files, so the files can be loaded together or concatenated. Loading all files",
        "into a SPARQL store reproduces the public endpoint (http://phenomebrowser.net/flopo/sparql).",
        "",
        "Without OWL: rdf/plain-records.nt.gz has the flat records, the places, the taxa and the term",
        "names of all sources as N-Triples: no named graphs, no blank nodes, no OWL constructs. It is",
        "the file for a triple store that makes its own graphs, or for reading the data as a plain",
        "graph. A record (fb:TraitRecord) points to its taxon (fb:taxon), plant part (fb:bearer),",
        "value (fb:quality), numbers (fb:low, fb:high, fb:unit) and sentence (fb:text); a taxon",
        "points to its records with fb:record. The same triples are in the <source>/index,",
        "<source>/places, taxa and vocab graphs below.",
        "",
        "Each source has up to three graphs:",
    ]
    lines += [f"  <source>/{kind}: {text}" for kind, text in GRAPH_KINDS.items()]
    lines += ["", "Shared graphs:"] + [f"  {name}: {text}" for name, text in SHARED_GRAPHS.items()]
    lines += [
        "",
        "Namespaces: fb: http://phenomebrowser.net/flopo/browse# (flat record properties),",
        "http://phenomebrowser.net/flopo/annotation/ (annotation model), obo: http://purl.obolibrary.org/obo/",
        "(FLOPO, PO, PATO, UO, RO, BFO), sio: http://semanticscience.org/resource/, prov: http://www.w3.org/ns/prov#.",
        "The annotation patterns, with their OWL and RDF forms, are documented on the Patterns pages of the website.",
        "",
        "An annotation class is an OWL class with a definition, for example",
        "  'has part' some (leaf and 'has characteristic' some glabrous)",
        "and a taxon is a subclass of the classes of its accepted records. 'X or Y' is a union of",
        "values, the absence of a part X is not ('has part' some ('part of' some X)), and numbers",
        "are data ranges.",
        "",
        "Evidence and provenance are kept apart. Evidence is what supports an annotation: its source",
        "sentence, linked with 'has evidence' (RO:0002558) and typed ECO:0007319, author statement",
        "used in automatic assertion. Provenance is how it was made (PROV-O): prov:wasDerivedFrom the",
        "sentence, prov:wasGeneratedBy the extraction step.",
        "",
        "TSV tables (tsv/)",
        "-----------------",
        "",
        "Tab-separated, UTF-8, gzip-compressed, first line is the header. No quoting: tabs and line",
        "breaks inside text are replaced by spaces. Empty means not stated. Several values in one cell",
        "are joined with '|'. Ontology classes are written as CURIEs (PO:0025034); every such column",
        "<name>_id is followed by <name>_label with the class names. Read with, for example,",
        "  pandas.read_csv('traits-all.tsv.gz', sep='\\t', dtype=str, quoting=3)",
        "  read.delim(gzfile('traits-all.tsv.gz'), quote='', colClasses='character')",
        "",
        "The tables hold the flat form of the records. What only the RDF has: the OWL definitions,",
        "the full provenance of each annotation, statements not yet annotated, merged ranges and conflicts.",
        "",
    ]
    for key, (title, text, columns) in TABLES.items():
        names = "traits-<source>.tsv.gz and traits-all.tsv.gz" if key == "traits" else f"{key}.tsv.gz"
        lines += [f"{title}: {names}", f"  {text}", ""]
        for name, _, kind, description in columns:
            shown = f"{name}_id, {name}_label" if kind == "term" else name
            lines += [f"  {shown}", f"      {description}"]
        lines.append("")
    lines += ["Sources", "-------", ""]
    for key, info in sorted(sources.items()):
        lines.append(f"  {key}: {info.get('title') or info.get('label') or key}")
    lines += ["", "Files", "-----", "", "SHA-256 checksums are in SHA256SUMS.txt.", ""]
    for f in files:
        count = f"{f['rows']:,} rows" if "rows" in f else f"{f['triples']:,} triples" if "triples" in f else ""
        lines.append(f"  {f['path']}  {f['bytes']:,} bytes  {count}")
    return "\n".join(lines) + "\n"


def build(release: Path, jobs: int = 8) -> Path:
    global LOOKUP
    meta = json.loads((release / "release.json").read_text())
    out = release / "downloads"
    if out.exists():
        raise SystemExit(f"{out} exists")
    tmp = release / "downloads.tmp"
    subprocess.run(["rm", "-rf", str(tmp)], check=True)
    (tmp / "rdf").mkdir(parents=True)
    (tmp / "tsv").mkdir()
    started = time.time()

    # RDF: every graph file, compressed.
    files: list[dict] = []
    present = [g for g in meta["graphs"] if (release / g["file"]).stat().st_size]
    procs = []
    for g in present:
        target = tmp / "rdf" / (Path(g["file"]).name + ".gz")
        procs.append((g, target, target.open("wb")))
    for start in range(0, len(procs), jobs):
        batch = [(subprocess.Popen(["pigz", "-6", "-p", "6", "-c", str(release / g["file"])], stdout=handle), handle)
                 for g, _, handle in procs[start:start + jobs]]
        for proc, handle in batch:
            if proc.wait():
                raise SystemExit("pigz failed")
            handle.close()
    print(f"rdf: {len(present)} files compressed ({time.time() - started:.0f}s)", file=sys.stderr)
    plain_count = plain_triples(release, present, tmp / "rdf" / PLAIN_NAME)
    print(f"rdf: {plain_count} plain triples ({time.time() - started:.0f}s)", file=sys.stderr)

    # Tables.
    LOOKUP = Lookup(release, meta["graphs"])
    sources = {local(iri): {"label": props[RDFS_LABEL][0] if props.get(RDFS_LABEL) else "",
                            "title": props[DCT + "title"][0] if props.get(DCT + "title") else ""}
               for iri, props in LOOKUP.vocab.items()
               if any(o == FB + "Source" for o in props.get(RDF_TYPE, []))}
    per_source: dict[str, dict[str, str]] = defaultdict(dict)
    for g in present:
        name = g["graph"].rsplit("/graph/", 1)[-1]
        if "/" in name:
            source, kind = name.rsplit("/", 1)
            per_source[source][kind] = str(release / g["file"])
    tasks = [(s, kinds.get("index"), kinds.get("places"), str(tmp / "tsv")) for s, kinds in per_source.items()]
    tasks.sort(key=lambda t: -(os.path.getsize(t[1]) if t[1] else 0))
    with ProcessPoolExecutor(max_workers=jobs) as pool:  # forked: the workers share LOOKUP
        results = list(pool.map(source_tables, tasks))
    print(f"tsv: {len(results)} sources ({time.time() - started:.0f}s)", file=sys.stderr)
    order = sorted(per_source)
    rows = {r["source"]: r for r in results}
    tsv = tmp / "tsv"
    trait_parts = [tsv / f"traits-{s}.tsv.gz" for s in order if rows[s].get("traits")]
    for s in order:  # a source without trait records gets no table
        path = tsv / f"traits-{s}.tsv.gz"
        if path.exists() and not rows[s].get("traits"):
            path.unlink()
    _concatenate(trait_parts, tsv / "traits-all.tsv.gz")
    for kind in ("occurrences", "growth-traits"):
        parts = [tsv / f".{kind}-{s}.part.gz" for s in order if (tsv / f".{kind}-{s}.part.gz").exists()]
        _concatenate(parts, tsv / f"{kind}.tsv.gz")
        for part in parts:
            part.unlink()
    taxon_counts: dict[str, int] = defaultdict(int)
    for r in results:
        for taxon, count in r["taxa"].items():
            taxon_counts[taxon] += count
    table_rows = {
        "traits-all": sum(r.get("traits", 0) for r in results),
        "occurrences": sum(r["occurrences"] for r in results),
        "growth-traits": sum(r["growth-traits"] for r in results),
    }
    gz = Gz(tsv / "taxa.tsv.gz", TAXON_COLUMNS)
    names = Gz(tsv / "taxon-names.tsv.gz", NAME_COLUMNS)
    for iri in sorted(LOOKUP.taxa):
        props = LOOKUP.taxa[iri]
        if not any(o == FB + "Taxon" for o in props.get(RDF_TYPE, [])):
            continue
        gz.write(_cells(iri, props, TAXON_COLUMNS, {"trait_records": str(taxon_counts.get(iri, 0))}))
        for node in props.get(FB + "printedName", []):
            names.write(_cells(node, LOOKUP.taxa.get(node, {}), NAME_COLUMNS, {"taxon": iri}))
    table_rows["taxa"], table_rows["taxon-names"] = gz.close(), names.close()
    gz = Gz(tsv / "terms.tsv.gz", TERM_COLUMNS)
    for iri in sorted(LOOKUP.vocab):
        if LOOKUP.vocab[iri].get(FB + "curie"):
            gz.write(_cells(iri, LOOKUP.vocab[iri], TERM_COLUMNS))
    table_rows["terms"] = gz.close()

    # The list of files.
    for g, target, _ in procs:
        name = g["graph"].rsplit("/graph/", 1)[-1]
        source, kind = name.rsplit("/", 1) if "/" in name else ("", name)
        files.append({"path": f"rdf/{target.name}", "format": "nquads", "graph": g["graph"], "source": source,
                      "kind": kind, "triples": g["triples"], "bytes": target.stat().st_size, "sha256": _sha256(target)})
    plain = tmp / "rdf" / PLAIN_NAME
    files.append({"path": f"rdf/{PLAIN_NAME}", "format": "ntriples", "kind": "plain", "source": "",
                  "title": "Flat records, places, taxa and term names as plain triples",
                  "triples": plain_count, "bytes": plain.stat().st_size, "sha256": _sha256(plain)})
    for path in sorted(tsv.glob("*.tsv.gz")):
        stem = path.name.removesuffix(".tsv.gz")
        source = stem.removeprefix("traits-") if stem.startswith("traits-") and stem != "traits-all" else ""
        files.append({"path": f"tsv/{path.name}", "format": "tsv", "source": source,
                      "table": "traits" if stem.startswith("traits-") else stem,
                      "rows": rows[source]["traits"] if source else table_rows[stem],
                      "bytes": path.stat().st_size, "sha256": _sha256(path)})
    (tmp / "README.txt").write_text(readme(meta, files, sources), encoding="utf-8")
    (tmp / "SHA256SUMS.txt").write_text("".join(f"{f['sha256']}  {f['path']}\n" for f in files))
    manifest = {
        "release": meta["stamp"],
        "sources": sources,
        "graph_kinds": GRAPH_KINDS,
        "shared_graphs": SHARED_GRAPHS,
        "tables": {key: {"title": title, "description": text,
                         "columns": [{"name": f"{n}_id, {n}_label" if kind == "term" else n, "description": d}
                                     for n, _, kind, d in columns]}
                   for key, (title, text, columns) in TABLES.items()},
        "files": files,
    }
    (tmp / "downloads.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.rename(out)
    print(f"downloads: {len(files)} files, {sum(f['bytes'] for f in files) / 1e9:.1f} GB ({time.time() - started:.0f}s)", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("release", type=Path)
    parser.add_argument("--jobs", type=int, default=8)
    args = parser.parse_args(argv)
    print(build(args.release, args.jobs))


if __name__ == "__main__":
    main()
