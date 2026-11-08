# FLOPO Candidate Additions — Kew Monographs & Databases (Kew Bulletin, GrassBase, ILDIS, CATE via POWO) (`powo-kew`)

- **Records processed**: 20
- **Extracted trait rows**: 1,574
- **Formal assertions emitted**: 780
- **Distinct candidate value terms**: 95
- **Distinct candidate anatomical bearers**: 38
- **Distinct novel PO × PATO/FLOPO combinations**: 169

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `glandular-pubescent` | 9 | 3 | `PATO:0000066` (pilosity) | `PO_0009031|PO_0009043|PO_0025034|PO_0009053|PO_0009055` |
| `wine-coloured` | 6 | 1 | `PATO:0000141` (structure) | `PO_0009042|PO_0009053|spathe tube|spathe blade|PO_0009001` |
| `subcoriaceous` | 5 | 4 | `PATO:0000150` (texture) | `cataphyll|PO_0025034` |
| `matte` | 4 | 3 | `PATO:0000141` (structure) | `PO_0025034|PO_0009033` |
| `scandent` | 4 | 3 | `PATO:0000141` (structure) | `PO_0009047|PO_0000003|part` |
| `paler` | 3 | 3 | `PATO:0000141` (structure) | `PO_0020039|PO_0005020|stipe` |
| `showy` | 3 | 3 | `PATO:0000141` (structure) | `PO_0009046` |
| `stained` | 3 | 1 | `PATO:0000141` (structure) | `spathe-tube|spathe-limb|PO_0009072` |
| `boat-shaped` | 2 | 2 | `PATO:0000052` (shape) | `spathe blade|FLOPO_0985017` |
| `divaricate` | 2 | 2 | `PATO:0000052` (shape) | `PO_0009069` |
| `epiphytic` | 2 | 2 | `PATO:0000141` (structure) | `PO_0000003` |
| `flexuous` | 2 | 2 | `PATO:0000141` (structure) | `part:|PO_0009047` |
| `flushed` | 2 | 1 | `PATO:0000141` (structure) | `PO_0009077|bristle` |
| `foliaceous` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009055` |
| `narrowed` | 2 | 1 | `PATO:0000141` (structure) | `PO_0020039|PO_0009001` |
| `obscure` | 2 | 2 | `PATO:0000141` (structure) | `PO_0005020|PO_0025034` |
| `one-flowered` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009049` |
| `plano-convex` | 2 | 1 | `PATO:0000141` (structure) | `PO_0009010|PO_0020030` |
| `prismatic` | 2 | 1 | `PATO:0000141` (structure) | `PO_0009062|PO_0009074` |
| `semiglossy` | 2 | 1 | `PATO:0000141` (structure) | `PO_0009033|PO_0025034` |
| `subobtuse` | 2 | 1 | `PATO:0000141` (structure) | `limb|PO_0009031` |
| `terrestrial` | 2 | 2 | `PATO:0000141` (structure) | `PO_0000003` |
| `visible` | 2 | 2 | `PATO:0000141` (structure) | `PO_0005020` |
| `abundant` | 1 | 1 | `PATO:0000141` (structure) | `gland` |
| `accrescent` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009060` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `spathe` | 49 | 10 | `length|wide|width|purple|pale green` |
| `cataphyll` | 17 | 5 | `length|apiculate|persistent|deciduous|thin` |
| `spathe-limb` | 8 | 1 | `ovate|pale|stained purple|mid-green|purple` |
| `spathe blade` | 6 | 2 | `long|cream|glossy|open|pale yellowish-green` |
| `primary lateral vein` | 5 | 3 | `amount|sunken|raised|straight` |
| `interstice` | 4 | 1 | `yellow|long|grooved|absent` |
| `rachis` | 4 | 2 | `terete|tomentose|long|angular` |
| `spathe tube` | 4 | 2 | `glossy|closed|pale pink|pale purple` |
| `spathe-tube` | 4 | 1 | `greenish white|mid-green|constricted` |
| `apiculus` | 3 | 1 | `green|recurving|length` |
| `basal vein` | 3 | 2 | `amount|free` |
| `base` | 3 | 2 | `yellow|smooth|narrowly attenuate` |
| `bristle` | 3 | 1 | `filiform|deep yellow|length` |
| `column` | 3 | 2 | `length|short` |
| `geniculum` | 3 | 2 | `length|thickened` |
| `in alternate spiral` | 3 | 3 | `amount` |
| `in principal spiral` | 3 | 3 | `amount` |
| `per side` | 3 | 3 | `amount` |
| `stipe` | 3 | 2 | `length|absent` |
| `appendix` | 2 | 1 | `clavate|stipitate` |
| `female zone` | 2 | 1 | `oblong-elliptic|diameter` |
| `limb` | 2 | 1 | `ovate|white` |
| `margin` | 2 | 2 | `hairy|ciliolate` |
| `pistil` | 2 | 2 | `exserted|green` |
| `sheath` | 2 | 1 | `amount|tubular` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0009031` | sepal | `PATO_0001408` | ciliated | `EQ|PO_0009031|PATO_0001408` | `allowed` / `new_class_candidate` | 7 | 4 |
| `PO_0030120` | spadix inflorescence | `PATO_0000122` | length | `EQ|PO_0030120|PATO_0000122` | `novel` / `new_class_candidate` | 7 | 6 |
| `PO_0009053` | peduncle | `PATO_0104016` | terete | `EQ|PO_0009053|PATO_0104016` | `novel` / `new_class_candidate` | 5 | 5 |
| `FLOPO_0985017` | corolla lip | `PATO_0000122` | length | `EQ|FLOPO_0985017|PATO_0000122` | `novel` / `new_class_candidate` | 4 | 4 |
| `FLOPO_0985017` | corolla lip | `PATO_0000921` | width | `EQ|FLOPO_0985017|PATO_0000921` | `novel` / `new_class_candidate` | 4 | 4 |
| `FLOPO_0985017` | corolla lip | `PATO_0000406` | curved | `EQ|FLOPO_0985017|PATO_0000406` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0004542` | rhizome | `PATO_0000574` | decreased length | `EQ|PO_0004542|PATO_0000574` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0009032` | petal | `FLOPO_0985003` | reflexed | `EQ|PO_0009032|FLOPO_0985003` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0009032` | petal | `PATO_0002445` | torsioned | `EQ|PO_0009032|PATO_0002445` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0020038` | petiole | `PATO_0104016` | terete | `EQ|PO_0020038|PATO_0104016` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0020039` | leaf lamina | `PATO_0000600` | increased width | `EQ|PO_0020039|PATO_0000600` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025034` | leaf | `PATO_0000600` | increased width | `EQ|PO_0025034|PATO_0000600` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0025034` | leaf | `FLOPO_0985015` | plicate | `EQ|PO_0025034|FLOPO_0985015` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0030120` | spadix inflorescence | `PATO_0001334` | diameter | `EQ|PO_0030120|PATO_0001334` | `novel` / `new_class_candidate` | 3 | 2 |
| `PO_0030120` | spadix inflorescence | `PATO_0001500` | tapered | `EQ|PO_0030120|PATO_0001500` | `novel` / `new_class_candidate` | 3 | 3 |
| `FLOPO_0985017` | corolla lip | `FLOPO_0988009` | white | `EQ|FLOPO_0985017|FLOPO_0988009` | `novel` / `new_class_candidate` | 2 | 2 |
| `FLOPO_0985017` | corolla lip | `PATO_0002007` | convex 3-D shape | `QUALREL|FLOPO_0985017|PATO_0002007|continuum|PATO_0001866|FLOPO_0991025` | `novel` / `structured_annotation_only` | 2 | 2 |
| `PO_0005020` | vascular bundle | `PATO_0000070` | amount | `EQC|PO_0005020|2|PATO_0000070` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009047` | stem | `FLOPO_0991012` | leafy | `EQ|PO_0009047|FLOPO_0991012` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0020003` | plant ovule | `PATO_0000070` | amount | `EQ|PO_0020003|PATO_0000070` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0020038` | petiole | `FLOPO_0991061` | sulcate | `EQ|PO_0020038|FLOPO_0991061` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0020039` | leaf lamina | `PATO_0000948` | heart shaped | `EQ|PO_0020039|PATO_0000948` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0030120` | spadix inflorescence | `FLOPO_0988008` | purple | `EQ|PO_0030120|FLOPO_0988008` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0030120` | spadix inflorescence | `FLOPO_0991065` | stipitate | `EQ|PO_0030120|FLOPO_0991065` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0030120` | spadix inflorescence | `PATO_0001873` | cylindrical | `EQ|PO_0030120|PATO_0001873` | `novel` / `new_class_candidate` | 2 | 2 |
