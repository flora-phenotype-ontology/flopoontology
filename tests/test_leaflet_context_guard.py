"""Regression tests: leaflet laminas must not be borne on leaf apex / leaf base.

The three texts are verbatim excerpts of corrected assertions listed in
``scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/leaflet-bearer-corrections.tsv``:
fdac 897395 (deterministic locative recovery), Flora Malesiana vol16 1091 (leaf-apex candidate) and
vol16 1213 (leaf-base candidate).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flopo2.extract.context_recovery import LocativeMapping, recover_record
from flopo2.extract.leaflet_context import leaflet_context, leaflet_guarded
from flopo2.verify.missing_bearers import _po_exact_forms, _po_forms

FDAC_897395 = (
    "à pétiole et rachis de 3–4 cm de long, glabres; folioles 5, à pétiolule de 7–9 mm de long; "
    "limbe lancéolé-oblong, ovale-lancéolé à oblong ou largement lancéolé, aigu ou obtus à la "
    "base, acuminé au sommet, de 5–12 cm de long."
)
FM16_1091 = (
    "Leaves imparipinnate; lateral leaflets lanceolate or narrowly elliptic, the largest 3-5 by "
    "1-1.6 cm, base unequal and ± sessile, apex acuminate;"
)
FM16_1213 = (
    "Leaves trifoliolate; terminal leaflet narrowly elliptic to narrowly obovate, "
    "(2.8-)4.3-11 by (0.9-)1.2-2.3 cm, apex acute, base attenuate;"
)


@pytest.mark.parametrize(
    ("text", "surface", "expected"),
    [
        (FDAC_897395, "acuminé", "leaflet_clause_then_lamina"),
        (FM16_1091, "acuminate", "leaflet_subject"),
        (FM16_1213, "attenuate", "leaflet_subject"),
        # Simple leaves: no leaflet cue.
        ("Leaves elliptic, acuminate at apex.", "acuminate", ""),
        # Pinnatisect is a simple (dissected) leaf, not a leaflet cue.
        ("Leaves pinnatisect, ovate in outline, apex obtuse.", "obtuse", ""),
        # The description returns to the leaf after the leaflet mention.
        ("Leaflets 5. Leaf blade elliptic, apex acuminate.", "acuminate", ""),
        # A leaf noun inside a prepositional phrase does not end the leaflet context.
        (
            "folioles 7; poils visibles sur les jeunes feuilles; limbes ovales, acuminés au sommet",
            "acuminés",
            "leaflet_clause_then_lamina",
        ),
    ],
)
def test_leaflet_context(text, surface, expected):
    assert leaflet_context(text, text.index(surface)) == expected


def test_guard_applies_only_to_leaf_apex_and_base():
    position = FDAC_897395.index("acuminé")
    assert leaflet_guarded("PO_0020137", FDAC_897395, position)
    assert leaflet_guarded("PO_0020040", FDAC_897395, position)
    assert not leaflet_guarded("PO_0009025", FDAC_897395, position)


def _locative_record(text: str) -> tuple[dict, dict]:
    start = text.index("acuminé au sommet")
    record = {
        "source": "fdac",
        "source_id": "897395",
        "source_segment_index": 1,
        "taxon": "Planta exemplaris",
        "organ": "feuilles",
        "language": "fr",
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": start,
                "end": start + len("acuminé"),
                "surface_form": "acuminé",
                "reason": "unsupported_alternative_or_transition",
                "candidate_pato_id": "PATO_0002228",
                "extractor": "deterministic_baseline",
            }
        ],
    }
    key = ("fdac", "897395", 1, start, start + len("acuminé"), "PATO_0002228")
    clause_start = text.index("limbe")
    mapping = LocativeMapping(
        po_id="PO_0020137",
        po_label="leaf apex",
        container_surface="limbe",
        locative_phrase="au sommet",
        orientation="apical_region",
        attachment_rule="organ_specific_apex",
        normalization_scope="locative_captured_by_atomic_po_bearer",
        clause_start=clause_start,
        clause_end=text.index(", de 5"),
    )
    return record, {key: mapping}


@pytest.mark.parametrize(
    ("text", "recovered"),
    [
        (FDAC_897395, False),
        # Control: the same lamina clause without the leaflet clause is a leaf apex.
        (FDAC_897395.replace("folioles 5, à pétiolule de 7–9 mm de long; ", ""), True),
    ],
)
def test_context_recovery_withholds_leaf_apex_in_leaflet_context(text, recovered):
    record, mappings = _locative_record(text)
    out, audit = recover_record(
        record,
        _po_exact_forms(),
        _po_forms(Path("config/po_lexicon.tsv")),
        locative_mappings=mappings,
    )
    assert bool(out["assertions"]) is recovered
    assert bool(out["unresolved_spans"]) is not recovered
    expected = (
        "recovered_existing_po_locative_subregion"
        if recovered
        else "leaflet_context_bearer_withheld"
    )
    assert audit[0]["disposition"] == expected


def _stage(tmp_path: Path, text: str, surface: str, pato_id: str) -> Path:
    start = text.rindex(surface)
    stage = tmp_path / "stage.jsonl"
    stage.write_text(
        json.dumps(
            {
                "source": "flora-malesiana",
                "source_id": "vol16_final.xml",
                "source_segment_index": 0,
                "taxon": "Planta exemplaris",
                "organ": "leaves",
                "language": "en",
                "char_start": 0,
                "char_end": len(text),
                "text": text,
                "assertions": [],
                "unresolved_spans": [
                    {
                        "start": start,
                        "end": start + len(surface),
                        "surface_form": surface,
                        "reason": "same_attribute_composite_or_transition",
                        "candidate_pato_id": pato_id,
                        "extractor": "fixture",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    return stage


def _exclusion(output: Path) -> str:
    return json.loads((output / "excluded.jsonl").read_text(encoding="utf-8"))["reason"]


@pytest.mark.parametrize(
    ("text", "excluded"),
    [
        (FM16_1091, True),
        ("Leaves lanceolate or narrowly elliptic, base unequal, apex acuminate;", False),
    ],
)
def test_leaf_apex_candidate_excludes_leaflet_context(tmp_path: Path, text, excluded):
    from test_recover_leaf_apex_expressions import _files

    from flopo2.verify.recover_leaf_apex_expressions import prepare_leaf_apex_review_input

    po, pato, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_leaf_apex_review_input(
        stage_path=_stage(tmp_path, text, "acuminate", "PATO_0002228"),
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    assert report["conserved"] is True
    assert report["candidates"] == (0 if excluded else 1)
    if excluded:
        assert _exclusion(output) == "leaflet_context_bearer"


@pytest.mark.parametrize(
    ("text", "excluded"),
    [
        (FM16_1213, True),
        ("Leaves narrowly elliptic to narrowly obovate, apex acute, base attenuate;", False),
    ],
)
def test_leaf_base_candidate_excludes_leaflet_context(tmp_path: Path, text, excluded):
    from test_recover_leaf_base_expressions import _files

    from flopo2.verify.recover_leaf_base_expressions import prepare_leaf_base_review_input

    po, pato, registry, combinations = _files(tmp_path)
    output = tmp_path / "output"
    report = prepare_leaf_base_review_input(
        stage_path=_stage(tmp_path, text, "attenuate", "PATO_0001982"),
        review_input_path=output / "review.jsonl",
        candidate_ledger_path=output / "ledger.jsonl",
        exclusions_path=output / "excluded.jsonl",
        report_path=output / "report.json",
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
        combinations_path=combinations,
    )
    assert report["conserved"] is True
    assert report["candidates"] == (0 if excluded else 1)
    if excluded:
        assert _exclusion(output) == "leaflet_context_bearer"



# Verbatim contexts from leaflet-lamina-review.tsv: #37 (fdac 903565) and #96 (fdac 900409) are
# ``leaflet`` verdicts; #684 (Kew 113184, fern frond after "pinnae") is a ``leaf`` verdict.
FDAC_903565 = (
    "bres; pétiole de 7–15 cm de long et 1–2 mm de diam. à la base, cannelé, glabre; folioles 5–7; "
    "pétiolule de 1–6 cm de long, glabre; limbe elliptique à obovale ou oblancéolé, atténué à "
    "arrondi à la base, acuminé au sommet, de 6–15 cm de long et 2,5–6 cm de large, entier à "
    "faiblement ondulé, papyracé, glabre sur les 2 face"
)
FDAC_900409 = (
    "à fines stries longitudinales; rachis de 25 cm de long, strié comme le pétiole; folioles "
    "alternes ou subopposées, à pétiolule de 3–4 mm de long; limbe elliptique, atténué vers la base "
    "aiguë et asymétrique et vers le sommet très brièvement acuminé, de 10–16 cm de long et "
    "4,5–5 cm de large, coriace, glabre; nervure média"
)
KEW_113184 = (
    "Fronds erect to arching with pinnae held horizontally, 0.6–2 m (occasionally 3 m) tall; stipe "
    "purplish brown or chestnut brown, up to 60 cm long, glabrous; lamina up to 40 cm long and "
    "19 cm wide"
)


def _lamina_assertions(text: str) -> list[dict]:
    from flopo2.extract.baseline import extract_segment_with_unresolved

    assertions, _ = extract_segment_with_unresolved(
        {"text": text, "organ": "feuilles", "language": "fr"}
    )
    return [row for row in assertions if row["po_id"] == "PO_0020039"]


@pytest.mark.parametrize("text", [FDAC_903565, FDAC_900409])
def test_baseline_withholds_leaf_lamina_after_foliole_cue(text):
    position = text.index("limbe")
    assert leaflet_guarded("PO_0020039", text, position)
    assert _lamina_assertions(text) == []
    # Control: the same lamina clause without the preceding leaflet description is a leaf lamina.
    control = text[position:]
    assert not leaflet_guarded("PO_0020039", control, len(control))
    assert _lamina_assertions(control)


def test_leaf_lamina_guard_uses_only_the_foliole_trigger():
    # Fern frond lamina after "pinnae" is the leaf lamina (review verdict ``leaf``): the full
    # leaflet context fires, but the lamina guard must not.
    position = KEW_113184.index("up to 40")
    assert leaflet_context(KEW_113184, position)
    assert not leaflet_guarded("PO_0020039", KEW_113184, position)
    # Apex/base keep the full pattern.
    assert leaflet_guarded("PO_0020137", KEW_113184, position)


def test_leaflet_bearer_remaps_only_guarded_leaf_parts():
    from flopo2.extract.leaflet_context import leaflet_bearer

    apex = FDAC_897395.index("acuminé")
    assert leaflet_bearer("PO_0020137", FDAC_897395, apex) == "FLOPO_0986000"
    assert leaflet_bearer("PO_0020040", FDAC_897395, apex) == "FLOPO_0986001"
    assert leaflet_bearer("PO_0020039", FDAC_897395, apex) == "FLOPO_0986002"
    # Other bearers and unguarded (simple-leaf) contexts are unchanged.
    assert leaflet_bearer("PO_0009025", FDAC_897395, apex) == "PO_0009025"
    simple = "Leaves elliptic, acuminate at apex."
    assert leaflet_bearer("PO_0020137", simple, simple.index("acuminate")) == "PO_0020137"
    # The lamina keeps the foliol*-only trigger: a fern frond after "pinnae" stays leaf lamina.
    fern = "Fronds pinnate; pinnae 10 pairs; lamina glabrous."
    assert leaflet_bearer("PO_0020039", fern, fern.index("glabrous")) == "PO_0020039"


def test_leaflet_bearer_ids_are_released():
    from flopo2.extract.leaflet_context import LEAFLET_PART_BY_LEAF_PART
    from flopo2.verify.local_bearer_table import released_flopo_ids

    assert set(LEAFLET_PART_BY_LEAF_PART.values()) <= released_flopo_ids()
