from __future__ import annotations

import csv
from pathlib import Path

from rdflib import OWL, RDF, RDFS, Graph, URIRef

from tools.apply_pato_botanical_colour_terms import apply_terms
from tools.build_botanical_colour_terms import MODULE, OBO, build_modules
from tools.update_flopo_colour_sensu_release import BEGIN_MARKER, update_release


ROOT = Path(__file__).resolve().parents[1]
PROPOSALS = ROOT / "curation" / "botanical_colour_sensu_proposals.tsv"
IDS = ROOT / "config" / "botanical_colour_id_registry.tsv"
EVIDENCE = ROOT / "curation" / "botanical_evidence.tsv"
ORCID = "https://orcid.org/0000-0001-8149-5890"


def _build() -> tuple[str, str, list[dict[str, str]]]:
    return build_modules(PROPOSALS, IDS, EVIDENCE, "2026-07-15")


def test_pato_module_contains_generic_colours_only():
    pato_obo, _flopo_ttl, rows = _build()
    pato_rows = [row for row in rows if row["ontology_id"].startswith("PATO:")]
    new_ids = sorted(
        int(row["ontology_id"].split(":", 1)[1])
        for row in pato_rows
        if row["status"] == "new_pato_generic"
    )

    assert len(pato_rows) == 11
    assert new_ids == [
        104314,
        104317,
        104321,
        104324,
        104326,
        104329,
        104333,
        104336,
        104343,
    ]
    assert pato_obo.count("[Term]\n") == 11
    assert pato_obo.count("property_value: http://purl.org/dc/terms/contributor") == 11
    assert pato_obo.count(ORCID) == 11
    assert "name: cream\n" in pato_obo
    assert "id: PATO:0104031\n" in pato_obo
    assert "id: PATO:0001425\n" in pato_obo
    assert not any(line.startswith("name: ") and " sensu " in line for line in pato_obo.splitlines())
    assert "standardized scarlet (current reviewed set)" not in pato_obo
    assert "unionOf" not in pato_obo


def test_flopo_module_contains_every_source_qualified_colour():
    _pato_obo, flopo_ttl, rows = _build()
    graph = Graph().parse(data=flopo_ttl, format="turtle")
    flopo_rows = [row for row in rows if row["ontology_id"].startswith("FLOPO:")]
    classes = set(graph.subjects(RDF.type, OWL.Class))

    assert len(flopo_rows) == 25
    assert len(classes) == 25
    assert (MODULE, RDF.type, OWL.Ontology) in graph
    assert sorted(int(row["ontology_id"].split(":", 1)[1]) for row in flopo_rows) == list(
        range(980586, 980611)
    )
    by_key = {row["proposal_key"]: row for row in rows}
    for row in flopo_rows:
        cls = OBO[row["ontology_id"].replace(":", "_")]
        parent_row = by_key[row["asserted_parent"]]
        parent = OBO[parent_row["ontology_id"].replace(":", "_")]
        assert (cls, RDFS.subClassOf, parent) in graph
        assert str(parent).startswith(str(OBO) + "PATO_")
        assert " sensu " in row["preferred_label"]


def test_cream_uses_existing_pato_parent_and_new_flopo_senses():
    pato_obo, flopo_ttl, rows = _build()
    by_key = {row["proposal_key"]: row for row in rows}

    assert by_key["COLOR:cream"]["ontology_id"] == "PATO:0104031"
    assert by_key["COLOR:cream_rhs_5"]["ontology_id"] == "FLOPO:0980586"
    assert by_key["COLOR:cream_saccardo_1891"]["ontology_id"] == "FLOPO:0980587"
    assert 'synonym: "creamy" EXACT []' in pato_obo
    assert "cream sensu RHS Colour Chart fifth edition" not in pato_obo
    assert "cream sensu RHS Colour Chart fifth edition" in flopo_ttl


def test_registry_defers_only_optional_closed_union():
    with IDS.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    deferred = [row for row in rows if row["status"].startswith("deferred")]

    assert deferred == [
        {
            "proposal_key": "COLOR:scarlet_reviewed_union",
            "ontology_id": "",
            "status": "deferred_optional_closed_union",
        }
    ]


