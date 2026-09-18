# FLOPO flora assertion and observation model

Status: accepted design, revised 2026-08-04; schema extensions E2 (per-operand qualifiers) and E3
(positional scope, nested parts, pinned BSPO) added 2026-09-18 after curator approval.

This document is the normative design for representing FLOPO vocabulary, statements in floras,
and observations. `flopo.owl` is the reusable vocabulary. Source-specific claims and empirical
observations live in separate OWL modules. FAC-representable claims import the generated
annotation-class extension; qualitative continua, taxon-level alternatives, and transitions are
retained as source-anchored relation records instead.

## 1. Logical layers

### Reusable FLOPO TBox

FLOPO contains reusable traits and phenotype manifestations. A trait combines a plant entity with
the most specific appropriate class in PATO's `attribute_slim`; a manifestation combines the same
entity with a value of that attribute. Thus a numerical source phenotype always has a reusable
trait such as `pedicel length` in FLOPO, even when its particular interval is source-specific.

Source-specific intervals and arbitrary disjunctions remain OWL class descriptions. They are not
minted in the FLOPO term namespace merely because they occur in a flora. Reusable relational and
composite phenotypes may be named in FLOPO after review.

PO remains the preferred bearer vocabulary. If a flora requires an anatomical bearer absent from
PO, FLOPO may contain a local support class under the closest PO superclass. Such a class must have
an evidence-backed definition and an asserted superclass, plus a `part_of` axiom whenever that
parthood is universal. It uses a FLOPO ontology IRI; source statements, formal assertions, and
observations continue to use their separate `w3id.org/flopo/...` data IRI spaces.

### Identified annotation-class extension

The separate ontology `https://w3id.org/flopo/annotation-extension` gives every distinct logical
phenotype description a stable class IRI of the form
`https://w3id.org/flopo/annotation-class/FAC_<digest>`. Each generated class is defined with
`EquivalentClasses(FAC_<digest> <OWL class description>)`. These are annotation targets, not
curated FLOPO vocabulary terms, so their IDs never use `FLOPO_`.

Identity is derived from a canonical form of the logical expression. Bearer, quality expression,
same-bearer context qualities, typed part restrictions (including nested parts and BSPO region
fillers, section 9), numeric bounds and unit, scoped negation, seasonal restrictions, and PO
developmental-stage restrictions participate. Taxon, source, provenance offsets, extractor,
confidence, modalities such as *usually*, per-operand qualifiers (`value_operands`, section 5),
bearer-scope provenance (`bearer_scope`) and part cue evidence (`part_text`) do not. Thus two flora
assertions and an observation reuse one `FAC_` IRI whenever they characterize the same phenotype.
The registry retains the full SHA-256 digest and canonical signature; the public local ID uses the
first 128 digest bits.

FAC-representable annotation data uses `phenotype_class_iri` as its authoritative semantic target.
Decomposed fields such as `po_id`, `pato_id`, `value_terms`, and `value_operator` are retained for
extraction, indexing, reconstruction, and verification, but consumers can follow the class IRI.
The OWL source module links a formal assertion to this class IRI with the annotation property
`flopoann:phenotype_class`, avoiding class/individual punning. It imports the extension instead of
repeating each expression definition. Section 3 describes the deliberately non-FAC qualitative
relation exception.

### Flora source TBox

An unqualified, curated flora claim is a source-scoped universal statement. For example:

```text
NCBITaxon:Quercus SubClassOf sio:has_phenotype some FAC:green-leaf-expression-id
```

Here the `FAC` class is equivalent to the OWL description for a phenotype having as part a leaf
that has quality green. The source module, rather than `flopo.owl` or the annotation extension,
owns the taxon axiom. A strong closed reading may additionally constrain every phenotype value for
the same trait. Source modules must not be merged into a single global theory without choosing how
to handle contradictions and differing geographic scopes.

### Observation ABox

An observation characterizes particular organisms, structures, qualities, processes, and records.
It uses SIO `observing` or, only when an actual measurement took place, SIO `measuring`. Entailments
from a flora source are never counted as observed evidence.

## 2. Quantitative phenotypes

