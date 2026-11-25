"""Read-only pass: the accepted counts ("petals 5", "leaflets 3-7") that the floras state, as one TSV.

Counterpart of ``extract_measures.py`` (measurements with a unit) and ``extract.py`` (non-numeric statements):
assertions with unit ``count``, every plant part.

    python3 -m flopo2.traitvision.extract_counts local-corpora/trait-vision/counts-all.tsv
"""
import glob
import json
import sys

from flopo2.traitvision import scope


def main(path):
    out = open(path, 'w')
    out.write('taxon\tfamily\trank\tsource\tpo_id\tentity\tlow\thigh\tqualifier\tfrequency\tctx\ttext\n')
    for f in sorted(glob.glob('local-corpora/*/derived/*-annotated.jsonl')):
        src = f.split('/')[1]
        n = 0
        with open(f) as fh:
            for line in fh:
                if '"count"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if scope.skip(r, src):
                    continue
                for a in r.get('assertions', []):
                    if a.get('gate', {}).get('status') != 'accepted' or a.get('negated') or a.get('unit') != 'count':
                        continue
                    lo, hi = a.get('value_low'), a.get('value_high')
                    if lo is None and hi is None:
                        continue
                    c = a.get('composition') or {}
                    ctx = 'ctx' if a.get('developmental_stage_contexts') or a.get('bearer_context_qualities') else ''
                    out.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in (
                        r.get('taxon'), r.get('taxon_family') or '', r.get('taxon_rank') or '', src, a.get('po_id'),
                        c.get('entity_label') or a.get('raw_entity_text') or '', '' if lo is None else f'{lo:g}',
                        '' if hi is None else f'{hi:g}', a.get('value_qualifier') or '', a.get('frequency_qualifier') or '',
                        ctx, (a.get('source_text') or '')[:60])) + '\n')
                    n += 1
        print(src, n, flush=True)
    out.close()


if __name__ == '__main__':
    main(sys.argv[1])
