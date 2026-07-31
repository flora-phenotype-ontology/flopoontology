from __future__ import annotations

import json


def test_gate_accept_review_block(tmp_path):
    from flopo2.verify.gates import load_combinations, run_file

    combos = tmp_path / "combos.tsv"
    combos.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_leaf\tPATO_green\tallowed\ttest\tleaf green\n"
        "PO_leaf\tPATO_bad\tblocked\ttest\tleaf bad\n"
    )
    inp = tmp_path / "phase6.jsonl"
    inp.write_text(
        json.dumps({
            "source": "s",
            "source_id": "1",
            "text": "leaves green",
            "assertions": [
                {"po_id": "PO_leaf", "pato_id": "PATO_green", "source_text": "leaves green",
                 "composition": {"status": "accept"}},
                {"po_id": "PO_leaf", "pato_id": "PATO_blue", "source_text": "leaves green",
                 "composition": {"status": "accept"}},
                {"po_id": "PO_leaf", "pato_id": "PATO_bad", "source_text": "leaves green",
                 "composition": {"status": "accept"}},
            ],
        }) + "\n"
    )
    out = tmp_path / "gated.jsonl"
    accepted = tmp_path / "accepted.jsonl"
    review = tmp_path / "review.jsonl"
    blocked = tmp_path / "blocked.jsonl"
    summary = run_file(inp, out, combos, accepted, review, blocked)
    assert summary["statuses"] == {"accepted": 1, "review": 1, "blocked": 1}
    assert load_combinations(combos)[("PO_leaf", "PATO_green")].status == "allowed"
    assert '"gate"' in out.read_text()
    assert accepted.read_text().count("\n") == 1
    assert review.read_text().count("\n") == 1
    assert blocked.read_text().count("\n") == 1


def test_gate_split_preserves_unresolved_only_segments(tmp_path):
    from flopo2.verify.gates import run_file

    combos = tmp_path / "combos.tsv"
    combos.write_text("po_id\tpato_id\tstatus\tsource\texample_label\n")
    inp = tmp_path / "phase6.jsonl"
    inp.write_text(json.dumps({
        "source": "s",
        "source_id": "1",
        "taxon": "Taxon a",
        "text": "leaves red or yellow",
        "unresolved_spans": [{
            "start": 7,
            "end": 10,
            "surface_form": "red",
            "reason": "explicit_disjunction",
            "candidate_pato_id": "PATO_0000322",
            "extractor": "deterministic_baseline",
        }],
        "assertions": [],
    }) + "\n")
    accepted = tmp_path / "accepted.jsonl"
    review = tmp_path / "review.jsonl"
    summary = run_file(
        inp,
        tmp_path / "gated.jsonl",
        combos,
        accepted_out=accepted,
        review_out=review,
    )
    assert summary["unresolved_spans"] == 1
    assert json.loads(accepted.read_text())["unresolved_spans"][0]["reason"] == "explicit_disjunction"
    assert json.loads(review.read_text())["unresolved_spans"][0]["reason"] == "explicit_disjunction"


def test_gate_marks_existing_and_new_class_candidates(tmp_path):
    from flopo2.verify.gates import load_eq_registry, run_file

    combos = tmp_path / "combos.tsv"
    combos.write_text(
        "po_id\tpato_id\tstatus\tsource\texample_label\n"
        "PO_leaf\tPATO_green\tallowed\ttest\tleaf green\n"
        "PO_leaf\tPATO_blue\tallowed\ttest\tleaf blue\n"
    )
    registry = tmp_path / "registry.tsv"
    registry.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000001\t1\tleaf green\t"
        "EQ|PO_leaf|PATO_green\t0\n"
    )
    inp = tmp_path / "phase6.jsonl"
    inp.write_text(
        json.dumps({
            "source": "s",
            "source_id": "1",
            "text": "leaves green and blue",
            "assertions": [
                {"po_id": "PO_leaf", "pato_id": "PATO_green", "source_text": "leaves green",
                 "composition": {"status": "accept"}},
                {"po_id": "PO_leaf", "pato_id": "PATO_blue", "source_text": "blue",
                 "composition": {"status": "accept"}},
            ],
        }) + "\n"
    )
    out = tmp_path / "gated.jsonl"
    summary = run_file(inp, out, combos, registry_path=registry)
    assert summary["registry_eq"] == 1
    rows = json.loads(out.read_text())["assertions"]
    assert rows[0]["gate"]["flopo_status"] == "existing"
    assert rows[0]["gate"]["flopo_iri"].endswith("FLOPO_0000001")
    assert rows[1]["gate"]["flopo_status"] == "new_class_candidate"
    assert rows[1]["gate"]["review_priority"] == 50
    assert load_eq_registry(registry)[("PO_leaf", "PATO_green")][1] is False


