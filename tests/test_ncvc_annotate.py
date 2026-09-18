import csv
import json

import pytest

from flopo2.ingest import ncvc_annotate as na
from flopo2.ingest import ncvc_guide
from flopo2.verify.data_model import validate_jsonl

DESCRIPTION_EN = (
    "A perennial evergreen shrub 3 m tall; the leaves are ovate, 2–4 cm long; "
    "flowers white or yellow; flowers white; fruit a capsule. Plant dioecious."
)


def _ph(entity, quality, po, pato, source, **extra):
    row = {
        "entity_en": entity,
        "quality_en": quality,
        "po_label": po,
        "pato_label": pato,
        "value_low": None,
        "value_high": None,
        "unit": "",
        "source_en": source,
        "source_ar": "",
        "qualifiers": {"negated": False, "stage": "", "frequency": "", "alternatives": []},
    }
    row.update(extra)
    return row


RECORD = {
    "source": ncvc_guide.SOURCE,
    "pdf_page": 28,
    "printed_pages": [54, 55],
    "scientific_name": "Ehretia obtusifolia",
    "authority": "Hochst. ex A.DC.",
    "family": "Boraginaceae",
    "synonyms": ["Ehretia aspera"],
    "description_ar": "شجيرة معمرة دائمة الخضرة، الأوراق بيضاوية",
    "description_en": DESCRIPTION_EN,
    "ksa_regions": [{"iso_3166_2": "SA-11", "name_en": "Al Bahah", "verbatim_ar": "منطقة الباحة"}],
    "localities": [
        {
            "verbatim_ar": "جبل فيفا",
            "name_en": "Jabal Fayfa",
            "feature_type": "mountain",
            "region_iso_3166_2": "SA-09",
            "region_basis": "inferred",
        }
    ],
    "growth_adaptation": {
        "temperature_c": {"ar": "27 م°", "en": "27 °C", "low": None, "high": 27},
        "soil_salinity_ppm": {"ar": "", "en": "less than 1000 ppm", "low": None, "high": 1000},
        "flowering": {"ar": "أبريل", "en": "April", "months": [4]},
    },
    "cultivation": {"elevation_m": {"ar": "", "en": "> 800 m", "low": 800, "high": None}},
    "phenotypes": [
        _ph("whole plant", "perennial", "whole plant", "", "perennial"),
        _ph("whole plant", "evergreen", "whole plant", "", "evergreen", source_ar="دائمة الخضرة"),
        _ph("whole plant", "height", "whole plant", "height", "3 m tall", value_high=3, unit="m"),
        _ph("leaf", "ovate", "leaf", "ovate", "leaves ovate"),
        _ph(
            "leaf", "length", "leaf", "length", "2–4 cm long", value_low=2, value_high=4, unit="cm"
        ),
        _ph(
            "flower",
            "white",
            "flower",
            "white",
            "flowers white or yellow",
            qualifiers={"negated": False, "stage": "", "frequency": "", "alternatives": ["yellow"]},
        ),
        _ph("flower", "white", "flower", "white", "flowers white"),
        _ph("fruit", "capsule", "capsule fruit", "", "fruit a capsule"),
        _ph("whole plant", "dioecious", "whole plant", "", "dioecious"),
        _ph("seed", "black", "seed", "black", "seeds black"),
    ],
}


def _tsv(path, header, rows):
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    return path


