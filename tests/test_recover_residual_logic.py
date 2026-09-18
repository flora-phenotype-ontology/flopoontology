from __future__ import annotations

import json


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000014
name: color
subset: attribute_slim

[Term]
id: PATO:0000322
name: red
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000320
name: green
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000323
name: white
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000954
name: pink
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000052
name: shape
subset: attribute_slim

[Term]
id: PATO:0001891
name: ovate
subset: value_slim
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000947
name: elliptic
subset: value_slim
is_a: PATO:0000052 ! shape
"""


def _lexicon(tmp_path):
    from flopo2.verify.recover_explicit_unions import ExactPatoValueLexicon

    pato = tmp_path / "pato.obo"
    pato.write_text(PATO_OBO, encoding="utf-8")
    return ExactPatoValueLexicon.load(pato)


def _record(
    text: str,
    spans: list[tuple[str, str, str]],
    *,
    source: str = "test-flora",
    source_id: str = "source-1",
) -> dict:
    cursor = 0
    unresolved = []
    for surface, pato_id, reason in spans:
        start = text.index(surface, cursor)
        end = start + len(surface)
        cursor = end
        unresolved.append(
            {
                "start": start,
                "end": end,
                "surface_form": surface,
                "reason": reason,
                "candidate_pato_id": pato_id,
                "extractor": "deterministic_baseline",
            }
        )
    return {
        "source": source,
        "source_id": source_id,
        "source_segment_index": 0,
        "taxon": "Testus example",
        "organ": "petals",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": unresolved,
    }


def test_recovers_complete_conjunction_as_fac_all_of(tmp_path):
    from flopo2.verify.recover_residual_logic import EXTRACTOR, recover_record

    record = _record(
        "Petals red and white.",
        [
            ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
            ("white", "PATO_0000323", "same_attribute_composite_or_transition"),
        ],
    )

    recovered, outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["unresolved_spans"] == []
    assert len(recovered["assertions"]) == 1
    assertion = recovered["assertions"][0]
    assert assertion["po_id"] == "PO_0009032"
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["value_operator"] == "all_of"
    assert assertion["value_terms"] == ["PATO_0000322", "PATO_0000323"]
    assert assertion["source_text"] == "red and white"
    assert assertion["extractor"] == EXTRACTOR
    assert "phenotype_class_iri" not in assertion
    assert "flopo_id" not in assertion
    assert outcomes["promoted_assertions"] == 1
    assert decisions[0].route == "FAC_all_of"


def test_recovers_complete_union_with_unspanned_exact_operand(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    # The baseline knew ``white`` but treated nearby ``pink`` as unsupported.  The residual
    # pass may ground the complete exact three-way expression even though only one operand was
    # represented by an unresolved span.
    record = _record(
        "Petals white, pink or red.",
        [("white", "PATO_0000323", "unsupported_same_attribute_neighbor")],
    )

    recovered, outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assertion = recovered["assertions"][0]
    assert assertion["value_operator"] == "one_of"
    assert assertion["value_terms"] == [
        "PATO_0000323",
        "PATO_0000954",
        "PATO_0000322",
    ]
    assert assertion["value_text"] == "white, pink or red"
    assert recovered["unresolved_spans"] == []
    assert outcomes["resolved_evidence_spans"] == 1
    assert decisions[0].input_reasons == ("unsupported_same_attribute_neighbor",)


def test_rejects_mixed_logical_operators(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Petals red or white and green.",
        [
            ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
            ("white", "PATO_0000323", "same_attribute_composite_or_transition"),
            ("green", "PATO_0000320", "same_attribute_composite_or_transition"),
        ],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 3
    assert {decision.reason for decision in decisions} == {"mixed_logical_operators"}
    assert {decision.route for decision in decisions} == {"logical_expression_review"}


def test_routes_qualitative_range_without_promoting(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Leaves ovate to elliptic.",
        [
            ("ovate", "PATO_0001891", "same_attribute_composite_or_transition"),
            ("elliptic", "PATO_0000947", "same_attribute_composite_or_transition"),
        ],
    )
    record["organ"] = "leaves"

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 2
    assert {decision.route for decision in decisions} == {"qualitative_range_or_transition"}


def test_routes_temporal_transition_before_range(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Fruits green turning red.",
        [
            ("green", "PATO_0000320", "same_attribute_composite_or_transition"),
            ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
        ],
    )
    record["organ"] = "fruits"

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert {decision.route for decision in decisions} == {"temporal_or_developmental"}


def test_unrelated_later_temporal_phrase_does_not_override_attached_range(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Leaves ovate to elliptic, green at first.",
        [
            ("ovate", "PATO_0001891", "same_attribute_composite_or_transition"),
            ("elliptic", "PATO_0000947", "same_attribute_composite_or_transition"),
        ],
    )
    record["organ"] = "leaves"

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert {decision.route for decision in decisions} == {"qualitative_range_or_transition"}


def test_adjacent_number_is_typed_context_not_logical_value(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Ovary sessile à 5 locules.",
        [("sessile", "PATO_0001436", "unsupported_alternative_or_transition")],
    )
    record["organ"] = "ovary"

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert decisions[0].route == "numeric_or_cardinality_context"
    assert decisions[0].reason == "adjacent_numeric_context"


def test_requires_same_explicit_bearer_occurrence(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Petals red and white sepals.",
        [
            ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
            ("white", "PATO_0000323", "same_attribute_composite_or_transition"),
        ],
    )

    recovered, _outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"] == record["unresolved_spans"]
    assert all(
        decision.route in {"logical_expression_review", "bearer_review"} for decision in decisions
    )


def test_independently_audited_locative_is_out_of_scope(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Petals red and white.",
        [
            ("red", "PATO_0000322", "unsupported_alternative_or_transition"),
            ("white", "PATO_0000323", "unsupported_alternative_or_transition"),
        ],
        source="flora-gabon",
    )
    first = record["unresolved_spans"][0]
    key = (
        "flora-gabon",
        "source-1",
        0,
        first["start"],
        first["end"],
        first["candidate_pato_id"],
    )

    recovered, _outcomes, decisions = recover_record(
        record, _lexicon(tmp_path), locative_keys=frozenset({key})
    )

    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"] == record["unresolved_spans"]
    assert {decision.route for decision in decisions} == {"locative_context"}


def test_existing_equivalent_assertion_resolves_evidence_without_duplicate(tmp_path):
    from flopo2.verify.recover_residual_logic import recover_record

    record = _record(
        "Petals red and white.",
        [
            ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
            ("white", "PATO_0000323", "same_attribute_composite_or_transition"),
        ],
    )
    record["assertions"] = [
        {
            "po_id": "PO_0009032",
            "pato_id": "PATO_0000014",
            "source_start": 7,
            "source_end": 20,
            "source_text": "red and white",
            "value_operator": "all_of",
            "value_terms": ["PATO_0000322", "PATO_0000323"],
        }
    ]

    recovered, outcomes, decisions = recover_record(record, _lexicon(tmp_path))

    assert len(recovered["assertions"]) == 1
    assert recovered["unresolved_spans"] == []
    assert outcomes["resolved_by_existing_assertion"] == 1
    assert decisions[0].status == "resolved_existing"


def test_file_report_invariants_and_bearer_source_stratified_sample(tmp_path):
    import csv

    from flopo2.verify.recover_residual_logic import recover_file, write_reviewed_sample

    records = [
        _record(
            "Petals red and white.",
            [
                ("red", "PATO_0000322", "same_attribute_composite_or_transition"),
                ("white", "PATO_0000323", "same_attribute_composite_or_transition"),
            ],
            source="flora-a",
            source_id="a",
        ),
        _record(
            "Leaves ovate or elliptic.",
            [("ovate", "PATO_0001891", "unsupported_same_attribute_neighbor")],
            source="flora-b",
            source_id="b",
        ),
    ]
    records[1]["organ"] = "leaves"
    input_path = tmp_path / "input.jsonl"
    input_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )
    pato = tmp_path / "pato.obo"
    pato.write_text(PATO_OBO, encoding="utf-8")

    report = recover_file(
        input_path,
        tmp_path / "output.jsonl",
        decisions_tsv=tmp_path / "decisions.tsv",
        pato_obo=pato,
        sample_tsv=tmp_path / "sample.tsv",
        sample_size=50,
    )

    assert report["result"] == "pass"
    assert all(report["invariants"].values())
    assert report["promoted_by_source"] == {"flora-a": 1, "flora-b": 1}
    assert report["promoted_by_operator"] == {"all_of": 1, "one_of": 1}
    assert report["sample"]["sample_size"] == 2
    assert report["sample"]["sources"] == {"flora-a": 1, "flora-b": 1}
    assert report["sample"]["bearers"] == {"PO_0009025": 1, "PO_0009032": 1}

    reviewed = tmp_path / "sample-reviewed.tsv"
    assert (
        write_reviewed_sample(
            tmp_path / "sample.tsv",
            reviewed,
            semantic_judgment="correct",
            bearer_judgment="correct",
            completeness_judgment="complete",
            review_note="independent audit",
        )
        == 2
    )
    with reviewed.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert {row["semantic_judgment"] for row in rows} == {"correct"}
    assert {row["review_note"] for row in rows} == {"independent audit"}
