"""Mean of the crop embeddings of each photograph: emb-crop-G (ids = photo id * 16 + k) -> emb-pcrop-G (ids = photo id).
The same for the -field folder. Run on ORIX: python crop_to_photo.py DIR leaf flower fruit"""
import sys
from pathlib import Path
import numpy as np
D = Path(sys.argv[1])
for g in sys.argv[2:]:
    for suf in ('', '-field'):
        src = D / f'emb-crop-{g}{suf}'; out = D / f'emb-pcrop-{g}{suf}'; out.mkdir(exist_ok=True)
        embs, ids = [], []
        for f in sorted(src.glob('emb-*.npy')):
            embs.append(np.load(f, mmap_mode='r')); ids += [int(x) for x in f.with_suffix('.ids').read_text().split()]
        ids = np.array(ids); pid = ids // 16
        keep = (ids % 16) != 15 if suf == '' else np.ones(len(ids), bool)      # training: organ crops only
        E = np.concatenate([np.asarray(e, dtype=np.float32) for e in embs])[keep]; pid = pid[keep]
        u, inv = np.unique(pid, return_inverse=True)
        import torch
        dev = 'cuda' if torch.cuda.is_available() else 'cpu'
        S = torch.zeros((len(u), E.shape[1]), device=dev).index_add_(0, torch.as_tensor(inv, device=dev), torch.as_tensor(E, device=dev))
        S = torch.nn.functional.normalize(S, dim=1).cpu().numpy()
        np.save(out / 'emb-0.npy', S.astype(np.float16)); (out / 'emb-0.ids').write_text('\n'.join(map(str, u)) + '\n')
        print(g, suf, len(ids), '->', len(u), flush=True)
