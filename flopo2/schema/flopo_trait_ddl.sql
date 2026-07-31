-- # Class: TraitExtraction Description: The set of trait assertions extracted from a single text segment (one organ block of one taxon). Carries the provenance needed to trace every assertion back to its source.
--     * Slot: id
--     * Slot: annotation_extension_iri Description: IRI of the annotation-extension ontology that defines the phenotype_class_iri targets used in this materialized record.
--     * Slot: source_segment_index Description: Zero-based document-order occurrence within one source file. This distinguishes repeated taxon/organ/text blocks whose local character offsets are otherwise identical.
--     * Slot: taxon_name Description: Verbatim taxon name string from the source treatment.
--     * Slot: organ_hint Description: The FlorML char-class / subheading the segment came from (anatomical prior).
-- # Class: SourceStatement Description: A verbatim flora statement retained as evidence. Its identifier includes document and segment identity as well as offsets and text, so identical wording in different treatments remains distinct evidence.
--     * Slot: statement_id Description: Stable source-scoped identifier assigned by the provenance normalizer.
--     * Slot: verbatim_text Description: Exact source text selected by start and end.
--     * Slot: start Description: Zero-based inclusive offset in the source segment.
--     * Slot: end Description: Zero-based exclusive offset in the source segment.
--     * Slot: document_start Description: Zero-based inclusive offset in the source document, when available.
--     * Slot: document_end Description: Zero-based exclusive offset in the source document, when available.
--     * Slot: language Description: BCP 47 language code for the retained statement.
--     * Slot: sentence_index Description: Zero-based sentence or statement occurrence within the source segment, if known.
--     * Slot: TraitExtraction_id Description: Autocreated FK slot
-- # Class: UnresolvedTraitSpan Description: A verbatim candidate trait span withheld from assertion promotion because its negation, composition, bearer, modifier, or ontology interpretation is unresolved.
--     * Slot: id
--     * Slot: start Description: Zero-based inclusive character offset in the source segment.
--     * Slot: end Description: Zero-based exclusive character offset in the source segment.
--     * Slot: surface_form Description: Exact source text selected by start and end.
--     * Slot: reason Description: Stable machine-readable reason the candidate was withheld.
--     * Slot: candidate_pato_id Description: PATO identifier suggested by the lexical cue, if any.
--     * Slot: original_reason Description: Stable unresolved reason retained before a context-specific recovery pass.
--     * Slot: negation_residual_reason Description: Machine-readable reason a negated candidate remains unresolved.
--     * Slot: negation_residual_detail Description: Human-readable audit detail explaining the negation residual disposition.
--     * Slot: partial_promotion Description: True when part of this source span was promoted to one or more assertions while the retained residual still needs normalization or ontology curation.
--     * Slot: pending_bearer Description: Bearer phrase still awaiting PO or reviewed FLOPO-local anatomy grounding.
--     * Slot: extractor Description: Extraction implementation that produced this unresolved record.
--     * Slot: TraitExtraction_id Description: Autocreated FK slot
-- # Class: TraitAssertion Description: One grounded entity-quality statement: an anatomical entity (PO) bears a quality (PATO), optionally with a quantitative phenotype value, bearer context quality, modality, season, or negation, justified by a retained source statement. In flora data this is normally a source-scoped universal or qualified TBox claim, not an observation or measurement event.
--     * Slot: id
--     * Slot: phenotype_class_iri Description: Authoritative semantic annotation target: the stable IRI of the equivalent OWL class expression in the FLOPO annotation extension. It is outside the FLOPO term namespace, is generated deterministically after extraction, and is required in materialized annotation datasets.
--     * Slot: anatomical_entity Description: The plant anatomical structure the quality inheres in: normally a Plant Ontology class, or a reviewed FLOPO-local extension of the PO hierarchy when PO lacks the bearer.
--     * Slot: quality Description: The phenotypic quality or attribute (PATO).
--     * Slot: trait Description: Optional pre-composed plant trait this corresponds to (Trait Ontology).
--     * Slot: raw_entity_text Description: Verbatim or minimally normalized entity expression emitted by the extractor.
--     * Slot: raw_quality_text Description: Verbatim or minimally normalized quality/value expression emitted by the extractor.
--     * Slot: bearer_start Description: Zero-based inclusive offset of the verbatim bearer mention raw_entity_text in the source segment. Provenance only and never part of a FAC / logical signature.
--     * Slot: bearer_end Description: Zero-based exclusive offset of the verbatim bearer mention raw_entity_text in the source segment. Paired with bearer_start.
--     * Slot: entity_mention_id Description: Identifier of the terminology mention supporting anatomical_entity.
--     * Slot: value_text Description: Categorical/free-text value of the trait when not numeric (e.g. "ovate").
--     * Slot: value_operator Description: Derived extraction/indexing field used to construct and verify phenotype_class_iri. one_of preserves textual alternatives and must never be converted to conjunctive is_a axioms; this field is not the authoritative semantic annotation target.
--     * Slot: developmental_stage_operator Description: Logical relationship among multiple developmental-stage contexts. one_of is compiled as an anonymous OWL union in the FAC definition and never minted in FLOPO proper.
--     * Slot: value_low Description: Lower bound of a quantitative phenotype range (e.g. 3 in "3-7 cm").
--     * Slot: value_high Description: Upper bound of a quantitative phenotype range (e.g. 7 in "3-7 cm").
--     * Slot: value_low_inclusive Description: Whether value_low is an inclusive bound (xsd:minInclusive) or strict (xsd:minExclusive).
--     * Slot: value_high_inclusive Description: Whether value_high is an inclusive bound (xsd:maxInclusive) or strict (xsd:maxExclusive).
--     * Slot: unit Description: Unit for the quantitative phenotype value (Units of Measurement Ontology).
--     * Slot: modifier Description: Deprecated combined hedge field retained for wire compatibility. New data must populate the orthogonal frequency, epistemic, value, and degree qualifier fields.
--     * Slot: frequency_qualifier Description: Frequency force of the flora statement; unspecified preserves an absent cue.
--     * Slot: epistemic_modality Description: Epistemic force with which the source presents the statement.
--     * Slot: value_qualifier Description: Exactness or approximation of a categorical or numerical value.
--     * Slot: degree_qualifier Description: Degree cue kept separate from frequency and epistemic modality.
--     * Slot: modality_text Description: Exact lexical cue or phrase (for example "usually" or "possibly").
--     * Slot: modality_start Description: Zero-based inclusive offset of the verbatim modality cue modality_text in the source segment, when a cue is present. Provenance only and never part of a FAC / logical signature.
--     * Slot: modality_end Description: Zero-based exclusive offset of the verbatim modality cue modality_text in the source segment. Paired with modality_start.
--     * Slot: season_operator Description: Logical relationship among multiple seasonal contexts. one_of is represented as an anonymous union in the annotation-extension class definition and never minted as a FLOPO vocabulary class.
--     * Slot: negated Description: True if the source makes an explicitly scoped negative phenotype assertion.
--     * Slot: negation_scope Description: OWL scope of an explicit negation. quality asserts an existing bearer that does not satisfy the quality expression; absence asserts that no part satisfying the complete bearer-plus-quality expression exists. Required whenever negated is true and omitted otherwise.
--     * Slot: cardinality Description: Count when the trait is a number of parts (e.g. "stamens 6"). Free text to allow ranges.
--     * Slot: source_text Description: The exact span of the source segment that justifies this assertion (provenance / anti-hallucination anchor). MUST be copied verbatim from the input.
--     * Slot: source_statement_id Description: Identifier of the retained SourceStatement supporting this formal assertion. It is assigned deterministically before persistence when an older extractor omits it.
--     * Slot: source_start Description: Zero-based inclusive offset of source_text in its source segment.
--     * Slot: source_end Description: Zero-based exclusive offset of source_text in its source segment.
--     * Slot: extractor Description: Extraction implementation that produced the assertion (e.g. openrouter or deterministic_baseline).
--     * Slot: confidence Description: Model self-reported confidence in [0,1]; refined later by self-consistency voting.
--     * Slot: normalization_status Description: How the entity/quality normalization was obtained or why it remains unresolved.
--     * Slot: TraitExtraction_id Description: Autocreated FK slot
-- # Class: SeasonContext Description: A source-retained seasonal qualification that is compiled into the OWL phenotype class description. Named seasons may use ENVO or FLOPO annotation vocabulary terms; calendar intervals use month bounds and remain geographically scoped.
--     * Slot: id
--     * Slot: season_term Description: CURIE of a named season, for example ENVO:03000129 or FLOPOANN:wet_season.
--     * Slot: season_text Description: Exact seasonal phrase copied from the source statement.
--     * Slot: start Description: Inclusive offset of season_text in the source segment, when available.
--     * Slot: end Description: Exclusive offset of season_text in the source segment, when available.
--     * Slot: start_month Description: Calendar start month in the inclusive range 1 through 12.
--     * Slot: end_month Description: Calendar end month in the inclusive range 1 through 12.
--     * Slot: hemisphere Description: Hemisphere context if explicitly established; never inferred from a season word alone.
--     * Slot: geographic_context Description: Geographic entity CURIE or source-retained region label qualifying the season.
--     * Slot: temporal_relation Description: Relation used when compiling the seasonal class restriction.
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
-- # Class: DevelopmentalStageContext Description: A source-retained PO developmental or life-cycle stage that temporally scopes a phenotype class. It is distinct from a PATO age/maturity quality of the anatomical bearer and from a specimen-preparation state such as "when dry".
--     * Slot: id
--     * Slot: stage_term Description: PO (or reviewed FLOPO-local PO extension) class for the developmental stage.
--     * Slot: stage_text Description: Exact developmental-stage phrase copied from the source statement.
--     * Slot: start Description: Inclusive offset of stage_text in the source segment, when available.
--     * Slot: end Description: Exclusive offset of stage_text in the source segment, when available.
--     * Slot: temporal_relation Description: Relation used when compiling the stage restriction on the phenotype.
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
-- # Class: TermMention Description: A source-text span matched to prior botanical terminology before extraction.
--     * Slot: mention_id Description: Segment-local stable identifier used to link an assertion to this mention.
--     * Slot: start Description: Zero-based inclusive character offset of the mention in the source segment.
--     * Slot: end Description: Zero-based exclusive character offset of the mention in the source segment.
--     * Slot: surface_form Description: Verbatim text covered by the mention span.
--     * Slot: normalized_form Description: Case-, accent-, and punctuation-normalized form used for lookup.
--     * Slot: language Description: BCP 47 language code inherited from the source segment or glossary.
--     * Slot: longest_match Description: True when no longer overlapping terminology match contains this span.
--     * Slot: overlap_group Description: Segment-local number shared by overlapping mention alternatives.
--     * Slot: match_type Description: Lookup method, for example exact, inflection, or retrieved.
--     * Slot: organ_context Description: Organ heading used as a soft ranking prior for this mention.
--     * Slot: logical_operator Description: Logical relationship among component_ids when this is a compound expression.
--     * Slot: attribute_id Description: PATO attribute used when the mention denotes a categorical value expression.
--     * Slot: TraitExtraction_id Description: Autocreated FK slot
-- # Class: TermCandidate Description: A constrained ontology normalization candidate for a botanical source span.
--     * Slot: id
--     * Slot: target_id Description: CURIE of the proposed PO, PATO, or FLOPO normalization target.
--     * Slot: label Description: Preferred label of the target at registry build time.
--     * Slot: namespace Description: Target ontology namespace, restricted operationally to PO, PATO, or FLOPO.
--     * Slot: score Description: Reproducible hybrid retrieval score in the closed interval [0,1].
--     * Slot: mapping_relation Description: SKOS or FLOPO relation asserted or proposed between source term and target.
--     * Slot: review_status Description: Curation state; only a human workflow may assign reviewed status.
--     * Slot: TermMention_mention_id Description: Autocreated FK slot
-- # Class: UnresolvedTraitSpan_promoted_po_ids
--     * Slot: UnresolvedTraitSpan_id Description: Autocreated FK slot
--     * Slot: promoted_po_ids Description: PO identifiers already promoted from a partially resolved source span.
-- # Class: TraitAssertion_quality_mention_ids
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
--     * Slot: quality_mention_ids Description: Identifiers of terminology mentions supporting the quality or its values.
-- # Class: TraitAssertion_value_terms
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
--     * Slot: value_terms Description: Grounded PATO or FLOPO identifiers for atomic, conjunctive, or alternative values.
-- # Class: TraitAssertion_bearer_context_qualities
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
--     * Slot: bearer_context_qualities Description: Additional PATO qualities that inhere in the same anatomical bearer and form part of the OWL phenotype class description, for example young or mature. These are conjunctive bearer qualities, not developmental-stage process classes or assertion modalities.
-- # Class: TraitAssertion_mapping_provenance
--     * Slot: TraitAssertion_id Description: Autocreated FK slot
--     * Slot: mapping_provenance Description: Stable registry term identifiers or retrieval methods supporting normalization.
-- # Class: TermMention_semantic_roles
--     * Slot: TermMention_mention_id Description: Autocreated FK slot
--     * Slot: semantic_roles Description: Candidate botanical roles such as entity, attribute, or value.
-- # Class: TermMention_registry_term_ids
--     * Slot: TermMention_mention_id Description: Autocreated FK slot
--     * Slot: registry_term_ids Description: Stable BTERM records whose forms match this span.
-- # Class: TermMention_component_ids
--     * Slot: TermMention_mention_id Description: Autocreated FK slot
--     * Slot: component_ids Description: PATO or FLOPO values forming a reviewed conjunction or disjunction.
-- # Class: TermCandidate_registry_term_ids
--     * Slot: TermCandidate_id Description: Autocreated FK slot
--     * Slot: registry_term_ids Description: Stable BTERM records supporting this candidate.
-- # Class: TermCandidate_evidence
--     * Slot: TermCandidate_id Description: Autocreated FK slot
--     * Slot: evidence Description: Retrieval, synonym-scope, or curation evidence supporting the candidate.

