# FLOPO Candidate Additions — North American Flora Monographs (New York Botanical Garden) (`nybg-naf`)

- **Records processed**: 20
- **Extracted trait rows**: 764
- **Formal assertions emitted**: 241
- **Distinct candidate value terms**: 54
- **Distinct candidate anatomical bearers**: 41
- **Distinct novel PO × PATO/FLOPO combinations**: 62

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `autoicous` | 10 | 10 | `PATO:0000141` (structure) | `PO_0000003` |
| `thick-walled` | 6 | 5 | `PATO:0000141` (structure) | `leaf cell|annulus cell|cell` |
| `double` | 4 | 4 | `PATO:0000141` (structure) | `PO_0030042|preperistome|annulus` |
| `nodose` | 4 | 4 | `PATO:0000141` (structure) | `leaf cell wall|basal cell wall` |
| `united` | 4 | 4 | `PATO:0001435` (attachment quality) | `PO_0030043|PO_0030042` |
| `nannandrous` | 3 | 3 | `PATO:0000141` (structure) | `PO_0000003` |
| `percurrent` | 3 | 3 | `PATO:0000141` (structure) | `PO_0030072|part:` |
| `depressed-globose` | 2 | 2 | `PATO:0000052` (shape) | `oospore|oogonium` |
| `gynandrosporous` | 2 | 2 | `PATO:0000141` (structure) | `PO_0000003` |
| `immersed` | 2 | 2 | `PATO:0000141` (structure) | `PO_0030091` |
| `narrowed` | 2 | 2 | `PATO:0000141` (structure) | `PO_0030091` |
| `operculate` | 2 | 2 | `PATO:0000052` (shape) | `oogonium` |
| `annulate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0030037` |
| `appendiculate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0030043` |
| `arranged in lines` | 1 | 1 | `PATO:0000141` (structure) | `peristome papilla` |
| `bistratose` | 1 | 1 | `PATO:0000141` (structure) | `leaf cell` |
| `broadly acute` | 1 | 1 | `PATO:0000141` (structure) | `PO_0025034` |
| `conic-rostellate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0030044` |
| `distinct` | 1 | 1 | `PATO:0001435` (attachment quality) | `oogonium` |
| `emergent` | 1 | 1 | `PATO:0000141` (structure) | `PO_0030091` |
| `ending below the apex` | 1 | 1 | `PATO:0000141` (structure) | `PO_0030072` |
| `epigynous` | 1 | 1 | `PATO:0000141` (structure) | `androsporangium` |
| `filling` | 1 | 1 | `PATO:0000141` (structure) | `oospore` |
| `fragmentary` | 1 | 1 | `PATO:0000141` (structure) | `preperistome` |
| `geminate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0030043` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `leaf cell` | 45 | 10 | `rounded|papillose|isodiametric|rectangular|smooth` |
| `annulus` | 10 | 9 | `present|persistent|long|amount` |
| `annulus cell` | 9 | 4 | `amount|rounded|incrassate|small` |
| `oogonium` | 9 | 6 | `obovoid|globose|amount|erect|terminal` |
| `exothecial cell` | 8 | 8 | `differentiated|uniform|scarcely differentiated|long|oblong` |
| `basal cell` | 7 | 3 | `smooth|rectangular|linear|oblong|translucent` |
| `spore` | 7 | 6 | `papillose|large` |
| `fi` | 5 | 2 | `amount` |
| `oospore` | 5 | 5 | `scrobiculate|globose|smooth` |
| `/*` | 4 | 2 | `amount` |
| `capsule neck` | 4 | 4 | `long|short` |
| `ju` | 4 | 1 | `amount` |
| `neck` | 4 | 2 | `long|wrinkled|tapering|short` |
| `oogonia` | 4 | 4 | `amount` |
| `cell` | 3 | 2 | `quadrate|rounded|amount` |
| `segment` | 3 | 2 | `amount|smooth` |
| `sporewall` | 3 | 3 | `smooth|areolate|angulate` |
| `/i` | 2 | 1 | `amount` |
| `endostome segment` | 2 | 1 | `amount|erose` |
| `papilla` | 2 | 2 | `simple` |
| `terminal cell` | 2 | 2 | `apiculate|obtuse` |
| `androsporangia` | 1 | 1 | `amount` |
| `androsporangium` | 1 | 1 | `amount` |
| `articulation` | 1 | 1 | `amount` |
| `band` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0002000` | stomatal complex | `PATO_0001665` | superficial | `EQ|PO_0002000|PATO_0001665` | `novel` / `new_class_candidate` | 11 | 11 |
| `PO_0030043` | peristome tooth | `FLOPO_0991059` | papillose | `EQ|PO_0030043|FLOPO_0991059` | `novel` / `new_class_candidate` | 10 | 7 |
| `PO_0025515` | phyllome lamina tooth | `PATO_0000070` | amount | `EQ|PO_0025515|PATO_0000070` | `novel` / `new_class_candidate` | 9 | 9 |
| `PO_0030037` | spore capsule calyptra | `PATO_0000454` | hairy | `EQ|PO_0030037|PATO_0000454` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0030091` | capsule fruit | `PATO_0000052` | shape | `QUALREL|PO_0030091|PATO_0000052|continuum|PATO_0001873|PATO_0000946` | `novel` / `structured_annotation_only` | 7 | 7 |
| `PO_0000003` | whole plant | `FLOPO_0991007` | caespitose | `EQ|PO_0000003|FLOPO_0991007` | `allowed` / `new_class_candidate` | 5 | 5 |
| `PO_0020128` | leaf margin | `PATO_0002211` | recurved | `EQ|PO_0020128|PATO_0002211` | `novel` / `new_class_candidate` | 5 | 5 |
| `PO_0030044` | spore capsule operculum | `FLOPO_0991028` | beaked | `EQ|PO_0030044|FLOPO_0991028` | `novel` / `new_class_candidate` | 5 | 5 |
| `PO_0025034` | leaf | `PATO_0000389` | acute | `EQ|PO_0025034|PATO_0000389` | `novel` / `new_class_candidate` | 4 | 4 |
| `PO_0030043` | peristome tooth | `PATO_0002112` | perforate | `EQ|PO_0030043|PATO_0002112` | `novel` / `new_class_candidate` | 4 | 4 |
| `PO_0030091` | capsule fruit | `PATO_0000623` | exserted | `EQ|PO_0030091|PATO_0000623` | `novel` / `new_class_candidate` | 4 | 4 |
| `PO_0000084` | plant sperm cell | `PATO_0000070` | amount | `EQ|PO_0000084|PATO_0000070` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025034` | leaf | `PATO_0002522` | keel-shaped | `EQ|PO_0025034|PATO_0002522` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025125` | antheridium | `PATO_0000070` | amount | `EQ|PO_0025125|PATO_0000070` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025125` | antheridium | `PATO_0000122` | length | `EQ|PO_0025125|PATO_0000122` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025125` | antheridium | `PATO_0000921` | width | `EQ|PO_0025125|PATO_0000921` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0030043` | peristome tooth | `FLOPO_0991004` | paired | `EQ|PO_0030043|FLOPO_0991004` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0030043` | peristome tooth | `PATO_0000070` | amount | `EQ|PO_0030043|PATO_0000070` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0030043` | peristome tooth | `PATO_0000140` | position | `EQV|PO_0030043|ONE_OF|FLOPO_0985006&PATO_0000622` | `novel` / `annotation_extension_only` | 3 | 2 |
| `PO_0030044` | spore capsule operculum | `PATO_0000052` | shape | `QUALREL|PO_0030044|PATO_0000052|continuum|PATO_0002021|PATO_0000944` | `novel` / `structured_annotation_only` | 3 | 3 |
| `PO_0000003` | whole plant | `FLOPO_0988022` | olive green | `EQ|PO_0000003|FLOPO_0988022` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0000003` | whole plant | `PATO_0001357` | pulvinate | `EQ|PO_0000003|PATO_0001357` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0030037` | spore capsule calyptra | `FLOPO_0985015` | plicate | `EQ|PO_0030037|FLOPO_0985015` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0030043` | peristome tooth | `PATO_0000122` | length | `EQ|PO_0030043|PATO_0000122` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0030043` | peristome tooth | `PATO_0001199` | linear | `EQ|PO_0030043|PATO_0001199` | `novel` / `new_class_candidate` | 2 | 2 |