def test_gate_verifier_hook_routes_review(tmp_path):
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "leaves green",
        {"po_id": "PO_leaf", "pato_id": "PATO_green", "source_text": "leaves green"},
        {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()},
        verifier=lambda assertion, text: ("disagree", ["wrong entity"]),
    )
    assert decision.status == "review"
    assert "verifier_disagrees" in decision.reasons
    assert decision.review_priority >= 70


def test_gate_routes_reduced_virulence_to_manual_review():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "leaf base attenuated",
        {"po_id": "PO_leaf", "pato_id": "PATO_0002147", "source_text": "attenuated",
         "composition": {"status": "accept"}},
        {("PO_leaf", "PATO_0002147"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "review"
    assert "pato_reduced_virulence_manual_review" in decision.reasons
    assert decision.review_priority >= 75


def test_gate_routes_new_attribute_trait_to_manual_review():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "petals erect",
        {"po_id": "PO_petal", "pato_id": "PATO_orientation", "source_text": "erect",
         "composition": {"status": "accept"}},
        {("PO_petal", "PATO_orientation"): type("C", (), {"status": "allowed"})()},
        registry={},
        attribute_pato_ids={"PATO_orientation"},
    )
    assert decision.status == "review"
    assert "pato_attribute_trait_manual_review" in decision.reasons
    assert decision.flopo_status == "new_class_candidate"


def test_gate_requires_upper_bound_cue_in_retained_source_span():
    from flopo2.verify.gates import Combination, check_assertion

    combinations = {
        ("PO_0009025", "PATO_0000122"): Combination("allowed", "test")
    }
    missing = check_assertion(
        "Leaves 5 mm long.",
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000122",
            "source_text": "5 mm long",
            "source_start": 7,
            "source_end": 16,
            "value_high": 5,
            "unit": "mm",
            "composition": {"status": "accept"},
        },
        combinations,
        attribute_pato_ids={"PATO_0000122"},
    )
    assert missing.status == "blocked"
    assert "upper_bound_cue_not_in_source_span" in missing.reasons

    retained = check_assertion(
        "Leaves up to 5 mm long.",
        {
            "po_id": "PO_0009025",
            "pato_id": "PATO_0000122",
            "source_text": "up to 5 mm long",
            "source_start": 7,
            "source_end": 22,
            "value_high": 5,
            "unit": "mm",
            "composition": {"status": "accept"},
        },
        combinations,
        attribute_pato_ids={"PATO_0000122"},
    )
    assert "upper_bound_cue_not_in_source_span" not in retained.reasons


def test_gate_keeps_existing_attribute_trait_accepted():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "petals erect",
        {"po_id": "PO_petal", "pato_id": "PATO_orientation", "source_text": "erect",
         "composition": {"status": "accept"}},
        {("PO_petal", "PATO_orientation"): type("C", (), {"status": "allowed"})()},
        registry={("PO_petal", "PATO_orientation"): ("http://example.org/FLOPO_1", False)},
        attribute_pato_ids={"PATO_orientation"},
    )
    assert decision.status == "accepted"
    assert "pato_attribute_trait_manual_review" not in decision.reasons
    assert decision.flopo_status == "existing"


