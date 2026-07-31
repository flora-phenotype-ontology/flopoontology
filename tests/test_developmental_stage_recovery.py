"""Tests for the v3 developmental-stage recovery module.

These lock the two attachment-safe routes (P1 stage-conditioned bearer quality, R2 plain value
when the stage is provably out of scope) and, crucially, the adversarial rejections: a promotion
here must never attach a stage to the wrong bearer, never conjoin PATO-disjoint qualities on one
bearer, and never turn a stage-conditioned value into an unconditional flora universal.
"""

from __future__ import annotations

from pathlib import Path

from flopo2.extract.baseline import extract_segment_with_unresolved
from flopo2.extract.developmental_stage_recovery import recover_dev_record
from flopo2.verify.missing_bearers import _po_exact_forms, _po_forms

_PO = _po_exact_forms()
_CAND = _po_forms(Path("config/po_lexicon.tsv"))


def _run(text: str, *, organ: str = "description", language: str = "en"):
    assertions, unresolved = extract_segment_with_unresolved(
        {"text": text, "organ": organ, "language": language}
    )
    record = {
        "source": "flora-test",
        "source_id": "one.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "organ": organ,
        "language": language,
        "text": text,
        "assertions": assertions,
        "unresolved_spans": unresolved,
    }
    return recover_dev_record(record, _PO, _CAND)


def _recovered(audit):
    return [r for r in audit if r["disposition"].startswith("recovered")]


def _run_manual_stage(text: str, value: str, pato_id: str):
    start = text.index(value)
    record = {
        "source": "flora-test",
        "source_id": "stage.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
        "organ": "description",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": start,
                "end": start + len(value),
                "surface_form": value,
                "reason": "developmental_stage_context",
                "candidate_pato_id": pato_id,
                "extractor": "test",
            }
        ],
    }
    return recover_dev_record(record, _PO, _CAND)


# --------------------------------------------------------------------------------------------- P1
def test_p1_age_maturity_is_conjunctive_bearer_quality():
    cases = (
        ("Young leaves pubescent.", "PATO_0001320", "PATO_0000309"),
        ("Mature leaves glabrous.", "PATO_0000453", "PATO_0001701"),
        ("Fruits red at maturity.", "PATO_0000322", "PATO_0001701"),
        ("Juvenile leaves ovate.", "PATO_0001891", "PATO_0001190"),
    )
    for text, primary, stage in cases:
        out, audit, props = _run(text)
        rec = [a for a in out["assertions"] if a.get("pato_id") == primary]
        assert rec, text
        assert rec[0]["bearer_context_qualities"] == [stage], text
        assert rec[0]["normalization_status"] == "compositional"
        assert props and props[0]["route"] == "P1"


def test_p1_extended_predicate_a_letat_jeune():
    out, audit, props = _run(
        "ramilles et feuilles glabres même à l'état jeune.", language="fr"
    )
    rec = _recovered(audit)
    assert rec and rec[0]["stage_pato"] == "PATO_0000309"
    assert rec[0]["disposition"] == "recovered_bearer_stage_quality"


def test_p1_transition_keeps_only_its_own_stage_no_disjoint_conjunction():
    # "pubescent when young, glabrous when old" -> each value keeps only its own stage; the
    # reasoner must never see glabrous+pubescent conjoined on one bearer.
    out, audit, props = _run("branches pubescent when young, glabrous when old.")
    for a in out["assertions"]:
        ctx = set(a.get("bearer_context_qualities") or [])
        quals = {a.get("pato_id")} | ctx
        assert not ({"PATO_0000453", "PATO_0001320"} <= quals), a


# --------------------------------------------------------------------------------------------- P2
def test_p2_anthesis_is_a_po_temporal_context_not_a_pato_bearer_quality():
    text = "Pedicels erect at anthesis."
    out, audit, proposals = _run_manual_stage(text, "erect", "PATO_0000622")
    assertion = out["assertions"][0]
    assert assertion["bearer_context_qualities"] == []
    assert assertion["developmental_stage_contexts"] == [
        {
            "stage_term": "PO_0007616",
            "stage_text": "at anthesis",
            "start": text.index("at anthesis"),
            "end": text.index("at anthesis") + len("at anthesis"),
            "temporal_relation": "present_during",
        }
    ]
    assert assertion["source_text"] == "Pedicels erect at anthesis"
    assert audit[0]["disposition"] == "recovered_po_developmental_stage"
    assert proposals[0]["route"] == "P2"


