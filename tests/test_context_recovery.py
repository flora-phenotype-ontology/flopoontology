from __future__ import annotations

import json
from pathlib import Path

from flopo2.extract.baseline import extract_segment_with_unresolved
from flopo2.extract.context_recovery import LocativeMapping, recover_file, recover_record
from flopo2.verify.missing_bearers import _po_exact_forms
from flopo2.verify.missing_bearers import _po_forms


def _record(text: str, *, organ: str = "leaves", language: str = "en") -> dict:
    assertions, unresolved = extract_segment_with_unresolved(
        {"text": text, "organ": organ, "language": language}
    )
    return {
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


def _recover(text: str, *, organ: str = "leaves", language: str = "en"):
    return recover_record(
        _record(text, organ=organ, language=language),
        _po_exact_forms(),
        _po_forms(Path("config/po_lexicon.tsv")),
    )


def _recover_locative(
    text: str,
    *,
    po_id: str,
    po_label: str,
    locative_phrase: str,
    attachment_rule: str,
    container_surface: str,
):
    record = _record(text, organ="description", language="fr")
    unresolved = record["unresolved_spans"][0]
    key = (
        record["source"],
        record["source_id"],
        record["source_segment_index"],
        unresolved["start"],
        unresolved["end"],
        unresolved["candidate_pato_id"],
    )
    mapping = LocativeMapping(
        po_id=po_id,
        po_label=po_label,
        container_surface=container_surface,
        locative_phrase=locative_phrase,
        orientation="test_orientation",
        attachment_rule=attachment_rule,
        normalization_scope=(
            "bearer_only_encode_location_in_fac"
            if attachment_rule in {"direct_trichome_quality", "direct_leaf_vein"}
            else "locative_captured_by_atomic_po_bearer"
        ),
        clause_start=0,
        clause_end=len(text.rstrip(".")),
    )
    return recover_record(
        record,
        _po_exact_forms(),
        _po_forms(Path("config/po_lexicon.tsv")),
        locative_mappings={key: mapping},
    )


def test_age_and_maturity_are_conjunctive_bearer_qualities():
    cases = (
        ("Young leaves pubescent.", "PATO_0001320", "PATO_0000309", "Young"),
        ("Mature leaves glabrous.", "PATO_0000453", "PATO_0001701", "Mature"),
        ("Fruits red at maturity.", "PATO_0000322", "PATO_0001701", "at maturity"),
        ("Immature fruits green.", "PATO_0000320", "PATO_0001501", "Immature"),
        ("Old stems ridged.", "PATO_0002358", "PATO_0000308", "Old"),
    )
    for text, primary, context, cue in cases:
        record, audit = _recover(text, organ="description")
        assert record["unresolved_spans"] == []
        assert len(record["assertions"]) == 1
        assertion = record["assertions"][0]
        assert assertion["pato_id"] == primary
        assert assertion["bearer_context_qualities"] == [context]
        assert cue in assertion["source_text"]
        assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_explicit_dry_state_is_supported_but_fresh_and_transitions_remain_unresolved():
    recovered, _audit = _recover("Leaves brown when dry.")
    assert recovered["assertions"][0]["bearer_context_qualities"] == ["PATO_0001801"]
    assert recovered["unresolved_spans"] == []

    for text in (
        "Leaves green when fresh.",
        "Leaves brown on drying.",
        "Leaves later becoming glabrous.",
        "Leaves eventually red.",
    ):
        retained, audit = _recover(text)
        assert retained["assertions"] == []
        assert retained["unresolved_spans"]
        assert audit[0]["disposition"] == "retained"


def test_context_does_not_leak_across_comma_to_another_bearer():
    recovered, audit = _recover(
        "Young branches pubescent, leaves green.", organ="description"
    )
    assert len(recovered["assertions"]) == 1
    assert recovered["assertions"][0]["po_id"] == "PO_0025073"
    assert recovered["assertions"][0]["bearer_context_qualities"] == ["PATO_0000309"]
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["green"]
    assert [row["disposition"] for row in audit] == [
        "recovered_bearer_context_quality",
        "retained",
    ]


def test_context_does_not_leak_to_a_nested_bearer_in_the_same_phrase():
    recovered, audit = _recover(
        "Fruit very young brown in a black cupule.", organ="fruits"
    )
    assert [(row["pato_id"], row["bearer_context_qualities"]) for row in recovered["assertions"]] == [
        ("PATO_0000952", ["PATO_0000309"]),
    ]
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["black"]
    assert [row["disposition"] for row in audit] == [
        "recovered_bearer_context_quality",
        "retained",
    ]


def test_context_does_not_leak_from_container_to_substructure_or_reverse():
    for text, language in (
        ("Old fruits with one persistent valve 2 mm long.", "en"),
        ("Bark of young internodes glabrous.", "en"),
        ("Écorce des jeunes entrenoeuds glabre.", "fr"),
        ("Rameaux présentant au stade jeune une pubérulence blanche.", "fr"),
    ):
        recovered, audit = _recover(text, organ="description", language=language)
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert all(row["disposition"] == "retained" for row in audit)


def test_audited_context_scope_and_range_counterexamples_stay_unresolved():
    cases = (
        ("Rameaux jeunes pubescents à glabres.", "fr"),
        ("Jeune tige tomentelleuse à pubescente.", "fr"),
        ("Jeune limbe couvert d'une arachnée blanche.", "fr"),
        ("upper surface of mature leaves glabrous.", "en"),
        ("lamina of fronds of mature plants 55 cm long.", "en"),
        ("young branchlets densely brown hairy.", "en"),
        ("Juvenile leaves ovate to broadly lanceolate.", "en"),
        ("old leaf-bases up to 3.5 cm long.", "en"),
        ("indumentum dark brown on old leaves.", "en"),
        ("Young leaves pubescent when mature.", "en"),
    )
    for text, language in cases:
        recovered, audit = _recover(text, organ="description", language=language)
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert all(row["disposition"] == "retained" for row in audit)


def test_strict_audit_context_false_promotions_stay_unresolved():
    cases = (
        (
            "tige et rameaux à écorce vert olivâtre à l'état sec.",
            "inflorescences",
            "fr",
        ),
        (
            "rhizophores recourbés, jaune paille à l'état sec.",
            "habit",
            "fr",
        ),
        ("Jeune fruit à follicules sessiles.", "fruit", "fr"),
        ("paroi de 2 mm d'épaisseur à l'état sec.", "fruits", "fr"),
        ("Fruit bluish black when mature.", "description", "en"),
        (
            "the older stems brown, purple-brown or reddish.",
            "description",
            "en",
        ),
        (
            "Mature leaflets glabrous beneath except for hairs on the nerves.",
            "description",
            "en",
        ),
        ("Infructescences pinkish red at maturity.", "description", "en"),
        (
            "anthères avec appendice du connectif, blanches à l’état sec.",
            "fleurs",
            "fr",
        ),
        ("Vieilles inflorescences à rameaux glabres.", "description", "fr"),
        ("Rameaux âgés brun grisâtre mat.", "description", "fr"),
        ("Fruit juvénile vert marbré.", "description", "fr"),
        (
            "receptacle with lateral bracts, red at maturity.",
            "description",
            "en",
        ),
        ("Corolla in mature bud 12-24 mm long.", "description", "en"),
        ("Leaves bright red when young.", "description", "en"),
        ("juvenile fruits described as glabrous.", "description", "en"),
        (
            "spatheoles tinged with green at maturity, the peduncles short.",
            "description",
            "en",
        ),
        ("Sporocarps almost black at maturity.", "leaves", "en"),
        ("pulpe beige jaune à l'état sec.", "gousses", "fr"),
        ("corolle presque noire à l'état sec.", "fleurs", "fr"),
        (
            "axis shortly tomentose when young, glabrescent later.",
            "inflorescences",
            "en",
        ),
        ("ovary in very immature fruits glabrous.", "description", "en"),
        ("older stems almost glabrous.", "description", "en"),
        ("Fruit almost glabrous at maturity.", "description", "en"),
        ("mature leaves glabrous except for scales.", "description", "en"),
        ("Young branches brown woolly.", "description", "en"),
        ("Corolla in the mature bud 65-75 mm long.", "description", "en"),
        ("old leaves practically glabrous.", "description", "en"),
        (
            "Corolla with white lobes and a yellowish tube, in mature bud 10-15 mm long.",
            "description",
            "en",
        ),
        ("one-year-old stem glabrous.", "description", "en"),
        (
            "older leaves sparsely pubescent on underside of veins.",
            "description",
            "en",
        ),
        ("jeunes folioles rouge rosé.", "description", "fr"),
        (
            "arille lacinié jaune prenant à l'état sec un aspect cotoneux blanc.",
            "fruits",
            "fr",
        ),
        ("Berry green turning red at maturity.", "description", "en"),
        ("blades usually turning black when dry.", "description", "en"),
        (
            "rameaux jeunes tomenteux et blanc grisâtre, glabrescents à l'état adulte.",
            "description",
            "fr",
        ),
        ("mid-vein of sepals usually green when young.", "description", "en"),
        (
            "Jeunes rameaux pubescents tomentelleux à glabres.",
            "description",
            "fr",
        ),
        ("test verruqueux, noir à maturité.", "seeds", "fr"),
        ("endocarpe mince, glabre intérieurement à maturité.", "drupes", "fr"),
        (
            "inflorescences densely brown tomentose when young, more sparse later.",
            "description",
            "en",
        ),
        ("young branches reddish pubescent, soon glabrous.", "description", "en"),
        (
            "Mature leaves almost entirely glabrous save for scattered hairs on venation.",
            "description",
            "en",
        ),
    )
    for text, organ, language in cases:
        recovered, audit = _recover(text, organ=organ, language=language)
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert all(row["disposition"] == "retained" for row in audit)


def test_reviewed_french_receptacle_bearer_overrides_inflorescence_heading():
    recovered, audit = _recover(
        "Réceptacle fructifié jaune à maturité.",
        organ="inflorescences",
        language="fr",
    )
    assert len(recovered["assertions"]) == 1
    assertion = recovered["assertions"][0]
    assert assertion["po_id"] == "PO_0009064"
    assert assertion["bearer_context_qualities"] == ["PATO_0001701"]
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_reviewed_french_fruit_tissues_override_broad_fruit_heading():
    cases = (
        (
            "mésocarpe charnu, de 1 mm d'épaisseur à l'état sec.",
            "capsules",
            "PO_0009087",
            "PATO_0000915",
        ),
        (
            "endocarpe noir à l'état sec.",
            "drupes",
            "PO_0009086",
            "PATO_0000317",
        ),
    )
    for text, organ, po_id, pato_id in cases:
        recovered, audit = _recover(text, organ=organ, language="fr")
        assert recovered["unresolved_spans"] == []
        assertion = recovered["assertions"][0]
        assert (assertion["po_id"], assertion["pato_id"]) == (po_id, pato_id)
        assert assertion["bearer_context_qualities"] == ["PATO_0001801"]
        assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_cross_comma_exocarp_bearer_overrides_broad_fruit_heading():
    recovered, audit = _recover(
        "exocarpe velouté, brun à l'état sec.", organ="fruits", language="fr"
    )
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0009085",
        "PATO_0000952",
    )
    assert assertion["bearer_context_qualities"] == ["PATO_0001801"]
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_exact_leaf_blade_corrects_broad_leaf_heading_in_stage_context():
    recovered, audit = _recover(
        "blade tomentose when young.", organ="leaves", language="en"
    )
    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0025060",
        "PATO_0002341",
    )
    assert assertion["bearer_context_qualities"] == ["PATO_0000309"]
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_cross_comma_leaf_blade_remains_the_explicit_stage_bearer():
    recovered, audit = _recover(
        "blade papery, elliptic, tomentose when young.",
        organ="leaves",
        language="en",
    )
    assertion = next(
        row for row in recovered["assertions"] if row["pato_id"] == "PATO_0002341"
    )
    assert assertion["po_id"] == "PO_0025060"
    assert assertion["bearer_context_qualities"] == ["PATO_0000309"]
    assert any(
        row["disposition"] == "recovered_bearer_context_quality" for row in audit
    )


