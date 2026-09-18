"""Darwin Core (dwc:Occurrence) CSV view of occurrence assertions.

Flora distribution statements are literature-derived, so ``basisOfRecord`` is the generic
``Occurrence`` (GBIF basis_of_record vocabulary).  Coordinates are exported only for point-like
features whose geometry is the feature's own; area features (ADM1, countries, continents,
regions) and anchor-derived points get ``locationID``/``higherGeographyID`` instead of a
misleading centroid.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from pathlib import Path

from flopo2.geo import vocab
from flopo2.geo.gazetteer import countries, sa_regions
from flopo2.geo.models import OccurrenceAssertion

DWC_COLUMNS = [
    "occurrenceID",
    "basisOfRecord",
    "scientificName",
    "taxonID",
    "taxonRank",
    "family",
    "occurrenceStatus",
    "establishmentMeans",
    "degreeOfEstablishment",
    "locationID",
    "higherGeographyID",
    "country",
    "countryCode",
    "stateProvince",
    "locality",
    "verbatimLocality",
    "decimalLatitude",
    "decimalLongitude",
    "geodeticDatum",
    "georeferenceProtocol",
    "georeferenceSources",
    "georeferenceRemarks",
    "occurrenceRemarks",
    "associatedReferences",
]

AREA_TYPES = {
    "world",
    "continent",
    "continental_region",
    "oceanic_region",
    "country",
    "admin1",
    "admin2",
    "governorate",
    "region",
    "natural_region",
    "desert",
    "coast",
    "harrah",
    "plateau",
}


def dwc_row(occ: OccurrenceAssertion) -> dict[str, str]:
    place = occ.place
    regions = sa_regions()
    region = regions.get(place.iso_3166_2 or place.admin1_iso_3166_2)
    country = countries().get(place.country_code)
    dwc_status, gbif_status = vocab.gbif_occurrence_status(occ.occurrence_status, occ.abundance)
    em, doe = vocab.dwc_establishment(occ.establishment_means, occ.endemic)
    lat = lon = ""
    geo_remarks = []
    if place.geometry is not None:
        if place.geometry.anchor_note:
            geo_remarks.append(f"relative locality; anchor point {place.geometry.wkt} not exported")
        elif place.feature_type in AREA_TYPES:
            geo_remarks.append(f"area feature; representative point {place.geometry.wkt}")
        else:
            lon, lat = place.geometry.wkt[7:-1].split()
    remarks = [f"basis={occ.basis}"]
    if occ.occurrence_status != dwc_status:
        remarks.append(f"flopo occurrenceStatus={occ.occurrence_status} (GBIF: {gbif_status})")
    if occ.abundance != "unspecified":
        remarks.append(f"abundance={occ.abundance}")
    if occ.endemic:
        remarks.append("endemic")
    if occ.extralimital:
        remarks.append("extralimital")
    if occ.epistemic_modality != "asserted":
        remarks.append(f"epistemic={occ.epistemic_modality}")
    if occ.status_text:
        remarks.append(f"status cue: {occ.status_text}")
    if occ.conflict:
        remarks.append(f"CONFLICT: {occ.conflict_note}")
    if occ.stated_region:
        remarks.append(f"stated region {occ.stated_region} ({occ.stated_region_basis})")
    higher = ""
    if place.within:
        higher = place.within[0]
    return {
        "occurrenceID": occ.iri,
        "basisOfRecord": "Occurrence",
        "scientificName": occ.taxon_name,
        "taxonID": occ.taxon_id,
        "taxonRank": occ.taxon_rank,
        "family": occ.taxon_family,
        "occurrenceStatus": dwc_status,
        "establishmentMeans": em,
        "degreeOfEstablishment": doe,
        "locationID": place.feature_iri,
        "higherGeographyID": higher,
        "country": country.label if country else "",
        "countryCode": place.country_code,
        "stateProvince": region.label if region else "",
        "locality": "" if place.feature_type in AREA_TYPES else place.label,
        "verbatimLocality": occ.place_text,
        "decimalLatitude": lat,
        "decimalLongitude": lon,
        "geodeticDatum": "EPSG:4326" if lat else "",
        "georeferenceProtocol": "FLOPO flopo2.geo gazetteer join (GeoNames/Wikidata)"
        if place.resolved or place.same_as
        else "",
        "georeferenceSources": place.gazetteer,
        "georeferenceRemarks": "; ".join(geo_remarks),
        "occurrenceRemarks": "; ".join(remarks),
        "associatedReferences": f"{occ.source}: {occ.source_id}",
    }


def write_csv(occurrences: Iterable[OccurrenceAssertion], path: Path) -> int:
    n = 0
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=DWC_COLUMNS)
        w.writeheader()
        for occ in occurrences:
            w.writerow(dwc_row(occ))
            n += 1
    return n
