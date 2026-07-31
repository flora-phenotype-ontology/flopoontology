-- Phase 7 curated trait database schema.
-- SQLite-compatible for local development; columns map directly to the planned Postgres schema.

CREATE TABLE IF NOT EXISTS text_segment (
  segment_id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  source_id TEXT NOT NULL,
  source_segment_index INTEGER NOT NULL DEFAULT 0,
  taxon TEXT NOT NULL DEFAULT '',
  organ TEXT NOT NULL DEFAULT '',
  language TEXT NOT NULL DEFAULT '',
  char_start INTEGER NOT NULL DEFAULT 0,
  char_end INTEGER NOT NULL DEFAULT 0,
  text TEXT NOT NULL,
  UNIQUE(source, source_id, source_segment_index)
);

CREATE TABLE IF NOT EXISTS source_statement (
  statement_id TEXT PRIMARY KEY,
  segment_id INTEGER NOT NULL REFERENCES text_segment(segment_id),
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  document_start INTEGER,
  document_end INTEGER,
  verbatim_text TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT '',
  sentence_index INTEGER,
  UNIQUE(segment_id, char_start, char_end, verbatim_text)
);

CREATE TABLE IF NOT EXISTS annotation_class (
  phenotype_class_iri TEXT PRIMARY KEY,
  annotation_class_id TEXT NOT NULL UNIQUE,
  expression_sha256 TEXT NOT NULL UNIQUE,
  canonical_expression_signature TEXT NOT NULL,
  CHECK(
    phenotype_class_iri GLOB
    'https://w3id.org/flopo/annotation-class/FAC_[0-9a-f]*'
  )
);