def test_context_recovery_preserves_frequency_and_degree_as_orthogonal_modalities():
    cases = (
        (
            "branchlets usually tomentose when young.",
            "usually",
            "unmodified",
            "usually",
        ),
        (
            "mature leaves rarely completely glabrous.",
            "rarely",
            "completely",
            "rarely completely",
        ),
        (
            "blades usually green when dry.",
            "usually",
            "unmodified",
            "usually",
        ),
    )
    for text, frequency, degree, modality_text in cases:
        recovered, _audit = _recover(text, organ="description", language="en")
        assertion = recovered["assertions"][0]
        assert assertion["frequency_qualifier"] == frequency
        assert assertion["degree_qualifier"] == degree
        assert assertion["modality_text"] == modality_text


def test_context_recovery_preserves_frequency_and_approximation_as_orthogonal_modalities():
    recovered, audit = _recover(
        "bractées ostiolaires souvent ± dressées sur le sec",
        organ="fleurs",
        language="fr",
    )
    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert assertion["frequency_qualifier"] == "often"
    assert assertion["value_qualifier"] == "approximately"
    assert assertion["modality_text"] == "souvent ±"
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_exact_drupe_bearer_overrides_generic_fruit_heading():
    recovered, audit = _recover(
        "Drupe red at maturity.", organ="drupes", language="fr"
    )
    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0030103",
        "PATO_0000322",
    )
    assert assertion["bearer_context_qualities"] == ["PATO_0001701"]
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_exact_follicle_bearer_overrides_generic_fruit_heading():
    recovered, audit = _recover(
        "follicules légèrement côtelés à l'état sec.",
        organ="fruits",
        language="fr",
    )
    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0030105",
        "PATO_0002358",
    )
    assert assertion["bearer_context_qualities"] == ["PATO_0001801"]
    assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_stage_context_does_not_flatten_disjunctions_or_colour_compounds():
    for text in (
        "Young branches glabrous or slightly pubescent.",
        "Young leaves dark red.",
        "Young leaves red-purple.",
    ):
        recovered, audit = _recover(text, organ="description")
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert all(row["disposition"] == "retained" for row in audit)