@pytest.fixture()
def catalogs(tmp_path):
    obo = tmp_path / "po.obo"
    obo.write_text(
        "".join(
            f"[Term]\nid: {curie}\nname: {name}\n{extra}\n"
            for curie, name, extra in (
                ("PO:0025034", "leaf", ""),
                ("PO:0000003", "whole plant", ""),
                ("PO:0009046", "flower", ""),
                ("PO:0009001", "fruit", ""),
                ("PO:0030091", "capsule fruit", 'synonym: "capsule" EXACT []'),
            )
        ),
        encoding="utf-8",
    )
    po_lex = _tsv(
        tmp_path / "po_lexicon.tsv",
        ["id", "label", "synonyms", "namespace"],
        [
            ("PO_0025034", "leaf", "", ""),
            ("PO_0000003", "whole plant", "", ""),
            ("PO_0009046", "flower", "", ""),
            ("PO_0009001", "fruit", "", ""),
            ("PO_0030091", "capsule fruit", "capsule", ""),
        ],
    )
    pato_lex = _tsv(
        tmp_path / "pato_lexicon.tsv",
        ["id", "label", "synonyms", "slim"],
        [
            ("PATO_0001891", "ovate", "", "value_slim"),
            ("PATO_0000119", "height", "", "attribute_slim"),
            ("PATO_0000122", "length", "", "attribute_slim"),
            ("PATO_0000467", "present", "", "value_slim"),
            ("PATO_0001733", "evergreen (plant)", "", "value_slim"),
            ("PATO_0000323", "white", "", "value_slim"),
            ("PATO_0000324", "yellow", "", "value_slim"),
            ("PATO_0000014", "color", "", "attribute_slim"),
        ],
    )
    registry = _tsv(
        tmp_path / "registry.tsv",
        ["flopo_iri", "flopo_num", "label", "signature", "deprecated"],
        [
            (
                "http://purl.obolibrary.org/obo/FLOPO_0000009",
                "9",
                "leaf ovate",
                "EQ|PO_0025034|PATO_0001891",
                "0",
            ),
            (
                "http://purl.obolibrary.org/obo/FLOPO_0005767",
                "5767",
                "whole plant evergreen (plant)",
                "EQ|PO_0000003|PATO_0001733",
                "0",
            ),
            (
                "http://purl.obolibrary.org/obo/FLOPO_0980073",
                "980073",
                "whole plant perennial",
                "OTHER",
                "0",
            ),
        ],
    )
    combos = _tsv(
        tmp_path / "combos.tsv",
        ["po_id", "pato_id", "status", "source", "example_label"],
        [
            ("PO_0025034", "PATO_0001891", "allowed", "curator_review_x", "leaf ovate"),
            ("PO_0000003", "PATO_0001733", "allowed", "curator_review_x", "whole plant evergreen"),
            ("PO_0000003", "PATO_0000119", "allowed", "curator_review_x", "whole plant height"),
            ("PO_0025034", "PATO_0000122", "allowed", "curator_review_x", "leaf length"),
            ("PO_0009046", "PATO_0000323", "allowed", "curator_review_x", "flower white"),
        ],
    )
    rules = _tsv(
        tmp_path / "rules.tsv",
        [
            "rule_id",
            "match_field",
            "match_key",
            "bearer_constraint",
            "kind",
            "po_id",
            "pato_id",
            "value_term",
            "flopo_class",
            "target_label",
            "evidence",
            "review_status",
        ],
        [
            (
                "Q01",
                "quality",
                "perennial",
                "",
                "flopo_phenotype_class",
                "",
                "",
                "",
                "FLOPO_0980073",
                "whole plant perennial",
                "e",
                "r",
            ),
            (
                "Q18",
                "quality",
                "evergreen",
                "",
                "pato",
                "",
                "PATO_0001733",
                "",
                "",
                "evergreen (plant)",
                "e",
                "r",
            ),
            (
                "Q29",
                "quality",
                "capsule",
                "",
                "entity_presence",
                "PO_0030091",
                "PATO_0000467",
                "",
                "",
                "capsule fruit present",
                "e",
                "r",
            ),
            (
                "Q26",
                "quality",
                "dioecious",
                "",
                "hold",
                "",
                "",
                "",
                "",
                "no sexual-system term",
                "e",
                "r",
            ),
        ],
    )
    holds = _tsv(
        tmp_path / "holds.tsv",
        [
            "rule_id",
            "pdf_page",
            "action",
            "entity_regex",
            "quality_regex",
            "source_regex",
            "reason_code",
            "reason",
            "evidence",
        ],
        [
            (
                "H16",
                "28",
                "hold",
                "^flower$",
                "white",
                "",
                "colour_contradicts_photos",
                "photos lilac",
                "notes",
            ),
            (
                "H99",
                "28",
                "drop_synonyms",
                "",
                "",
                "",
                "synonyms_other_species",
                "wrong synonyms",
                "notes",
            ),
        ],
    )
    res = na.load_resources(
        po_obo=obo,
        po_lexicon=po_lex,
        pato_lexicon=pato_lex,
        flopo_registry=registry,
        combinations=combos,
        normalization=rules,
        holds=holds,
    )
    return res, {"po_lexicon": po_lex, "pato_lexicon": pato_lex, "flopo_registry": registry}


