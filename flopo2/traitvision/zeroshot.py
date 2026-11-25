"""Baselines without training: BioCLIP 2 image and text embeddings alone, on the same test as ``baseline_v2.py``.

``texts``  (local) for every photographed species the sentences of its flora descriptions, names removed
           (``flora-texts.tsv``: taxon, sentence; at most CHUNKS sentences per species).
``run``    (GPU) four baselines, same observations and candidates as ``baseline_v2.py`` (same sampling):

* trait prompts   every value of every trait as a prompt ("a photo of a plant; leaf shape: ovate"); a photograph's
                  answer is the softmax over the values. Written as ``pred-<trait>.npz`` so that ``baseline_v2.py
                  --reuse`` runs its identification on them; per-trait balanced accuracy on the agreed species here.
* trait text      the candidate's flora values as text, one sentence per trait; similarity to the photographs.
* flora text      the candidate's flora description, sentence by sentence; similarity to the photographs.
* species name    "a photo of <name>": what BioCLIP 2 knows from its own training on names (an upper reference,
                  not a competitor: it uses the name, which the trait model never sees).

    python -m flopo2.traitvision.zeroshot texts ~/tmp/flopo-trait-vision/photo-taxa.txt
    python zeroshot.py run --data DIR --model DIR --out DIR
"""
import argparse
import collections
import csv
import glob
import json
import re
import sys
from pathlib import Path

CHUNKS = 24
WORDS = {'habit': 'growth habit', 'spines': 'spines, thorns or prickles', 'leaf_hair': 'leaf hairs', 'stem_hair': 'stem hairs',
         'posture': 'posture of the stem', 'substrate': 'growing', 'flower_position': 'position of the flowers',
         'leaf_complexity': 'leaf', 'leaf_position': 'leaves', 'leaf_attachment': 'leaves', 'life_span': 'life span',
         'leaf_persistence': 'leaves', 'spines:absent': 'none', 'spines:present': 'present'}


def texts(taxa_file):
    from flopo2.traitvision import scope
    here = Path('local-corpora/trait-vision')
    want = set(Path(taxa_file).expanduser().read_text().split('\n'))
    name = {r['taxon']: r['accepted'] for r in csv.DictReader(open(here / 'taxon-names-v3.tsv'), delimiter='\t')}
    out = collections.defaultdict(list)
    for f in sorted(glob.glob('local-corpora/*/derived/*-annotated.jsonl')):
        src = f.split('/')[1]
        for line in open(f):
            try:
                r = json.loads(line)
            except Exception:
                continue
            t = r.get('taxon') or ''
            if (r.get('taxon_rank') or 'species') != 'species' or not re.match(r'[A-Z][a-z-]+ [a-z-]+( |$)', t) or scope.skip(r, src):
                continue
            acc = name.get(t) or ' '.join(t.split()[:2])
            if acc not in want or len(out[acc]) >= CHUNKS:
                continue
            banned = {w.lower() for w in (t + ' ' + acc).split() if len(w) > 3}
            for s in re.split(r'(?<=[a-z0-9\)])[.;] +', r.get('text') or ''):
                s = ' '.join(s.split())
                low = set(re.findall(r'[a-z-]+', s.lower()))
                if (len(s.split()) < 4 or low & banned or re.search(r'\b[A-Z]\. ?[a-z]{3,}|\b(var|subsp|ssp|syn|sensu|auct)\b\.?|[12][0-9]{3}', s)
                        or len(re.findall(r'\b[A-Z][a-z]+', s)) > 2):
                    continue                                   # names, synonyms, authors, citations
                if len(out[acc]) < CHUNKS:
                    out[acc].append(s[:400])
        print(src, len(out), flush=True)
    with open(here / 'flora-texts.tsv', 'w') as fh:
        fh.write('taxon\ttext\n')
        for t in sorted(out):
            for s in out[t]:
                fh.write(f'{t}\t{s}\n')
    print('species', len(out), 'sentences', sum(len(v) for v in out.values()))


def phrase(trait, cls):
    return f"{WORDS.get(trait, trait.replace('_', ' '))}: {WORDS.get(trait + ':' + cls, cls.replace('_', ' '))}"


