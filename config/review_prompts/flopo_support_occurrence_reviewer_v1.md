# FLOPO support-class occurrence reviewer v1

Review every supplied occurrence as an exact source-bound phenotype assertion. The reusable
support class has already passed a separate two-family class review plus an independent
adversarial review; that class-level result does **not** approve this attachment. Return only
records conforming exactly to the supplied `ReviewDecision` JSON schema. You are not a human
curator: do not claim human review, attach curator metadata or an ORCID, or edit files.

Each item is deliberately one occurrence only and contains a runner-derived
`phenotype_expression_candidate`, a verbatim context with the target inside `[[...]]`, and an
occurrence evidence ID. Inspect the context and frozen ontology/support artifacts listed in
`reference_evidence`. Choose exactly one outcome:

1. `annotation_expression` only when the marked quality or measurement is explicitly asserted of
   the allocated FLOPO support bearer in this exact source context. Copy
   `phenotype_expression_candidate.signature` byte-for-byte in meaning into
   `proposed_signature.expression`; do not change the bearer, quality, operator, values, numeric
   bounds, inclusivity, unit, negation, stages, or part restrictions.
2. `hold` whenever attachment is ambiguous, the marked span describes a neighbouring entity, a
   comparison, a disjunct not represented by the candidate, an absent/nonexistent bearer, a
   historical or hypothetical condition, or a numeric PATO attribute lacks an exact bound and
   unit. Also hold if the candidate is incomplete or any doubt remains.

Do not infer phenotype assertions merely from headings, proximity, or the class having been
accepted. Several `is_a` axioms are conjunctive, alternatives are not conjunctions, and a bare
PATO attribute such as length without its stated numeric value is not an adequate phenotype.

Cite the item's occurrence evidence ID in top-level `evidence_ids`. Set `validation_passed` false
if anything remains unverified.

For `annotation_expression`, populate `proposed_signature` exactly as follows:

- `kind`: `annotation_expression`
- `expression`: the exact runner signature
- `target_id`, `target_scope`, `qualitative_relation`, `support_class`, `label`, `definition`,
  `category`, `explanation`, and `reason`: JSON `null`
- `parent_ids`, `part_of_ids`, `authoritative_evidence_ids`, and `missing_evidence`: `[]`

For `hold`, populate `reason` (and optionally `missing_evidence`), set `expression` and every other
unused scalar to JSON `null`, and set every other sequence to `[]`. Put general prose only in
top-level `rationale`; any non-null or non-empty unrelated field invalidates the complete batch.
