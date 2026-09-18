from __future__ import annotations

import csv


BASE = {
    "source": "fdac",
    "source_id": "source.xml",
    "source_segment_index": "1",
    "segment_id": "2",
    "taxon": "Taxon",
    "organ": "description",
    "language": "fr",
    "original_reason": "unsupported_alternative_or_transition",
    "proposed_reason": "locative_context",
    "proposed_pato_id": "PATO_0002228",
    "heading_candidate_bearer": "",
    "current_candidate_bearer": "",
    "extractor": "test",
}


def _row(clause: str, verbatim: str, locative: str, **updates: str) -> dict[str, str]:
    start = clause.index(verbatim)
    row = {
        **BASE,
        "clause": clause,
        "clause_start": "0",
        "clause_end": str(len(clause)),
        "span_start": str(start),
        "span_end": str(start + len(verbatim)),
        "source_span_start": str(start),
        "source_span_end": str(start + len(verbatim)),
        "verbatim": verbatim,
        "locative_phrase": locative,
    }
    row.update(updates)
    return row


def test_classifies_only_explicit_local_po_subregions():
    from flopo2.verify.audit_locative_bearers import classify_row

    leaf_apex = classify_row(_row("Limbe acuminé au sommet", "acuminé", "au sommet"))
    assert leaf_apex.disposition == "safe_existing_po"
    assert leaf_apex.proposed_bearer_id == "PO_0020137"

    leaf_base = classify_row(_row("Limbe atténué à la base", "atténué", "à la base"))
    assert leaf_base.proposed_bearer_id == "PO_0008019"

    petal_margin = classify_row(_row("Pétales glabres au bord", "glabres", "au bord"))
    assert petal_margin.proposed_bearer_id == "PO_0025008"

    lobe_apex = classify_row(
        _row("Corolle à lobes obtus au sommet", "obtus", "au sommet")
    )
    assert lobe_apex.disposition == "review"
    assert lobe_apex.container_surface == "lobes"

    no_local_container = classify_row(_row("Acuminé au sommet", "Acuminé", "au sommet"))
    assert no_local_container.disposition == "review"


def test_oriented_epidermis_vein_and_trichome_precedence():
    from flopo2.verify.audit_locative_bearers import classify_row

    leaf_surface = classify_row(
        _row("Limbe pubescent à la face inférieure", "pubescent", "à la face")
    )
    assert leaf_surface.proposed_bearer_id == "PO_0000049"
    assert leaf_surface.locative_orientation == "abaxial"

    petal_inside = classify_row(
        _row("Pétales glabres à l'intérieur", "glabres", "à l'intérieur")
    )
    assert petal_inside.proposed_bearer_id == "PO_0006053"

    corolla_inside = classify_row(
        _row("Corolle glabre à l'intérieur", "glabre", "à l'intérieur")
    )
    assert corolla_inside.disposition == "review"

    vein = classify_row(
        _row(
            "Nervures secondaires pubescentes à la face inférieure",
            "pubescentes",
            "à la face",
            organ="secondary veins",
            proposed_pato_id="PATO_0001320",
        )
    )
    assert vein.proposed_bearer_id == "PO_0020140"

    hair = classify_row(
        _row(
            "Bractées avec de longs poils blancs à la marge",
            "blancs",
            "à la marge",
            proposed_pato_id="PATO_0000323",
        )
    )
    assert hair.proposed_bearer_id == "PO_0000282"
    assert hair.attachment_rule == "direct_trichome_quality"

    not_hair = classify_row(
        _row(
            "Périanthe à poils noirs et sommet blanc à l'intérieur",
            "blanc",
            "à l'intérieur",
            proposed_pato_id="PATO_0000323",
        )
    )
    assert not_hair.disposition == "review"


def test_does_not_inherit_incidental_or_intervening_container_mentions():
    from flopo2.verify.audit_locative_bearers import classify_row

    incidental_petiole = classify_row(
        _row(
            "Limbe décurrent sur le pétiole, glabre à la face supérieure",
            "glabre",
            "à la face",
        )
    )
    assert incidental_petiole.disposition == "review"

    compared_sepal = classify_row(
        _row(
            "Bractées semblables aux sépales, glabres à l'intérieur",
            "glabres",
            "à l'intérieur",
        )
    )
    assert compared_sepal.disposition == "review"

    leaf_teeth = classify_row(
        _row(
            "Bord du limbe à grosses dents obtuses au sommet",
            "obtuses",
            "au sommet",
        )
    )
    assert leaf_teeth.disposition == "review"

    decimal_leaf = classify_row(
        _row(
            "Limbe de 4.0–6.5 cm, acuminé au sommet",
            "acuminé",
            "au sommet",
        )
    )
    assert decimal_leaf.proposed_bearer_id == "PO_0020137"

    following_container = classify_row(
        _row("Sépales dressés à la base du fruit", "dressés", "à la base")
    )
    assert following_container.disposition == "review"

    incidental_branching = classify_row(
        _row(
            "Plus courts que les feuilles, parfois ramifiés à la base",
            "ramifiés",
            "à la base",
            proposed_pato_id="PATO_0000402",
        )
    )
    assert incidental_branching.disposition == "review"


def test_audit_writes_complete_deterministic_artifacts(tmp_path):
    from flopo2.verify.audit_locative_bearers import APPENDED_FIELDS, audit_tsv

    rows = [
        _row("Feuilles acuminées au sommet", "acuminées", "au sommet"),
        _row("Corolle pubescente au niveau des anthères", "pubescente", "au niveau"),
    ]
    input_tsv = tmp_path / "input.tsv"
    fields = list(rows[0])
    with input_tsv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    output_dir = tmp_path / "out"
    summary = audit_tsv(input_tsv, output_dir)

    assert summary["input_rows"] == 2
    assert summary["safe_existing_po_rows"] == 1
    assert summary["review_rows"] == 1
    assert summary["invariant_safe_plus_review"] == 2
    decisions = list(
        csv.DictReader(
            (output_dir / "locative-bearer-decisions.tsv").open(encoding="utf-8"),
            delimiter="\t",
        )
    )
    assert len(decisions) == 2
    assert all(field in decisions[0] for field in APPENDED_FIELDS)
    assert decisions[0]["verbatim"] == "acuminées"
    assert decisions[0]["span_start"] == str(rows[0]["clause"].index("acuminées"))
    assert (output_dir / "grouped-safe-mappings.tsv").exists()
    assert (output_dir / "fixed-seed-safe-sample.tsv").exists()
    assert (output_dir / "fixed-seed-review-sample.tsv").exists()
