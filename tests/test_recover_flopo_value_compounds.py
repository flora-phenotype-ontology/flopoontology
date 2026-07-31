from __future__ import annotations

import json

import pytest


REGISTRY = (
    "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
    "http://purl.obolibrary.org/obo/FLOPO_0980098\t980098\tcreamy-white\tOTHER\t0\n"
    "http://purl.obolibrary.org/obo/FLOPO_0980185\t980185\tgolden-yellow\tOTHER\t0\n"
    "http://purl.obolibrary.org/obo/FLOPO_0980999\t980999\tobsolete-val\tOTHER\t1\n"
)
PO = (
    "id\tlabel\tsynonyms\tnamespace\n"
    "PO_0009032\tpetal\tpetals\tplant_anatomy\n"
    "PO_0009001\tfruit\tfruits\tplant_anatomy\n"
)
PATO = "id\tlabel\tslim\nPATO_0000014\tcolor\tattribute_slim\n"


def _record(text: str, surfaces: list[tuple[str, str]]) -> dict:
    return {
        "source": "flora-test",
        "source_id": "one.xml",
        "source_segment_index": 0,
        "taxon": "Planta exemplar",
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
                "candidate_pato_id": pato,
                "extractor": "test",
            }
            for surface, pato in surfaces
        ],
    }


def _files(tmp_path):
    registry = tmp_path / "registry.tsv"
    registry.write_text(REGISTRY)
    po = tmp_path / "po.tsv"
    po.write_text(PO)
    pato = tmp_path / "pato.tsv"
    pato.write_text(PATO)
    return registry, po, pato


def test_lexicon_contains_only_audited_live_values(tmp_path):
    from flopo2.verify.recover_flopo_value_compounds import flopo_value_lexicon

    registry, _po, _pato = _files(tmp_path)
    lexicon = flopo_value_lexicon(registry)
    assert lexicon["creamy white"] == ("FLOPO_0980098", "creamy-white")
    assert all(value[0] != "FLOPO_0980999" for value in lexicon.values())
    assert "white hairy" not in lexicon
    assert "green striped" not in lexicon


def test_clean_compound_uses_pato_trait_and_flopo_value(tmp_path):
    from flopo2.owl.annotation_class import annotation_class_signature
    from flopo2.verify import recover_flopo_value_compounds as recovery
    from flopo2.verify.data_model import validate_jsonl
    from flopo2.verify.gates import check_assertion

    registry, po, pato = _files(tmp_path)
    input_path = tmp_path / "input.jsonl"
    output_path = tmp_path / "output.jsonl"
    input_path.write_text(
        json.dumps(
            _record(
                "Petals creamy-white.",
                [("creamy", "PATO_0000323"), ("white", "PATO_0000323")],
            )
        )
        + "\n"
    )
    report = recovery.recover_file(
        input_path, output_path, po_lexicon=po, registry=registry
    )
    record = json.loads(output_path.read_text())
    assertion = record["assertions"][0]
    assert report["outcomes"]["promoted:FLOPO_0980098"] == 1
    assert assertion["po_id"] == "PO_0009032"
    assert assertion["pato_id"] == "PATO_0000014"
    assert assertion["value_operator"] == "atomic"
    assert assertion["value_terms"] == ["FLOPO_0980098"]
    assert record["unresolved_spans"] == []
    assert annotation_class_signature(assertion)["quality"] == {
        "kind": "atomic",
        "terms": ["http://purl.obolibrary.org/obo/FLOPO_0980098"],
    }
    validation = validate_jsonl(
        output_path,
        po_lexicon=po,
        pato_lexicon=pato,
        flopo_registry=registry,
    )
    assert validation["ok"], validation
    decision = check_assertion(
        record["text"],
        {**assertion, "composition": {"status": "accept"}},
        {("PO_0009032", "PATO_0000014"): type("C", (), {"status": "allowed"})()},
        attribute_pato_ids={"PATO_0000014"},
        flopo_catalog_ids={"FLOPO_0980098"},
    )
    assert decision.status == "accepted"


def test_reused_guards_block_disjunction_and_transition(tmp_path):
    from flopo2.verify import recover_flopo_value_compounds as recovery

    registry, po, _pato = _files(tmp_path)
    lexicon = recovery.flopo_value_lexicon(registry)
    bearers = recovery.exact.BearerResolver(po)
    disjunction = _record(
        "Petals white or creamy-white.",
        [("creamy", "PATO_0000323"), ("white", "PATO_0000323")],
    )
    out, outcomes = recovery.recover_record(disjunction, lexicon, bearers)
    assert out["assertions"] == []
    assert outcomes["retained:logical_compound_context"] == 1

    transition = _record(
        "Fruit turning golden-yellow.",
        [("golden", "PATO_0000324"), ("yellow", "PATO_0000324")],
    )
    transition["organ"] = "fruits"
    out, outcomes = recovery.recover_record(transition, lexicon, bearers)
    assert out["assertions"] == []
    assert outcomes["retained:developmental_stage_context"] == 1


def test_pattern_scope_is_reverted_and_input_cannot_be_overwritten(tmp_path):
    from flopo2.verify import recover_flopo_value_compounds as recovery

    registry, po, _pato = _files(tmp_path)
    record = _record(
        "Petals creamy-white median stripes.",
        [("creamy", "PATO_0000323"), ("white", "PATO_0000323")],
    )
    source = tmp_path / "source.jsonl"
    source.write_text(json.dumps(record) + "\n")
    with pytest.raises(ValueError, match="distinct"):
        recovery.recover_file(source, source, po_lexicon=po, registry=registry)

    output = tmp_path / "output.jsonl"
    report = recovery.recover_file(source, output, po_lexicon=po, registry=registry)
    recovered = json.loads(output.read_text())
    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 2
    assert report["outcomes"]["retained:strict_pattern_or_marking_scope"] == 1
