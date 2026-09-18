from tools.classify_flopo_release import obo_without_imports


def test_controlled_classification_removes_only_obo_import_headers():
    source = (
        "format-version: 1.2\n"
        "import: http://example.org/external.owl\n"
        "ontology: example\n\n"
        "[Term]\n"
        "id: X:1\n"
        "name: retained\n"
    )

    result = obo_without_imports(source)

    assert "import:" not in result
    assert "ontology: example" in result
    assert "[Term]\nid: X:1\nname: retained" in result