def test_context_recovers_direct_same_bearer_surface_constructions():
    for text in (
        "Young branches very finely pubescent.",
        "Pubescent on young branches.",
    ):
        recovered, audit = _recover(text, organ="description")
        assert len(recovered["assertions"]) == 1
        assert recovered["assertions"][0]["po_id"] == "PO_0025073"
        assert recovered["assertions"][0]["bearer_context_qualities"] == ["PATO_0000309"]
        assert audit[0]["disposition"] == "recovered_bearer_context_quality"


def test_unique_nearby_po_form_recovers_bearer_without_heading_fallback():
    recovered, audit = _recover(
        "Vexillum subglobose, glabrous.", organ="description"
    )
    assert len(recovered["assertions"]) == 1
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0025324",
        "PATO_0005014",
    )
    assert assertion["raw_entity_text"].lower() == "vexillum"
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["glabrous"]
    assert {row["disposition"] for row in audit} == {
        "recovered_existing_po_bearer",
        "retained",
    }


def test_reviewed_french_local_bearers_override_broad_headings():
    for text, expected_po in (
        ("Anthères globuleuses.", "PO_0009066"),
        ("Feuilles caulinaires lancéolées.", "PO_0000013"),
    ):
        recovered, audit = _recover(text, organ="description", language="fr")
        assert len(recovered["assertions"]) == 1
        assert recovered["assertions"][0]["po_id"] == expected_po
        assert recovered["unresolved_spans"] == []
        assert audit == []


