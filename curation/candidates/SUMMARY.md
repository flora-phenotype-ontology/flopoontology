# Cross-Flora FLOPO Ontology Addition Candidates

This report aggregates candidate value terms (`FLOPO:0991xxx`), missing anatomical bearers,
and novel `PO × PATO/FLOPO` combinations across all processed floras.

## Per-Flora Overview

| Source | Flora | Records | Extracted Rows | Assertions | Value Candidates | Bearer Candidates | Novel Combinations |
|---|---|---:|---:|---:|---:|---:|---:|
| [`africa-tree-db`](africa-tree-db/CANDIDATES.md) | Africa Tree Database (ATDB) | 20 | 628 | 527 | 7 | 5 | 26 |
| [`eflora-andes`](eflora-andes/CANDIDATES.md) | Trees and Shrubs of the Andes of Ecuador & Flora of Chile (eFloras) | 13 | 669 | 427 | 46 | 12 | 90 |
| [`eflora-fna`](eflora-fna/CANDIDATES.md) | Flora of North America North of Mexico (eFloras) | 20 | 1,148 | 566 | 36 | 15 | 45 |
| [`eflora-foc`](eflora-foc/CANDIDATES.md) | Flora of China (eFloras) | 20 | 771 | 392 | 24 | 13 | 66 |
| [`eflora-fom`](eflora-fom/CANDIDATES.md) | Steyermark's Flora of Missouri (eFloras) | 20 | 967 | 468 | 60 | 24 | 73 |
| [`eflora-fop`](eflora-fop/CANDIDATES.md) | Flora of Pakistan (eFloras) | 20 | 821 | 596 | 20 | 5 | 50 |
| [`eflora-mfoc`](eflora-mfoc/CANDIDATES.md) | Moss Flora of China (eFloras) | 20 | 647 | 327 | 34 | 28 | 69 |
| [`eflora-other`](eflora-other/CANDIDATES.md) | eFloras Additional Floras (Missouri, Moss Flora of China, Andean) | 20 | 491 | 321 | 23 | 3 | 48 |
| [`fdac`](fdac/CANDIDATES.md) | Flore d'Afrique Centrale (Meise Botanic Garden) | 20 | 1,167 | 672 | 53 | 19 | 122 |
| [`fdac-genera`](fdac-genera/CANDIDATES.md) | Flore du Congo Belge et du Ruanda-Urundi — Genera (Meise Botanic Garden) | 20 | 569 | 308 | 46 | 12 | 76 |
| [`feis-plants`](feis-plants/CANDIDATES.md) | USFS Fire Effects Information System (FEIS) — Plant Species | 20 | 426 | 216 | 31 | 7 | 31 |
| [`flora-gabon`](flora-gabon/CANDIDATES.md) | Flore du Gabon (FlorML) | 20 | 337 | 248 | 13 | 0 | 54 |
| [`flora-guianas`](flora-guianas/CANDIDATES.md) | Flora of the Guianas (FlorML) | 20 | 739 | 383 | 15 | 4 | 24 |
| [`flora-malesiana`](flora-malesiana/CANDIDATES.md) | Flora Malesiana (FlorML) | 20 | 1,211 | 404 | 53 | 22 | 84 |
| [`flora-zimbabwe`](flora-zimbabwe/CANDIDATES.md) | Flora of Zimbabwe (Hyde, Wursten, Ballings & Coates Palgrave) | 20 | 505 | 288 | 32 | 5 | 45 |
| [`illinois-wildflowers`](illinois-wildflowers/CANDIDATES.md) | Illinois Wildflowers (John Hilty) | 20 | 904 | 630 | 34 | 17 | 88 |
| [`kew-african`](kew-african/CANDIDATES.md) | Kew African Flora Species | 20 | 404 | 282 | 14 | 2 | 32 |
| [`korup-flora`](korup-flora/CANDIDATES.md) | Vascular Plants of Korup National Park (Cameroon) | 19 | 1,485 | 1,063 | 57 | 22 | 142 |
| [`nybg-naf`](nybg-naf/CANDIDATES.md) | North American Flora Monographs (New York Botanical Garden) | 20 | 764 | 241 | 54 | 41 | 62 |
| [`phytokeys`](phytokeys/CANDIDATES.md) | PhytoKeys Botanical Taxonomic Monographs (Pensoft) | 18 | 1,874 | 913 | 88 | 33 | 150 |
| [`plants-tibet`](plants-tibet/CANDIDATES.md) | Plants of Tibet (Flora Xizangica / Tibetan Plateau) | 20 | 1,137 | 785 | 39 | 17 | 105 |
| [`plazi`](plazi/CANDIDATES.md) | Plazi / Pensoft / BHL Open-Access Taxonomic Treatments (Zenodo BLR) | 17 | 557 | 331 | 28 | 8 | 62 |
| [`powo-cate`](powo-cate/CANDIDATES.md) | CATE Araceae & Palmweb Monocot Monographs (via Kew POWO) | 19 | 1,398 | 601 | 84 | 38 | 117 |
| [`powo-cayman`](powo-cayman/CANDIDATES.md) | Flora of the Cayman Islands (via Kew POWO) | 20 | 525 | 350 | 29 | 4 | 48 |
| [`powo-fiq`](powo-fiq/CANDIDATES.md) | Flora of Iraq (via Kew POWO) | 81 | 3,457 | 2,124 | 138 | 41 | 261 |
| [`powo-fsom`](powo-fsom/CANDIDATES.md) | Flora of Somalia (via Kew POWO) | 20 | 679 | 429 | 21 | 21 | 62 |
| [`powo-ftea`](powo-ftea/CANDIDATES.md) | Flora of Tropical East Africa (via Kew POWO) | 20 | 1,221 | 710 | 52 | 24 | 97 |
| [`powo-fwta`](powo-fwta/CANDIDATES.md) | Flora of West Tropical Africa (via Kew POWO) | 20 | 127 | 97 | 3 | 1 | 18 |
| [`powo-fz`](powo-fz/CANDIDATES.md) | Flora Zambesiaca (via Kew POWO) | 20 | 1,449 | 893 | 63 | 27 | 98 |
| [`powo-grassbase`](powo-grassbase/CANDIDATES.md) | GrassBase — The Online World Grass Flora (RBG Kew via POWO) | 20 | 1,798 | 1,086 | 60 | 21 | 155 |
| [`powo-ildis`](powo-ildis/CANDIDATES.md) | ILDIS World Database of Legumes (via Kew POWO) | 20 | 64 | 42 | 0 | 0 | 0 |
| [`powo-kew`](powo-kew/CANDIDATES.md) | Kew Monographs & Databases (Kew Bulletin, GrassBase, ILDIS, CATE via POWO) | 20 | 1,574 | 780 | 95 | 38 | 169 |
| [`powo-neotropical`](powo-neotropical/CANDIDATES.md) | Neotropical & Colombian Floras (CPLC, UPFC, UPB, Neotropikey via POWO) | 20 | 34 | 25 | 1 | 0 | 0 |
| [`powo-tong`](powo-tong/CANDIDATES.md) | Trees of New Guinea (via Kew POWO) | 20 | 822 | 429 | 69 | 11 | 62 |
| [`silvics-na`](silvics-na/CANDIDATES.md) | Silvics of North America (USFS Agriculture Handbook 654) | 20 | 419 | 162 | 18 | 17 | 28 |
| [`smithsonian-botany`](smithsonian-botany/CANDIDATES.md) | Smithsonian Contributions to Botany (NMNH Taxonomic Monographs) | 18 | 1,803 | 1,137 | 62 | 11 | 111 |
| [`usda-plants`](usda-plants/CANDIDATES.md) | USDA NRCS PLANTS Database — Botanical Descriptions | 20 | 535 | 378 | 21 | 9 | 51 |
| [`wfo`](wfo/CANDIDATES.md) | World Flora Online Species Descriptions (WFO) | 20 | 960 | 526 | 51 | 22 | 123 |