def test_normalize_key_drops_parentheticals_and_habit_suffix():
    assert na.normalize_key("Legume (pod)") == "legume"
    assert na.normalize_key("shrub habit") == "shrub"
    assert na.normalize_key("tree growth form") == "tree"


def test_locate_span_prefers_literal_then_token_window_then_words():
    text = "The leaves are 1-2 mm long [sic], green; flowers yellow."
    assert na.locate_span(text, "leaves 1-2 mm long [sic]", [])[2] == "source_en_token_window"
    start, end, method = na.locate_span(text, "flowers yellow", [])
    assert (text[start:end], method) == ("flowers yellow", "source_en_exact")
    start, end, method = na.locate_span(text, "leaf colour", [("green", "quality_word")])
    assert (text[start:end], method) == ("green", "quality_word")
    assert na.locate_span(text, "seeds black", []) is None


def test_locate_span_prefers_unused_occurrence():
    text = "flowers white or yellow; flowers white."
    first = na.locate_span(text, "flowers white", [], 0)
    second = na.locate_span(text, "flowers white", [], 0, frozenset({first[0]}))
    assert second[0] > first[0]


@pytest.mark.parametrize(
    ("low", "high", "text", "expected"),
    [
        (None, 3, "3 m tall", (3.0, 3.0, "single", "")),
        (None, 8, "up to 8 m", (None, 8.0, "upper", "")),
        (
            None,
            1000,
            "less than 1000 ppm",
            (None, 1000.0, "upper", "upper_bound_cue_not_supported"),
        ),
        (1000, None, "> 1000 ppm", (1000.0, None, "lower", "")),
        (4, 2, "2-4 cm", (2.0, 4.0, "range", "")),
    ],
)
def test_normalize_bounds(low, high, text, expected):
    assert na.normalize_bounds(low, high, text) == expected


def test_rule_table_rejects_unknown_identifiers(catalogs):
    res, _paths = catalogs
    res.rules.append(
        na.NormalizationRule("X", "quality", "x", "", "pato", "", "PATO_9999999", "", "", "", "")
    )
    with pytest.raises(ValueError, match="unknown PATO"):
        na.check_rule_identifiers(res)


def test_annotate_record_dispositions(catalogs):
    res, _paths = catalogs
    segments, dispositions = na.annotate_record(RECORD, res)
    by_quality = {}
    for d in dispositions:
        by_quality.setdefault(d.row["quality_en"], []).append(d)
    assert by_quality["perennial"][0].status == "unresolved"
    assert by_quality["perennial"][0].reason == "flopo_phenotype_class_without_eq_signature"
    assert by_quality["perennial"][0].row["flopo_class"] == "FLOPO_0980073"
    evergreen = by_quality["evergreen"][0]
    assert evergreen.status == "accepted"
    assert evergreen.assertion["gate"]["flopo_iri"].endswith("FLOPO_0005767")
    assert evergreen.assertion["extractor"] == na.EXTRACTOR
    assert any("pdf_page=28" in p for p in evergreen.assertion["mapping_provenance"])
    assert any(
        p.startswith("source_ar: statement-") for p in evergreen.assertion["mapping_provenance"]
    )
    height = by_quality["height"][0].assertion
    assert (height["value_low"], height["value_high"], height["unit"]) == (3.0, 3.0, "m")
    white_alt, white_held = by_quality["white"]
    assert white_alt.reason == "taxon_level_alternatives_or_continuum"
    assert white_held.status == "held"
    assert white_held.assertion["gate"]["status"] == "review"
    assert "ncvc_hold:colour_contradicts_photos" in white_held.assertion["gate"]["reasons"]
    assert white_held.assertion["source_start"] == DESCRIPTION_EN.index("flowers white;")
    capsule = by_quality["capsule"][0].assertion
    assert (capsule["po_id"], capsule["pato_id"]) == ("PO_0030091", "PATO_0000467")
    assert capsule["gate"]["po_pato_status"] == "novel"
    assert by_quality["dioecious"][0].reason.startswith("no_ontology_term:")
    assert by_quality["black"][0].status == "unanchored"
    ar = next(s for s in segments if s["language"] == "ar" and s["organ"] == "description")
    assert [s["verbatim_text"] for s in ar["source_statements"]] == ["دائمة الخضرة"]