`pedicel 5-10 mm long` in a flora is a phenotype class description consisting of the reusable
`pedicel length` trait and a value restriction. The complete description receives an `FAC_` IRI in
the annotation extension. It is not a measurement event or measurement result.

```text
FLOPO:pedicel_length
  and flopoann:has_magnitude some xsd:decimal[>= 5, <= 10]
  and flopoann:has_value_unit some UO:0000016
```

`flopoann:has_magnitude` is functional for one quality realization. Units are normalized before
logical comparison because OWL reasoners do not convert units. The verbatim number and unit remain
in the source statement. An observation may separately record a SIO measurement process and result
as evidence for the observed magnitude.

## 3. Qualitative value relations

Phrases such as *elliptic to ovate* normally describe a continuum that includes unstated
intermediate shapes. They are not equivalent to either `elliptic and ovate` or the finite union
`elliptic or ovate`. Likewise, alternatives reported across members of a taxon are not necessarily
an exhaustive value set, and *green becoming red* places its endpoints at different times.

The wire model therefore uses `qualitative_value_relation` with one controlled interpretation
(`continuum`, `taxon_level_alternatives`, or `temporal_transition`), two ordered grounded endpoint
classes, and exact source text/offsets for both endpoints and the connector. The top-level
`pato_id` is the common PATO attribute, such as shape or colour. Such an assertion:

* has no `phenotype_class_iri` and never enters the FAC registry;
* never creates an `owl:unionOf`, conjunctive parents, or a reusable FLOPO class;
* never generates a strict taxon `SubClassOf` axiom;
* is serialized as a `flopoann:QualitativeValueRelation` linked to the formal flora assertion,
  retaining the interpretation and all endpoint/connector evidence.

Admission requires exact source spans, live endpoint identifiers, a PATO attribute at the top
level, an allowed bearer/attribute pair, no conflicting logical/numeric/negation/context fields,
and deterministic local gates. Machine review can approve only the runner-derived exact signature;
two independent model families must agree, and every non-consensus occurrence remains explicitly
held. Held items may be admitted when a third model family agrees exactly with one of the first two
and all deterministic gates pass (curator decision, 2026-09-18). A deterministic recovery rule may
also admit relations without per-item model review when a seeded, stratified audit of its output
has a 95% Wilson lower bound of at least 0.95; its provenance names the rule and the audit sample.
This review status is machine provenance, never a claim of human or curator approval.

### Endpoint qualifiers (E2)

An endpoint may carry its own degree, approximation, or frequency cue: *narrowly elliptic to
broadly elliptic*. The endpoint text (`from_text`/`to_text`) then covers the cue and the value, and
an optional `from_operand`/`to_operand` record (a `ValueOperand`, section 5) stores the grounded
value, the controlled qualifier, and the verbatim cue with offsets. Its value must equal
`from_value`/`to_value`, its text and offsets must equal the endpoint text and offsets, and its
`operand_index` is 0 or 1. Endpoint operands are provenance on a non-FAC relation; they change
neither the relation semantics used for assertion identity nor any FAC class. They are serialized
as `flopoann:ValueOperand` individuals linked by `flopoann:qualitative_from_operand` /
`flopoann:qualitative_to_operand`.

Composite operands (an operand or endpoint that is itself a continuum, *oblong or
oblong-lanceolate*; proposal E1) are deferred and not part of the wire model.

## 4. Lossless provenance

Every source statement that supports a formal assertion is a first-class `flopoann:SourceStatement`
and `sio:statement`. Its stable identifier is derived from source collection, source document,
segment occurrence, offsets, and verbatim text--never from text alone. Consequently identical
sentences in two treatments remain different evidence entities.

A trait assertion may keep a narrow lexical anchor for extraction, but its linked source statement
must cover the complete available support: the verbatim bearer mention, predicate/comparator,
modality, season, and developmental-stage cue.  When a bearer is supplied only by a FlorML organ
heading rather than repeated in the segment, that heading remains explicit as the record's
`organ_hint`; it is never invented inside the verbatim statement.  The provenance normalizer
expands legacy narrow anchors to include every exact supporting cue it can locate, and validation
rejects a linked statement that drops any retained evidence.

