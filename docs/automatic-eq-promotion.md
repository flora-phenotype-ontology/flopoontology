# Automatic review and promotion of flora EQ classes

`flopo2.verify.eq_release` stages atomic entity–quality signatures, classifies them
with ELK, reviews the resulting taxonomy with Qwen, and promotes only passing
classes. A class can pass even when a source occurrence needs a separate negation,
span, disjunction or developmental-stage review. This workflow approves reusable
vocabulary; it does not change annotation occurrence gates.

The 2026-10-25 input is
`curation/flopo-global-eq-candidates-2026-10-25.tsv`: all 2,195 signatures from the
40-source local audit. The table contains provenance pointers and counts, not the
copyrighted description excerpts. Candidates use temporary hash-based IRIs until
promotion. Stable FLOPO IDs are allocated after the current maximum, with every
existing and deprecated identifier preserved.

The initial review added **963** EQ classes and held **1,232** candidates.
ELK found no passing candidates requiring equivalence reuse or collapse. Each held
candidate has one primary review category below; the TSV retains all its flags.

| Primary disposition | Candidates |
| --- | ---: |
| Added after all checks passed | 963 |
| Reasoner incoherence | 49 |
| Quality or bearer mapping | 4 |
| Collision with an existing label without proven equivalence | 27 |
| Qwen inherence disagreement | 60 |
| Qwen hierarchy disagreement | 1,092 |
| **Total** | **2,195** |

All 2,146 satisfiable candidates received complete model answers after retries.
The remaining 49 response errors concern the unsatisfiable candidates, whose
classified neighbourhoods are empty; they already fail deterministic admission.
The 1,152 candidates held only for Qwen disagreements initially needed review. A
negative model answer alone does not establish that an ontology relation is wrong.

## Run

From the repository root, using its Python environment and installed JDK/ROBOT:

```bash
.venv/bin/python -m flopo2.verify.eq_release prepare --work scratchpad/eq-campaign
.venv/bin/python -m flopo2.verify.eq_release review --work scratchpad/eq-campaign
.venv/bin/python -m flopo2.verify.eq_release promote --work scratchpad/eq-campaign
```

The default Qwen endpoint/model/key-file settings are shared with the flora
transcription client. `--base-url`, `--model`, `--key-file` and `--workers` are
available for an explicitly selected endpoint. Credentials are read by the client
and never written to the review artifacts. Eight concurrent requests is the default.

The work directory retains the controlled ontology closure, temporary classes,
reasoner taxonomy, all prompts' structured inputs, model responses, decisions and
input fingerprints. Review resumes from a content-addressed response cache. An
invalid or truncated answer is retried up to three times, then triaged; a failed
request is never counted as agreement. Re-running review retries request errors.

The initial 2026-10-25 review retains
`curation/flopo-global-eq-review-2026-10-25.json.gz`: exact request payloads,
normalized responses and recorded request errors, input fingerprints and the
promotion summary. The readable per-signature outcome table is
`curation/flopo-global-eq-dispositions-2026-10-25.tsv`.
`curation/flopo-global-eq-triage-2026-10-25.tsv` contains only held candidates,
grouped by their primary review reason and ordered by assertion frequency within
each group; it retains source identifiers and the detailed failed checks.
`curation/flopo-global-eq-summary-2026-10-25.json` records that initial snapshot's
counts, hashes and validation results. These historical files are preserved;
the subsequent re-extraction changes the final release artifacts.

## Checks and admission

1. Load FLOPO and the pinned local PO, PATO and plant GO modules without importing
   their unrelated external closures. Build every candidate's standard
   `has_part some (E and has_quality some Q)` definition and bearer grouping.
2. `tools/FlopoReasonerReport.java` uses the OWLAPI ELK reasoner to return
   satisfiability, equivalent named classes and **direct** superclasses. Neighbour
   depths are measured on this reasoner taxonomy, not on asserted or transitively
   materialized RDF edges. Equivalent names share their neighbourhoods.
3. Check identifiers, obsoletion, quality ancestry, known PATO homonym traps,
   explicitly forbidden combinations, and
   `config/flopo_quality_bearer_constraints.tsv`. The latter restricts selected
   qualities to appropriate bearer ancestries. A missing allow-list entry alone
   does not prohibit a novel combination.
4. **After classification**, ask Qwen whether Q can actually inhere in E and, for
   every named superclass D up to three levels above C, “Is C a kind of D? Answer
   yes or no.” For every subclass S up to two levels below C, ask “Is S a kind of
   C? Answer yes or no.” Give class, bearer and quality labels/definitions and
   bearer/quality ancestors. Larger neighbourhoods are split into batches; no
   neighbours are silently truncated.
5. Require a yes to inherence and every hierarchy question, all deterministic
   checks passing, and at least one nontrivial classified neighbour. Missing,
   duplicated, unexpected or non-binary answers fail validation.