def test_p2_flowering_fruiting_and_bud_use_reviewed_po_stages():
    cases = (
        ("Bracts green during flowering.", "green", "PATO_0000320", "PO_0007016"),
        ("Pedicels erect at fruiting stage.", "erect", "PATO_0000622", "PO_0025500"),
        ("Petals yellow in bud.", "yellow", "PATO_0000324", "PO_0007615"),
    )
    for text, value, pato, stage in cases:
        out, audit, _proposals = _run_manual_stage(text, value, pato)
        assert audit[0]["disposition"] == "recovered_po_developmental_stage", text
        assert out["assertions"][0]["developmental_stage_contexts"][0]["stage_term"] == stage


def test_p2_stage_noun_cannot_steal_the_anatomical_bearer():
    cases = (
        ("Sepals 12 mm wide in fruit.", "12 mm wide", "PATO_0000921", "PO_0009031"),
        ("Sepals in bud 5 mm long.", "5 mm long", "PATO_0000122", "PO_0009031"),
        ("Calyx 1.5 mm wide in flower.", "1.5 mm wide", "PATO_0000921", "PO_0009060"),
    )
    for text, value, pato, bearer in cases:
        out, audit, _proposals = _run_manual_stage(text, value, pato)
        assert audit[0]["disposition"] == "recovered_po_developmental_stage", text
        assert out["assertions"][0]["po_id"] == bearer, text


def test_p2_rejects_transition_and_unsupported_before_relation():
    for text in (
        "Pedicels becoming reflexed at fruiting stage.",
        "Pedicels erect before anthesis.",
    ):
        value = "reflexed" if "reflexed" in text else "erect"
        pato = "PATO_0002212" if value == "reflexed" else "PATO_0000622"
        out, audit, proposals = _run_manual_stage(text, value, pato)
        assert not out["assertions"], text
        assert not proposals, text
        assert audit[0]["disposition"].startswith("r2_"), text


# ---------------------------------------------------------------------------------- P1 rejections
def test_p1_rejects_contradictory_double_stage():
    out, audit, props = _run("Young leaves pubescent when mature.")
    assert _recovered(audit) == []


def test_p1_rejects_comparative_stage():
    out, audit, props = _run("branchlets pubescent as on young stems.")
    assert _recovered(audit) == []


def test_p1_rejects_container_substructure_scope():
    for text, lang in (
        ("Bark of young internodes glabrous.", "en"),
        ("Écorce des jeunes entrenoeuds glabre.", "fr"),
    ):
        out, audit, props = _run(text, language=lang)
        assert _recovered(audit) == [], text


def test_immature_as_bearer_head_is_not_a_context():
    # "immature" directly heads the bearer NP -> it is the bearer, not a context modifier.
    out, audit, props = _run("immature fruit green.", organ="fruits")
    rec = _recovered(audit)
    assert all(r["stage_pato"] != "PATO_0001501" for r in rec)


# --------------------------------------------------------------------------------------------- R2
def test_r2_plain_when_stage_two_members_away():
    out, audit, props = _run(
        "bractées obtuses, entièrement couvertes de poils, à l'état jeune violettes.",
        language="fr",
    )
    rec = [r for r in audit if r["surface_form"].startswith("obtus")]
    assert rec and rec[0]["disposition"] == "recovered_plain_stage_out_of_scope"
    plain = [a for a in out["assertions"] if a.get("raw_quality_text", "").startswith("obtus")]
    assert plain and not plain[0]["bearer_context_qualities"]
    assert plain[0]["normalization_status"] == "context_override"


def test_r2_rejects_member_with_local_stage_cue():
    # value's own member carries the stage -> not a plain recovery (it is conditioned).
    out, audit, props = _run("jeunes pousses glabres.", language="fr", organ="arbuste")
    assert all(
        r["disposition"] != "recovered_plain_stage_out_of_scope" for r in audit
    )


def test_r2_rejects_adjacent_cue_holds_for_review():
    # cue exactly one comma member away -> held, not auto-promoted.
    out, audit, props = _run("leaves elliptic, when young pubescent.")
    rec = [r for r in audit if r["surface_form"] == "elliptic"]
    assert rec and rec[0]["disposition"].startswith("r2_adjacent")


def test_r2_rejects_specimen_state_conditioned_value():
    # "brown ... when dry" -> brown is state-conditioned; not a plain unconditional recovery.
    out, audit, props = _run("Leaves brown when dry.")
    assert _recovered(audit) == []


# ------------------------------------------------------- adversarial guards (attack_fixtures.jsonl)
def test_guard_preposed_parenthetical_caveat():
    # F1-E / F2-B: a pre-posed (immature)/(seen only ...) caveat scopes the whole description.
    for text, organ in (
        ("Fruit (immature) 6 mm long, fusiform, densely pubescent.", "fruits"),
        ("Berries (seen only in immature stage) with several oblong seeds.", "fruits"),
    ):
        out, audit, props = _run(text, organ=organ)
        assert _recovered(audit) == [], text