The provenance chain is:

```text
source document
  <- prov:wasDerivedFrom - source statement
  <- prov:wasDerivedFrom - formal flora assertion record
  <- prov:wasGeneratedBy - extraction/curation activity
```

Every strict OWL `SubClassOf` axiom is also represented as an `owl:Axiom` and annotated with the
source-statement IRI, formal-assertion IRI, exact cue, offsets, extractor, mapping provenance,
curation state, and confidence. Reusable FLOPO classes may point to all supporting assertion
records, but source records are never collapsed to a few examples.

## 5. Modality

Frequency, epistemic modality, value approximation, and degree are different axes:

* frequency: `universal`, `usually`, `often`, `sometimes`, `occasionally`, `rarely`, `never`, or
  `unspecified`;
* epistemic force: `asserted`, `probable`, `possible`, `uncertain`, or `reported`;
* value qualifier: `exact`, `approximately`, `nearly`, `almost`, or `sub` (Latin *sub-*/*semi-*
  prefix, used only when no reviewed PATO/FLOPO term exists for the prefixed form);
* degree qualifier: `unmodified`; the intensity values `slightly`, `moderately`, `very`,
  `extremely`, `completely`; and the dimensional values `narrowly`, `broadly` (width),
  `densely`, `sparsely` (density), `shortly` (extent), `finely` (texture), `deeply`,
  `shallowly` (depth). Each value carries an `axis` annotation in the LinkML enum. French cues
  map directly (*étroitement*, *largement*, *densément*, *éparsement*/*peu*, *brièvement*,
  *finement*, *profondément*, *peu profondément*); the shared lexicon is
  `flopo2/annotation/operands.py`.

The exact lexical cue is always retained. No arbitrary numeric probability is assigned to words
such as *usually* or *often*.

OWL annotations do not weaken an axiom. Therefore only strict, accepted assertions are emitted as
logical taxon subclass axioms. A qualified assertion is represented by a
`flopoann:FloraAssertion` meta-level individual linked to the stable annotation-extension class IRI.
The target remains an ordinary OWL class defined by `owl:equivalentClass`; it is not classified as
an `AnyOfPhenotypeExpression` or any other syntactic metaclass.
It can be compiled into a temporary constraint for validation or queried statistically, but it is
not silently asserted as a universal truth.

Unqualified flora prose defaults to `unspecified`, not automatically to a lexical `always`. The
curation policy determines whether an accepted unqualified claim receives strict logical force.

### Per-operand qualifiers (E2)

Assertion-level qualifiers apply to the whole statement. A cue that modifies one operand of a
categorical expression (*glabrous or sparsely pubescent*, *± densely tomentose*) is recorded in
`value_operands`: one `ValueOperand` per operand in source order, with `operand_index`, the grounded
`value`, the verbatim operand `text`/`start`/`end`, its own `degree_qualifier`,
`value_qualifier` and `frequency_qualifier`, and the verbatim `qualifier_text` with offsets, which
must lie inside the operand. The set of operand values equals `value_terms` (or the atomic
quality), and an atomic assertion has exactly one operand.

* **Entailing** cues keep FAC identity. Every degree value except `completely` is entailing:
  *sparsely pubescent* is pubescent, so the head value enters the FAC union and the cue is
  provenance. Operands never participate in the FAC signature, so adding them never changes a
  `phenotype_class_iri`.
* **Non-entailing** cues (`approximately`, `nearly`, `almost`, `sub`): *suborbicular* is not
  orbicular. An assertion with such an operand is not FAC-representable, carries no
  `phenotype_class_iri`, and is serialized with logical status `structured_value_operands`.
* **Strictness**: entailing degree operands keep strict eligibility; an operand-level frequency or
  approximation makes the assertion qualified (non-strict).
* **Conflicts**: the same axis may not carry different non-default values at assertion and operand
  level (`assertion_and_operand_qualifier_conflict`). Intensity and a dimensional degree combine:
  *very sparsely* keeps `very` at assertion level and `sparsely` on the operand.

