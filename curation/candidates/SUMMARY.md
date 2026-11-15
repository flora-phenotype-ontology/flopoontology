# Cross-Flora FLOPO Ontology Addition Candidates

This report aggregates candidate value terms (`FLOPO:0991xxx`), missing anatomical bearers,
and novel `PO × PATO/FLOPO` combinations across all processed floras.

## Per-Flora Overview

| Source | Flora | Records | Extracted Rows | Assertions | Value Candidates | Bearer Candidates | Novel Combinations |
|---|---|---:|---:|---:|---:|---:|---:|
| [`africa-tree-db`](africa-tree-db/CANDIDATES.md) | Africa Tree Database (ATDB) | 642 | 17,876 | 15,926 | 49 | 21 | 174 |
| [`eflora-andes`](eflora-andes/CANDIDATES.md) | Trees and Shrubs of the Andes of Ecuador & Flora of Chile (eFloras) | 13 | 669 | 470 | 23 | 6 | 30 |
| [`eflora-fna`](eflora-fna/CANDIDATES.md) | Flora of North America North of Mexico (eFloras) | 11,192 | 503,751 | 359,121 | 3,044 | 1,059 | 7,607 |
| [`eflora-foc`](eflora-foc/CANDIDATES.md) | Flora of China (eFloras) | 34,180 | 1,686,089 | 1,171,530 | 4,272 | 1,766 | 15,824 |
| [`eflora-fom`](eflora-fom/CANDIDATES.md) | Steyermark's Flora of Missouri (eFloras) | 31 | 1,735 | 1,066 | 47 | 15 | 133 |
| [`eflora-fop`](eflora-fop/CANDIDATES.md) | Flora of Pakistan (eFloras) | 3,578 | 133,523 | 106,669 | 1,248 | 347 | 4,151 |
| [`eflora-mfoc`](eflora-mfoc/CANDIDATES.md) | Moss Flora of China (eFloras) | 1,655 | 70,314 | 34,039 | 908 | 477 | 1,753 |
| [`eflora-other`](eflora-other/CANDIDATES.md) | eFloras Additional Floras (Missouri, Moss Flora of China, Andean) | 3,888 | 147,723 | 87,351 | 1,726 | 801 | 4,500 |
| [`fdac`](fdac/CANDIDATES.md) | Flore d'Afrique Centrale (Meise Botanic Garden) | 6,570 | 428,692 | 301,990 | 2,585 | 760 | 7,337 |
| [`fdac-genera`](fdac-genera/CANDIDATES.md) | Flore du Congo Belge et du Ruanda-Urundi — Genera (Meise Botanic Garden) | 891 | 42,896 | 29,296 | 999 | 190 | 2,134 |
| [`feis-plants`](feis-plants/CANDIDATES.md) | USFS Fire Effects Information System (FEIS) — Plant Species | 849 | 17,165 | 13,153 | 358 | 88 | 512 |
| [`flora-gabon`](flora-gabon/CANDIDATES.md) | Flore du Gabon (FlorML) | 3,112 | 182,980 | 129,537 | 1,743 | 547 | 5,599 |
| [`flora-guianas`](flora-guianas/CANDIDATES.md) | Flora of the Guianas (FlorML) | 1,162 | 65,650 | 48,791 | 588 | 127 | 1,900 |
| [`flora-malesiana`](flora-malesiana/CANDIDATES.md) | Flora Malesiana (FlorML) | 2,992 | 183,550 | 119,611 | 1,159 | 458 | 3,287 |
| [`flora-zimbabwe`](flora-zimbabwe/CANDIDATES.md) | Flora of Zimbabwe (Hyde, Wursten, Ballings & Coates Palgrave) | 5,186 | 108,241 | 82,152 | 1,005 | 301 | 3,352 |
| [`illinois-wildflowers`](illinois-wildflowers/CANDIDATES.md) | Illinois Wildflowers (John Hilty) | 1,233 | 58,441 | 45,289 | 405 | 127 | 1,579 |
| [`kew-african`](kew-african/CANDIDATES.md) | Kew African Flora Species | 12,104 | 524,005 | 412,075 | 2,698 | 970 | 9,064 |
| [`korup-flora`](korup-flora/CANDIDATES.md) | Vascular Plants of Korup National Park (Cameroon) | 129 | 6,736 | 5,366 | 120 | 26 | 390 |
| [`nybg-naf`](nybg-naf/CANDIDATES.md) | North American Flora Monographs (New York Botanical Garden) | 10,895 | 454,400 | 325,231 | 2,645 | 661 | 5,168 |
| [`phytokeys`](phytokeys/CANDIDATES.md) | PhytoKeys Botanical Taxonomic Monographs (Pensoft) | 283 | 24,012 | 17,372 | 337 | 133 | 1,174 |
| [`plants-tibet`](plants-tibet/CANDIDATES.md) | Plants of Tibet (Flora Xizangica / Tibetan Plateau) | 443 | 23,809 | 17,639 | 310 | 82 | 1,370 |
| [`plazi`](plazi/CANDIDATES.md) | Plazi / Pensoft / BHL Open-Access Taxonomic Treatments (Zenodo BLR) | 562 | 33,729 | 24,200 | 646 | 201 | 2,031 |
| [`powo-cate`](powo-cate/CANDIDATES.md) | CATE Araceae & Palmweb Monocot Monographs (via Kew POWO) | 111 | 9,241 | 5,110 | 213 | 69 | 606 |
| [`powo-cayman`](powo-cayman/CANDIDATES.md) | Flora of the Cayman Islands (via Kew POWO) | 168 | 4,064 | 3,174 | 66 | 15 | 227 |
| [`powo-fiq`](powo-fiq/CANDIDATES.md) | Flora of Iraq (via Kew POWO) | 82 | 3,543 | 2,476 | 56 | 13 | 168 |
| [`powo-fsom`](powo-fsom/CANDIDATES.md) | Flora of Somalia (via Kew POWO) | 231 | 7,583 | 6,169 | 91 | 19 | 378 |
| [`powo-ftea`](powo-ftea/CANDIDATES.md) | Flora of Tropical East Africa (via Kew POWO) | 807 | 45,518 | 35,785 | 535 | 140 | 1,921 |
| [`powo-fwta`](powo-fwta/CANDIDATES.md) | Flora of West Tropical Africa (via Kew POWO) | 354 | 2,323 | 1,874 | 35 | 3 | 88 |
| [`powo-fz`](powo-fz/CANDIDATES.md) | Flora Zambesiaca (via Kew POWO) | 765 | 46,380 | 35,828 | 551 | 147 | 2,003 |
| [`powo-grassbase`](powo-grassbase/CANDIDATES.md) | GrassBase — The Online World Grass Flora (RBG Kew via POWO) | 73 | 6,796 | 4,635 | 81 | 48 | 222 |
| [`powo-ildis`](powo-ildis/CANDIDATES.md) | ILDIS World Database of Legumes (via Kew POWO) | 394 | 1,207 | 1,180 | 1 | 0 | 1 |
| [`powo-kew`](powo-kew/CANDIDATES.md) | Kew Monographs & Databases (Kew Bulletin, GrassBase, ILDIS, CATE via POWO) | 395 | 22,080 | 14,145 | 395 | 136 | 1,276 |
| [`powo-neotropical`](powo-neotropical/CANDIDATES.md) | Neotropical & Colombian Floras (CPLC, UPFC, UPB, Neotropikey via POWO) | 3,855 | 6,316 | 5,425 | 12 | 0 | 5 |
| [`powo-tong`](powo-tong/CANDIDATES.md) | Trees of New Guinea (via Kew POWO) | 206 | 8,820 | 5,926 | 223 | 53 | 495 |
| [`silvics-na`](silvics-na/CANDIDATES.md) | Silvics of North America (USFS Agriculture Handbook 654) | 184 | 2,890 | 1,663 | 92 | 28 | 124 |
| [`smithsonian-botany`](smithsonian-botany/CANDIDATES.md) | Smithsonian Contributions to Botany (NMNH Taxonomic Monographs) | 1,383 | 48,948 | 29,898 | 721 | 301 | 1,747 |
| [`usda-plants`](usda-plants/CANDIDATES.md) | USDA NRCS PLANTS Database — Botanical Descriptions | 678 | 15,003 | 11,827 | 308 | 51 | 622 |
| [`wfo`](wfo/CANDIDATES.md) | World Flora Online Species Descriptions (WFO) | 20 | 960 | 534 | 49 | 19 | 29 |

