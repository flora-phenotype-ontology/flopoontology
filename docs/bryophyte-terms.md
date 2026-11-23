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

## Which description is one of a moss

Not the source. The source "Moss Flora of China" is not a flora that eFloras marks as such: the
eFloras export has only a name and a text per row, and the rows were sorted into floras by words
in the text. Every row with "Leaves ... capsule / spores / costa" that was not from the Flora of
China, of North America or of Pakistan went to the moss flora. So it held about 100 descriptions
of sedges, ferns, poppies and aroids (a sedge utricle has a "costa", a fern has "spores").

`is_bryophyte(family, text)` decides instead:

- the family is one of the bryophyte families, or
- there is no family and the text has a word that only a moss description has (exostome,
  endostome, alar cells, perichaetial, autoicous, ...) or two of seta, peristome, calyptra,
  gemmae, dioicous (one is not enough: a pitcher plant has a peristome, a eucalypt a calyptra), or
- the family is that of a vascular plant but the text has four or more of these words.

A family of bryophytes does not count where the text has a word of the seed plants (spikelet,
glume, petal, anther, seed, ...) and no moss word: the family is taken from the genus, and the
grass *Microstegium* stood under the moss family Funariaceae in a list of genera.

The last case of the list is a name that two plants share. Names are matched without their author, and
*Girgensohnia* is a moss (Bruch & Schimper) and an amaranth (Bunge): the moss description of
*Girgensohnia ruthenica* was attached to the amaranth.

What follows from it:

- a description in the moss flora that is not one of a bryophyte is left out of that source
  (`misfiled`); the same text is in "eFloras Other", where it is now kept instead of being counted
  as a copy. The ingest (`flopo2/ingest/external.py`) applies the same rule to new runs;
- the name matching is told the group (`Builder.taxon(..., bryophyte=...)`). A moss is never
  matched to the checklist of vascular plants, and a match of the other group from World Flora
  Online is not used. The taxon is then known by its printed name, apart from the other plant;
- the same the other way round: a flowering plant whose name the service gives to a moss (one
  Malvaceae taxon stood under Hypnales).

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
- A moss whose name is shared with a flowering plant is known by its printed name only; it has
  no identifier from World Flora Online until names are matched with their authors.
- The family list has the families the atlas has seen; a new flora may bring others.