Recovery rules write operands instead of discarding degree words. Stage assertions whose cue held
a degree word the earlier enum could not represent are enriched by an update-only correction delta
(`flopo2/verify/enrich_operand_qualifiers.py`) whose applier re-checks that the FAC IRI is
unchanged. In OWL, operands are `flopoann:ValueOperand` individuals linked by
`flopoann:has_value_operand` with operand value, qualifier and evidence annotations.

## 6. Seasonal context

Season is part of the phenotype class description:

```text
FLOPO:flower_red
  and flopoann:present_during some flopoann:wet_season
```

The model reuses `ENVO:03000096` (season), `ENVO:03000097` (warm season),
`ENVO:03000098` (cold season), and `ENVO:03000129` (monsoon season). The application vocabulary
provides spring, summer, autumn, winter, wet-season, and dry-season classes. These are not assigned
globally fixed calendar months: their interpretation is linked to the source's geographic context.

Calendar expressions such as `May-August` use an assertion-scoped season class with `start_month`
and `end_month` data restrictions. Wrap-around ranges and overlap are checked by the validator;
standard OWL datatype reasoning alone does not understand a cyclic calendar.

Multiple season contexts carry an explicit `atomic`, `one_of`, or `all_of` operator. Alternatives
are an anonymous union inside the annotation-extension class definition; conjunctive seasons
become separate temporal restrictions. Neither form creates a reusable FLOPO class automatically,
although the full description has an `FAC_` annotation ID.

For qualities, `flopoann:present_during` relates a phenotype manifestation to a season. For process
phenotypes, a more specific temporal relation such as RO `happens during` may be used. The local
relation is necessary because SIO `exists at` has a time-measurement range, while ENVO seasons are
temporal regions rather than measurement results.

## 7. Bearer age/maturity and developmental-stage context

Age and maturity qualifications are additional qualities of the same anatomical bearer. For
example, *young leaves pubescent* denotes the class description:

```text
SIO:010056 and BFO:0000051 some
  (PO:0009025 and RO:0000053 some PATO:0001320
              and RO:0000053 some PATO:0000309)
```

Here `PATO:0001320` is pubescent and `PATO:0000309` is young. Neither is modeled as a generic PO
developmental process. The wire field `bearer_context_qualities` contains only canonical PATO
identifiers, is sorted and deduplicated for class identity, and is omitted from the canonical
signature when empty so existing `FAC_` identifiers remain stable. A context quality may not
duplicate the assertion's primary categorical quality. Recovery requires the context cue and
bearer to occur in the same local clause; uncertain attachment remains unresolved.

True PO developmental stages are processes, not PATO qualities. A phenotype asserted only during
the whole-plant flowering stage is therefore represented separately:

```text
SIO:010056 and <positive phenotype expression>
  and flopoann:present_during_developmental_stage some PO:0007016
```

The wire field `developmental_stage_contexts` retains the PO class, exact cue, and offsets. The
stage restriction participates in FAC identity but does not create a FLOPO term. The dedicated
property ranges over `PO:0009012` (plant structure development stage); it is distinct from the
season-specific `flopoann:present_during`, whose range is an ENVO season. Multiple stage contexts
use the same `atomic`/`one_of`/`all_of` discipline as seasonal contexts.

Specimen preparation/state (*when dry*, *in sicco*, *à l’état sec*) is not a developmental stage
and is not converted to a PO-stage restriction. Bare *dry* can instead describe habitat, season,
texture, water composition, or another structure. Transition expressions such as *green when
young, red when mature* become two independently stage-scoped assertions only when both
value-stage attachments are explicit; otherwise they remain unresolved.

## 8. Scoped negation

Negation is part of the OWL class description and must state its scope. `negation_scope: quality`
preserves bearer existence:

```text
has_part some (Leaf and not (has_quality some Glabrous))
```

`negation_scope: absence` instead negates the complete represented EQ combination:

```text
not (has_part some (Trichome and has_quality some Black))
```

These are not interchangeable under open-world semantics: an organism without leaves satisfies
the second pattern for a leaf quality but not the first. Arbitrary negated descriptions receive
FAC identifiers only. A phrase such as *not exceeding 10 mm* is not logical negation; it is an
ordinary inclusive upper-bound phenotype. Unqualified accepted negative flora statements retain
the same source-scoped universal force as positive flora statements, while qualified/modal
negatives remain meta-level assertions.

