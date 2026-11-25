"""Every categorical trait for the photographs of the atlas species (standalone; runs on ORIX).

    python trait_atlas_fit.py DIR SET [SET ...]    # DIR = pilot-v1; each SET has SET/species.tsv and embeddings in emb-SET

For each trait of ``labels-v5.tsv`` one head on the frozen BioCLIP 2 embeddings, trained as in ``baseline_v2.py`` (a species
is one example: up to 64 photographs, mean of the predicted probabilities, loss = -log of the probability of the values the
floras allow). Five folds over genera (hash of the genus name): the photographs of a species are predicted by the head that
was trained without any species of its genus. Pimpernels: Lysimachia and Anagallis share a fold.
Writes SET/pred-all.npz: photo_ids, and per trait p_<trait> (float16) and c_<trait> (class names).
"""
import collections, csv, hashlib, sys
from pathlib import Path
import numpy as np
import torch

D = Path(sys.argv[1]); SETS = sys.argv[2:]
dev = 'cuda'
FOLDS, EPOCHS, MIN_CLASS = 5, 40, 50


def load(folder):
    embs, ids = [], []
    for f in sorted(folder.glob('emb-*.npy')):
        embs.append(np.load(f)); ids += [int(x) for x in f.with_suffix('.ids').read_text().split()]
    return np.concatenate(embs), np.array(ids)


def fold(genus):
    genus = 'Lysimachia' if genus == 'Anagallis' else genus
    return int(hashlib.md5(genus.encode()).hexdigest(), 16) % FOLDS


emb, ids = load(D / 'emb')
row = {int(i): n for n, i in enumerate(ids)}
labels = collections.defaultdict(dict)
for r in csv.DictReader(open(D / 'labels-v5.tsv'), delimiter='\t'):
    labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
photos = collections.defaultdict(list)
for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
    if int(r['photo_id']) in row:
        photos[r['taxon']].append(row[int(r['photo_id'])])
taxa = sorted(photos)
index = {t: n for n, t in enumerate(taxa)}
X = torch.zeros((len(taxa), 64, emb.shape[1]), dtype=torch.float16); M = torch.zeros((len(taxa), 64), dtype=torch.bool)
for n, t in enumerate(taxa):
    p = photos[t][:64]
    X[n, :len(p)] = torch.from_numpy(emb[p]); M[n, :len(p)] = True
X, M = X.to(dev), M.to(dev)
del emb
tfold = torch.tensor([fold(t.split()[0]) for t in taxa], device=dev)
print('species with photographs', len(taxa), 'traits', len(labels), flush=True)

sets = {}
for s in SETS:
    e, i = load(D / f'emb-{s}')
    sp = {int(r['photo_id']): r['taxon'] for r in csv.DictReader(open(D / s / 'inat-photos-cline.tsv'), delimiter='\t')}
    sets[s] = (torch.from_numpy(e).to(dev), i, torch.tensor([fold(sp[int(k)].split()[0]) for k in i], device=dev), {})
    print(s, len(i), 'photographs', flush=True)

for trait in sorted(labels):
    lab = labels[trait]
    count = collections.Counter(c for t, v in lab.items() if t in index for c in v)
    classes = sorted(c for c, k in count.items() if k >= MIN_CLASS)
    if len(classes) < 2:
        continue
    have = [t for t in lab if t in index and lab[t] & set(classes)]
    rows = torch.tensor([index[t] for t in have], device=dev)
    Y = torch.zeros((len(have), len(classes)), device=dev)
    for n, t in enumerate(have):
        for c in lab[t] & set(classes):
            Y[n, classes.index(c)] = 1
    out = {s: torch.zeros((len(v[1]), len(classes)), device=dev) for s, v in sets.items()}
    for f in range(FOLDS):
        torch.manual_seed(f)
        keep = (tfold[rows] != f).nonzero().squeeze(1)
        net = torch.nn.Sequential(torch.nn.Linear(X.shape[2], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2), torch.nn.Linear(1024, len(classes))).to(dev)
        opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=0.05)
        steps = EPOCHS * (len(keep) // 512 + 1); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
        net.train()
        for step in range(steps):
            i = keep[torch.randint(0, len(keep), (512,), device=dev)]; r = rows[i]
            p = torch.softmax(net(X[r].float()), -1) * M[r][..., None]
            p = p.sum(1) / M[r].sum(1, keepdim=True)
            loss = -torch.log((p * Y[i]).sum(1).clamp_min(1e-6)).mean()
            opt.zero_grad(); loss.backward(); opt.step(); sched.step()
        net.eval()
        with torch.no_grad():
            for s, (C, _, cf, _) in sets.items():
                j = (cf == f).nonzero().squeeze(1)
                for a in range(0, len(j), 65536):
                    out[s][j[a:a + 65536]] = torch.softmax(net(C[j[a:a + 65536]].float()), -1)
    for s in sets:
        sets[s][3]['p_' + trait] = out[s].cpu().numpy().astype(np.float16); sets[s][3]['c_' + trait] = np.array(classes)
    print(trait, len(classes), 'classes', len(have), 'species, last loss', round(float(loss), 3), flush=True)
for s, (_, i, _, res) in sets.items():
    np.savez_compressed(D / s / 'pred-all.npz', photo_ids=i, **res)
    print('wrote', s, flush=True)
