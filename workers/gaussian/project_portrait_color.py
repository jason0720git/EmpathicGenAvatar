"""Calibrate visible 3D Gaussian colors against the unchanged source photograph.

Only the front facial surface is sampled; recessed mouth/eyes and rear geometry
retain their original materials. No output bitmap is synthesized or retouched.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path
import cv2
import numpy as np
from scipy.spatial import Delaunay, cKDTree
from plyfile import PlyData
from export_asset import decode_glb
from calibrate_asset import read_vectors


def project(source,photo,measurement,camera,output,strength=.65):
    with zipfile.ZipFile(source) as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    skin=next(n for n in files if n.endswith('/skin.glb'));root=skin.rsplit('/',1)[0]
    if root+'/portrait_color.json' in files:raise ValueError('Do not project repeatedly onto projected colors')
    doc,b=decode_glb(files[skin]);p=doc['meshes'][0]['primitives'][0]
    base=read_vectors(doc,b,p['attributes']['POSITION'])
    ply=PlyData.read(io.BytesIO(files[root+'/offset.ply']));v=ply['vertex'].data
    centers=base+np.column_stack([v[k] for k in ('x','y','z')])
    origin=np.array(camera['position']);forward=np.array(camera['target'])-origin;forward/=np.linalg.norm(forward)
    right=np.cross(forward,camera['up']);right/=np.linalg.norm(right);up=np.cross(right,forward)
    h,w=measurement['render_size'];f=h/(2*np.tan(np.radians(camera['fov'])/2));rel=centers-origin;depth=rel@forward
    uv=np.column_stack([w/2+f*(rel@right)/depth,h/2-f*(rel@up)/depth])
    render=np.array(measurement['render_landmarks']);src=np.array(measurement['source_landmarks'])
    # Extend the brow hull into the forehead. Both sets use their own eye scale.
    def extend(lm):
        eye=np.linalg.norm(lm[36:42].mean(0)-lm[42:48].mean(0))
        extra=lm[[17,19,21,22,24,26]].copy();extra[:,1]-=eye*.55
        return np.vstack([lm,extra])
    render,src=extend(render),extend(src)
    tri=Delaunay(render);simplex=tri.find_simplex(uv);inside=simplex>=0
    safe=np.maximum(simplex,0);bary=np.einsum('nij,nj->ni',tri.transform[safe,:2],uv-tri.transform[safe,2])
    bary=np.column_stack([bary,1-bary.sum(1)])
    pixels=np.einsum('ni,nij->nj',bary,src[tri.simplices[safe]])
    img=cv2.cvtColor(cv2.imread(str(photo)),cv2.COLOR_BGR2RGB)/255.
    color=cv2.remap(img,pixels[:,0].astype('float32').reshape(-1,1),pixels[:,1].astype('float32').reshape(-1,1),cv2.INTER_LINEAR).reshape(-1,3)
    # Approximate visibility with a local front-depth envelope. Restrict to
    # head skin; never project lip pixels onto the added oral surfaces.
    _,neighbors=cKDTree(uv[:20018]).query(uv,k=12)
    front=depth[:20018][neighbors].min(1)
    visibility=np.clip((.004-(depth-front))/.003,0,1)
    hull=render[tri.convex_hull].reshape(-1,2)
    boundary=cKDTree(hull).query(uv)[0]
    alpha=strength*inside*visibility*np.clip(boundary/7,0,1)
    alpha[20018:]=0
    # Eyeballs and lid edges need their rig-specific colors during closure.
    for ids in (range(36,42),range(42,48)):
        eye=render[list(ids)];lo=eye.min(0)-3;hi=eye.max(0)+3
        alpha[np.all((uv>=lo)&(uv<=hi),axis=1)]=0
    old=np.column_stack([v['f_dc_'+str(i)] for i in range(3)])
    calibrated=old*(1-alpha[:,None])+color*alpha[:,None]
    for i in range(3):v['f_dc_'+str(i)]=calibrated[:,i]
    buf=io.BytesIO();ply.write(buf);files[root+'/offset.ply']=buf.getvalue()
    report={'version':'source-portrait-color-v1','strength':strength,'points':int((alpha>.01).sum()),
            'scope':'front facial surface only; original photo unchanged; excludes eyes and oral augmentation'}
    files[root+'/portrait_color.json']=json.dumps(report,indent=2).encode()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for k,value in files.items():z.writestr(k,value)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('photo',type=Path);p.add_argument('record',type=Path);p.add_argument('measurement',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();r=json.loads(a.record.read_text());print(json.dumps(project(a.source,a.photo,json.loads(a.measurement.read_text()),r['source_camera'],a.output)))