CREATE TABLE IF NOT EXISTS trait_assertion (
  assertion_id INTEGER PRIMARY KEY AUTOINCREMENT,
  segment_id INTEGER NOT NULL REFERENCES text_segment(segment_id),
  source_statement_id TEXT NOT NULL REFERENCES source_statement(statement_id),
  phenotype_class_iri TEXT REFERENCES annotation_class(phenotype_class_iri),
  po_id TEXT NOT NULL,
  pato_id TEXT NOT NULL,
  negated INTEGER NOT NULL DEFAULT 0,
  negation_scope TEXT NOT NULL DEFAULT '',
  value_low REAL,
  value_high REAL,
  value_low_inclusive INTEGER NOT NULL DEFAULT 1,
  value_high_inclusive INTEGER NOT NULL DEFAULT 1,
  unit TEXT NOT NULL DEFAULT '',
  value_text TEXT NOT NULL DEFAULT '',
  trait TEXT NOT NULL DEFAULT '',
  modifier TEXT NOT NULL DEFAULT '',
  frequency_qualifier TEXT NOT NULL DEFAULT 'unspecified',
  epistemic_modality TEXT NOT NULL DEFAULT 'asserted',
  value_qualifier TEXT NOT NULL DEFAULT 'exact',
  degree_qualifier TEXT NOT NULL DEFAULT 'unmodified',
  modality_text TEXT NOT NULL DEFAULT '',
  season_contexts TEXT NOT NULL DEFAULT '[]',
  season_operator TEXT NOT NULL DEFAULT 'atomic',
  developmental_stage_contexts TEXT NOT NULL DEFAULT '[]',
  developmental_stage_operator TEXT NOT NULL DEFAULT 'atomic',
  cardinality TEXT NOT NULL DEFAULT '',
  confidence REAL,
  raw_entity_text TEXT NOT NULL DEFAULT '',
  raw_quality_text TEXT NOT NULL DEFAULT '',
  bearer_start INTEGER,
  bearer_end INTEGER,
  modality_start INTEGER,
  modality_end INTEGER,
  entity_mention_id TEXT NOT NULL DEFAULT '',
  quality_mention_ids TEXT NOT NULL DEFAULT '[]',
  value_operator TEXT NOT NULL DEFAULT 'atomic',
  value_terms TEXT NOT NULL DEFAULT '[]',
  bearer_context_qualities TEXT NOT NULL DEFAULT '[]',
  normalization_status TEXT NOT NULL DEFAULT '',
  mapping_provenance TEXT NOT NULL DEFAULT '[]',
  source_text TEXT NOT NULL DEFAULT '',
  source_start INTEGER,
  source_end INTEGER,
  extractor TEXT NOT NULL DEFAULT '',
  composition_status TEXT NOT NULL DEFAULT '',
  composition_confidence REAL,
  composition_reasons TEXT NOT NULL DEFAULT '[]',
  gate_status TEXT NOT NULL DEFAULT '',
  gate_confidence REAL,
  gate_reasons TEXT NOT NULL DEFAULT '[]',
  po_pato_status TEXT NOT NULL DEFAULT '',
  flopo_iri TEXT NOT NULL DEFAULT '',
  flopo_status TEXT NOT NULL DEFAULT '',
  review_priority INTEGER NOT NULL DEFAULT 0,
  verifier_status TEXT NOT NULL DEFAULT '',
  verifier_reasons TEXT NOT NULL DEFAULT '[]',
  floratraiter_status TEXT NOT NULL DEFAULT '',
  floratraiter_reasons TEXT NOT NULL DEFAULT '[]',
  curation_status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS term_mention (
  term_mention_id INTEGER PRIMARY KEY AUTOINCREMENT,
  segment_id INTEGER NOT NULL REFERENCES text_segment(segment_id),
  mention_id TEXT NOT NULL,
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  surface_form TEXT NOT NULL,
  normalized_form TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT '',
  semantic_roles TEXT NOT NULL DEFAULT '[]',
  registry_term_ids TEXT NOT NULL DEFAULT '[]',
  longest_match INTEGER NOT NULL DEFAULT 1,
  overlap_group INTEGER NOT NULL DEFAULT 0,
  match_type TEXT NOT NULL DEFAULT '',
  organ_context TEXT NOT NULL DEFAULT '',
  logical_operator TEXT NOT NULL DEFAULT '',
  component_ids TEXT NOT NULL DEFAULT '[]',
  attribute_id TEXT NOT NULL DEFAULT '',
  UNIQUE(segment_id, mention_id)
);

CREATE TABLE IF NOT EXISTS unresolved_span (
  unresolved_span_id INTEGER PRIMARY KEY AUTOINCREMENT,
  segment_id INTEGER NOT NULL REFERENCES text_segment(segment_id),
  char_start INTEGER NOT NULL,
  char_end INTEGER NOT NULL,
  surface_form TEXT NOT NULL,
  reason TEXT NOT NULL,
  candidate_pato_id TEXT NOT NULL DEFAULT '',
  original_reason TEXT NOT NULL DEFAULT '',
  negation_residual_reason TEXT NOT NULL DEFAULT '',
  negation_residual_detail TEXT NOT NULL DEFAULT '',
  partial_promotion INTEGER NOT NULL DEFAULT 0,
  pending_bearer TEXT NOT NULL DEFAULT '',
  promoted_po_ids TEXT NOT NULL DEFAULT '[]',
  extractor TEXT NOT NULL,
  UNIQUE(segment_id, char_start, char_end, reason, candidate_pato_id, extractor)
);

CREATE TABLE IF NOT EXISTS term_candidate (
  term_candidate_id INTEGER PRIMARY KEY AUTOINCREMENT,
  term_mention_id INTEGER NOT NULL REFERENCES term_mention(term_mention_id),
  target_id TEXT NOT NULL,
  target_label TEXT NOT NULL DEFAULT '',
  target_namespace TEXT NOT NULL DEFAULT '',
  score REAL NOT NULL DEFAULT 0,
  mapping_relation TEXT NOT NULL DEFAULT '',
  review_status TEXT NOT NULL DEFAULT '',
  registry_term_ids TEXT NOT NULL DEFAULT '[]',
  evidence TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_trait_assertion_pair
ON trait_assertion(po_id, pato_id, value_operator, value_terms);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_phenotype_class
ON trait_assertion(phenotype_class_iri);
CREATE INDEX IF NOT EXISTS idx_source_statement_segment ON source_statement(segment_id);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_source_statement
ON trait_assertion(source_statement_id);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_modality
ON trait_assertion(frequency_qualifier, epistemic_modality);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_gate ON trait_assertion(gate_status);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_flopo ON trait_assertion(flopo_status);
CREATE INDEX IF NOT EXISTS idx_trait_assertion_review_priority ON trait_assertion(review_priority DESC);
CREATE INDEX IF NOT EXISTS idx_text_segment_taxon ON text_segment(taxon);
CREATE INDEX IF NOT EXISTS idx_term_mention_segment ON term_mention(segment_id);
CREATE INDEX IF NOT EXISTS idx_term_candidate_target ON term_candidate(target_id);
CREATE INDEX IF NOT EXISTS idx_unresolved_span_segment ON unresolved_span(segment_id);
CREATE INDEX IF NOT EXISTS idx_unresolved_span_reason ON unresolved_span(reason);

CREATE VIEW IF NOT EXISTS v_accepted_assertions AS
SELECT ta.*, ts.source, ts.source_id, ts.taxon, ts.organ, ts.language, ts.text
FROM trait_assertion ta
JOIN text_segment ts USING(segment_id)
WHERE ta.gate_status = 'accepted';

CREATE VIEW IF NOT EXISTS v_review_queue AS
SELECT ta.*, ts.source, ts.source_id, ts.taxon, ts.organ, ts.language, ts.text
FROM trait_assertion ta
JOIN text_segment ts USING(segment_id)
WHERE ta.gate_status IN ('review', 'blocked') OR ta.curation_status = 'review';

CREATE VIEW IF NOT EXISTS v_review_queue_prioritized AS
SELECT *
FROM v_review_queue
ORDER BY review_priority DESC, assertion_id ASC;

CREATE VIEW IF NOT EXISTS v_new_class_candidates AS
SELECT ta.*, ts.source, ts.source_id, ts.taxon, ts.organ, ts.language, ts.text
FROM trait_assertion ta
JOIN text_segment ts USING(segment_id)
WHERE ta.flopo_status = 'new_class_candidate' AND ta.gate_status IN ('accepted', 'review');

CREATE VIEW IF NOT EXISTS mv_species_trait_matrix AS
SELECT ts.taxon, ta.phenotype_class_iri,
       COUNT(*) AS assertion_count
FROM trait_assertion ta
JOIN text_segment ts USING(segment_id)
WHERE ta.gate_status = 'accepted'
GROUP BY ts.taxon, ta.phenotype_class_iri;

CREATE VIEW IF NOT EXISTS mv_trait_species AS
SELECT ta.phenotype_class_iri, ts.taxon,
       COUNT(*) AS assertion_count
FROM trait_assertion ta
JOIN text_segment ts USING(segment_id)
WHERE ta.gate_status = 'accepted'
GROUP BY ta.phenotype_class_iri, ts.taxon;