CREATE TABLE "TraitExtraction" (
	id INTEGER NOT NULL,
	annotation_extension_iri TEXT,
	source_segment_index INTEGER,
	taxon_name TEXT,
	organ_hint TEXT,
	PRIMARY KEY (id)
);
CREATE INDEX "ix_TraitExtraction_id" ON "TraitExtraction" (id);

CREATE TABLE "SourceStatement" (
	statement_id TEXT NOT NULL,
	verbatim_text TEXT NOT NULL,
	start INTEGER NOT NULL,
	"end" INTEGER NOT NULL,
	document_start INTEGER,
	document_end INTEGER,
	language TEXT,
	sentence_index INTEGER,
	"TraitExtraction_id" INTEGER,
	PRIMARY KEY (statement_id),
	FOREIGN KEY("TraitExtraction_id") REFERENCES "TraitExtraction" (id)
);
CREATE INDEX "ix_SourceStatement_statement_id" ON "SourceStatement" (statement_id);

CREATE TABLE "UnresolvedTraitSpan" (
	id INTEGER NOT NULL,
	start INTEGER NOT NULL,
	"end" INTEGER NOT NULL,
	surface_form TEXT NOT NULL,
	reason TEXT NOT NULL,
	candidate_pato_id TEXT,
	original_reason TEXT,
	negation_residual_reason TEXT,
	negation_residual_detail TEXT,
	partial_promotion BOOLEAN,
	pending_bearer TEXT,
	extractor TEXT NOT NULL,
	"TraitExtraction_id" INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY("TraitExtraction_id") REFERENCES "TraitExtraction" (id)
);
CREATE INDEX "ix_UnresolvedTraitSpan_id" ON "UnresolvedTraitSpan" (id);

