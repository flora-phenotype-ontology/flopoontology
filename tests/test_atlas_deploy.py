from tools.atlas_checks import compare, graph_count_differences
from tools.atlas_release import export_graph


def _result(variables, *rows):
    return {"head": {"vars": variables}, "results": {"bindings": [
        {v: cell for v, cell in zip(variables, row) if cell is not None} for row in rows]}}


def _lit(value, datatype=None):
    cell = {"type": "literal", "value": value}
    if datatype:
        cell["datatype"] = "http://www.w3.org/2001/XMLSchema#" + datatype
    return cell


def test_compare_tolerates_engine_differences():
    qlever = _result(["t", "n", "names"], [_lit("a"), _lit("3", "int"), _lit("x; y")], [_lit("b"), _lit("1", "int"), None])
    oxigraph = _result(["t", "n", "names"], [_lit("b"), _lit("1", "integer"), None], [_lit("a"), _lit("3", "integer"), _lit("y; x")])
    assert compare(qlever, oxigraph) == (True, 0, 6)
    fewer = _result(["t", "n", "names"], [_lit("a"), _lit("3", "int"), _lit("x; y")])
    assert compare(qlever, fewer)[0] is False
    other = _result(["t", "n", "names"], [_lit("a"), _lit("4", "int"), _lit("x; y")], [_lit("b"), _lit("1", "int"), None])
    assert compare(qlever, other) == (True, 1, 6)


def test_export_keeps_blank_nodes_of_two_files_apart(tmp_path):
    for name in ("a", "b"):
        (tmp_path / f"{name}.nt").write_text(f"_:x <http://p> <http://{name}> .\n")
    export_graph(tmp_path / "a.nt", "http://g/a", tmp_path / "a.nq", "g0x")
    export_graph(tmp_path / "b.nt", "http://g/b", tmp_path / "b.nq", "g1x")
    a, b = (tmp_path / "a.nq").read_text(), (tmp_path / "b.nq").read_text()
    assert a.startswith("_:g0xx ") and b.startswith("_:g1xx ") and "<http://g/a>" in a


def test_graph_counts_allow_empty_graphs_but_detect_data_loss_and_unexpected_data():
    expected = {"http://g/traits": 23, "http://g/places": 0}
    assert graph_count_differences(expected, {"http://g/traits": 23}) == []
    assert graph_count_differences(expected, {}) == ["http://g/traits 23 -> 0"]
    assert graph_count_differences(expected, {"http://g/traits": 22}) == ["http://g/traits 23 -> 22"]
    assert graph_count_differences(expected, {"http://g/traits": 23, "http://g/extra": 1}) == ["http://g/extra 0 -> 1"]


def test_parity_sample_keeps_every_graph_and_cuts_only_the_large_ones(tmp_path, monkeypatch):
    import json

    from tools import atlas_checks

    release = tmp_path / "rel"
    (release / "rdf").mkdir(parents=True)
    sizes = {"a": 3, "b": 40, "c": 100}
    graphs = []
    for name, n in sizes.items():
        (release / f"rdf/{name}.nq").write_text("".join(f"<s{i}> <p> <o> <http://g/{name}> .\n" for i in range(n)))
        graphs.append({"graph": f"http://g/{name}", "file": f"rdf/{name}.nq", "triples": n, "sha256": "x"})
    (release / "release.json").write_text(json.dumps({"stamp": "t", "triples": 143, "graphs": graphs}))

    monkeypatch.setattr(atlas_checks, "PARITY_MAX_TRIPLES", 1000)
    assert not atlas_checks.make_parity_sample(release, tmp_path / "none", budget=50)

    monkeypatch.setattr(atlas_checks, "PARITY_MAX_TRIPLES", 100)
    out = tmp_path / "sample"
    assert atlas_checks.make_parity_sample(release, out, budget=50)
    meta = json.loads((out / "release.json").read_text())
    got = {g["graph"].rsplit("/", 1)[-1]: g["triples"] for g in meta["graphs"]}
    assert got == {"a": 3, "b": 23, "c": 24} and meta["triples"] == 50
    for name, n in got.items():
        assert len((out / f"rdf/{name}.nq").read_text().splitlines()) == n


