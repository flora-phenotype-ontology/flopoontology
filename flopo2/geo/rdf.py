"""RDF (Turtle) export: GeoSPARQL features + Darwin Core occurrences + provenance."""

from __future__ import annotations

from collections.abc import Iterable

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from flopo2.geo import vocab
from flopo2.geo.models import OccurrenceAssertion, Place, digest

GEO = Namespace(vocab.GEO)
SF = Namespace(vocab.SF)
GN = Namespace(vocab.GN)
GNC = Namespace(vocab.GN_CODE)
WD = Namespace(vocab.WD)
WDT = Namespace("http://www.wikidata.org/prop/direct/")
DWC = Namespace(vocab.DWC)
DWCIRI = Namespace(vocab.DWCIRI)
DWCEM = Namespace(vocab.DWCEM)
DWCDOE = Namespace(vocab.DWCDOE)
GBIFOS = Namespace(vocab.GBIF_OS)
DCTERMS = Namespace(vocab.DCTERMS)
PROV = Namespace(vocab.PROV)
OA = Namespace(vocab.OA)
FG = Namespace(vocab.FLOPOGEO)
GEOF = Namespace("http://www.opengis.net/def/function/geosparql/")

# Local vocabulary: only for notions with no standard term (documented in DESIGN.md §4).
LOCAL_TERMS = {
    "OccurrenceAssertion": ("Class", "A flora statement that a taxon occurs (or not) in a place."),
    "SourceStatement": ("Class", "A verbatim source text span an assertion was extracted from."),
    "featureType": ("DatatypeProperty", "FLOPO feature type (continent, country, admin1, ...)."),
    "basis": ("DatatypeProperty", "stated | inferred | gazetteer."),
    "occurrenceStatus": ("DatatypeProperty", "FLOPO occurrence status (finer than DwC)."),
    "establishmentMeans": ("DatatypeProperty", "FLOPO establishment means."),
    "endemic": ("DatatypeProperty", "Source states the taxon is endemic to the place."),
    "extralimital": ("DatatypeProperty", "Place lies outside the flora area (FlorML extra)."),
    "abundance": ("DatatypeProperty", "rare | occasional | common | widespread | unspecified."),
    "epistemicModality": (
        "DatatypeProperty",
        "asserted | probable | possible | uncertain | reported.",
    ),
    "statusText": ("DatatypeProperty", "Verbatim status/abundance cue."),
    "conflict": ("DatatypeProperty", "Stated region disagrees with the gazetteer ADM1."),
    "conflictNote": ("DatatypeProperty", "Explanation of the conflict."),
    "statedRegion": ("ObjectProperty", "ADM1 feature the source text attaches the place to."),
    "statedRegionBasis": ("DatatypeProperty", "stated | inferred."),
    "placeSelector": ("ObjectProperty", "oa:TextPositionSelector of the place mention."),
    "anchorFeature": ("ObjectProperty", "Anchor of a relative locality (10 km E of X)."),
    "coordinateSource": ("DatatypeProperty", "geonames | wikidata: origin of the point."),
    "approximate": ("DatatypeProperty", "Geometry is that of an anchor, not of the feature."),
    "resolutionConfidence": ("DatatypeProperty", "Gazetteer match confidence."),
    "gazetteer": ("DatatypeProperty", "Gazetteer/reference table (and version) used."),
    "extractor": ("DatatypeProperty", "Software that produced the assertion."),
    "mappingNote": ("DatatypeProperty", "Free-text mapping provenance."),
}


def new_graph() -> Graph:
    g = Graph()
    for prefix, ns in {
        "geo": GEO,
        "sf": SF,
        "gn": GN,
        "gnc": GNC,
        "wd": WD,
        "wdt": WDT,
        "dwc": DWC,
        "dwciri": DWCIRI,
        "dwcem": DWCEM,
        "dwcdoe": DWCDOE,
        "gbifos": GBIFOS,
        "dcterms": DCTERMS,
        "prov": PROV,
        "oa": OA,
        "flopogeo": FG,
        "skos": SKOS,
        "owl": OWL,
        "gnf": Namespace(vocab.GN_FEATURE),
        "fgc": Namespace(vocab.GEOGRAPHIC_CONTEXT),
        "fgeom": Namespace(vocab.FLOPO_GEOMETRY),
        "focc": Namespace(vocab.FLOPO_OCCURRENCE),
        "fst": Namespace(vocab.FLOPO_STATEMENT),
    }.items():
        g.bind(prefix, ns)
    for name, (kind, comment) in LOCAL_TERMS.items():
        g.add((FG[name], RDF.type, OWL[kind]))
        g.add((FG[name], RDFS.comment, Literal(comment, lang="en")))
    return g


