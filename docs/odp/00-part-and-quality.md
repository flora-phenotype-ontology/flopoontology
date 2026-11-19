# 00. Part and quality

**Intent.** The basic statement of a flora: a part of the plant has a quality.
**Wording.** "leaves glabrous", "petals white", "stem woody", "leaves 3-8 cm long".

Every other pattern adds to this one: a frequency, a range, a second part, a whole, a stage.

## Annotation

```json
{"po_id": "PO_0025034", "pato_id": "PATO_0000452", "value_low": null, "value_high": null}
```

The bearer is a Plant Ontology part (leaf, PO:0025034); the quality is a PATO quality or a FLOPO
flora value (glabrous, PATO:0000452). A measurement adds the numbers and a UO unit: "leaves 3-8 cm
long" is leaf, length (PATO:0000122), 3 to 8, centimetre (UO:0000015).

## OWL

The annotation is a class of plants, written in the Entity-Quality form of the phenotype
ontologies [1]: `has part some (leaf and has characteristic some glabrous)`. A measurement puts
the numbers in a data range: `has part some (leaf and has characteristic some (length and has
measurement value some xsd:decimal[>= 3, <= 8] and has value unit some centimeter))`.

When the claim is strict and accepted by the checks (no "rarely", "about", "sometimes", no
specimen condition), the taxon is asserted to be a subclass of this class; a qualified claim stays
a statement about the record (see "What goes into OWL" in the introduction). Because FLOPO classes are defined the same
way, a reasoner places the taxon under FLOPO's own classes: a taxon with glabrous leaves is a
'leaf glabrous' phenotype, and also a phenotype of every part that leaves are part of. That is
what lets the atlas answer "which taxa have glabrous leaves" across all floras, whatever words
each flora used.

## RDF

```turtle
<record> a fb:TraitRecord ; fb:taxon <taxon> ; fb:bearer obo:PO_0025034 ;
    fb:quality obo:PATO_0000452 ; fb:text "leaves glabrous" ; fb:source <flora> ;
    fb:phenotypeClass <annotation-class/FAC_...> .
```

The record keeps the words of the source (`fb:text`) beside the terms, so every annotation can be
checked against what the flora says. `fb:phenotypeClass` is the OWL class above; records with the
same content share one class.

## Related work

The Entity-Quality model of Mungall et al. [1] and its use for systematic characters by Dahdul et
al. [2] and Balhoff et al. [3].
