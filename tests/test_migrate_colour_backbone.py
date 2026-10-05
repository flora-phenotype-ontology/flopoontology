"""Tests for the colour-backbone value migration (exact / narrow / related rules)."""

from __future__ import annotations

import json
from pathlib import Path

from flopo2.annotation.operands import operands_fac_representable
from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.verify.migrate_colour_backbone import (
    Migrator,
    Rule,
    load_rules,
    main,
    migrate_file,
)

RULES = {
    "FLOPO_0980085": Rule("FLOPO_0980085", "FLOPO_0988006", "related", "greenish"),
    "PATO_0104314": Rule("PATO_0104314", "FLOPO_0988001", "narrow", "crimson"),
    "PATO_0104329": Rule("PATO_0104329", "PATO_0001287", "narrow", "chestnut colour"),
    "PATO_0104336": Rule("PATO_0104336", "FLOPO_0988005", "exact", "olive colour"),
    "FLOPO_0980264": Rule("FLOPO_0980264", "PATO_0001249", "exact", "dark-green"),
}
REGISTRY = {
    "EQ|PO_0009059|FLOPO_0988005": ("http://purl.obolibrary.org/obo/FLOPO_0990001", False),
}


def _gate(signature: str, status: str = "new_class_candidate", iri: str = "") -> dict:
    return {"status": "accepted", "reasons": [], "flopo_iri": iri, "flopo_status": status,
            "flopo_signature": signature}


def _assertion(text: str, surface: str, **fields) -> dict:
    start = text.index(surface)
    base = {
        "po_id": "PO_0009059", "pato_id": "PATO_0000014", "negated": False,
        "source_text": surface, "source_start": start, "source_end": start + len(surface),
        "value_text": surface, "value_operator": "atomic", "value_terms": [],
        "value_qualifier": "exact", "degree_qualifier": "unmodified",
        "frequency_qualifier": "unspecified", "epistemic_modality": "asserted",
        "modality_text": "", "mapping_provenance": [], "season_contexts": [],
        "bearer_context_qualities": [], "developmental_stage_contexts": [],
        "developmental_stage_operator": "atomic",
    }
    base.update(fields)
    return base


def _run(assertion: dict, text: str, rules=RULES) -> tuple[dict, Migrator]:
    migrator = Migrator(rules, REGISTRY)
    assert migrator.migrate_record({"text": text, "assertions": [assertion]})
    return assertion, migrator


def test_exact_rule_replaces_value_and_keeps_fac_and_registry_class():
    text = "corolla olive"
    a = _assertion(text, "olive", pato_id="PATO_0104336")
    a["gate"] = _gate("EQ|PO_0009059|PATO_0104336")
    a["phenotype_class_iri"] = "stale"
    a, m = _run(a, text)
    assert a["pato_id"] == "PATO_0000014" and a["value_terms"] == ["FLOPO_0988005"]
    assert a["value_qualifier"] == "exact" and not a["modality_text"]
    assert a["phenotype_class_iri"] == annotation_class_iri(a)
    assert a["gate"]["flopo_signature"] == "EQ|PO_0009059|FLOPO_0988005"
    assert a["gate"]["flopo_iri"].endswith("FLOPO_0990001")
    assert a["gate"]["flopo_status"] == "existing"
    assert "colour_backbone_migration:PATO_0104336->FLOPO_0988005" in a["mapping_provenance"]
    assert m.stats["by_rule"] == {"exact": 1}


def test_exact_rule_to_pato_target_keeps_pato_id_as_value():
    text = "corolla dark-green"
    a = _assertion(text, "dark-green", pato_id="FLOPO_0980264")
    a["gate"] = _gate("EQ|PO_0009059|FLOPO_0980264")
    a, _ = _run(a, text)
    assert a["pato_id"] == "PATO_0001249" and a["value_terms"] == []