def test_gate_accepts_new_attribute_trait_after_explicit_curator_review():
    from flopo2.verify.gates import Combination, check_assertion

    decision = check_assertion(
        "petals 3 mm long",
        {
            "po_id": "PO_petal",
            "pato_id": "PATO_length",
            "source_text": "3 mm long",
            "source_start": 7,
            "source_end": 16,
            "value_low": 3,
            "value_high": 3,
            "unit": "mm",
            "composition": {"status": "accept"},
        },
        {
            ("PO_petal", "PATO_length"): Combination(
                status="allowed",
                source="curator_review_2026-07-17",
                example_label="petal length",
            )
        },
        registry={},
        attribute_pato_ids={"PATO_length"},
    )
    assert decision.status == "accepted"
    assert "pato_attribute_trait_manual_review" not in decision.reasons
    assert decision.flopo_status == "new_class_candidate"


def test_gate_preserves_supported_one_of_value_expression():
    from flopo2.verify.gates import check_assertion

    assertion = {
        "po_id": "PO_flower",
        "pato_id": "PATO_color",
        "source_text": "greenish or pinkish flowers",
        "value_operator": "one_of",
        "value_terms": ["FLOPO_greenish", "FLOPO_pinkish"],
        "composition": {"status": "accept"},
    }
    decision = check_assertion(
        "greenish or pinkish flowers",
        assertion,
        {("PO_flower", "PATO_color"): type("C", (), {"status": "allowed"})()},
        registry={},
        signature_registry={},
        attribute_pato_ids={"PATO_color"},
    )
    assert decision.status == "accepted"
    assert decision.flopo_signature == (
        "EQV|PO_flower|ONE_OF|FLOPO_greenish&FLOPO_pinkish"
    )
    assert "pato_attribute_trait_manual_review" not in decision.reasons


def test_gate_blocks_disjunction_without_source_or_components():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "pink flowers",
        {
            "po_id": "PO_flower",
            "pato_id": "PATO_color",
            "source_text": "pink flowers",
            "value_operator": "one_of",
            "value_terms": ["PATO_pink"],
        },
        {("PO_flower", "PATO_color"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "blocked"
    assert "logical_value_missing_components" in decision.reasons


def test_gate_blocks_numeric_bounds_without_unit():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "leaves 3-7 cm long",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "3-7 cm long",
            "value_low": 3.0,
            "value_high": 7.0,
            "unit": "",
            "composition": {"status": "accept"},
        },
        {("PO_leaf", "PATO_length"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "blocked"
    assert "measurement_missing_unit" in decision.reasons


def test_gate_blocks_reversed_and_nonfinite_measurements():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_leaf", "PATO_length"): type("C", (), {"status": "allowed"})()}
    reversed_range = check_assertion(
        "leaves 8-6 mm long",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "8-6 mm long",
            "value_low": 8.0,
            "value_high": 6.0,
            "unit": "mm",
            "composition": {"status": "accept"},
        },
        combo,
    )
    nonfinite = check_assertion(
        "leaves unbounded in length",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "unbounded in length",
            "value_high": float("inf"),
            "unit": "cm",
            "composition": {"status": "accept"},
        },
        combo,
    )
    assert reversed_range.status == "blocked"
    assert "reversed_measurement_range" in reversed_range.reasons
    assert nonfinite.status == "blocked"
    assert "nonfinite_measurement" in nonfinite.reasons


def test_gate_accepts_finite_numeric_phenotype_for_source_owl_axioms():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "leaves 3-7 cm long",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "3-7 cm long",
            "value_low": 3.0,
            "value_high": 7.0,
            "unit": "cm",
            "composition": {"status": "accept"},
        },
        {("PO_leaf", "PATO_length"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "accepted"
    assert "numeric_measurement_not_axiomatized" not in decision.reasons


def test_gate_requires_pato_attribute_for_numeric_phenotype():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "leaves 3-7 cm long",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "3-7 cm long",
            "value_low": 3.0,
            "value_high": 7.0,
            "unit": "cm",
            "composition": {"status": "accept"},
        },
        {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()},
        attribute_pato_ids={"PATO_length"},
    )
    assert decision.status == "blocked"
    assert "numeric_quality_not_pato_attribute" in decision.reasons