CREATE TABLE "TraitAssertion" (
	id INTEGER NOT NULL,
	phenotype_class_iri TEXT,
	anatomical_entity TEXT NOT NULL,
	quality TEXT NOT NULL,
	trait TEXT,
	raw_entity_text TEXT,
	raw_quality_text TEXT,
	bearer_start INTEGER,
	bearer_end INTEGER,
	entity_mention_id TEXT,
	value_text TEXT,
	value_operator VARCHAR(6),
	developmental_stage_operator VARCHAR(6),
	value_low FLOAT,
	value_high FLOAT,
	value_low_inclusive BOOLEAN,
	value_high_inclusive BOOLEAN,
	unit TEXT,
	modifier VARCHAR(13),
	frequency_qualifier VARCHAR(12),
	epistemic_modality VARCHAR(9),
	value_qualifier VARCHAR(13),
	degree_qualifier VARCHAR(10),
	modality_text TEXT,
	modality_start INTEGER,
	modality_end INTEGER,
	season_operator VARCHAR(6),
	negated BOOLEAN,
	negation_scope VARCHAR(7),
	cardinality TEXT,
	source_text TEXT NOT NULL,
	source_statement_id TEXT,
	source_start INTEGER,
	source_end INTEGER,
	extractor TEXT,
	confidence FLOAT,
	normalization_status VARCHAR(16),
	"TraitExtraction_id" INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY("TraitExtraction_id") REFERENCES "TraitExtraction" (id)
);
CREATE INDEX "ix_TraitAssertion_id" ON "TraitAssertion" (id);

