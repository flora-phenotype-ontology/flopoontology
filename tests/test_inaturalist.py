from flopo2.saudi.inaturalist import approved_choice, name_key, photos, rank_ok, read_taxa


def fixture():
    taxon = {"name": "Acacia albida", "names": ["Acacia albida"], "family": "Fabaceae", "wfo": "wfo-1"}
    candidate = {"id": 10, "name": "Faidherbia albida", "rank": "species", "is_active": True,
                 "iconic_taxon_id": 47126, "ancestors": [{"rank": "family", "name": "Fabaceae"}]}
    decision = {"selected_id": 10, "relation": "exact", "confidence": "high"}
    return taxon, candidate, decision


def test_qwen_synonym_needs_independent_identity():
    taxon, candidate, decision = fixture()
    assert not approved_choice(taxon, candidate, decision, {})[0]
    assert not approved_choice(taxon, candidate, decision, {"Faidherbia albida": "wfo-2"})[0]
    assert approved_choice(taxon, candidate, decision, {"Faidherbia albida": "wfo-1"})[0]


def test_cannot_select_species_parent_for_infraspecific_taxon():
    taxon, candidate, decision = fixture()
    taxon["name"] = "Acacia albida var. example"
    assert not approved_choice(taxon, candidate, decision, {"Faidherbia albida": "wfo-1"})[0]
    assert rank_ok("Abies recurvata ernestii", "variety")
    assert not rank_ok("Abies recurvata var. ernestii", "subspecies")
    assert not rank_ok("Lotus corniculatus", "complex")
    assert name_key("Abies recurvata var. ernestii") == name_key("Abies recurvata ernestii")


def test_reject_wrong_family_inactive_and_nonplant():
    taxon, candidate, decision = fixture()
    taxon["names"].append(candidate["name"])
    assert approved_choice(taxon, candidate, decision, {})[0]
    for changes in ({"is_active": False}, {"iconic_taxon_id": 1},
                    {"ancestors": [{"rank": "family", "name": "Poaceae"}]}):
        assert not approved_choice(taxon, {**candidate, **changes}, decision, {})[0]


def test_reject_qwen_hallucinated_id_broad_or_uncertain_choice():
    taxon, candidate, decision = fixture()
    taxon["names"].append(candidate["name"])
    for changes in ({"selected_id": 99}, {"relation": "broader"}, {"confidence": "medium"}):
        assert not approved_choice(taxon, candidate, {**decision, **changes}, {})[0]


def test_historical_family_difference_requires_wfo_identity_and_qwen():
    taxon, candidate, decision = fixture()
    taxon["family"] = "Papilionaceae"
    taxon["names"].append(candidate["name"])
    wfo = {candidate["name"]: "wfo-1"}
    assert not approved_choice(taxon, candidate, None, wfo)[0]
    assert not approved_choice(taxon, candidate, decision, {})[0]
    assert approved_choice(taxon, candidate, decision, wfo)[0]


def test_photos_filter_licenses_deduplicate_and_preserve_attribution():
    photo = {"id": 1, "license_code": "cc-by", "url": "https://example.org/photos/1/square.jpg", "attribution": "Photographer"}
    row = {"default_photo": {**photo, "license_code": None}, "taxon_photos": [
        {"photo": photo}, {"photo": photo}, {"photo": {**photo, "id": 2, "license_code": "cc-by-nd"}},
        {"photo": {**photo, "id": 3, "url": "javascript:bad"}}]}
    result = photos(row)
    assert len(result) == 1
    assert result[0]["attribution"] == "Photographer"
    assert result[0]["url"].endswith("/medium.jpg")


def test_reads_only_actual_taxa_and_their_printed_synonyms(tmp_path):
    path = tmp_path / "taxa.nt"
    path.write_text('''<http://t> <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> <http://phenomebrowser.net/flopo/browse#Taxon> .
<http://t> <http://www.w3.org/2000/01/rdf-schema#label> "Faidherbia albida" .
<http://t> <http://phenomebrowser.net/flopo/browse#printedName> <http://n> .
<http://n> <http://phenomebrowser.net/flopo/browse#name> "Acacia albida" .
<http://n> <http://www.w3.org/2000/01/rdf-schema#label> "Not a taxon" .
''')
    result = read_taxa(path)
    assert len(result) == 1
    assert result[0]["names"] == ["Acacia albida", "Faidherbia albida"]


def test_release_copies_public_catalogue_only_and_supports_no_catalogue(tmp_path, monkeypatch):
    import json
    from tools import atlas_release
    data, web = tmp_path / "data", tmp_path / "web"
    data.mkdir()
    web.mkdir()
    (data / "summary.json").write_text('{}')
    (data / "inaturalist-audit.json").write_text('["private audit"]')
    (web / "index.html").write_text('atlas')
    monkeypatch.setattr(atlas_release, "_inputs", lambda *a, **kw: [])
    absent = atlas_release.build("absent", tmp_path / "releases", data, web)
    assert json.loads((absent / "web/inaturalist.json").read_text()) == {"taxa": {}}
    (data / "inaturalist.json").write_text('{"taxa":{"t":{"id":1}}}')
    present = atlas_release.build("present", tmp_path / "releases", data, web)
    assert json.loads((present / "web/inaturalist.json").read_text())["taxa"]["t"]["id"] == 1
    assert not (present / "web/inaturalist-audit.json").exists()


def test_web_release_preserves_published_rdf_and_summary(tmp_path):
    import json
    from tools.atlas_release import build_web, _sha256
    base, data, web = (tmp_path / n for n in ("base", "data", "web"))
    (base / "rdf").mkdir(parents=True)
    (base / "web").mkdir()
    (base / "index").mkdir()
    data.mkdir()
    web.mkdir()
    (base / "rdf/g.nq").write_text('<http://s> <http://p> <http://o> <http://g> .\n')
    (base / "web/summary.json").write_text('{"taxa":1}')
    (data / "summary.json").write_text('{"taxa":999}')
    (data / "inaturalist.json").write_text('{"taxa":{"t":{"id":1}}}')
    (web / "app.js").write_text('new browser')
    graph = {"file": "rdf/g.nq", "graph": "http://g", "triples": 1, "sha256": _sha256(base / "rdf/g.nq")}
    (base / "release.json").write_text(json.dumps({"stamp": "base", "commit": "old", "graphs": [graph], "triples": 1}))
    release = build_web("next", base, tmp_path / "releases", data, web)
    assert json.loads((release / "web/summary.json").read_text()) == {"taxa": 1}
    assert _sha256(release / "rdf/g.nq") == graph["sha256"]
    assert (release / "index").resolve() == (base / "index").resolve()
    meta = json.loads((release / "release.json").read_text())
    assert meta["graphs"] == [graph] and meta["base_release"] == "base"
    assert meta["inaturalist_sha256"] == _sha256(release / "web/inaturalist.json")
