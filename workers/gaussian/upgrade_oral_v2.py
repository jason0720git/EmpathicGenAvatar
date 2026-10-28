"""Repair existing oral v1 assets without changing source-face geometry.
Keeps a complete backup; creates lip anchors from identity-fit landmarks.
"""
import io,json,zipfile,hashlib,shutil
from pathlib import Path
import numpy as np
from plyfile import PlyData,PlyElement
from export_asset import decode_glb,encode_glb
from calibrate_asset import read_vectors,write_vectors

def upgrade(folder):
    folder=Path(folder);path=folder/'asset.zip';record=json.loads((folder/'record.json').read_text(encoding='utf8'))
    source=folder/'asset.pre-oral-v2.zip'
    with zipfile.ZipFile(source if source.exists() else path) as z: files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    root=next(n.rsplit('/',1)[0] for n in files if n.endswith('/skin.glb'))
    doc,binary=decode_glb(files[root+'/skin.glb']);mesh=doc['meshes'][0];p=mesh['primitives'][0]
    oral=mesh['extras']['oral']
    if oral['version']=='explicit-oral-gaussians-v2': return oral
    assert oral['base_count']==20018 and oral['added']==890
    base=read_vectors(doc,binary,p['attributes']['POSITION']);n=oral['base_count']
    ply=PlyData.read(io.BytesIO(files[root+'/offset.ply']));v=ply['vertex'].data.copy()
    centers=base+np.column_stack([v[k] for k in ('x','y','z')])
    names=mesh['extras']['targetNames'];deltas={name:read_vectors(doc,binary,t['POSITION']) for name,t in zip(names,p['targets'])}
    measurement=json.loads(files[root+'/identity_fit.json'])['measurement'];cam=record['source_camera']
    origin=np.array(cam['position']);forward=np.array(cam['target'])-origin;forward/=np.linalg.norm(forward)
    right=np.cross(forward,cam['up']);right/=np.linalg.norm(right);up=np.cross(right,forward)
    h,w=measurement['render_size'];f=h/(2*np.tan(np.radians(cam['fov'])/2));rel=centers[:n]-origin;depth=rel@forward
    uv=np.column_stack([w/2+f*(rel@right)/depth,h/2-f*(rel@up)/depth])
    lm=np.array(measurement['target_landmarks']);anchors={}
    for key,index in [('upper',62),('lower',66),('left',48),('right',54)]:
        distance=np.linalg.norm(uv-lm[index],axis=1)
        jaw_y=deltas['jawOpen'][:n,1]
        if key=='upper':distance=np.where(jaw_y>-.003,distance,np.inf)
        if key=='lower':distance=np.where(jaw_y<-.012,distance,np.inf)
        ids=np.argsort(distance)[:18];ids=ids[np.argsort(depth[ids])[:6]]
        anchors[key]={'position':np.mean(centers[ids],axis=0).tolist(),'deltas':{name:np.mean(delta[ids],axis=0).tolist() for name,delta in deltas.items()}}
    # V1 crowns extended upward from the mouth seam and were then clipped away.
    # Upper crowns descend from the gum. Dense overlapping splats remain separate teeth.
    start=n+375+275
    for tooth in range(8):
        for ix in range(3):
            for row in range(5):
                i=start+tooth*15+ix*5+row;t=row/4
                length=[.0048,.0054,.0056,.006,.006,.0056,.0054,.0048][tooth]
                base[i,1]=oral['anchor'][1]+.002-length*t
                base[i,2]+=.0005*(1-abs(ix-1))
                for k in range(3):v['scale_'+str(k)][i]=np.log([.00065,.00080,.00065][k])
                shade=(.67+.12*np.sin(np.pi*t))*(.88 if ix!=1 else 1.)
                for k,c in enumerate([shade,shade*.95,shade*.88]):v['f_dc_'+str(k)][i]=c
    # The tongue must sit in front of the dark back wall, behind the teeth.
    base[n+375:n+650,2]+=.003
    for i in range(n+770,n+890):
        v['scale_0'][i]=np.log(.00065)
        for k in range(3):v['f_dc_'+str(k)][i]*=.82
    write_vectors(doc,binary,p['attributes']['POSITION'],base)
    oral.update(version='explicit-oral-gaussians-v2',lip_anchors=anchors,occlusion='projected-per-fragment-lip-aperture')
    mesh['extras']['oral']=oral
    files[root+'/oral.json']=json.dumps(oral).encode();files[root+'/skin.glb']=encode_glb(doc,binary)
    out=io.BytesIO();PlyData([PlyElement.describe(v,'vertex')]).write(out);files[root+'/offset.ply']=out.getvalue()
    backup=folder/'asset.pre-oral-v2.zip'
    if not backup.exists():shutil.copy2(path,backup);shutil.copy2(folder/'record.json',folder/'record.pre-oral-v2.json')
    temp=folder/'oral-v2.tmp'
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for name,data in files.items():z.writestr(name,data)
    temp.replace(path);record['asset_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();record['oral_version']=oral['version']
    (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    return {'avatar':folder.name,'hash':record['asset_sha256'],'anchors':{k:a['position'] for k,a in anchors.items()}}
if __name__=='__main__':
    import sys
    for path in sys.argv[1:]:print(json.dumps(upgrade(path)))
