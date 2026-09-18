import csv
import json
from pathlib import Path


PATO_OBO = """format-version: 1.2

[Term]
id: PATO:0000414
name: unbranched
is_a: PATO:0002009 ! branchiness

[Term]
id: PATO:0001287
name: red brown
synonym: "reddish-brown" EXACT []
is_a: PATO:0000952 ! brown

[Term]
id: PATO:0001936
name: obovate
is_a: PATO:0001891 ! ovate

[Term]
id: PATO:0104032
name: coriaceous
synonym: "leathery" EXACT []
is_a: PATO:0000150 ! texture
"""


FORMS = """form\tcount\tfamily\tsubtype\taction\tn_parts\tsep\tlangs\tnorm_pato\twhole_pato_label\tcomp_buckets\tnote
un branched\t2\tF3_ocr_rejoin\twhole_token_single_word\tqueue_curation\t2\thyphen\ten:2\tPATO_0000414\t\tshape\treviewed
coriace ous\t2\tF3_ocr_rejoin\twhole_token_single_word\tqueue_curation\t2\thyphen\ten:2\tPATO_0104032\t\ttexture\treviewed
red dish brown\t1\tF3_ocr_rejoin\tinternal_fragment_split\tqueue_curation\t3\tmulti_dash\ten:1\t\t\tcolor\treviewed
ob ovate\t1\tF3_ocr_rejoin\twhole_token_single_word\tqueue_curation\t2\thyphen\ten:1\tPATO_0001936\t\tshape\treviewed
red brown\t4\tF1_atomic_pato\tatomic_colour\tpromote_atomic_guarded\t2\thyphen\ten:4\tPATO_0001287\tred brown\tcolor\tnot OCR
"""


def _span(text: str, surface: str, pato_id: str) -> dict:
    start = text.index(surface)
    return {
        "start": start,
        "end": start + len(surface),
        "surface_form": surface,
        "reason": "hyphenated_or_slash_compound",
        "candidate_pato_id": pato_id,
        "extractor": "deterministic_baseline",
    }


def _record(text: str, organ: str, spans: list[dict]) -> dict:
    return {
        "source": "test-flora",
        "source_id": "T1",
        "source_segment_index": 0,
        "taxon": "Testa plantus",
        "organ": organ,
        "language": "en",
        "text": text,
        "assertions": [],
        "unresolved_spans": spans,
    }


def _files(tmp_path: Path) -> tuple[Path, Path, Path]:
    pato = tmp_path / "pato.obo"
    pato.write_text(PATO_OBO, encoding="utf-8")
    forms = tmp_path / "forms.tsv"
    forms.write_text(FORMS, encoding="utf-8")
    po = tmp_path / "po.tsv"
    po.write_text(
        "id\tlabel\tsynonyms\n"
        "PO_0009047\tstem\tstems\n"
        "PO_0020049\tcompound leaf\tleaflet|leaflets\n"
        "PO_0004518\tbark\tbark\n"
        "PO_0009032\tpetal\tpetals\n",
        encoding="utf-8",
    )
    return pato, forms, po


def test_compact_lexicon_uses_labels_and_exact_synonyms(tmp_path):
    from flopo2.verify.recover_ocr_normalizations import exact_pato_compact_lexicon

    pato, _forms, _po = _files(tmp_path)
    lexicon = exact_pato_compact_lexicon(pato)

    assert lexicon["coriaceous"].pato_id == "PATO_0104032"
    assert lexicon["reddishbrown"].pato_id == "PATO_0001287"