## Top Cross-Flora Value Term Candidates

Ranked first by number of floras in which the term is needed, then by total occurrences.

| Quality word | Floras | Total Count | Suggested PATO parent | Top Bearers |
|---|---:|---:|---|---|
| `unequal` | 17 | 21 | `PATO:0000141` (structure) | `PO_0025034|PO_0009031|PO_0025331|PO_0030112` |
| `subcoriaceous` | 11 | 36 | `PATO:0000150` (texture) | `PO_0025034|cataphyll|part:|spathe` |
| `subequal` | 10 | 13 | `PATO:0000141` (structure) | `PO_0009031|PO_0009059|PO_0020049|PO_0020040` |
| `paler` | 9 | 18 | `PATO:0000141` (structure) | `PO_0025034|PO_0020039|PO_0005020|PO_0020139` |
| `subentire` | 9 | 18 | `PATO:0000141` (structure) | `PO_0025034|scale|margin|indusium` |
| `distinct` | 9 | 13 | `PATO:0001435` (attachment quality) | `PO_0025034|PO_0005020|PO_0025228|PO_0020140` |
| `narrowed` | 8 | 34 | `PATO:0000141` (structure) | `PO_0025034|FLOPO_0985027|PO_0020049|frond base` |
| `united` | 8 | 17 | `PATO:0001435` (attachment quality) | `PO_0009074|PO_0030043|PO_0030042|part:` |
| `lax` | 8 | 16 | `PATO:0000060` (spatial pattern) | `PO_0009049|PO_0025034|PO_0020039` |
| `accrescent` | 8 | 10 | `PATO:0000141` (structure) | `PO_0009060|PO_0009064|PO_0009049|PO_0030123` |
| `suborbicular` | 8 | 10 | `PATO:0000052` (shape) | `PO_0025034|PO_0009010|gland|PO_0000055` |
| `round` | 7 | 14 | `PATO:0000141` (structure) | `PO_0025359|PO_0030070|PO_0009010|FLOPO_0985030` |
| `obscure` | 7 | 13 | `PATO:0000141` (structure) | `PO_0005020|PO_0025034|PO_0004518|PO_0009047` |
| `serrulate` | 7 | 11 | `PATO:0000052` (shape) | `PO_0025034|PO_0020049|margin|FLOPO_0985027` |
| `covered` | 7 | 8 | `PATO:0000141` (structure) | `PO_0009047|PO_0009001|PO_0020038|PO_0025034` |
| `sheathing` | 7 | 8 | `PATO:0000141` (structure) | `PO_0025034|PO_0020038|PO_0020041` |
| `compound` | 7 | 7 | `PATO:0000141` (structure) | `PO_0009049` |
| `resinous` | 6 | 51 | `PATO:0000150` (texture) | `PO_0009047|PO_0025034|PO_0004518|PO_0025073` |
| `turbinate` | 6 | 27 | `PATO:0000052` (shape) | `PO_0009001|PO_0009059|part|PO_0009060` |
| `veined` | 6 | 12 | `PATO:0000141` (structure) | `calyx tube|PO_0009010|phyllary|PO_0009059` |
| `parallel` | 6 | 10 | `PATO:0000141` (structure) | `PO_0025034|PO_0005020|PO_0009066|tertiary nerves` |
| `terrestrial` | 6 | 9 | `PATO:0000141` (structure) | `PO_0000003` |
| `tuberous` | 6 | 9 | `PATO:0000141` (structure) | `PO_0009005|PO_0004542|PO_0009047|PO_0000003` |
| `boat-shaped` | 6 | 8 | `PATO:0000052` (shape) | `PO_0009055|spathe blade|PO_0020041|FLOPO_0985017` |
| `rigid` | 6 | 8 | `PATO:0000141` (structure) | `PO_0020038|PO_0009047|PO_0025349|PO_0025034` |
| `depressed` | 6 | 7 | `PATO:0000141` (structure) | `PO_0009001|PO_0005020|pistil|PO_0009072` |
| `fasciculate` | 6 | 7 | `PATO:0000060` (spatial pattern) | `PO_0009049|indumentum|PO_0009046|PO_0009060` |
| `spirally arranged` | 6 | 7 | `PATO:0000141` (structure) | `PO_0025034|PO_0009055` |
| `strigose` | 6 | 7 | `PATO:0000066` (pilosity) | `PO_0009001|PO_0030112|PO_0025034|PO_0020049` |
| `adnate` | 6 | 6 | `PATO:0001435` (attachment quality) | `PO_0020041|PO_0020049|PO_0009001|PO_0009060` |
| `quality:` | 6 | 6 | `PATO:0000141` (structure) | `PO_0020039|leaf scar|PO_0020003|PO_0009060` |
| `pinnatifid` | 5 | 24 | `PATO:0000052` (shape) | `PO_0025034|FLOPO_0985026|PO_0025060|FLOPO_0985027` |
| `glandular-pubescent` | 5 | 23 | `PATO:0000066` (pilosity) | `PO_0025034|PO_0009055|PO_0009047|part:` |
| `plane` | 5 | 21 | `PATO:0000141` (structure) | `PO_0025034|PO_0020039|PO_0005020|PO_0020128` |
| `included` | 5 | 14 | `PATO:0000141` (structure) | `PO_0009055|PO_0009066|PO_0009073|PO_0009059` |
| `unarmed` | 5 | 14 | `PATO:0000141` (structure) | `PO_0009049|PO_0009047|PO_0020038|rachis` |
| `impressed` | 5 | 12 | `PATO:0000141` (structure) | `PO_0020039|midvein|PO_0025034|PO_0005020` |
| `lenticellate` | 5 | 12 | `PATO:0000052` (shape) | `PO_0025073|PO_0009001|PO_0004518|PO_0009047` |
| `divaricate` | 5 | 11 | `PATO:0000052` (shape) | `PO_0009069|PO_0025073|PO_0020049|PO_0025517` |
| `stalked` | 5 | 10 | `PATO:0000141` (structure) | `FLOPO_0985026|FLOPO_0985027|phyllary|PO_0020049` |

