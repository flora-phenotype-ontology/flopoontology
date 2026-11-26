import json

from tools.atlas_patterns import SELECTORS, build as pattern_docs, to_html
from tools.atlas_places import aggregate
from tools.atlas_taxa_index import build as taxa_index

B = "http://phenomebrowser.net/flopo/browse#"
T = "http://phenomebrowser.net/flopo/taxon/"


def test_every_pattern_page_has_text_and_a_selector():
    docs = pattern_docs()
    ids = [p["id"] for p in docs["patterns"]]
    assert ids[0] == "00" and len(ids) == len(set(ids)) >= 15
    for p in docs["patterns"]:
        assert p["title"] and p["intent"] and "<h3>OWL</h3>" in p["html"], p["id"]
        assert p["selector"] == SELECTORS[p["id"]]
    assert "What goes into OWL" in docs["intro"]


def test_markdown_links_between_patterns_stay_on_the_site():
    html = to_html("See pattern [13](13-indefinite-count.md) and `a < b`.")
    assert 'href="#/patterns/13"' in html and "<code>a &lt; b</code>" in html


def _write(path, lines):
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_map_counts_coded_regions_and_flora_areas(tmp_path):
    occ = "<http://phenomebrowser.net/flopo/saudi-flora/occurrence/1>"
    # the lines of one record are not adjacent; the locality "Taif" names no country
    _write(tmp_path / "ncvc-places.nt", [
        f'{occ} <{B}locality> "Taif" .',
        f"<http://phenomebrowser.net/flopo/saudi-flora/occurrence/2> <{B}locality> \"Riyadh\" .",
        f"{occ} <{B}region> <http://phenomebrowser.net/flopo/geo/region/SA-02> .",
        f"{occ} <{B}taxon> <{T}ipni-1> .",
        f"{occ} <{B}source> <http://phenomebrowser.net/flopo/saudi-flora/source/ncvc> .",
    ])
    _write(tmp_path / "taxa.nt", [
        f"<http://phenomebrowser.net/flopo/taxon-name/ipni-2/collenette/0a1b2c3d> <{B}source> <http://phenomebrowser.net/flopo/saudi-flora/source/collenette> .",
    ])
    result = aggregate(tmp_path)
    sau = result["countries"]["SAU"]
    assert sau["taxa_places"] == 1 and sau["taxa_flora"] == 1 and sau["taxa"] == 2
    assert result["_taxa"]["SAU"] == {T + "ipni-1", T + "ipni-2"}


def test_taxon_index(tmp_path):
    _write(tmp_path / "taxa.nt", [
        f'<{T}ipni-2> <http://www.w3.org/2000/01/rdf-schema#label> "Acacia tortilis" .',
        f"<{T}ipni-2> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{B}Taxon> .",
        f"<{T}ipni-1> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <{B}Taxon> .",
        f'<{T}ipni-2/habitat/ncvc/0a1b2c3d> <http://www.w3.org/2000/01/rdf-schema#label> "sandy plains" .',
        f'<{T}ipni-2> <{B}family> "Fabaceae" .',
        f'<{T}ipni-1> <http://www.w3.org/2000/01/rdf-schema#label> "Abutilon" .',
        f"<http://phenomebrowser.net/flopo/taxon-name/ipni-2/ncvc/0a1b2c3d> <{B}source> <http://phenomebrowser.net/flopo/saudi-flora/source/ncvc> .",
    ])
    _write(tmp_path / "ncvc-index.nt", [
        f"<http://phenomebrowser.net/flopo/flora-assertion/a1> <{B}taxon> <{T}ipni-2> .",
        f"<http://phenomebrowser.net/flopo/flora-assertion/a2> <{B}taxon> <{T}ipni-2> .",
    ])
    index, position = taxa_index(tmp_path)
    assert [t[1] for t in index["taxa"]] == ["Abutilon", "Acacia tortilis"]
    acacia = index["taxa"][position["ipni-2"]]
    assert index["families"][acacia[3]] == "Fabaceae" and acacia[4] == 2 and index["sources"][acacia[5][0]] == "ncvc"
    json.dumps(index)


def test_taxon_index_has_printed_names_and_sorts_past_punctuation(tmp_path):
    label = "http://www.w3.org/2000/01/rdf-schema#label"
    typ = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    name = lambda flora, h, text: f'<http://phenomebrowser.net/flopo/taxon-name/ipni-7/{flora}/{h}> <{B}name> "{text}" .'
    _write(tmp_path / "taxa.nt", [
        f'<{T}ipni-7> <{label}> "Vachellia tortilis" .',
        f"<{T}ipni-7> <{typ}> <{B}Taxon> .",
        f"<{T}ipni-8> <{label}> \"'Lithospermum' corsonianum\" .",
        f"<{T}ipni-8> <{typ}> <{B}Taxon> .",
        f'<{T}ipni-9> <{label}> "Mimosa pudica" .',
        f"<{T}ipni-9> <{typ}> <{B}Taxon> .",
        name("collenette", "a1", "Acacia tortilis (Forssk.) Hayne"),
        name("kew-african", "a2", "Acacia tortilis subsp. raddiana (Savi) Brenan"),
        name("ncvc", "a3", "Vachellia tortilis"),  # the accepted name is not a synonym
        name("wfo", "a4", "Acacia"),  # a genus alone is not a name to search by
    ])
    index, position = taxa_index(tmp_path)
    assert [t[0] for t in index["taxa"]] == ["ipni-8", "ipni-9", "ipni-7"]  # L, M, V
    assert index["taxa"][position["ipni-7"]][7] == "Acacia tortilis|Acacia tortilis subsp. raddiana"
    assert index["taxa"][position["ipni-9"]][7] == ""
