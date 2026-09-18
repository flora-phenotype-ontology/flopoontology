"""Tests for re-admitting corrected leaflet qualities on the FLOPO leaflet classes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flopo2.verify import readmit_leaflet_bearers as rl
from flopo2.verify.gates import Combination

TEXT = "folioles 5, à pétiolule de 5 mm de long; limbe coriace, glabre."
START = TEXT.index("glabre")
KEY = {
    "source": "fdac",
    "source_id": "1",
    "source_segment_index": 1,
    "taxon": "Testia exempla",
    "organ": "feuilles",
    "char_start": 0,
    "char_end": len(TEXT),
}


def _record() -> dict:
    return {
        **KEY,
        "language": "fr",
        "text": TEXT,
        "source_statements": [
            {"statement_id": "st-1", "start": START, "end": START + 6, "verbatim_text": "glabre"}
        ],
        "assertions": [
            {
                "po_id": "PO_0020039",
                "pato_id": "PATO_0000453",
                "source_text": "glabre",
                "source_start": START,
                "source_end": START + 6,
                "source_statement_id": "st-1",
                "value_operator": "atomic",
                "value_terms": [],
                "negated": False,
                "negation_scope": "",
                "extractor": "deterministic_baseline",
                "mapping_provenance": [],
                "composition": {"status": "accept", "entity_label": "leaf lamina"},
                "gate": {"status": "accepted"},
            }
        ],
        "unresolved_spans": [],
    }


def _correction() -> dict:
    return {
        "key": dict(KEY),
        "add_source_statements": [],
        "add_assertions": [],
        "remove_unresolved": [],
        "remove_assertions": [
            {
                "source_statement_id": "st-1",
                "po_id": "PO_0020039",
                "pato_id": "PATO_0000453",
                "source_start": START,
                "source_end": START + 6,
            }
        ],
        "add_unresolved": [
            {
                "start": START,
                "end": START + 6,
                "surface_form": "glabre",
                "reason": "missing_or_unsupported_bearer",
                "candidate_pato_id": "PATO_0000453",
                "extractor": rl.CORRECTION_EXTRACTOR,
                "pending_bearer": "leaflet lamina",
            }
        ],
    }


@pytest.fixture()
def paths(tmp_path: Path) -> tuple[Path, Path]:
    stage = tmp_path / "stage.jsonl"
    stage.write_text(json.dumps(_record(), ensure_ascii=False) + "\n", encoding="utf-8")
    correction = tmp_path / "correction.jsonl"
    correction.write_text(json.dumps(_correction(), ensure_ascii=False) + "\n", encoding="utf-8")
    return stage, correction


def test_held_without_an_approved_leaflet_pair(paths, tmp_path):
    resources = rl.GateResources()
    resources.combinations.pop(("FLOPO_0986002", "PATO_0000453"), None)
    report = rl.build(*paths, tmp_path / "out", resources=resources)
    assert report["readmitted_assertions"] == 0
    assert report["counts"]["held_pair_only"] == 1
    assert (tmp_path / "out" / "leaflet-readmit-delta.jsonl").read_text() == ""
    candidates = (tmp_path / "out" / "leaflet-readmit-pair-candidates.tsv").read_text()
    assert "FLOPO_0986002\tleaflet lamina\tPATO_0000453" in candidates


def test_readmitted_on_leaflet_lamina_when_pair_allowed(paths, tmp_path):
    resources = rl.GateResources()
    resources.combinations[("FLOPO_0986002", "PATO_0000453")] = Combination(
        status="allowed", source="curator_review_test"
    )
    report = rl.build(*paths, tmp_path / "out", resources=resources)
    assert report["readmitted_assertions"] == 1
    (line,) = [json.loads(row) for row in (tmp_path / "out" / "leaflet-readmit-delta.jsonl").open()]
    (assertion,) = line["add_assertions"]
    assert (assertion["po_id"], assertion["pato_id"]) == ("FLOPO_0986002", "PATO_0000453")
    assert (assertion["source_start"], assertion["source_statement_id"]) == (START, "st-1")
    assert assertion["gate"]["status"] == "accepted"
    assert rl.CLASS_APPROVAL in assertion["mapping_provenance"]
    assert any(p.startswith("leaflet_correction:") for p in assertion["mapping_provenance"])
    assert line["remove_unresolved"] == [
        {"start": START, "end": START + 6, "reason": "missing_or_unsupported_bearer", "surface_form": "glabre"}
    ]


def test_mismatched_correction_line_fails():
    line = _correction()
    line["add_unresolved"][0]["candidate_pato_id"] = "PATO_0000001"
    with pytest.raises(ValueError, match="does not match"):
        rl.pair_removals(line)


def _guard(text: str, value: str, pato_id: str = "PATO_0000453", **kwargs) -> str:
    start = text.index(value)
    return rl.readmit_guard(text, {"start": start, "end": start + len(value)}, pato_id, **kwargs)


@pytest.mark.parametrize(
    ("text", "value", "pato_id", "reason"),
    [
        # Verbatim-style excerpts of the error classes found in the review rounds.
        ("folioles 5; limbe papyracé, glabre en dessus, pubescent en dessous.", "glabre",
         "PATO_0000453", "surface_restricted_value"),
        ("folioles 3; limbe 2-lobé, ± pubescent, à lobes oblongs, arrondis.", "oblongs",
         "PATO_0000946", "lobe_or_segment_member"),
        ("folioles 5; limbe ovale, sommet à peine acuminé.", "acuminé", "PATO_0002228",
         "hedge_or_frequency_before_value"),
        ("folioles 5; limbe suborbiculaire à largement oblong, arrondi.", "oblong", "PATO_0000946",
         "range_or_alternative_before_value"),
        ("folioles 5; limbe elliptique à ± rhomboïdal, cunéé.", "elliptique", "PATO_0000947",
         "range_after_value"),
        ("folioles 5; limbe coriace, marge pubescente; nervures 6.", "pubescente", "PATO_0001320",
         "lamina_part_member"),
        ("Folioles oblongues, 12-20 cm long et 3-4 cm large.", "oblongues", "PATO_0000946",
         "leaflet_subject_not_lamina"),
        ("folioles 5; limbe tantôt rhomboïde, très aigu et acuminé, tantôt ovale.", "acuminé",
         "PATO_0002228", "clause_level_alternation"),
        ("folioles 5; limbe glabre, sauf quelques poils à la base.", "glabre", "PATO_0000453",
         "exception_after_value"),
        ("folioles 5; limbe elliptique, atténué vers la base, ± obtus, à sommet aigu.", "obtus",
         "PATO_0001935", "apex_or_base_shape_on_lamina"),
        ("folioles 5; limbe coriace, vert très foncé, luisant en dessus, vert clair en dessous.",
         "vert très foncé", "PATO_0000320", "surface_restricted_next_member"),
        ("pinnae 20 pairs; lamina glabrous.", "glabrous", "PATO_0000453",
         "lamina_without_foliole_cue"),
    ],
)
def test_readmit_guard_holds_error_classes(text, value, pato_id, reason):
    assert _guard(text, value, pato_id) == reason


def test_readmit_guard_keeps_plain_leaflet_lamina_values():
    text = "folioles 3, à pétiolule glabre; limbe lancéolé, cartacé à coriace, glabre, à bords enroulés."
    start = text.index("glabre, à")
    assert rl.readmit_guard(text, {"start": start, "end": start + 6}, "PATO_0000453") == ""
    assert _guard(text, "lancéolé", "PATO_0001877") == ""
    assert _guard("folioles 5; limbe ovale, arrondi à la base, acuminé au sommet.", "acuminé",
                  "PATO_0002228", lamina=False) == ""


def test_surface_restriction_member_scope():
    from flopo2.extract.surface_context import surface_restriction

    text = "limbe coriace, glabre en dessus, pubescent en dessous"
    assert surface_restriction(text, text.index("glabre"), text.index("glabre") + 6) == "en dessus"
    assert surface_restriction(text, text.index("coriace"), text.index("coriace") + 7) == ""
    text = "la supérieure glabre, l’inférieure tomenteuse"
    start = text.index("tomenteuse")
    assert surface_restriction(text, start, start + 10)