def test_guard_leading_stage_scope_forward():
    # F2-A: a clause led by a bare stage cue elides that stage over later continuation members.
    out, audit, props = _run(
        "jeunes fusiformes, secs et indéhiscents, de 1,5 cm de long, tomenteux.",
        language="fr",
        organ="fruits",
    )
    assert all(
        r["disposition"] != "recovered_plain_stage_out_of_scope" for r in audit
    )


def test_guard_transition_clause_blocks_r2():
    # F3-x: a transition clause has shifting stage scope; keep plain recovery out of it.
    out, audit, props = _run(
        "Épis ellipsoïdes, devenant sphériques à maturité, à bractées brunes.",
        language="fr",
        organ="inflorescences",
    )
    assert all(
        r["disposition"] != "recovered_plain_stage_out_of_scope" for r in audit
    )


def test_guard_nested_structure_bearer_extended_predicate():
    # F1-A: white is the pith's, not the branch's, across the partitive "à moelle".
    out, audit, props = _run("rameaux jeunes à moelle blanche.", language="fr")
    assert _recovered(audit) == []


def test_no_reject_fixture_is_ever_promoted():
    """Every adversarial REJECT fixture must stay non-recovered (safety-critical invariant)."""

    import json
    import re

    fixtures = Path(
        "scratchpad/flopo-semantic-v2-20260718/claude-fanout-v3/"
        "developmental-stage/adversarial/attack_fixtures.jsonl"
    )
    if not fixtures.exists():  # scratchpad may be absent in a clean checkout
        return

    def organ_of(text: str) -> str:
        tl = text.lower()
        for kw, organ in (
            ("berr", "fruits"), ("fruit", "fruits"), ("aken", "fruits"), ("baie", "fruits"),
            ("epis", "inflorescences"), ("corolle", "corolla"), ("ligule", "leaves"),
            ("limbe", "lamina"), ("feuill", "feuilles"), ("leaf", "leaves"),
            ("leaves", "leaves"), ("rameau", "rameaux"), ("tige", "tiges"),
            ("stem", "stems"), ("branch", "branchlets"), ("flower", "flowers"),
        ):
            if kw in tl:
                return organ
        return "description"

    leaks = []
    for line in fixtures.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        fx = json.loads(line)
        if fx.get("expected") != "reject":
            continue
        text, val = fx["text"], fx.get("value_surface", "")
        start = text.find(val)
        if start < 0:
            continue
        lang = "fr" if re.search(r"[àâéèêîïôûç]| de | des | les ", text.lower()) else "en"
        record = {
            "source": "fx", "source_id": "x", "source_segment_index": 0, "taxon": "T",
            "organ": organ_of(text), "language": lang, "text": text, "assertions": [],
            "unresolved_spans": [{
                "start": start, "end": start + len(val), "surface_form": val,
                "reason": "developmental_stage_context",
                "candidate_pato_id": fx.get("value_pato") or "PATO_0000453",
                "extractor": "fx",
            }],
        }
        _out, audit, _props = recover_dev_record(record, _PO, _CAND)
        if any(r["disposition"].startswith("recovered") for r in audit):
            leaks.append((val, text[:70]))
    assert leaks == [], f"adversarial REJECT fixtures leaked: {leaks}"


# ------------------------------------------------------------------------------------- accounting
def test_accounting_identity_on_small_file(tmp_path):
    from flopo2.extract.developmental_stage_recovery import recover_file

    src = tmp_path / "in.jsonl"
    lines = []
    import json

    for text, organ, lang in (
        ("Young leaves pubescent.", "description", "en"),
        ("bractées obtuses, couvertes de poils, à l'état jeune violettes.", "description", "fr"),
        ("Leaves brown when dry.", "description", "en"),
        ("Leaves green.", "leaves", "en"),
    ):
        assertions, unresolved = extract_segment_with_unresolved(
            {"text": text, "organ": organ, "language": lang}
        )
        lines.append(
            json.dumps(
                {
                    "source": "flora-test",
                    "source_id": "s",
                    "source_segment_index": 0,
                    "taxon": "T",
                    "organ": organ,
                    "language": lang,
                    "text": text,
                    "assertions": assertions,
                    "unresolved_spans": unresolved,
                }
            )
        )
    src.write_text("\n".join(lines) + "\n", encoding="utf-8")
    acc = recover_file(
        src,
        tmp_path / "rec.jsonl",
        tmp_path / "aud.tsv",
        tmp_path / "prop.jsonl",
        tmp_path / "acc.json",
    )
    assert acc["identity_ok"]
    assert acc["dev_span_total_input"] == acc["promoted_total"] + acc["remaining_total"]
    assert acc["records_input"] == 4
    assert acc["records_output"] == 4
    assert (tmp_path / "rec.jsonl").read_text().count("\n") == 4
