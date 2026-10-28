"""Correct native LAM inner soft-tissue chroma without new geometry or screen overlays.

Conservative jaw-deformation and recessed-position mask excludes the static upper
crowns and rigid lower dental displacement. This is appearance calibration, not
reconstruction of a separately articulated anatomical tongue.
"""
import io, json, hashlib, shutil, zipfile
from pathlib import Path
import numpy as np
from plyfile import PlyData, PlyElement
from export_asset import decode_glb, encode_glb
from calibrate_asset import read_vectors


def smooth(lo, hi, value):
    t=np.clip((value-lo)/(hi-lo),0,1)
    return t*t*(3-2*t)


def calibrate(folder):
    folder=Path(folder); path=folder/'asset.zip'; backup=folder/'asset.pre-material-v7.zip'
    if not backup.exists():
        shutil.copy2(path,backup)
        shutil.copy2(folder/'record.json',folder/'record.pre-material-v7.json')
    with zipfile.ZipFile(backup) as z:
        files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    skin=next(n for n in files if n.endswith('/skin.glb')); root=skin.rsplit('/',1)[0]
    doc,binary=decode_glb(files[skin]);mesh=doc['meshes'][0];p=mesh['primitives'][0]
    oral=mesh['extras']['oral'];count=oral['base_count']
    base=read_vectors(doc,binary,p['attributes']['POSITION'])
    jaw=read_vectors(doc,binary,p['targets'][mesh['extras']['targetNames'].index('jawOpen')]['POSITION'])
    v=PlyData.read(io.BytesIO(files[root+'/offset.ply']))['vertex'].data.copy()
    center=base+np.column_stack([v[k] for k in ('x','y','z')])
    x,y,z=(center-np.array(oral['anchor'])).T; width=oral['halfwidth']
    # Teeth follow a rigid jaw arc with a large rearward component. The inner
    # soft surface has a predominantly downward deformation; preserve crowns.
    down=-jaw[:,1]; ratio=abs(jaw[:,2])/np.maximum(down,1e-6)
    spatial=(1-smooth(width*.6,width*.95,abs(x)))*smooth(-.010,-.005,y)*(1-smooth(.003,.008,y))
    spatial*=smooth(.002,.006,-z)*(1-smooth(.022,.030,-z))
    tissue=smooth(.016,.028,down)*(1-smooth(.60,.80,ratio))
    rgb=np.column_stack([v['f_dc_'+str(i)] for i in range(3)])
    # Change only pale/blue-gray tissue; leave already dark or red tissue alone.
    pale=smooth(.04,.16,np.maximum(rgb[:,1],rgb[:,2])-rgb[:,0]+.16)*smooth(.16,.38,rgb.mean(1))
    # The native reconstruction also stretches pale upper-surface splats below
    # the dental crown into a nearly stationary oral backing. Shade that
    # recessed lower band separately; retain the visible upper tooth edge.
    backing=(1-smooth(width*.6,width*.95,abs(x)))*smooth(.001,.006,-y)*(1-smooth(.013,.018,-y))
    backing*=smooth(.003,.005,-z)*(1-smooth(.020,.028,-z))*(1-smooth(.003,.007,abs(jaw[:,1])))
    alpha=np.maximum(spatial*tissue,backing)*pale*.95;alpha[count:]=0
    light=np.clip(rgb.mean(1),.18,.6)
    target=np.column_stack([.19+.5*light,.035+.23*light,.05+.25*light])
    corrected=rgb*(1-alpha[:,None])+target*alpha[:,None]
    for i in range(3):v['f_dc_'+str(i)]=corrected[:,i]
    report={'version':'native-soft-tissue-chroma-v7','changed_splats':int((alpha>.01).sum()),
        'max_blend':float(alpha.max()),'added_geometry':False,'independent_tongue':False,
        'method':'recessed native tissue/backing chroma mask; upper crown band and rigid lower arc preserved',
        'changed_indices':np.flatnonzero(alpha>.01).tolist()}
    mesh['extras']['oralMaterial']=report
    files[skin]=encode_glb(doc,binary)
    out=io.BytesIO();PlyData([PlyElement.describe(v,'vertex')]).write(out);files[root+'/offset.ply']=out.getvalue()
    files[root+'/oral_material.json']=json.dumps(report,indent=2).encode()
    tmp=folder/'material-v7.tmp'
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for name,raw in files.items():z.writestr(name,raw)
    tmp.replace(path)
    record=json.loads((folder/'record.json').read_text(encoding='utf8'))
    record['asset_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    record['oral_material']=report
    (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='changed_indices'}))
    return report

if __name__=='__main__':
    import sys
    for folder in sys.argv[1:]:calibrate(folder)
