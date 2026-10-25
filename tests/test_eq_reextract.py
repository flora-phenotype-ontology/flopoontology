import pytest

from flopo2.verify.eq_reextract import validate, representative_examples


def item():
    return {
        "entity_candidates": [{"id": "PO_leaf"}],
        "quality_candidates": [{"id": "PATO_red"}],
        "evidence": [{"id": "e1", "passage": "Leaves red when young."}],
    }


def answer():
    return {
        "status": "extracted",
        "eqs": [
            {
                "evidence_id": "e1",
                "entity_id": "PO_leaf",
                "quality_id": "PATO_red",
                "quote": "Leaves red",
                "mapping": "exact",
                "qualifiers": {
                    "negated": False,
                    "stage": "young",
                    "frequency": "",
                    "degree": "",
                    "operator": "atomic",
                },
            }
        ],
    }


def test_grounded_extraction_preserves_context():
    result = validate(answer(), item())
    assert result["eqs"][0]["qualifiers"]["stage"] == "young"


@pytest.mark.parametrize(
    "field,value",
    [
        ("entity_id", "PO_invented"),
        ("quality_id", "PO_leaf"),
        ("quote", "Leaves blue"),
        ("quote", ""),
        ("evidence_id", "wrong"),
    ],
)
def test_invented_identifier_or_unanchored_quote_is_rejected(field, value):
    result = answer()
    result["eqs"][0][field] = value
    with pytest.raises(ValueError):
        validate(result, item())


def test_no_mapping_cannot_smuggle_an_eq_into_the_candidate_list():
    result = answer()
    result["status"] = "no_mapping"
    with pytest.raises(ValueError):
        validate(result, item())


def test_qualifiers_are_required():
    result = answer()
    result["eqs"][0]["qualifiers"].pop("negated")
    with pytest.raises(ValueError):
        validate(result, item())


def test_examples_prioritize_distinct_sources():
    rows = [
        {"id": str(n), "source": s, "source_id": str(n), "original_phrase": "leaf red"}
        for n, s in enumerate(["a", "a", "a", "b", "c"])
    ]
    assert {r["source"] for r in representative_examples(rows)} == {"a", "b", "c"}


def test_outcome_recording_requires_every_exact_proposal(tmp_path):
    from types import SimpleNamespace
    from flopo2.verify.eq_reextract import record
    from flopo2.verify.eq_release import write_tsv, save_json, read_tsv

    write_tsv(
        tmp_path / "extractions.tsv",
        [
            {
                "original_signature": "old",
                "proposed_signature": "corrected",
                "mapping": "exact",
            }
        ],
    )
    save_json(tmp_path / "export-manifest.json", {"original_targets": 1})
    dispositions = tmp_path / "dispositions.tsv"
    write_tsv(dispositions, [], fields=["signature", "status", "disposition", "flopo_iri"])
    args = SimpleNamespace(
        work=tmp_path, dispositions=dispositions, outcomes=tmp_path / "outcomes.tsv"
    )
    with pytest.raises(ValueError, match="exactly"):
        record(args)
    assert not args.outcomes.exists()
    write_tsv(
        dispositions,
        [
            {
                "signature": "corrected",
                "status": "pass",
                "disposition": "equivalent_reuse",
                "flopo_iri": "existing",
            }
        ],
    )
    record(args)
    result = read_tsv(args.outcomes)[0]
    assert result["original_signature"] == "old"
    assert result["disposition"] == "equivalent_reuse"
    assert result["flopo_iri"] == "existing"


def test_endpoint_switch_preserves_original_cache_identity():
    from flopo2.verify.eq_reextract import cached_request, PROMPT_VERSION
    from flopo2.verify.eq_release import digest

    request = {"model": "qwen", "messages": ["same question"]}
    old = digest({"version": PROMPT_VERSION, "endpoint": "old", "payload": request})
    cache = {old: {"answer": {"status": "extracted"}}}
    assert cached_request(request, "new", ["old"], cache) == (old, "old")
    assert cached_request(request, "new", [], cache)[1] == "new"
    assert cached_request({**request, "model": "another"}, "new", ["old"], cache)[1] == "new"


def test_current_ledger_keeps_partial_and_deterministic_failures_open():
    from flopo2.verify.eq_reextract import current_dispositions

    old = [
        {
            "signature": s,
            "status": "pass" if s == "initial" else "triage",
            "label": s,
            "flopo_iri": "existing" if s == "initial" else "",
            "reasons": "",
        }
        for s in ["initial", "resolved", "partial", "deterministic"]
    ]
    rows = [
        {
            "original_signature": s,
            "validation": v,
            "flopo_iri": "accepted" if v == "pass" else "",
            "proposed_signature": "proposal",
            "reextraction_status": "extracted",
            "reextraction_reason": "",
            "validation_reasons": "no" if v != "pass" else "",
            "failed_checks": "[]",
        }
        for s, v in [("resolved", "pass"), ("partial", "pass"), ("partial", "triage")]
    ]
    current = {r["original_signature"]: r for r in current_dispositions(old, rows)}
    assert current["initial"]["current_status"] == "initially_accepted"
    assert current["resolved"]["requires_review"] == "no"
    assert current["partial"]["current_status"] == "partially_accepted"
    assert current["partial"]["requires_review"] == "yes"
    assert current["deterministic"]["requires_review"] == "yes"