def test_narrow_rule_generalises_without_qualifier():
    text = "petals crimson or white"
    a = _assertion(
        text, "crimson or white", value_operator="one_of",
        value_terms=["PATO_0104314", "PATO_0000323"],
    )
    a["gate"] = _gate("EQV|PO_0009059|ONE_OF|PATO_0000323&PATO_0104314", "annotation_extension_only")
    a["phenotype_class_iri"] = "stale"
    a, m = _run(a, text)
    assert a["value_terms"] == ["FLOPO_0988001", "PATO_0000323"]
    assert a["value_qualifier"] == "exact" and not a.get("value_operands")
    assert a["phenotype_class_iri"] == annotation_class_iri(a)
    assert "colour_backbone_migration:PATO_0104314->FLOPO_0988001" in a["mapping_provenance"]
    assert m.stats["by_rule"] == {"narrow": 1} and not m.stats["approximation"]


def test_related_atomic_is_assertion_level_approximation_and_keeps_fac():
    text = "leaves greenish"
    a = _assertion(text, "greenish", value_terms=["FLOPO_0980085"])
    a["gate"] = _gate("EQ|PO_0009059|FLOPO_0980085")
    a["phenotype_class_iri"] = "stale"
    a, m = _run(a, text)
    assert a["value_terms"] == ["FLOPO_0988006"]
    assert a["value_qualifier"] == "approximately"
    cue = text[a["modality_start"]:a["modality_end"]]
    assert cue == a["modality_text"] == "ish"
    assert operands_fac_representable(a)  # assertion-level cue: qualified, class link retained
    assert a["phenotype_class_iri"] == annotation_class_iri(a)


def test_related_in_union_gets_per_operand_approximation_and_no_fac():
    text = "petals white or greenish"
    a = _assertion(
        text, "white or greenish", value_operator="one_of",
        value_terms=["PATO_0000323", "FLOPO_0980085"],
    )
    a["gate"] = _gate("EQV|PO_0009059|ONE_OF|FLOPO_0980085&PATO_0000323", "annotation_extension_only")
    a["phenotype_class_iri"] = "https://w3id.org/flopo/annotation-class/FAC_old"
    a, m = _run(a, text)
    white, green = a["value_operands"]
    assert white["value"] == "PATO_0000323" and white["value_qualifier"] == "exact"
    assert green["value"] == "FLOPO_0988006" and green["value_qualifier"] == "approximately"
    assert text[green["qualifier_start"]:green["qualifier_end"]] == green["qualifier_text"] == "ish"
    assert a["value_qualifier"] == "exact"  # only the operand is approximate
    assert not operands_fac_representable(a)
    assert "phenotype_class_iri" not in a  # a non-entailing operand never carries a FAC IRI
    assert a["gate"]["flopo_status"] == "structured_annotation_only"
    assert a["gate"]["flopo_iri"] == ""
    assert a["gate"]["flopo_signature"] == "EQV|PO_0009059|ONE_OF|FLOPO_0988006&PATO_0000323"
    assert m.stats["fac"]["cleared_non_entailing_operand"] == 1


def test_related_existing_operand_is_marked_in_place():
    text = "petals white or greenish"
    a = _assertion(
        text, "white or greenish", value_operator="one_of",
        value_terms=["PATO_0000323", "FLOPO_0980085"],
        value_operands=[
            {"operand_index": 0, "value": "PATO_0000323", "text": "white", "start": 7, "end": 12,
             "degree_qualifier": "unmodified", "value_qualifier": "exact",
             "frequency_qualifier": "unspecified"},
            {"operand_index": 1, "value": "FLOPO_0980085", "text": "greenish", "start": 16,
             "end": 24, "degree_qualifier": "unmodified", "value_qualifier": "exact",
             "frequency_qualifier": "unspecified"},
        ],
    )
    a["gate"] = _gate("x", "annotation_extension_only")
    a, _ = _run(a, text)
    assert [o["value_qualifier"] for o in a["value_operands"]] == ["exact", "approximately"]
    assert a["value_operands"][1]["qualifier_text"] == "ish"


