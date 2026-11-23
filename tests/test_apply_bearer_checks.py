"""Passes over existing records: the position of the bearer, and parts of one plant group."""

from __future__ import annotations

from flopo2.verify import apply_bearer_position as position
from flopo2.verify import apply_bryophyte_terms as bryophyte
from flopo2.verify import apply_plant_group as group


def _assertion(text: str, bearer: str, po: str, pato: str = "PATO_0000956") -> dict:
    from flopo2.owl.annotation_class import ensure_annotation_class_iri

    start = text.index(bearer)
    assertion = {"po_id": po, "pato_id": pato, "value_terms": [], "value_operator": "atomic", "negated": False,
                 "source_text": text, "bearer_start": start, "bearer_end": start + len(bearer),
                 "raw_entity_text": bearer, "gate": {"status": "accepted", "reasons": []},
                 "composition": {"entity_label": bearer, "quality_label": "x"}}
    ensure_annotation_class_iri(assertion)
    return assertion


def test_the_position_before_the_bearer_is_recorded():
    words = position.load()
    pattern = position._pattern(words)
    text = "the lateral umbels usually sterile"
    a = _assertion(text, "umbels", "PO_0030129")
    before = a["phenotype_class_iri"]
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["lateral"][0]] and a["phenotype_class_iri"] != before
    assert position.apply(a, text, words, pattern) == ""  # idempotent

    text = "Basal leaves spatulate"
    a = _assertion(text, "leaves", "PO_0025034", "PATO_0000052")
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["basal"][0]]


def test_a_record_that_is_not_linked_to_a_class_gets_the_position_but_no_class_identifier():
    # "5-7 on each side" is written in the record only; the formal builder refuses a class on it
    words = position.load()
    pattern = position._pattern(words)
    text = "lateral veins 5-7 on each side"
    a = _assertion(text, "veins", "PO_0005020", "PATO_0000070")
    a.pop("phenotype_class_iri")
    a["count_position"] = {"kind": "each_side", "position_text": "on each side"}
    assert position.apply(a, text, words, pattern) == "added"
    assert a["bearer_context_qualities"] == [words["lateral"][0]] and "phenotype_class_iri" not in a


def test_a_position_without_a_class_or_two_positions_go_to_review():
    words = position.load()
    pattern = position._pattern(words)
    for text in ("the axillary umbels mostly sterile", "the terminal and uppermost umbels mostly small and sterile"):
        a = _assertion(text, "umbels", "PO_0030129")
        before = a["phenotype_class_iri"]
        assert position.apply(a, text, words, pattern) == "review"
        assert a["gate"] == {"status": "review", "reasons": [position.REASON]} and a["phenotype_class_iri"] == before
        assert position.apply(a, text, words, pattern) == ""
    text = "umbels sterile"
    assert position.apply(_assertion(text, "umbels", "PO_0030129"), text, words, pattern) == ""


def test_a_grass_part_in_another_family_goes_to_review():
    guard = group.Guard()
    awn = {"po_id": "PO_0025349", "gate": {"status": "accepted", "reasons": []}}
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "Poaceae")
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "Cyperaceae")
    assert not guard.apply(dict(awn, gate={"status": "accepted", "reasons": []}), "")
    assert guard.apply(awn, "Asteraceae") and awn["gate"] == {"status": "review", "reasons": [group.REASON]}
    assert not guard.apply(awn, "Asteraceae")  # once
    lemma_awn = {"po_id": "PO_0006032", "gate": {"status": "accepted", "reasons": []}}
    assert guard.apply(lemma_awn, "Geraniaceae")
    leaf = {"po_id": "PO_0025034", "gate": {"status": "accepted", "reasons": []}}
    assert not guard.apply(leaf, "Asteraceae")


def test_grass_spikelet_parts_are_one_browse_group():
    from flopo2.saudi.vocab import Vocabulary

    vocab = Vocabulary()
    assert {vocab.organ_group(t) for t in ("PO:0025349", "PO:0006032", "PO:0009037", "PO:0009039")} == {"spikelet"}
    assert vocab.organ_group("PO:0009046") == "flower"
    assert "shrub habit" in vocab.other_names("FLOPO:0987002")


def test_a_moss_gets_the_moss_parts_of_the_plant_ontology():
    terms = bryophyte.Terms()
    # the capsule of a moss is a spore capsule, not a fruit type: another class, the FLOPO class goes
    a = _assertion("Capsule yellow-brown", "Capsule", "PO_0030091", "PATO_0000014")
    a["gate"].update(flopo_signature="EQ|PO_0030091|PATO_0000014", flopo_iri="http://purl.obolibrary.org/obo/FLOPO_0994024", flopo_status="existing")
    before = a["phenotype_class_iri"]
    assert terms.apply(a, "Pottiaceae") == "replaced"
    assert a["po_id"] == "PO_0025094" and a["composition"]["entity_label"] == "sporangium"
    assert a["phenotype_class_iri"] != before and a["gate"]["flopo_signature"] == "EQ|PO_0025094|PATO_0000014"
    assert a["gate"]["flopo_iri"] != "http://purl.obolibrary.org/obo/FLOPO_0994024"
    assert terms.apply(a, "Pottiaceae") == ""  # idempotent

    # a moss leaf is a non-vascular leaf, which is a leaf: the FLOPO class of the leaf still holds
    a = _assertion("leaves glabrous", "leaves", "PO_0025034", "PATO_0000453")
    a["gate"].update(flopo_signature="EQ|PO_0025034|PATO_0000453", flopo_iri="http://example.org/leaf-glabrous", flopo_status="existing")
    assert terms.apply(a, "Sphagnaceae") == "replaced" and a["po_id"] == "PO_0025075"
    assert a["gate"]["flopo_iri"] in ("http://example.org/leaf-glabrous", terms.flopo.get("EQ|PO_0025075|PATO_0000453"))

    # the same words in a flowering plant are left alone
    a = _assertion("Capsule yellow-brown", "Capsule", "PO_0030091", "PATO_0000014")
    assert terms.apply(a, "Malvaceae") == "" and a["po_id"] == "PO_0030091"
    assert terms.apply(a, "") == ""
    # but not in a source that has mosses only, whatever family the name was matched to
    assert terms.apply(a, "Cyperaceae", True) == "replaced"


def test_a_flower_part_in_a_moss_goes_to_review_and_moss_parts_stay():
    terms = bryophyte.Terms()
    a = _assertion("petals white", "petals", "PO_0009032", "PATO_0000323")
    assert terms.apply(a, "Bryaceae") == "review"
    assert a["gate"]["status"] == "review" and a["gate"]["reasons"] == ["bearer_outside_plant_group"]
    assert terms.apply(a, "Bryaceae") == ""
    for part in ("PO_0030032", "PO_0030043", "PO_0030072", "PO_0030078", "PO_0020128"):  # seta, peristome tooth, costa, rhizoid, leaf margin
        a = _assertion("seta red", "seta", part, "PATO_0000322")
        assert terms.apply(a, "Bryaceae") == "" and a["gate"]["status"] == "accepted"
    assert "malvaceae" not in terms.families and "pottiaceae" in terms.families
