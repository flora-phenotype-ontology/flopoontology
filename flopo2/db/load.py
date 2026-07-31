"""Load Phase 7 gated assertions into the local FLOPO trait database."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.owl.annotation_class import (
    annotation_class_digest,
    canonical_signature_json,
    ensure_annotation_class_iri,
)


SCHEMA = Path(__file__).with_name("schema.sql")


def init_db(db_path: Path, schema_path: Path = SCHEMA) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        columns = {row[1] for row in conn.execute("PRAGMA table_info(text_segment)")}
        missing = {"char_start", "char_end", "source_segment_index"} - columns
        if missing:
            # The previous uniqueness constraint omitted taxon and cannot be repaired safely in
            # place: its rows may already conflate evidence from different taxa.  Refuse to append
            # to that database and require a rebuild from the gated JSONL source of truth.
            raise RuntimeError(
                "trait database uses the pre-provenance schema; rebuild it at a fresh path "
                f"(missing columns: {', '.join(sorted(missing))})"
            )
        assertion_columns = {row[1] for row in conn.execute("PRAGMA table_info(trait_assertion)")}
        missing_assertion = {
            "source_statement_id",
            "source_start",
            "source_end",
            "extractor",
            "trait",
            "modifier",
            "cardinality",
            "confidence",
            "frequency_qualifier",
            "epistemic_modality",
            "value_qualifier",
            "degree_qualifier",
            "modality_text",
            "bearer_start",
            "bearer_end",
            "modality_start",
            "modality_end",
            "season_contexts",
            "season_operator",
            "phenotype_class_iri",
            "bearer_context_qualities",
            "negation_scope",
            "developmental_stage_contexts",
            "developmental_stage_operator",
        } - assertion_columns
        if missing_assertion:
            raise RuntimeError(
                "trait database uses the pre-assertion-provenance schema; rebuild it at a fresh "
                f"path (missing columns: {', '.join(sorted(missing_assertion))})"
            )
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "source_statement" not in tables:
            raise RuntimeError(
                "trait database lacks the source_statement provenance table; rebuild it at a "
                "fresh path"
            )
        if "annotation_class" not in tables:
            raise RuntimeError(
                "trait database lacks the annotation_class registry table; rebuild it at a "
                "fresh path"
            )
        unresolved_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(unresolved_span)")
        }
        missing_unresolved = {
            "original_reason",
            "negation_residual_reason",
            "negation_residual_detail",
            "partial_promotion",
            "pending_bearer",
            "promoted_po_ids",
        } - unresolved_columns
        if missing_unresolved:
            raise RuntimeError(
                "trait database uses the pre-residual-provenance schema; rebuild it at a fresh "
                f"path (missing columns: {', '.join(sorted(missing_unresolved))})"
            )


def _register_annotation_class(conn: sqlite3.Connection, assertion: dict) -> str | None:
    """Register and return the stable FAC class IRI for a representable assertion."""

    if str(assertion.get("cardinality", "") or "").strip():
        # Cardinality is retained for review but is not yet compiled into the phenotype class.
        return None
    class_iri = ensure_annotation_class_iri(assertion)
    digest = annotation_class_digest(assertion)
    signature = canonical_signature_json(assertion)
    class_id = class_iri.rsplit("/", 1)[-1]
    conn.execute(
        """
        INSERT OR IGNORE INTO annotation_class(
          phenotype_class_iri, annotation_class_id, expression_sha256,
          canonical_expression_signature
        ) VALUES (?, ?, ?, ?)
        """,
        (class_iri, class_id, digest, signature),
    )
    stored = conn.execute(
        """
        SELECT expression_sha256, canonical_expression_signature
        FROM annotation_class WHERE phenotype_class_iri=?
        """,
        (class_iri,),
    ).fetchone()
    if stored != (digest, signature):
        raise RuntimeError(f"annotation-class identity collision at {class_iri}")
    return class_iri


def _segment_id(conn: sqlite3.Connection, obj: dict) -> int:
    text = obj.get("text", "")
    char_start = obj.get("char_start", 0)
    char_end = obj.get("char_end", len(text))
    source_segment_index = obj.get("source_segment_index", 0)
    conn.execute(
        """
        INSERT OR IGNORE INTO text_segment(
          source, source_id, source_segment_index, taxon, organ, language,
          char_start, char_end, text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            obj.get("source", ""),
            obj.get("source_id", ""),
            source_segment_index,
            obj.get("taxon", ""),
            obj.get("organ", ""),
            obj.get("language", ""),
            char_start,
            char_end,
            text,
        ),
    )
    row = conn.execute(
        """
        SELECT segment_id FROM text_segment
        WHERE source=? AND source_id=? AND source_segment_index=?
        """,
        (
            obj.get("source", ""),
            obj.get("source_id", ""),
            source_segment_index,
        ),
    ).fetchone()
    if row is None:
        raise RuntimeError("failed to create or fetch segment")
    return int(row[0])


