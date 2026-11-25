"""Read-only pass: the accepted measurements (number + unit) that the floras state, as one TSV.

Counterpart of ``extract.py`` (which keeps the non-numeric statements). Kept: size measurements of the whole
plant, stem, leaf (lamina, leaflet), flower, fruit and seed, in the unit the flora gives, converted to metres.

    python3 -m flopo2.traitvision.extract_measures local-corpora/trait-vision/measures-all.tsv
"""
import glob
import json
import re
import sys

from flopo2.traitvision import scope

ENT = re.compile(r'^(whole plant|stem|trunk|leaf|leaf lamina|leaflet|flower|corolla|petal|fruit|seed)$')
METRES = {'mm': 1e-3, 'cm': 1e-2, 'dm': 0.1, 'm': 1.0, 'µm': 1e-6, 'um': 1e-6, 'μm': 1e-6, 'in': 0.0254, 'ft': 0.3048}


def main(path):
    out = open(path, 'w')
    out.write('taxon\tfamily\trank\tsource\tpo_id\tentity\tattr\tquality\tlow_m\thigh_m\tunit\tqualifier\tctx\ttext\n')
    for f in sorted(glob.glob('local-corpora/*/derived/*-annotated.jsonl')):
        src = f.split('/')[1]
        n = 0
        with open(f) as fh:
            for line in fh:
                if '"value_high"' not in line and '"value_low"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if scope.skip(r, src):
                    continue
                for a in r.get('assertions', []):
                    if a.get('gate', {}).get('status') != 'accepted' or a.get('negated'):
                        continue
                    lo, hi = a.get('value_low'), a.get('value_high')
                    k = METRES.get((a.get('unit') or '').strip())
                    if (lo is None and hi is None) or k is None:
                        continue
                    c = a.get('composition') or {}
                    el = c.get('entity_label') or ''
                    if not ENT.search(el):
                        continue
                    ctx = 'ctx' if a.get('developmental_stage_contexts') or a.get('bearer_context_qualities') else ''
                    out.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in (
                        r.get('taxon'), r.get('taxon_family') or '', r.get('taxon_rank') or '', src, a.get('po_id'), el,
                        a.get('pato_id'), c.get('quality_label') or a.get('raw_quality_text') or '',
                        '' if lo is None else f'{lo * k:.6g}', '' if hi is None else f'{hi * k:.6g}', a.get('unit'),
                        a.get('value_qualifier') or '', ctx, (a.get('source_text') or '')[:60])) + '\n')
                    n += 1
        print(src, n, flush=True)
    out.close()


if __name__ == '__main__':
    main(sys.argv[1])
