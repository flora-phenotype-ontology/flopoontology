# Source-specific botanical colour review

Date: 2026-07-15

This is a review-only design. It changes no PATO or FLOPO class and reserves no identifier. The
machine-readable companion is `botanical_colour_sensu_proposals.tsv`; its curator columns are
blank. `botanical_colour_prototypes.tsv` remains the evidence inventory from which the proposals
were separated.

## Recommendation

Represent a historically variable colour name by an unqualified lexical umbrella and one
operational subclass per documented standard:

```text
scarlet
├── scarlet sensu Saccardo (1891), category 15
├── scarlet sensu Ridgway (1912), plate I chip 5
└── scarlet sensu Wilson Horticultural Colour Chart (1938/1940), H19
```

An observation containing only `scarlet` maps to the umbrella. It maps to a sensu child only when
the source explicitly declares the relevant standard, chart, chip, or operational protocol. This
preserves all three recognition definitions without pretending that they specify one shared
wavelength, RGB interval, or physical prototype.

The generic class is an **open primitive superclass**, not currently equivalent to the union of
the known sensu children. The list of historical standards is not demonstrably exhaustive, and an
unqualified flora use may follow an undocumented local convention. Closing `scarlet` to today's
three children would therefore exclude future or unrecorded senses.

If a closed logical grouping is useful, add the separately labelled class `standardized scarlet
(current reviewed set)` below `scarlet` and define that class as the union of the three reviewed
children. This view must be regenerated when the reviewed set changes. It is not the target for an
unqualified annotation. No sensu children are disjoint merely because their prototypes disagree;
their physical regions can overlap.

## Uniform definition templates

The umbrella definition is intentionally source-neutral:

> A colour quality that satisfies at least one documented source-specific operational sense
> conventionally designated “X”.

Each sensu class then supplies a recognition boundary:

> A colour quality recognized as X according to STANDARD by the specimen's closest match to
> DESIGNATION under the comparison conditions specified by that standard.

For Ridgway terms, the physical Ridgway chip is the prototype. Hamly's Munsell coordinate is an
approximate legacy conversion and must not replace the chip as the normative standard. For RHS,
the physical chart chips are normative; display RGB values are not. Prototype exemplars such as
fruit, petals, or dried culms are retained only in the source-specific class that states them.

Degree modifiers such as `deep`, `pale`, `light`, and `bright` are not synonyms of the umbrella or
sensu child. They require a separately defined modifier or a compound FLOPO phenotype.

## Existing-term migration

`PATO:0104031 cream` currently has the RHS fifth-edition 158A/158B operational definition. Preserve
that formal referent: rename it `cream sensu RHS Colour Chart fifth edition`, retain the definition,
and place it below a new generic `cream` colour umbrella. Move the unrestricted exact synonym
`creamy` to the generic umbrella. Existing annotations should be migrated to the generic class
unless their source actually named RHS 158A/158B.

`PATO:0001425 rosy` and `PATO:0001942 brown green`/`olive green` need separate semantic review
before being reused as the generic `rose` or `olive` umbrella. Their current definitions do not
encode the source splits in the evidence table. No source-specific child should inherit from a
core hue merely on lexical intuition; any red, pink, yellow, green, or brown parent must follow
from the operational region and be checked independently.

## Category exceptions

`silvery` and `golden` do not fit one pure-colour hierarchy. Saccardo's silver is white plus metallic
lustre, and his gold-yellow includes splendour; botanical uses can also arise from hairs, wax,
surface reflection, maturation, or drying. Keep their unqualified forms as FLOPO appearance
phenotypes or contextual terminology entries. A genuinely chromatic source value such as Ridgway
`Old Gold` may still be a source-qualified PATO colour, but it must not be made a subclass of a
FLOPO appearance phenotype. The terminology layer can relate these cross-category senses without
turning the lexical cluster into an ontology superclass.

Compound colours remain in FLOPO. Alternatives such as `greenish or pinkish` use a union; mixtures
use an explicit component relation and are not conjunctive subclasses of all component colours.

## Validation gates

Before proposing or materializing upstream terms:

1. Every sensu class has one named standard, designation, recognition rule, and resolvable source.
2. Every sensu colour is a subclass of exactly one generic lexical umbrella, unless it is recorded
   as a cross-category exception.
3. Unqualified annotations resolve to the umbrella; source-qualified annotations resolve to the
   matching child; degree-modified annotations do not collapse to either without composition.
4. Generic umbrellas remain open. Any named closed-union view lists exactly its reviewed children
   and is never used as the unqualified annotation target.
5. Sensu children are not asserted disjoint without measured non-overlap evidence.
6. Physical chips or stated prototypes remain normative; RGB renderings and Hamly conversions are
   not substituted for them.
7. Every proposed source-specific class passes positive closest-match examples, boundary examples,
   and counterexamples drawn from a different standard.
8. PATO and FLOPO reasoner checks find no new unsatisfiable class and no phenotype/quality category
   crossing.

## Evidence

- Saccardo, *Chromotaxia* (1891): `EVID:SACCARDO_CHROMOTAXIA`
- Ridgway, *Color Standards and Color Nomenclature* (1912): `EVID:RIDGWAY_1912`
- NIST SP 440 source-name concordance: `EVID:NIST_SP440`
- ISCC-NBS centroid paper: `EVID:NIST_CENTROIDS`
- UPOV/RHS comparison protocol: `EVID:UPOV_TGP14`
- Hamly's approximate Ridgway-to-Munsell key: DOI:10.1364/JOSA.39.000592

