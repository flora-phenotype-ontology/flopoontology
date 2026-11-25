"""Read-only pass: write the accepted non-numeric assertions on pilot plant parts as one TSV.

A statement "X to Y" has no value term; its two ends are in the columns ``rel_from`` and ``rel_to``
(``rel`` names the reading the annotator gave it, e.g. continuum).
"""
import glob
import json
import re
import sys

from flopo2.traitvision import scope

ENT = re.compile(r'^(whole plant|leaf|leaf lamina|leaf margin|leaflet|flower|corolla|corolla lobe|petal|tepal|'
                 r'perianth|fruit|inflorescence|thorn|spine|prickle|leaf spine|stem)$|inflorescence$|fruit$')
out = open(sys.argv[1], 'w')
out.write('taxon\tfamily\trank\tsource\tpo_id\tentity\tattr\tvalues\toperator\tnegated\tfrequency\tqlabel\ttext\trel\trel_from\trel_to\n')
for f in sorted(glob.glob('local-corpora/*/derived/*-annotated.jsonl')):
    src = f.split('/')[1]
    n = 0
    with open(f) as fh:
        for line in fh:
            try:
                r = json.loads(line)
            except Exception:
                continue
            if scope.skip(r, src):
                continue
            for a in r.get('assertions', []):
                if a.get('gate', {}).get('status') != 'accepted':
                    continue
                if a.get('value_low') is not None or a.get('value_high') is not None:
                    continue
                c = a.get('composition') or {}
                el = c.get('entity_label') or ''
                if not ENT.search(el):
                    continue
                if a.get('developmental_stage_contexts') or a.get('bearer_context_qualities'):
                    ctx = 'ctx'
                else:
                    ctx = ''
                vals = a.get('value_terms') or [a.get('pato_id')]
                q = a.get('qualitative_value_relation') or {}
                out.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in (
                    r.get('taxon'), r.get('taxon_family') or '', r.get('taxon_rank') or '', src, a.get('po_id'), el,
                    a.get('pato_id'), '|'.join(vals), a.get('value_operator') + (':' + ctx if ctx else ''),
                    int(bool(a.get('negated'))), a.get('frequency_qualifier') or '', c.get('quality_label') or '',
                    (a.get('source_text') or '')[:80],
                    q.get('interpretation') or '', q.get('from_value') or '', q.get('to_value') or '')) + '\n')
                n += 1
    print(src, n, dict(scope.skip.count), file=sys.stderr, flush=True)
