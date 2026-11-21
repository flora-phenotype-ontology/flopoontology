# 17. Value defined by a measure

**Intent.** A value word of a flora stands for a range on a scale. The range is written down once, with its source, so that a word and a measurement of the same organ can be compared, and so that it is known which words are neighbours and which exclude each other.
**Wording.** "lanceolate" for a range of length to width, "acute" for a range of angles, "opposite" for two parts at a node.

This is a pattern for defining value classes, not for annotating a statement: no record carries
it, and the annotator does not use it. The classes and relations are temporary FLOPO terms; they
were proposed to PATO in https://github.com/pato-ontology/pato/pull/629.

## Definition

A *value defined by a measure* is a value class Q for which a named source gives a condition C on
a count, or on a measurable attribute of the same bearer, such that every bearer that satisfies C
has Q. C is the *core* of Q. The core says when the word certainly applies. It does not say that
the word is never used outside it.

## Relations

| Relation | Kind | Definition | Axioms |
|---|---|---|---|
| has number of parts per node FLOPO:0995001 | data property | A relation between an arrangement quality of an axis and the number of parts of one kind that the axis bears at each of its nodes. The kind of part is the second entity of the quality (RO:0002503 *towards*). Source: Ellis et al. [9], character 2. | functional; domain quality PATO:0000001; range integers of 1 or more |
| has number of rows FLOPO:0995002 | data property | A relation between a spatial pattern quality of a structure and the number of rows, series or whorls in which the members of that structure are arranged. | functional; domain quality; range integers of 1 or more |
| has neighbouring value FLOPO:0995003 | annotation property | A relation between two value classes that are defined by ranges on the same scales, whose ranges do not overlap, meet at a common bound on exactly one scale (or are consecutive counts) and overlap on every other scale, so that a small change of one measured attribute turns the one value into the other. | symmetric by statement in both directions; derived from the ranges, never asserted by hand; not between a range and one inside it |
| has phenotype magnitude `flopoann:has_magnitude` | data property | The inherent numerical magnitude used in a quantitative phenotype class description; not a measurement result. (The property of patterns 02 and 11.) | functional; range decimal |
| has characteristic RO:0000053, towards RO:0002503 | object properties | as in the Relation Ontology; *towards* connects a relational quality to its second entity [1] | |

The lower bound of the two counts is stated in the bridge file only, because OWL 2 EL has no
facets. A count of 0 parts per node is then unsatisfiable.

| Attribute class | Parent | Definition (source: Ellis et al. [9]) |
|---|---|---|
| length to width ratio FLOPO:0995010 | ratio PATO:0001470 | A ratio quality inhering in a flat bearer by virtue of the bearer's length divided by its greatest width measured at right angles to its long axis. (Character 9.) |
| relative position of the widest point FLOPO:0995011 | position PATO:0000140 | A position quality inhering in a flat bearer by virtue of the distance from the bearer's base to its zone of greatest width, as a fraction of the bearer's length. (Character 10.) |
| apex angle FLOPO:0995012 | angle PATO:0002326 | An angle quality inhering in a flat bearer by virtue of the angle, in degrees, between the two rays that leave the end of the bearer's midvein at its apex and are tangent to its margins, measured on the proximal side. (Character 16.) |
| base angle FLOPO:0995013 | angle PATO:0002326 | An angle quality inhering in a flat bearer by virtue of the angle, in degrees, between the two rays that leave the point where the bearer's lowest laminar tissue joins its stalk and are tangent to its margins, measured on the distal side. (Character 18.) |

## OWL

**Form A: the value is a count.** The count belongs to the quality itself; the definition is an
equivalence.

`'alternate placement' EquivalentTo ('has number of parts per node' value 1)`

`opposite EquivalentTo ('has number of parts per node' value 2)`

`whorled EquivalentTo ('has number of parts per node' some integer[>= 3])`

