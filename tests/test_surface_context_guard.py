"""Surface/side-restriction guard: one-surface values are not whole-organ values.

Texts follow reviewed rows of scratchpad/flopo-claude-recovery-20260918/surface-audit/
sample-review.tsv (e.g. ``limbe … glabre en dessus, pubescent en dessous``).
"""

from __future__ import annotations

import pytest

from flopo2.extract.baseline import extract_segment_with_unresolved
from flopo2.extract.surface_context import single_side_restriction, surface_guarded


def _values(text: str, organ: str = "feuilles", language: str = "fr") -> set[tuple[str, str]]:
    assertions, _ = extract_segment_with_unresolved({"text": text, "organ": organ, "language": language})
    return {(row["po_id"], row["pato_id"]) for row in assertions}


@pytest.mark.parametrize(
    ("text", "value", "side"),
    [
        ("limbe papyracé, glabre en dessus, pubescent en dessous", "glabre", "upper"),
        ("limbe papyracé, glabre en dessus, pubescent en dessous", "pubescent", "lower"),
        ("Leaf-blades glabrous above, sparsely pubescent beneath", "glabrous", "upper"),
        ("leaves uniformly pubescent above and beneath", "pubescent", ""),
        ("limbe coriace, glabre sur les 2 faces", "glabre", ""),
        ("sépales pubescents sur la face externe", "pubescents", "other"),
        ("limbe coriace, glabre, à bords enroulés", "glabre", ""),
    ],
)
def test_single_side_restriction(text, value, side):
    start = text.index(value)
    assert single_side_restriction(text, start, start + len(value)) == side


def test_guard_applies_to_laminar_bearers_and_surface_families_only():
    text = "limbe papyracé, glabre en dessus, pubescent en dessous"
    start = text.index("glabre")
    assert surface_guarded("PO_0020039", "pilosity", text, start, start + 6)
    assert not surface_guarded("PO_0020039", "shape", text, start, start + 6)
    assert not surface_guarded("PO_0000050", "pilosity", text, start, start + 6)


def test_baseline_withholds_one_surface_pilosity():
    text = "Limbe elliptique, papyracé, glabre en dessus, pubescent en dessous."
    values = _values(text)
    assert ("PO_0020039", "PATO_0000453") not in values
    assert ("PO_0020039", "PATO_0001320") not in values
    control = "Limbe elliptique, papyracé, glabre sur les 2 faces."
    assert ("PO_0020039", "PATO_0000453") in _values(control)


def test_surface_correction_removes_one_surface_value_and_restores_span():
    from flopo2.verify.apply_deltas import apply_line
    from flopo2.verify.surface_restriction_correction import correct_record

    text = "Limbe papyracé, glabre en dessus, pubescent en dessous; nervures 6."
    start = text.index("glabre")
    both_start = text.index("papyracé")
    record = {
        "source": "fdac", "source_id": "1", "source_segment_index": 1, "taxon": "T", "organ": "feuilles",
        "char_start": 0, "char_end": len(text), "text": text, "unresolved_spans": [],
        "source_statements": [
            {"statement_id": "st-1", "start": start, "end": start + 6, "verbatim_text": "glabre"},
            {"statement_id": "st-2", "start": both_start, "end": both_start + 8, "verbatim_text": "papyracé"},
        ],
        "assertions": [
            {"po_id": "PO_0020039", "pato_id": "PATO_0000453", "source_statement_id": "st-1",
             "source_start": start, "source_end": start + 6, "source_text": "glabre",
             "gate": {"status": "accepted"}},
            {"po_id": "PO_0020039", "pato_id": "PATO_0001242", "source_statement_id": "st-2",
             "source_start": both_start, "source_end": both_start + 8, "source_text": "papyracé",
             "gate": {"status": "accepted"}},
        ],
    }
    line, _ = correct_record(record, {"PATO_0000453": "glabrous", "PATO_0001242": "papery"})
    assert [row["pato_id"] for row in line["remove_assertions"]] == ["PATO_0000453"]
    (span,) = line["add_unresolved"]
    assert (span["surface_form"], span["pending_bearer"]) == ("glabre", "upper surface")
    out = apply_line(record, line, "surface")
    assert [row["pato_id"] for row in out["assertions"]] == ["PATO_0001242"]
