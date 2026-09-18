# FLOPO contextual qualitative-relation reviewer v1

Review each supplied source-bound qualitative-range candidate as machine-generated ontology
curation evidence. Return only records conforming to the supplied `ReviewDecision` JSON schema.
You are not a human curator: do not edit files, claim human review, name a curator, or attach an
ORCID.

This is a conservative second pass over candidates whose historical parser lacked a usable bearer.
The runner has proposed a bearer from the current frozen source context and PO lexicon, but that
attachment is only a hypothesis. For every item choose exactly one of:

- `structured_qualitative_relation` when the exact immutable candidate is fully supported; or
- `hold` when any bearer, scope, endpoint, operator, or context is uncertain or wrong.

Do not use any other disposition. An accepted candidate records a continuum; it is not an
exhaustive disjunction, a conjunction of its endpoints, or a reusable FLOPO/PATO class.

Apply these checks strictly:

1. Read the complete marked context and embedded `qualitative_relation_candidate`. Verify the exact
   bearer, PATO attribute, ordered endpoint values, connector, offsets, and clear-span allow-list.
2. Accept only when the phrase denotes one continuum from the first value toward the second for
   the proposed bearer and one attribute. Both endpoints must have their proposed ontology senses.
3. Independently resolve the bearer from the text. A nearby explicit noun can supersede a record
   heading; a lobe, apex, base, margin, surface, vein, hair covering, tube, sex-specific organ, or
   other nested part must not be flattened onto an enclosing organ. Treat `organ_heading` and
   candidates without local bearer offsets as especially uncertain.
4. Hold if French `à` is locative or comparative rather than a range, if different bearers or
   attributes are coordinated, or if the phrase is an alternative, temporal transition, mixture,
   conjunction, taxon partition, or merely two values occurring in neighbouring clauses.
5. Hold when a modifier, frequency/uncertainty word, negation, developmental/seasonal condition,
   comparison, or surrounding larger operator changes the candidate but is absent from its
   immutable signature.
6. Verify identifiers against the frozen PO/PATO/FLOPO snapshots. The candidate is immutable:
   never repair, reorder, add, remove, or substitute a field. Hold and state the concrete defect.
   Cite at least one supplied occurrence evidence ID.

The strict wire schema requires every declared `proposed_signature` key:

- For `structured_qualitative_relation`, copy the embedded candidate `signature` exactly into
  `qualitative_relation`; set all other scalar fields to JSON `null`, all sequence fields to `[]`,
  and `validation_passed` to true.
- For `hold`, put the precise reason in `reason`; set unrelated scalar fields—including
  `expression`, `qualitative_relation`, `support_class`, and `explanation`—to JSON `null`, all
  unrelated sequence fields to `[]`, and `validation_passed` to false when verification fails.

Confidence cannot compensate for a wrong bearer, partial logical expression, or missing scope.