Source: Ellis et al. [9], 2.1 "with one leaf per node", 2.3 "opposed pairs that arise from the
same node", 2.4 "Three or more leaves are borne at each node". Likewise uniseriate, biseriate and
multiseriate with 'has number of rows' 1, 2, and 3 or more. A reasoner then finds without a
further axiom that opposite and whorled exclude each other. With pattern 16 the bearer of these
qualities is the axis: `'shoot axis' and 'has characteristic' some (opposite and towards some leaf)`.

**Form B: the value follows from an attribute of the same bearer.** The number belongs to an
attribute quality of the bearer, in the form the annotations use for numbers (patterns 02 and
11). The definition is a sufficient condition between two phenotypes of one bearer:

`('has characteristic' some ('length to width ratio' and 'has phenotype magnitude' some decimal[>= 3, < 10])) and ('has characteristic' some ('relative position of the widest point' and 'has phenotype magnitude' some decimal[<= 0.4])) SubClassOf 'has characteristic' some lanceolate`

| Value | Core | Ellis et al. [9] | Systematics Association 1962 [10] |
|---|---|---|---|
| linear PATO:0001199 | length:width 10 or more | 10.5 "The L:W ratio of a leaf is ≥10:1, regardless of the position of the widest part" | figure 12, *linearis*: oblong series (parallel sides) at 12:1 |
| ovate FLOPO:0991024 | widest point at 0.4 or below; length:width below 10 | 10.3 "The widest part of the leaf is in the proximal two-fifths" | figures 38-39, *ovatus*: widest at one third from the base, 2:1 to 3:2 |
| lanceolate PATO:0001877 | as ovate; length:width 3 to below 10 | 10.3 "We suggest defining lanceolate leaves as ovate leaves with a L:W ratio between 3:1 and 10:1" | not in the chart (see below); figures 36-37 *anguste ovatus*, 6:1 to 3:1 |
| elliptic PATO:0000947 | widest point between 0.4 and 0.6; length:width above 1.2 and below 10 | 10.1 "The widest part of the leaf is in the middle one-fifth" | figures 3-4, *ellipticus*: 2:1 to 3:2 |
| orbicular PATO:0001934 | as elliptic; length:width 1 to 1.2 | 10.1 "orbiculate for elliptic leaves with a L:W ratio ranging from 1.2:1 to 1:1" | figure 6, *circularis*, 1:1; "we prefer circularis" |
| oblate PATO:0000409 | as elliptic; length:width below 1 | 10.1 "oblate for elliptic leaves with a L:W ratio <1:1" | rejected; *transverse late ellipticus*, 5:6 |
| obovate PATO:0001936 | widest point at 0.6 or above; length:width below 10 | 10.2 "The widest part of the leaf is in the distal two-fifths" | figures 47-48, *obovatus*: widest at one third from the apex, 2:1 to 3:2 |
| oblanceolate PATO:0002330 | as obovate; length:width 3 to below 10 | 10.2 "obovate leaves with a L:W ratio between 3:1 and 10:1" | not in the chart; figures 45-46 *anguste obovatus* |
| acute FLOPO:0991095 | apex or base angle below 90° | 16 "Acute - Apex angle <90°"; 18 "Acute - Angle <90°" | not treated |
| obtuse PATO:0001935 | apex or base angle 90° to below 180° | 16 "Obtuse - Apex angle between 90° and 180°"; 18 | not treated |

The axioms are those of the manual [9], one consistent source. The upper limit of 10 for ovate,
elliptic and obovate is ours: it follows from 10.5, by which a blade of 10:1 or more is linear
wherever it is widest. The reading of the chart [10] is recorded with each class as an annotation.

The chart was read in full on 2026-11-21. It gives each series (elliptic, oblong, rhombic, ovate,
obovate, trullate, obtrullate, triangular, obtriangular) the same columns of length to breadth:
12:1 (*linearis*, only for parallel-sided and triangular shapes), 6:1 to 3:1 (*anguste*,
narrowly), 2:1 to 3:2 (the plain name), 6:5 (*late*, broadly), 1:1, and the transverse shapes;
"each term covers all the figures corresponding with all the ratios contained within the interval
characteristic of the column" (p. 146). On lanceolate the committee wrote: "one term,
*lanceolatus*, has been so variously used (principally for figures 2 and 37) that we are not even
sure under which series we should discuss it. It has become so imprecise in meaning that we have
had to eliminate it from this scheme" (p. 146). Figure 2 is narrowly elliptic, figure 37 narrowly
ovate. The two sources agree that a lanceolate blade is 3:1 or narrower; they disagree on whether
it must be widest below the middle, and on where linear begins (10:1 or 12:1).

