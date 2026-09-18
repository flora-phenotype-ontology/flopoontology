from __future__ import annotations


def _resolver(tmp_path):
    from flopo2.verify.recover_exact_pato_compounds import BearerResolver

    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0009025\tleaf\tleaves\n", encoding="utf-8")
    return BearerResolver(po)


def _record(text, spans):
    return {
        "source": "flora",
        "source_id": "1",
        "organ": "leaves",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": text.index(surface),
                "end": text.index(surface) + len(surface),
                "surface_form": surface,
                "reason": "same_attribute_composite_or_transition",
                "candidate_pato_id": pato_id,
                "extractor": "test",
            }
            for surface, pato_id in spans
        ],
    }


def test_recovers_only_independent_outline_from_cross_aspect_pair(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    record = _record(
        "Leaves oblong, acuminate.",
        [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
    )
    recovered, outcomes = recover_record(record, _resolver(tmp_path))

    assert [row["pato_id"] for row in recovered["assertions"]] == ["PATO_0000946"]
    assert recovered["assertions"][0]["source_text"] == "oblong"
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["acuminate"]
    assert outcomes["promoted:PATO_0000946"] == 1
    assert outcomes["resolved_evidence_spans"] == 1


def test_recovers_french_coordinated_outline_but_retains_termination(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    record = _record(
        "Feuilles oblongues et obtuses.",
        [("oblongues", "PATO_0000946"), ("obtuses", "PATO_0001935")],
    )
    recovered, _outcomes = recover_record(record, _resolver(tmp_path))

    assert [row["pato_id"] for row in recovered["assertions"]] == ["PATO_0000946"]
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["obtuses"]


def test_retains_same_aspect_transition_disjunction_compound_and_locative(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    examples = [
        (
            "Leaves elliptic, oblong.",
            [("elliptic", "PATO_0000947"), ("oblong", "PATO_0000946")],
        ),
        (
            "Leaves oblong to acuminate.",
            [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Leaves oblong or acuminate.",
            [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Leaves oblong-acuminate.",
            [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Leaves oblong at base, acuminate.",
            [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Leaves oblong to narrowly elliptic, acuminate.",
            [
                ("oblong", "PATO_0000946"),
                ("elliptic", "PATO_0000947"),
                ("acuminate", "PATO_0002228"),
            ],
        ),
        (
            "Petals lanceolate or ovate, linear, obtuse.",
            [
                ("lanceolate", "PATO_0001877"),
                ("ovate", "PATO_0001891"),
                ("linear", "PATO_0001199"),
                ("obtuse", "PATO_0001935"),
            ],
        ),
        (
            "Leaves lanceolate, sometimes broadly linear, acuminate.",
            [
                ("lanceolate", "PATO_0001877"),
                ("linear", "PATO_0001199"),
                ("acuminate", "PATO_0002228"),
            ],
        ),
    ]
    for text, spans in examples:
        record = _record(text, spans)
        recovered, outcomes = recover_record(record, _resolver(tmp_path))
        assert recovered["assertions"] == [], text
        assert len(recovered["unresolved_spans"]) == len(spans), text
        assert not outcomes, text


def test_reviewed_french_anther_alias_overrides_flower_heading(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    record = _record(
        "Anthères oblongues, obtuses.",
        [("oblongues", "PATO_0000946"), ("obtuses", "PATO_0001935")],
    )
    record["organ"] = "flowers"
    recovered, outcomes = recover_record(record, _resolver(tmp_path))

    assert [row["po_id"] for row in recovered["assertions"]] == ["PO_0009066"]
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["obtuses"]
    assert outcomes["promoted_bearer_method:explicit_local"] == 1


def test_routes_unmodelled_subparts_and_locative_bearers(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    examples = [
        (
            "Lemmas of the flowers elliptic, obtuse.",
            [("elliptic", "PATO_0000947"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Leaf with pinnae oblong, obtuse.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Leaves developed on sterile stem, oblong, acuminate.",
            [("oblong", "PATO_0000946"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Apical swelling of the flower bud oblong, obtuse.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Calyx with ovate, obtuse teeth.",
            [("ovate", "PATO_0001891"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Rhizome with narrowly lanceolate, attenuate scales.",
            [("lanceolate", "PATO_0001877"), ("attenuate", "PATO_0001982")],
        ),
        (
            "Rhizome covered with narrowly lanceolate, attenuate, ciliate rhizome-scales.",
            [("lanceolate", "PATO_0001877"), ("attenuate", "PATO_0001982")],
        ),
        (
            "Leaflets obliquely ovate lanceolate, acuminate.",
            [
                ("ovate", "PATO_0001891"),
                ("lanceolate", "PATO_0001877"),
                ("acuminate", "PATO_0002228"),
            ],
        ),
        (
            "Pods with a stipe 5 mm long, oblong, attenuate.",
            [("oblong", "PATO_0000946"), ("attenuate", "PATO_0001982")],
        ),
        (
            "Capsules oblong, attenuate, with 5 valves elliptic.",
            [("oblong", "PATO_0000946"), ("attenuate", "PATO_0001982")],
        ),
        (
            "One leaf on fertile stem, cauline, narrowly elliptic, acuminate.",
            [("elliptic", "PATO_0000947"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Leaves attenuate into a petiole, elliptic, acuminate.",
            [("elliptic", "PATO_0000947"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Tige présentant 11 feuilles alternes, simples, à pétiole de 2–10 mm "
            "de long, elliptiques, acuminées.",
            [("elliptiques", "PATO_0000947"), ("acuminées", "PATO_0002228")],
        ),
        (
            "Feuilles inférieures pétiolées (à pétioles largement ailés), "
            "elliptiques, atténuées.",
            [("elliptiques", "PATO_0000947"), ("atténuées", "PATO_0001982")],
        ),
        (
            "(? flowers with 5 narrow, oblong, obtuse, flat tepals; hermaphrodite "
            "flowers with 6 tepals.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Most leaflets are oblong and obtuse, but some acute.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Inflorescences; in male: bracts broadly elliptic, obtuse.",
            [("elliptic", "PATO_0000947"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Inflorescences; in male: many-flowered, peduncle 0.5-2 cm. long; bracts "
            "broadly elliptic, obtuse.",
            [("elliptic", "PATO_0000947"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Ray florets 12; rays broadly oblong, obtuse.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Longest pinnae 26 mm long and 8 mm wide, narrowly oblong, obtuse.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Upper leaves adpressed to the stem, smaller, lanceolate, acuminate.",
            [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Bracts clasping the pedicel, lanceolate, acuminate.",
            [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Bracts almost covering the flowers, lanceolate, acuminate.",
            [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Pedicelle long et bractéoles elliptiques, obtuses.",
            [("elliptiques", "PATO_0000947"), ("obtuses", "PATO_0001935")],
        ),
        (
            "Fertile stem with distant lanceolate acuminate sheaths.",
            [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Connective-appendage oblong, obtuse.",
            [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Petals oval to broadly elliptic, acuminate.",
            [("elliptic", "PATO_0000947"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Stipels narrowly lanceolate, acuminate.",
            [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Anthers with ovate, obtuse apical appendages.",
            [("ovate", "PATO_0001891"), ("obtuse", "PATO_0001935")],
        ),
        (
            "Anthères à appendice apical ovale, obtus.",
            [("ovale", "PATO_0001891"), ("obtus", "PATO_0001935")],
        ),
        (
            "Stipules oval-narrowly elliptic, acuminate.",
            [("elliptic", "PATO_0000947"), ("acuminate", "PATO_0002228")],
        ),
        (
            "Dorsal sepal oblong-ovate, elliptic, obtuse.",
            [("elliptic", "PATO_0000947"), ("obtuse", "PATO_0001935")],
        ),
    ]
    for text, spans in examples:
        record = _record(text, spans)
        recovered, outcomes = recover_record(record, _resolver(tmp_path))
        assert recovered["assertions"] == [], text
        assert not outcomes, text


def test_directly_coordinated_subject_bearers_each_receive_outline(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record
    from flopo2.verify.recover_exact_pato_compounds import BearerResolver

    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009055\tbract\tbracts\n"
        "PO_0009043\tbracteole\tbracteoles\n",
        encoding="utf-8",
    )
    record = _record(
        "Bracts and bracteoles linear, acuminate.",
        [("linear", "PATO_0001199"), ("acuminate", "PATO_0002228")],
    )
    recovered, outcomes = recover_record(record, BearerResolver(po))

    assert {row["po_id"] for row in recovered["assertions"]} == {
        "PO_0009055",
        "PO_0009043",
    }
    assert [row["surface_form"] for row in recovered["unresolved_spans"]] == ["acuminate"]
    assert outcomes["promoted:PATO_0001199"] == 2


def test_postposed_supported_bearer_closing_adjective_list_is_used(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    record = _record(
        "Flowers with 5 narrow, oblong, obtuse, flat tepals.",
        [("oblong", "PATO_0000946"), ("obtuse", "PATO_0001935")],
    )
    recovered, _outcomes = recover_record(record, _resolver(tmp_path))

    assert [row["po_id"] for row in recovered["assertions"]] == ["PO_0009033"]


def test_relational_object_does_not_beat_bracteole_subject(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    record = _record(
        "Bracteoles ascending from below the calyx, lanceolate, acuminate.",
        [("lanceolate", "PATO_0001877"), ("acuminate", "PATO_0002228")],
    )
    recovered, _outcomes = recover_record(record, _resolver(tmp_path))

    assert [row["po_id"] for row in recovered["assertions"]] == ["PO_0009043"]

    bract = _record(
        "Bract exceeding ovary, ovate, acuminate.",
        [("ovate", "PATO_0001891"), ("acuminate", "PATO_0002228")],
    )
    recovered, _outcomes = recover_record(bract, _resolver(tmp_path))
    assert [row["po_id"] for row in recovered["assertions"]] == ["PO_0009055"]

    petals = _record(
        "Pétales imbriqués dans le bouton, elliptiques, obtus.",
        [("elliptiques", "PATO_0000947"), ("obtus", "PATO_0001935")],
    )
    recovered, _outcomes = recover_record(petals, _resolver(tmp_path))
    assert recovered["assertions"] == []


def test_same_outline_with_qualified_or_alternative_is_not_consumed(tmp_path):
    from flopo2.verify.recover_cross_aspect_shapes import recover_record

    text = "Bracts lanceolate or broadly lanceolate, acuminate."
    first = text.index("lanceolate")
    second = text.index("lanceolate", first + 1)
    record = {
        "source": "flora",
        "source_id": "1",
        "organ": "leaves",
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": [
            {
                "start": start,
                "end": start + len(surface),
                "surface_form": surface,
                "reason": "same_attribute_composite_or_transition",
                "candidate_pato_id": pato_id,
                "extractor": "test",
            }
            for start, surface, pato_id in (
                (first, "lanceolate", "PATO_0001877"),
                (second, "lanceolate", "PATO_0001877"),
                (text.index("acuminate"), "acuminate", "PATO_0002228"),
            )
        ],
    }
    recovered, outcomes = recover_record(record, _resolver(tmp_path))

    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 3
    assert not outcomes
