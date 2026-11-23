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
    # a moss whose name is also that of a flowering plant carries that family: the text decides
    moss = "Plants small. Seta 5 mm; capsule erect; peristome single, exostome teeth short; calyptra cucullate."
    assert terms.apply(a, "Amaranthaceae", moss) == "replaced"
    # a moss of an old genus without a family
    b = _assertion("Capsule yellow-brown", "Capsule", "PO_0030091", "PATO_0000014")
    assert terms.apply(b, "", "Autoicous. Capsule yellow-brown.") == "replaced"


def test_a_description_is_one_of_a_bryophyte_by_family_or_by_moss_words():
    is_bryophyte = bryophyte.is_bryophyte
    assert is_bryophyte("Pottiaceae", "") and is_bryophyte("Jungermanniaceae", "")
    assert not is_bryophyte("", "Leaves ovate; capsule 5 mm; seeds many.")
    assert is_bryophyte("", "Seta red; peristome double.") and is_bryophyte("", "alar cells inflated")
    # one such word is not enough: a pitcher has a peristome, a eucalypt a calyptra, a grass setae
    assert not is_bryophyte("", "Pitcher with a broad peristome.")
    assert not is_bryophyte("Poaceae", "Spikelets with setae; calyptra absent.")
    assert not is_bryophyte("Polypodiaceae", "Gametophytes dioicous, with gemmae.")
    assert "malvaceae" not in bryophyte.families()
    # the family is taken from the genus, and a grass genus stood under a moss family
    grass = "Culms 30 cm. Spikelets paired; lower glume 4 mm; lemma awned; anthers 3."
    assert not is_bryophyte("Funariaceae", grass) and bryophyte.group("Funariaceae", grass) is False
    assert is_bryophyte("Funariaceae", "Plants small. Leaves ovate, costa percurrent. Seta 5 mm.")


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


def test_spore_capsule_parts_are_one_browse_group():
    from flopo2.saudi.vocab import Vocabulary

    vocab = Vocabulary()
    assert {vocab.organ_group(t) for t in ("PO:0025094", "PO:0030032", "PO:0030043", "PO:0030044", "PO:0025017")} == {"spore"}
    assert vocab.organ_group("PO:0025075") == "leaf" and vocab.organ_group("PO:0030022") == "stem"


def test_a_moss_is_not_matched_to_the_flowering_plant_of_the_same_name(tmp_path):
    from flopo2.saudi.build import BASE, Builder
    from flopo2.saudi.taxa import ResolvedName

    builder = Builder(tmp_path)
    amaranth = ResolvedName("Girgensohnia ruthenica", match_type="Exact", accepted_name="Girgensohnia oppositiflora",
                            accepted_wfo_id="wfo-0000000001", family="Amaranthaceae", order="Caryophyllales")
    moss = ResolvedName("Hypnum cupressiforme", match_type="Exact", accepted_name="Hypnum cupressiforme",
                        accepted_wfo_id="wfo-0000000002", family="Hypnaceae", order="Hypnales")
    builder.names = {"Girgensohnia ruthenica": amaranth, "Hypnum cupressiforme": moss}
    builder.ipni = {"Girgensohnia ruthenica": {
        "accepted_ipni_id": "165000-1", "accepted_wcvp_id": "1", "accepted_name": "Girgensohnia oppositiflora",
        "accepted_authors": "(Pall.) Fenzl", "family": "Amaranthaceae", "status": "Synonym", "ipni_id": "165001-1",
        "matched_name": "Girgensohnia ruthenica", "matched_authors": "Bunge"}}
    builder.wfo_to_ipni = {}

    plant = str(builder.taxon("Girgensohnia ruthenica", "eflora-fop", family="Amaranthaceae", bryophyte=False))
    assert plant == BASE + "taxon/ipni-165000-1"
    as_moss = str(builder.taxon("Girgensohnia ruthenica", "eflora-mfoc", family="Amaranthaceae", bryophyte=True))
    assert as_moss != plant and as_moss.endswith("taxon/name/Girgensohnia_ruthenica_-_bryophyte")
    assert builder.taxa[as_moss]["family"] == "" and builder.taxa[as_moss]["order"] == "" and not builder.taxa[as_moss]["ipni"]
    # a moss that the name service knows as a moss keeps its taxon; unknown group changes nothing
    assert str(builder.taxon("Hypnum cupressiforme", "eflora-mfoc", family="Hypnaceae", bryophyte=True)).endswith("wfo-0000000002")
    assert str(builder.taxon("Hypnum cupressiforme", "nybg-naf", bryophyte=None)).endswith("wfo-0000000002")
    # a flowering plant whose name the service gives to a moss is known by its printed name
    assert str(builder.taxon("Hypnum cupressiforme", "x", family="Malvaceae", bryophyte=False)).endswith("taxon/name/Hypnum_cupressiforme")


def test_descriptions_of_other_plants_are_not_part_of_the_moss_flora():
    sedge = {"taxon_family": "Cyperaceae", "text": "Rhizome short. Culms 30 cm. Utricles with a distinct costa."}
    assert bryophyte.misfiled("eflora-mfoc", sedge) and not bryophyte.misfiled("eflora-other", sedge)
    assert not bryophyte.misfiled("eflora-mfoc", {"taxon_family": "Pottiaceae", "text": "Leaves ovate."})
    assert bryophyte.group("", "Leaves ovate.") is None and bryophyte.group("Cyperaceae", "x") is False
