"""Check a sample of the trait values taken from the floras with a larger model reading the source text.

``prepare``  a random sample of the accepted statements behind every trait used for the photographs (26 categorical
             traits, the sizes, the counts): the passage of the flora with the statement marked, and the value our
             pipeline took from it, in plain words. Batches of 30 under ``local-corpora/trait-vision/judge/``.
``run``      each batch to the judge (``claude-max -p --model opus``); stops when the account is out of credit.
``collect``  per trait: share judged correct (Wilson 95% interval) and the kinds of error; ``judge-results.tsv``.

The judge sees the taxon, the passage and the claim, and answers: correct / wrong_value / wrong_part / not_stated /
restricted (true only of a stage, sex, position or as an exception, but taken as a general statement) / unclear.

    python -m flopo2.traitvision.judge_extraction prepare [--per-trait 100]
    python -m flopo2.traitvision.judge_extraction run [--workers 3] [--limit N]
    python -m flopo2.traitvision.judge_extraction collect
"""
import argparse
import collections
import csv
import glob
import json
import math
import random
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flopo2.traitvision import labels as L
from flopo2.traitvision import labels_extra as X

OUT = Path('local-corpora/trait-vision/judge')
SIZE_TRAITS = {v[0] for v in X.RULES.values()}
VERDICTS = ('correct', 'wrong_value', 'wrong_part', 'not_stated', 'restricted', 'unclear')
PROMPT = """You are checking a database of plant traits that was extracted automatically from floras (taxonomic descriptions).
For each item below you get the taxon, a passage of the flora with the statement the extraction used marked as «...», and the
CLAIM the database makes about the taxon on the basis of that statement. Judge only whether the passage supports the claim.

Verdicts:
- correct      the passage states this of the taxon (botanical synonyms and the stated grouping of values count as correct:
               e.g. "serrate" -> margin toothed, "leathery" -> coriaceous, "scarlet" -> red, "suborbicular" -> round)
- wrong_value  the passage is about this part and this property, but the value is different
- wrong_part   the value is stated, but of another part or another property (e.g. the bract, not the leaf; the base, not the apex)
- not_stated   the passage does not say this at all (e.g. it denies it, or it concerns another taxon)
- restricted   stated only of a developmental stage, a sex, a position on the plant, or as a rare exception, but claimed in general
- unclear      the passage is too short or garbled to tell

For a size or a count the claim gives the range taken from the statement; it is correct when the numbers and the unit match
the statement and they measure the named part and dimension. Do not use any tools. Answer with a JSON array only, one object
per item, in the order given: {"id": "...", "verdict": "...", "note": "at most 12 words, empty when correct"}.

ITEMS
"""
WORDS = {'habit': 'growth habit', 'spines': 'spines, thorns or prickles', 'leaf_hair': 'leaf hairiness', 'stem_hair': 'stem hairiness',
         'posture': 'posture of the plant or stem', 'substrate': 'where the plant grows (epiphytic or terrestrial)',
         'flower_position': 'position of the flowers or inflorescences', 'leaf_complexity': 'leaf simple or compound',
         'leaf_position': 'leaves basal or cauline', 'leaf_attachment': 'leaves sessile or petiolate'}


def claims(rec, a):
    """(trait, plain-word claim) for one accepted assertion."""
    c = a.get('composition') or {}
    el = c.get('entity_label') or ''
    lo, hi, unit = a.get('value_low'), a.get('value_high'), (a.get('unit') or '').strip()
    ctx = bool(a.get('developmental_stage_contexts') or a.get('bearer_context_qualities'))
    if lo is not None or hi is not None:
        if a.get('negated') or ctx:
            return []
        rng = f'{lo:g}-{hi:g}' if lo is not None and hi is not None and lo != hi else f'{(hi if hi is not None else lo):g}'
        if unit == 'count' and el in X.COUNTS:
            return [(X.COUNTS[el], f'number of {el}s: {rng}')]
        rule = X.RULES.get((el, c.get('quality_label') or a.get('raw_quality_text') or ''))
        if rule and unit in ('mm', 'cm', 'dm', 'm'):
            return [(rule[0], f"{el} {c.get('quality_label') or a.get('raw_quality_text')}: {rng} {unit}")]
        return []
    q = a.get('qualitative_value_relation') or {}
    row = {'entity': el, 'attr': a.get('pato_id'), 'values': '|'.join(a.get('value_terms') or [a.get('pato_id') or '']),
           'operator': (a.get('value_operator') or '') + (':ctx' if ctx else ''), 'negated': str(int(bool(a.get('negated')))),
           'frequency': a.get('frequency_qualifier') or '', 'qlabel': c.get('quality_label') or '', 'text': (a.get('source_text') or '')[:80]}
    if row['frequency'] in L.RARE:
        return []
    out = []
    for trait, cls in set(L.classes(row, claims.sup) + X.classes(row)):
        if trait != 'leaflet_shape':
            out.append((trait, f"{WORDS.get(trait, trait.replace('_', ' '))}: {cls}"))
    return out


