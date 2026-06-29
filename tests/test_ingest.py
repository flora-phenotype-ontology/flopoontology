"""Tests for FlorML and fdac CSV ingestion."""

from __future__ import annotations

from flopo2.ingest import fdac, florml
from flopo2.ingest.models import MORPHOLOGY_FEATURES

FLORML = """<?xml version="1.0" encoding="utf-8"?>
<publication lang="fr">
  <treatment>
    <taxon>
      <nomenclature><homotypes><nom class="accepted">
        <name class="family">Sapotaceae</name>
      </nom></homotypes></nomenclature>
      <feature class="description">
        <char class="habit">Arbres. Latex blanc.</char>
      </feature>
    </taxon>
    <taxon>
      <nomenclature><homotypes><nom class="accepted">
        <name class="genus">Manilkara</name>
        <name class="species">letestui</name>
        <name class="author">Aubr.</name>
      </nom></homotypes></nomenclature>
      <feature class="description">
        <char class="leaves">Feuilles oblongues.<br/>Glabres dessous.</char>
        <char class="flowers">Fleurs rouges.</char>
      </feature>
      <feature class="distribution">
        <char class="distribution">Gabon.</char>
      </feature>
    </taxon>
  </treatment>
</publication>
"""

FDAC = (
    "name_id|family|genus|species|authority|subspecies|subspauthority|variety|treatment_id|uuid|"
    "volume|page|description|altitudemodifier|altitude|maxaltitude|minaltitude|vernacular|usage|"
    "observations|distributionstring|habitatstring|chorologie|notes|footnote\n"
    "42|Proteaceae|Protea|congensis|Engl.||||||1|237|"
    "<span class='subheading'>Sous-arbuste</span> à souche ligneuse. "
    "<span class='subheading'>Feuilles</span> oblongues, glabres.|||||||||||\n"
)


def test_florml_segments_and_organs(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(FLORML)
    segs = list(florml.iter_segments(p))
    organs = {s.organ for s in segs}
    # Morphology only — distribution feature is skipped.
    assert "leaves" in organs and "flowers" in organs and "habit" in organs
    assert "distribution" not in organs
    assert all(s.language == "fr" for s in segs)


def test_florml_family_forward_fill(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(FLORML)
    segs = list(florml.iter_segments(p))
    sp = next(s for s in segs if s.taxon.species == "letestui")
    # Family declared on the parent family-taxon is forward-filled onto the species.
    assert sp.taxon.family == "Sapotaceae"
    assert sp.taxon.genus == "Manilkara"
    assert sp.taxon.rank == "species"


def test_florml_br_becomes_space(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(FLORML)
    segs = list(florml.iter_segments(p))
    leaves = next(s for s in segs if s.organ == "leaves")
    # The <br/> must not merge "oblongues." and "Glabres".
    assert "oblongues. Glabres" in leaves.text


def test_florml_offsets_monotonic(tmp_path):
    p = tmp_path / "f.xml"
    p.write_text(FLORML)
    sp_segs = [s for s in florml.iter_segments(p) if s.taxon.species == "letestui"]
    # Offsets within a taxon are non-overlapping and increasing.
    assert sp_segs[0].char_start == 0
    assert sp_segs[1].char_start >= sp_segs[0].char_end


def test_fdac_subheading_split(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text(FDAC)
    segs = list(fdac.iter_segments(p))
    organs = {s.organ: s for s in segs}
    assert "sous-arbuste" in organs  # subheading → organ (lowercased)
    assert "feuilles" in organs
    assert organs["feuilles"].taxon.genus == "Protea"
    assert organs["feuilles"].taxon.family == "Proteaceae"
    # HTML tags stripped.
    assert "<span" not in organs["feuilles"].text


def test_morphology_feature_set():
    # Guard against accidentally extracting non-phenotype sections.
    assert "description" in MORPHOLOGY_FEATURES
    assert "specimens" not in MORPHOLOGY_FEATURES
    assert "taxonomy" not in MORPHOLOGY_FEATURES
