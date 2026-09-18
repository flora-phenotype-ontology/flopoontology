from __future__ import annotations


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000051
name: morphology
subset: attribute_slim

[Term]
id: PATO:0000150
name: texture
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0000701
name: smooth
subset: value_slim
is_a: PATO:0000150 ! texture

[Term]
id: PATO:0000700
name: rough
subset: value_slim
is_a: PATO:0000150 ! texture

[Term]
id: PATO:0000014
name: color
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0000322
name: red
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000320
name: green
subset: value_slim
is_a: PATO:0000014 ! color

[Term]
id: PATO:0000141
name: structure
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0001503
name: simple
subset: value_slim
is_a: PATO:0000141 ! structure

[Term]
id: PATO:0002009
name: branchiness
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0000402
name: branched
subset: value_slim
is_a: PATO:0002009 ! branchiness

[Term]
id: PATO:0000122
name: length
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0000573
name: increased length
subset: value_slim
synonym: "long" EXACT []
is_a: PATO:0000122 ! length

[Term]
id: PATO:0104010
name: papyraceous
subset: value_slim
synonym: "chartaceous" EXACT []
is_a: PATO:0000150 ! texture

[Term]
id: PATO:0104032
name: coriaceous
subset: value_slim
is_a: PATO:0000150 ! texture

[Term]
id: PATO:0000140
name: position
subset: attribute_slim
is_a: PATO:0000051 ! morphology

[Term]
id: PATO:0002389
name: procumbent
subset: value_slim
is_a: PATO:0000140 ! position

[Term]
id: PATO:0000622
name: erect
subset: value_slim
is_a: PATO:0000140 ! position
"""


def _record(text: str, operands: list[tuple[str, str]]) -> dict:
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
        "organ": "petals",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": spans,
    }


def _audit_components(tmp_path):
    from flopo2.verify.audit_other_attribute_unions import (
        PatoAttributeGraph,
        _all_exact_value_lexicon,
    )

    pato = tmp_path / "pato.obo"
    pato.write_text(PATO_OBO, encoding="utf-8")
    graph = PatoAttributeGraph.load(pato)
    return graph, _all_exact_value_lexicon(graph)


def test_unique_common_attribute_is_the_most_specific_slim(tmp_path):
    graph, _lexicon = _audit_components(tmp_path)

    resolution = graph.unique_common_attribute(("PATO_0000701", "PATO_0000700"))

    assert resolution is not None
    assert resolution.pato_id == "PATO_0000150"
    assert resolution.label == "texture"
    assert resolution.distances == (1, 1)


def test_audit_queues_safe_nonreviewed_attribute_but_not_reviewed_family(tmp_path):
    from flopo2.verify.audit_other_attribute_unions import audit_record

    graph, lexicon = _audit_components(tmp_path)
    texture = _record(
        "Petals smooth or rough.",
        [("smooth", "PATO_0000701"), ("rough", "PATO_0000700")],
    )
    colour = _record(
        "Petals red or green.",
        [("red", "PATO_0000322"), ("green", "PATO_0000320")],
    )

    texture_rows, texture_outcomes = audit_record(texture, graph, lexicon)
    colour_rows, colour_outcomes = audit_record(colour, graph, lexicon)

    assert len(texture_rows) == 1
    assert texture_rows[0]["status"] == "review_queue"
    assert texture_rows[0]["attribute_pato_id"] == "PATO_0000150"
    assert texture_rows[0]["bearer_po_id"] == "PO_0009032"
    assert texture_outcomes[
        "candidate_review_queue:structurally_safe_nonreviewed_attribute"
    ] == 1
    assert colour_rows == []
    assert colour_outcomes["edge_excluded:already_in_reviewed_family"] == 1


def test_audit_does_not_fold_conjunctive_morphology_into_union(tmp_path):
    from flopo2.verify.audit_other_attribute_unions import audit_record

    graph, lexicon = _audit_components(tmp_path)
    record = _record(
        "Stems long, simple or branched.",
        [("simple", "PATO_0001503"), ("branched", "PATO_0000402")],
    )

    rows, _outcomes = audit_record(record, graph, lexicon)

    assert len(rows) == 1
    assert rows[0]["status"] == "review_queue"
    assert rows[0]["expression_text"] == "simple or branched"
    assert rows[0]["arity"] == 2


def test_audit_routes_unmodelled_preceding_alternatives(tmp_path):
    from flopo2.verify.audit_other_attribute_unions import audit_record

    graph, lexicon = _audit_components(tmp_path)
    serial = _record(
        "Leaves membranous, chartaceous, or coriaceous.",
        [
            ("chartaceous", "PATO_0104010"),
            ("coriaceous", "PATO_0104032"),
        ],
    )
    posture = _record(
        "Plants climbing, procumbent or erect.",
        [("procumbent", "PATO_0002389"), ("erect", "PATO_0000622")],
    )

    serial_rows, _outcomes = audit_record(serial, graph, lexicon)
    posture_rows, _outcomes = audit_record(posture, graph, lexicon)

    assert serial_rows[0]["status"] == "routed"
    assert serial_rows[0]["reason"] == "unmodelled_preceding_alternative"
    assert posture_rows[0]["status"] == "routed"
    assert posture_rows[0]["reason"] == "unmodelled_preceding_alternative"