## Top Cross-Flora Value Term Candidates

Ranked first by number of floras in which the term is needed, then by total occurrences.

| Quality word | Floras | Total Count | Suggested PATO parent | Top Bearers |
|---|---:|---:|---|---|
| `parallel` | 29 | 869 | `PATO:0000141` (structure) | `PO_0025034|PO_0005020|PO_0020138|PO_0020140` |
| `round` | 29 | 581 | `PATO:0000141` (structure) | `PO_0009010|PO_0025359|PO_0005656|FLOPO_0986020` |
| `compound` | 29 | 568 | `PATO:0000141` (structure) | `PO_0009049|PO_0020049|PO_0020039|PO_0030115` |
| `naked` | 28 | 854 | `PATO:0000141` (structure) | `PO_0009047|PO_0025073|PO_0009049|PO_0009064` |
| `scale-like` | 27 | 1,163 | `PATO:0000052` (shape) | `PO_0004542|PO_0004518|PO_0025393|PO_0009047` |
| `distinct` | 26 | 1,354 | `PATO:0001435` (attachment quality) | `PO_0025034|PO_0009010|PO_0009073|PO_0009072` |
| `few-flowered` | 26 | 1,225 | `PATO:0000141` (structure) | `PO_0009049|PO_0030117|PO_0025073|PO_0030126` |
| `divergent` | 26 | 1,028 | `PATO:0000141` (structure) | `PO_0009001|PO_0009066|PO_0009074|PO_0009073` |
| `tufted` | 25 | 777 | `PATO:0000060` (spatial pattern) | `PO_0025034|FLOPO_0985026|PO_0009005|PO_0004542` |
| `stalked` | 24 | 1,169 | `PATO:0000141` (structure) | `FLOPO_0985027|PO_0020049|FLOPO_0985028|PO_0009066` |
| `thin-walled` | 23 | 1,080 | `PATO:0000141` (structure) | `cell|leaf cell|laminal cell|exothecial cell` |
| `visible` | 23 | 1,036 | `PATO:0000141` (structure) | `PO_0005020|PO_0025034|PO_0020140|PO_0020138` |
| `eglandular` | 23 | 993 | `PATO:0000141` (structure) | `PO_0025034|PO_0009047|PO_0000003|PO_0009045` |
| `fine` | 23 | 469 | `PATO:0000141` (structure) | `PO_0025034|PO_0005020|bristle|PO_0006011` |
| `marked` | 23 | 409 | `PATO:0000141` (structure) | `PO_0009032|PO_0009059|PO_0009046|FLOPO_0985017` |
| `confluent` | 23 | 392 | `PATO:0000141` (structure) | `PO_0009066|PO_0025359|PO_0005020|PO_0009073` |
| `separate` | 23 | 374 | `PATO:0000052` (shape) | `PO_0025359|PO_0009049|PO_0030117|PO_0020049` |
| `unarmed` | 22 | 871 | `PATO:0000141` (structure) | `PO_0000003|PO_0009047|PO_0025073|PO_0020038` |
| `glandless` | 22 | 421 | `PATO:0000141` (structure) | `PO_0025034|PO_0020038|PO_0009047|PO_0020039` |
| `armed` | 22 | 405 | `PATO:0000141` (structure) | `PO_0009047|PO_0020038|PO_0025073|PO_0000003` |
| `thick-walled` | 21 | 1,050 | `PATO:0000141` (structure) | `cell|leaf cell|PO_0025034|laminal cell` |
| `gland-tipped` | 21 | 490 | `PATO:0000141` (structure) | `PO_0020041|PO_0025034|PO_0009001|PO_0009031` |
| `well developed` | 21 | 475 | `PATO:0000141` (structure) | `PO_0025034|PO_0009038|endostome segment|PO_0030042` |
| `dichasial` | 21 | 242 | `PATO:0000141` (structure) | `PO_0009049|PO_0020122|part:|infloresc` |
| `abundant` | 21 | 201 | `PATO:0000141` (structure) | `PO_0009049|FLOPO_0980431|scale|PO_0025393` |
| `well-developed` | 21 | 196 | `PATO:0000141` (structure) | `PO_0009055|PO_0025034|PO_0020041|PO_0009047` |
| `pustulate` | 21 | 192 | `PATO:0000052` (shape) | `PO_0025034|PO_0009001|PO_0020039|PO_0009072` |
| `double` | 20 | 551 | `PATO:0000141` (structure) | `PO_0030042|PO_0030072|PO_0025034|PO_0030043` |
| `wiry` | 20 | 539 | `PATO:0000141` (structure) | `PO_0009047|PO_0000003|PO_0009053|PO_0004542` |
| `delicate` | 20 | 358 | `PATO:0000052` (shape) | `PO_0000003|PO_0025034|PO_0009047|PO_0009049` |
| `pungent` | 20 | 357 | `PATO:0001331` (odor) | `PO_0025034|PO_0020039|callus|PO_0009043` |
| `appendaged` | 20 | 344 | `PATO:0000141` (structure) | `PO_0009066|PO_0009032|PO_0009029|PO_0009045` |
| `oblong-ovate` | 20 | 330 | `PATO:0000052` (shape) | `PO_0009031|PO_0009032|PO_0020049|PO_0020039` |
| `septate` | 20 | 311 | `PATO:0000052` (shape) | `PO_0009001|PO_0025034|PO_0020039|PO_0009047` |
| `tough` | 20 | 295 | `PATO:0000141` (structure) | `PO_0009047|PO_0004542|PO_0009005|PO_0009001` |
| `low` | 20 | 233 | `PATO:0000141` (structure) | `basal membrane|PO_0025166|laminal papilla|rib` |
| `barrel-shaped` | 20 | 71 | `PATO:0000052` (shape) | `FLOPO_0985020|PO_0009100|PO_0009064|PO_0009059` |
| `ovate-lanceolate` | 19 | 1,198 | `PATO:0000052` (shape) | `PO_0009055|PO_0009031|PO_0020041|PO_0020039` |
| `ternate` | 19 | 745 | `PATO:0000052` (shape) | `PO_0025034|PO_0020049|PO_0009055|PO_0020039` |
| `sheathed` | 19 | 505 | `PATO:0000141` (structure) | `PO_0020038|PO_0009047|PO_0009055|PO_0025034` |

