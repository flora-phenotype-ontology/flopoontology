import json
from types import SimpleNamespace
from flopo2.vision.full_data import split
from flopo2.vision import full_data


def test_full_split_preserves_prior_genus_and_removes_near_duplicates(tmp_path,monkeypatch):
    monkeypatch.setattr(full_data,'hash_bucket',lambda value: 0 if value=='observer:3' else 99)
    old=tmp_path/'old';old.mkdir();data=tmp_path/'data';data.mkdir()
    def row(i,g,s,h):return {'photo_id':i,'observation_id':i,'observer_id':i,'taxon':g,'genus':g,'split':s,'sha256':str(i),'dhash':h}
    prior=[row(1,'A','train','0000000000000000'),row(2,'B','test','ffffffffffffffff')]
    (old/'splits.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in prior))
    rows=[row(3,'A','unknown','123456789abcdef0'),row(4,'B','unknown','0000000000000001'),row(5,'B','unknown','fedcba9876543210')]
    (data/'images.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    split(SimpleNamespace(previous=old,out=data,legacy=None))
    kept=[json.loads(s) for s in (data/'splits.jsonl').read_text().splitlines()]
    assert {r['photo_id']:r['split'] for r in kept}=={3:'train',5:'test'}


def test_collector_handles_new_and_cached_metadata_with_download_workers(tmp_path,monkeypatch):
    profile={'taxon':'a','inat_id':1,'name':'A a','genus':'A','family':'F'}
    (tmp_path/'profiles.json').write_text(json.dumps([profile]))
    (tmp_path/'trait-inventory.json').write_text(json.dumps({'events':[{'taxon':'a'}]}))
    record={'id':10,'user':{'id':5},'quality_grade':'research','taxon':{'id':1},'photos':[{'id':20,'license_code':'cc0','url':'https://example.org/square.jpg'}]}
    class API:
        def __init__(self,*args):pass
        def get(self,*args,**kwargs):return {'results':[record]}
    monkeypatch.setattr(full_data,'API',API)
    monkeypatch.setattr(full_data,'download',lambda r,out:dict(r,sha256='test',dhash='0',image_path='test.jpg'))
    args=SimpleNamespace(out=tmp_path,per_taxon=2,pages=1)
    full_data.collect(args);full_data.collect(args)
    assert json.loads((tmp_path/'collection.json').read_text())['observations']==1
