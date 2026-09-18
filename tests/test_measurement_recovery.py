import json

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.measurement_recovery import measurement_recovery
from flopo2.terminology.model import RegistryEntry


def test_measurement_recovery_holds_mentions_fixed_and_rejects_habitat_use(tmp_path):
    catalog = OntologyCatalog(
        {
            "PO_leaf": OntologyTerm("PO_leaf", "leaf", "PO", ("leaves",)),
            "PATO_width": OntologyTerm("PATO_width", "width", "PATO"),
        }
    )
    entries = [
        RegistryEntry(
            term_id="wide",
            surface_form="wide",
            normalized_form="wide",
            language="en",
            semantic_role="quality",
            mapping_relation="flopo:unmapped",
            review_status="reviewed",
        )
    ]
    terminology = TerminologyIndex(
        [*entries, *TerminologyIndex._catalog_entries(catalog)], catalog
    )
    corpus = tmp_path / "segments.jsonl"
    rows = [
        {
            "text": "Leaves 1.2 cm wide on a wide plain.",
            "language": "en",
            "organ": "description",
        },
        {
            "text": "Known from high altitude.",
            "language": "en",
            "organ": "description",
        },
    ]
    corpus.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    report = measurement_recovery(corpus, terminology)
    assert report["measurement_grammar_recovered_mentions"] == 1
    assert report["measurement_grammar_recovered_surfaces"] == [("wide", 1)]
    assert report["missing_mentions"] == 2
    assert report["missing_after_measurement_grammar"] == 1
