-- # Class: TraitExtraction Description: The set of trait assertions extracted from a single text segment (one organ block of one taxon). Carries the provenance needed to trace every assertion back to its source.
--     * Slot: id
--     * Slot: taxon_name Description: Verbatim taxon name string from the source treatment.
--     * Slot: organ_hint Description: The FlorML char-class / subheading the segment came from (anatomical prior).
-- # Class: TraitAssertion Description: One grounded entity-quality observation: an anatomical entity (PO) bears a quality (PATO), optionally with a measured value/unit, modifier, or negation, justified by a source span.
--     * Slot: id
--     * Slot: anatomical_entity Description: The plant anatomical structure the quality inheres in (Plant Ontology).
--     * Slot: quality Description: The phenotypic quality or attribute (PATO).
--     * Slot: trait Description: Optional pre-composed plant trait this corresponds to (Trait Ontology).
--     * Slot: value_text Description: Categorical/free-text value of the trait when not numeric (e.g. "ovate").
--     * Slot: value_low Description: Lower bound of a measured range (e.g. 3 in "3-7 cm"). Numbers only.
--     * Slot: value_high Description: Upper bound of a measured range (e.g. 7 in "3-7 cm"). Numbers only.
--     * Slot: unit Description: Measurement unit (Units of measurement ontology), e.g. cm, mm.
--     * Slot: modifier Description: Frequency/degree hedge attached to the assertion in the text.
--     * Slot: negated Description: True if the text asserts the ABSENCE of the quality (e.g. "leaves not hairy").
--     * Slot: cardinality Description: Count when the trait is a number of parts (e.g. "stamens 6"). Free text to allow ranges.
--     * Slot: source_text Description: The exact span of the source segment that justifies this assertion (provenance / anti-hallucination anchor). MUST be copied verbatim from the input.
--     * Slot: confidence Description: Model self-reported confidence in [0,1]; refined later by self-consistency voting.
--     * Slot: TraitExtraction_id Description: Autocreated FK slot

CREATE TABLE "TraitExtraction" (
	id INTEGER NOT NULL,
	taxon_name TEXT,
	organ_hint TEXT,
	PRIMARY KEY (id)
);
CREATE INDEX "ix_TraitExtraction_id" ON "TraitExtraction" (id);

CREATE TABLE "TraitAssertion" (
	id INTEGER NOT NULL,
	anatomical_entity TEXT NOT NULL,
	quality TEXT NOT NULL,
	trait TEXT,
	value_text TEXT,
	value_low FLOAT,
	value_high FLOAT,
	unit TEXT,
	modifier VARCHAR(12),
	negated BOOLEAN,
	cardinality TEXT,
	source_text TEXT NOT NULL,
	confidence FLOAT,
	"TraitExtraction_id" INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY("TraitExtraction_id") REFERENCES "TraitExtraction" (id)
);
CREATE INDEX "ix_TraitAssertion_id" ON "TraitAssertion" (id);