def test_related_relation_endpoint_gets_endpoint_operand():
    text = "greenish to red"
    a = _assertion(
        text, text,
        qualitative_value_relation={
            "interpretation": "continuum", "from_value": "FLOPO_0980085", "to_value": "PATO_0000322",
            "from_text": "greenish", "from_start": 0, "from_end": 8,
            "connector_text": "to", "connector_start": 9, "connector_end": 11,
            "to_text": "red", "to_start": 12, "to_end": 15,
        },
    )
    a["gate"] = _gate("QUALREL|PO_0009059|PATO_0000014|continuum|FLOPO_0980085|PATO_0000322",
                      "structured_annotation_only")
    a, m = _run(a, text)
    rel = a["qualitative_value_relation"]
    assert rel["from_value"] == "FLOPO_0988006" and rel["to_value"] == "PATO_0000322"
    assert rel["from_operand"]["value"] == "FLOPO_0988006"
    assert rel["from_operand"]["value_qualifier"] == "approximately"
    assert rel["from_operand"]["qualifier_text"] == "ish"
    assert "to_operand" not in rel and "phenotype_class_iri" not in a
    assert a["gate"]["flopo_signature"].endswith("continuum|FLOPO_0988006|PATO_0000322")


def test_relation_with_identical_endpoints_is_left_unchanged_and_reported():
    text = "crimson to red"
    rules = RULES
    a = _assertion(
        text, text,
        qualitative_value_relation={
            "interpretation": "continuum", "from_value": "PATO_0104314", "to_value": "FLOPO_0988001",
            "from_text": "crimson", "from_start": 0, "from_end": 7,
            "connector_text": "to", "connector_start": 8, "connector_end": 10,
            "to_text": "red", "to_start": 11, "to_end": 14,
        },
    )
    a["gate"] = _gate("QUALREL")
    migrator = Migrator(rules, REGISTRY)
    assert not migrator.migrate_record({"text": text, "assertions": [a]})
    assert a["qualitative_value_relation"]["from_value"] == "PATO_0104314"
    assert migrator.stats["degenerate"]["relation_identical_endpoints"] == 1


def test_duplicate_terms_collapse_to_atomic():
    text = "petals red or crimson"
    a = _assertion(
        text, "red or crimson", value_operator="one_of",
        value_terms=["FLOPO_0988001", "PATO_0104314"],
    )
    a["gate"] = _gate("x", "annotation_extension_only")
    a["phenotype_class_iri"] = "stale"
    a, m = _run(a, text)
    assert a["value_terms"] == ["FLOPO_0988001"] and a["value_operator"] == "atomic"
    assert m.stats["degenerate"]["duplicate_terms_collapsed"] == 1
    assert a["phenotype_class_iri"] == annotation_class_iri(a)


def test_load_rules_from_crosswalk_and_cli_roundtrip(tmp_path: Path):
    rules = load_rules()
    assert rules["FLOPO_0980085"].kind == "related" and rules["FLOPO_0980085"].new == "FLOPO_0988006"
    assert rules["PATO_0104314"].kind == "narrow" and rules["PATO_0104314"].new == "FLOPO_0988001"
    assert rules["PATO_0104336"].kind == "exact" and rules["PATO_0104336"].new == "FLOPO_0988005"
    text = "leaves greenish"
    assertion = _assertion(text, "greenish", value_terms=["FLOPO_0980085"])
    assertion["gate"] = _gate("EQ|PO_0009059|FLOPO_0980085")
    untouched = {"text": "x", "assertions": []}
    source = tmp_path / "in.jsonl"
    source.write_text(
        json.dumps({"text": text, "assertions": [assertion]}) + "\n" + json.dumps(untouched) + "\n"
    )
    out, report = tmp_path / "out.jsonl", tmp_path / "report.json"
    assert main([str(source), "-o", str(out), "--report", str(report)]) == 0
    lines = out.read_text().splitlines()
    assert lines[1] == json.dumps(untouched)  # unchanged records are copied verbatim
    migrated = json.loads(lines[0])["assertions"][0]
    assert migrated["value_terms"] == ["FLOPO_0988006"]
    assert json.loads(report.read_text())["by_rule_assertions"] == {"related": 1}
    # migrating the output again changes nothing
    again = migrate_file(out, tmp_path / "out2.jsonl", rules=rules)
    assert again["changed_assertions"] == 0