def test_gate_blocks_non_measurement_unit():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "aiguillons apparaissant vers la 5e feuille",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_length",
            "source_text": "5e feuille",
            "value_low": 5,
            "value_high": 5,
            "unit": "leaf",
            "composition": {"status": "accept"},
        },
        {("PO_leaf", "PATO_length"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "blocked"
    assert "unsupported_measurement_unit" in decision.reasons


def test_gate_reviews_ambiguous_span_without_offsets():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "green leaves; green stems",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "green",
            "composition": {"status": "accept"},
        },
        {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()},
    )
    assert decision.status == "review"
    assert "ambiguous_source_span_without_offsets" in decision.reasons


def test_gate_segment_reviews_explicitly_missing_taxon():
    from flopo2.verify.gates import gate_segment

    row = gate_segment(
        {
            "taxon": "",
            "text": "leaves green",
            "assertions": [
                {
                    "po_id": "PO_leaf",
                    "pato_id": "PATO_green",
                    "source_text": "leaves green",
                    "composition": {"status": "accept"},
                }
            ],
        },
        {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()},
    )
    gate = row["assertions"][0]["gate"]
    assert gate["status"] == "review"
    assert "missing_taxon_provenance" in gate["reasons"]


def test_gate_accepts_scoped_negation_and_still_reviews_cardinality():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()}
    negated = check_assertion(
        "leaves not green",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "not green",
            "negated": True,
            "negation_scope": "quality",
            "composition": {"status": "accept"},
        },
        combo,
    )
    assert negated.status == "accepted"
    assert negated.flopo_status == "annotation_extension_only"

    missing_scope = check_assertion(
        "leaves not green",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "not green",
            "negated": True,
            "composition": {"status": "accept"},
        },
        combo,
    )
    assert missing_scope.status == "blocked"
    assert "missing_negation_scope" in missing_scope.reasons

    cardinality = check_assertion(
        "leaves green",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "leaves green",
            "cardinality": "3-5",
            "composition": {"status": "accept"},
        },
        combo,
    )
    assert cardinality.status == "review"
    assert "cardinality_not_supported_by_owl" in cardinality.reasons

    modal = check_assertion(
        "leaves usually green",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_green",
            "source_text": "usually green",
            "modifier": "usually",
            "composition": {"status": "accept"},
        },
        combo,
    )
    assert modal.status == "accepted"
    assert "modifier_requires_compositional_representation" not in modal.reasons


def test_gate_scans_primary_and_component_ids_for_botanical_homonyms():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_leaf", "PATO_shape"): type("C", (), {"status": "allowed"})()}
    decision = check_assertion(
        "leaf acute or obtuse",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_shape",
            "source_text": "acute or obtuse",
            "value_operator": "one_of",
            "value_terms": ["PATO_0000389", "PATO_0001935"],
            "composition": {"status": "accept"},
        },
        combo,
        attribute_pato_ids={"PATO_shape"},
    )
    assert decision.status == "review"
    assert "pato_acute_process_duration_manual_review" in decision.reasons


def test_gate_requires_attribute_as_top_level_of_logical_value():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "flowers red or yellow",
        {
            "po_id": "PO_flower",
            "pato_id": "PATO_red",
            "source_text": "red or yellow",
            "value_operator": "one_of",
            "value_terms": ["PATO_red", "PATO_yellow"],
            "composition": {"status": "accept"},
        },
        {("PO_flower", "PATO_red"): type("C", (), {"status": "allowed"})()},
        attribute_pato_ids={"PATO_color"},
    )
    assert decision.status == "review"
    assert "logical_value_top_level_not_attribute" in decision.reasons


