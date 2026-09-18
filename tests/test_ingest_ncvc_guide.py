import csv
import json

import pytest

from flopo2.ingest import ncvc_guide

RECORD = {
    "source": ncvc_guide.SOURCE,
    "pdf_page": 28,
    "scientific_name": "Ehretia obtusifolia",
    "authority": "Hochst. ex A.DC.",
    "family": "Boraginaceae",
    "description_ar": "شجيرة متساقطة الأوراق",
    "description_en": "A deciduous shrub 3 m tall; leaves ovate.",
    "ecology_en": "Rocky slopes and mountain wadis.",
    "ksa_regions": [
        {"iso_3166_2": "SA-11", "name_en": "Al Bahah", "verbatim_ar": "منطقة الباحة"},
        {"iso_3166_2": "SA-11", "name_en": "Al Bahah", "verbatim_ar": "الباحة"},
    ],
    "localities": [
        {
            "verbatim_ar": "جبل فيفا",
            "name_en": "Jabal Fayfa",
            "feature_type": "mountain",
            "region_iso_3166_2": "SA-09",
            "region_basis": "inferred",
        }
    ],
    "phenotypes": [
        {"entity_en": "leaf", "quality_en": "ovate", "po_label": "Leaf", "pato_label": "ovate"},
        {
            "entity_en": "shrub",
            "quality_en": "height",
            "po_label": "",
            "pato_label": "height",
            "value_low": 3,
            "value_high": 3,
            "unit": "m",
        },
        {"entity_en": "leaf", "quality_en": "x", "po_label": "leaf", "pato_label": "PATO_0000001"},
    ],
}


def _lexicon(tmp_path, name, rows):
    path = tmp_path / name
    with path.open("w", encoding="utf-8") as fh:
        fh.write("id\tlabel\tsynonyms\n")
        for row in rows:
            fh.write("\t".join(row) + "\n")
    return ncvc_guide.load_lexicon(path)


def _write(tmp_path, records):
    raw = tmp_path / "raw"
    raw.mkdir()
    with (raw / "pages-001-002.jsonl").open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return raw


def test_segments_are_bilingual_and_skip_non_species_pages(tmp_path):
    raw = _write(tmp_path, [RECORD, {"pdf_page": 318, "non_species_page": True}])
    segs = list(ncvc_guide.iter_segments(raw))
    assert [(s.organ, s.language) for s in segs] == [
        ("description", "ar"),
        ("description", "en"),
        ("habitat", "en"),
    ]
    assert [s.source_segment_index for s in segs] == [0, 1, 2]
    assert segs[0].taxon.name_string == "Ehretia obtusifolia Hochst. ex A.DC."
    assert segs[0].source_id == "ncvc-saudi-native-plants-guide-2024:page-028"


def test_distribution_dedupes_regions_and_keeps_localities():
    rows = list(ncvc_guide.iter_distribution_rows([RECORD]))
    regions = [r for r in rows if r["level"] == "region"]
    assert [r["iso_3166_2"] for r in regions] == ["SA-11"]
    (loc,) = [r for r in rows if r["level"] == "locality"]
    assert loc["region_name"] == "Jazan" and loc["basis"] == "inferred"


def test_distribution_whole_kingdom_expands_to_all_regions():
    rec = {**RECORD, "ksa_regions_all": True}
    regions = [r for r in ncvc_guide.iter_distribution_rows([rec]) if r["level"] == "region"]
    assert len(regions) == len(ncvc_guide.SAUDI_REGIONS)


def test_unknown_region_code_is_rejected():
    rec = {**RECORD, "ksa_regions": [{"iso_3166_2": "SA-13"}]}
    with pytest.raises(ValueError):
        list(ncvc_guide.iter_distribution_rows([rec]))


def test_phenotypes_ground_only_through_exact_lexicon_forms(tmp_path):
    po = _lexicon(tmp_path, "po.tsv", [("PO_0025034", "leaf", "")])
    pato = _lexicon(
        tmp_path, "pato.tsv", [("PATO_0001891", "ovate", ""), ("PATO_0000119", "height", "")]
    )
    reg = tmp_path / "reg.tsv"
    reg.write_text(
        "flopo_iri\tflopo_num\tlabel\tsignature\tdeprecated\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000009\t9\tleaf ovate\tEQ|PO_0025034|PATO_0001891\t0\n"
        "http://purl.obolibrary.org/obo/FLOPO_0000010\t10\tleaf height\tEQ|PO_0025034|PATO_0000119\t1\n",
        encoding="utf-8",
    )
    eq = ncvc_guide.load_eq_registry(reg)
    assert list(eq) == [("PO_0025034", "PATO_0001891")]
    rows = list(ncvc_guide.iter_phenotype_rows([RECORD], po, pato, eq))
    assert (rows[0]["po_id"], rows[0]["pato_id"]) == ("PO_0025034", "PATO_0001891")
    assert (rows[0]["flopo_id"], rows[0]["flopo_label"]) == ("FLOPO_0000009", "leaf ovate")
    assert rows[1]["po_status"] == "unlabelled" and rows[1]["pato_id"] == "PATO_0000119"
    # An identifier written as a label is not trusted.
    assert rows[2]["pato_id"] == "" and rows[2]["pato_status"] == "not_in_lexicon"


def test_lexicon_collision_is_not_grounded(tmp_path):
    po = _lexicon(tmp_path, "po.tsv", [("PO_1", "spine", ""), ("PO_2", "thorn", "spine")])
    assert ncvc_guide._ground("spine", po) == ("", "collision")


def test_main_writes_outputs(tmp_path, capsys):
    raw = _write(tmp_path, [RECORD])
    po = tmp_path / "po.tsv"
    po.write_text("id\tlabel\tsynonyms\nPO_0025034\tleaf\t\n", encoding="utf-8")
    obo = tmp_path / "po.obo"
    obo.write_text(
        "[Term]\nid: PO:0025034\nname: leaf\n"
        'synonym: "foliage leaf" EXACT []\nsynonym: "leaflet" NARROW []\n',
        encoding="utf-8",
    )
    lex = ncvc_guide.load_obo_exact_lexicon(obo, "PO")
    assert "foliage leaf" in lex and "leaflet" not in lex
    ncvc_guide.main(
        [
            str(raw),
            "-o",
            str(tmp_path / "out"),
            "--po-obo",
            str(obo),
            "--pato-lexicon",
            str(po),
            "--flopo-registry",
            "config/flopo_id_registry.tsv",
        ]
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"species": 1, "segments": 3, "distribution_rows": 2, "phenotype_rows": 3}
    with (tmp_path / "out" / "ncvc-saudi-distribution.tsv").open(encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh, delimiter="\t"))) == 2
