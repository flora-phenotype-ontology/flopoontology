"""Offline tests for taxon normalization (no network — a stub client returns canned GNV results)."""

from __future__ import annotations

from flopo2.taxon.normalize import (
    SRC_GBIF,
    SRC_IPNI,
    SRC_WFO,
    ResolvedTaxon,
    TaxonNormalizer,
    resolve_from_gnv_result,
)

# A GNV `names[]` entry shaped like the real API response (withAllMatches=true).
GNV_RESULT = {
    "name": "Gambeya africana",
    "matchType": "Exact",
    "bestResult": {
        "matchedCanonicalSimple": "Gambeya africana",
        "currentCanonicalSimple": "Gambeya africana",
    },
    "results": [
        {"dataSourceId": SRC_WFO, "recordId": "wfo-0000970690-2025-12",
         "currentCanonicalSimple": "Gambeya africana"},
        {"dataSourceId": SRC_IPNI, "recordId": "bare-name-786839-1"},
        {"dataSourceId": SRC_GBIF, "recordId": "2885895"},
    ],
}


class StubClient:
    """Stands in for GlobalNamesClient; records calls and returns canned results."""

    def __init__(self, results: dict[str, dict]):
        self.results = results
        self.verify_calls: list[list[str]] = []

    def verify(self, names, sources=None):
        self.verify_calls.append(list(names))
        return [self.results.get(n, {"name": n, "matchType": "NoMatch"}) for n in names]

    def close(self):
        pass


def test_resolve_from_gnv_result_extracts_per_source_ids():
    rt = resolve_from_gnv_result("Gambeya africana", "Gambeya africana", GNV_RESULT)
    assert rt.resolved
    assert rt.match_type == "Exact"
    assert rt.wfo_id == "wfo-0000970690-2025-12"
    assert rt.ipni_id == "bare-name-786839-1"
    assert rt.gbif_id == "2885895"
    assert rt.accepted_canonical == "Gambeya africana"


def test_nomatch():
    rt = resolve_from_gnv_result("Notarealplant xyz", "Notarealplant xyz",
                                 {"name": "Notarealplant xyz", "matchType": "NoMatch"})
    assert not rt.resolved
    assert rt.wfo_id == ""


def test_normalizer_caches_and_dedupes(tmp_path):
    stub = StubClient({"Gambeya africana": GNV_RESULT})
    tn = TaxonNormalizer(cache_path=tmp_path / "c.sqlite", client=stub)

    # Duplicate input names must collapse to a single verify entry.
    out = tn.resolve_many(["Gambeya africana", "Gambeya africana"])
    assert len(out) == 2  # one per requested position
    assert out[0].wfo_id == "wfo-0000970690-2025-12"
    assert stub.verify_calls == [["Gambeya africana"]]  # deduped to one lookup

    # Second call is served entirely from cache — no new verify call.
    tn.resolve("Gambeya africana")
    assert stub.verify_calls == [["Gambeya africana"]]

    # Survives a reopen (persistent SQLite cache).
    tn.close()
    tn2 = TaxonNormalizer(cache_path=tmp_path / "c.sqlite", client=StubClient({}))
    assert tn2.resolve("Gambeya africana").wfo_id == "wfo-0000970690-2025-12"
    tn2.close()


def test_cache_roundtrip_is_resolvedtaxon(tmp_path):
    tn = TaxonNormalizer(cache_path=tmp_path / "c.sqlite", client=StubClient({"X": GNV_RESULT | {"name": "X"}}))
    rt = tn.resolve("X")
    assert isinstance(rt, ResolvedTaxon)
    tn.close()