def add_place(g: Graph, place: Place) -> URIRef:
    f = URIRef(place.feature_iri)
    if (f, RDF.type, GEO.Feature) in g:
        return f
    g.add((f, RDF.type, GEO.Feature))
    g.add((f, RDFS.label, Literal(place.label)))
    g.add((f, FG.featureType, Literal(place.feature_type)))
    for lang, name in place.names.items():
        if lang in {"ar", "en", "fr"}:
            g.add((f, SKOS.altLabel, Literal(name, lang=lang)))
    if place.resolved:
        g.add((f, RDF.type, GN.Feature))
        g.add((f, GN.name, Literal(place.label)))
        if place.geonames_feature_code:
            cls = place.geonames_feature_code.split(".")[0]
            g.add((f, GN.featureClass, GNC[cls]))
            g.add((f, GN.featureCode, GNC[place.geonames_feature_code]))
    if place.country_code:
        g.add((f, GN.countryCode, Literal(place.country_code)))
    if place.iso_3166_2:
        g.add((f, WDT.P300, Literal(place.iso_3166_2)))
    for iri in place.same_as:
        g.add((f, SKOS.exactMatch, URIRef(iri)))
        # owl:sameAs only where the Wikidata item was selected by its GeoNames id (P1566)
        if place.resolved and place.gazetteer.startswith("flopo-geo-reference"):
            g.add((f, OWL.sameAs, URIRef(iri)))
    for iri in place.anchor_iris:
        g.add((f, FG.anchorFeature, URIRef(iri)))
    for iri in place.within:
        g.add((f, GEO.sfWithin, URIRef(iri)))
        # mirror the containment in the GeoNames hierarchy for GeoNames features only
        if place.resolved and place.feature_type == "admin1":
            g.add((f, GN.parentCountry, URIRef(iri)))
        elif place.resolved and place.admin1_iso_3166_2 and place.feature_type != "country":
            g.add((f, GN.parentADM1, URIRef(iri)))
    if place.gazetteer:
        g.add((f, FG.gazetteer, Literal(place.gazetteer)))
    if place.resolution_confidence:
        g.add((f, FG.resolutionConfidence, Literal(place.resolution_confidence)))
    if place.geometry is not None:
        geom = URIRef(vocab.FLOPO_GEOMETRY + digest(place.feature_iri, place.geometry.wkt, n=20))
        g.add((f, GEO.hasGeometry, geom))
        if not place.geometry.anchor_note:
            g.add((f, GEO.hasDefaultGeometry, geom))
        g.add((geom, RDF.type, GEO.Geometry))
        g.add((geom, RDF.type, SF.Point))
        g.add((geom, GEO.asWKT, Literal(place.geometry.wkt, datatype=GEO.wktLiteral)))
        g.add((geom, FG.coordinateSource, Literal(place.geometry.source)))
        if place.geometry.anchor_note:
            g.add((geom, FG.approximate, Literal(True)))
            g.add((geom, RDFS.comment, Literal(place.geometry.anchor_note, lang="en")))
    return f


