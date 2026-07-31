import csv

from flopo2.extract.ground import Lexicon
from flopo2.terminology.obo_lexicon import write_obo_lexicon


def test_obo_lexicon_is_scoped_english_live_and_deterministic(tmp_path):
    obo = tmp_path / "po.obo"
    obo.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PO:0002\n"
        "name: flower\n"
        "namespace: plant_anatomy\n"
        "subset: reference\n"
        'synonym: "bloom" EXACT []\n'
        'synonym: "blossom (narrow)" NARROW []\n'
        'synonym: "flor (Spanish, exact)" EXACT Spanish []\n\n'
        "[Term]\n"
        "id: PO:0001\n"
        "name: leaf\n"
        "namespace: plant_anatomy\n\n"
        "[Term]\n"
        "id: PO:0999\n"
        "name: obsolete leaf thing\n"
        "is_obsolete: true\n",
        encoding="utf-8",
    )
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"
    assert write_obo_lexicon(obo, first, "PO") == 2
    assert write_obo_lexicon(obo, second, "PO") == 2
    assert first.read_bytes() == second.read_bytes()
    with first.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert [row["id"] for row in rows] == ["PO_0001", "PO_0002"]
    assert rows[1]["synonyms"] == "bloom|blossom"
    assert rows[1]["namespace"] == "plant_anatomy"


def test_pato_lexicon_carries_subsets_as_slims(tmp_path):
    obo = tmp_path / "pato.obo"
    obo.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PATO:1\n"
        "name: red\n"
        'synonym: "scarlet" EXACT []\n'
        'synonym: "reddish" RELATED []\n'
        'synonym: "warm colour" BROAD []\n'
        'synonym: "deep red" NARROW []\n'
        "subset: value_slim\n"
        "subset: scalar_slim\n",
        encoding="utf-8",
    )
    output = tmp_path / "pato.tsv"
    assert write_obo_lexicon(obo, output, "PATO") == 1
    with output.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle, delimiter="\t"))
    assert row["slim"] == "value_slim|scalar_slim"
    assert row["synonyms"] == "scarlet"


def test_context_gated_colour_homonym_is_not_unconditional(tmp_path):
    obo = tmp_path / "pato.obo"
    obo.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PATO:0104336\n"
        "name: olive colour\n"
        'synonym: "olive" EXACT []\n'
        'synonym: "olive-green" EXACT []\n'
        "subset: value_slim\n",
        encoding="utf-8",
    )
    output = tmp_path / "pato.tsv"
    assert write_obo_lexicon(obo, output, "PATO") == 1
    lexicon = Lexicon.load(output)
    assert lexicon.ground("olive") is None
    assert lexicon.ground("olive-green") == "PATO_0104336"
    assert lexicon.ground("olive colour") == "PATO_0104336"