def test_apply_is_idempotent_removes_draft_sensu_terms_and_scopes_olive(tmp_path):
    pato_obo, _flopo_ttl, _rows = _build()
    module = tmp_path / "module.obo"
    module.write_text(pato_obo, encoding="utf-8")
    pato = tmp_path / "pato-edit.obo"
    pato.write_text(
        "format-version: 1.2\n\n"
        "[Term]\n"
        "id: PATO:0001425\n"
        "name: rosy\n"
        'def: "old rose definition" []\n\n'
        "[Term]\n"
        "id: PATO:0001942\n"
        "name: brown green\n"
        'def: "brown and green" []\n'
        'synonym: "olive green" EXACT []\n\n'
        "[Term]\n"
        "id: PATO:0104031\n"
        "name: cream sensu RHS Colour Chart fifth edition\n"
        'def: "draft source-specific cream" []\n\n'
        "[Term]\n"
        "id: PATO:0104345\n"
        "name: straw yellow sensu Ridgway (1912)\n"
        'def: "draft source-specific straw" []\n\n'
        "[Typedef]\n"
        "id: part_of\n"
        "name: part of\n",
        encoding="utf-8",
    )

    replaced, inserted, removed = apply_terms(pato, module)
    first = pato.read_text(encoding="utf-8")
    replaced_again, inserted_again, removed_again = apply_terms(pato, module)
    second = pato.read_text(encoding="utf-8")

    assert (replaced, inserted, removed) == (2, 9, 1)
    assert (replaced_again, inserted_again, removed_again) == (11, 0, 0)
    assert first == second
    assert first.count("id: PATO:0001425\n") == 1
    assert first.count("id: PATO:0104031\n") == 1
    assert "id: PATO:0104345\n" not in first
    assert not any(line.startswith("name: ") and " sensu " in line for line in first.splitlines())
    assert first.count('synonym: "olive green" RELATED []') == 1
    assert 'synonym: "olive green" EXACT []' not in first


def test_flopo_release_embedding_is_idempotent(tmp_path):
    _pato_obo, flopo_ttl, _rows = _build()
    module = tmp_path / "flopo-colour-sensu-extension.ttl"
    module.write_text(flopo_ttl, encoding="utf-8")
    release = tmp_path / "flopo.owl"
    release.write_text(
        '<?xml version="1.0"?>\n'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
        'xmlns:owl="http://www.w3.org/2002/07/owl#" '
        'xmlns:rdfs="http://www.w3.org/2000/01/rdf-schema#" '
        'xmlns:obo="http://purl.obolibrary.org/obo/" '
        'xmlns:dcterms="http://purl.org/dc/terms/">\n'
        '  <owl:Ontology rdf:about="http://purl.obolibrary.org/obo/flopo.owl">\n'
        '    <owl:versionIRI rdf:resource="http://purl.obolibrary.org/obo/flopo/releases/2026-07-14/flopo.owl"/>\n'
        '    <owl:versionInfo>2026-07-14</owl:versionInfo>\n'
        '  </owl:Ontology>\n'
        "</rdf:RDF>\n",
        encoding="utf-8",
    )

    assert update_release(release, module, "2026-07-15") == 25
    first = release.read_text(encoding="utf-8")
    assert update_release(release, module, "2026-07-15") == 25
    second = release.read_text(encoding="utf-8")

    assert first == second
    assert second.count(BEGIN_MARKER) == 1
    graph = Graph().parse(release.as_posix())
    assert len(
        {
            cls
            for cls in graph.subjects(RDF.type, OWL.Class)
            if isinstance(cls, URIRef) and str(cls).startswith(str(OBO) + "FLOPO_0980")
        }
    ) == 25


def test_checked_in_pato_dependency_has_generics_but_no_draft_sensu_terms():
    pato = (ROOT / "ont" / "quality.obo").read_text(encoding="utf-8")
    _pato_obo, _flopo_ttl, rows = _build()
    generic_ids = {
        row["ontology_id"]
        for row in rows
        if row["ontology_id"].startswith("PATO:")
    }

    for pato_id in generic_ids:
        assert pato.count(f"id: {pato_id}\n") == 1
    draft_range = {f"PATO:{number:07d}" for number in range(104312, 104346)}
    for stale_id in draft_range - generic_ids:
        assert f"id: {stale_id}\n" not in pato
    managed_blocks = [
        block
        for block in pato.split("\n\n")
        if any(f"id: {pato_id}\n" in block for pato_id in generic_ids)
    ]
    assert len(managed_blocks) == 11
    assert not any(
        line.startswith("name: ") and " sensu " in line
        for block in managed_blocks
        for line in block.splitlines()
    )


def test_actual_flopo_release_contains_local_senses_with_pato_parents():
    graph = Graph().parse((ROOT / "ontology" / "flopo.owl").as_posix())
    _pato_obo, _flopo_ttl, rows = _build()
    by_key = {row["proposal_key"]: row for row in rows}
    flopo_rows = [row for row in rows if row["ontology_id"].startswith("FLOPO:")]

    for row in flopo_rows:
        cls = OBO[row["ontology_id"].replace(":", "_")]
        parent_row = by_key[row["asserted_parent"]]
        parent = OBO[parent_row["ontology_id"].replace(":", "_")]
        assert (cls, RDF.type, OWL.Class) in graph
        assert list(graph.objects(cls, RDFS.subClassOf)) == [parent]