def add_occurrence(g: Graph, occ: OccurrenceAssertion, region_iris: dict[str, str]) -> URIRef:
    o = URIRef(occ.iri)
    f = add_place(g, occ.place)
    st = URIRef(vocab.FLOPO_STATEMENT + occ.source_statement_id)
    if (st, RDF.type, FG.SourceStatement) not in g:
        g.add((st, RDF.type, FG.SourceStatement))
        lang = occ.statement_language or None
        g.add((st, RDF.value, Literal(occ.statement_text, lang=lang)))
        g.add((st, DCTERMS.source, Literal(occ.source_id)))
        g.add((st, DCTERMS.isPartOf, Literal(occ.source)))
    g.add((o, RDF.type, DWC.Occurrence))
    g.add((o, RDF.type, FG.OccurrenceAssertion))
    g.add((o, DWC.occurrenceID, Literal(occ.occurrence_id)))
    g.add((o, DWC.basisOfRecord, Literal("Occurrence")))
    g.add((o, DWC.scientificName, Literal(occ.taxon_name)))
    if occ.taxon_id:
        g.add((o, DWC.taxonID, Literal(occ.taxon_id)))
    if occ.taxon_rank:
        g.add((o, DWC.taxonRank, Literal(occ.taxon_rank)))
    if occ.taxon_family:
        g.add((o, DWC.family, Literal(occ.taxon_family)))
    g.add((o, DCTERMS.spatial, f))
    g.add((o, PROV.wasDerivedFrom, st))
    for src in occ.derived_from:
        g.add((o, PROV.wasDerivedFrom, URIRef(vocab.FLOPO_OCCURRENCE + src)))
    if occ.place_text:
        lang = occ.statement_language or None
        g.add((o, DWC.verbatimLocality, Literal(occ.place_text, lang=lang)))
    if occ.place_start is not None:
        sel = BNode()
        g.add((o, FG.placeSelector, sel))
        g.add((sel, RDF.type, OA.TextPositionSelector))
        g.add((sel, OA.start, Literal(occ.place_start, datatype=XSD.nonNegativeInteger)))
        g.add((sel, OA.end, Literal(occ.place_end, datatype=XSD.nonNegativeInteger)))
    dwc_status, gbif_status = vocab.gbif_occurrence_status(occ.occurrence_status, occ.abundance)
    if dwc_status:
        g.add((o, DWC.occurrenceStatus, Literal(dwc_status)))
    g.add((o, DWCIRI.occurrenceStatus, GBIFOS[gbif_status]))
    em, doe = vocab.dwc_establishment(occ.establishment_means, occ.endemic)
    if em:
        g.add((o, DWC.establishmentMeans, Literal(em)))
        g.add((o, DWCIRI.establishmentMeans, DWCEM[vocab.DWC_ESTABLISHMENT_MEANS[em]]))
    if doe:
        g.add((o, DWC.degreeOfEstablishment, Literal(doe)))
        g.add((o, DWCIRI.degreeOfEstablishment, DWCDOE[vocab.DWC_DEGREE_OF_ESTABLISHMENT[doe]]))
    g.add((o, FG.basis, Literal(occ.basis)))
    g.add((o, FG.occurrenceStatus, Literal(occ.occurrence_status)))
    g.add((o, FG.establishmentMeans, Literal(occ.establishment_means)))
    g.add((o, FG.abundance, Literal(occ.abundance)))
    g.add((o, FG.epistemicModality, Literal(occ.epistemic_modality)))
    if occ.endemic:
        g.add((o, FG.endemic, Literal(True)))
    if occ.extralimital:
        g.add((o, FG.extralimital, Literal(True)))
    if occ.status_text:
        g.add((o, FG.statusText, Literal(occ.status_text)))
    if occ.stated_region and occ.stated_region in region_iris:
        g.add((o, FG.statedRegion, URIRef(region_iris[occ.stated_region])))
        g.add((o, FG.statedRegionBasis, Literal(occ.stated_region_basis)))
    g.add((o, FG.conflict, Literal(occ.conflict)))
    if occ.conflict_note:
        g.add((o, FG.conflictNote, Literal(occ.conflict_note, lang="en")))
    g.add((o, FG.extractor, Literal(occ.extractor)))
    for note in occ.mapping_notes:
        g.add((o, FG.mappingNote, Literal(note)))
    return o


def to_graph(occurrences: Iterable[OccurrenceAssertion]) -> Graph:
    from flopo2.geo.gazetteer import sa_regions

    regions = {iso: ref.place().feature_iri for iso, ref in sa_regions().items()}
    g = new_graph()
    for occ in occurrences:
        add_occurrence(g, occ, regions)
    add_containers(g)
    return g


def add_containers(g: Graph) -> None:
    """Materialise reference features (ADM1, countries, continents) that are sfWithin targets."""
    from flopo2.geo.gazetteer import continents, countries, sa_regions

    index = {}
    for table in (continents(), countries(), sa_regions()):
        for ref in table.values():
            place = ref.place()
            index[place.feature_iri] = place
    pending = {o for o in g.objects(None, GEO.sfWithin)} | {
        o for o in g.objects(None, FG.statedRegion)
    }
    while pending:
        iri = pending.pop()
        if (iri, RDF.type, GEO.Feature) in g or str(iri) not in index:
            continue
        place = index[str(iri)]
        add_place(g, place)
        pending.update(URIRef(w) for w in place.within)
