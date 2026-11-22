# 00. Part and quality

**Intent.** The basic statement of a flora: a part of the plant has a quality.
**Wording.** "leaves glabrous", "petals white", "stem woody", "leaves 3-8 cm long".

Every other pattern adds to this one: a frequency, a range, a second part, a whole, a stage.

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0000453", "value_low": null, "value_high": null}
```

The bearer is a Plant Ontology part (leaf, PO:0025034); the quality is a PATO quality or a FLOPO
flora value (glabrous, PATO:0000453). A measurement adds the numbers and a UO unit: "leaves 3-8 cm
long" is leaf, length (PATO:0000122), 3 to 8, centimetre (UO:0000015).

## OWL

The class of the annotation is a *phene*: a quality of the plant, defined by a property of the
plant.

```
'flora phenotype' and 'phenotype of' some
    ('has part' some (leaf and 'has characteristic' some glabrous))
```

The inner expression, `'has part' some (leaf and 'has characteristic' some glabrous)`, is the
**defining property**: what a plant must be like to have this phenotype. It is written in the
Entity-Quality form of the phenotype ontologies [1]. A measurement puts the numbers in a data
range: `'has part' some (leaf and 'has characteristic' some (length and 'has measurement value'
some xsd:decimal[>= 3, <= 8] and 'has value unit' some centimeter))`. The other patterns change
the defining property only; the frame around it is always the same.

The frame is that of Hoehndorf, Oellrich and Rebholz-Schuhmann [11] (`Phene and phene-of some Y`)
and the second of the two readings that Gkoutos, Schofield and Hoehndorf [8] set out: a
phenotype class is either a class of organisms or a class of qualities of organisms, and a
resource should choose one. Until 2026-11-22 FLOPO classes were written as the defining property
alone (a class of plants), and the atlas classes as a mixture of the two.

`'phenotype of'` (RO:0002201) is **functional**, a phene belongs to one plant, and `'has
phenotype'` (RO:0002200) is its inverse. Two consequences:

* A plant that has the phene of Y is a Y. From `Taxon SubClassOf 'has phenotype' some C` for
  several classes C it follows that every plant of the taxon has all their defining properties
  at once, so "petals absent" and "petals white" in one taxon is a contradiction (pattern 15).
* The conjunction of two phenes of one plant is the phene of the conjunction of their defining
  properties.

Subsumption between phenes follows subsumption between their defining properties, and OWL 2 EL
(ELK) computes it: 'leaf glabrous' is under 'leaf phenotype' as before. The step from the phenes
of a plant to the plant needs the functional property and so a reasoner for all of OWL 2 DL; for
ELK it is stated once per class as the *bearer axiom* `'has phenotype' some C SubClassOf Y`
(`docs/phene-consistency.md`).

When the claim is strict and accepted by the checks (no "rarely", "about", "sometimes", no
specimen condition), the taxon is asserted to have the phenotype: `Taxon SubClassOf 'has
phenotype' some C`; a qualified claim stays a statement about the record (see "What goes into
OWL" in the introduction). Because FLOPO classes are defined the same way, a reasoner places the
class of the annotation under FLOPO's own classes: 'leaf glabrous', and the phenotype of every
part that leaves are part of. That is what lets the atlas answer "which taxa have glabrous
leaves" across all floras, whatever words each flora used.

## RDF

```turtle
<record> a fb:TraitRecord ; fb:taxon <taxon> ; fb:bearer obo:PO_0025034 ;
    fb:quality obo:PATO_0000453 ; fb:text "leaves glabrous" ; fb:source <flora> ;
    fb:phenotypeClass <annotation-class/FAC_...> .
```

The record keeps the words of the source (`fb:text`) beside the terms, so every annotation can be
checked against what the flora says. `fb:phenotypeClass` is the OWL class above; records with the
same content share one class.

## Related work

The Entity-Quality model of Mungall et al. [1] and its use for systematic characters by Dahdul et
al. [2] and Balhoff et al. [3]; the phene as the quality that a defining property gives its
bearer, with the functional relation to the bearer, in Hoehndorf et al. [11]; the two readings of
a phenotype class in the review [8].
