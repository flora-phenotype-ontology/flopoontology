# FLOPO flora assertion and observation model

Status: accepted design, revised 2026-07-18.

This document is the normative design for representing FLOPO vocabulary, statements in floras,
and observations. `flopo.owl` is the reusable vocabulary. Source-specific claims and empirical
observations live in separate OWL modules which import that vocabulary and the generated
annotation-class extension.

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
same-bearer context qualities, numeric bounds and unit, scoped negation, seasonal restrictions,
and PO developmental-stage restrictions
participate. Taxon, source,
provenance offsets, extractor, confidence, and modalities such as *usually* do not. Thus two flora
assertions and an observation reuse one `FAC_` IRI whenever they characterize the same phenotype.
The registry retains the full SHA-256 digest and canonical signature; the public local ID uses the
first 128 digest bits.

Annotation data uses `phenotype_class_iri` as its authoritative semantic target. Decomposed fields
such as `po_id`, `pato_id`, `value_terms`, and `value_operator` are retained for extraction,
indexing, reconstruction, and verification, but consumers need only follow the class IRI. The OWL
source module links a formal assertion to this class IRI with the annotation property
`flopoann:phenotype_class`, avoiding class/individual punning. It imports the extension instead of
repeating each expression definition.

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

## 3. Lossless provenance

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

## 4. Modality

Frequency, epistemic modality, value approximation, and degree are different axes:

* frequency: `universal`, `usually`, `often`, `sometimes`, `occasionally`, `rarely`, `never`, or
  `unspecified`;
* epistemic force: `asserted`, `probable`, `possible`, `uncertain`, or `reported`;
* value qualifier: `exact`, `approximately`, `nearly`, or `almost`.
* degree qualifier: `unmodified`, `slightly`, `moderately`, `very`, `extremely`, or
  `completely`.

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

## 5. Seasonal context

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

## 6. Bearer age/maturity and developmental-stage context

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

## 7. Scoped negation

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

## 8. Validation

Observation-to-flora comparison returns `compatible`, `incompatible`, or `undetermined`, after
matching taxon, trait, bearer, geography, developmental context, and season. A compatible
observation supports but does not prove a universal flora statement. Missing evidence remains
undetermined under OWL's open-world semantics.

ELK remains suitable for the reusable EL vocabulary. Source validation involving unions,
complements, closure, and datatype facets requires an OWL 2 DL reasoner.