## Top Cross-Flora Anatomical Bearer Candidates

| Bearer word | Floras | Total Count | Top Qualities |
|---|---:|---:|---|
| `rachis` | 12 | 54 | `length|angular|pubescent|straight` |
| `segment` | 11 | 35 | `amount|rounded|acuminate|mucronulate` |
| `scale` | 9 | 103 | `brown|linear|length|concolorous` |
| `gland` | 9 | 20 | `amount|absent|present|conspicuous` |
| `floret` | 8 | 55 | `amount|female|sterile|fertile` |
| `wing` | 8 | 29 | `amount|dilated|truncate|flattened` |
| `stipe` | 7 | 63 | `length|grooved|diameter|scaly` |
| `head` | 7 | 12 | `amount|present` |
| `spathe` | 6 | 154 | `length|width|wide|lanceolate` |
| `phyllary` | 6 | 110 | `amount|lanceolate|ovate|pilose` |
| `spore` | 6 | 36 | `papillose|small|globular|spiny` |
| `scape` | 6 | 33 | `tomentose|amount|erect|long` |
| `disk` | 6 | 30 | `fleshy|diameter|height|thick` |
| `whorl` | 6 | 8 | `amount` |
| `appendage` | 5 | 17 | `ciliate|triangular|light brown|spinulose` |
| `cell` | 5 | 16 | `amount|short|oblong-rhombic|elongate` |
| `rootstock` | 5 | 14 | `woody|thick|woolly|thickened` |
| `pistil` | 5 | 13 | `green|exserted|length|slender` |
| `margin` | 5 | 8 | `dentate|fringed|entire|hairy` |
| `winged` | 5 | 8 | `present` |
| `rib` | 5 | 6 | `amount` |
| `cataphyll` | 4 | 57 | `length|deciduous|apiculate|persistent` |
| `bristle` | 4 | 13 | `filiform|length|present|yellow` |
| `leaf scar` | 4 | 10 | `height|inconspicuous|width|prominent` |
| `perianth tube` | 4 | 8 | `length|cylindric|curving|magenta` |
| `main vein` | 4 | 4 | `amount|prominent` |
| `seed cone` | 3 | 46 | `cylindric|purple|sessile|round` |
| `disc` | 3 | 18 | `diameter|annular|thickened|short` |
| `indusium` | 3 | 17 | `thick|diameter|width|brown` |
| `pollen cone` | 3 | 15 | `red|purple|purplish|bluish` |
| `tendril` | 3 | 9 | `long|hirsute|sterile|pubescent` |
| `in alternate spiral` | 3 | 8 | `amount` |
| `in principal spiral` | 3 | 8 | `amount` |
| `node` | 3 | 8 | `amount|swollen|oblique` |
| `per side` | 3 | 8 | `amount` |
| `embryo` | 3 | 7 | `curved|large|broad|glandulose` |
| `lateral nerve` | 3 | 6 | `amount|prominent|branched` |
| `column` | 3 | 5 | `short|length|straight` |
| `cone` | 3 | 5 | `globose|ovoid|pendent|reddish yellow` |
| `axis` | 3 | 4 | `thickened|woody|length|glabrous` |

