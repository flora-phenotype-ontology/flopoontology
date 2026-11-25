"""Flower-colour head for the colour-form species (standalone; runs on ORIX).

    python colour_cline_fit.py DIR [SET]      # DIR = pilot-v1; reads emb/, emb-cline/, cline/species.tsv; writes cline/pred.npz

One head on the frozen BioCLIP 2 embeddings, trained as in ``baseline_v2.py`` (a species is one example: up to 64 photographs,
mean of the predicted probabilities, loss = -log of the probability of the colours the floras allow), on every species with a
flora flower colour EXCEPT all species of the genera of the colour-form species. So no photograph and no label of these genera
is seen. Five heads with different seeds; the saved prediction is their mean. A check on held-out species with one agreed
colour (a tenth of the other genera) is printed.
"""
import collections, csv, hashlib, sys
from pathlib import Path
import numpy as np
import torch

D = Path(sys.argv[1])
SET = sys.argv[2] if len(sys.argv) > 2 else 'cline'      # folder with species.tsv; embeddings in emb-<SET>
dev = 'cuda'


def load(folder):
    embs, ids = [], []
    for f in sorted(folder.glob('emb-*.npy')):
        embs.append(np.load(f)); ids += [int(x) for x in f.with_suffix('.ids').read_text().split()]
    return np.concatenate(embs), np.array(ids)


emb, ids = load(D / 'emb')
row = {int(i): n for n, i in enumerate(ids)}
labels = {}
for r in csv.DictReader(open(D / 'labels-v5.tsv'), delimiter='\t'):
    if r['trait'] == 'flower_colour':
        labels[r['taxon']] = set(r['allowed'].split('|'))
classes = sorted({c for v in labels.values() for c in v})
agreed = {r['taxon']: r['value'] for r in csv.DictReader(open(D / 'agreed-v5.tsv'), delimiter='\t') if r['trait'] == 'flower_colour'} if (D / 'agreed-v5.tsv').exists() else {}
held = {r['taxon'].split()[0] for r in csv.DictReader(open(D / SET / 'species.tsv'), delimiter='\t')}
if 'Lysimachia' in held:
    held.add('Anagallis')     # the pimpernels under their older genus name
photos = collections.defaultdict(list)
for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
    if int(r['photo_id']) in row and r['taxon'] in labels:
        photos[r['taxon']].append(row[int(r['photo_id'])])
bucket = lambda g: int(hashlib.md5(g.encode()).hexdigest(), 16) % 10
train = [t for t in photos if t.split()[0] not in held and bucket(t.split()[0]) != 0]
test = [t for t in photos if t.split()[0] not in held and bucket(t.split()[0]) == 0 and t in agreed]
print('classes', classes, 'training species', len(train), 'check species', len(test), 'held genera', len(held), flush=True)


def bags(taxa):
    X = torch.zeros((len(taxa), 64, emb.shape[1]), dtype=torch.float16); M = torch.zeros((len(taxa), 64), dtype=torch.bool)
    for n, t in enumerate(taxa):
        p = photos[t][:64]
        X[n, :len(p)] = torch.from_numpy(emb[p]); M[n, :len(p)] = True
    return X.to(dev), M.to(dev)


Xtr, Mtr = bags(train); Xte, Mte = bags(test)
Y = torch.zeros((len(train), len(classes)), device=dev)
for n, t in enumerate(train):
    for c in labels[t]:
        Y[n, classes.index(c)] = 1
yte = torch.tensor([classes.index(agreed[t]) for t in test], device=dev)
cemb, cids = load(D / f'emb-{SET}')
C = torch.from_numpy(cemb).to(dev)
prob = torch.zeros((len(cids), len(classes)), device=dev)
SEEDS = 5
for seed in range(SEEDS):
    torch.manual_seed(seed)
    net = torch.nn.Sequential(torch.nn.Linear(emb.shape[1], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2), torch.nn.Linear(1024, len(classes))).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=0.05)
    steps = 40 * (len(train) // 512 + 1); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)

    def bagprob(X, M):
        p = torch.softmax(net(X.float()), -1) * M[..., None]
        return p.sum(1) / M.sum(1, keepdim=True)
    for step in range(steps):
        net.train()
        i = torch.randint(0, len(train), (512,), device=dev)
        loss = -torch.log((bagprob(Xtr[i], Mtr[i]) * Y[i]).sum(1).clamp_min(1e-6)).mean()
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    net.eval()
    with torch.no_grad():
        p = torch.cat([bagprob(Xte[a:a + 2048], Mte[a:a + 2048]) for a in range(0, len(test), 2048)])
        hit = (p.argmax(1) == yte).float()
        bal = float(torch.stack([hit[yte == c].mean() for c in yte.unique()]).mean())
        print(f'seed {seed} loss {float(loss):.3f} check species: accuracy {float(hit.mean()):.3f} balanced {bal:.3f}', flush=True)
        prob += torch.cat([torch.softmax(net(C[a:a + 65536].float()), -1) for a in range(0, len(cids), 65536)]) / SEEDS
np.savez_compressed(D / SET / 'pred.npz', photo_ids=cids, prob=prob.cpu().numpy().astype(np.float32), classes=np.array(classes))
print('predicted', len(cids), flush=True)
