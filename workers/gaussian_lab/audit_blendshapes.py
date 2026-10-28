"""Audit named native LAM deformation fields and candidate combinations."""
import io,json,sys,zipfile
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'workers/gaussian'))
from export_asset import decode_glb
from calibrate_asset import read_vectors


def audit(avatar_id):
    folder=ROOT/'data/gaussian/avatars'/avatar_id
    with zipfile.ZipFile(folder/'asset.zip') as z:
        name=next(n for n in z.namelist() if n.endswith('/skin.glb'))
        d,b=decode_glb(z.read(name))
    m=d['meshes'][0];p=m['primitives'][0]
    n=m.get('extras',{}).get('oral',{}).get('base_count',20018)
    pos=read_vectors(d,b,p['attributes']['POSITION'])[:n]
    fields={name:read_vectors(d,b,t['POSITION'])[:n] for name,t in zip(m['extras']['targetNames'],p['targets'])}
    report={'avatar_id':avatar_id,'native_vertices':n,'channels':{},'combinations':{}}
    for name,delta in fields.items():
        length=np.linalg.norm(delta,axis=1);active=length>.0001
        report['channels'][name]={'finite':bool(np.isfinite(delta).all()),'moving_vertices':int(active.sum()),
          'max_mm':float(length.max()*1000),'mean_active_mm':float(length[active].mean()*1000) if active.any() else 0,
          'active_centroid':pos[active].mean(0).tolist() if active.any() else None}
    profiles=json.loads((ROOT/'apps/api/app/emotion_profiles.json').read_text())
    for emotion,profile in profiles.items():
        delta=np.zeros_like(pos);magnitudes=np.zeros(n)
        for name,weight in profile.items():
            assert name in fields and report['channels'][name]['moving_vertices']>0,name
            delta+=fields[name]*weight;magnitudes+=np.linalg.norm(fields[name]*weight,axis=1)
        report['combinations'][emotion]={'active_channels':list(profile),
            'max_mm':float(np.linalg.norm(delta,axis=1).max()*1000),
            'weighted_cancellation_fraction':float(1-np.linalg.norm(delta,axis=1).sum()/magnitudes.sum()) if magnitudes.sum() else 0,
            'scope':'nominal 0..1 rig range; spatial cancellation is not a perceptual emotion score'}
    return report

if __name__=='__main__':
    out=ROOT/'artifacts/dynamics-v8';out.mkdir(exist_ok=True)
    for avatar in ['2a80fe76d5f44beba2a3c0ac','88546d4a362b4a97979c5360']:
        report=audit(avatar);(out/f'channel-audit-{avatar}.json').write_text(json.dumps(report,indent=2))
        print(avatar,'channels',len(report['channels']),'native zero channels',[n for n,v in report['channels'].items() if v['moving_vertices']==0])