def test_annotated_segments_pass_strict_data_model_validation(catalogs, tmp_path):
    res, paths = catalogs
    segments, _ = na.annotate_record(RECORD, res)
    out = tmp_path / "out.jsonl"
    out.write_text(
        "".join(json.dumps(s, ensure_ascii=False) + "\n" for s in segments), encoding="utf-8"
    )
    report = validate_jsonl(
        out,
        stage="gated",
        require_annotation_class=True,
        strict_source_statements=True,
        **paths,
    )
    assert report["errors"] == 0, report["error_examples"]
    assert report["assertions"] == 6


def test_growth_rows_normalize_single_values_and_keep_comparators():
    rows = {r["trait"]: r for r in na.iter_growth_rows([RECORD])}
    assert (rows["temperature_c"]["low"], rows["temperature_c"]["high"]) == (27.0, 27.0)
    assert rows["temperature_c"]["note"].startswith("single printed value")
    assert rows["soil_salinity_ppm"]["bound_type"] == "upper"
    assert (rows["elevation_m"]["low"], rows["elevation_m"]["high"]) == (800.0, "")
    assert rows["flowering"]["months"] == "4"
    assert "TO:0002616" in rows["flowering"]["ontology_hint"]


def test_taxa_rows_drop_synonyms_flagged_as_other_species(catalogs):
    res, _paths = catalogs
    (row,) = na.iter_taxa_rows([RECORD], res.holds)
    assert row["synonyms"] == ""
    assert "H99:synonyms_other_species" in row["data_quality_flags"]


def test_distribution_join_with_gazetteer_and_taxa():
    rows = list(ncvc_guide.iter_distribution_rows([RECORD]))
    gazetteer = [{"verbatim_ar": "جبل فيفا", "geonames_id": "123"}]
    taxa = [{"pdf_page": "28", "accepted_name": "Ehretia obtusifolia"}]
    joined, extra = na.join_distribution(rows, gazetteer, taxa)
    assert "gaz_geonames_id" in extra and "taxa_accepted_name" in extra
    loc = next(r for r in joined if r["level"] == "locality")
    assert loc["gaz_geonames_id"] == "123"
    assert all(r["taxa_accepted_name"] == "Ehretia obtusifolia" for r in joined)


def test_run_writes_all_outputs(catalogs, tmp_path):
    res, paths = catalogs
    corpus = tmp_path / "corpus"
    raw = corpus / "raw"
    raw.mkdir(parents=True)
    with (raw / "pages-028-028.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(RECORD, ensure_ascii=False) + "\n")
        fh.write(json.dumps({"pdf_page": 29, "non_species_page": True}) + "\n")
    (corpus / "taxa.tsv").write_text(
        "pdf_page\taccepted_family\treliability\tnotes\n28\tEhretiaceae\tok\t\n",
        encoding="utf-8",
    )
    summary = na.run(corpus, res=res, catalog_paths=paths)
    derived = corpus / "derived"
    for name in (
        "ncvc-saudi-annotated.jsonl",
        "ncvc-saudi-distribution.tsv",
        "ncvc-saudi-growth-traits.tsv",
        "ncvc-saudi-taxa.tsv",
        "ncvc-saudi-whole-plant-classes.tsv",
        "ncvc-saudi-novel-eq-candidates.tsv",
        "ncvc-saudi-phenotype-dispositions.tsv",
        "summary.json",
        "validation.json",
        "REPORT.md",
    ):
        assert (derived / name).exists(), name
    assert summary["species_records"] == 1
    assert summary["page_coverage"]["non_species_pages"] == [29]
    assert summary["validation"]["errors"] == 0
    assert summary["taxa_family_corrections"] == 1
    assert "## Geography" in (derived / "REPORT.md").read_text(encoding="utf-8")
    with (derived / "ncvc-saudi-novel-eq-candidates.tsv").open(encoding="utf-8") as fh:
        novel = list(csv.DictReader(fh, delimiter="\t"))
    assert [r["signature"] for r in novel] == ["EQ|PO_0030091|PATO_0000467"]


def test_unreliable_description_in_taxa_review_holds_the_page(catalogs):
    res, _paths = catalogs
    taxa = [{"pdf_page": "28", "reliability": "unreliable_description", "notes": "copied"}]
    (rule,) = na.holds_from_taxa(taxa, res.holds)
    assert rule.action == "hold_all" and rule.matches(28, {})
    res.holds = [*res.holds, rule]
    _segments, dispositions = na.annotate_record(RECORD, res)
    assert all(d.status != "accepted" for d in dispositions)
