from tools.atlas_checks import compare
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
