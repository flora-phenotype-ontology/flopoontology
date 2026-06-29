"""Fast regression guard for the OBO Foundry fixes in ontology/flopo.owl.

Uses a text scan (not a full 27 MB rdflib parse) so the suite stays fast. Skips if the release
file is absent. Guards the ERROR-level dashboard checks we fixed so a rebuild can't silently
regress them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

OWL = Path("ontology/flopo.owl")
pytestmark = pytest.mark.skipif(not OWL.exists(), reason="flopo.owl not present")


@pytest.fixture(scope="module")
def head() -> str:
    # rdflib's serializer does not guarantee the ontology header is first, so scan the whole file.
    return OWL.read_text(encoding="utf-8", errors="replace")


def test_license_present(head):
    assert "creativecommons.org/publicdomain/zero/1.0" in head


def test_version_iri_present(head):
    assert "flopo/releases/" in head and "versionIRI" in head


def test_title_and_description_present(head):
    assert "Flora Phenotype Ontology" in head
    assert "digitized Floras" in head


def test_root_term_annotation_present(head):
    assert "IAO_0000700" in head  # has_ontology_root_term (GitHub #11)


def test_no_malformed_deprecated():
    # Every owl:deprecated must be the boolean true literal; no empty/lang-tagged variants.
    text = OWL.read_text(encoding="utf-8", errors="replace")
    # crude but effective: there must be no empty deprecated element
    assert "<owl:deprecated></owl:deprecated>" not in text
    assert 'owl:deprecated xml:lang' not in text


def test_definitions_present():
    # At least the bulk of textual definitions were added.
    text = OWL.read_text(encoding="utf-8", errors="replace")
    assert text.count("IAO_0000115") > 20000
