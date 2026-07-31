from __future__ import annotations

import csv
import json


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000014
name: color

[Term]
id: PATO:0000322
name: red
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000320
name: green
subset: value_slim
synonym: "verdant" RELATED []
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000318
name: blue
subset: value_slim
synonym: "azure" EXACT []
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000323
name: white
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000052
name: shape

[Term]
id: PATO:0001891
name: ovate
subset: value_slim
synonym: "ovoid" EXACT []
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000946
name: oblong
subset: value_slim
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000944
name: sharpness
subset: attribute_slim
synonym: "apiculate" EXACT []
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000414
name: unbranched
subset: value_slim
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000402
name: branched
subset: value_slim
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000066
name: pilosity

[Term]
id: PATO:0000453
name: glabrous
subset: value_slim
is_a: PATO:0000066 ! pilosity

[Term]
id: PATO:0000454
name: hairy
subset: value_slim
is_a: PATO:0000066 ! pilosity
"""


def _record(
    text: str,
    operands: list[tuple[str, str]],
    *,
    organ: str = "petals",
    source: str = "test-flora",
) -> dict:
    cursor = 0
    spans = []
    for surface, pato_id in operands:
        start = text.index(surface, cursor)
        cursor = start + len(surface)
        spans.append(
            {
                "start": start,
                "end": cursor,
                "surface_form": surface,
                "reason": "explicit_disjunction",
                "candidate_pato_id": pato_id,
                "extractor": "deterministic_baseline",
            }
        )
    return {
        "source": source,
        "source_id": "source-1",
        "source_segment_index": 0,
        "taxon": "Testus example",
        "organ": organ,
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": spans,
    }


def _lexicon(tmp_path):
    from flopo2.verify.recover_explicit_unions import ExactPatoValueLexicon

    path = tmp_path / "pato.obo"
    path.write_text(PATO_OBO, encoding="utf-8")
    return ExactPatoValueLexicon.load(path)


def test_lexicon_uses_preferred_and_exact_but_not_related_synonyms(tmp_path):
    lexicon = _lexicon(tmp_path)

    assert lexicon.forms["red"].pato_id == "PATO_0000322"
    assert lexicon.forms["azure"].pato_id == "PATO_0000318"
    assert "verdant" not in lexicon.forms
    assert "apiculate" not in lexicon.forms
    assert "ovoid" not in lexicon.forms


def test_promotes_complete_same_explicit_bearer_union_and_removes_evidence(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    recovered, outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["unresolved_spans"] == []
    assert len(recovered["assertions"]) == 1
    assertion = recovered["assertions"][0]
    assert assertion["po_id"] == "PO_0009032"
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["value_operator"] == "one_of"
    assert assertion["value_terms"] == ["PATO_0000322", "PATO_0000320"]
    assert assertion["source_text"] == "red or green"
    assert assertion["value_text"] == "red or green"
    assert assertion["extractor"] == (
        "deterministic_exact_pato_explicit_union_recovery"
    )
    assert outcomes["promoted_assertions"] == 1
    assert outcomes["resolved_evidence_spans"] == 2
    assert decisions[0].status == "promoted"
    assert decisions[0].bearer_surface == "Petals"


def test_promotes_complete_ternary_union_in_source_order(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red, green or azure.",
        [
            ("red", "PATO_0000322"),
            ("green", "PATO_0000320"),
            ("azure", "PATO_0000318"),
        ],
    )

    recovered, outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"][0]["value_terms"] == [
        "PATO_0000322",
        "PATO_0000320",
        "PATO_0000318",
    ]
    assert recovered["unresolved_spans"] == []
    assert outcomes["promoted_arity:3"] == 1
    assert decisions[0].arity == 3


def test_source_span_includes_closing_logical_parenthesis(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red (or green).",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"][0]["source_text"] == "red (or green)"
    assert recovered["assertions"][0]["value_text"] == "red (or green)"
    assert decisions[0].expression_text == "red (or green)"


def test_routes_heading_only_different_bearers_and_related_operand(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    cases = (
        (
            _record(
                "Red or green.",
                [("Red", "PATO_0000322"), ("green", "PATO_0000320")],
            ),
            "heading_only_or_missing",
        ),
        (
            _record(
                "Petals red or sepals green.",
                [("red", "PATO_0000322"), ("green", "PATO_0000320")],
            ),
            "modified_or_ungrounded_right_operand",
        ),
        (
            _record(
                "Petals red or green sepals.",
                [("red", "PATO_0000322"), ("green", "PATO_0000320")],
            ),
            "different_explicit_bearers",
        ),
        (
            _record(
                "Petals red or verdant.",
                [("red", "PATO_0000322"), ("verdant", "PATO_0000320")],
            ),
            "ungrounded_operand",
        ),
    )
    for record, expected_reason in cases:
        recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"] == record["unresolved_spans"]
        assert expected_reason in {decision.reason for decision in decisions}


def test_routes_transition_hyphen_substring_and_subregion_scope(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    cases = (
        (
            _record(
                "Petals white to red or green.",
                [("red", "PATO_0000322"), ("green", "PATO_0000320")],
            ),
            "transition_context",
        ),
        (
            _record(
                "Petals red-orange or green.",
                [("red", "PATO_0000322"), ("green", "PATO_0000320")],
            ),
            "ungrounded_operand",
        ),
        (
            _record(
                "Petal margins red or green.",
                [("red", "PATO_0000322"), ("green", "PATO_0000320")],
                organ="petals",
            ),
            "blocked_local",
        ),
    )
    for record, expected_reason in cases:
        recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))
        assert recovered["assertions"] == []
        assert expected_reason in {decision.reason for decision in decisions}


def test_does_not_promote_when_one_unresolved_operand_is_not_covered(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red, chartreuse or green.",
        [
            ("red", "PATO_0000322"),
            ("chartreuse", "PATO_missing"),
            ("green", "PATO_0000320"),
        ],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"] == record["unresolved_spans"]
    assert any("ungrounded" in decision.reason for decision in decisions)


def test_routes_partial_adjacent_list_and_qualified_bearer(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    partial = _record(
        "Petals red or green, or chartreuse.",
        [
            ("red", "PATO_0000322"),
            ("green", "PATO_0000320"),
            ("chartreuse", "PATO_missing"),
        ],
    )
    qualified = _record(
        "Inner petals red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )
    subset = _record(
        "Lowermost petals red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    partial_result, _outcomes, partial_decisions = recover_record(
        partial, _lexicon(tmp_path)
    )
    qualified_result, _outcomes, qualified_decisions = recover_record(
        qualified, _lexicon(tmp_path)
    )
    subset_result, _outcomes, subset_decisions = recover_record(
        subset, _lexicon(tmp_path)
    )

    assert partial_result["assertions"] == []
    assert qualified_result["assertions"] == []
    assert subset_result["assertions"] == []
    assert "incomplete_adjacent_alternative" in {
        decision.reason for decision in partial_decisions
    }
    assert "blocked_local" in {
        decision.reason for decision in qualified_decisions
    }
    assert "qualified_bearer_subset" in {
        decision.reason for decision in subset_decisions
    }


def test_routes_developmental_colour_change(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red or green, turning brown.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert "developmental_stage_context" in {
        decision.reason for decision in decisions
    }


def test_promotes_union_before_unrelated_comparison_in_following_predicate(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Fruit red or green, shaped like a fig.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
        organ="fruits",
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert len(recovered["assertions"]) == 1
    assert recovered["assertions"][0]["po_id"] == "PO_0009001"
    assert decisions[0].status == "promoted"


def test_routes_comparison_that_directly_scopes_union(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals resembling red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert "comparative_context" in {decision.reason for decision in decisions}


def test_promotes_union_before_unrelated_hyphen_like_part(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Leaves ovate or oblong, base tapering into the sheath-like petiole.",
        [("ovate", "PATO_0001891"), ("oblong", "PATO_0000946")],
        organ="leaves",
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert len(recovered["assertions"]) == 1
    assert decisions[0].status == "promoted"


def test_following_blocked_noun_does_not_steal_preceding_union_bearer(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Fruits red or green, with scales on the outside.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
        organ="fruits",
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert len(recovered["assertions"]) == 1
    assert recovered["assertions"][0]["po_id"] == "PO_0009001"
    assert decisions[0].status == "promoted"


def test_prior_semicolon_member_does_not_make_local_bearer_ambiguous(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Leaves opposite, petioles compressed; stipules interpetiolar, red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
        organ="stipules",
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert len(recovered["assertions"]) == 1
    assert recovered["assertions"][0]["po_id"] == "PO_0020041"
    assert decisions[0].status == "promoted"


def test_routes_union_explicitly_excluded_from_flora_geographic_scope(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Flowers red (or green, not in Malesia).",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
        organ="flowers",
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert "excluded_geographic_scope" in {decision.reason for decision in decisions}


def test_does_not_flatten_two_adjacent_disjunctions_into_one_union(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Petals red or green, white or blue.",
        [
            ("red", "PATO_0000322"),
            ("green", "PATO_0000320"),
            ("white", "PATO_0000323"),
            ("blue", "PATO_0000318"),
        ],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert {
        decision.reason for decision in decisions if decision.status == "routed"
    } == {"incomplete_adjacent_alternative"}


def test_routes_relational_object_instead_of_inheriting_nearest_bearer(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_record

    record = _record(
        "Undershrub with numerous shoots from a thick woody rhizome, "
        "unbranched or branched.",
        [("unbranched", "PATO_0000414"), ("branched", "PATO_0000402")],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert "intervening_relational_object_bearer" in {
        decision.reason for decision in decisions
    }


def test_recover_file_writes_routed_candidates_and_deterministic_sample(tmp_path):
    from flopo2.verify.recover_explicit_unions import recover_file

    pato = tmp_path / "pato.obo"
    pato.write_text(PATO_OBO, encoding="utf-8")
    input_path = tmp_path / "input.jsonl"
    records = [
        _record(
            "Petals red or green.",
            [("red", "PATO_0000322"), ("green", "PATO_0000320")],
            source="flora-a",
        ),
        _record(
            "Petals red, green or blue.",
            [
                ("red", "PATO_0000322"),
                ("green", "PATO_0000320"),
                ("blue", "PATO_0000318"),
            ],
            source="flora-b",
        ),
    ]
    input_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    output = tmp_path / "output.jsonl"
    candidates = tmp_path / "candidates.tsv"
    sample = tmp_path / "sample.tsv"

    report = recover_file(
        input_path,
        output,
        candidate_tsv=candidates,
        pato_obo=pato,
        sample_tsv=sample,
        sample_seed=7,
        sample_size=2,
    )

    assert report["promoted_by_arity"] == {"2": 1, "3": 1}
    assert report["sample"]["sample_size"] == 2
    with candidates.open(encoding="utf-8") as handle:
        candidate_rows = list(csv.DictReader(handle, delimiter="\t"))
    with sample.open(encoding="utf-8") as handle:
        sample_rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["status"] for row in candidate_rows} == {"promoted"}
    assert {(row["source"], row["arity"]) for row in sample_rows} == {
        ("flora-a", "2"),
        ("flora-b", "3"),
    }


def test_recover_file_never_overwrites_input(tmp_path):
    import pytest

    from flopo2.verify.recover_explicit_unions import recover_file

    path = tmp_path / "input.jsonl"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        recover_file(path, path, candidate_tsv=tmp_path / "candidates.tsv")
