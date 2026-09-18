"""SQL tables for GeoSPARQL-shaped occurrence data (SQLite and PostgreSQL compatible DDL)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable

from flopo2.geo.models import OccurrenceAssertion, Place

DDL = """
-- A geo:Feature: GeoNames feature (resolved = 1, feature_iri = https://sws.geonames.org/<id>/)
-- or a FLOPO-minted local feature (https://w3id.org/flopo/geographic-context/<digest>).
CREATE TABLE IF NOT EXISTS geo_feature (
  feature_iri TEXT PRIMARY KEY,
  label TEXT NOT NULL,
  feature_type TEXT NOT NULL,
  resolved INTEGER NOT NULL CHECK (resolved IN (0, 1)),
  geonames_id TEXT NOT NULL DEFAULT '',
  geonames_feature_code TEXT NOT NULL DEFAULT '',
  wikidata_id TEXT NOT NULL DEFAULT '',
  country_code TEXT NOT NULL DEFAULT '',
  iso_3166_2 TEXT NOT NULL DEFAULT '',
  admin1_iso_3166_2 TEXT NOT NULL DEFAULT '',
  wkt TEXT,                                  -- geo:asWKT, CRS84 lon-lat POINT
  coordinate_source TEXT NOT NULL DEFAULT '',
  geometry_approximate INTEGER NOT NULL DEFAULT 0,  -- anchor point of a relative locality
  gazetteer TEXT NOT NULL DEFAULT '',
  resolution_confidence TEXT NOT NULL DEFAULT '',
  names_json TEXT NOT NULL DEFAULT '{}',
  CHECK (resolved = 0 OR geonames_id <> ''),
  CHECK (iso_3166_2 = '' OR substr(iso_3166_2, 1, 2) = country_code)
);
-- geo:sfWithin (derived from GeoNames admin codes / reference tables / qualifier parse)
CREATE TABLE IF NOT EXISTS geo_feature_within (
  feature_iri TEXT NOT NULL REFERENCES geo_feature(feature_iri),
  container_iri TEXT NOT NULL REFERENCES geo_feature(feature_iri),
  PRIMARY KEY (feature_iri, container_iri)
);
-- skos:exactMatch / owl:sameAs / flopogeo:anchorFeature links to GeoNames or Wikidata
CREATE TABLE IF NOT EXISTS geo_feature_link (
  feature_iri TEXT NOT NULL REFERENCES geo_feature(feature_iri),
  relation TEXT NOT NULL CHECK (relation IN ('exactMatch', 'anchor')),
  target_iri TEXT NOT NULL,
  PRIMARY KEY (feature_iri, relation, target_iri)
);
-- Standalone stand-in for flopo2/db/schema.sql source_statement (merge on integration).
CREATE TABLE IF NOT EXISTS occurrence_source_statement (
  statement_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  verbatim_text TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS taxon_occurrence (
  occurrence_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_statement_id TEXT NOT NULL REFERENCES occurrence_source_statement(statement_id),
  taxon_name TEXT NOT NULL,
  taxon_rank TEXT NOT NULL DEFAULT '',
  taxon_family TEXT NOT NULL DEFAULT '',
  taxon_id TEXT NOT NULL DEFAULT '',
  feature_iri TEXT NOT NULL REFERENCES geo_feature(feature_iri),
  place_text TEXT NOT NULL DEFAULT '',
  place_start INTEGER,
  place_end INTEGER,
  stated_region TEXT NOT NULL DEFAULT '',
  stated_region_basis TEXT NOT NULL DEFAULT '' CHECK (stated_region_basis IN ('', 'stated', 'inferred')),
  basis TEXT NOT NULL CHECK (basis IN ('stated', 'inferred', 'gazetteer')),
  occurrence_status TEXT NOT NULL DEFAULT 'present'
    CHECK (occurrence_status IN ('present', 'absent', 'doubtful', 'expected', 'excluded', 'extinct')),
  establishment_means TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (establishment_means IN ('native', 'introduced', 'naturalised', 'cultivated', 'uncertain', 'unspecified')),
  endemic INTEGER NOT NULL DEFAULT 0,
  extralimital INTEGER NOT NULL DEFAULT 0,
  abundance TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (abundance IN ('rare', 'occasional', 'common', 'widespread', 'unspecified')),
  epistemic_modality TEXT NOT NULL DEFAULT 'asserted'
    CHECK (epistemic_modality IN ('asserted', 'probable', 'possible', 'uncertain', 'reported')),
  status_text TEXT NOT NULL DEFAULT '',
  conflict INTEGER NOT NULL DEFAULT 0,
  conflict_note TEXT NOT NULL DEFAULT '',
  derived_from_json TEXT NOT NULL DEFAULT '[]',
  extractor TEXT NOT NULL,
  mapping_notes_json TEXT NOT NULL DEFAULT '[]',
  CHECK ((place_start IS NULL) = (place_end IS NULL)),
  CHECK (NOT (occurrence_status IN ('absent', 'extinct')
              AND establishment_means IN ('native', 'introduced', 'naturalised')))
);
CREATE INDEX IF NOT EXISTS idx_taxon_occurrence_taxon ON taxon_occurrence(taxon_name);
CREATE INDEX IF NOT EXISTS idx_taxon_occurrence_feature ON taxon_occurrence(feature_iri);
CREATE INDEX IF NOT EXISTS idx_geo_feature_within_container ON geo_feature_within(container_iri);
"""


def _feature_row(p: Place) -> tuple:
    g = p.geometry
    return (
        p.feature_iri,
        p.label,
        p.feature_type,
        int(p.resolved),
        p.geonames_id,
        p.geonames_feature_code,
        p.wikidata_id,
        p.country_code,
        p.iso_3166_2,
        p.admin1_iso_3166_2,
        g.wkt if g else None,
        g.source if g else "",
        int(bool(g and g.anchor_note)),
        p.gazetteer,
        p.resolution_confidence,
        json.dumps(p.names, ensure_ascii=False),
    )


def load_sqlite(conn: sqlite3.Connection, occurrences: Iterable[OccurrenceAssertion]) -> int:
    """Load occurrences (and every feature they reference, containers included)."""
    from flopo2.geo.gazetteer import continents, countries, sa_regions

    conn.executescript(DDL)
    reference = {}
    for table in (continents(), countries(), sa_regions()):
        for ref in table.values():
            place = ref.place()
            reference[place.feature_iri] = place
    features: dict[str, Place] = {}
    n = 0
    occ_rows, stmt_rows = [], {}
    for occ in occurrences:
        features.setdefault(occ.place.feature_iri, occ.place)
        stmt_rows[occ.source_statement_id] = (
            occ.source_statement_id,
            occ.source,
            occ.source_id,
            occ.statement_text,
            occ.statement_language,
        )
        occ_rows.append(
            (
                occ.occurrence_id,
                occ.source,
                occ.source_id,
                occ.source_statement_id,
                occ.taxon_name,
                occ.taxon_rank,
                occ.taxon_family,
                occ.taxon_id,
                occ.place.feature_iri,
                occ.place_text,
                occ.place_start,
                occ.place_end,
                occ.stated_region,
                occ.stated_region_basis,
                occ.basis,
                occ.occurrence_status,
                occ.establishment_means,
                int(occ.endemic),
                int(occ.extralimital),
                occ.abundance,
                occ.epistemic_modality,
                occ.status_text,
                int(occ.conflict),
                occ.conflict_note,
                json.dumps(occ.derived_from),
                occ.extractor,
                json.dumps(occ.mapping_notes, ensure_ascii=False),
            )
        )
        n += 1
    pending = [iri for p in list(features.values()) for iri in p.within]
    while pending:
        iri = pending.pop()
        if iri not in features and iri in reference:
            features[iri] = reference[iri]
            pending.extend(reference[iri].within)
    conn.executemany(
        "INSERT OR REPLACE INTO geo_feature VALUES (" + ",".join("?" * 16) + ")",
        [_feature_row(p) for p in features.values()],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO geo_feature_within VALUES (?, ?)",
        [(p.feature_iri, w) for p in features.values() for w in p.within if w in features],
    )
    conn.executemany(
        "INSERT OR IGNORE INTO geo_feature_link VALUES (?, ?, ?)",
        [(p.feature_iri, "exactMatch", t) for p in features.values() for t in p.same_as]
        + [(p.feature_iri, "anchor", t) for p in features.values() for t in p.anchor_iris],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO occurrence_source_statement VALUES (?, ?, ?, ?, ?)",
        list(stmt_rows.values()),
    )
    conn.executemany("INSERT INTO taxon_occurrence VALUES (" + ",".join("?" * 27) + ")", occ_rows)
    conn.commit()
    return n