def run(a):
    import numpy as np
    import open_clip
    import torch
    import baseline_v2 as B
    import regime_tests as R
    import train as T
    D, DEV = a.data, 'cuda'
    a.out.mkdir(parents=True, exist_ok=True)
    model, _, _ = open_clip.create_model_and_transforms('ViT-L-14', pretrained=str(a.model / 'open_clip_model.safetensors'), device=DEV)
    tok = open_clip.get_tokenizer('ViT-L-14')
    model.eval()

    def encode(strings):
        out = []
        with torch.no_grad(), torch.autocast('cuda'):
            for i in range(0, len(strings), 2048):
                out.append(torch.nn.functional.normalize(model.encode_text(tok(strings[i:i + 2048]).to(DEV)).float(), dim=-1))
        return torch.cat(out) if out else torch.zeros(0, 768, device=DEV)

    emb, ids = T.load_embeddings(D / 'emb')
    row_of = {}
    for n, i in enumerate(ids):
        row_of.setdefault(int(i), n)
    pid, taxa, obs_of = [], [], []
    for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
        if int(r['photo_id']) in row_of:
            pid.append(int(r['photo_id'])); taxa.append(r['taxon']); obs_of.append(r['observation_uuid'])
    pid, taxa = np.array(pid), np.array(taxa)
    N = len(pid)
    x = torch.nn.functional.normalize(torch.from_numpy(emb[[row_of[i] for i in pid]]).to(DEV).float(), dim=-1)
    del emb
    labels_, family = collections.defaultdict(dict), {}
    for r in csv.DictReader(open(D / 'labels-v5.tsv'), delimiter='\t'):
        labels_[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
        family.setdefault(r['taxon'], r['family'])
    agreed = collections.defaultdict(dict)
    for r in csv.DictReader(open(D / 'agreed-v5.tsv'), delimiter='\t'):
        if int(r['floras']) >= 2:
            agreed[r['trait']][r['taxon']] = r['value']
    onames, oinv = np.unique(np.array(obs_of), return_inverse=True)
    names, inv = np.unique(taxa, return_inverse=True)
    scale = float(model.logit_scale.exp())
    report = {'traits': {}}

    # ---- trait prompts
    ref = json.loads((a.ref / 'baseline-v2.json').read_text())
    for trait in sorted(labels_):
        z = np.load(a.ref / f'pred-{trait}.npz')
        classes = [str(c) for c in z['classes']]
        t = encode([f'a photo of a plant; {phrase(trait, c)}' for c in classes])
        prob = torch.cat([torch.softmax(scale * x[i:i + 65536] @ t.T, 1) for i in range(0, N, 65536)])
        g = torch.zeros(len(names), len(classes), device=DEV).index_add_(0, torch.from_numpy(inv).to(DEV), prob)
        guess = g.argmax(1).cpu().numpy()
        pairs = [(agreed[trait][s], classes[guess[n]]) for n, s in enumerate(names) if agreed[trait].get(s) in classes]
        sc = R.bal(pairs)
        report['traits'][trait] = {'agreed': sc, 'n_agreed': len(pairs), 'observers': None, 'n_observers': 0, 'trained': ref['traits'][trait]['agreed']}
        print(f"RESULT {trait:17s} agreed (n={len(pairs)}) prompts {sc:.3f}   trained {ref['traits'][trait]['agreed']:.3f}", flush=True)
        np.savez(a.out / f'pred-{trait}.npz', photo_ids=pid, prob=prob.cpu().numpy().astype(np.float16), classes=np.array(classes), chosen=z['chosen'])
    (a.out / 'baseline-v2.json').write_text(json.dumps(report, indent=1) + '\n')

    # ---- candidates' texts against the observations: the sampling of baseline_v2.py
    flora = collections.defaultdict(list)
    for r in csv.DictReader(open(D / 'flora-texts.tsv'), delimiter='\t', quoting=csv.QUOTE_NONE):
        flora[r['taxon']].append(r['text'])
    rng = np.random.default_rng(0)
    pilot = {t: d for t, d in labels_.items() if t in B.PILOT}
    ntr = collections.Counter(t for d in pilot.values() for t in d)
    otax = np.empty(len(onames), object); otax[oinv] = taxa
    ofold = np.array([next(f for f in range(5) if (T.bucket(t.split()[0]) - 2 * f) % 10 < 2) for t in otax])
    oi = torch.from_numpy(oinv).to(DEV)
    ox = torch.nn.functional.normalize(torch.zeros(len(onames), x.shape[1], device=DEV).index_add_(0, oi, x), dim=-1)
    tot = collections.Counter()
    for fold in range(5):
        hobs = np.flatnonzero(ofold == fold)
        cands = sorted({t for t in set(otax[hobs]) if ntr[t] >= B.MIN_TRAITS})
        cix = {t: n for n, t in enumerate(cands)}
        fam = np.array([family[t] for t in cands])
        hobs = hobs[[otax[o] in cix for o in hobs]]
        hobs = hobs[rng.choice(len(hobs), min(B.SAMPLE, len(hobs)), replace=False)]
        true = torch.from_numpy(np.array([cix[otax[o]] for o in hobs])).to(DEV)
        q = ox[torch.from_numpy(hobs).to(DEV)]
        famt = torch.from_numpy(np.unique(fam, return_inverse=True)[1]).to(DEV)
        sets = {'species name': [[f'a photo of {t}'] for t in cands],
                'trait text': [[f'a plant; {phrase(tr, " or ".join(sorted(d[t])))}' for tr, d in sorted(labels_.items()) if t in d] for t in cands],
                'flora text': [flora.get(t, []) for t in cands]}
        for kind, lists in sets.items():
            flat = [s for l in lists for s in l]
            owner = torch.from_numpy(np.repeat(np.arange(len(cands)), [len(l) for l in lists])).to(DEV)
            e = encode(flat)
            has = torch.zeros(len(cands), device=DEV).index_add_(0, owner, torch.ones(len(flat), device=DEV)) > 0
            for pool in ('mean text', 'mean similarity'):
                if pool == 'mean text':
                    c = torch.nn.functional.normalize(torch.zeros(len(cands), e.shape[1], device=DEV).index_add_(0, owner, e), dim=-1)
                    s = q @ c.T
                else:
                    cnt = torch.zeros(len(cands), device=DEV).index_add_(0, owner, torch.ones(len(flat), device=DEV)).clamp(min=1)
                    s = torch.zeros(len(hobs), len(cands), device=DEV).index_add_(1, owner, q @ e.T) / cnt
                s = torch.where(has[None, :], s, s[:, has].mean(1, keepdim=True).expand_as(s))     # no text: the average candidate
                st = s[torch.arange(len(hobs)), true][:, None]
                for scope_, mask in (('all', torch.ones_like(s, dtype=torch.bool)), ('family', famt[None, :] == famt[true][:, None])):
                    rk = 1 + ((s > st) & mask).sum(1) + 0.5 * (((s == st) & mask).sum(1) - 1)
                    for kk in (1, 5, 10):
                        tot[kind, pool, scope_, kk] += float((rk <= kk).sum())
            tot[kind, 'with text'] += float(has[true].sum())
        tot['obs'] += len(hobs)
        print('fold', fold, 'candidates', len(cands), 'observations', len(hobs), flush=True)
    n = tot['obs']
    report['identification'] = {}
    for kind in ('species name', 'trait text', 'flora text'):
        for pool in ('mean text', 'mean similarity'):
            for scope_ in ('all', 'family'):
                r = {f'top{k}': tot[kind, pool, scope_, k] / n for k in (1, 5, 10)}
                report['identification'][f'{kind} | {pool} | {scope_}'] = dict(r, true_species_with_text=tot[kind, 'with text'] / n)
                print(f"RESULT {kind:13s} {pool:16s} {scope_:7s} first {r['top1']:.3f}  in first 5 {r['top5']:.3f}  in first 10 {r['top10']:.3f}"
                      f"   true species has text {tot[kind, 'with text'] / n:.3f}", flush=True)
    (a.out / 'zeroshot.json').write_text(json.dumps(report, indent=1) + '\n')


def main():
    if sys.argv[1] == 'texts':
        return texts(sys.argv[2])
    p = argparse.ArgumentParser()
    p.add_argument('mode')
    p.add_argument('--data', type=Path, required=True)
    p.add_argument('--model', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--ref', type=Path, help='a trained run: its classes per trait and its scores for comparison')
    run(p.parse_args())


if __name__ == '__main__':
    main()
