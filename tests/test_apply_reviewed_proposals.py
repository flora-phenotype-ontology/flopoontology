from __future__ import annotations

import json

import pytest


def _segment() -> dict:
    return {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 3,
        "taxon": "Planta exemplaris",
        "text": "bracts lanceolate-triangular",
        "assertions": [],
        "source_statements": [],
        "unresolved_spans": [
            {
                "start": 7,
                "end": 17,
                "surface_form": "lanceolate",
                "reason": "hyphenated_or_slash_compound",
                "candidate_pato_id": "PATO_0001877",
            }
        ],
    }


def _proposal() -> dict:
    return {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 3,
        "taxon": "Planta exemplaris",
        "assertion": {
            "po_id": "PO_0009055",
            "pato_id": "PATO_0002338",
            "negated": False,
            "source_start": 7,
            "source_end": 28,
            "source_text": "lanceolate-triangular",
            "source_statement_id": "statement-reviewed",
            "value_operator": "atomic",
            "value_terms": [],
        },
        "source_statement": {
            "statement_id": "statement-reviewed",
            "verbatim_text": "lanceolate-triangular",
            "start": 7,
            "end": 28,
            "language": "en",
            "document_start": 7,
            "document_end": 28,
        },
    }


BARK_TEXT = "Bark smooth, brown or grey"
SMOOTH_ASSERTION = {
    "po_id": "PO_0004518",
    "pato_id": "PATO_0000970",
    "negated": False,
    "source_start": 5,
    "source_end": 11,
    "source_text": "smooth",
    "source_statement_id": "statement-smooth",
    "value_operator": "atomic",
    "value_terms": [],
}
BROWN_ASSERTION = {
    "po_id": "PO_0004518",
    "pato_id": "PATO_0000014",
    "negated": False,
    "source_start": 13,
    "source_end": 18,
    "source_text": "brown",
    "source_statement_id": "statement-brown",
    "value_operator": "atomic",
    "value_terms": [],
}
BROWN_SELECTOR = {
    "po_id": "PO_0004518",
    "pato_id": "PATO_0000014",
    "negated": False,
    "source_start": 13,
    "source_end": 18,
    "value_operator": "atomic",
    "value_terms": [],
}


def _bark_segment() -> dict:
    return {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 4,
        "taxon": "Planta exemplaris",
        "text": BARK_TEXT,
        "assertions": [dict(SMOOTH_ASSERTION), dict(BROWN_ASSERTION)],
        "source_statements": [
            {
                "statement_id": "statement-smooth",
                "verbatim_text": "smooth",
                "start": 5,
                "end": 11,
                "language": "en",
                "document_start": 5,
                "document_end": 11,
            },
            {
                "statement_id": "statement-brown",
                "verbatim_text": "brown",
                "start": 13,
                "end": 18,
                "language": "en",
                "document_start": 13,
                "document_end": 18,
            },
        ],
        "unresolved_spans": [
            {"start": 22, "end": 26, "surface_form": "grey", "reason": "logical"}
        ],
    }


def _bark_proposal() -> dict:
    return {
        "source": "flora-test",
        "source_id": "volume.xml",
        "source_segment_index": 4,
        "taxon": "Planta exemplaris",
        "assertion": {
            "po_id": "PO_0004518",
            "pato_id": "PATO_0000014",
            "negated": False,
            "source_start": 13,
            "source_end": 26,
            "source_text": "brown or grey",
            "source_statement_id": "statement-colour",
            "value_operator": "one_of",
            "value_terms": ["PATO_0000952", "PATO_0000954"],
        },
        "source_statement": {
            "statement_id": "statement-colour",
            "verbatim_text": "brown or grey",
            "start": 13,
            "end": 26,
            "language": "en",
            "document_start": 13,
            "document_end": 26,
        },
        "apply": {
            "clear_unresolved_spans": [{"start": 22, "end": 26}],
            "remove_assertions": [dict(BROWN_SELECTOR)],
        },
    }


def _write(tmp_path, segment, proposals):
    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    input_path.write_text(json.dumps(segment) + "\n", encoding="utf-8")
    proposal_path.write_text(
        "".join(json.dumps(proposal) + "\n" for proposal in proposals), encoding="utf-8"
    )
    return input_path, proposal_path, tmp_path / "output.jsonl"


def test_apply_reviewed_proposal_adds_assertion_provenance_and_clears_component(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(_segment()) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps(_proposal()) + "\n", encoding="utf-8")

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["assertions_added"] == 1
    assert report["source_statements_added"] == 1
    assert report["unresolved_spans_removed"] == 1
    assert row["assertions"][0]["pato_id"] == "PATO_0002338"
    assert row["source_statements"][0]["statement_id"] == "statement-reviewed"
    assert row["unresolved_spans"] == []


def test_apply_reviewed_proposal_rejects_offset_mismatch(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    input_path.write_text(json.dumps(_segment()) + "\n", encoding="utf-8")
    proposal = _proposal()
    proposal["assertion"]["source_text"] = "wrong"
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="evidence mismatch"):
        apply_reviewed_proposals(input_path, proposal_path, tmp_path / "output.jsonl")


