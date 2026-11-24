# Cross-Flora FLOPO Ontology Addition Candidates

This report aggregates candidate value terms (`FLOPO:0991xxx`), missing anatomical bearers,
and novel `PO × PATO/FLOPO` combinations across all processed floras.

## Per-Flora Overview

| Source | Flora | Records | Extracted Rows | Assertions | Value Candidates | Bearer Candidates | Novel Combinations |
|---|---|---:|---:|---:|---:|---:|---:|
| [`africa-tree-db`](africa-tree-db/CANDIDATES.md) | Africa Tree Database (ATDB) | 642 | 17,876 | 15,519 | 28 | 11 | 176 |
| [`eflora-andes`](eflora-andes/CANDIDATES.md) | Trees and Shrubs of the Andes of Ecuador & Flora of Chile (eFloras) | 13 | 669 | 476 | 14 | 2 | 32 |
| [`eflora-fna`](eflora-fna/CANDIDATES.md) | Flora of North America North of Mexico (eFloras) | 11,192 | 503,751 | 373,014 | 2,121 | 610 | 8,610 |
| [`eflora-foc`](eflora-foc/CANDIDATES.md) | Flora of China (eFloras) | 34,180 | 1,686,089 | 1,230,030 | 3,008 | 1,100 | 17,810 |
| [`eflora-fom`](eflora-fom/CANDIDATES.md) | Steyermark's Flora of Missouri (eFloras) | 31 | 1,735 | 1,117 | 21 | 4 | 154 |
| [`eflora-fop`](eflora-fop/CANDIDATES.md) | Flora of Pakistan (eFloras) | 3,578 | 133,523 | 109,628 | 773 | 183 | 4,525 |
| [`eflora-mfoc`](eflora-mfoc/CANDIDATES.md) | Moss Flora of China (eFloras) | 1,655 | 70,314 | 39,234 | 581 | 241 | 2,246 |
| [`eflora-other`](eflora-other/CANDIDATES.md) | eFloras Additional Floras (Missouri, Moss Flora of China, Andean) | 3,888 | 147,723 | 95,435 | 1,056 | 384 | 5,331 |
| [`fdac`](fdac/CANDIDATES.md) | Flore d'Afrique Centrale (Meise Botanic Garden) | 6,570 | 428,692 | 309,305 | 1,908 | 458 | 8,299 |
| [`fdac-genera`](fdac-genera/CANDIDATES.md) | Flore du Congo Belge et du Ruanda-Urundi — Genera (Meise Botanic Garden) | 891 | 42,896 | 30,834 | 650 | 98 | 2,402 |
| [`feis-plants`](feis-plants/CANDIDATES.md) | USFS Fire Effects Information System (FEIS) — Plant Species | 849 | 17,165 | 13,761 | 236 | 54 | 573 |
| [`flora-gabon`](flora-gabon/CANDIDATES.md) | Flore du Gabon (FlorML) | 3,112 | 182,980 | 132,283 | 1,242 | 319 | 6,209 |
| [`flora-guianas`](flora-guianas/CANDIDATES.md) | Flora of the Guianas (FlorML) | 1,162 | 65,650 | 50,801 | 345 | 72 | 2,093 |
| [`flora-malesiana`](flora-malesiana/CANDIDATES.md) | Flora Malesiana (FlorML) | 2,992 | 183,550 | 125,893 | 740 | 255 | 3,716 |
| [`flora-zimbabwe`](flora-zimbabwe/CANDIDATES.md) | Flora of Zimbabwe (Hyde, Wursten, Ballings & Coates Palgrave) | 5,186 | 108,241 | 84,720 | 606 | 154 | 3,585 |
| [`illinois-wildflowers`](illinois-wildflowers/CANDIDATES.md) | Illinois Wildflowers (John Hilty) | 1,233 | 58,441 | 47,793 | 233 | 77 | 1,732 |
| [`kew-african`](kew-african/CANDIDATES.md) | Flora of Tropical East Africa (Royal Botanic Gardens, Kew; database export of 2014) | 12,104 | 524,005 | 424,478 | 1,752 | 550 | 10,066 |
| [`korup-flora`](korup-flora/CANDIDATES.md) | Vascular Plants of Korup National Park (Cameroon) | 129 | 6,736 | 5,559 | 62 | 9 | 430 |
| [`nybg-naf`](nybg-naf/CANDIDATES.md) | North American Flora Monographs (New York Botanical Garden) | 10,895 | 454,400 | 355,677 | 1,784 | 349 | 6,542 |
| [`phytokeys`](phytokeys/CANDIDATES.md) | PhytoKeys Botanical Taxonomic Monographs (Pensoft) | 283 | 24,012 | 18,109 | 179 | 71 | 1,312 |
| [`plants-tibet`](plants-tibet/CANDIDATES.md) | Plants of Tibet (Flora Xizangica / Tibetan Plateau) | 443 | 23,809 | 18,356 | 145 | 36 | 1,477 |
| [`plazi`](plazi/CANDIDATES.md) | Plazi / Pensoft / BHL Open-Access Taxonomic Treatments (Zenodo BLR) | 562 | 33,729 | 25,069 | 396 | 108 | 2,231 |
| [`powo-cate`](powo-cate/CANDIDATES.md) | CATE Araceae & Palmweb Monocot Monographs (via Kew POWO) | 111 | 9,241 | 5,586 | 122 | 28 | 705 |
| [`powo-cayman`](powo-cayman/CANDIDATES.md) | Flora of the Cayman Islands (via Kew POWO) | 168 | 4,064 | 3,291 | 33 | 4 | 241 |
| [`powo-fiq`](powo-fiq/CANDIDATES.md) | Flora of Iraq (via Kew POWO) | 82 | 3,543 | 2,543 | 31 | 4 | 168 |
| [`powo-fsom`](powo-fsom/CANDIDATES.md) | Flora of Somalia (via Kew POWO) | 231 | 7,583 | 6,302 | 45 | 10 | 388 |
| [`powo-ftea`](powo-ftea/CANDIDATES.md) | Flora of Tropical East Africa (via Kew POWO) | 807 | 45,518 | 36,592 | 275 | 59 | 2,075 |
| [`powo-fwta`](powo-fwta/CANDIDATES.md) | Flora of West Tropical Africa (via Kew POWO) | 354 | 2,323 | 1,944 | 20 | 2 | 94 |
| [`powo-fz`](powo-fz/CANDIDATES.md) | Flora Zambesiaca (via Kew POWO) | 765 | 46,380 | 36,811 | 309 | 58 | 2,110 |
| [`powo-grassbase`](powo-grassbase/CANDIDATES.md) | GrassBase — The Online World Grass Flora (RBG Kew via POWO) | 73 | 6,796 | 4,787 | 40 | 25 | 265 |
| [`powo-ildis`](powo-ildis/CANDIDATES.md) | ILDIS World Database of Legumes (via Kew POWO) | 394 | 1,207 | 1,180 | 1 | 0 | 1 |
| [`powo-kew`](powo-kew/CANDIDATES.md) | Kew Monographs & Databases (Kew Bulletin, GrassBase, ILDIS, CATE via POWO) | 395 | 22,080 | 14,871 | 222 | 61 | 1,448 |
| [`powo-neotropical`](powo-neotropical/CANDIDATES.md) | Neotropical & Colombian Floras (CPLC, UPFC, UPB, Neotropikey via POWO) | 3,855 | 6,316 | 5,519 | 3 | 0 | 10 |
| [`powo-tong`](powo-tong/CANDIDATES.md) | Trees of New Guinea (via Kew POWO) | 206 | 8,820 | 6,193 | 116 | 23 | 532 |
| [`silvics-na`](silvics-na/CANDIDATES.md) | Silvics of North America (USFS Agriculture Handbook 654) | 184 | 2,890 | 1,766 | 65 | 13 | 136 |
| [`smithsonian-botany`](smithsonian-botany/CANDIDATES.md) | Smithsonian Contributions to Botany (NMNH Taxonomic Monographs) | 1,383 | 48,948 | 32,100 | 498 | 240 | 2,017 |
| [`usda-plants`](usda-plants/CANDIDATES.md) | USDA NRCS PLANTS Database — Botanical Descriptions | 678 | 15,003 | 12,370 | 191 | 20 | 686 |
| [`wfo`](wfo/CANDIDATES.md) | World Flora Online Species Descriptions (WFO) | 111,454 | 4,656,458 | 3,457,622 | 75,077 | 9,660 | 38,696 |

