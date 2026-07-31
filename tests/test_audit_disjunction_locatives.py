from __future__ import annotations

import sqlite3


def _database(path):
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE text_segment (
          segment_id INTEGER PRIMARY KEY, source TEXT, source_id TEXT,
          source_segment_index INTEGER, taxon TEXT, organ TEXT, language TEXT,
          char_start INTEGER, text TEXT
        );
        CREATE TABLE unresolved_span (
          unresolved_span_id INTEGER PRIMARY KEY, segment_id INTEGER,
          char_start INTEGER, char_end INTEGER, surface_form TEXT, reason TEXT,
          candidate_pato_id TEXT, extractor TEXT
        );
        """
    )
    examples = [
        (1, "Feuilles acuminées au sommet.", "acuminées", "unsupported_alternative_or_transition"),
        (2, "Feuilles aiguës à obtuses à la base.", "obtuses", "unsupported_alternative_or_transition"),
        (3, "Feuilles rouges ou vertes.", "rouges", "explicit_disjunction"),
        (4, "Feuilles glabres à l'état adulte.", "glabres", "unsupported_alternative_or_transition"),
    ]
    for segment_id, text, surface, reason in examples:
        start = text.index(surface)
        connection.execute(
            "INSERT INTO text_segment VALUES (?,?,?,?,?,?,?,?,?)",
            (segment_id, "fdac", f"{segment_id}.xml", 0, "Taxon", "feuilles", "fr", 100, text),
        )
        connection.execute(
            "INSERT INTO unresolved_span VALUES (?,?,?,?,?,?,?,?)",
            (segment_id, segment_id, start, start + len(surface), surface, reason, "PATO_0002228", "test"),
        )
    connection.commit()
    connection.close()


def test_audit_routes_only_anatomical_locatives_and_preserves_offsets(tmp_path):
    from flopo2.verify.audit_disjunction_locatives import audit_sqlite

    database = tmp_path / "audit.sqlite"
    output = tmp_path / "locatives.tsv"
    _database(database)

    report = audit_sqlite(database, output)

    assert report["target_reason_counts"] == {
        "explicit_disjunction": 1,
        "unsupported_alternative_or_transition": 3,
    }
    assert report["locative_context_rows"] == 1
    lines = output.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "acuminées au sommet" in lines[1]
    assert "\tacuminées\tunsupported_alternative_or_transition\tlocative_context\t" in lines[1]
    assert "\t109\t118\t" in lines[1]