## Top Cross-Flora Anatomical Bearer Candidates

| Bearer word | Floras | Total Count | Top Qualities |
|---|---:|---:|---|
| `thyrse` | 20 | 198 | `present|amount` |
| `glomerule` | 18 | 468 | `present|amount|sessile|diameter` |
| `pulp` | 17 | 84 | `white|bitter|green-black|orange-red` |
| `cystolith` | 13 | 116 | `punctiform|present|fusiform|conspicuous` |
| `thyrsus` | 13 | 72 | `present` |
| `primary branch` | 13 | 37 | `amount|length` |
| `pseudostaminode` | 12 | 100 | `dentate|entire|fimbriate|length` |
| `antherode` | 12 | 43 | `length|apiculate|hairy|absent` |
| `dichasia` | 12 | 23 | `present|amount|sessile` |
| `basal leave` | 11 | 274 | `amount` |
| `cystoliths` | 11 | 261 | `present` |
| `basal sheath` | 11 | 175 | `glabrous|amount|fibrous|pale brown` |
| `dichasium` | 11 | 49 | `present|amount` |
| `flowering stem` | 11 | 37 | `amount|erect|light brown|length` |
| `petioleaves` | 11 | 24 | `petiolate|glabrous|glabrescent|hairy` |
| `ribbed` | 11 | 22 | `present|amount` |
| `cell wall` | 10 | 186 | `thick|thin|thickened|pitted` |
| `pseudoraceme` | 10 | 98 | `present` |
| `hairs` | 10 | 71 | `glandular|short|white|present` |
| `seed wing` | 10 | 50 | `amount|hyaline|tapered|silky` |
| `nerved` | 10 | 25 | `amount` |
| `pseudo-umbel` | 10 | 22 | `present|amount` |
| `stilt` | 10 | 21 | `present` |
| `inflores` | 10 | 20 | `lax|spiciform|paniculiform|dense` |
| `ostiole` | 9 | 328 | `prominent|flat|open|sunken` |
| `marginal cell` | 9 | 237 | `amount|quadrate|linear|short-linear` |
| `involucre lobe` | 9 | 140 | `amount|rounded|ovate|acute` |
| `floral tube` | 9 | 119 | `villous|greenish white|length|green` |
| `cocci` | 9 | 25 | `amount|smooth|puberulous|papillate` |
| `pseudostipule` | 9 | 25 | `absent|ovate|acuminate|asymmetric` |
| `smaller` | 9 | 18 | `amount` |
| `veined` | 9 | 18 | `amount|present` |
| `verticillate` | 9 | 15 | `present|amount` |
| `basal cell` | 8 | 563 | `smooth|rectangular|amount|differentiated` |
| `sporocarp` | 8 | 274 | `elliptic|thick|length|amount` |
| `stipule lobe` | 8 | 115 | `amount|lanceolate|acute|linear` |
| `nectary scale` | 8 | 112 | `length|linear|linear-subulate|broad` |
| `anther appendage` | 8 | 107 | `ovate|rounded|orbicular|oblong-lanceolate` |
| `perianth part` | 8 | 61 | `amount|ovate|red|reduced` |
| `fig` | 8 | 58 | `amount|axillary|brownish|solitary` |

