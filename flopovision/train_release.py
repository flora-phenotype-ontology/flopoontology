"""Train the released FLOPOVision trait heads (runs on a GPU; about 20 minutes).

    python train_release.py DIR OUT     # DIR: emb/ (BioCLIP 2 image embeddings), labels-v5.tsv, inat-photos-v3-all.tsv

One head per categorical trait on the frozen, L2-normalised BioCLIP 2 image embedding: Linear(768, 1024), GELU, Dropout(0.2),
Linear(1024, classes). A species is one training example: up to 64 photographs, the mean of the predicted probabilities, and
the loss is -log of the probability of the values that the floras allow for the species. The released heads are trained on all
species; the accuracies in the model card come from the same procedure with whole genera held out.
Writes OUT/flopovision-heads.safetensors and OUT/config.json.
"""
import collections, csv, json, sys
from pathlib import Path
import numpy as np
import torch
from safetensors.torch import save_file

D, OUT = Path(sys.argv[1]), Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
dev = 'cuda'
EPOCHS, MIN_CLASS = 40, 50
embs, ids = [], []
for f in sorted((D / 'emb').glob('emb-*.npy')):
    embs.append(np.load(f)); ids += [int(x) for x in f.with_suffix('.ids').read_text().split()]
emb = np.concatenate(embs); row = {i: n for n, i in enumerate(ids)}
labels = collections.defaultdict(dict)
for r in csv.DictReader(open(D / 'labels-v5.tsv'), delimiter='\t'):
    labels[r['trait']][r['taxon']] = set(r['allowed'].split('|'))
photos = collections.defaultdict(list)
for r in csv.DictReader(open(D / 'inat-photos-v3-all.tsv'), delimiter='\t'):
    if int(r['photo_id']) in row:
        photos[r['taxon']].append(row[int(r['photo_id'])])
taxa = sorted(photos); index = {t: n for n, t in enumerate(taxa)}
X = torch.zeros((len(taxa), 64, emb.shape[1]), dtype=torch.float16); M = torch.zeros((len(taxa), 64), dtype=torch.bool)
for n, t in enumerate(taxa):
    p = photos[t][:64]
    X[n, :len(p)] = torch.from_numpy(emb[p]); M[n, :len(p)] = True
X, M = X.to(dev), M.to(dev)
weights, config = {}, {'name': 'FLOPOVision', 'version': '0.1', 'encoder': 'imageomics/bioclip-2 (ViT-L-14, image tower, L2-normalised output)',
                       'embedding_dim': int(emb.shape[1]), 'hidden': 1024, 'species_with_photographs': len(taxa), 'traits': {}}
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
    torch.manual_seed(0)
    net = torch.nn.Sequential(torch.nn.Linear(X.shape[2], 1024), torch.nn.GELU(), torch.nn.Dropout(0.2), torch.nn.Linear(1024, len(classes))).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=0.05)
    steps = EPOCHS * (len(have) // 512 + 1); sched = torch.optim.lr_scheduler.OneCycleLR(opt, 1e-3, total_steps=steps)
    net.train()
    for step in range(steps):
        i = torch.randint(0, len(have), (512,), device=dev); r = rows[i]
        p = torch.softmax(net(X[r].float()), -1) * M[r][..., None]
        p = p.sum(1) / M[r].sum(1, keepdim=True)
        loss = -torch.log((p * Y[i]).sum(1).clamp_min(1e-6)).mean()
        opt.zero_grad(); loss.backward(); opt.step(); sched.step()
    for k, v in net.state_dict().items():
        weights[f'{trait}.{k}'] = v.detach().cpu().contiguous()
    config['traits'][trait] = {'classes': classes, 'training_species': len(have), 'species_per_class': {c: count[c] for c in classes}}
    print(trait, len(classes), 'classes', len(have), 'species, last loss', round(float(loss.detach()), 3), flush=True)
save_file(weights, str(OUT / 'flopovision-heads.safetensors'))
(OUT / 'config.json').write_text(json.dumps(config, indent=1) + '\n')
print('wrote', OUT, flush=True)
