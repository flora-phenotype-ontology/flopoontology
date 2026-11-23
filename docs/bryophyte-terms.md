# Mosses, liverworts and hornworts: the plant parts

Marco Schmidt and Claus Weiland pointed out (23 Nov 2026) that the atlas has a moss flora and that
the organs of the vascular plants do not occur in mosses. The mosses stay; what was wrong is fixed.

## What was wrong

A flora describes a moss with the words of the vascular plants: "leaves", "stem", "capsule". The
annotator grounds the word alone. In the Moss Flora of China (1,429 taxa, 39,234 records):

| Flora word | Was annotated as | Records | Right? |
|---|---|---|---|
| leaf | leaf (PO:0025034) | 9,799 | correct but too general |
| capsule | capsule fruit (PO:0030091), a fruit type | 3,448 | wrong |
| stem | stem (PO:0009047) | 2,371 | correct but too general |
| seta, peristome tooth, costa, operculum, calyptra, rhizoid | the PO class of that name | about 7,000 | correct |
| sepal, petal, seed, fruit, inflorescence, ... | the seed-plant organ | about 2,400 | wrong |

The Plant Ontology covers bryophytes. It has the three classes that were thought missing:
non-vascular leaf PO:0025075 (exact synonym "phyllid"), gametophore axis PO:0030020 (exact
synonyms "caulid", "cauloid") with gametophore stem PO:0030022, and rhizoid PO:0030078. The moss
capsule is the sporangium PO:0025094 (exact synonyms "moss capsule", "spore capsule").

## What is done

`flopo2/verify/apply_bryophyte_terms.py`, with two tables:

- `config/bryophyte_families.tsv`: 171 families of mosses, liverworts and hornworts (those of the
  atlas, by their order in World Flora Online);
- `config/po_bryophyte_terms.tsv`: what happens to a part in a taxon of these families.

| Part | In a bryophyte |
|---|---|
| leaf | non-vascular leaf PO:0025075 |
| stem | gametophore stem PO:0030022 |
| branch | gametophore branch PO:0030021 |
| capsule fruit | sporangium PO:0025094 |
| flower, fruit, seed, inflorescence, root, vascular leaf, pollen, ovule, and their parts | review, reason `bearer_outside_plant_group` |

The Moss Flora of China is treated as bryophytes throughout: some of its names were matched to a
vascular plant of the same name and carry that plant's family.

Where the new part is a kind of the old one (a non-vascular leaf is a leaf), the FLOPO class of
the record stays, since it still holds. For the capsule the FLOPO class is dropped until FLOPO has
one for the sporangium.

The site has a section "Spore capsule and spores" for the capsule, seta, calyptra, peristome,
operculum and the spores (of mosses and of ferns).

## Open

- "leaf margin", "leaf apex", "leaf lamina" and "leaf base" are kept: PO defines them as parts of
  a leaf, and a non-vascular leaf is a leaf.
- "perianth" in a liverwort is a real structure but not the perianth of a flower; these records
  go to review with the other flower parts.
- Moss names matched to a vascular plant of the same name (94 taxa of the moss flora) are a fault
  of the name matching and are not fixed here.
- The family list has the families the atlas has seen; a new flora may bring others.