6. Reuse an active existing FLOPO class when ELK establishes equivalence. Collapse
   equivalent passing candidates to one new stable class. Preserve a disposition
   for each original signature. A rejected candidate is never published merely
   because it is equivalent to a passing one.

ELK establishes entailments in its supported profile. Satisfiability in this
controlled closure is not a proof that a botanical combination is meaningful,
which is why independent inherence and taxonomy judgements are required. Qwen's
judgements are fallible machine review, not a claim of expert consensus.

The promotion step checks that the ontology, candidate list, constraints, relevant
code and review artifacts still match the classified run. It writes the module,
registry, accepted pair table and triage dispositions. It refuses to reuse an
already-promoted run. Each subsequent campaign gets its own generated block and
module; the allocation registry accumulates stable identifiers.

After promotion, rebuild and embed the existing flora corrections module so new
solid-shape classes use “ovoid” and new length classes receive their long/short
synonyms:

```bash
.venv/bin/python -m tools.build_flopo_flora_corrections
.venv/bin/python -m tools.update_flopo_flora_corrections_release
```

Then run the README's release finalization passes, including registry regeneration,
bearer parents, classification and inferred-parent materialization.
The candidate review is over the staged taxonomy containing all candidates;
release classification is repeated after removing triaged candidates.

## Re-extraction after a failed model review

`flopo2.verify.eq_reextract` selects **all 1,217** initially held signatures with
a Qwen failure flag, including request errors and cases with additional deterministic
failures. The other 15 candidates have only deterministic failures. The selected
signatures occur in 3,695 assertions; re-extraction uses up to three examples per
concept, prioritizing different sources (2,017 examples in this campaign).

Qwen reads the original passage afresh, with the previous EQ and criticism explicitly
marked fallible. It selects from existing, live entity/quality IDs with definitions
and synonyms. Quotes must match the source exactly. Negation, stage, frequency,
degree and alternative/compound operators are retained. Broader or uncertain
mappings, unsupported phenomena and concepts requiring richer expressions remain
in triage. Candidate retrieval is finite: `no_mapping` means no adequate mapping
was found among the supplied alternatives, not that none exists anywhere in PO/PATO.

```bash
.venv/bin/python -m flopo2.verify.eq_reextract prepare --work scratchpad/reextract
.venv/bin/python -m flopo2.verify.eq_reextract extract --work scratchpad/reextract
.venv/bin/python -m flopo2.verify.eq_release prepare --work scratchpad/revalidate \
  --candidates scratchpad/reextract/candidates.tsv \
  --evidence scratchpad/reextract/validation-evidence.json
.venv/bin/python -m flopo2.verify.eq_release review --work scratchpad/revalidate
.venv/bin/python -m flopo2.verify.eq_release promote --work scratchpad/revalidate \
  --dispositions curation/flopo-reextracted-eq-dispositions-2026-10-25.tsv
.venv/bin/python -m flopo2.verify.eq_reextract record --work scratchpad/reextract
```

Every exact proposed EQ is classified again before the second Qwen review. This
review supplies formal EQ patterns and anatomical part relationships, and requires
an explicit `grounded: yes` for the source examples as well as inherence and every
hierarchy answer. The second round does not override a negative answer. Passing
equivalents reuse existing IDs; only genuinely new passing concepts receive IDs.
When several originals converge on the same EQ, validation receives up to three
examples for that deduplicated class. A passing class outcome is not a second
review of every re-extracted source span.
Separate campaign ledgers preserve the original failures alongside their outcomes.
`flopo-current-eq-dispositions-2026-10-25.tsv` consolidates the current outcome of
all 2,195 original candidates; its `-triage.tsv` companion contains only candidates
still requiring review. A partially accepted re-extraction remains in that review
table. Correcting a mapping does not assert that the original, rejected EQ was valid.

Source passages and exact requests remain in the ignored work directory. Public
ledgers record source identifiers, character offsets, SHA-256 hashes, qualifiers,
model reasons and dispositions. Any public review archive redacts passages and
quotes while retaining hashes of the exact private requests. This is vocabulary
review; it does not rewrite or approve individual taxon assertions.

An endpoint change can reuse exact successful requests from an explicitly named
earlier endpoint via `--cache-base-url`. Request keys continue to include the actual
original endpoint, model, complete payload and prompt version. The manifest records
the selected endpoint for each request; an old response is never relabelled as a
request to a new server.

## Re-extraction results for 2026-10-25

All **1,217** original candidates with a Qwen failure were sent for re-extraction,
using 2,017 source examples from 3,695 available assertions. Qwen returned 1,098
extractions, 56 no-mapping outcomes, 25 complex cases, 23 unsupported cases and
15 invalid responses after retries. No-mapping means no exact mapping was found
within the supplied candidate vocabulary; it does not establish absence from PO
or PATO.