def test_recovers_standalone_unbranched_but_not_disjunction(tmp_path):
    from flopo2.verify.classify_unresolved import load_hyphen_forms
    from flopo2.verify.recover_exact_pato_compounds import BearerResolver
    from flopo2.verify.recover_ocr_normalizations import (
        exact_pato_compact_lexicon,
        recover_record,
    )

    pato, forms, po = _files(tmp_path)
    reviewed = load_hyphen_forms(forms)
    lexicon = exact_pato_compact_lexicon(pato)
    bearers = BearerResolver(po)

    text = "Stem of vertical shoot slender, un-branched."
    record = _record(text, "stems", [_span(text, "branched", "PATO_0000402")])
    recovered, audit, outcomes = recover_record(record, reviewed, lexicon, bearers)
    assert [row["pato_id"] for row in recovered["assertions"]] == ["PATO_0000414"]
    assert recovered["assertions"][0]["raw_quality_text"] == "un-branched"
    assert recovered["unresolved_spans"] == []
    assert audit[0]["disposition"] == "promoted"
    assert outcomes["resolved_evidence_spans"] == 1

    text = "Stems sparsely branched or un-branched."
    span = _span(text, "branched", "PATO_0000402")
    span["start"] = text.rindex("branched")
    span["end"] = span["start"] + len("branched")
    record = _record(text, "stems", [span])
    recovered, audit, outcomes = recover_record(record, reviewed, lexicon, bearers)
    assert recovered["assertions"] == []
    assert len(recovered["unresolved_spans"]) == 1
    assert audit[0]["reason"] == "logical_compound_context"
    assert outcomes["retained:logical_compound_context"] == 1


def test_recovers_coriaceous_despite_unrelated_later_or(tmp_path):
    from flopo2.verify.classify_unresolved import load_hyphen_forms
    from flopo2.verify.recover_exact_pato_compounds import BearerResolver
    from flopo2.verify.recover_ocr_normalizations import (
        exact_pato_compact_lexicon,
        recover_record,
    )

    pato, forms, po = _files(tmp_path)
    text = "Leaflets dark green above, coriace- ous, lanceolate or ovate."
    record = _record(text, "leaflets", [_span(text, "coriace", "PATO_0104032")])
    recovered, audit, _outcomes = recover_record(
        record,
        load_hyphen_forms(forms),
        exact_pato_compact_lexicon(pato),
        BearerResolver(po),
    )

    assert recovered["assertions"][0]["pato_id"] == "PATO_0104032"
    assert recovered["assertions"][0]["po_id"] == "PO_0020049"
    assert audit[0]["source_token"] == "coriace- ous"


def test_retains_repaired_whole_term_inside_range(tmp_path):
    from flopo2.verify.classify_unresolved import load_hyphen_forms
    from flopo2.verify.recover_exact_pato_compounds import BearerResolver
    from flopo2.verify.recover_ocr_normalizations import (
        exact_pato_compact_lexicon,
        recover_record,
    )

    pato, forms, po = _files(tmp_path)
    text = "Petals oval to ob-ovate to oblanceolate."
    record = _record(text, "petals", [_span(text, "ovate", "PATO_0001891")])
    recovered, audit, _outcomes = recover_record(
        record,
        load_hyphen_forms(forms),
        exact_pato_compact_lexicon(pato),
        BearerResolver(po),
    )

    assert recovered["assertions"] == []
    assert audit[0]["pato_id"] == "PATO_0001936"
    assert audit[0]["reason"] == "logical_compound_context"


def test_file_run_is_non_overwriting_and_audited(tmp_path):
    from flopo2.verify.recover_ocr_normalizations import recover_file

    pato, forms, po = _files(tmp_path)
    text = "Stem of vertical shoot slender, un-branched."
    record = _record(text, "stems", [_span(text, "branched", "PATO_0000402")])
    source = tmp_path / "input.jsonl"
    source.write_text(json.dumps(record) + "\n", encoding="utf-8")
    output = tmp_path / "output.jsonl"
    audit = tmp_path / "audit.tsv"

    report = recover_file(
        source,
        output,
        classified_forms=forms,
        pato_obo=pato,
        po_lexicon=po,
        audit_tsv=audit,
    )

    assert json.loads(source.read_text())["assertions"] == []
    assert report["audited_occurrences"] == 1
    assert report["outcomes"]["promoted:PATO_0000414"] == 1
    with audit.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0]["disposition"] == "promoted"