def test_downloads_have_every_graph_and_flat_tables(tmp_path):
    import csv
    import gzip
    import json

    from tools import atlas_downloads as dl

    fb, base, obo = dl.FB, dl.BASE, dl.OBO
    g = base + "saudi-flora/graph/"
    rec, alt, taxon, src = base + "flora-assertion/r1", base + "flora-assertion/r1/alternative/1", base + "taxon/ipni-1-1", base + "saudi-flora/source/demo"

    def nq(graph, *triples):
        return "".join(f"<{s}> <{p}> {o if o.startswith('\"') else '<' + o + '>'} <{g}{graph}> .\n" for s, p, o in triples)

    files = {
        "00-demo-index.nq": nq(
            "demo/index",
            (rec, dl.RDF_TYPE, fb + "TraitRecord"), (rec, fb + "taxon", taxon), (rec, fb + "source", src),
            (rec, fb + "bearer", obo + "PO_0025034"), (rec, fb + "quality", obo + "PATO_0000323"),
            (rec, fb + "quality", obo + "PATO_0000014"), (rec, fb + "valueOperator", '"one_of"'),
            (rec, fb + "status", '"accepted"'), (rec, fb + "negated", '"false"^^<http://www.w3.org/2001/XMLSchema#boolean>'),
            (rec, fb + "text", '"white\\tor rarely red"'), (rec, dl.RDFS_LABEL, '"leaf white or red"'),
            (rec, fb + "alternative", alt), (alt, fb + "quality", obo + "PATO_0000322"), (alt, fb + "frequency", '"rarely"'),
            (base + "saudi-flora/pending/p1", dl.RDF_TYPE, fb + "PendingStatement"),
        ),
        "01-demo-places.nq": nq(
            "demo/places",
            (base + "saudi-flora/occurrence/o1", dl.RDF_TYPE, fb + "Occurrence"),
            (base + "saudi-flora/occurrence/o1", fb + "taxon", taxon), (base + "saudi-flora/occurrence/o1", fb + "source", src),
            (base + "saudi-flora/occurrence/o1", fb + "locality", '"Quebec"'),
        ),
        "02-empty-places.nq": "",
        "03-taxa.nq": nq(
            "taxa",
            (taxon, dl.RDF_TYPE, fb + "Taxon"), (taxon, dl.RDFS_LABEL, '"Aus bus"'), (taxon, fb + "family", '"Aaceae"'),
            (taxon, fb + "ipni", '"1-1"'), (taxon, fb + "printedName", base + "taxon-name/ipni-1-1/demo/x"),
            (base + "taxon-name/ipni-1-1/demo/x", fb + "name", '"Aus buss"'), (base + "taxon-name/ipni-1-1/demo/x", fb + "source", src),
        ),
        "04-vocab.nq": nq(
            "vocab",
            (obo + "PO_0025034", dl.RDFS_LABEL, '"leaf"'), (obo + "PO_0025034", fb + "curie", '"PO:0025034"'),
            (obo + "PATO_0000323", dl.RDFS_LABEL, '"white"'), (obo + "PATO_0000014", dl.RDFS_LABEL, '"red"'),
            (src, dl.RDF_TYPE, fb + "Source"), (src, dl.RDFS_LABEL, '"Demo"'), (src, dl.DCT + "title", '"Demo flora"'),
        ),
    }
    release = tmp_path / "rel"
    (release / "rdf").mkdir(parents=True)
    graphs = []
    for name, text in files.items():
        (release / "rdf" / name).write_text(text)
        graph = g + name[3:-3].replace("demo-", "demo/").replace("empty-", "empty/")
        graphs.append({"graph": graph, "file": f"rdf/{name}", "triples": text.count("\n"), "sha256": "x"})
    (release / "release.json").write_text(json.dumps({"stamp": "t", "graphs": graphs}))

    out = dl.build(release, jobs=2)

    def table(name):
        with gzip.open(out / "tsv" / name, "rt", encoding="utf-8") as handle:
            return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE))

    listing = json.loads((out / "downloads.json").read_text())
    paths = {f["path"] for f in listing["files"]}
    # every graph with data is offered, the empty one is not; the compressed file is the graph
    assert {"rdf/00-demo-index.nq.gz", "rdf/03-taxa.nq.gz"} <= paths and "rdf/02-empty-places.nq.gz" not in paths
    assert gzip.open(out / "rdf" / "00-demo-index.nq.gz", "rt").read() == files["00-demo-index.nq"]
    (row,) = table("traits-demo.tsv.gz")  # the pending statement is not a trait record
    assert table("traits-all.tsv.gz") == [row]
    assert row["entity_id"] == "PO:0025034" and row["entity_label"] == "leaf"
    assert row["quality_id"] == "PATO:0000014|PATO:0000323" and row["quality_label"] == "red|white"
    assert row["taxon_name"] == "Aus bus" and row["ipni_id"] == "1-1" and row["source"] == "demo"
    assert row["source_text"] == "white or rarely red"  # the tab inside the text is gone
    assert row["alternative_frequencies"] == "PATO:0000322=rarely"
    assert list(row) == dl.header(dl.TRAIT_COLUMNS)
    assert table("occurrences.tsv.gz")[0]["locality"] == "Quebec"
    assert table("taxa.tsv.gz")[0]["trait_records"] == "1"
    assert table("taxon-names.tsv.gz")[0]["printed_name"] == "Aus buss"
    assert table("terms.tsv.gz")[0]["id"] == "PO:0025034"
    # every column of every table is described in the README and in the list the web page shows
    readme = (out / "README.txt").read_text()
    for key, (_title, _text, columns) in dl.TABLES.items():
        assert len(listing["tables"][key]["columns"]) == len(columns)
        assert all(description and name in readme for name, _prop, _kind, description in columns)
    sums = dict(reversed(line.split("  ")) for line in (out / "SHA256SUMS.txt").read_text().splitlines())
    assert set(sums) == paths