def test_apply_reviewed_proposal_requires_an_exact_segment_match(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    input_path.write_text(json.dumps(_segment()) + "\n", encoding="utf-8")
    proposal = _proposal()
    proposal["source_id"] = "missing.xml"
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="not matched exactly once"):
        apply_reviewed_proposals(input_path, proposal_path, tmp_path / "output.jsonl")
    assert not (tmp_path / "output.jsonl").exists()


def test_exact_clear_list_preserves_other_span_inside_expression(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    segment = _segment()
    segment["text"] = "bracts opaque, lanceolate or triangular"
    segment["unresolved_spans"] = [
        {"start": 7, "end": 13, "surface_form": "opaque", "reason": "other"},
        {"start": 15, "end": 25, "surface_form": "lanceolate", "reason": "logical"},
        {"start": 29, "end": 39, "surface_form": "triangular", "reason": "logical"},
    ]
    proposal = _proposal()
    proposal["assertion"].update(
        {
            "source_start": 7,
            "source_end": 39,
            "source_text": "opaque, lanceolate or triangular",
        }
    )
    proposal["source_statement"].update(
        {
            "verbatim_text": "opaque, lanceolate or triangular",
            "start": 7,
            "end": 39,
            "document_start": 7,
            "document_end": 39,
        }
    )
    proposal["apply"] = {
        "clear_unresolved_spans": [
            {"start": 15, "end": 25},
            {"start": 29, "end": 39},
        ]
    }
    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(segment) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["unresolved_spans_removed"] == 2
    assert [(span["start"], span["end"]) for span in row["unresolved_spans"]] == [(7, 13)]


def test_exact_clear_list_must_match_an_unresolved_span_once(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(_segment()) + "\n", encoding="utf-8")
    proposal = _proposal()
    proposal["apply"] = {"clear_unresolved_spans": [{"start": 18, "end": 28}]}
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="clear ranges did not match exactly once"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_existing_source_statement_id_must_have_same_evidence(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    segment = _segment()
    existing = dict(_proposal()["source_statement"])
    existing["verbatim_text"] = "different evidence"
    segment["source_statements"] = [existing]
    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(segment) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps(_proposal()) + "\n", encoding="utf-8")
    output_path.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(ValueError, match="source statement identity collision"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert output_path.read_text(encoding="utf-8") == "preserve me\n"


def test_nested_added_source_statement_is_supported(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _proposal()
    statement = proposal.pop("source_statement")
    proposal["apply"] = {"added_source_statements": [statement]}
    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(_segment()) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)

    assert report["source_statements_added"] == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_statements"] == [statement]


def test_existing_source_statement_can_supply_proposal_evidence(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _proposal()
    statement = proposal.pop("source_statement")
    segment = _segment()
    segment["source_statements"] = [statement]
    input_path = tmp_path / "input.jsonl"
    proposal_path = tmp_path / "proposals.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(json.dumps(segment) + "\n", encoding="utf-8")
    proposal_path.write_text(json.dumps(proposal) + "\n", encoding="utf-8")

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)

    assert report.get("source_statements_added", 0) == 0
    assert json.loads(output_path.read_text(encoding="utf-8"))["source_statements"] == [statement]


def test_removal_replaces_atomic_with_union_and_retains_independent_conjunct(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    input_path, proposal_path, output_path = _write(
        tmp_path, _bark_segment(), [_bark_proposal()]
    )

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8"))

    assert report["assertions_added"] == 1
    assert report["assertions_removed"] == 1
    assert report["unresolved_spans_removed"] == 1
    assert [
        (assertion["pato_id"], assertion["value_operator"], assertion["source_end"])
        for assertion in row["assertions"]
    ] == [("PATO_0000970", "atomic", 11), ("PATO_0000014", "one_of", 26)]
    # the superseded assertion's provenance is retained as evidence
    assert [statement["statement_id"] for statement in row["source_statements"]] == [
        "statement-smooth",
        "statement-brown",
        "statement-colour",
    ]
    assert row["unresolved_spans"] == []


def test_absent_removal_list_keeps_append_only_behaviour(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    del proposal["apply"]["remove_assertions"]
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8"))

    assert report.get("assertions_removed", 0) == 0
    assert len(row["assertions"]) == 3


def test_removal_list_must_not_be_empty(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"] = []
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="empty or malformed removal list"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_removal_selector_matching_no_assertion_fails(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"][0]["source_end"] = 17
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="removal selector matched 0 assertions"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_removal_selector_matching_several_assertions_fails(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    segment = _bark_segment()
    segment["assertions"].append(dict(BROWN_ASSERTION))
    input_path, proposal_path, output_path = _write(tmp_path, segment, [_bark_proposal()])

    with pytest.raises(ValueError, match="removal selector matched 2 assertions"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


@pytest.mark.parametrize("field", sorted(BROWN_SELECTOR))
def test_incomplete_removal_selector_fails(tmp_path, field):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    del proposal["apply"]["remove_assertions"][0][field]
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match=f"removal selector is incomplete .*{field}"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


@pytest.mark.parametrize(
    "field,value",
    [
        ("po_id", ""),
        ("po_id", None),
        ("pato_id", 14),
        ("negated", "false"),
        ("negated", 0),
        ("source_start", "13"),
        ("source_start", True),
        ("source_start", -1),
        ("source_end", 13),
        ("value_operator", ""),
        ("value_terms", "PATO_0000952"),
        ("value_terms", [""]),
        ("value_terms", [None]),
    ],
)
def test_malformed_removal_selector_value_fails(tmp_path, field, value):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"][0][field] = value
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="removal selector"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_removal_selector_with_extra_field_fails(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"][0]["source_text"] = "brown"
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="removal selector has unknown fields"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_duplicate_removal_selector_within_a_proposal_fails(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"].append(dict(BROWN_SELECTOR))
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="duplicate removal selectors"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_duplicate_removal_selector_across_proposals_fails(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    second = _bark_proposal()
    second["assertion"]["value_terms"] = ["PATO_0000954", "PATO_0000952"]
    second["apply"] = {"remove_assertions": [dict(BROWN_SELECTOR)]}
    input_path, proposal_path, output_path = _write(
        tmp_path, _bark_segment(), [_bark_proposal(), second]
    )

    with pytest.raises(ValueError, match="duplicate removal selectors"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_proposal_cannot_remove_the_assertion_it_adds(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    proposal = _bark_proposal()
    proposal["apply"]["remove_assertions"] = [
        {
            "po_id": "PO_0004518",
            "pato_id": "PATO_0000014",
            "negated": False,
            "source_start": 13,
            "source_end": 26,
            "value_operator": "one_of",
            "value_terms": ["PATO_0000952", "PATO_0000954"],
        }
    ]
    input_path, proposal_path, output_path = _write(tmp_path, _bark_segment(), [proposal])

    with pytest.raises(ValueError, match="removes the assertion it adds"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_proposal_cannot_remove_an_assertion_another_proposal_adds(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    second = _bark_proposal()
    second["assertion"] = dict(BROWN_ASSERTION)
    second["source_statement"] = {
        "statement_id": "statement-brown",
        "verbatim_text": "brown",
        "start": 13,
        "end": 18,
        "language": "en",
        "document_start": 13,
        "document_end": 18,
    }
    second["assertion"]["source_statement_id"] = "statement-brown"
    del second["apply"]
    input_path, proposal_path, output_path = _write(
        tmp_path, _bark_segment(), [_bark_proposal(), second]
    )

    with pytest.raises(ValueError, match="removes an assertion added"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert not output_path.exists()


def test_removal_never_infers_an_independent_conjunct_from_range_overlap(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    segment = _bark_segment()
    proposal = _bark_proposal()
    proposal["assertion"].update(
        {"source_start": 5, "source_end": 26, "source_text": "smooth, brown or grey"}
    )
    proposal["source_statement"].update(
        {
            "verbatim_text": "smooth, brown or grey",
            "start": 5,
            "end": 26,
            "document_start": 5,
            "document_end": 26,
        }
    )
    input_path, proposal_path, output_path = _write(tmp_path, segment, [proposal])

    report = apply_reviewed_proposals(input_path, proposal_path, output_path)
    row = json.loads(output_path.read_text(encoding="utf-8"))

    # only the explicitly selected `brown` is removed; `smooth` survives the wider source range
    assert report["assertions_removed"] == 1
    assert [assertion["pato_id"] for assertion in row["assertions"]] == [
        "PATO_0000970",
        "PATO_0000014",
    ]
    assert row["assertions"][0]["source_text"] == "smooth"


def test_invalid_proposal_beside_a_valid_one_leaves_existing_output_intact(tmp_path):
    from flopo2.verify.apply_reviewed_proposals import apply_reviewed_proposals

    invalid = _bark_proposal()
    invalid["assertion"] = dict(SMOOTH_ASSERTION)
    invalid["assertion"]["source_statement_id"] = "statement-smooth"
    invalid["source_statement"] = {
        "statement_id": "statement-smooth",
        "verbatim_text": "smooth",
        "start": 5,
        "end": 11,
        "language": "en",
        "document_start": 5,
        "document_end": 11,
    }
    invalid["apply"] = {
        "remove_assertions": [dict(BROWN_SELECTOR, pato_id="PATO_9999999")]
    }
    input_path, proposal_path, output_path = _write(
        tmp_path, _bark_segment(), [_bark_proposal(), invalid]
    )
    output_path.write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(ValueError, match="removal selector matched 0 assertions"):
        apply_reviewed_proposals(input_path, proposal_path, output_path)
    assert output_path.read_text(encoding="utf-8") == "preserve me\n"
