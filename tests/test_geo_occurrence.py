"""Tests for flopo2.geo: models, gazetteer join, FlorML parsing, RDF / DwC / SQL exports."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from flopo2.geo import dwc, queries, rdf, sql, vocab
from flopo2.geo.florml import iter_file, resolve_florml_place
from flopo2.geo.gazetteer import countries, ncvc_place, normalize_name, resolve_name, sa_regions
from flopo2.geo.models import (
    Geometry,
    OccurrenceAssertion,
    Place,
    geonames_iri,
    local_feature_iri,
    point_wkt,
)
from flopo2.geo.ncvc import iter_occurrences

GEO = "http://www.opengis.net/ont/geosparql#"
SOURCE = "ncvc-saudi-native-plants-guide-2024"
PAGE = f"{SOURCE}:page-015"
STATEMENT = "في منطقة جازان (صبيا، جزيرة فرسان)، ومنطقة عسير (رابغ)."


def _gaz_row(**kw: str) -> dict[str, str]:
    row = {
        "locality_key": "صبيا|sabya",
        "verbatim_ar": "صبيا",
        "name_en_canonical": "Sabya",
        "feature_type": "city",
        "geonames_id": "103922",
        "wikidata_qid": "Q1017330",
        "lat": "17.1495",
        "lon": "42.62537",
        "admin1_iso_3166_2": "SA-09",
        "stated_regions": "SA-09:p15",
        "conflict": "no",
        "resolution_source": "",
        "confidence": "high",
        "notes": "",
    }
    row.update(kw)
    return row


def _dist_row(level: str, **kw: str) -> dict[str, str]:
    row = {
        "source": SOURCE,
        "source_id": PAGE,
        "taxon": "Avicennia marina",
        "taxon_family": "Acanthaceae",
        "level": level,
        "iso_3166_2": "",
        "region_name": "",
        "locality_name": "",
        "feature_type": "",
        "basis": "",
        "verbatim_ar": "",
        "gaz_locality_key": "",
        "taxa_wfo_or_powo_id": "wfo-0000303022 | powo:x",
        "taxa_accepted_family": "Acanthaceae",
    }
    row.update(kw)
    return row


@pytest.fixture
def ncvc_occurrences() -> list[OccurrenceAssertion]:
    gaz = {
        "صبيا|sabya": _gaz_row(),
        "رابغ|rabigh": _gaz_row(
            locality_key="رابغ|rabigh",
            verbatim_ar="رابغ",
            name_en_canonical="Rābigh",
            geonames_id="103035",
            wikidata_qid="Q97291030",
            lat="22.798563",
            lon="39.03493",
            admin1_iso_3166_2="SA-02",
            conflict="yes",
        ),
        "جزيرة فرسان|farasan island": _gaz_row(
            locality_key="جزيرة فرسان|farasan island",
            verbatim_ar="جزيرة فرسان",
            name_en_canonical="10 km off Farasan",
            feature_type="island",
            geonames_id="107312",
            wikidata_qid="",
            notes="relative/sub-locality: IDs and coordinates are those of anchor",
        ),
    }
    rows = [
        _dist_row(
            "region",
            iso_3166_2="SA-09",
            region_name="Jazan",
            basis="stated",
            verbatim_ar="منطقة جازان",
        ),
        _dist_row(
            "region",
            iso_3166_2="SA-14",
            region_name="Asir",
            basis="stated",
            verbatim_ar="منطقة عسير",
        ),
        _dist_row(
            "locality",
            iso_3166_2="SA-09",
            locality_name="Sabya",
            feature_type="city",
            basis="stated",
            verbatim_ar="صبيا",
            gaz_locality_key="صبيا|sabya",
        ),
        _dist_row(
            "locality",
            iso_3166_2="SA-09",
            locality_name="Farasan",
            feature_type="island",
            basis="stated",
            verbatim_ar="جزيرة فرسان",
            gaz_locality_key="جزيرة فرسان|farasan island",
        ),
        _dist_row(
            "locality",
            iso_3166_2="SA-14",
            locality_name="Rabigh",
            feature_type="city",
            basis="stated",
            verbatim_ar="رابغ",
            gaz_locality_key="رابغ|rabigh",
        ),
    ]
    raw = {PAGE: {"ksa_distribution_ar": STATEMENT, "abundance_en": "rare"}}
    return list(iter_occurrences(rows, gaz, raw))


# --- reference tables ----------------------------------------------------------------------


def test_sa_regions_cover_all_thirteen_adm1_with_geonames_and_wikidata() -> None:
    regions = sa_regions()
    assert len(regions) == 13
    jazan = regions["SA-09"]
    assert (jazan.geonames_id, jazan.wikidata_id) == ("105298", "Q269973")
    assert jazan.within == (geonames_iri("102358"),)  # Saudi Arabia
    assert all(r.geonames_feature_code == "A.ADM1" for r in regions.values())


def test_country_and_alias_resolution() -> None:
    assert countries()["GA"].geonames_id == "2400553"
    assert countries()["GA"].wikidata_id == "Q1000"
    assert resolve_name("Zaïre").code == "CD"
    assert resolve_name("Côte-d'Ivoire").code == "CI"
    assert resolve_name("Laos").code == "LA"  # regression: article stripping ate "la"
    assert resolve_name("Afrique").kind == "continent"
    assert resolve_name("Rhodésie") is None  # ambiguous: deliberately unmapped
    assert normalize_name(" Côte d ' Ivoire. ") == "cote d'ivoire"


# --- models ------------------------------------------------------------------------------


def test_place_rejects_inconsistent_identity() -> None:
    with pytest.raises(ValidationError):
        Place(
            feature_iri="https://example.org/x",
            label="x",
            feature_type="city",
            resolved=True,
            geonames_id="1",
        )
    with pytest.raises(ValidationError):
        Place(
            feature_iri=local_feature_iri("s", "x"), label="x", feature_type="nope", resolved=False
        )
    with pytest.raises(ValidationError):
        Place(
            feature_iri=geonames_iri("105298"),
            label="J",
            feature_type="admin1",
            resolved=True,
            geonames_id="105298",
            country_code="YE",
            iso_3166_2="SA-09",
        )


def test_geometry_is_crs84_point() -> None:
    assert point_wkt("17.1495", "42.62537") == "POINT (42.62537 17.1495)"
    with pytest.raises(ValidationError):
        Geometry(wkt="POINT (200 10)", source="geonames")


def test_local_feature_iri_is_stable_and_scoped() -> None:
    a = local_feature_iri("florml|flora-gabon|region", "Nord  Gabon")
    assert a == local_feature_iri("florml|flora-gabon|region", "nord gabon")
    assert a != local_feature_iri("florml|flora-malesiana|region", "nord gabon")
    assert a.startswith(vocab.GEOGRAPHIC_CONTEXT)


# --- gazetteer join -----------------------------------------------------------------------


def test_ncvc_place_resolved_relative_and_wikidata_only() -> None:
    resolved = ncvc_place(_gaz_row())
    assert resolved.resolved and resolved.feature_iri == "https://sws.geonames.org/103922/"
    assert resolved.within == [geonames_iri("105298")]  # sfWithin Jazan from admin1 code
    assert resolved.geometry.wkt == "POINT (42.62537 17.1495)"
    relative = ncvc_place(_gaz_row(notes="relative/sub-locality: anchor Sabya"))
    assert not relative.resolved and relative.anchor_iris[0] == geonames_iri("103922")
    assert relative.within == [] and relative.geometry.anchor_note
    wd_only = ncvc_place(_gaz_row(geonames_id="", admin1_iso_3166_2=""))
    assert not wd_only.resolved and wd_only.same_as == [vocab.WD + "Q1017330"]


def test_ncvc_occurrences_offsets_conflict_and_gazetteer_basis(ncvc_occurrences) -> None:
    by_label = {(o.place.label, o.basis): o for o in ncvc_occurrences}
    sabya = by_label[("Sabya", "stated")]
    assert STATEMENT[sabya.place_start : sabya.place_end] == "صبيا"
    assert not sabya.conflict and sabya.abundance == "rare"
    rabigh = by_label[("Rābigh", "stated")]
    assert rabigh.conflict and "SA-14" in rabigh.conflict_note and "SA-02" in rabigh.conflict_note
    # Makkah (SA-02) is implied only by the gazetteer ADM1 of Rabigh
    derived = [o for o in ncvc_occurrences if o.basis == "gazetteer"]
    assert [o.place.iso_3166_2 for o in derived] == ["SA-02"]
    assert derived[0].derived_from == [rabigh.occurrence_id]
    assert len({o.occurrence_id for o in ncvc_occurrences}) == len(ncvc_occurrences)


def test_occurrence_rejects_non_verbatim_span(ncvc_occurrences) -> None:
    occ = ncvc_occurrences[0]
    data = occ.model_dump()
    data["place_start"] = 0
    data["place_end"] = 3
    with pytest.raises(ValidationError):
        OccurrenceAssertion(**data)


# --- FlorML -----------------------------------------------------------------------------

FLORML = """<?xml version="1.0" encoding="UTF-8"?>
<publication lang="fr"><treatment><taxon>
 <nomenclature><homotypes><nom class="accepted">
  <name class="family">Myrtaceae</name><name class="genus">Syzygium</name>
  <name class="species">jambos</name></nom></homotypes></nomenclature>
 <feature class="distribution"><string>Originaire d'<distributionLocality class="continent">Asie</distributionLocality>,
  introduit au <distributionLocality class="country" status="introduced">Gabon</distributionLocality>
  et au <distributionLocality class="region" doubtful="true">Nord-Ouest du Cameroun</distributionLocality>.
  Absent du <distributionLocality class="country" frequency="absent">Congo</distributionLocality>.</string>
 </feature></taxon></treatment></publication>