def test_gate_accepts_atomic_attribute_plus_value_but_reviews_incompatible_primary():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_stem", "PATO_shape"): type("C", (), {"status": "allowed"})()}
    supported = check_assertion(
        "stems cylindrical",
        {
            "po_id": "PO_stem",
            "pato_id": "PATO_shape",
            "source_text": "cylindrical",
            "value_operator": "atomic",
            "value_terms": ["PATO_cylindrical"],
        },
        combo,
        attribute_pato_ids={"PATO_shape"},
    )
    incompatible = check_assertion(
        "stems cylindrical",
        {
            "po_id": "PO_stem",
            "pato_id": "PATO_red",
            "source_text": "cylindrical",
            "value_operator": "atomic",
            "value_terms": ["PATO_cylindrical"],
        },
        {("PO_stem", "PATO_red"): type("C", (), {"status": "allowed"})()},
        attribute_pato_ids={"PATO_shape"},
    )
    assert supported.status == "accepted"
    assert incompatible.status == "blocked"
    assert "atomic_value_top_level_incompatible" in incompatible.reasons


def test_gate_reviews_atomic_source_disjunction_but_not_degree_idiom():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()}
    disjunction = check_assertion(
        "leaves green or yellow",
        {"po_id": "PO_leaf", "pato_id": "PATO_green", "source_text": "green or yellow"},
        combo,
    )
    degree = check_assertion(
        "leaves more or less green",
        {"po_id": "PO_leaf", "pato_id": "PATO_green", "source_text": "more or less green"},
        combo,
    )
    assert disjunction.status == "review"
    assert "atomic_source_contains_disjunction" in disjunction.reasons
    assert "atomic_source_contains_disjunction" not in degree.reasons


def test_gate_reviews_atomic_disjunction_just_outside_submitted_source_span():
    from flopo2.verify.gates import check_assertion

    combo = {("PO_leaf", "PATO_shape"): type("C", (), {"status": "allowed"})()}
    truncated = check_assertion(
        "Leaves simple or compound.",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_shape",
            "source_text": "Leaves simple",
            "source_start": 0,
            "source_end": 13,
        },
        combo,
    )
    independent = check_assertion(
        "Leaves simple, flowers red or yellow.",
        {
            "po_id": "PO_leaf",
            "pato_id": "PATO_shape",
            "source_text": "Leaves simple",
            "source_start": 0,
            "source_end": 13,
        },
        combo,
    )
    assert truncated.status == "review"
    assert "atomic_clause_contains_disjunction" in truncated.reasons
    assert independent.status == "accepted"


def test_gate_normalizes_complete_composition_audit_without_losing_review_assertions():
    from flopo2.verify.gates import gate_segment

    obj = {
        "source": "flora-test",
        "source_id": "1",
        "taxon": "Planta exemplar",
        "text": "Leaves green.",
        "decisions": [{
            "assertion": {
                "po_id": "PO_leaf",
                "pato_id": "PATO_green",
                "source_text": "Leaves green",
                "source_start": 0,
                "source_end": 12,
                "extractor": "test",
                "value_term_ids": ["PATO_green"],
            },
            "status": "review",
            "confidence": 0.5,
            "reasons": ["source_span_mentions_different_entity"],
            "entity_label": "leaf",
            "quality_label": "green",
            "clause": "Leaves green",
        }],
    }
    combo = {("PO_leaf", "PATO_green"): type("C", (), {"status": "allowed"})()}
    gated = gate_segment(obj, combo)
    assertion = gated["assertions"][0]
    assert "decisions" not in gated
    assert assertion["value_terms"] == ["PATO_green"]
    assert assertion["composition"]["status"] == "review"
    assert assertion["gate"]["status"] == "review"
    assert "composition_not_accepted" in assertion["gate"]["reasons"]


def test_gate_blocks_unknown_logical_component_when_catalog_is_supplied():
    from flopo2.verify.gates import check_assertion

    decision = check_assertion(
        "flowers red or yellow",
        {
            "po_id": "PO_flower",
            "pato_id": "PATO_color",
            "source_text": "red or yellow",
            "value_operator": "one_of",
            "value_terms": ["PATO_red", "PATO_missing"],
        },
        {("PO_flower", "PATO_color"): type("C", (), {"status": "allowed"})()},
        attribute_pato_ids={"PATO_color"},
        pato_catalog_ids={"PATO_color", "PATO_red"},
    )
    assert decision.status == "blocked"
    assert "unknown_value_pato_id" in decision.reasons



