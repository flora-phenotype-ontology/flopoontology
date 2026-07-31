from __future__ import annotations

import pytest

from flopo2.extract.baseline import _organ_to_po, extract_segment


@pytest.mark.parametrize(
    ("heading", "po_id"),
    [
        ("fleurs", "PO_0009046"),
        ("feuilles", "PO_0009025"),
        ("graines", "PO_0009010"),
        ("tiges", "PO_0009047"),
        ("folioles", "PO_0020049"),
        ("périgone", "PO_0009058"),
        ("rameaux", "PO_0025073"),
        ("méricarpes", "PO_0020075"),
        ("plantule", "PO_0008037"),
    ],
)
def test_fdac_exact_french_structure_heading(heading, po_id):
    assert _organ_to_po(heading) == po_id


@pytest.mark.parametrize(
    "heading",
    ["arbre", "arbuste", "herbe", "liane", "suffrutex", "plante vivace"],
)
def test_fdac_growth_form_heading_uses_whole_plant(heading):
    assert _organ_to_po(heading) == "PO_0000003"


@pytest.mark.parametrize(
    "heading",
    ["racèmes", "panicules", "cymes", "capitules", "épis", "fascicules"],
)
def test_fdac_architecture_heading_uses_broad_inflorescence(heading):
    assert _organ_to_po(heading) == "PO_0009049"


@pytest.mark.parametrize(
    "heading",
    ["gousses", "capsules", "baies", "akènes", "siliques"],
)
def test_fdac_fruit_type_heading_uses_broad_fruit(heading):
    assert _organ_to_po(heading) == "PO_0009001"


@pytest.mark.parametrize(
    ("heading", "po_id"),
    [("drupes", "PO_0030103"), ("follicules", "PO_0030105")],
)
def test_fdac_exact_fruit_type_heading_uses_existing_po_class(heading, po_id):
    assert _organ_to_po(heading) == po_id


@pytest.mark.parametrize("heading", ["description", "variété", "espèce", "strobiles"])
def test_fdac_ambiguous_heading_remains_unmapped(heading):
    assert _organ_to_po(heading) == ""


def test_fdac_french_heading_drives_grounded_verbatim_assertions():
    segment = {
        "organ": "gousses",
        "language": "fr",
        "text": "Gousses oblongues, glabres et longues de 3–5 cm.",
    }
    assertions = extract_segment(segment)

    assert {assertion["po_id"] for assertion in assertions} == {"PO_0009001"}
    assert {assertion["pato_id"] for assertion in assertions} >= {
        "PATO_0000946",
        "PATO_0000453",
        "PATO_0000122",
    }
    assert all(assertion["source_text"] in segment["text"] for assertion in assertions)


def test_fdac_explicit_french_bearer_overrides_broad_heading():
    segment = {
        "organ": "habit",
        "language": "fr",
        "text": "Rameaux pubescents; feuilles glabres; arbuste dressé.",
    }
    pairs = {(row["po_id"], row["pato_id"]) for row in extract_segment(segment)}
    assert ("PO_0025073", "PATO_0001320") in pairs
    assert ("PO_0009025", "PATO_0000453") in pairs
    assert ("PO_0000003", "PATO_0000622") in pairs


def test_fdac_disjunction_is_retained_for_contextual_modeling():
    segment = {
        "organ": "rameaux",
        "language": "fr",
        "text": "Rameaux simples ou ramifiés; autres rameaux dressés.",
    }
    pairs = {(row["po_id"], row["pato_id"]) for row in extract_segment(segment)}
    assert ("PO_0025073", "PATO_0000402") not in pairs
    assert ("PO_0025073", "PATO_0000622") in pairs