"""


def test_florml_elements_to_occurrences(tmp_path: Path) -> None:
    path = tmp_path / "t.xml"
    path.write_text(FLORML, encoding="utf-8")
    occ = list(iter_file(path, source="flora-test"))
    assert [o.place_text for o in occ] == ["Asie", "Gabon", "Nord-Ouest du Cameroun", "Congo"]
    for o in occ:
        assert o.statement_text[o.place_start : o.place_end] == o.place_text
        assert o.taxon_name == "Syzygium jambos"
    asia, gabon, nw_cameroon, congo = occ
    assert asia.place.feature_iri == geonames_iri("6255147")
    assert gabon.place.geonames_id == "2400553" and gabon.establishment_means == "introduced"
    assert not nw_cameroon.place.resolved
    assert nw_cameroon.place.within == [geonames_iri(countries()["CM"].geonames_id)]
    assert nw_cameroon.occurrence_status == "doubtful"
    assert congo.occurrence_status == "absent" and congo.place.country_code == "CG"


def test_florml_world_class_stays_local() -> None:
    place, _ = resolve_florml_place("monde entier", "world", "flora-gabon")
    assert not place.resolved and place.within == []


# --- exports -----------------------------------------------------------------------------


def test_rdf_export_parses_and_answers_competency_queries(ncvc_occurrences) -> None:
    g = rdf.to_graph(ncvc_occurrences)
    g2 = Graph().parse(data=g.serialize(format="turtle"), format="turtle")
    assert len(g2) == len(g)
    sabya = URIRef("https://sws.geonames.org/103922/")
    assert (sabya, RDF.type, URIRef(GEO + "Feature")) in g2
    assert (sabya, URIRef(GEO + "sfWithin"), URIRef(geonames_iri("105298"))) in g2
    # containers are materialised: Jazan sfWithin Saudi Arabia sfWithin Asia
    assert (
        URIRef(geonames_iri("102358")),
        URIRef(GEO + "sfWithin"),
        URIRef(geonames_iri("6255147")),
    ) in g2
    wkts = set(g2.objects(None, URIRef(GEO + "asWKT")))
    assert Literal("POINT (42.62537 17.1495)", datatype=URIRef(GEO + "wktLiteral")) in wkts
    q1 = {r[0] for r in queries.run(g2, "Q1_taxa_in_asir")}
    assert q1 == {"Avicennia marina"}
    q2 = {r[1] for r in queries.run(g2, "Q2_localities_within_SA-09")}
    assert "Sabya" in q2 and "10 km off Farasan" not in q2  # relative locality: no sfWithin
    q3 = queries.run(g2, "Q3_conflicts_stated_vs_geonames_adm1")
    assert [(r[1], r[2], r[3]) for r in q3] == [("Rābigh", "SA-14", "SA-02")]
    q5 = {r[1] for r in queries.run(g2, "Q5_taxa_in_bbox_geof")}
    assert q5 == {"Sabya"}


def test_dwc_row_vocabularies(ncvc_occurrences) -> None:
    rows = [dwc.dwc_row(o) for o in ncvc_occurrences]
    assert all(r["basisOfRecord"] == "Occurrence" for r in rows)
    assert {r["establishmentMeans"] for r in rows} == {"native"}
    sabya = next(r for r in rows if r["locality"] == "Sabya")
    assert (sabya["decimalLatitude"], sabya["decimalLongitude"]) == ("17.1495", "42.62537")
    assert sabya["stateProvince"] == "Jazan Region" and sabya["countryCode"] == "SA"
    region = next(r for r in rows if r["locationID"] == geonames_iri("105298"))
    assert region["decimalLatitude"] == "" and "area feature" in region["georeferenceRemarks"]
    relative = next(r for r in rows if r["verbatimLocality"] == "جزيرة فرسان")
    assert relative["decimalLatitude"] == "" and "anchor" in relative["georeferenceRemarks"]


def test_status_mappings() -> None:
    assert vocab.gbif_occurrence_status("present", "rare") == ("present", "rare")
    assert vocab.gbif_occurrence_status("expected") == ("", "doubtful")
    assert vocab.gbif_occurrence_status("extinct") == ("absent", "absent")
    assert vocab.dwc_establishment("cultivated", False) == ("introduced", "cultivated")
    assert vocab.dwc_establishment("native", True) == ("nativeEndemic", "native")


def test_sqlite_load_enforces_foreign_keys(ncvc_occurrences) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    assert sql.load_sqlite(conn, ncvc_occurrences) == len(ncvc_occurrences)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    n = conn.execute(
        "SELECT COUNT(*) FROM taxon_occurrence o JOIN geo_feature_within w "
        "ON o.feature_iri = w.feature_iri WHERE w.container_iri = ?",
        (geonames_iri("105298"),),
    ).fetchone()[0]
    assert n == 1  # Sabya (the relative Farasan locality has no containment)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "UPDATE taxon_occurrence SET occurrence_status = 'absent' "
            "WHERE establishment_means = 'native'"
        )
