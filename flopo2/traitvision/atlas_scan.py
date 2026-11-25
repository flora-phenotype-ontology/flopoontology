import numpy as np, csv, sys, json
S=sys.argv[1]
z=np.load(f'{S}/pred-all.npz'); row={int(p):n for n,p in enumerate(z['photo_ids'])}
M=[r for r in csv.DictReader(open(f'{S}/inat-photos-cline.tsv'),delimiter='\t') if int(r['photo_id']) in row]
ix=[row[int(r['photo_id'])] for r in M]; tx=np.array([r['taxon'] for r in M])
lat=np.array([float(r['latitude']) for r in M]); lon=np.array([float(r['longitude']) for r in M])
blk=(np.floor(lat/2)*1000+np.floor(lon/2)).astype(int); rng=np.random.default_rng(0)
def r2(y,b):
    u,inv,c=np.unique(b,return_inverse=True,return_counts=True); m=np.bincount(inv,y)/c
    return ((m[inv]-y.mean())**2).sum()/max(((y-y.mean())**2).sum(),1e-9)
traits=[k[2:] for k in z.files if k.startswith('p_')]; res=[]
species=sorted(set(tx)); idx={sp:np.flatnonzero(tx==sp) for sp in species}
for t in traits:
    P=z['p_'+t][ix].astype(np.float32); cl=[str(c) for c in z['c_'+t]]; a=P.argmax(1); conf=P.max(1)>(0.8 if len(cl)==2 else 0.6)
    for sp in species:
        i=idx[sp][conf[idx[sp]]]
        if len(i)<300: continue
        sh=np.bincount(a[i],minlength=len(cl))/len(i); o=np.argsort(-sh)
        if sh[o[1]]<0.10: res.append((t,sp,cl[o[0]],sh[o[0]],cl[o[1]],sh[o[1]],None,None,len(i))); continue
        j=i[np.isin(a[i],o[:2])]; y=(a[j]==o[0]).astype(float); b=blk[j]
        u,inv,c=np.unique(b,return_inverse=True,return_counts=True); k=c[inv]>=10
        if k.sum()<200 or len(np.unique(b[k]))<5: res.append((t,sp,cl[o[0]],sh[o[0]],cl[o[1]],sh[o[1]],None,None,len(i))); continue
        R=r2(y[k],b[k]); null=float(np.percentile([r2(rng.permutation(y[k]),b[k]) for _ in range(100)],99))
        res.append((t,sp,cl[o[0]],float(sh[o[0]]),cl[o[1]],float(sh[o[1]]),float(R),null,len(i)))
with open(f'{S}/atlas-scan.tsv','w') as f:
    f.write('trait\ttaxon\tfirst form\tshare\tsecond form\tshare\tR2 of 2-degree cells\tpermutation 99%\tconfident photographs\n')
    for r in res: f.write('\t'.join('' if v is None else (f'{v:.3f}' if isinstance(v,float) else str(v)) for v in r)+'\n')
print(f"{'trait':18s} species  two forms  beyond null  excess>0.1  median excess")
for t in traits:
    a=[r for r in res if r[0]==t]; p=[r for r in a if r[6] is not None]; ex=np.array([r[6]-r[7] for r in p]) if p else np.array([0.])
    print(f"{t:18s} {len(a):6d} {sum(r[5]>=0.10 for r in a):9d} {int((ex>0).sum()):11d} {int((ex>0.1).sum()):10d} {np.median(ex):+.3f}")