## Top Cross-Flora Value Term Candidates

Ranked first by number of floras in which the term is needed, then by total occurrences.

| Quality word | Floras | Total Count | Suggested PATO parent | Top Bearers |
|---|---:|---:|---|---|
| `round` | 30 | 1,039 | `PATO:0000141` (structure) | `PO_0009010|PO_0025359|PO_0005656|PO_0025017` |
| `compound` | 29 | 1,303 | `PATO:0000141` (structure) | `PO_0009049|PO_0020039|annulus|synflorescence` |
| `scale-like` | 28 | 1,511 | `PATO:0000052` (shape) | `PO_0004518|PO_0025393|PO_0009047|PO_0004542` |
| `distinct` | 27 | 2,379 | `PATO:0001435` (attachment quality) | `PO_0025034|PO_0020039|PO_0009035|PO_0020104` |
| `tufted` | 26 | 1,154 | `PATO:0000060` (spatial pattern) | `PO_0025034|FLOPO_0985026|PO_0009005|PO_0004542` |
| `stalked` | 25 | 2,531 | `PATO:0000141` (structure) | `FLOPO_0985027|PO_0020049|FLOPO_0985028|PO_0025034` |
| `naked` | 25 | 1,364 | `PATO:0000141` (structure) | `PO_0009064|PO_0009032|rachis|PO_0020038` |
| `thin-walled` | 24 | 2,276 | `PATO:0000141` (structure) | `cell|PO_0009002|PO_0009001|PO_0009084` |
| `fine` | 24 | 822 | `PATO:0000141` (structure) | `PO_0025034|PO_0005020|PO_0025393|PO_0000282` |
| `marked` | 24 | 701 | `PATO:0000141` (structure) | `PO_0009032|PO_0009059|PO_0009046|PO_0020039` |
| `separate` | 24 | 592 | `PATO:0000052` (shape) | `PO_0025359|PO_0009049|PO_0030117|PO_0020049` |
| `thick-walled` | 22 | 2,266 | `PATO:0000141` (structure) | `cell|PO_0009002|PO_0025034|basal cell` |
| `well developed` | 22 | 898 | `PATO:0000141` (structure) | `PO_0030043|PO_0025034|PO_0009038|PO_0030042` |
| `abundant` | 22 | 398 | `PATO:0000141` (structure) | `PO_0009049|scale|PO_0025393|PO_0000282` |
| `well-developed` | 22 | 357 | `PATO:0000141` (structure) | `PO_0025034|PO_0020041|annulus|PO_0009028` |
| `double` | 21 | 1,290 | `PATO:0000141` (structure) | `PO_0030042|PO_0030072|PO_0025393|PO_0025359` |
| `pungent` | 21 | 981 | `PATO:0001331` (odor) | `PO_0025034|PO_0020039|callus|PO_0009055` |
| `delicate` | 21 | 772 | `PATO:0000052` (shape) | `PO_0000003|PO_0025034|PO_0009047|PO_0009049` |
| `parallel` | 21 | 549 | `PATO:0000141` (structure) | `PO_0009001|PO_0009066|PO_0009032|PO_0009069` |
| `low` | 21 | 513 | `PATO:0000141` (structure) | `FLOPO_0986125|PO_0025166|PO_0025352|FLOPO_0986025` |
| `tough` | 21 | 457 | `PATO:0000141` (structure) | `PO_0009047|PO_0004542|PO_0020039|PO_0025034` |
| `confluent` | 21 | 368 | `PATO:0000141` (structure) | `PO_0009066|PO_0009073|PO_0005020|PO_0025166` |
| `strong` | 20 | 736 | `PATO:0000141` (structure) | `PO_0030072|PO_0025034|FLOPO_0986075|PO_0025172` |
| `oblong-ovate` | 20 | 632 | `PATO:0000052` (shape) | `PO_0009031|PO_0009032|PO_0020039|PO_0025034` |
| `bilocular` | 20 | 376 | `PATO:0000141` (structure) | `PO_0009072|PO_0009066|PO_0009001|PO_0025263` |
| `massive` | 20 | 165 | `PATO:0000141` (structure) | `PO_0004542|PO_0009049|PO_0009047|annulus` |
| `high` | 20 | 149 | `PATO:0000141` (structure) | `FLOPO_0986064|PO_0025166|FLOPO_0986025|PO_0000003` |
| `ovate-lanceolate` | 19 | 2,139 | `PATO:0000052` (shape) | `PO_0009055|PO_0009031|PO_0025034|PO_0020039` |
| `bidentate` | 19 | 733 | `PATO:0000052` (shape) | `beak|PO_0009031|PO_0025034|PO_0009059` |
| `diverging` | 19 | 413 | `PATO:0000141` (structure) | `PO_0025517|PO_0009074|PO_0005020|PO_0025034` |
| `unilocular` | 19 | 355 | `PATO:0000141` (structure) | `PO_0009072|PO_0009001|PO_0009066|PO_0030091` |
| `leafless` | 19 | 236 | `PATO:0000141` (structure) | `PO_0009049|PO_0009053|PO_0003024|PO_0025034` |
| `ringed` | 19 | 141 | `PATO:0000141` (structure) | `PO_0025034|FLOPO_0986077|PO_0009001|PO_0009047` |
| `epipetalous` | 19 | 134 | `PATO:0000141` (structure) | `PO_0009029|PO_0009077|PO_0009067|PO_0009066` |
| `stilt` | 19 | 70 | `PATO:0000141` (structure) | `PO_0009005` |
| `developed` | 18 | 745 | `PATO:0000141` (structure) | `annulus|PO_0009047|PO_0025034|PO_0025060` |
| `densely flowered` | 18 | 579 | `PATO:0000060` (spatial pattern) | `PO_0009049|PO_0030117|PO_0025073|PO_0030115` |
| `purple-tinged` | 18 | 423 | `PATO:0000141` (structure) | `PO_0009047|PO_0009059|PO_0009045|PO_0009055` |
| `tinged` | 18 | 299 | `PATO:0000141` (structure) | `PO_0009032|PO_0009059|PO_0009046|FLOPO_0985017` |
| `radiate` | 18 | 257 | `PATO:0000052` (shape) | `PO_0009046|PO_0020039|oral seta|PO_0000282` |

