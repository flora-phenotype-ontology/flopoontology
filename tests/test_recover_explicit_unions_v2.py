from __future__ import annotations

from flopo2.verify import recover_explicit_unions as v1
from flopo2.verify import recover_explicit_unions_v2 as v2


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000052
name: shape

[Term]
id: PATO:0002006
name: 2-D shape
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0002007
name: convex 3-D shape
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000946
name: oblong
subset: value_slim
is_a: PATO:0002006 ! 2-D shape

[Term]
id: PATO:0001891
name: ovate
subset: value_slim
is_a: PATO:0002007 ! convex 3-D shape

[Term]
id: PATO:0001877
name: lanceolate
subset: value_slim
is_a: PATO:0000052 ! shape

[Term]
id: PATO:0000066
name: pilosity

[Term]
id: PATO:0000453
name: glabrous
subset: value_slim
is_a: PATO:0000066 ! pilosity

[Term]
id: PATO:0001320
name: pubescent
subset: value_slim
is_a: PATO:0000066 ! pilosity

[Term]
id: PATO:0000014
name: colour

[Term]
id: PATO:0000324
name: yellow
subset: value_slim
is_a: PATO:0000014 ! colour

[Term]
id: PATO:0000320
name: green
subset: value_slim
is_a: PATO:0000014 ! colour
"""

QUALITY_FAMILY = {
    "PATO_0000946": "shape",
    "PATO_0001891": "shape",
    "PATO_0001877": "shape",
    "PATO_0000453": "pilosity",
    "PATO_0001320": "pilosity",
    "PATO_0000324": "colour",
    "PATO_0000320": "colour",
}
LABELS = {term: term for term in QUALITY_FAMILY}
DIMENSIONS = {"PATO_0000946": "2d", "PATO_0001891": "3d"}


def _record(
    text: str,
    operands: list[tuple[str, str]],
    *,
    organ: str = "description",
    taxon_family: str = "",
) -> dict:
    cursor = 0
    spans = []
    for surface, pato_id in operands:
        start = text.index(surface, cursor)
        cursor = start + len(surface)
        spans.append(
            {
                "start": start,
                "end": cursor,
                "surface_form": surface,
                "reason": "explicit_disjunction",
                "candidate_pato_id": pato_id,
                "extractor": "deterministic_baseline",
            }
        )
    return {
        "source": "test-flora",
        "source_id": "source-1",
        "source_segment_index": 0,
        "taxon": "Testus example",
        "taxon_family": taxon_family,
        "organ": organ,
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": spans,
    }


def _lexicon(tmp_path):
    path = tmp_path / "pato.obo"
    path.write_text(PATO_OBO, encoding="utf-8")
    return v1.ExactPatoValueLexicon.load(path)


def _recover(record, tmp_path, components):
    return v2.recover_record(
        record,
        QUALITY_FAMILY,
        DIMENSIONS,
        components,
        LABELS,
        _lexicon(tmp_path),
    )


def test_promotes_only_named_flopo_phenotype_operands_and_keeps_bearer_evidence(tmp_path):
    record = _record(
        "Gynophore glabrous or pubescent.",
        [("glabrous", "PATO_0000453"), ("pubescent", "PATO_0001320")],
    )
    components = {
        ("PO_0006330", "PATO_0000453"): "FLOPO_0001001",
        ("PO_0006330", "PATO_0001320"): "FLOPO_0001002",
    }

    recovered, outcomes, decisions = _recover(record, tmp_path, components)

    assert recovered["unresolved_spans"] == []
    assertion = recovered["assertions"][0]
    assert assertion["value_operator"] == "one_of"
    assert assertion["value_terms"] == ["PATO_0000453", "PATO_0001320"]
    assert assertion["source_text"] == "Gynophore glabrous or pubescent"
    assert "PATO union operands:PATO_0000453|PATO_0001320" in assertion[
        "mapping_provenance"
    ]
    assert "FLOPO phenotype operands:FLOPO_0001001|FLOPO_0001002" in assertion[
        "mapping_provenance"
    ]
    assert outcomes["resolved_evidence_spans"] == 2
    assert decisions[0].status == "promoted"


def test_routes_when_any_component_phenotype_is_not_named_in_flopo(tmp_path):
    record = _record(
        "Gynophore glabrous or pubescent.",
        [("glabrous", "PATO_0000453"), ("pubescent", "PATO_0001320")],
    )
    components = {("PO_0006330", "PATO_0000453"): "FLOPO_0001001"}

    recovered, _outcomes, decisions = _recover(record, tmp_path, components)

    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 2
    assert "component_phenotype_not_in_flopo" in {
        decision.reason for decision in decisions
    }


def test_routes_pato_2d_3d_shape_mixture_before_union(tmp_path):
    record = _record(
        "Spikelets ovate or oblong.",
        [("ovate", "PATO_0001891"), ("oblong", "PATO_0000946")],
    )
    components = {
        ("PO_0009051", "PATO_0001891"): "FLOPO_0004862",
        ("PO_0009051", "PATO_0000946"): "FLOPO_0006516",
    }

    recovered, _outcomes, decisions = _recover(record, tmp_path, components)

    assert recovered["assertions"] == []
    assert "mixed_pato_shape_dimensions" in {decision.reason for decision in decisions}


def test_clause_head_does_not_use_related_phyllary_or_record_organ_fallback(tmp_path):
    components = {
        ("PO_0009045", "PATO_0000453"): "FLOPO_0001001",
        ("PO_0009045", "PATO_0001320"): "FLOPO_0001002",
        ("PO_0009025", "PATO_0000453"): "FLOPO_0001003",
        ("PO_0009025", "PATO_0001320"): "FLOPO_0001004",
    }
    cases = (
        _record(
            "phyllaries glabrous or pubescent.",
            [("glabrous", "PATO_0000453"), ("pubescent", "PATO_0001320")],
        ),
        _record(
            "Mystery glabrous or pubescent.",
            [("glabrous", "PATO_0000453"), ("pubescent", "PATO_0001320")],
            organ="leaves",
        ),
    )

    for record in cases:
        recovered, _outcomes, decisions = _recover(record, tmp_path, components)
        assert recovered["assertions"] == []
        assert "heading_only_or_missing" in {decision.reason for decision in decisions}


def test_routes_container_ambiguous_receptacle_even_when_po_lexicon_matches(tmp_path):
    record = _record(
        "receptacle glabrous or pubescent.",
        [("glabrous", "PATO_0000453"), ("pubescent", "PATO_0001320")],
    )
    components = {
        ("PO_0009064", "PATO_0000453"): "FLOPO_0001001",
        ("PO_0009064", "PATO_0001320"): "FLOPO_0001002",
    }

    recovered, _outcomes, decisions = _recover(record, tmp_path, components)

    assert recovered["assertions"] == []
    assert "ambiguous_container_specific_bearer" in {
        decision.reason for decision in decisions
    }


def test_routes_banner_petal_outside_papilionaceous_taxon(tmp_path):
    text = "Étendard jaune ou vert."
    record = _record(
        text,
        [("jaune", "PATO_0000324"), ("vert", "PATO_0000320")],
        taxon_family="Balsaminaceae",
    )
    record["language"] = "fr"
    components = {
        ("PO_0025324", "PATO_0000324"): "FLOPO_0001001",
        ("PO_0025324", "PATO_0000320"): "FLOPO_0001002",
    }

    recovered, _outcomes, decisions = _recover(record, tmp_path, components)

    assert recovered["assertions"] == []
    assert "banner_petal_outside_papilionaceous_taxon" in {
        decision.reason for decision in decisions
    }