## Top Cross-Flora Novel PO × PATO / FLOPO Combinations

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Floras | Total Count |
|---|---|---|---|---|---|---:|---:|
| `PO_0000003` | whole plant | `FLOPO_0991072` | dioecious | `EQ|PO_0000003|FLOPO_0991072` | `allowed` / `new_class_candidate` | 34 | 1,628 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `novel` / `new_class_candidate` | 33 | 2,597 |
| `PO_0000003` | whole plant | `FLOPO_0991071` | monoecious | `EQ|PO_0000003|FLOPO_0991071` | `allowed` / `new_class_candidate` | 33 | 1,191 |
| `PO_0030112` | pedicel | `PATO_0002212` | slender | `EQ|PO_0030112|PATO_0002212` | `allowed` / `new_class_candidate` | 32 | 3,274 |
| `PO_0000003` | whole plant | `FLOPO_0991108` | climbing | `EQ|PO_0000003|FLOPO_0991108` | `allowed` / `new_class_candidate` | 32 | 2,249 |
| `PO_0020039` | leaf lamina | `PATO_0104359` | entire | `EQ|PO_0020039|PATO_0104359` | `novel` / `new_class_candidate` | 29 | 5,279 |
| `PO_0009001` | fruit | `PATO_0104354` | winged | `EQ|PO_0009001|PATO_0104354` | `novel` / `new_class_candidate` | 29 | 1,037 |
| `PO_0020049` | leaflet | `PATO_0104359` | entire | `EQ|PO_0020049|PATO_0104359` | `novel` / `new_class_candidate` | 29 | 962 |
| `PO_0009046` | flower | `PATO_0000070` | amount | `EQC|PO_0009046|n|PATO_0000070` | `allowed` / `new_class_candidate` | 29 | 893 |
| `PO_0030112` | pedicel | `PATO_0000591` | increased thickness | `EQ|PO_0030112|PATO_0000591` | `novel` / `new_class_candidate` | 28 | 1,032 |
| `PO_0009073` | stigma | `FLOPO_0991006` | capitate | `EQ|PO_0009073|FLOPO_0991006` | `allowed` / `new_class_candidate` | 27 | 1,980 |
| `PO_0000003` | whole plant | `FLOPO_0991110` | epiphytic | `EQ|PO_0000003|FLOPO_0991110` | `allowed` / `new_class_candidate` | 27 | 1,431 |
| `PO_0009047` | stem | `FLOPO_0991108` | climbing | `EQ|PO_0009047|FLOPO_0991108` | `allowed` / `new_class_candidate` | 27 | 288 |
| `PO_0020049` | leaflet | `PATO_0000070` | amount | `EQC|PO_0020049|2|PATO_0000070` | `allowed` / `new_class_candidate` | 26 | 3,465 |
| `PO_0020138` | leaf lamina vein | `PATO_0000070` | amount | `EQ|PO_0020138|PATO_0000070` | `novel` / `new_class_candidate` | 26 | 1,636 |
| `PO_0020039` | leaf lamina | `PATO_0001408` | ciliated | `EQ|PO_0020039|PATO_0001408` | `novel` / `new_class_candidate` | 26 | 1,522 |
| `PO_0009031` | sepal | `FLOPO_0991101` | unequal | `EQ|PO_0009031|FLOPO_0991101` | `allowed` / `new_class_candidate` | 26 | 1,495 |
| `PO_0025034` | leaf | `FLOPO_0991161` | trifoliolate | `EQ|PO_0025034|FLOPO_0991161` | `allowed` / `new_class_candidate` | 26 | 1,411 |
| `FLOPO_0986009` | stigma lobe | `PATO_0000070` | amount | `EQ|FLOPO_0986009|PATO_0000070` | `novel` / `new_class_candidate` | 26 | 1,345 |
| `PO_0020039` | leaf lamina | `PATO_0001889` | scalloped | `EQ|PO_0020039|PATO_0001889` | `novel` / `new_class_candidate` | 26 | 935 |
| `PO_0009001` | fruit | `FLOPO_0991149` | dehiscent | `EQ|PO_0009001|FLOPO_0991149` | `allowed` / `new_class_candidate` | 26 | 860 |
| `PO_0009010` | seed | `FLOPO_0991100` | reticulate | `EQ|PO_0009010|FLOPO_0991100` | `allowed` / `new_class_candidate` | 26 | 785 |
| `PO_0009010` | seed | `FLOPO_0991025` | obovoid | `EQ|PO_0009010|FLOPO_0991025` | `allowed` / `new_class_candidate` | 26 | 475 |
| `PO_0020128` | leaf margin | `PATO_0104359` | entire | `EQ|PO_0020128|PATO_0104359` | `novel` / `new_class_candidate` | 25 | 1,406 |
| `PO_0005656` | portion of secretory tissue | `PATO_0000467` | present | `EQ|PO_0005656|PATO_0000467` | `novel` / `new_class_candidate` | 25 | 967 |
| `PO_0025034` | leaf | `FLOPO_0991100` | reticulate | `EQ|PO_0025034|FLOPO_0991100` | `allowed` / `new_class_candidate` | 25 | 748 |
| `PO_0000003` | whole plant | `FLOPO_0991111` | terrestrial | `EQ|PO_0000003|FLOPO_0991111` | `allowed` / `new_class_candidate` | 25 | 707 |
| `PO_0025034` | leaf | `FLOPO_0991174` | gland-dotted | `EQ|PO_0025034|FLOPO_0991174` | `allowed` / `new_class_candidate` | 25 | 546 |
| `PO_0009049` | inflorescence | `PATO_0001861` | fasciculated | `EQ|PO_0009049|PATO_0001861` | `novel` / `new_class_candidate` | 25 | 485 |
| `PO_0009005` | root | `FLOPO_0991109` | tuberous | `EQ|PO_0009005|FLOPO_0991109` | `allowed` / `new_class_candidate` | 25 | 414 |
| `FLOPO_0985027` | pinna | `PATO_0000070` | amount | `EQC|FLOPO_0985027|2|PATO_0000070` | `allowed` / `new_class_candidate` | 24 | 2,396 |
| `PO_0009032` | petal | `FLOPO_0991169` | clawed | `EQ|PO_0009032|FLOPO_0991169` | `allowed` / `new_class_candidate` | 24 | 1,901 |
| `PO_0009031` | sepal | `FLOPO_0991102` | equal | `EQ|PO_0009031|FLOPO_0991102` | `allowed` / `new_class_candidate` | 24 | 1,131 |
| `PO_0005020` | vascular bundle | `PATO_0000464` | inconspicuous | `EQ|PO_0005020|PATO_0000464` | `novel` / `new_class_candidate` | 24 | 1,046 |
| `PO_0000049` | leaf lamina abaxial epidermis | `PATO_0001320` | pubescent hair | `EQ|PO_0000049|PATO_0001320` | `allowed` / `new_class_candidate` | 24 | 1,033 |
| `PO_0020039` | leaf lamina | `FLOPO_0991054` | mucronate | `EQ|PO_0020039|FLOPO_0991054` | `allowed` / `new_class_candidate` | 24 | 984 |
| `PO_0020041` | stipule | `FLOPO_0991046` | membranous | `EQ|PO_0020041|FLOPO_0991046` | `allowed` / `new_class_candidate` | 24 | 944 |
| `PO_0030112` | pedicel | `PATO_0000454` | hairy | `EQ|PO_0030112|PATO_0000454` | `novel` / `new_class_candidate` | 24 | 855 |
| `PO_0030112` | pedicel | `PATO_0002117` | glandular | `EQ|PO_0030112|PATO_0002117` | `novel` / `new_class_candidate` | 24 | 778 |
| `PO_0009032` | petal | `FLOPO_0991068` | free | `EQ|PO_0009032|FLOPO_0991068` | `allowed` / `new_class_candidate` | 24 | 666 |