## Top Cross-Flora Novel PO × PATO / FLOPO Combinations

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Floras | Total Count |
|---|---|---|---|---|---|---:|---:|
| `PO_0030123` | panicle inflorescence | `PATO_0000467` | present | `EQ|PO_0030123|PATO_0000467` | `allowed` / `new_class_candidate` | 20 | 57 |
| `PO_0009049` | inflorescence | `FLOPO_0991000` | axillary | `EQ|PO_0009049|FLOPO_0991000` | `allowed` / `new_class_candidate` | 18 | 50 |
| `PO_0025034` | leaf | `PATO_0001412` | unstructured | `EQ|PO_0025034|PATO_0001412` | `novel` / `new_class_candidate` | 18 | 47 |
| `PO_0025034` | leaf | `PATO_0000389` | acute | `EQ|PO_0025034|PATO_0000389` | `novel` / `new_class_candidate` | 16 | 36 |
| `PO_0025517` | leaf lamina lobe | `PATO_0000070` | amount | `EQ|PO_0025517|PATO_0000070` | `allowed` / `new_class_candidate` | 15 | 25 |
| `PO_0025034` | leaf | `FLOPO_0991023` | petiolate | `EQ|PO_0025034|FLOPO_0991023` | `allowed` / `new_class_candidate` | 13 | 47 |
| `PO_0009046` | flower | `PATO_0000587` | decreased size | `EQ|PO_0009046|PATO_0000587` | `allowed` / `new_class_candidate` | 13 | 18 |
| `PO_0020039` | leaf lamina | `PATO_0000948` | heart shaped | `EQ|PO_0020039|PATO_0000948` | `allowed` / `new_class_candidate` | 11 | 18 |
| `PO_0009049` | inflorescence | `FLOPO_0991003` | solitary | `EQ|PO_0009049|FLOPO_0991003` | `allowed` / `new_class_candidate` | 11 | 15 |
| `PO_0009046` | flower | `FLOPO_0991003` | solitary | `EQ|PO_0009046|FLOPO_0991003` | `allowed` / `new_class_candidate` | 10 | 29 |
| `PO_0009073` | stigma | `FLOPO_0991006` | capitate | `EQ|PO_0009073|FLOPO_0991006` | `allowed` / `new_class_candidate` | 10 | 22 |
| `PO_0009031` | sepal | `PATO_0000389` | acute | `EQ|PO_0009031|PATO_0000389` | `novel` / `new_class_candidate` | 10 | 17 |
| `PO_0020039` | leaf lamina | `PATO_0001412` | unstructured | `EQ|PO_0020039|PATO_0001412` | `novel` / `new_class_candidate` | 9 | 35 |
| `PO_0000003` | whole plant | `FLOPO_0991007` | caespitose | `EQ|PO_0000003|FLOPO_0991007` | `allowed` / `new_class_candidate` | 9 | 26 |
| `PO_0009055` | bract | `PATO_0001730` | deciduous (generic) | `EQ|PO_0009055|PATO_0001730` | `allowed` / `new_class_candidate` | 9 | 17 |
| `PO_0009001` | fruit | `FLOPO_0991062` | ribbed | `EQ|PO_0009001|FLOPO_0991062` | `allowed` / `new_class_candidate` | 9 | 13 |
| `PO_0030112` | pedicel | `PATO_0002212` | slender | `EQ|PO_0030112|PATO_0002212` | `allowed` / `new_class_candidate` | 9 | 13 |
| `PO_0020003` | plant ovule | `PATO_0000070` | amount | `EQ|PO_0020003|PATO_0000070` | `novel` / `new_class_candidate` | 8 | 20 |
| `PO_0009005` | root | `FLOPO_0991027` | fibrous-rooted | `EQ|PO_0009005|FLOPO_0991027` | `allowed` / `new_class_candidate` | 8 | 17 |
| `PO_0020039` | leaf lamina | `PATO_0104010` | papyraceous | `EQ|PO_0020039|PATO_0104010` | `allowed` / `new_class_candidate` | 8 | 14 |
| `PO_0004542` | rhizome | `PATO_0000574` | decreased length | `EQ|PO_0004542|PATO_0000574` | `allowed` / `new_class_candidate` | 8 | 12 |
| `PO_0009010` | seed | `FLOPO_0985004` | winged | `EQ|PO_0009010|FLOPO_0985004` | `allowed` / `new_class_candidate` | 8 | 11 |
| `PO_0025331` | ray flower | `PATO_0000070` | amount | `EQ|PO_0025331|PATO_0000070` | `allowed` / `new_class_candidate` | 7 | 29 |
| `PO_0020049` | leaflet | `PATO_0000070` | amount | `EQC|PO_0020049|2|PATO_0000070` | `allowed` / `new_class_candidate` | 7 | 20 |
| `PO_0009073` | stigma | `FLOPO_0991059` | papillose | `EQ|PO_0009073|FLOPO_0991059` | `allowed` / `new_class_candidate` | 7 | 15 |
| `PO_0020039` | leaf lamina | `PATO_0000389` | acute | `EQ|PO_0020039|PATO_0000389` | `novel` / `new_class_candidate` | 7 | 15 |
| `PO_0025034` | leaf | `FLOPO_0991058` | scabrous | `EQ|PO_0025034|FLOPO_0991058` | `allowed` / `new_class_candidate` | 7 | 14 |
| `PO_0009010` | seed | `PATO_0001866` | prolate | `EQ|PO_0009010|PATO_0001866` | `allowed` / `new_class_candidate` | 7 | 13 |
| `PO_0009074` | style | `PATO_0000574` | decreased length | `EQ|PO_0009074|PATO_0000574` | `allowed` / `new_class_candidate` | 7 | 13 |
| `PO_0009055` | bract | `PATO_0001732` | non-deciduous (any body part) | `EQ|PO_0009055|PATO_0001732` | `novel` / `new_class_candidate` | 7 | 12 |
| `PO_0025034` | leaf | `FLOPO_0991002` | basal | `EQ|PO_0025034|FLOPO_0991002` | `allowed` / `new_class_candidate` | 7 | 11 |
| `PO_0004518` | bark | `FLOPO_0988086` | grayish brown | `EQ|PO_0004518|FLOPO_0988086` | `allowed` / `new_class_candidate` | 7 | 9 |
| `PO_0009001` | fruit | `FLOPO_0991025` | obovoid | `EQ|PO_0009001|FLOPO_0991025` | `allowed` / `new_class_candidate` | 7 | 9 |
| `PO_0009055` | bract | `PATO_0000587` | decreased size | `EQ|PO_0009055|PATO_0000587` | `allowed` / `new_class_candidate` | 7 | 9 |
| `PO_0025034` | leaf | `FLOPO_0985006` | spreading | `EQ|PO_0025034|FLOPO_0985006` | `novel` / `new_class_candidate` | 7 | 7 |
| `PO_0009046` | flower | `FLOPO_0991000` | axillary | `EQ|PO_0009046|FLOPO_0991000` | `allowed` / `new_class_candidate` | 6 | 24 |
| `FLOPO_0986006` | corolla lobe | `PATO_0000122` | length | `EQ|FLOPO_0986006|PATO_0000122` | `allowed` / `new_class_candidate` | 6 | 23 |
| `PO_0005020` | vascular bundle | `PATO_0000070` | amount | `EQC|PO_0005020|2|PATO_0000070` | `allowed` / `new_class_candidate` | 6 | 16 |
| `PO_0009031` | sepal | `PATO_0001408` | ciliated | `EQ|PO_0009031|PATO_0001408` | `allowed` / `new_class_candidate` | 6 | 16 |
| `PO_0025034` | leaf | `PATO_0001408` | ciliated | `EQ|PO_0025034|PATO_0001408` | `allowed` / `new_class_candidate` | 6 | 16 |
