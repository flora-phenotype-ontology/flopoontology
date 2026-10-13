"""Build the Saudi-flora RDF dataset: FLOPO annotations from every Saudi source, one named graph each.

For each source corpus (stage-22 wire-format JSONL) the dataset contains

* ``<source>/assertions`` -- the source-scoped OWL assertion module of
  :mod:`flopo2.owl.assertions` (source statements, formal flora assertions linked to FAC annotation
  classes, strict taxon axioms, provenance);
* ``<source>/index`` -- a browse index on the same assertion IRIs (``fb:`` vocabulary): taxon,
  bearer, quality, FLOPO class, organ and trait group, numeric value, gate status, source text;
  plus every transcribed statement that is not (yet) a formal assertion, as ``fb:PendingStatement``
  with the reason;
* ``<source>/places`` -- taxon occurrence by Saudi region and named locality.

Shared graphs: ``taxa`` (accepted WFO taxa that merge the sources, printed names per source) and
``vocab`` (labels and groups for every PO/PATO/FLOPO term used, the region list, the sources).

The dataset is written as N-Quads to ``local-corpora/saudi-flora/rdf/`` (git-ignored: it contains
verbatim text of copyrighted guides) with a ``summary.json`` of coverage figures.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

from rdflib import OWL, RDF, RDFS, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS, SKOS

from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.owl.assertions import (
    HAS_PHENOTYPE,
    UNIT_IRIS,
    _load_attributes,
    _Nodes,
    _phenotype_expression,
    _some,
    build_assertion_ontology,
    formal_assertion_iri,
)
from flopo2.saudi.taxa import resolve
from flopo2.saudi.vocab import ORGAN_GROUPS, TRAIT_GROUPS, Vocabulary, curie, iri

BASE = "http://phenomebrowser.net/flopo/"
FB = Namespace(BASE + "browse#")
GRAPH = BASE + "saudi-flora/graph/"
REGION = BASE + "geo/region/"
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
OUT = Path("local-corpora/saudi-flora")

REGIONS = {
    "SA-01": "Riyadh", "SA-02": "Makkah", "SA-03": "Al Madinah", "SA-04": "Eastern Province",
    "SA-05": "Al Qassim", "SA-06": "Ha'il", "SA-07": "Tabuk", "SA-08": "Northern Borders",
    "SA-09": "Jazan", "SA-10": "Najran", "SA-11": "Al Bahah", "SA-12": "Al Jawf", "SA-14": "Asir",
}

SOURCES = {
    "ncvc": {
        "title": "Guide to the native plants of the Kingdom of Saudi Arabia (NCVC, 2024)",
        "short": "NCVC 2024",
        "corpus": Path("local-corpora/saudi-flora/ncvc-derived/ncvc-saudi-annotated.jsonl"),
        "raw": Path("local-corpora/saudi-ncvc-guide/raw"),
        "dispositions": Path("local-corpora/saudi-flora/ncvc-derived/ncvc-saudi-phenotype-dispositions.tsv"),
        "distribution": Path("local-corpora/saudi-ncvc-guide/derived/ncvc-saudi-distribution.tsv"),
        "growth": Path("local-corpora/saudi-ncvc-guide/derived/ncvc-saudi-growth-traits.tsv"),
        "taxa": Path("local-corpora/saudi-ncvc-guide/derived/ncvc-saudi-taxa.tsv"),
    },
    "collenette": {
        "title": "S. Collenette, An illustrated guide to the flowers of Saudi Arabia (1985)",
        "short": "Collenette 1985",
        "corpus": Path("local-corpora/saudi-collenette/derived/collenette-saudi-annotated.jsonl"),
        "raw_jsonl": Path("local-corpora/saudi-collenette/raw/collenette-qwen.jsonl"),
        "dispositions": Path("local-corpora/saudi-collenette/derived/collenette-saudi-dispositions.tsv"),
    },
}

GROWTH_LABELS = {
    "flowering": "Flowering time", "growth_rate": "Growth rate", "drought": "Drought tolerance",
    "waterlogging": "Waterlogging tolerance", "soil_salinity_ppm": "Soil salinity tolerance",
    "temperature_c": "Temperature range", "frost": "Frost tolerance", "elevation_m": "Elevation",
    "propagation": "Propagation", "planting_time": "Planting time", "irrigation": "Irrigation need",
    "fertilization": "Fertilization need", "care": "Care", "toxicity_hazards": "Toxicity and hazards",
    "pests_diseases": "Pests and diseases", "common_stresses": "Common stresses",
}
MONTHS = "January February March April May June July August September October November December".split()


UNIT_LABELS = {"UO_0000008": "m", "UO_0000015": "cm", "UO_0000016": "mm", "UO_0000017": "µm"}
UNIT_FACTOR = {"UO_0000008": 1.0, "UO_0000015": 0.01, "UO_0000016": 0.001, "UO_0000017": 1e-6}
UO_NAMES = {"UO_0000008": "meter", "UO_0000015": "centimeter", "UO_0000016": "millimeter", "UO_0000017": "micrometer"}


def unit_uo(unit: str) -> str:
    """Printed unit -> UO local id (UO_0000008 for m)."""

    return UNIT_IRIS.get(str(unit or "").strip().rstrip(".").lower(), "")


def _digest(*parts: object) -> str:
    return hashlib.sha256("\n".join(map(str, parts)).encode("utf-8")).hexdigest()[:24]


def _lit(value, datatype=None):
    return Literal(value, datatype=datatype) if datatype else Literal(value)


def _number(value) -> Literal | None:
    if value is None or value == "":
        return None
    try:
        return Literal(float(value), datatype=XSD.decimal)
    except (TypeError, ValueError):
        return None


class Builder:
    def __init__(self, out: Path = OUT) -> None:
        self.out = out
        self.vocab = Vocabulary()
        self.used_terms: set[str] = set()
        self.taxa: dict[str, dict] = {}  # taxon IRI -> info
        self.names: dict[str, object] = {}
        self.aliases: dict[str, str] = {}
        self.not_names: set[str] = set()
        self.summary: dict[str, dict] = {}
        # (taxon, bearer, attribute) -> numeric records of every source, for merged ranges
        self.numeric: dict[tuple[str, str, str], list[dict]] = {}

    # ------------------------------------------------------------------ taxa
    def resolve_names(self, names: list[str]) -> None:
        """Resolve printed names, applying WFO-verified OCR corrections (taxa.propose_name_fixes)."""

        fixes_path = self.out / "name-fixes.json"
        fixes = json.loads(fixes_path.read_text()) if fixes_path.exists() else {}
        self.aliases = {n: f["proposed"] for n, f in fixes.items() if f.get("verified")}
        self.not_names = {n for n, f in fixes.items() if f.get("verdict") == "not a name"}
        self.names = resolve(sorted({*names, *self.aliases.values()}), self.out / "taxon-cache.json")

    def taxon(self, name: str, source: str, *, family: str = "", page: object = "") -> URIRef:
        resolved = self.names.get(self.aliases.get(name, name))
        if resolved and not resolved.accepted_wfo_id and name in self.not_names:
            resolved = None
            label = f"Unidentified entry: “{name}”"
            taxon_iri = BASE + "taxon/name/" + quote(name.replace(" ", "_"))
            self.taxa.setdefault(taxon_iri, {"label": label, "authorship": "", "family": family, "order": "",
                                             "wfo": "", "names": {}, "extra": defaultdict(set)})
        taxon_iri = resolved.taxon_iri if resolved else BASE + "taxon/name/" + quote(name.replace(" ", "_"))
        info = self.taxa.setdefault(
            taxon_iri,
            {
                "label": (resolved.label if resolved else name) or name,
                "authorship": resolved.accepted_authorship if resolved else "",
                "family": (resolved.family if resolved and resolved.family else family),
                "order": resolved.order if resolved else "",
                "wfo": resolved.accepted_wfo_id if resolved else "",
                "names": {},
                "extra": defaultdict(set),
            },
        )
        if not info["family"] and family:
            info["family"] = family
        entry = info["names"].setdefault((source, name), {"pages": set(), "status": ""})
        if str(page).strip().isdigit():
            entry["pages"].add(str(int(page)))
        if resolved:
            entry["status"] = resolved.status or resolved.match_type
        return URIRef(taxon_iri)

    # ------------------------------------------------------------------ index
    def index_corpus(self, key: str, corpus: Path, graph: Graph) -> Counter:
        counts: Counter = Counter()
        source = URIRef(BASE + "saudi-flora/source/" + key)
        for line in corpus.open(encoding="utf-8"):
            record = json.loads(line)
            if record.get("language") == "ar":
                continue
            page = re.search(r"page-(\d+)", record.get("source_id", ""))
            taxon = self.taxon(record["taxon"], key, family=record.get("taxon_family", ""), page=page.group(1) if page else "")
            statements = {s["statement_id"]: s for s in record.get("source_statements") or []}
            text = record.get("text", "")
            for index, assertion in enumerate(record.get("assertions") or []):
                formal = formal_assertion_iri(assertion["source_statement_id"], index, assertion)
                self._index_assertion(graph, formal, assertion, taxon, source, statements, text)
                counts["assertions"] += 1
                counts[f"gate_{assertion['gate']['status']}"] += 1
            for span in record.get("unresolved_spans") or []:
                node = URIRef(BASE + "saudi-flora/pending/" + _digest(key, record["source_id"], span["start"], span["end"], span["reason"]))
                graph.add((node, RDF.type, FB.PendingStatement))
                graph.add((node, FB.taxon, taxon))
                graph.add((node, FB.source, source))
                graph.add((node, FB.text, Literal(span.get("surface_form", ""))))
                graph.add((node, FB.reason, Literal(span.get("reason", ""))))
                graph.add((node, FB.context, Literal(_sentence(text, span["start"], span["end"]))))
                if span.get("candidate_pato_id"):
                    graph.add((node, FB.quality, URIRef(iri(span["candidate_pato_id"]))))
                    self.used_terms.add(curie(span["candidate_pato_id"]))
                counts["pending"] += 1
        return counts

    def _index_assertion(self, g: Graph, formal: URIRef, a: dict, taxon, source, statements, text) -> None:
        gate = a.get("gate") or {}
        bearer = a["po_id"]
        values = a.get("value_terms") or []
        relation = a.get("qualitative_value_relation") or {}
        quality = values[0] if values else (relation.get("from_value") or a["pato_id"])
        g.add((formal, RDF.type, FB.TraitRecord))
        g.add((formal, FB.taxon, taxon))
        g.add((formal, FB.source, source))
        g.add((formal, FB.bearer, URIRef(iri(bearer))))
        g.add((formal, FB.quality, URIRef(iri(quality))))
        if (values or relation) and a.get("pato_id"):
            g.add((formal, FB.attribute, URIRef(iri(a["pato_id"]))))
        if relation:
            # Both endpoints are values of the record, so "ovate to oblong" is found under both.
            g.add((formal, FB.quality, URIRef(iri(relation["to_value"]))))
            g.add((formal, FB.fromValue, URIRef(iri(relation["from_value"]))))
            g.add((formal, FB.toValue, URIRef(iri(relation["to_value"]))))
            g.add((formal, FB.relation, Literal(relation["interpretation"])))
            g.add((formal, FB.connector, Literal(relation["connector_text"].strip())))
            g.add((formal, FB.fromText, Literal(relation["from_text"])))
            g.add((formal, FB.toText, Literal(relation["to_text"])))
            for side, prop in (("from", FB.fromDegree), ("to", FB.toDegree)):
                operand = relation.get(f"{side}_operand") or {}
                if operand.get("degree_qualifier", "unmodified") != "unmodified":
                    g.add((formal, prop, Literal(operand["degree_qualifier"])))
            self.used_terms.update({curie(relation["from_value"]), curie(relation["to_value"])})
        self.used_terms.update({curie(bearer), curie(quality), curie(a.get("pato_id") or quality)})
        if gate.get("flopo_iri"):
            g.add((formal, FB.flopoClass, URIRef(gate["flopo_iri"])))
            self.used_terms.add(curie(gate["flopo_iri"]))
        if a.get("phenotype_class_iri"):
            g.add((formal, FB.phenotypeClass, URIRef(a["phenotype_class_iri"])))
        g.add((formal, FB.organGroup, FB["organ-" + self.vocab.organ_group(bearer)]))
        g.add((formal, FB.traitGroup, FB["trait-" + self.vocab.trait_group(quality, a.get("pato_id", ""))]))
        g.add((formal, FB.status, Literal(gate.get("status", ""))))
        g.add((formal, FB.negated, Literal(bool(a.get("negated")))))
        for prop, field in ((FB.low, "value_low"), (FB.high, "value_high")):
            number = _number(a.get(field))
            if number is not None:
                g.add((formal, prop, number))
        if a.get("unit"):
            uo = unit_uo(a["unit"])
            g.add((formal, FB.unit, URIRef(iri(uo)) if uo else Literal(a["unit"])))
            if uo:
                self.used_terms.add(curie(uo))
            g.add((formal, FB.unitSymbol, Literal(a["unit"])))
            if uo and (a.get("value_low") is not None or a.get("value_high") is not None):
                self.numeric.setdefault((str(taxon), bearer, a["pato_id"]), []).append(
                    {"record": formal, "source": source, "low": a.get("value_low"),
                     "high": a.get("value_high"), "uo": uo}
                )
        if a.get("value_qualifier") not in (None, "", "exact"):
            g.add((formal, FB.qualifier, Literal(a["value_qualifier"])))
        if a.get("frequency_qualifier") not in (None, "", "unspecified"):
            g.add((formal, FB.frequency, Literal(a["frequency_qualifier"])))
        g.add((formal, FB.text, Literal(a.get("source_text", ""))))
        statement = statements.get(a.get("source_statement_id"))
        if statement:
            g.add((formal, FB.context, Literal(_sentence(text, statement["start"], statement["end"]))))
        g.add((formal, RDFS.label, Literal(self._label(a, bearer, quality))))

    def _label(self, a: dict, bearer: str, quality: str) -> str:
        organ = self.vocab.label(bearer)
        if a.get("value_low") is not None or a.get("value_high") is not None:
            low, high = a.get("value_low"), a.get("value_high")
            fmt = lambda v: f"{float(v):g}"  # noqa: E731
            if low is not None and high is not None and float(low) != float(high):
                value = f"{fmt(low)}–{fmt(high)}"
            elif low is None:
                value = f"up to {fmt(high)}"
            elif high is None:
                value = f"at least {fmt(low)}"
            else:
                value = fmt(low)
            unit = UNIT_LABELS.get(unit_uo(a.get("unit", "")), a.get("unit", ""))
            return f"{organ} {self.vocab.label(a['pato_id'])} {value} {unit}".strip()
        relation = a.get("qualitative_value_relation")
        if relation:
            return (f"{organ} {self.vocab.label(relation['from_value'])} "
                    f"{relation['connector_text'].strip()} {self.vocab.label(relation['to_value'])}")
        if a.get("negated") and a.get("negation_scope") == "absence":
            return f"{organ} absent"
        prefix = "not " if a.get("negated") else ""
        return f"{organ} {prefix}{self.vocab.label(quality)}"

    # ------------------------------------------------------------------ places
    def ncvc_places(self, cfg: dict, g: Graph) -> int:
        count = 0
        source = URIRef(BASE + "saudi-flora/source/ncvc")
        with cfg["distribution"].open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                taxon = self.taxon(row["taxon"], "ncvc", family=row.get("taxon_family", ""))
                region = row.get("iso_3166_2") or row.get("gaz_admin1_iso_3166_2") or ""
                self._occurrence(
                    g, source, taxon, region, row.get("locality_name", ""), row.get("feature_type", ""),
                    row.get("gaz_lat", ""), row.get("gaz_lon", ""), row.get("basis", ""),
                )
                count += 1
        return count

    def _occurrence(self, g, source, taxon, region, locality, feature, lat, lon, basis, verbatim="") -> None:
        node = URIRef(BASE + "saudi-flora/occurrence/" + _digest(source, taxon, region, locality, verbatim))
        g.add((node, RDF.type, FB.Occurrence))
        g.add((node, FB.taxon, taxon))
        g.add((node, FB.source, source))
        if region in REGIONS:
            g.add((node, FB.region, URIRef(REGION + region)))
        if locality:
            g.add((node, FB.locality, Literal(locality)))
        if verbatim and verbatim != locality:
            g.add((node, FB.verbatimLocality, Literal(verbatim)))
        if feature:
            g.add((node, FB.featureType, Literal(feature)))
        if basis:
            g.add((node, FB.basis, Literal(basis)))
        if lat and lon:
            g.add((node, FB.lat, Literal(float(lat), datatype=XSD.decimal)))
            g.add((node, FB.lon, Literal(float(lon), datatype=XSD.decimal)))
            g.add((node, GEO.asWKT, Literal(f"POINT ({float(lon)} {float(lat)})", datatype=GEO.wktLiteral)))

    def ncvc_extras(self, cfg: dict, g: Graph) -> int:
        """Growth/cultivation table cells, vernacular names, native range and abundance."""

        source = URIRef(BASE + "saudi-flora/source/ncvc")
        count = 0
        with cfg["growth"].open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                taxon = self.taxon(row["taxon"], "ncvc")
                node = URIRef(BASE + "saudi-flora/growth/" + _digest("ncvc", row["source_id"], row["table"], row["trait"]))
                g.add((node, RDF.type, FB.GrowthTrait))
                g.add((node, FB.taxon, taxon))
                g.add((node, FB.source, source))
                g.add((node, FB.trait, Literal(row["trait"])))
                g.add((node, RDFS.label, Literal(GROWTH_LABELS.get(row["trait"], row["trait"].replace("_", " ")))))
                g.add((node, FB.value, Literal(row["value_en"])))
                if row.get("value_ar"):
                    g.add((node, FB.value, Literal(row["value_ar"], lang="ar")))
                for prop, field in ((FB.low, "low"), (FB.high, "high")):
                    number = _number(row.get(field))
                    if number is not None:
                        g.add((node, prop, number))
                if row.get("unit"):
                    g.add((node, FB.unit, Literal(row["unit"])))
                for month in filter(None, (row.get("months") or "").split("|")):
                    g.add((node, FB.month, Literal(int(month))))
                if row.get("ontology_hint"):
                    g.add((node, FB.ontologyHint, Literal(row["ontology_hint"])))
                count += 1
        with cfg["taxa"].open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                taxon = self.taxon(row["scientific_name"], "ncvc", page=row.get("pdf_page", ""))
                info = self.taxa[str(taxon)]["extra"]
                for name in filter(None, (row.get("arabic_names") or "").split("|")):
                    info["vernacular_ar"].add(name)
                if row.get("native_range_en"):
                    info["native_range"].add(row["native_range_en"])
                if row.get("abundance_en"):
                    info["abundance"].add(("ncvc", row["abundance_en"]))
        return count

    def collenette_extras(self, cfg: dict, g: Graph) -> int:
        """Localities, elevation, abundance, habitat and flowering from the LLM transcription."""

        source = URIRef(BASE + "saudi-flora/source/collenette")
        gazetteer = _gazetteer()
        latest = {}
        for line in cfg["raw_jsonl"].open(encoding="utf-8"):
            row = json.loads(line)
            if "error" not in row:
                latest[row["source_id"]] = row
        count = 0
        for raw in latest.values():
            taxon = self.taxon(raw["taxon"], "collenette")
            info = self.taxa[str(taxon)]["extra"]
            if raw.get("abundance_en"):
                info["abundance"].add(("collenette", raw["abundance_en"]))
            if raw.get("habitat_en"):
                info["habitat"].add(("collenette", raw["habitat_en"]))
            elevation = raw.get("elevation") or {}
            if elevation.get("low") or elevation.get("high"):
                low, high = elevation.get("low") or elevation.get("high"), elevation.get("high") or elevation.get("low")
                try:
                    metres = [round(float(v) * 0.3048) for v in (low, high)]
                    info["elevation_m"].update(metres)
                except (TypeError, ValueError):
                    pass
            for month in raw.get("flowering_months") or []:
                if isinstance(month, int) and 1 <= month <= 12:
                    node = URIRef(BASE + "saudi-flora/growth/" + _digest("collenette", raw["source_id"], "flowering"))
                    g.add((node, RDF.type, FB.GrowthTrait))
                    g.add((node, FB.taxon, taxon))
                    g.add((node, FB.source, source))
                    g.add((node, FB.trait, Literal("flowering")))
                    g.add((node, RDFS.label, Literal("Flowering time")))
                    g.add((node, FB.value, Literal(raw.get("flowering_text") or "")))
                    g.add((node, FB.month, Literal(month)))
            for loc in raw.get("localities") or []:
                name = loc.get("name_en", "")
                hit = gazetteer.get(name.lower())
                region = loc.get("region_iso_3166_2") or (hit or {}).get("region", "")
                self._occurrence(
                    g, source, taxon, region, name, loc.get("feature_type", ""),
                    (hit or {}).get("lat", ""), (hit or {}).get("lon", ""),
                    loc.get("region_basis", ""), verbatim=loc.get("verbatim", ""),
                )
                count += 1
        return count


    # ------------------------------------------------------------------ merged numeric ranges
    def merged_graph(self) -> Graph:
        """One range per taxon, plant part and attribute over all sources' numeric values.

        Each source value lies in the merged range, so every source claim entails the merged
        class: ``taxon SubClassOf has_phenotype some (bearer and has_quality some (attribute and
        has_magnitude some xsd:decimal[>= low, <= high] and has_value_unit some UO))``.  A missing
        lower bound ("up to 1 m") leaves the merged range open below.
        """

        g = Graph()
        nodes = _Nodes()
        attributes = _load_attributes(Path("config/pato_lexicon.tsv"))
        for (taxon_iri, bearer, attribute), members in sorted(self.numeric.items()):
            if len(members) < 2:
                continue
            units = Counter(m["uo"] for m in members)
            uo = units.most_common(1)[0][0]
            factor = {m["uo"]: UNIT_FACTOR[m["uo"]] / UNIT_FACTOR[uo] for m in members}
            lows = [None if m["low"] is None else float(m["low"]) * factor[m["uo"]] for m in members]
            highs = [None if m["high"] is None else float(m["high"]) * factor[m["uo"]] for m in members]
            low = None if any(v is None for v in lows) else round(min(lows), 6)
            high = None if any(v is None for v in highs) else round(max(highs), 6)
            if low is None and high is None:
                continue
            assertion = {
                "po_id": bearer, "pato_id": attribute, "value_terms": [], "value_operator": "atomic",
                "value_low": low, "value_high": high, "value_low_inclusive": True,
                "value_high_inclusive": True, "unit": UNIT_LABELS[uo], "negated": False,
            }
            fac = URIRef(annotation_class_iri(assertion))
            expression, _numeric, _seasonal, _disjunctive = _phenotype_expression(g, nodes, assertion, attributes)
            g.add((fac, RDF.type, OWL.Class))
            g.add((fac, OWL.equivalentClass, expression))
            taxon = URIRef(taxon_iri)
            g.add((taxon, RDF.type, OWL.Class))
            g.add((taxon, RDFS.subClassOf, _some(g, nodes, HAS_PHENOTYPE, fac)))
            node = URIRef(BASE + "saudi-flora/merged/" + _digest(taxon_iri, bearer, attribute))
            g.add((node, RDF.type, FB.MergedTrait))
            g.add((node, FB.taxon, taxon))
            g.add((node, FB.bearer, URIRef(iri(bearer))))
            g.add((node, FB.attribute, URIRef(iri(attribute))))
            g.add((node, FB.phenotypeClass, fac))
            g.add((node, FB.unit, URIRef(iri(uo))))
            g.add((node, FB.unitSymbol, Literal(UNIT_LABELS[uo])))
            for prop, value in ((FB.low, low), (FB.high, high)):
                if value is not None:
                    g.add((node, prop, Literal(value, datatype=XSD.decimal)))
            fmt = lambda v: f"{v:g}"  # noqa: E731
            shown = (f"{fmt(low)}–{fmt(high)}" if low is not None and high is not None and low != high
                     else f"up to {fmt(high)}" if low is None else f"at least {fmt(low)}" if high is None else fmt(low))
            label = f"{self.vocab.label(bearer)} {self.vocab.label(attribute)} {shown} {UNIT_LABELS[uo]}"
            g.add((node, RDFS.label, Literal(label)))
            for member in members:
                g.add((node, FB.member, member["record"]))
                g.add((node, URIRef("http://www.w3.org/ns/prov#wasDerivedFrom"), member["record"]))
            g.add((node, FB.sourceCount, Literal(len({str(m["source"]) for m in members}))))
            self.used_terms.update({curie(bearer), curie(attribute), curie(uo)})
        return g

    # ------------------------------------------------------------------ shared graphs
    def taxa_graph(self) -> Graph:
        g = Graph()
        for taxon_iri, info in self.taxa.items():
            t = URIRef(taxon_iri)
            g.add((t, RDF.type, FB.Taxon))
            g.add((t, RDFS.label, Literal(info["label"])))
            if info["authorship"]:
                g.add((t, FB.authorship, Literal(info["authorship"])))
            if info["family"]:
                g.add((t, FB.family, Literal(info["family"])))
            if info["order"]:
                g.add((t, FB.order, Literal(info["order"])))
            if info["wfo"]:
                g.add((t, FB.wfo, Literal(info["wfo"])))
                g.add((t, SKOS.exactMatch, URIRef("https://list.worldfloraonline.org/" + info["wfo"])))
            for (source, name), entry in info["names"].items():
                node = URIRef(taxon_iri.replace("/taxon/", "/taxon-name/", 1) + "/" + source + "/" + _digest(name)[:8])
                g.add((t, FB.printedName, node))
                g.add((node, FB.name, Literal(name)))
                g.add((node, FB.source, URIRef(BASE + "saudi-flora/source/" + source)))
                if entry["status"]:
                    g.add((node, FB.nameStatus, Literal(entry["status"])))
                for page in sorted(entry["pages"], key=lambda p: int(p) if p.isdigit() else 0):
                    g.add((node, FB.page, Literal(page)))
            extra = info["extra"]
            for name in extra.get("vernacular_ar", ()):
                g.add((t, FB.vernacularName, Literal(name, lang="ar")))
            for text in extra.get("native_range", ()):
                g.add((t, FB.nativeRange, Literal(text)))
            for prop, key in ((FB.abundance, "abundance"), (FB.habitat, "habitat")):
                for source, text in extra.get(key, ()):
                    node = URIRef(f"{taxon_iri}/{key}/{source}/{_digest(text)[:8]}")
                    g.add((t, prop, node))
                    g.add((node, RDFS.label, Literal(text)))
                    g.add((node, FB.source, URIRef(BASE + "saudi-flora/source/" + source)))
            metres = extra.get("elevation_m")
            if metres:
                g.add((t, FB.elevationMin, Literal(min(metres))))
                g.add((t, FB.elevationMax, Literal(max(metres))))
        return g

    def vocab_graph(self) -> Graph:
        g = Graph()
        for term in sorted(self.used_terms):
            if not term or ":" not in term:
                continue
            node = URIRef(iri(term))
            if term.startswith("UO:"):
                local = term.replace(":", "_")
                g.add((node, RDFS.label, Literal(UO_NAMES.get(local, term))))
                g.add((node, FB.symbol, Literal(UNIT_LABELS.get(local, ""))))
                g.add((node, FB.curie, Literal(term)))
                continue
            g.add((node, RDFS.label, Literal(self.vocab.label(term))))
            g.add((node, FB.curie, Literal(term)))
            if term.startswith("PO:") or self.vocab.organ_group(term) != "other" and term.startswith("FLOPO:"):
                g.add((node, FB.organGroup, FB["organ-" + self.vocab.organ_group(term)]))
            if term.startswith(("PATO:", "FLOPO:098")):
                g.add((node, FB.traitGroup, FB["trait-" + self.vocab.trait_group(term)]))
        for order, (key, label, _roots) in enumerate([*ORGAN_GROUPS, ("other", "Other parts", [])]):
            g.add((FB["organ-" + key], RDF.type, FB.OrganGroup))
            g.add((FB["organ-" + key], RDFS.label, Literal(label)))
            g.add((FB["organ-" + key], FB.order, Literal(order)))
        for order, (key, label, _roots) in enumerate([*TRAIT_GROUPS, ("other", "Other qualities", [])]):
            g.add((FB["trait-" + key], RDF.type, FB.TraitGroup))
            g.add((FB["trait-" + key], RDFS.label, Literal(label)))
            g.add((FB["trait-" + key], FB.order, Literal(order)))
        for code, name in REGIONS.items():
            g.add((URIRef(REGION + code), RDF.type, FB.Region))
            g.add((URIRef(REGION + code), RDFS.label, Literal(name)))
            g.add((URIRef(REGION + code), SKOS.notation, Literal(code)))
        for key, cfg in SOURCES.items():
            node = URIRef(BASE + "saudi-flora/source/" + key)
            g.add((node, RDF.type, FB.Source))
            g.add((node, DCTERMS.title, Literal(cfg["title"])))
            g.add((node, RDFS.label, Literal(cfg["short"])))
        return g

    # ------------------------------------------------------------------ main
    def build(self, sources: list[str], rebuild_assertions: bool = False) -> dict:
        rdf = self.out / "rdf"
        rdf.mkdir(parents=True, exist_ok=True)
        names = []
        for key in sources:
            cfg = SOURCES[key]
            for line in cfg["corpus"].open(encoding="utf-8"):
                names.append(json.loads(line)["taxon"])
            if key == "ncvc":
                with cfg["distribution"].open(encoding="utf-8") as handle:
                    names += [r["taxon"] for r in csv.DictReader(handle, delimiter="\t")]
                with cfg["growth"].open(encoding="utf-8") as handle:
                    names += [r["taxon"] for r in csv.DictReader(handle, delimiter="\t")]
                with cfg["taxa"].open(encoding="utf-8") as handle:
                    names += [r["scientific_name"] for r in csv.DictReader(handle, delimiter="\t")]
            if key == "collenette":
                names += [json.loads(line)["taxon"] for line in cfg["raw_jsonl"].open(encoding="utf-8")]
        self.resolve_names(sorted(set(names)))

        files = {}
        for key in sources:
            cfg = SOURCES[key]
            # Shared taxon IRIs: the assertion module uses record["taxon_iri"] as the taxon class.
            tagged = rdf / f"{key}-corpus-tagged.jsonl"
            lines = []
            with cfg["corpus"].open(encoding="utf-8") as src:
                for line in src:
                    record = json.loads(line)
                    record["taxon_iri"] = str(self.taxon(record["taxon"], key))
                    lines.append(json.dumps(record, ensure_ascii=False) + "\n")
            content = "".join(lines)
            # Rewrite only on change: the assertion module (minutes to build) follows its mtime.
            if not tagged.exists() or tagged.read_text(encoding="utf-8") != content:
                tagged.write_text(content, encoding="utf-8")
            assertions = rdf / f"{key}-assertions.ttl"
            if rebuild_assertions or not assertions.exists() or assertions.stat().st_mtime < tagged.stat().st_mtime:
                # Embed each annotation class's OWL definition: negation as ObjectComplementOf,
                # numeric values as xsd:decimal ranges with UO units.
                build_assertion_ontology(
                    tagged, assertions, version="saudi-flora", output_format="turtle",
                    embed_annotation_classes=True,
                )
            files[f"{key}/assertions"] = assertions

            index = Graph()
            counts = self.index_corpus(key, cfg["corpus"], index)
            places = Graph()
            if key == "ncvc":
                counts["occurrences"] = self.ncvc_places(cfg, places)
                counts["growth_traits"] = self.ncvc_extras(cfg, index)
            else:
                counts["occurrences"] = self.collenette_extras(cfg, places)
            counts.update(_disposition_counts(cfg["dispositions"]))
            for name, graph in ((f"{key}/index", index), (f"{key}/places", places)):
                path = rdf / f"{name.replace('/', '-')}.nt"
                graph.serialize(path, format="nt", encoding="utf-8")
                files[name] = path
            self.summary[key] = dict(counts)
        merged = self.merged_graph()
        self.summary["merged_ranges"] = len(set(merged.subjects(RDF.type, FB.MergedTrait)))
        for name, graph in (("merged", merged), ("taxa", self.taxa_graph()), ("vocab", self.vocab_graph())):
            path = rdf / f"{name}.nt"
            graph.serialize(path, format="nt", encoding="utf-8")
            files[name] = path
        manifest = {name: {"graph": GRAPH + name, "file": str(path)} for name, path in files.items()}
        (self.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        self.summary["taxa"] = {
            "taxa": len(self.taxa),
            "with_wfo": sum(bool(i["wfo"]) for i in self.taxa.values()),
            "families": len({i["family"] for i in self.taxa.values() if i["family"]}),
            "per_source": {
                key: sum(any(s == key for s, _ in i["names"]) for i in self.taxa.values()) for key in sources
            },
            "in_all_sources": sum(len({s for s, _ in i["names"]}) == len(sources) for i in self.taxa.values()),
        }
        (self.out / "summary.json").write_text(json.dumps(self.summary, indent=1) + "\n")
        return self.summary


def _disposition_counts(path: Path) -> Counter:
    """Phenotype rows the transcription produced vs. rows that became formal assertions."""

    counts: Counter = Counter()
    if not path.exists():
        return counts
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            counts["phenotype_rows"] += 1
            if row["status"] in {"accepted", "review", "held", "blocked"}:
                counts["rows_formalized"] += 1
    return counts


def _sentence(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind(";", 0, start)) + 1
    right_candidates = [i for i in (text.find(".", end), text.find(";", end)) if i != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()


def _gazetteer() -> dict[str, dict]:
    """English place name -> region and point, from the NCVC gazetteer (GeoNames/Wikidata)."""

    out: dict[str, dict] = {}
    path = Path("local-corpora/saudi-ncvc-guide/gazetteer.tsv")
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            names = {row.get("name_en_canonical", ""), row.get("name_en", "")}
            for name in filter(None, names):
                if row.get("lat") and row.get("lon"):
                    out.setdefault(
                        name.lower(),
                        {"lat": row["lat"], "lon": row["lon"], "region": row.get("admin1_iso_3166_2", "")},
                    )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sources", nargs="+", default=list(SOURCES))
    parser.add_argument("--rebuild-assertions", action="store_true")
    args = parser.parse_args(argv)
    available = [s for s in args.sources if SOURCES[s]["corpus"].exists()]
    print(json.dumps(Builder().build(available, args.rebuild_assertions), indent=1))


if __name__ == "__main__":
    main()
