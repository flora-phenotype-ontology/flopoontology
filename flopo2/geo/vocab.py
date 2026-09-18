"""Namespaces and controlled-value mappings for FLOPO taxon occurrence assertions.

Every external IRI below was checked against a pinned copy of the defining document under
``scratchpad/geo-occurrence-20260918/evidence/`` (see ``SHA256SUMS`` there):

* OGC GeoSPARQL 1.1 (``geosparql11_geo.ttl``, versionIRI ``http://www.opengis.net/ont/geosparql/1.1``)
  and the Simple Features geometry vocabulary (``geosparql11_sf_geometries.ttl``).
* GeoNames ontology v3.3 (``geonames_ontology_v3.3.rdf``) and live feature RDF
  (``geonames_features/*.rdf``).  Live GeoNames data uses the ``http://www.geonames.org/ontology#``
  namespace for properties and ``gn:Feature`` while feature-code individuals and feature IRIs are
  published under ``https``; we reproduce the published data exactly (see DESIGN.md §3).
* Darwin Core term list (``dwc_terms_current.csv``), the dwciri list (``dwciri_terms.csv``), the
  TDWG establishmentMeans / degreeOfEstablishment vocabularies and the GBIF occurrence-status
  and basis-of-record vocabularies.
"""

from __future__ import annotations

# --- namespaces ---------------------------------------------------------------------------
GEO = "http://www.opengis.net/ont/geosparql#"
SF = "http://www.opengis.net/ont/sf#"
GN = "http://www.geonames.org/ontology#"  # property / class namespace used by GeoNames data
GN_CODE = "https://www.geonames.org/ontology#"  # namespace of published feature-code individuals
GN_FEATURE = "https://sws.geonames.org/"  # feature IRIs: <GN_FEATURE><id>/ (Wikidata P1921)
WD = "http://www.wikidata.org/entity/"
DWC = "http://rs.tdwg.org/dwc/terms/"
DWCIRI = "http://rs.tdwg.org/dwc/iri/"
DWCEM = "http://rs.tdwg.org/dwcem/values/"
DWCDOE = "http://rs.tdwg.org/dwcdoe/values/"
GBIF_OS = "http://rs.gbif.org/vocabulary/gbif/occurrence_status/"
DCTERMS = "http://purl.org/dc/terms/"
PROV = "http://www.w3.org/ns/prov#"
SKOS = "http://www.w3.org/2004/02/skos/core#"
OA = "http://www.w3.org/ns/oa#"
WGS84 = "http://www.w3.org/2003/01/geo/wgs84_pos#"

# FLOPO-minted resources.  Local (unresolved) features reuse the geographic-context base already
# used by ``flopo2.owl.annotation_class`` so annotation classes and occurrences share place IRIs.
GEOGRAPHIC_CONTEXT = "https://w3id.org/flopo/geographic-context/"
FLOPO_GEOMETRY = "https://w3id.org/flopo/geometry/"
FLOPO_OCCURRENCE = "https://w3id.org/flopo/occurrence/"
FLOPO_STATEMENT = "https://w3id.org/flopo/source-statement/"
FLOPO_TAXON_NAME = "https://w3id.org/flopo/taxon-name/"
FLOPOGEO = "https://w3id.org/flopo/geo#"  # small local vocabulary for terms with no standard

WGS84_CRS = "http://www.opengis.net/def/crs/OGC/1.3/CRS84"

# --- controlled values ----------------------------------------------------------------------
BASIS = ("stated", "inferred", "gazetteer")
OCCURRENCE_STATUS = ("present", "absent", "doubtful", "expected", "excluded", "extinct")
ESTABLISHMENT_MEANS = (
    "native",
    "introduced",
    "naturalised",
    "cultivated",
    "uncertain",
    "unspecified",
)
ABUNDANCE = ("rare", "occasional", "common", "widespread", "unspecified")
EPISTEMIC_MODALITY = ("asserted", "probable", "possible", "uncertain", "reported")
FEATURE_TYPES = (
    "world",
    "continent",
    "continental_region",
    "oceanic_region",
    "country",
    "admin1",
    "admin2",
    "governorate",
    "region",
    "locality",
    "city",
    "town",
    "village",
    "mountain",
    "wadi",
    "natural_region",
    "desert",
    "island",
    "archipelago",
    "peninsula",
    "coast",
    "plateau",
    "park",
    "harrah",
    "other",
)

# GBIF occurrence_status vocabulary (identifiers verified in gbif_occurrence_status.xml).
GBIF_OCCURRENCE_STATUS = (
    "present",
    "common",
    "rare",
    "irregular",
    "doubtful",
    "absent",
    "excluded",
)

# TDWG establishmentMeans concept IRIs (tdwg_establishmentMeans.csv).
DWC_ESTABLISHMENT_MEANS = {
    "native": "e001",
    "nativeReintroduced": "e002",
    "introduced": "e003",
    "introducedAssistedColonisation": "e004",
    "vagrant": "e005",
    "uncertain": "e006",
    "nativeEndemic": "e007",
}
# TDWG degreeOfEstablishment concept IRIs (tdwg_degreeOfEstablishment.csv).
DWC_DEGREE_OF_ESTABLISHMENT = {
    "native": "d001",
    "captive": "d002",
    "cultivated": "d003",
    "released": "d004",
    "failing": "d005",
    "casual": "d006",
    "reproducing": "d007",
    "established": "d008",
    "colonising": "d009",
    "invasive": "d010",
    "widespreadInvasive": "d011",
}


def gbif_occurrence_status(status: str, abundance: str = "unspecified") -> tuple[str, str]:
    """Map a FLOPO occurrence status to (dwc:occurrenceStatus, GBIF vocabulary value).

    Darwin Core recommends ``present``/``absent`` for dwc:occurrenceStatus; the GBIF vocabulary
    refines presence (common/rare) and adds doubtful/excluded.  ``expected`` and ``extinct`` have
    no standard value: expected -> doubtful, extinct -> absent (both keep a remark).  Doubtful and
    expected records leave dwc:occurrenceStatus empty rather than claim presence.
    """
    if status in {"absent", "extinct", "excluded"}:
        dwc = "absent"
    elif status in {"doubtful", "expected"}:
        dwc = ""
    else:
        dwc = "present"
    if status == "present":
        gbif = abundance if abundance in {"common", "rare"} else "present"
    elif status == "expected":
        gbif = "doubtful"
    elif status == "extinct":
        gbif = "absent"
    else:
        gbif = status
    if gbif not in GBIF_OCCURRENCE_STATUS:
        raise ValueError(f"unmapped occurrence status {status!r}")
    return dwc, gbif


def dwc_establishment(establishment: str, endemic: bool) -> tuple[str, str]:
    """Map FLOPO establishment means to (dwc:establishmentMeans, dwc:degreeOfEstablishment)."""
    if establishment == "native":
        return ("nativeEndemic" if endemic else "native"), "native"
    if endemic and establishment == "unspecified":
        return "nativeEndemic", "native"
    return {
        "introduced": ("introduced", ""),
        "naturalised": ("introduced", "established"),
        "cultivated": ("introduced", "cultivated"),
        "uncertain": ("uncertain", ""),
        "unspecified": ("", ""),
    }[establishment]
