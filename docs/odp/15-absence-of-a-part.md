# 15. Absence of a part

**Intent.** The flora says that the plant does not have a part.
**Wording.** "petals absent", "stipules 0", "no stipules", "without a pappus", "leafless",
"exstipulate", "pétales nuls".

## Annotation

```json
{"po_id": "PO_0009032", "pato_id": "PATO_0000467", "negated": true, "negation_scope": "absence"}
```

The part (petal, PO:0009032) with the quality *present* (PATO:0000467), negated, and the scope of
the negation stated: the part is absent. "Absent", "no X", "without X" and the privative words
("leafless", "spineless") all become this one record. A part that is there but lacks a quality
("not fragrant", "never glaucous") is a different record: the same part with that quality and
`negation_scope: quality`.

## OWL

The expression below is the defining property of the class; the class itself is its phene,
`'flora phenotype' and 'phenotype of' some (...)` (pattern 00).

`not ('has part' some ('part of' some petal))`.

This is the form of Gkoutos, Schofield and Hoehndorf [8]. Absence is not a quality of a petal
that does not exist; it is the phene of plants that have no petal ("lacks-part phene" in [11]). With *part of* read as
reflexive and transitive, a plant that has no part of a petal has no petal, and a plant without
leaves is also a plant without leaf blades: "leaves absent" is a subclass of "leaf blade absent".
Until 2026-11-20 the atlas wrote `not ('has part' some (petal and 'has characteristic' some
present))`, which says nothing about the parts of the missing organ.

A qualified whole or a container stays with the part: "petals of male flowers absent" is
`not ('has part' some ('part of' some (petal and 'part of' some (flower and 'has characteristic'
some male))))`.

"Petals absent" and "petals white" in one taxon contradict each other: the taxon has both
phenes, `'phenotype of'` is functional, so one plant would have a white petal and no part of a
petal. A reasoner for all of OWL 2 DL finds this directly, one taxon at a time
(`tools/PheneTaxonConsistency.java`, HermiT; `docs/phene-consistency.md`).

Negation and functional properties are outside OWL 2 EL, and ELK passes over them. The class is
kept as written, and the question is put to ELK in another form
(`flopo2.verify.annotation_class_check`): every class C with defining property Y gets the bearer
axiom `'has phenotype' some C SubClassOf Y`; an absence class gets `'has phenotype' some C
SubClassOf M` with a marker class M that is disjoint with the presence, `'has part' some ('part
of' some petal)`. OWL EL cannot say that *part of* is reflexive, so the check states it for each
absent part (`petal SubClassOf 'part of' some petal`). "Petals absent" then contradicts "petals
white" and also "petal claw short", and both statements of that taxon are set to review
(`contradiction_within_taxon`).

## RDF

```turtle
<record> fb:bearer obo:PO_0009032 ; fb:quality obo:PATO_0000467 ; fb:negated true ;
    fb:text "petals absent" ; fb:phenotypeClass <annotation-class/FAC_...> .
```

## Rules

| Rule | Layer | Statement |
|---|---|---|
| `negation_scope` required | data model | a negated record says whether the part or the quality is denied |
| shape `AbsenceOfAPart` | ShEx | quality present, negated, no number |
| `contradiction_within_taxon` | ELK (bearer axioms); HermiT per taxon | the absent part, or a part of it, is not described in the same taxon |

## Related work

The review [8] gives the form and the reason for it: the absence of a whole should imply the
absence of its parts, which needs negation and therefore an expressive fragment of OWL. Loebe et
al. (Towards improving phenotype representation in OWL, *Journal of Biomedical Semantics* 2012;
3(Suppl 2):S5) compare the ways of writing absence. PATO's *absent* (PATO:0000462) as a quality
of the missing part, the form of the model-organism annotations (Mungall et al. [1]), is not
used: nothing bears the quality.

## Limits

A frequency keeps the record out of OWL as for every pattern ("stipules usually absent" is a
record only). "Petals absent" in a taxon whose flowers are described as "petals 5 in male
flowers" is flagged as a contradiction unless the flora's statement carries its condition.
Parts that the Plant Ontology does not place under the absent organ by *part of* are not
reached: a scar left by a fallen stipule is not part of a stipule.