## What is an axiom and what is a note

| | Form |
|---|---|
| core, from the manual [9] | axiom (equivalence in form A, sufficient condition in form B), annotated with `dct:source` |
| reading of the 1962 chart [10] | annotation `secondReading` |
| the range floras use | annotation `observedRange` |
| neighbour on the scale | annotation *has neighbouring value* (linear - lanceolate; lanceolate - elliptic; opposite - whorled; 20 pairs) |
| text definition proposed to PATO | annotation `proposedDefinition` with `dct:source` |

The cores are sufficient conditions only, for two reasons. The 1962 committee found the usage of
"lanceolate" too wide for one definition. And the floras do not keep to the cores: in 27,591
descriptions that give a blade length, a width and one shape word (99,412 annotated descriptions,
2026-11-21), "lanceolate" has a median length:width of 5.0 with 59% between 3 and 10, 23% below 3
and 18% at 10 or more; "linear" a median of 17.3 with 72% at 10 or more; "elliptic" 2.4;
"obovate" 2.1; "orbicular" 1.2. A necessary condition would make a fifth of the "lanceolate"
statements contradictions.

## Files

| File | Content |
|---|---|
| `tools/build_flopo_value_space_extension.py` | the one specification: relations, attribute classes, cores, sources; derives the neighbours |
| `ontology/flopo-value-space-extension.ttl` | OWL 2 EL: the temporary classes and relations with definitions, and the neighbours; embedded in `flopo.owl` by `tools/update_flopo_value_space_release.py` |
| `ontology/flopo-value-ranges.ofn` | OWL 2 DL bridge with the numeric axioms; not imported by `flopo.owl`, because ELK passes over data ranges |

## Rules

| Rule | Layer | Statement |
|---|---|---|
| generated files equal the specification | test | `tests/test_flopo_value_ranges.py` |
| every temporary class and relation has a definition, a source and a parent or domain | test | the same |
| neighbours are those the ranges give, in both directions | test | the same |
| a measurement or count classifies under the value word; two counts exclude each other | HermiT through `tools/robot.jar` | probe classes in `tests/data/flopo-value-ranges-probe.ofn` |

The probes: a bearer with length:width 4 and widest point at 0.3 is lanceolate and ovate; one
"12-20 times as long as wide" is linear; one "2-3 times as long as wide" is neither linear nor
lanceolate (the ratio alone does not say where the blade is widest); an apex angle of 60° is
acute and a base angle of 120° obtuse; an axis with 2 parts per node is opposite and one with 4
whorled; opposite and whorled together, and 0 parts per node, are unsatisfiable.

## Related work

PATO defines these values in words without numbers (*lanceolate*: "considerably longer than
wide, tapering towards the tip from below the middle"). It once had relations for magnitudes
(`has_ratio_quality`, `is_magnitude_of`), now obsolete. Colour in FLOPO already has the shape of
this pattern: the ISCC-NBS backbone classes carry Munsell hue, value and chroma ranges as
annotations (FLOPO:0988900-0988906, `ontology/flopo-colour-backbone.ttl`).

## Limits

Only blade shape, apex and base angle, parts per node and rows are covered. The values were
entered by hand from [9] and [10]; no language model was used. Oblong ([9] 10.4, "margins roughly
parallel for at least the middle one-third") needs a third attribute. Leaf size classes ([9],
character 8, after Webb 1959) are defined by area but are not words of the floras. The position of
the widest point is never stated in a flora, so form B connects text to measurements from images
or specimens; text to text it works only through the length to width ratio (pattern 11).