def load_jsonl(db_path: Path, jsonl_path: Path) -> dict:
    init_db(db_path)
    segments = 0
    assertions = 0
    unresolved_spans = 0
    source_statements = 0
    source_positions: Counter[tuple[str, str]] = Counter()
    with sqlite3.connect(db_path) as conn, Path(jsonl_path).open(encoding="utf-8") as fh:
        conn.execute("PRAGMA foreign_keys=ON")
        existing = conn.execute("SELECT COUNT(*) FROM text_segment").fetchone()[0]
        if existing:
            raise RuntimeError(
                "trait database is not empty; load into a fresh path to preserve a reproducible "
                "one-artifact-to-one-database provenance contract"
            )
        for line in fh:
            if not line.strip():
                continue
            obj = json.loads(line)
            source_key = (obj.get("source", ""), obj.get("source_id", ""))
            obj.setdefault("source_segment_index", source_positions[source_key])
            source_positions[source_key] += 1
            obj = ensure_source_statements(obj)
            sid = _segment_id(conn, obj)
            segments += 1
            for statement in obj.get("source_statements", []) or []:
                conn.execute(
                    """
                    INSERT INTO source_statement(
                      statement_id, segment_id, char_start, char_end, document_start,
                      document_end, verbatim_text, language, sentence_index
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        statement["statement_id"],
                        sid,
                        statement["start"],
                        statement["end"],
                        statement.get("document_start"),
                        statement.get("document_end"),
                        statement["verbatim_text"],
                        statement.get("language", "") or "",
                        statement.get("sentence_index"),
                    ),
                )
                source_statements += 1
            for mention in obj.get("term_mentions", []) or []:
                cursor = conn.execute(
                    """
                    INSERT OR IGNORE INTO term_mention(
                      segment_id, mention_id, char_start, char_end, surface_form,
                      normalized_form, language, semantic_roles, registry_term_ids,
                      longest_match, overlap_group, match_type, logical_operator,
                      organ_context, component_ids, attribute_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        mention.get("mention_id", ""),
                        mention.get("start", 0),
                        mention.get("end", 0),
                        mention.get("surface_form", ""),
                        mention.get("normalized_form", ""),
                        mention.get("language", ""),
                        json.dumps(mention.get("semantic_roles", []), ensure_ascii=False),
                        json.dumps(mention.get("registry_term_ids", []), ensure_ascii=False),
                        1 if mention.get("longest_match", True) else 0,
                        mention.get("overlap_group", 0),
                        mention.get("match_type", ""),
                        mention.get("logical_operator", ""),
                        mention.get("organ_context", ""),
                        json.dumps(mention.get("component_ids", []), ensure_ascii=False),
                        mention.get("attribute_id", ""),
                    ),
                )
                mention_row = conn.execute(
                    "SELECT term_mention_id FROM term_mention WHERE segment_id=? AND mention_id=?",
                    (sid, mention.get("mention_id", "")),
                ).fetchone()
                if mention_row is not None and cursor.rowcount:
                    for candidate in mention.get("candidates", []) or []:
                        conn.execute(
                            """
                            INSERT INTO term_candidate(
                              term_mention_id, target_id, target_label, target_namespace,
                              score, mapping_relation, review_status, registry_term_ids, evidence
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                mention_row[0],
                                candidate.get("target_id", ""),
                                candidate.get("label", ""),
                                candidate.get("namespace", ""),
                                candidate.get("score", 0.0),
                                candidate.get("mapping_relation", ""),
                                candidate.get("review_status", ""),
                                json.dumps(candidate.get("registry_term_ids", []), ensure_ascii=False),
                                json.dumps(candidate.get("evidence", []), ensure_ascii=False),
                            ),
                        )
            for unresolved in obj.get("unresolved_spans", []) or []:
                conn.execute(
                    """
                    INSERT INTO unresolved_span(
                      segment_id, char_start, char_end, surface_form, reason,
                      candidate_pato_id, original_reason, negation_residual_reason,
                      negation_residual_detail, partial_promotion, pending_bearer,
                      promoted_po_ids, extractor
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        unresolved.get("start", 0),
                        unresolved.get("end", 0),
                        unresolved.get("surface_form", ""),
                        unresolved.get("reason", ""),
                        unresolved.get("candidate_pato_id", "") or "",
                        unresolved.get("original_reason", "") or "",
                        unresolved.get("negation_residual_reason", "") or "",
                        unresolved.get("negation_residual_detail", "") or "",
                        1 if unresolved.get("partial_promotion", False) else 0,
                        unresolved.get("pending_bearer", "") or "",
                        json.dumps(
                            unresolved.get("promoted_po_ids") or [],
                            ensure_ascii=False,
                        ),
                        unresolved.get("extractor", "") or "",
                    ),
                )
                unresolved_spans += 1
            for a in obj.get("assertions", []) or []:
                comp = a.get("composition") or {}
                gate = a.get("gate") or {}
                phenotype_class_iri = _register_annotation_class(conn, a)
                values = {
                    "segment_id": sid,
                    "source_statement_id": a["source_statement_id"],
                    "phenotype_class_iri": phenotype_class_iri,
                    "po_id": a.get("po_id", ""),
                    "pato_id": a.get("pato_id", ""),
                    "negated": 1 if a.get("negated", False) else 0,
                    "negation_scope": a.get("negation_scope", "") or "",
                    "value_low": a.get("value_low"),
                    "value_high": a.get("value_high"),
                    "value_low_inclusive": 1 if a.get("value_low_inclusive", True) else 0,
                    "value_high_inclusive": 1 if a.get("value_high_inclusive", True) else 0,
                    "unit": a.get("unit", "") or "",
                    "value_text": a.get("value_text", "") or "",
                    "trait": a.get("trait", "") or "",
                    "modifier": a.get("modifier", "") or "",
                    "frequency_qualifier": a.get("frequency_qualifier", "unspecified"),
                    "epistemic_modality": a.get("epistemic_modality", "asserted"),
                    "value_qualifier": a.get("value_qualifier", "exact"),
                    "degree_qualifier": a.get("degree_qualifier", "unmodified"),
                    "modality_text": a.get("modality_text", "") or "",
                    "season_contexts": json.dumps(
                        a.get("season_contexts", []), ensure_ascii=False
                    ),
                    "season_operator": a.get("season_operator", "atomic") or "atomic",
                    "developmental_stage_contexts": json.dumps(
                        a.get("developmental_stage_contexts", []), ensure_ascii=False
                    ),
                    "developmental_stage_operator": (
                        a.get("developmental_stage_operator", "atomic") or "atomic"
                    ),
                    "cardinality": str(a.get("cardinality", "") or ""),
                    "confidence": a.get("confidence"),
                    "raw_entity_text": a.get("raw_entity_text", "") or "",
                    "raw_quality_text": a.get("raw_quality_text", "") or "",
                    "bearer_start": a.get("bearer_start"),
                    "bearer_end": a.get("bearer_end"),
                    "modality_start": a.get("modality_start"),
                    "modality_end": a.get("modality_end"),
                    "entity_mention_id": a.get("entity_mention_id", "") or "",
                    "quality_mention_ids": json.dumps(
                        a.get("quality_mention_ids", []), ensure_ascii=False
                    ),
                    "value_operator": a.get("value_operator", "atomic") or "atomic",
                    "value_terms": json.dumps(a.get("value_terms", []), ensure_ascii=False),
                    "bearer_context_qualities": json.dumps(
                        a.get("bearer_context_qualities", []), ensure_ascii=False
                    ),
                    "normalization_status": a.get("normalization_status", "") or "",
                    "mapping_provenance": json.dumps(
                        a.get("mapping_provenance", []), ensure_ascii=False
                    ),
                    "source_text": a.get("source_text", "") or "",
                    "source_start": a.get("source_start"),
                    "source_end": a.get("source_end"),
                    "extractor": a.get("extractor", "") or "",
                    "composition_status": comp.get("status", ""),
                    "composition_confidence": comp.get("confidence"),
                    "composition_reasons": json.dumps(
                        comp.get("reasons", []), ensure_ascii=False
                    ),
                    "gate_status": gate.get("status", ""),
                    "gate_confidence": gate.get("confidence"),
                    "gate_reasons": json.dumps(gate.get("reasons", []), ensure_ascii=False),
                    "po_pato_status": gate.get("po_pato_status", ""),
                    "flopo_iri": gate.get("flopo_iri", ""),
                    "flopo_status": gate.get("flopo_status", ""),
                    "review_priority": gate.get("review_priority", 0),
                    "verifier_status": gate.get("verifier_status", ""),
                    "verifier_reasons": json.dumps(
                        gate.get("verifier_reasons", []), ensure_ascii=False
                    ),
                    "floratraiter_status": gate.get("floratraiter_status", ""),
                    "floratraiter_reasons": json.dumps(
                        gate.get("floratraiter_reasons", []), ensure_ascii=False
                    ),
                    "curation_status": (
                        "accepted" if gate.get("status") == "accepted" else "review"
                    ),
                }
                columns = ", ".join(values)
                placeholders = ", ".join(f":{column}" for column in values)
                conn.execute(
                    f"INSERT INTO trait_assertion({columns}) VALUES ({placeholders})",
                    values,
                )
                assertions += 1
        annotation_classes = conn.execute("SELECT COUNT(*) FROM annotation_class").fetchone()[0]
    return {
        "segments": segments,
        "assertions": assertions,
        "source_statements": source_statements,
        "unresolved_spans": unresolved_spans,
        "annotation_classes": annotation_classes,
        "db": str(db_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Load gated FLOPO assertions into SQLite.")
    ap.add_argument("input", type=Path, help="Phase 7 gated JSONL")
    ap.add_argument("--db", type=Path, default=Path("flopo2.sqlite"))
    args = ap.parse_args()
    print(json.dumps(load_jsonl(args.db, args.input), indent=2))


if __name__ == "__main__":
    main()