## 9. Positional scope, BSPO parts and indumentum (E3)

Positional and sub-part cues (*glabrous above*, *pubescent beneath*, *à la face inférieure*, *hairy
at the apex*) are compiled as PO first, then pinned BSPO, never as free text:

1. **Substituted bearer.** When PO has the positional part, `po_id` becomes that class and the
   optional `bearer_scope` record keeps the organ as named (`outer_bearer`), the `scope_class`,
   `mode: substituted_bearer`, and the verbatim cue with offsets. PO's leaf lamina, sepal, petal,
   tepal, bract, cotyledon and petiole adaxial/abaxial epidermis classes cover *above/beneath*
   (for example PO:0000049 *leaf lamina abaxial epidermis*, defined as the epidermis covering the
   abaxial surface). A surface cue on a leaflet uses PO:0006018/PO:0006019 (leaf adaxial/abaxial
   epidermis), because a leaflet side is a portion of the compound leaf's epidermis and PO has no
   leaflet epidermis class. *Beneath/above* denote abaxial/adaxial only for these dorsiventral
   laminar organs, and *inside/outside* only for single perianth members and bracts; everything
   else stays unresolved. The reviewed table is `flopo2/annotation/positional.py`.
2. **Part restriction.** When the organ must remain the bearer or PO lacks the part (an ovary
   apex), the part is a `part_restrictions` filler, `has part some (part and has quality some V)`,
   and `bearer_scope.mode` is `part_restriction`. The filler is a PO class, a reviewed FLOPO-local
   support class, or a pinned BSPO class: BSPO:0000073 apical region, BSPO:0000074 basal region,
   BSPO:0000006 anatomical margin, BSPO:0000005 anatomical surface, BSPO:0000077/0000078
   proximal/distal region. The top-level quality repeats the value only when it holds for the
   whole organ (hairs at the apex make the ovary hairy); otherwise it is the value's PATO attribute.
3. **Indumentum.** Qualities of the hairs are qualities of PO:0000282 *trichome* as a part:
   *white-hairy* is `has part some (trichome and has quality some white)` on the organ, which keeps
   its hair-presence value; hair colour is never assigned to the organ. FLOPO_0986003
   *indumentum* names the collective covering.
4. **Nesting.** A part may have typed parts, to a total depth of two (bearer > part > part):
   *stellate-pubescent beneath* is abaxial epidermis with part trichome that is star shaped. A
   part may omit qualities only when it has nested parts. `part_text`/`part_start`/`part_end`
   keep each part cue.

`bearer_scope` and part cue evidence are provenance and never enter the FAC signature. Nested parts
enter it through an additive key emitted only when present, so every depth-one FAC identity is
unchanged. The BSPO release 2023-05-27 is pinned by checksum (`ontology/imports/bspo_import.sha256`)
and imported as the ROBOT BOT module `ontology/imports/bspo_import.owl` (term list
`bspo_terms.txt`, rebuild with `tools/build_bspo_import.py`, catalog entry *FLOPO pinned BSPO
import*). The annotation extension imports it; `flopo.owl` and its EL reasoning profile do not.
BSPO has no adaxial/abaxial side classes and no inner/outer surfaces; those remain PO/FLOPO
new-term requests rather than approximations with BSPO upper/lower sides.

The validator checks verbatim scope and part cues inside the linked statement, part depth, pinned
BSPO fillers, non-empty parts, that a substituted bearer equals the scope class (or a part
restriction contains it), and that the scope class is a reviewed or PO `part_of` part of the outer
bearer.

## 10. Validation

Observation-to-flora comparison returns `compatible`, `incompatible`, or `undetermined`, after
matching taxon, trait, bearer, geography, developmental context, and season. A compatible
observation supports but does not prove a universal flora statement. Missing evidence remains
undetermined under OWL's open-world semantics.

ELK remains suitable for the reusable EL vocabulary. Source validation involving unions,
complements, closure, and datatype facets requires an OWL 2 DL reasoner.
