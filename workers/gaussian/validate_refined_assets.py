"""Integration checks on generated oral assets, not synthetic placeholders."""
import io
import json
import zipfile
from pathlib import Path
import numpy as np
from plyfile import PlyData
from export_asset import decode_glb, accessor_array
from calibrate_asset import read_vectors


def validate(path):
    with zipfile.ZipFile(path) as z:
        d,b=decode_glb(z.read('avatar/skin.glb'))
        oral=json.loads(z.read('avatar/oral.json'))
        v=PlyData.read(io.BytesIO(z.read('avatar/offset.ply')))['vertex'].data
    p=d['meshes'][0]['primitives'][0];names=d['meshes'][0]['extras']['targetNames']
    assert len(v)==20908 and len(names)==52 and len(set(names))==52
    assert oral['recessed_bright_points_repaired']==0
    assert d['meshes'][0]['extras']['oral']==oral
    assert all(d['accessors'][i]['count']==len(v) for i in p['attributes'].values())
    assert accessor_array(d,b,p['indices']).max()<len(v)
    for name in v.dtype.names:assert np.isfinite(v[name]).all(),name
    tongue=read_vectors(d,b,p['targets'][names.index('tongueOut')]['POSITION'])
    assert np.count_nonzero(np.linalg.norm(tongue,axis=1))==275
    assert not tongue[:20018].any(), 'Tongue must not move original face'
    for target in p['targets']:
        values=read_vectors(d,b,target['POSITION'])
        assert values.shape==(len(v),3) and np.isfinite(values).all()
    assert np.exp(np.column_stack([v['scale_'+str(i)] for i in range(3)]))[20018:].max()<.002
    return {'points':len(v),'morphs':len(names),'tongue_points':275,'status':'passed'}


if __name__=='__main__':
    root=Path('/gaussian-data');ids=json.loads((root/'identity-fit/v2-ids.json').read_text())
    result={name:validate(root/'avatars'/aid/'asset.zip') for name,aid in ids.items()}
    (root/'identity-fit/v2-asset-checks.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