## Top Cross-Flora Anatomical Bearer Candidates

| Bearer word | Floras | Total Count | Top Qualities |
|---|---:|---:|---|
| `thyrse` | 21 | 221 | `present|amount|length|simple` |
| `primary branch` | 14 | 86 | `amount|length|diameter|opposite` |
| `thyrsus` | 14 | 74 | `present` |
| `pseudostaminode` | 13 | 206 | `dentate|fimbriate|length|oblong` |
| `antherode` | 13 | 152 | `length|sagittate|dehiscent|slender` |
| `dichasia` | 13 | 62 | `present|amount|sessile|simple` |
| `basal leave` | 12 | 560 | `amount` |
| `cell wall` | 12 | 337 | `thick|thickened|pitted|thin` |
| `nerved` | 11 | 40 | `amount` |
| `marginal cell` | 10 | 484 | `length|amount|linear|width` |
| `smaller` | 10 | 35 | `amount` |
| `veined` | 10 | 21 | `amount|present` |
| `verticillate` | 10 | 19 | `present|amount` |
| `basal cell` | 9 | 1,691 | `length|width|smooth|rectangular` |
| `marginal vein` | 9 | 547 | `amount|present|arched|straight` |
| `corolla throat` | 9 | 208 | `length|diameter|width|yellow` |
| `fig` | 9 | 201 | `amount|axillary|sessile|glabrous` |
| `pistillate` | 9 | 66 | `amount|present|spinose|broadly elliptic` |
| `condyle` | 9 | 37 | `perforate|inconspicuous|shape|length` |
| `bloom` | 9 | 25 | `present` |
| `fascicles` | 9 | 13 | `present` |
| `lateral leaflet` | 8 | 399 | `amount|width|ovate|length` |
| `pseudumbel` | 8 | 57 | `present|amount|slender|abortive` |
| `lateral spike` | 8 | 48 | `amount|length|female|cylindric` |
| `longitudinal ridge` | 8 | 39 | `amount|angular` |
| `fertile flower` | 8 | 19 | `amount|present` |
| `reticulation` | 7 | 305 | `prominent|visible|dense|obscure` |
| `median cell` | 7 | 256 | `length|width|smooth|porose` |
| `leaf cell wall` | 7 | 158 | `nodose|thin|thick|thickened` |
| `basal bract` | 7 | 131 | `amount|width|connate|membranous` |
| `fruit lobe` | 7 | 123 | `width|length|accrescent|pubescent` |
| `tubular sheath` | 7 | 120 | `amount|length` |
| `leaflet segment` | 7 | 110 | `oblong|amount|approximate|ascending` |
| `annulus cell` | 7 | 105 | `rectangular|large|small|vesiculose` |
| `triad` | 7 | 102 | `amount|opposite|pedicellate|sunken` |
| `commissure` | 7 | 34 | `amount|unequal|present|bulging` |
| `unequal` | 7 | 24 | `amount` |
| `leaves` | 7 | 17 | `rounded|cuneate|inequilateral|reticulate-veined` |
| `pistillate portion` | 7 | 17 | `wide|long|length|thick` |
| `pellucid` | 7 | 13 | `present` |

