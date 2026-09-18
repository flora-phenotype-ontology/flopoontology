"""GeoSPARQL-style competency queries, runnable with rdflib.

rdflib has no GeoSPARQL function library, so :func:`register_geof` adds a minimal
``geof:sfWithin`` (POINT within an axis-aligned POLYGON envelope, CRS84) for Q5.  Topological
queries (Q1-Q4) use the asserted ``geo:sfWithin`` relations, which a GeoSPARQL 1.1 store would
also answer by its query-rewrite extension.
"""

from __future__ import annotations

import re

from rdflib import Graph, Literal, URIRef
from rdflib.plugins.sparql.operators import register_custom_function

PREFIXES = """
PREFIX geo: <http://www.opengis.net/ont/geosparql#>
PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
PREFIX gn: <http://www.geonames.org/ontology#>
PREFIX gnc: <https://www.geonames.org/ontology#>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX dwc: <http://rs.tdwg.org/dwc/terms/>
PREFIX dwciri: <http://rs.tdwg.org/dwc/iri/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX prov: <http://www.w3.org/ns/prov#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX flopogeo: <https://w3id.org/flopo/geo#>
"""

COMPETENCY = {
    "Q1_taxa_in_asir": (
        "Taxa recorded in Asir (SA-14): at the region itself or at any feature geo:sfWithin it.",
        """
SELECT ?taxon (COUNT(DISTINCT ?occ) AS ?n) (GROUP_CONCAT(DISTINCT ?basis; separator="|") AS ?bases)
WHERE {
  ?asir wdt:P300 "SA-14" .
  ?occ a dwc:Occurrence ; dwc:scientificName ?taxon ; dcterms:spatial ?f ;
       flopogeo:basis ?basis ; dwc:occurrenceStatus "present" .
  ?f geo:sfWithin* ?asir .
} GROUP BY ?taxon ORDER BY DESC(?n) ?taxon
""",
    ),
    "Q2_localities_within_SA-09": (
        "Features geo:sfWithin Jazan (SA-09) with their GeoNames/Wikidata ids and WKT.",
        """
SELECT ?f ?label ?type ?wkt WHERE {
  ?r wdt:P300 "SA-09" .
  ?f geo:sfWithin ?r ; rdfs:label ?label ; flopogeo:featureType ?type .
  OPTIONAL { ?f geo:hasDefaultGeometry/geo:asWKT ?wkt }
} ORDER BY ?label
""",
    ),
    "Q3_conflicts_stated_vs_geonames_adm1": (
        "Occurrences whose stated region differs from the ADM1 the locality is sfWithin.",
        """
SELECT ?taxon ?locality ?stated ?adm1 WHERE {
  ?occ dcterms:spatial ?f ; dwc:scientificName ?taxon ; flopogeo:statedRegion ?s .
  ?f geo:sfWithin ?a ; rdfs:label ?locality .
  ?a gn:featureCode gnc:A.ADM1 ; wdt:P300 ?adm1 .
  ?s wdt:P300 ?stated .
  FILTER (?s != ?a)
} ORDER BY ?locality ?taxon
""",
    ),
    "Q4_taxa_per_region_by_basis": (
        "Distinct taxa per Saudi ADM1 region split by basis (stated/inferred/gazetteer).",
        """
SELECT ?iso ?basis (COUNT(DISTINCT ?taxon) AS ?taxa) WHERE {
  ?r gn:featureCode gnc:A.ADM1 ; wdt:P300 ?iso .
  ?occ dcterms:spatial ?r ; dwc:scientificName ?taxon ; flopogeo:basis ?basis .
} GROUP BY ?iso ?basis ORDER BY ?iso ?basis
""",
    ),
    "Q5_taxa_in_bbox_geof": (
        "Taxa at point localities whose WKT lies in the envelope 41-44E, 16-19N (geof:sfWithin).",
        """
SELECT DISTINCT ?taxon ?label ?wkt WHERE {
  ?occ dcterms:spatial ?f ; dwc:scientificName ?taxon .
  ?f rdfs:label ?label ; geo:hasDefaultGeometry/geo:asWKT ?wkt ;
     flopogeo:featureType ?t .
  FILTER (?t NOT IN ("admin1", "country", "continent"))
  FILTER (geof:sfWithin(?wkt,
     "POLYGON ((41 16, 44 16, 44 19, 41 19, 41 16))"^^geo:wktLiteral))
} ORDER BY ?label ?taxon
""",
    ),
}

FLORML = {
    "F1_taxa_in_gabon": (
        "Taxa recorded in Gabon or in any feature geo:sfWithin Gabon, by FLOPO status.",
        """
SELECT ?status (COUNT(DISTINCT ?taxon) AS ?taxa) (COUNT(?occ) AS ?n) WHERE {
  ?ga gn:countryCode "GA" ; gn:featureCode gnc:A.PCLI .
  ?occ dcterms:spatial ?f ; dwc:scientificName ?taxon ; flopogeo:occurrenceStatus ?status .
  ?f geo:sfWithin* ?ga .
} GROUP BY ?status ORDER BY DESC(?n)
""",
    ),
    "F2_occurrences_per_continent": (
        "Occurrences per GeoNames continent, following geo:sfWithin transitively.",
        """
SELECT ?continent (COUNT(?occ) AS ?n) WHERE {
  ?c gn:featureCode gnc:L.CONT ; rdfs:label ?continent .
  ?occ dcterms:spatial ?f .
  ?f geo:sfWithin* ?c .
} GROUP BY ?continent ORDER BY DESC(?n)
""",
    ),
    "F3_introduced_or_cultivated_by_country": (
        "Introduced/naturalised/cultivated records on resolved countries (DwC establishmentMeans IRI).",
        """
SELECT ?country ?em (COUNT(?occ) AS ?n) WHERE {
  ?occ dcterms:spatial ?f ; dwciri:establishmentMeans ?em .
  ?f gn:featureCode gnc:A.PCLI ; rdfs:label ?country .
  FILTER (?em = <http://rs.tdwg.org/dwcem/values/e003>)
} GROUP BY ?country ?em ORDER BY DESC(?n)
""",
    ),
}

_POINT = re.compile(r"^\s*POINT\s*\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)\s*$", re.I)
_POLY = re.compile(r"^\s*POLYGON\s*\(\((.*)\)\)\s*$", re.I)
_REGISTERED = False


def _sf_within(a: Literal, b: Literal) -> Literal:
    """POINT within the envelope of a POLYGON (sufficient for axis-aligned boxes)."""
    pa, pb = _POINT.match(str(a)), _POLY.match(str(b))
    if not pa or not pb:
        return Literal(False)
    x, y = float(pa.group(1)), float(pa.group(2))
    coords = [tuple(float(v) for v in c.split()) for c in pb.group(1).split(",")]
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return Literal(min(xs) < x < max(xs) and min(ys) < y < max(ys))


def register_geof() -> None:
    global _REGISTERED
    if not _REGISTERED:
        register_custom_function(
            URIRef("http://www.opengis.net/def/function/geosparql/sfWithin"), _sf_within
        )
        _REGISTERED = True


def run(graph: Graph, name: str) -> list[tuple[str, ...]]:
    register_geof()
    _desc, query = {**COMPETENCY, **FLORML}[name]
    return [
        tuple("" if v is None else str(v) for v in row) for row in graph.query(PREFIXES + query)
    ]
