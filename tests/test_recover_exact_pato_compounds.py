from __future__ import annotations

import json


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000014
name: color

[Term]
id: PATO:0000320
name: green
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000324
name: yellow
is_a: PATO:0000014 ! color

[Term]
id: PATO:0001941
name: yellow green
is_a: PATO:0000320 ! green

[Term]
id: PATO:0001942
name: brown green
synonym: "olive green" RELATED []
is_a: PATO:0000320 ! green

[Term]
id: PATO:0104336
name: olive colour
synonym: "olive green" EXACT []
is_a: PATO:0000014 ! color
"""


def _record(text: str, surfaces: list[tuple[str, str]]) -> dict:
    return {
        "source": "test-flora",
        "source_id": "1",
        "source_segment_index": 0,
        "taxon": "Testus",
        "organ": "petals",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": text.index(surface),
                "end": text.index(surface) + len(surface),
                "surface_form": surface,
                "reason": "hyphenated_or_slash_compound",
                "candidate_pato_id": pato_id,
                "extractor": "test",
            }
            for surface, pato_id in surfaces
        ],
    }


def test_exact_lexicon_uses_preferred_and_exact_but_not_related_synonyms(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import exact_compound_colour_lexicon

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")

    lexicon = exact_compound_colour_lexicon(obo)

    assert lexicon["yellow green"] == ("PATO_0001941", "yellow green")
    # The newer EXACT term wins; the older RELATED synonym is not a candidate at all.
    assert lexicon["olive green"] == ("PATO_0104336", "olive colour")


def test_recover_exact_atomic_compound_and_remove_both_component_spans(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009032\tpetal\tpetals\n", encoding="utf-8")
    record = _record(
        "Petals yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )

    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert recovered["unresolved_spans"] == []
    assert len(recovered["assertions"]) == 1
    assertion = recovered["assertions"][0]
    assert assertion["po_id"] == "PO_0009032"
    assert assertion["pato_id"] == "PATO_0001941"
    assert assertion["source_text"] == "yellow-green"
    assert record["text"][assertion["source_start"] : assertion["source_end"]] == "yellow-green"
    assert outcomes["resolved_evidence_spans"] == 2
    assert outcomes["promoted:PATO_0001941"] == 1


def test_quoted_exact_compound_is_reported_and_retains_complete_quote(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009001\tfruit\tfruits\n", encoding="utf-8")
    record = _record(
        "Fruit “yellow-green, very acid.”",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    record["organ"] = "fruits"

    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert outcomes["promoted:PATO_0001941"] == 1
    assertion = recovered["assertions"][0]
    assert assertion["epistemic_modality"] == "reported"
    assert assertion["modality_text"] == "“yellow-green, very acid.”"
    assert assertion["source_text"] == "“yellow-green, very acid.”"
    assert record["text"][assertion["source_start"] : assertion["source_end"]] == (
        assertion["source_text"]
    )
    assert "explicitly quoted source phrase; epistemic modality reported" in assertion[
        "mapping_provenance"
    ]


def test_separate_quoted_phrases_do_not_make_intervening_compound_reported(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\nPO_0004518\tbark\tportion of bark tissue\n",
        encoding="utf-8",
    )
    record = _record(
        "Bark “columnar” in habit, yellow-green, with “ant-galls”.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    record["organ"] = "bark"

    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert outcomes["promoted:PATO_0001941"] == 1
    assertion = recovered["assertions"][0]
    assert assertion.get("epistemic_modality", "asserted") == "asserted"
    assert assertion["source_text"] == "yellow-green"


def test_recovers_exact_compound_across_typographic_space_after_dash(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009001\tfruit\tfruits\n", encoding="utf-8")
    record = _record(
        "Fruit yellow- green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )

    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert outcomes["promoted:PATO_0001941"] == 1
    assert recovered["assertions"][0]["source_text"] == "yellow- green"
    assert recovered["assertions"][0]["raw_entity_text"] == "Fruit"
    assert recovered["assertions"][0]["bearer_start"] == 0
    assert recovered["assertions"][0]["bearer_end"] == 5
    assert recovered["unresolved_spans"] == []


def test_retain_compound_in_disjunction_transition_or_larger_token(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009032\tpetal\tpetals\n", encoding="utf-8")
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    disjunction = _record(
        "Petals white or pale yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(disjunction, lexicon, resolver)
    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 2
    assert outcomes["retained:logical_compound_context"] == 1

    rare_variant = _record(
        "Petals yellow-green (rarely yellow).",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(rare_variant, lexicon, resolver)
    assert recovered["assertions"] == []
    assert outcomes["retained:logical_compound_context"] == 1

    relative_modality = _record(
        "Petals orange, less often yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(relative_modality, lexicon, resolver)
    assert recovered["assertions"] == []
    assert outcomes["retained:unmodeled_relative_modality"] == 1

    developmental = _record(
        "Petals turning pale yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(developmental, lexicon, resolver)
    assert recovered["assertions"] == []
    assert outcomes["retained:developmental_stage_context"] == 1

    larger = _record(
        "Petals yellow-green-veined.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(larger, lexicon, resolver)
    assert recovered["assertions"] == []
    assert not outcomes


def test_retains_attributed_life_state_lip_and_modified_compounds(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009001\tfruit\tfruits\n"
        "PO_0009046\tflower\tflowers\n"
        "PO_0009060\tcalyx\tcalyces\n"
        "PO_0000003\twhole plant\tplants\n"
        "PO_0004518\tbark\tportion of bark tissue\n",
        encoding="utf-8",
    )
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)
    cases = (
        (
            "Fruit yellow-green with ridges (<i>fide</i> Jarman); details unknown.",
            "reported_attribution_context",
        ),
        ("Flowers with a deeper yellow-green lip.", "bearer_scope:unsupported_tube_or_lobe"),
        ("Calyx yellow-green (in life).", "unmodeled_life_state_context"),
        ("Bark buffish yellow-green.", "unmodeled_colour_modifier"),
        ("Rich yellow-green plant.", "unmodeled_colour_modifier"),
    )
    for text, reason in cases:
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        recovered, outcomes = recover_record(record, lexicon, resolver)
        assert recovered["assertions"] == [], text
        assert outcomes[f"retained:{reason}"] == 1, text


def test_relational_container_does_not_steal_seed_colour(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009010\tseed\tseeds\n", encoding="utf-8")
    record = _record(
        "Seed filling the capsule, globose, yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )

    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert outcomes["promoted:PATO_0001941"] == 1
    assert recovered["assertions"][0]["po_id"] == "PO_0009010"


def test_retains_ripening_colour_and_earlier_colour_in_ripening_contrast(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009001\tfruit\tfruits\n", encoding="utf-8")
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    for text in (
        "Fruit ripening yellow-green.",
        "Fruit yellow-green, ellipsoid, ripening evenly red.",
        "Fruit yellow-green quand mûr.",
        "Branches yellow-green and then green.",
        "Trunks blue before peeling, afterwards yellow-green.",
    ):
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        record["organ"] = "fruits"
        recovered, outcomes = recover_record(record, lexicon, resolver)
        assert recovered["assertions"] == [], text
        assert outcomes["retained:developmental_stage_context"] == 1, text


def test_routes_subregion_appendage_and_indumentum_colours_to_bearer_review(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009032\tpetal\tpetals\n"
        "PO_0009047\tstem\tstems\n"
        "PO_0004518\tbark\tportion of bark tissue\n",
        encoding="utf-8",
    )
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    for text in (
        "Stem prickles yellow-green.",
        "Petals yellow-green at the base.",
        "Petals with yellow-green silky indumentum.",
        "Petal tube yellow-green.",
        "Flowers yellow-green at the mouth of the spur.",
        "Leaves with yellow-green tips.",
        "Branches with yellow-green glands.",
        "Valves exposing yellow-green pulp.",
        "Leaflets with a densely yellow-green strigose midrib.",
        "Flowers yellow-green tomentose.",
        "Stipules yellow-green subhirsute.",
        "Standard yellow-green, rounded, with a few hairs on the nerve.",
        "Branches variegated with mid- and yellow-green.",
        "Leaves yellow-green above, paler beneath.",
        "Middle bark yellow-green; inner bark yellow-green or pale brown.",
        "Outer layer of bark yellow-green.",
        "Outer bark peeling and exposing yellow-green under-bark.",
        "Ovaries of the short-styled flower yellow-green.",
        "Male flowers: calyx white; petals yellow-green.",
        "Petals yellow-green within.",
        "Receptacle yellow-green scurfy.",
    ):
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        record["organ"] = "stems" if text.startswith("Stem") else "petals"
        recovered, outcomes = recover_record(record, lexicon, resolver)
        assert recovered["assertions"] == [], text
        assert sum(
            count
            for outcome, count in outcomes.items()
            if outcome.startswith("retained:bearer_scope:")
        ) == 1


def test_routes_pattern_colour_but_keeps_base_colour_with_secondary_pattern(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tleaf\tleaves\n", encoding="utf-8")
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    for text in (
        "Leaves green streaked with yellow-green.",
        "Leaves with yellow-green flecks.",
        "Leaves darkish green longitudinally streaked with brighter yellow-green.",
        "Leaves covered by a secretion that leaves a yellow-green stain on touching.",
        "Leaves faintly yellow-green banded.",
        "Leaves sparingly yellow-green flecked beneath.",
        "Stems yellow-green tinged dull purple.",
        "Sepals yellow-green suffused purple within.",
    ):
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        recovered, outcomes = recover_record(record, lexicon, resolver)
        assert recovered["assertions"] == [], text
        assert outcomes["retained:bearer_scope:pattern_or_marking_colour"] == 1, text

    base = _record(
        "Leaves yellow-green, mottled black.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, _outcomes = recover_record(base, lexicon, resolver)
    assert [row["pato_id"] for row in recovered["assertions"]] == ["PATO_0001941"]


def test_routes_colour_modifier_to_later_conjunctive_fac_description(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009047\tstem\tstems\n", encoding="utf-8")
    text = "Stems branched, often pale yellow-green."
    record = _record(
        text,
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, _outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 2
    assert _outcomes["retained:unmodeled_colour_modifier"] == 1

    hue_modifier = _record(
        "Stems yellowish yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        hue_modifier,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )
    assert recovered["assertions"] == []
    assert outcomes["retained:unmodeled_colour_modifier"] == 1

    coordinated_modality = _record(
        "Bark normally rough, flaking, yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        coordinated_modality,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )
    assert recovered["assertions"] == []
    assert outcomes["retained:unmodeled_coordinated_modality"] == 1

    parenthetical = _record(
        "Stems (dark) yellow-green.",
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        parenthetical,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )
    assert recovered["assertions"] == []
    assert outcomes["retained:unmodeled_colour_modifier"] == 1


def test_styled_flower_restriction_is_retained_for_relational_bearer_expression(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009072\tplant ovary\tovary|ovaries\n"
        "PO_0009046\tflower\tflowers\n",
        encoding="utf-8",
    )
    text = "Ovaries of the short-styled flower yellow-green."
    record = _record(
        text,
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert recovered["assertions"] == []
    assert outcomes["retained:bearer_scope:relational_bearer_context"] == 1


def test_postposed_white_hairs_do_not_steal_subject_colour(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\nPO_0000282\ttrichome\thair|hairs|trichomes\n",
        encoding="utf-8",
    )
    text = "Pod yellow-green, 8–12 mm long, with sparse white appressed hairs."
    record = _record(
        text,
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    record["organ"] = "description"
    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert recovered["assertions"] == []
    assert outcomes["retained:bearer_scope:postposed_nested_covering"] == 1


def test_per_relation_and_later_nested_bearer_do_not_steal_seed_colour(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009010\tseed\tseeds\n"
        "PO_0009030\tcarpel\tcarpels\n"
        "PO_0020063\thilum\thila\n"
        "PO_0020057\ttesta\tseed coat\n",
        encoding="utf-8",
    )
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    for text in (
        "Seeds 2 per carpel, yellow-green.",
        "Seeds yellow-green with a white hilum.",
        "Seeds 9 in each fruit, yellow-green.",
    ):
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        record["organ"] = "seeds"
        recovered, _outcomes = recover_record(record, lexicon, resolver)
        assert [row["po_id"] for row in recovered["assertions"]] == ["PO_0009010"], text


def test_direct_colour_before_coordinated_bearers_emits_both(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009031\tsepal\tsepals\n"
        "PO_0009032\tpetal\tpetals\n",
        encoding="utf-8",
    )
    text = "Flowers with yellow-green sepals and petals and a white lip."
    record = _record(
        text,
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert {row["po_id"] for row in recovered["assertions"]} == {
        "PO_0009031",
        "PO_0009032",
    }
    assert outcomes["promoted:PATO_0001941"] == 2
    assert outcomes["resolved_evidence_spans"] == 2


def test_coordinated_bearers_before_colour_emit_both(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0030112\tflower pedicel\tpedicels\n"
        "PO_0009060\tcalyx\tcalyces\n",
        encoding="utf-8",
    )
    text = "Pedicels and calyx both yellow-green."
    record = _record(
        text,
        [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
    )
    recovered, outcomes = recover_record(
        record,
        exact_compound_colour_lexicon(obo),
        BearerResolver(po),
    )

    assert {row["po_id"] for row in recovered["assertions"]} == {
        "PO_0030112",
        "PO_0009060",
    }
    assert outcomes["promoted:PATO_0001941"] == 2


def test_routes_named_colour_bearer_scope_missing_from_closed_po_rules(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import (
        BearerResolver,
        exact_compound_colour_lexicon,
        recover_record,
    )

    obo = tmp_path / "pato.obo"
    obo.write_text(PATO_OBO, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009010\tseed\tseeds\n"
        "PO_0009053\tinflorescence axis\tpeduncle\n"
        "PO_0009074\tplant style\tstyle\n"
        "PO_0020038\tpetiole\tpetioles\n"
        "PO_0009066\tanther\tanthers\n",
        encoding="utf-8",
    )
    lexicon = exact_compound_colour_lexicon(obo)
    resolver = BearerResolver(po)

    examples = (
        "Stylehead yellow-green.",
        "Petiole with coarse yellow-green sacking-like sheath.",
        "The spike proper yellow-green, 10 cm long.",
        "Stamens with filaments yellow-green, anthers short.",
        "Seeds with a yellow-green exotesta.",
    )
    for text in examples:
        record = _record(
            text,
            [("yellow", "PATO_0000324"), ("green", "PATO_0000320")],
        )
        recovered, outcomes = recover_record(record, lexicon, resolver)
        assert recovered["assertions"] == [], text
        assert sum(outcomes.values()) == 1, text


def test_recover_file_never_overwrites_input(tmp_path):
    import pytest

    from flopo2.verify.recover_exact_pato_compounds import recover_file

    path = tmp_path / "records.jsonl"
    path.write_text(json.dumps(_record("Petals green.", [])) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        recover_file(path, path)