CREATE TABLE "TermMention" (
	mention_id TEXT NOT NULL,
	start INTEGER NOT NULL,
	"end" INTEGER NOT NULL,
	surface_form TEXT NOT NULL,
	normalized_form TEXT NOT NULL,
	language TEXT,
	longest_match BOOLEAN,
	overlap_group INTEGER,
	match_type TEXT,
	organ_context TEXT,
	logical_operator VARCHAR(6),
	attribute_id TEXT,
	"TraitExtraction_id" INTEGER,
	PRIMARY KEY (mention_id),
	FOREIGN KEY("TraitExtraction_id") REFERENCES "TraitExtraction" (id)
);
CREATE INDEX "ix_TermMention_mention_id" ON "TermMention" (mention_id);

CREATE TABLE "SeasonContext" (
	id INTEGER NOT NULL,
	season_term TEXT,
	season_text TEXT NOT NULL,
	start INTEGER,
	"end" INTEGER,
	start_month INTEGER,
	end_month INTEGER,
	hemisphere VARCHAR(11),
	geographic_context TEXT,
	temporal_relation VARCHAR(14),
	"TraitAssertion_id" INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_SeasonContext_id" ON "SeasonContext" (id);

CREATE TABLE "DevelopmentalStageContext" (
	id INTEGER NOT NULL,
	stage_term TEXT NOT NULL,
	stage_text TEXT NOT NULL,
	start INTEGER,
	"end" INTEGER,
	temporal_relation VARCHAR(14),
	"TraitAssertion_id" INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_DevelopmentalStageContext_id" ON "DevelopmentalStageContext" (id);

CREATE TABLE "TermCandidate" (
	id INTEGER NOT NULL,
	target_id TEXT NOT NULL,
	label TEXT NOT NULL,
	namespace TEXT NOT NULL,
	score FLOAT NOT NULL,
	mapping_relation TEXT,
	review_status TEXT,
	"TermMention_mention_id" TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY("TermMention_mention_id") REFERENCES "TermMention" (mention_id)
);
CREATE INDEX "ix_TermCandidate_id" ON "TermCandidate" (id);

CREATE TABLE "UnresolvedTraitSpan_promoted_po_ids" (
	"UnresolvedTraitSpan_id" INTEGER,
	promoted_po_ids TEXT,
	PRIMARY KEY ("UnresolvedTraitSpan_id", promoted_po_ids),
	FOREIGN KEY("UnresolvedTraitSpan_id") REFERENCES "UnresolvedTraitSpan" (id)
);
CREATE INDEX "ix_UnresolvedTraitSpan_promoted_po_ids_UnresolvedTraitSpan_id" ON "UnresolvedTraitSpan_promoted_po_ids" ("UnresolvedTraitSpan_id");
CREATE INDEX "ix_UnresolvedTraitSpan_promoted_po_ids_promoted_po_ids" ON "UnresolvedTraitSpan_promoted_po_ids" (promoted_po_ids);

CREATE TABLE "TraitAssertion_quality_mention_ids" (
	"TraitAssertion_id" INTEGER,
	quality_mention_ids TEXT,
	PRIMARY KEY ("TraitAssertion_id", quality_mention_ids),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_TraitAssertion_quality_mention_ids_TraitAssertion_id" ON "TraitAssertion_quality_mention_ids" ("TraitAssertion_id");
CREATE INDEX "ix_TraitAssertion_quality_mention_ids_quality_mention_ids" ON "TraitAssertion_quality_mention_ids" (quality_mention_ids);

CREATE TABLE "TraitAssertion_value_terms" (
	"TraitAssertion_id" INTEGER,
	value_terms TEXT,
	PRIMARY KEY ("TraitAssertion_id", value_terms),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_TraitAssertion_value_terms_value_terms" ON "TraitAssertion_value_terms" (value_terms);
CREATE INDEX "ix_TraitAssertion_value_terms_TraitAssertion_id" ON "TraitAssertion_value_terms" ("TraitAssertion_id");

CREATE TABLE "TraitAssertion_bearer_context_qualities" (
	"TraitAssertion_id" INTEGER,
	bearer_context_qualities TEXT,
	PRIMARY KEY ("TraitAssertion_id", bearer_context_qualities),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_TraitAssertion_bearer_context_qualities_bearer_context_qualities" ON "TraitAssertion_bearer_context_qualities" (bearer_context_qualities);
CREATE INDEX "ix_TraitAssertion_bearer_context_qualities_TraitAssertion_id" ON "TraitAssertion_bearer_context_qualities" ("TraitAssertion_id");

CREATE TABLE "TraitAssertion_mapping_provenance" (
	"TraitAssertion_id" INTEGER,
	mapping_provenance TEXT,
	PRIMARY KEY ("TraitAssertion_id", mapping_provenance),
	FOREIGN KEY("TraitAssertion_id") REFERENCES "TraitAssertion" (id)
);
CREATE INDEX "ix_TraitAssertion_mapping_provenance_mapping_provenance" ON "TraitAssertion_mapping_provenance" (mapping_provenance);
CREATE INDEX "ix_TraitAssertion_mapping_provenance_TraitAssertion_id" ON "TraitAssertion_mapping_provenance" ("TraitAssertion_id");

CREATE TABLE "TermMention_semantic_roles" (
	"TermMention_mention_id" TEXT,
	semantic_roles TEXT,
	PRIMARY KEY ("TermMention_mention_id", semantic_roles),
	FOREIGN KEY("TermMention_mention_id") REFERENCES "TermMention" (mention_id)
);
CREATE INDEX "ix_TermMention_semantic_roles_TermMention_mention_id" ON "TermMention_semantic_roles" ("TermMention_mention_id");
CREATE INDEX "ix_TermMention_semantic_roles_semantic_roles" ON "TermMention_semantic_roles" (semantic_roles);

CREATE TABLE "TermMention_registry_term_ids" (
	"TermMention_mention_id" TEXT,
	registry_term_ids TEXT,
	PRIMARY KEY ("TermMention_mention_id", registry_term_ids),
	FOREIGN KEY("TermMention_mention_id") REFERENCES "TermMention" (mention_id)
);
CREATE INDEX "ix_TermMention_registry_term_ids_TermMention_mention_id" ON "TermMention_registry_term_ids" ("TermMention_mention_id");
CREATE INDEX "ix_TermMention_registry_term_ids_registry_term_ids" ON "TermMention_registry_term_ids" (registry_term_ids);

CREATE TABLE "TermMention_component_ids" (
	"TermMention_mention_id" TEXT,
	component_ids TEXT,
	PRIMARY KEY ("TermMention_mention_id", component_ids),
	FOREIGN KEY("TermMention_mention_id") REFERENCES "TermMention" (mention_id)
);
CREATE INDEX "ix_TermMention_component_ids_component_ids" ON "TermMention_component_ids" (component_ids);
CREATE INDEX "ix_TermMention_component_ids_TermMention_mention_id" ON "TermMention_component_ids" ("TermMention_mention_id");

CREATE TABLE "TermCandidate_registry_term_ids" (
	"TermCandidate_id" INTEGER,
	registry_term_ids TEXT,
	PRIMARY KEY ("TermCandidate_id", registry_term_ids),
	FOREIGN KEY("TermCandidate_id") REFERENCES "TermCandidate" (id)
);
CREATE INDEX "ix_TermCandidate_registry_term_ids_registry_term_ids" ON "TermCandidate_registry_term_ids" (registry_term_ids);
CREATE INDEX "ix_TermCandidate_registry_term_ids_TermCandidate_id" ON "TermCandidate_registry_term_ids" ("TermCandidate_id");

CREATE TABLE "TermCandidate_evidence" (
	"TermCandidate_id" INTEGER,
	evidence TEXT,
	PRIMARY KEY ("TermCandidate_id", evidence),
	FOREIGN KEY("TermCandidate_id") REFERENCES "TermCandidate" (id)
);
CREATE INDEX "ix_TermCandidate_evidence_evidence" ON "TermCandidate_evidence" (evidence);
CREATE INDEX "ix_TermCandidate_evidence_TermCandidate_id" ON "TermCandidate_evidence" ("TermCandidate_id");
