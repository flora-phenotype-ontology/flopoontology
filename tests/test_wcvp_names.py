from pathlib import Path

from flopo2.taxon.wcvp import Wcvp, ortho_close, printed_rank, split_name

HEADER = "plant_name_id|ipni_id|taxon_rank|taxon_status|family|taxon_name|taxon_authors|accepted_plant_name_id"
ROWS = [
    "1|100-1|Species|Accepted|Fabaceae|Vachellia tortilis|(Forssk.) Galasso & Banfi|1",
    "2|101-1|Subspecies|Accepted|Fabaceae|Vachellia tortilis subsp. raddiana|(Savi) Kyal. & Boatwr.|2",
    "3||Variety|Synonym|Fabaceae|Acacia tortilis var. raddiana|(Savi) Brenan|2",
    "4|103-1|Subspecies|Synonym|Fabaceae|Acacia tortilis subsp. raddiana|(Savi) Brenan|2",
    "5|200-1|Species|Accepted|Poaceae|Panicum reptans|L.|5",
    "6|201-1|Species|Illegitimate|Poaceae|Panicum reptans|Lam.|7",
    "7|202-1|Species|Accepted|Poaceae|Urochloa reptans|(L.) Stapf|7",
    "8|300-1|Species|Accepted|Plantaginaceae|Penstemon tubaeflorus|Nutt.|8",
    "9|400-1|Species|Accepted|Fagaceae|Quercus rubra|L.|9",
]


def wcvp(tmp_path: Path) -> Wcvp:
    # the loader needs only these columns; DictReader ignores column order
    path = tmp_path / "wcvp_names.csv"
    path.write_text("\n".join([HEADER, *ROWS]) + "\n", encoding="utf-8")
    return Wcvp(path)


def test_split_name_keeps_infraspecies_and_authors():
    assert split_name("Acacia tortilis (Forssk.) Hayne subsp. raddiana (Savi) Brenan") == ("acacia tortilis raddiana", "(Savi) Brenan")
    assert split_name("Abutilon angulatum (Guill. & Perr.) Mast.<br /> var. angulatum")[0] == "abutilon angulatum angulatum"
    assert printed_rank("Combretum L.f. ex Willd.") == ""


def test_rank_and_accepted_name(tmp_path):
    m = wcvp(tmp_path).match("Acacia tortilis (Forssk.) Hayne subsp. raddiana (Savi) Brenan")
    assert m.matched_name == "Acacia tortilis subsp. raddiana" and m.ipni_id == "103-1"
    assert m.accepted_ipni_id == "101-1" and m.accepted_name == "Vachellia tortilis subsp. raddiana"


def test_homonyms_by_author_or_wfo(tmp_path):
    w = wcvp(tmp_path)
    assert w.match("Panicum reptans L.").accepted_ipni_id == "200-1"
    assert w.match("Panicum reptans Lam.").accepted_ipni_id == "202-1"
    assert w.match("Panicum reptans", wfo_accepted="Urochloa reptans").accepted_ipni_id == "202-1"


def test_spelling_variants_only_when_close(tmp_path):
    w = wcvp(tmp_path)
    assert w.match("Penstemon tubiflorus").accepted_ipni_id == "300-1"
    assert w.match("Quercus robur").how == "none"
    assert not ortho_close("quercus robur", "quercus rubra")
