"""Taxon recognition & normalization — the species side of the knowledge base (Phase 2).

Flora treatments give taxon name strings (genus + species + author, sometimes only family). We:
  1. parse/canonicalize each name with the **GNparser** API (semantic elements, canonical form), and
  2. verify it against the **Global Names Verifier (GNV)**, restricted to plant-native backbones —
     **World Flora Online (WFO, source 196)** and **IPNI (167)**, plus **GBIF (11)** for a
     cross-domain link — recovering the accepted name and the per-backbone record IDs.

Every resolved taxon thus carries ``wfo_id`` + ``ipni_id`` (+ ``gbif_id``), so each phenotype
assertion links to a stable, interoperable species identity. Results are cached in SQLite keyed by
the canonical name, because the 116k corpus segments collapse to ~28k unique names.

No local binary is required — both are official public HTTP APIs (overridable for self-hosting).
The HTTP client is injectable so the logic is unit-testable offline.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

GNPARSER_API = "https://parser.globalnames.org/api/v1"
GNVERIFIER_API = "https://verifier.globalnames.org/api/v1"

# GNV data-source IDs (discovered via /data_sources; titles checked at runtime in tests).
SRC_WFO = 196   # World Flora Online Plant List
SRC_IPNI = 167  # International Plant Names Index
SRC_GBIF = 11   # GBIF Backbone Taxonomy
PREFERRED_SOURCES = [SRC_WFO, SRC_IPNI, SRC_GBIF]


@dataclass(frozen=True)
class ResolvedTaxon:
    input_name: str
    canonical: str  # GNparser canonical (simple)
    matched_name: str  # GNV current/accepted name (best result)
    match_type: str  # Exact / Fuzzy / PartialExact / NoMatch ...
    wfo_id: str = ""
    ipni_id: str = ""
    gbif_id: str = ""
    accepted_canonical: str = ""  # WFO accepted canonical, if available

    @property
    def resolved(self) -> bool:
        return self.match_type not in ("", "NoMatch")


class GlobalNamesClient:
    """Thin client over the GNparser + GNV HTTP APIs."""

    def __init__(self, client: httpx.Client | None = None, timeout: float = 60.0):
        self._client = client or httpx.Client(timeout=timeout)

    def parse(self, name: str) -> str:
        """Return the GNparser canonical (simple) form, or the input if parsing yields nothing."""
        r = self._client.get(f"{GNPARSER_API}/{httpx.URL(path=name).path.lstrip('/')}")
        r.raise_for_status()
        data = r.json()
        if data and data[0].get("parsed"):
            return data[0].get("canonical", {}).get("simple", name)
        return name

    def verify(self, names: list[str], sources: list[int] | None = None) -> list[dict]:
        """Verify name strings against preferred sources; returns the raw GNV ``names`` list."""
        payload = {
            "nameStrings": names,
            "dataSources": sources or PREFERRED_SOURCES,
            "withAllMatches": True,
            "withCapitalization": True,
        }
        r = self._client.post(f"{GNVERIFIER_API}/verifications", json=payload)
        r.raise_for_status()
        return r.json().get("names", [])

    def close(self) -> None:
        self._client.close()


def _record_for_source(name_result: dict, source_id: int) -> dict | None:
    """Find the match record from a specific data source within a GNV name result."""
    for res in name_result.get("results", []) or []:
        if res.get("dataSourceId") == source_id:
            return res
    return None


def resolve_from_gnv_result(input_name: str, canonical: str, name_result: dict) -> ResolvedTaxon:
    """Build a :class:`ResolvedTaxon` from a single GNV ``names[]`` entry."""
    best = name_result.get("bestResult", {}) or {}
    wfo = _record_for_source(name_result, SRC_WFO)
    ipni = _record_for_source(name_result, SRC_IPNI)
    gbif = _record_for_source(name_result, SRC_GBIF)
    return ResolvedTaxon(
        input_name=input_name,
        canonical=canonical,
        matched_name=best.get("matchedCanonicalSimple", "") or best.get("matchedName", ""),
        match_type=name_result.get("matchType", "NoMatch"),
        wfo_id=(wfo or {}).get("recordId", ""),
        ipni_id=(ipni or {}).get("recordId", ""),
        gbif_id=(gbif or {}).get("recordId", ""),
        accepted_canonical=(wfo or best).get("currentCanonicalSimple", ""),
    )


class TaxonNormalizer:
    """Resolve taxon name strings to WFO/IPNI/GBIF identities, with a persistent SQLite cache."""

    def __init__(self, cache_path: Path | str = "config/taxon_cache.sqlite",
                 client: GlobalNamesClient | None = None):
        self.client = client or GlobalNamesClient()
        self.cache = sqlite3.connect(str(cache_path))
        self.cache.execute(
            "CREATE TABLE IF NOT EXISTS taxon (name TEXT PRIMARY KEY, json TEXT)"
        )
        self.cache.commit()

    def _cached(self, name: str) -> ResolvedTaxon | None:
        row = self.cache.execute("SELECT json FROM taxon WHERE name=?", (name,)).fetchone()
        return ResolvedTaxon(**json.loads(row[0])) if row else None

    def _store(self, rt: ResolvedTaxon) -> None:
        self.cache.execute(
            "INSERT OR REPLACE INTO taxon(name, json) VALUES (?, ?)",
            (rt.input_name, json.dumps(asdict(rt))),
        )
        self.cache.commit()

    def resolve_many(self, names: list[str]) -> list[ResolvedTaxon]:
        """Resolve a batch of names, serving cache hits and verifying the misses in one GNV call."""
        out: dict[str, ResolvedTaxon] = {}
        misses: list[str] = []
        for n in dict.fromkeys(n for n in names if n):
            hit = self._cached(n)
            if hit:
                out[n] = hit
            else:
                misses.append(n)
        if misses:
            results = {r.get("name"): r for r in self.client.verify(misses)}
            for n in misses:
                nr = results.get(n, {})
                canonical = nr.get("name", n)
                rt = resolve_from_gnv_result(n, canonical, nr)
                self._store(rt)
                out[n] = rt
        return [out[n] for n in names if n in out]

    def resolve(self, name: str) -> ResolvedTaxon:
        return self.resolve_many([name])[0]

    def close(self) -> None:
        self.client.close()
        self.cache.close()