def test_attribute_table_gives_each_value_its_most_specific_attribute():
    """Comparable statements share an attribute: glabrous and pubescent are pilosities, a FLOPO
    colour is a colour, and an attribute is its own attribute (Gkoutos et al. 2018)."""
    from tools.atlas_attributes import build

    table = build()
    assert table["of"]["PATO_0000453"] == table["of"]["PATO_0001320"] == "PATO_0000066"  # pilosity
    assert table["of"]["PATO_0000122"] == "PATO_0000122"  # length
    assert table["label"]["PATO_0000066"] == "pilosity"
    assert "PATO_0000452" not in table["of"]  # obsolete
    assert any(k.startswith("FLOPO_") and v == "PATO_0000014" for k, v in table["of"].items())
    assert set(table["of"].values()) == set(table["label"])


def test_release_metadata_states_licence_version_and_every_file(tmp_path):
    import json

    """void.ttl, dataset.jsonld, the table schema and the citation of a data release."""
    import rdflib

    from tools import atlas_metadata as md

    release = tmp_path / "20261201-0900-web"
    (release / "downloads").mkdir(parents=True)
    (release / "web").mkdir()
    (release / "web" / "index.html").write_text("<html><head><title>x</title></head><body></body></html>")
    (release / "release.json").write_text(json.dumps({"stamp": "20261201-0900-web", "triples": 30, "commit": "abc"}))
    graph = "http://phenomebrowser.net/flopo/saudi-flora/graph/ncvc/index"
    (release / "downloads" / "downloads.json").write_text(json.dumps({
        "release": "20261130-1200-data", "sources": {"ncvc": {"label": "NCVC", "title": "Guide (NCVC, 2024)"}},
        "graph_kinds": {"index": "flat records"}, "shared_graphs": {},
        "tables": {"traits": {"title": "Trait records", "description": "", "columns": []}},
        "files": [
            {"path": "rdf/01-ncvc-index.nq.gz", "format": "nquads", "graph": graph, "source": "ncvc", "kind": "index",
             "triples": 30, "bytes": 100, "sha256": "aa"},
            {"path": "tsv/traits-all.tsv.gz", "format": "tsv", "source": "", "table": "traits", "rows": 7,
             "bytes": 50, "sha256": "bb"}]}))
    history = tmp_path / "data-releases.tsv"
    history.write_text("version\tdate\ttriples\tchanges\n20261101-0800\t2026-11-01\t20\tfirst\n")
    assert md.build(release, history)["version"] == "20261130-1200"  # the data version, not the web release

    g = rdflib.Graph().parse(release / "web" / "void.ttl")
    DCAT, VOID = rdflib.Namespace("http://www.w3.org/ns/dcat#"), rdflib.Namespace("http://rdfs.org/ns/void#")
    dataset, version = rdflib.URIRef(md.DATASET), rdflib.URIRef(md.release_iri("20261130-1200"))
    assert (dataset, DCAT.hasCurrentVersion, version) in g
    assert (version, DCAT.previousVersion, rdflib.URIRef(md.release_iri("20261101-0800"))) in g
    assert (version, rdflib.DCTERMS.license, rdflib.URIRef("https://creativecommons.org/licenses/by/4.0/")) in g
    assert g.value(version, VOID.triples).toPython() == 30
    assert g.value(rdflib.URIRef(graph), VOID.dataDump) == rdflib.URIRef(md.BASE + "downloads/rdf/01-ncvc-index.nq.gz")
    assert len(set(g.objects(version, DCAT.distribution))) == 2
    assert g.value(g.value(version, VOID.classPartition), VOID.entities).toPython() == 7

    described = json.loads((release / "web" / "dataset.jsonld").read_text())
    assert described["license"].endswith("/by/4.0/") and described["version"] == "20261130-1200"
    assert '"@type": "Dataset"' in (release / "web" / "index.html").read_text()
    md.build(release, history)  # a second build replaces the block in the page
    assert (release / "web" / "index.html").read_text().count("application/ld+json") == 1
    tables = json.loads((release / "downloads" / "tsv" / "csv-metadata.json").read_text())["tables"]
    names = [c["name"] for c in tables[0]["tableSchema"]["columns"]]
    from tools.atlas_downloads import TRAIT_COLUMNS, header
    assert names == header(TRAIT_COLUMNS)
    assert "CC-BY-4.0" in (release / "downloads" / "CITATION.cff").read_text()
    assert "Rights in them remain with the floras" in (release / "downloads" / "LICENSE.txt").read_text()
    assert json.loads((release / "web" / "versions.json").read_text())["history"][0]["version"] == "20261130-1200"