def test_scoped_po_synonym_is_not_used_as_an_exact_bearer():
    recovered, audit = _recover("Bristle white.", organ="description")
    assert recovered["assertions"] == []
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["white"]
    assert audit[0]["disposition"] == "retained"


def test_audited_exact_bearer_scope_counterexamples_stay_unresolved():
    for text in (
        "pedicels covered like bracteoles with long erect hairs.",
        "veins densely white puberulous.",
        "lower surface of costae bearing erect hairs 0.2-0.4 mm long.",
        "stalks of the capitula 1.2-7 cm long.",
        "keel pubescent near the tip.",
        "palea ovate when flattened.",
        "peristome red.",
        "inner pappus 4.5-6.5 mm long.",
        "upper receptacle tomentose.",
        "Ligules florales elliptiques.",
        "Glume supérieure acuminée.",
        "intérieur pubescent ponctué de 25 glandes.",
        "exsudat rouge sang au niveau du cambium.",
        "Lemma finement pubescente comme les glumes.",
        "receptacle tube c. 3 mm wide.",
        "lobes outside densely tomentose on part exposed in bud.",
        "Pedicelled spikelet resembling the sessile.",
        "Buds obtuse at the apex.",
        "Glomérules bractéolés sessiles.",
        "Glume supérieure légèrement pubescente.",
        "Longest petiolules 1-7 mm long.",
        "Pedicelled spikelet larger than the sessile.",
        "wings and keel glabrous.",
        "anthères à thèques subglobuleuses.",
        "Glume inférieure des épillets sessiles bidentée.",
        "pappus à 1–4 arêtes dressées.",
        "blade ovate, (long) triangular or subhastate.",
        "blade coriaceous, subcoriaceous or papery.",
        "paraphyses with peltate blades 0.25-0.65 mm wide.",
        "perianth divided into 5 lanceolate lobes.",
        "Wing of samara obliquely ovate.",
        "spinules at the base of cladodes 0.5-1.5 mm long.",
        "free part of lobes oblong.",
        "valves mûres à faces externes glabres.",
        "Costae smooth beneath.",
        "trace of aril appears as white patch.",
        "tube tomentose outside, glabrous in throat, pubescent behind anthers inside.",
        "lemmas at length rigidly coriaceous.",
        "Capitula in terminal dense globose clusters.",
        "pappus biseriate of 9–23 erect, awl-shaped golden-brown scales.",
        "pappus of white barbellate bristles.",
        "linear pellucid streaks between the veins.",
        "sporophylls on upper side lanceolate.",
        "réceptacle à paillettes jaunes.",
        "slash red outside, yellow near the wood.",
        "Capitula congested in axillary sessile clusters.",
        "lemma less distinctly acuminate than the upper glume.",
        "base étroitement atténuée rétrécie en un pétiolule.",
        "lemmas narrowly lanceolate in side view.",
        "lemma ovale lancéolée.",
        "glumes ovales oblongues.",
        "blade elliptic(-oblong).",
        "glumes broadly linear in profile.",
        "the sterile locule narrowly oblong.",
        "Female catkins 2.5-5 cm long.",
        "Leaf more than 8 cm wide.",
        "mature bud less than 1.5 mm diam.",
        "sarcocarpe assez épais, coriace sur le sec.",
        "l'ovaire jeune en section transversale montre 4 angles obtus.",
        "Akènes oblongs, de 2.0-2.2 mm de long (non encore mûrs).",
        "Akènes oblongs, anguleux, poilus, de 5 mm de long (non mûrs).",
        "Akènes poilus côtelés, de 7-8 mm de long (non entièrement mûrs).",
        "Inflorescence irrégulière, brun roux à maturité.",
        "spur c. 5 mm long, entire.",
        "ligule 4-6 mm long, 0.5-1 mm wide.",
        "palea with smooth keels.",
        "primary axis glabrous, up to 9 mm wide.",
        "articles with thin flesh, black when mature.",
        "Fruit rouge saumoné à maturité.",
        "Baies rouge vermillon à maturité.",
        "drupes rouge bleuâtre à maturité.",
        "drupes brun cannelle à l'état sec.",
        "fruit globuleux (brun à maturité ?).",
    ):
        recovered, audit = _recover(text, organ="description")
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert all(row["disposition"] == "retained" for row in audit)