The exact proposals deduplicated to **1,077 EQs**. ELK classified these before the
second Qwen review, which asked 5,021 hierarchy questions and checked inherence
and source grounding. All 1,077 received valid review responses. **584 passed**
all checks: **559 new classes** were added and **25 proposals** reused existing
classes with exact synonyms. The remaining **493 proposals** are held.

The current ledger accounts for every original candidate:

| Current outcome | Original candidates |
| --- | ---: |
| Accepted in the initial pass | 963 |
| Resolved after re-extraction | 545 |
| Partially accepted; further review needed | 28 |
| Held for review | 659 |
| **Total** | **2,195** |

Thus **687 original candidates still require review**. Counts differ between
original candidates, proposals and new classes because re-extraction can correct,
split or merge concepts. In total this release adds **1,522 EQ classes** and
contains **27,437 FLOPO classes**, preserving all previous identifiers.

Detailed outcomes are in `curation/flopo-eq-reextraction-outcomes-2026-10-25.tsv`;
the deduplicated decisions are in
`curation/flopo-reextracted-eq-dispositions-2026-10-25.tsv`. The redacted request
context, Qwen answers and fingerprints are retained in
`curation/flopo-eq-reextraction-review-2026-10-25.json.gz`, with counts and artifact
hashes in `curation/flopo-eq-reextraction-summary-2026-10-25.json`.
The summary's prepublication Dashboard result explicitly records the unresolved
version URL; the published release's complete validation belongs in
`releases/2026-10-25/validation.json`.

## Trait and phenotype annotations

```bash
.venv/bin/python -m flopo2.owl.trait_phenotype
```

`http://phenomebrowser.net/flopo/annotation/traitOrPhenotype` is an OWL annotation
property with literal values `trait` and `phenotype`:

- An EQ quality tagged `attribute_slim` in PATO gives a **trait**, e.g. leaf colour.
- A quality tagged `value_slim`, a descendant of a tagged value, or an explicitly
  declared local supporting value gives a **phenotype**, e.g. leaf red.
- Specified qualitative expressions and restricted measurement values are
  phenotypes.
- Attribute-only unions or intersections remain traits; mixed attribute/value
  operands are left unresolved unless an explicit value restriction determines
  the classification.
- Obsolete classes, supporting entities/qualities, broad phenotype groupings and
  untagged/ambiguous cases receive a basis explaining why no binary value was
  assigned. An untagged descendant of an attribute is not assumed to be a trait.

`traitPhenotypeBasis` records the evidence or exclusion reason, and
`curation/flopo-trait-phenotype-classification.tsv` provides the full accounting.
The annotation introduces no disjointness: a red-leaf phenotype remains a subclass
of the leaf-colour trait.

The 2026-10-25 release has **5,956 traits** and **19,051 phenotypes**. Another
2,430 classes are obsolete, supporting vocabulary, broad groupings or unresolved
cases; each has an explicit classification basis rather than a guessed binary tag.

## Provisional vocabulary

The flora-value specification now records a `provisional_reason` and
`definition_source`. These become OWL editor notes and source annotations. The
2026-10-25 review table records an individual modelling or lexical issue for each
provisional term. Provisional normalization rules are labelled `provisional`,
not falsely presented as curator-approved. A related synonym does not generate an
exact grounding rule.

The vocabulary update declares 25 previously referenced but missing IDs
(`FLOPO:0991046`–`FLOPO:0991070`) and 24 additional qualities
(`FLOPO:0991071`–`FLOPO:0991094`), each with a definition. Together with the 20
previous provisional qualities, these give 69 individually reviewed provisional
terms in `curation/flopo-provisional-term-review-2026-10-25.tsv`.

“Provisional” identifies an unresolved lexical or modelling decision, not a
missing definition. The outstanding decisions include:

- **Scope and reference structures:** appressed requires the surface against
  which an organ lies; concolorous/discolorous compare surfaces or parts;
  monoecious and andromonoecious describe a plant's sexual system, not one flower.
- **Time and development:** glabrescent describes loss of hairs, and accrescent
  describes enlargement during maturation. Their temporal meaning needs richer
  modelling than an unrestricted atomic quality.
- **Degree and boundaries:** subglabrous, subcoriaceous, serrulate, mucronulate
  and strigulose need decisions about separate values versus qualified values.
- **Sense distinctions:** valvate here means aestivation; resinous is not
  synonymous with adhesive; fibrous texture differs from fibrous-rooted
  architecture. These distinctions must also be respected in source annotations.
- **Upstream reuse:** papillose, sulcate, ribbed and amplexicaul need comparison
  with the corresponding existing PATO/PO/FLOPO meanings before an upstream
  submission or an exact equivalence is justified.

The review removed unsupported exact-normalization rules for chickpea-sized and
umbellate-racemose, retained glabrate and hypogeal only as related synonyms where
their senses differ, and removed the unsupported numeric range from pea-sized.
These are preliminary FLOPO vocabulary decisions; no PATO or PO submission is
implied by publication of the local classes.