def test_db_load_roundtrip(tmp_path):
    from flopo2.db.load import load_jsonl

    gated = tmp_path / "gated.jsonl"
    gated.write_text(
        json.dumps({
            "source": "s",
            "source_id": "1",
            "taxon": "Taxon a",
            "organ": "leaf",
            "language": "en",
            "text": "leaves green",
            "unresolved_spans": [{
                "start": 7,
                "end": 12,
                "surface_form": "green",
                "reason": "manual_semantic_review",
                "candidate_pato_id": "PATO_green",
                "extractor": "test",
            }],
            "term_mentions": [{
                "mention_id": "mention-green",
                "start": 7,
                "end": 12,
                "surface_form": "green",
                "normalized_form": "green",
                "language": "en",
                "organ_context": "leaf",
                "semantic_roles": ["value"],
                "registry_term_ids": ["BTERM:green"],
                "candidates": [{
                    "target_id": "PATO_green",
                    "label": "green",
                    "namespace": "PATO",
                    "score": 1.0,
                    "mapping_relation": "skos:exactMatch",
                    "review_status": "reviewed",
                    "registry_term_ids": ["BTERM:green"],
                    "evidence": ["manual_mapping_curation"],
                }],
            }],
            "assertions": [{
                "po_id": "PO_leaf",
                "pato_id": "PATO_color",
                "value_operator": "atomic",
                "value_terms": ["PATO_green"],
                "quality_mention_ids": ["mention-green"],
                "normalization_status": "reviewed",
                "mapping_provenance": ["BTERM:green"],
                "source_text": "leaves green",
                "source_start": 0,
                "source_end": 12,
                "extractor": "test",
                "trait": "TO_0000001",
                "modifier": "approximately",
                "cardinality": "3",
                "confidence": 0.8,
                "composition": {"status": "accept", "confidence": 1.0, "reasons": []},
                "gate": {"status": "accepted", "confidence": 1.0,
                         "reasons": [], "po_pato_status": "allowed",
                         "flopo_iri": "http://purl.obolibrary.org/obo/FLOPO_0000001",
                         "flopo_status": "existing", "review_priority": 0},
            }],
        }) + "\n"
    )
    db = tmp_path / "flopo.sqlite"
    summary = load_jsonl(db, gated)
    assert summary["assertions"] == 1
    assert summary["unresolved_spans"] == 1

    import sqlite3

    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from v_accepted_assertions").fetchone()[0] == 1
        assert conn.execute(
            "select flopo_status from trait_assertion"
        ).fetchone()[0] == "existing"
        assert conn.execute("select count(*) from term_mention").fetchone()[0] == 1
        assert conn.execute("select count(*) from term_candidate").fetchone()[0] == 1
        assert conn.execute("select organ_context from term_mention").fetchone()[0] == "leaf"
        assert conn.execute("select count(*) from unresolved_span").fetchone()[0] == 1
        assert conn.execute(
            "select trait, modifier, cardinality, confidence from trait_assertion"
        ).fetchone() == ("TO_0000001", "approximately", "3", 0.8)
        row = conn.execute(
            "select phenotype_class_iri, assertion_count from mv_species_trait_matrix"
        ).fetchone()
        # Cardinality is retained but not yet compiled into an annotation class, so this
        # deliberately unsafe legacy fixture has no FAC link.
        assert row == (None, 1)


def test_db_loader_rejects_reloading_nonempty_database(tmp_path):
    import pytest

    from flopo2.db.load import load_jsonl

    path = tmp_path / "rows.jsonl"
    path.write_text(json.dumps({
        "source": "s",
        "source_id": "1",
        "taxon": "Taxon a",
        "text": "leaves green",
        "assertions": [],
    }) + "\n")
    db = tmp_path / "traits.sqlite"
    load_jsonl(db, path)
    with pytest.raises(RuntimeError, match="not empty"):
        load_jsonl(db, path)