def test_legume_keel_petal_remains_an_exact_existing_po_bearer():
    recovered, audit = _recover("keel glabrous.", organ="description", language="en")
    assert recovered["unresolved_spans"] == []
    assert (recovered["assertions"][0]["po_id"], recovered["assertions"][0]["pato_id"]) == (
        "PO_0025327",
        "PATO_0000453",
    )
    assert audit[0]["disposition"] == "recovered_existing_po_bearer"


def test_canonical_missing_bearer_reason_still_honours_postposed_immature_scope():
    text = "Akènes oblongs, de 2.0-2.2 mm de long (non encore mûrs)."
    record = _record(text, organ="description", language="fr")
    oblong = next(row for row in record["unresolved_spans"] if row["surface_form"] == "oblongs")
    oblong["reason"] = "missing_or_unsupported_bearer"
    recovered, audit = recover_record(
        record,
        _po_exact_forms(),
        _po_forms(Path("config/po_lexicon.tsv")),
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "retained"


def test_leaf_scoped_bare_rachis_does_not_fall_back_to_whole_leaf():
    recovered, audit = _recover(
        "Rachis de 6-20 cm de longueur, pubescent ferrugineux chez les jeunes feuilles",
        organ="rachises",
        language="fr",
    )

    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert {row["bearer_po_id"] for row in audit} == {"PO_0020055"}
    assert {row["method"] for row in audit} == {"leaf_heading_scoped_rachis"}
    assert {row["disposition"] for row in audit} == {"retained"}


def test_between_veins_region_does_not_become_a_vein_quality():
    recovered, audit = _recover(
        "lower surface of costae and main veins sparsely minutely hairy, between veins glabrous",
        organ="description",
    )

    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "retained"


def test_reviewed_cross_comma_and_french_part_bearers_prevent_part_to_whole_leakage():
    cases = (
        (
            "caruncle yellow, black when dry.",
            "description",
            "en",
            "PO_0020060",
            "PATO_0000317",
        ),
        (
            "androcée noir à l'état sec.",
            "fleurs",
            "fr",
            "PO_0009061",
            "PATO_0000317",
        ),
        (
            "étendard jaune à l'état sec.",
            "fleurs",
            "fr",
            "PO_0025324",
            "PATO_0000324",
        ),
    )
    for text, organ, language, po_id, pato_id in cases:
        recovered, audit = _recover(text, organ=organ, language=language)
        assertion = next(row for row in recovered["assertions"] if row["pato_id"] == pato_id)
        assert assertion["po_id"] == po_id
        assert assertion["bearer_context_qualities"] == ["PATO_0001801"]
        assert any(row["disposition"] == "recovered_bearer_context_quality" for row in audit)


def test_sex_scoped_flora_clause_is_not_flattened_to_generic_flower_phenotypes():
    recovered, audit = _recover(
        "♂ rouges et vertes, devenant noires à l'état sec.",
        organ="fleurs",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert all(
        row["reason"] == "unmodelled_bearer_category"
        for row in recovered["unresolved_spans"]
    )
    assert all(row["disposition"] == "retained" for row in audit)


def test_nested_synflorescence_shape_does_not_remove_safe_capitulum_length():
    recovered, audit = _recover(
        "Capitula 40 mm long in globose synflorescences.",
        organ="description",
        language="en",
    )
    assert any(
        row["po_id"] == "PO_0030121" and row["pato_id"] == "PATO_0000122"
        for row in recovered["assertions"]
    )
    assert not any(row["pato_id"] == "PATO_0001499" for row in recovered["assertions"])
    assert any(row["surface_form"] == "globose" for row in recovered["unresolved_spans"])
    assert any(
        row["surface_form"] == "globose" and row["disposition"] == "retained"
        for row in audit
    )


def test_nested_acumen_measurement_is_not_reassigned_to_whole_valves():
    recovered, audit = _recover(
        "valves à acumen rigide 1-2 mm de longueur.",
        organ="description",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert any(
        row["surface_form"] == "1-2 mm de longueur"
        for row in recovered["unresolved_spans"]
    )
    assert all(row["disposition"] == "retained" for row in audit)


def test_nested_locule_measurement_is_not_reassigned_to_whole_anthers():
    recovered, audit = _recover(
        "anthères à 2 loges ellipsoïdes longues de 0,5 mm.",
        organ="flowers",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert any(
        row["surface_form"] == "longues de 0,5 mm"
        for row in recovered["unresolved_spans"]
    )
    assert all(row["disposition"] == "retained" for row in audit)


def test_depression_shape_is_not_reassigned_to_surrounding_hilum():
    recovered, audit = _recover(
        "Seeds brown, with an oblong depression around the hilum.",
        organ="description",
        language="en",
    )
    assert not any(
        row["po_id"] == "PO_0020063" and row["pato_id"] == "PATO_0000946"
        for row in recovered["assertions"]
    )
    assert any(row["surface_form"] == "oblong" for row in recovered["unresolved_spans"])
    assert any(
        row["surface_form"] == "oblong" and row["disposition"] == "retained"
        for row in audit
    )


def test_surface_quality_is_not_reassigned_to_nearby_glands():
    recovered, audit = _recover(
        "Surfaces glabres présentant quelques glandes jaunes.",
        organ="description",
        language="fr",
    )
    assert not any(row["pato_id"] == "PATO_0000324" for row in recovered["assertions"])
    assert not any(row["pato_id"] == "PATO_0000453" for row in recovered["assertions"])
    assert any(row["surface_form"] == "glabres" for row in recovered["unresolved_spans"])
    assert any(
        row["surface_form"] == "glabres" and row["disposition"] == "retained"
        for row in audit
    )
    assert any(row["surface_form"] == "jaunes" for row in recovered["unresolved_spans"])
    assert any(
        row["surface_form"] == "jaunes" and row["disposition"] == "retained"
        for row in audit
    )


def test_french_secretory_gland_is_not_po_nut_fruit_but_english_nutlet_remains_valid():
    recovered, audit = _recover(
        "nombreuses petites glandes noires près de la nervure médiane.",
        organ="leaves",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert any(row["surface_form"] == "noires" for row in recovered["unresolved_spans"])
    assert all(row["disposition"] == "retained" for row in audit)

    recovered, _audit = _recover("Nutlets brown.", organ="description", language="en")
    assert recovered["assertions"][0]["po_id"] == "PO_0030102"


def test_ambiguous_french_ligule_is_not_mapped_to_leaf_ligule():
    recovered, audit = _recover(
        "ligule rouge, exserte de l’involucre.",
        organ="description",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "retained"


def test_anther_tube_measurement_is_not_mapped_to_whole_anther():
    recovered, audit = _recover(
        "anthères à tube d'environ 1,2 mm de longueur.",
        organ="description",
        language="fr",
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "retained"


def test_region_head_blocks_punctuation_defect_exact_bearer_theft():
    text = "leaflet apex acuminate costae indistinct."
    start = text.index("acuminate")
    record = {
        **_record(text, organ="description"),
        "assertions": [],
        "unresolved_spans": [
            {
                "start": start,
                "end": start + len("acuminate"),
                "surface_form": "acuminate",
                "reason": "missing_or_unsupported_bearer",
                "candidate_pato_id": "PATO_0002228",
                "extractor": "test",
            }
        ],
    }
    recovered, audit = recover_record(
        record,
        _po_exact_forms(),
        _po_forms(Path("config/po_lexicon.tsv")),
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "retained"


def test_scoped_nearer_noun_and_structural_bridge_block_exact_bearer_recovery():
    cases = (
        ("pappus of white setae.", "white", "PATO_0000323"),
        ("base attenuated narrowing into a petiolule.", "attenuated", "PATO_0001982"),
    )
    for text, surface, pato_id in cases:
        start = text.index(surface)
        record = {
            **_record(text, organ="description"),
            "assertions": [],
            "unresolved_spans": [
                {
                    "start": start,
                    "end": start + len(surface),
                    "surface_form": surface,
                    "reason": "missing_or_unsupported_bearer",
                    "candidate_pato_id": pato_id,
                    "extractor": "test",
                }
            ],
        }
        recovered, audit = recover_record(
            record,
            _po_exact_forms(),
            _po_forms(Path("config/po_lexicon.tsv")),
        )
        assert recovered["assertions"] == []
        assert recovered["unresolved_spans"]
        assert audit[0]["disposition"] == "retained"


def test_language_tagged_po_synonym_is_not_an_unscoped_exact_bearer():
    forms = _po_exact_forms()
    assert ("anther",) in forms
    assert ("antera",) not in forms  # PO marks this EXACT Spanish.
    assert ("vexillum",) in forms  # Untagged EXACT remains eligible.
    assert ("part", "of") not in forms  # A following OBO typedef is not a PO term.


def test_reviewed_locative_subregion_mapping_can_promote_atomic_expression():
    recovered, audit = _recover_locative(
        "Pétales glabres à l’extérieur.",
        po_id="PO_0006052",
        po_label="petal abaxial epidermis",
        locative_phrase="à l’extérieur",
        attachment_rule="organ_specific_abaxial_epidermis",
        container_surface="Pétales",
    )
    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert (assertion["po_id"], assertion["pato_id"]) == (
        "PO_0006052",
        "PATO_0000453",
    )
    assert assertion["source_text"] == "Pétales glabres à l’extérieur"
    assert assertion["normalization_status"] == "reviewed"
    assert "locative_attachment:organ_specific_abaxial_epidermis" in assertion[
        "mapping_provenance"
    ]
    assert audit[0]["disposition"] == "recovered_existing_po_locative_subregion"


def test_reviewed_locative_uses_tight_evidence_before_unrelated_disjunction():
    recovered, audit = _recover_locative(
        "Pétales glabres à l’extérieur, rouges ou vertes.",
        po_id="PO_0006052",
        po_label="petal abaxial epidermis",
        locative_phrase="à l’extérieur",
        attachment_rule="organ_specific_abaxial_epidermis",
        container_surface="Pétales",
    )
    assertion = next(
        row
        for row in recovered["assertions"]
        if row.get("normalization_status") == "reviewed"
    )
    assert assertion["source_text"] == "Pétales glabres à l’extérieur"
    assert "ou" not in assertion["source_text"].casefold().split()
    assert audit[0]["disposition"] == "recovered_existing_po_locative_subregion"


def test_reviewed_locative_drops_container_prefix_with_unrelated_disjunction():
    recovered, audit = _recover_locative(
        "Pétales rouges ou vertes, glabres à l’extérieur.",
        po_id="PO_0006052",
        po_label="petal abaxial epidermis",
        locative_phrase="à l’extérieur",
        attachment_rule="organ_specific_abaxial_epidermis",
        container_surface="Pétales",
    )
    assertion = next(
        row
        for row in recovered["assertions"]
        if row.get("normalization_status") == "reviewed"
    )
    assert assertion["source_text"] == "glabres à l’extérieur"
    assert audit[0]["disposition"] == "recovered_existing_po_locative_subregion"


def test_locative_bearer_evidence_does_not_flatten_value_transition():
    recovered, audit = _recover_locative(
        "Pétales pubérulents à glabres à l’extérieur.",
        po_id="PO_0006052",
        po_label="petal abaxial epidermis",
        locative_phrase="à l’extérieur",
        attachment_rule="organ_specific_abaxial_epidermis",
        container_surface="Pétales",
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "bearer_normalized_logical_expression_pending"


def test_relational_trichome_locative_stays_expression_pending():
    recovered, audit = _recover_locative(
        "Poils blancs à la marge.",
        po_id="PO_0000282",
        po_label="trichome",
        locative_phrase="à la marge",
        attachment_rule="direct_trichome_quality",
        container_surface="Poils",
    )
    assert recovered["assertions"] == []
    assert recovered["unresolved_spans"]
    assert audit[0]["disposition"] == "bearer_normalized_expression_pending"


def test_recovery_file_is_distinct_and_emits_complete_audit(tmp_path):
    input_path = tmp_path / "baseline.jsonl"
    input_path.write_text(
        json.dumps(_record("Young leaves pubescent."), ensure_ascii=False) + "\n"
    )
    output_path = tmp_path / "recovered.jsonl"
    audit_path = tmp_path / "audit.tsv"
    stats = recover_file(input_path, output_path, audit_path)

    assert input_path.read_text() != output_path.read_text()
    assert stats["records"] == 1
    assert stats["recovered_bearer_context_quality"] == 1
    assert stats["recovered_by_source"] == {"flora-test": 1}
    assert "PATO_0000309" in output_path.read_text()
    assert "recovered_bearer_context_quality" in audit_path.read_text()


def test_recovery_rejects_any_path_alias_before_opening(tmp_path):
    input_path = tmp_path / "baseline.jsonl"
    original = json.dumps(_record("Young leaves pubescent."), ensure_ascii=False) + "\n"
    input_path.write_text(original)
    audit_path = tmp_path / "audit.tsv"

    try:
        recover_file(input_path, input_path, audit_path)
    except ValueError as exc:
        assert "distinct" in str(exc)
    else:
        raise AssertionError("same input/output path was not rejected")
    assert input_path.read_text() == original

    output_path = tmp_path / "recovered.jsonl"
    try:
        recover_file(input_path, output_path, output_path)
    except ValueError as exc:
        assert "distinct" in str(exc)
    else:
        raise AssertionError("same output/audit path was not rejected")