def prepare(a):
    claims.sup = L.ontology()
    rng = random.Random(20261123)
    pool, seen = collections.defaultdict(list), collections.Counter()
    for f in sorted(glob.glob('local-corpora/*/derived/*-annotated.jsonl')):
        src = f.split('/')[1]
        with open(f) as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if (r.get('taxon_rank') or '') != 'species':
                    continue
                text = r.get('text') or ''
                for s in r.get('assertions', []):
                    if s.get('gate', {}).get('status') != 'accepted':
                        continue
                    for trait, claim in claims(r, s):
                        seen[trait] += 1
                        n = a.per_trait if not trait.startswith('n_') and trait not in SIZE_TRAITS else a.per_size
                        if len(pool[trait]) < n:
                            pool[trait].append(None); k = len(pool[trait]) - 1
                        else:
                            k = rng.randrange(seen[trait])
                            if k >= n:
                                continue
                        st = s.get('source_text') or ''
                        i = text.find(st) if st else -1
                        passage = (text[max(0, i - 300):i] + '«' + st + '»' + text[i + len(st):i + len(st) + 300]) if i >= 0 else f'«{st}»'
                        item = {'trait': trait, 'source': src, 'taxon': r.get('taxon'), 'claim': claim, 'passage': passage}
                        pool[trait][k] = item
        print(src, sum(len(v) for v in pool.values()), flush=True)
    items = [it for v in pool.values() for it in v if it]
    rng.shuffle(items)
    OUT.mkdir(parents=True, exist_ok=True)
    for n, it in enumerate(items):
        it['id'] = f'j{n:05d}'
    (OUT / 'items.json').write_text(json.dumps(items, indent=0) + '\n')
    for b in range(0, len(items), 30):
        body = '\n'.join(f"id: {it['id']}\ntaxon: {it['taxon']}\npassage: {it['passage']}\nCLAIM: {it['claim']}\n" for it in items[b:b + 30])
        (OUT / f'batch-{b // 30:04d}.txt').write_text(PROMPT + body)
    print('items', len(items), 'batches', math.ceil(len(items) / 30), {t: len(v) for t, v in sorted(pool.items())})


LIMIT = re.compile(r'usage limit|limit reached|out of (extra )?usage|credit balance|rate.?limit|overloaded|quota', re.I)


def one(path, a):
    ans = path.with_suffix('.answer.json')
    if ans.exists():
        return 'done'
    try:
        done = subprocess.run([a.command, '-p', '--model', a.model, '--output-format', 'json'], input=path.read_text(),
                              capture_output=True, text=True, timeout=a.timeout, cwd=str(OUT))
        result = json.loads(done.stdout).get('result', '')
    except Exception as e:
        result = f'failed: {e}'
    m = re.search(r'\[.*\]', result, re.S)
    try:
        rows = json.loads(m.group(0))
        assert all('id' in r and r.get('verdict') in VERDICTS for r in rows)
    except Exception:
        path.with_suffix('.error.txt').write_text(result[:3000])
        return 'limit' if LIMIT.search(result[:600]) else 'failed'
    ans.write_text(json.dumps(rows, indent=0) + '\n')
    return 'done'


def run(a):
    batches = sorted(OUT.glob('batch-*.txt'))[:a.limit or None]
    stop = False
    with ThreadPoolExecutor(a.workers) as ex:
        for b, status in zip(batches, ex.map(lambda p: 'skipped' if stop else one(p, a), batches)):
            print(b.name, status, flush=True)
            stop = stop or status == 'limit'


def collect(a):
    items = {it['id']: it for it in json.loads((OUT / 'items.json').read_text())}
    by = collections.defaultdict(collections.Counter)
    with open(OUT / 'judge-results.tsv', 'w') as f:
        f.write('id\ttrait\tsource\ttaxon\tclaim\tverdict\tnote\n')
        for p in sorted(OUT.glob('batch-*.answer.json')):
            for r in json.loads(p.read_text()):
                it = items.get(r['id'])
                if it:
                    by[it['trait']][r['verdict']] += 1
                    by['ALL'][r['verdict']] += 1
                    by['source ' + it['source']][r['verdict']] += 1
                    f.write('\t'.join(str(x).replace('\t', ' ').replace('\n', ' ') for x in (r['id'], it['trait'], it['source'], it['taxon'], it['claim'], r['verdict'], r.get('note', ''))) + '\n')
    out = {}
    for t, c in sorted(by.items()):
        n = sum(c.values()) - c['unclear']
        if n < (20 if t.startswith('source ') else 1):
            continue
        p = c['correct'] / n
        z = 1.96
        mid, half = (p + z * z / 2 / n) / (1 + z * z / n), z * math.sqrt(p * (1 - p) / n + z * z / 4 / n / n) / (1 + z * z / n)
        out[t] = {'judged': n, 'correct': p, 'low': mid - half, 'high': mid + half, **{v: c[v] for v in VERDICTS}}
        print(f"{t:24s} n={n:5d} correct {p:.3f} ({mid - half:.3f}-{mid + half:.3f})  " + '  '.join(f'{v} {c[v]}' for v in VERDICTS[1:] if c[v]))
    (OUT / 'judge-summary.json').write_text(json.dumps(out, indent=1) + '\n')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=('prepare', 'run', 'collect'))
    p.add_argument('--per-trait', type=int, default=100)
    p.add_argument('--per-size', type=int, default=50)
    p.add_argument('--workers', type=int, default=3)
    p.add_argument('--limit', type=int, default=0)
    p.add_argument('--command', default='claude-max')
    p.add_argument('--model', default='opus')
    p.add_argument('--timeout', type=int, default=1500)
    a = p.parse_args()
    {'prepare': prepare, 'run': run, 'collect': collect}[a.mode](a)


if __name__ == '__main__':
    main()