## Top Cross-Flora Novel PO × PATO / FLOPO Combinations

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Floras | Total Count |
|---|---|---|---|---|---|---:|---:|
| `PO_0000003` | whole plant | `FLOPO_0991072` | dioecious | `EQ|PO_0000003|FLOPO_0991072` | `allowed` / `new_class_candidate` | 35 | 3,640 |
| `PO_0000003` | whole plant | `FLOPO_0991071` | monoecious | `EQ|PO_0000003|FLOPO_0991071` | `allowed` / `new_class_candidate` | 34 | 2,069 |
| `PO_0030112` | pedicel | `PATO_0002212` | slender | `EQ|PO_0030112|PATO_0002212` | `allowed` / `new_class_candidate` | 33 | 6,180 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `allowed` / `new_class_candidate` | 33 | 5,210 |
| `PO_0000003` | whole plant | `FLOPO_0991108` | climbing | `EQ|PO_0000003|FLOPO_0991108` | `allowed` / `new_class_candidate` | 33 | 4,559 |
| `PO_0020039` | leaf lamina | `PATO_0104359` | entire | `EQ|PO_0020039|PATO_0104359` | `allowed` / `new_class_candidate` | 31 | 10,228 |
| `PO_0009046` | flower | `PATO_0000070` | amount | `EQC|PO_0009046|n|PATO_0000070` | `allowed` / `new_class_candidate` | 30 | 1,882 |
| `PO_0020049` | leaflet | `PATO_0104359` | entire | `EQ|PO_0020049|PATO_0104359` | `allowed` / `new_class_candidate` | 30 | 1,652 |
| `PO_0009001` | fruit | `PATO_0104354` | winged | `EQ|PO_0009001|PATO_0104354` | `allowed` / `new_class_candidate` | 30 | 1,561 |
| `PO_0000042` | shoot-borne root | `PATO_0000467` | present | `EQ|PO_0000042|PATO_0000467` | `allowed` / `new_class_candidate` | 30 | 1,560 |
| `PO_0005656` | portion of secretory tissue | `PATO_0000467` | present | `EQ|PO_0005656|PATO_0000467` | `allowed` / `new_class_candidate` | 29 | 2,489 |
| `PO_0009001` | fruit | `FLOPO_0991149` | dehiscent | `EQ|PO_0009001|FLOPO_0991149` | `allowed` / `new_class_candidate` | 29 | 2,135 |
| `PO_0030112` | pedicel | `PATO_0000591` | increased thickness | `EQ|PO_0030112|PATO_0000591` | `allowed` / `new_class_candidate` | 29 | 1,848 |
| `PO_0009047` | stem | `FLOPO_0991108` | climbing | `EQ|PO_0009047|FLOPO_0991108` | `allowed` / `new_class_candidate` | 29 | 574 |
| `PO_0009073` | stigma | `FLOPO_0991006` | capitate | `EQ|PO_0009073|FLOPO_0991006` | `allowed` / `new_class_candidate` | 28 | 4,174 |
| `PO_0000003` | whole plant | `FLOPO_0991110` | epiphytic | `EQ|PO_0000003|FLOPO_0991110` | `allowed` / `new_class_candidate` | 28 | 3,702 |
| `PO_0020138` | leaf lamina vein | `PATO_0000070` | amount | `EQ|PO_0020138|PATO_0000070` | `allowed` / `new_class_candidate` | 28 | 3,063 |
| `PO_0020039` | leaf lamina | `PATO_0001408` | ciliated | `EQ|PO_0020039|PATO_0001408` | `allowed` / `new_class_candidate` | 28 | 2,622 |
| `PO_0025034` | leaf | `FLOPO_0991174` | gland-dotted | `EQ|PO_0025034|FLOPO_0991174` | `allowed` / `new_class_candidate` | 28 | 1,039 |
| `PO_0020049` | leaflet | `PATO_0000070` | amount | `EQC|PO_0020049|2|PATO_0000070` | `allowed` / `new_class_candidate` | 27 | 6,459 |
| `PO_0025034` | leaf | `FLOPO_0991161` | trifoliolate | `EQ|PO_0025034|FLOPO_0991161` | `allowed` / `new_class_candidate` | 27 | 2,766 |
| `PO_0009031` | sepal | `FLOPO_0991101` | unequal | `EQ|PO_0009031|FLOPO_0991101` | `allowed` / `new_class_candidate` | 27 | 2,654 |
| `FLOPO_0986009` | stigma lobe | `PATO_0000070` | amount | `EQ|FLOPO_0986009|PATO_0000070` | `allowed` / `new_class_candidate` | 27 | 2,569 |
| `PO_0000049` | leaf lamina abaxial epidermis | `PATO_0001320` | pubescent hair | `EQ|PO_0000049|PATO_0001320` | `allowed` / `new_class_candidate` | 27 | 1,975 |
| `PO_0020039` | leaf lamina | `PATO_0001889` | scalloped | `EQ|PO_0020039|PATO_0001889` | `allowed` / `new_class_candidate` | 27 | 1,804 |
| `PO_0009010` | seed | `FLOPO_0991100` | reticulate | `EQ|PO_0009010|FLOPO_0991100` | `allowed` / `new_class_candidate` | 27 | 1,386 |
| `PO_0009005` | root | `FLOPO_0991109` | tuberous | `EQ|PO_0009005|FLOPO_0991109` | `allowed` / `new_class_candidate` | 27 | 971 |
| `PO_0009010` | seed | `FLOPO_0991025` | obovoid | `EQ|PO_0009010|FLOPO_0991025` | `allowed` / `new_class_candidate` | 27 | 833 |
| `PO_0025034` | leaf | `PATO_0001968` | parallelodromous | `EQ|PO_0025034|PATO_0001968` | `allowed` / `new_class_candidate` | 27 | 319 |
| `PO_0020128` | leaf margin | `PATO_0104359` | entire | `EQ|PO_0020128|PATO_0104359` | `allowed` / `new_class_candidate` | 26 | 4,033 |
| `PO_0005020` | vascular bundle | `PATO_0000464` | inconspicuous | `EQ|PO_0005020|PATO_0000464` | `allowed` / `new_class_candidate` | 26 | 2,129 |
| `PO_0000003` | whole plant | `FLOPO_0991111` | terrestrial | `EQ|PO_0000003|FLOPO_0991111` | `allowed` / `new_class_candidate` | 26 | 2,019 |
| `PO_0025034` | leaf | `FLOPO_0991105` | sheathing | `EQ|PO_0025034|FLOPO_0991105` | `allowed` / `new_class_candidate` | 26 | 1,513 |
| `PO_0025034` | leaf | `FLOPO_0991100` | reticulate | `EQ|PO_0025034|FLOPO_0991100` | `allowed` / `new_class_candidate` | 26 | 1,165 |
| `PO_0009049` | inflorescence | `PATO_0001861` | fasciculated | `EQ|PO_0009049|PATO_0001861` | `novel` / `new_class_candidate` | 26 | 775 |
| `FLOPO_0985027` | pinna | `PATO_0000070` | amount | `EQC|FLOPO_0985027|2|PATO_0000070` | `allowed` / `new_class_candidate` | 25 | 4,500 |
| `PO_0009032` | petal | `FLOPO_0991169` | clawed | `EQ|PO_0009032|FLOPO_0991169` | `allowed` / `new_class_candidate` | 25 | 3,313 |
| `PO_0009031` | sepal | `FLOPO_0991102` | equal | `EQ|PO_0009031|FLOPO_0991102` | `allowed` / `new_class_candidate` | 25 | 2,297 |
| `PO_0020039` | leaf lamina | `FLOPO_0991054` | mucronate | `EQ|PO_0020039|FLOPO_0991054` | `allowed` / `new_class_candidate` | 25 | 1,886 |
| `PO_0020041` | stipule | `FLOPO_0991046` | membranous | `EQ|PO_0020041|FLOPO_0991046` | `allowed` / `new_class_candidate` | 25 | 1,864 |
