"""Landmark-guided native 3D correction from a neutral browser-render measurement.

No image retouching. Keeps source texture, skeleton and animation channels.
Corrections are smooth, camera-plane, depth-gated and capped at 6 mm.
"""
import argparse
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from scipy.spatial.distance import cdist
from scipy.spatial.transform import Rotation
from plyfile import PlyData
from calibrate_asset import read_vectors, write_vectors
from export_asset import decode_glb, encode_glb


def make_warp(measurement, camera, strength=.85):
    src=np.array(measurement['render_landmarks']); target=np.array(measurement['target_landmarks'])
    eye=np.linalg.norm(src[36:42].mean(0)-src[42:48].mean(0))
    low=src.min(0)-eye*.6; high=src.max(0)+eye*.6
    anchors=np.array([[x,y] for x in np.linspace(low[0],high[0],7) for y in (low[1],high[1])]
                     +[[x,y] for x in (low[0],high[0]) for y in np.linspace(low[1],high[1],7)[1:-1]])
    knots=np.vstack([src,anchors]); delta=np.vstack([(target-src)*strength,np.zeros_like(anchors)])
    radius=eye*.45
    kernel=lambda a,b:np.exp(-cdist(a,b,'sqeuclidean')/(2*radius**2))
    coefficients=np.linalg.solve(kernel(knots,knots)+np.eye(len(knots))*.025,delta)
    origin=np.array(camera['position'],dtype=float); forward=np.array(camera['target'],dtype=float)-origin;forward/=np.linalg.norm(forward)
    up=np.array(camera['up'],dtype=float);right=np.cross(forward,up);right/=np.linalg.norm(right);up=np.cross(right,forward)
    height,width=measurement['render_size']; focal=height/(2*np.tan(np.radians(camera['fov'])/2))
    def warp(points):
        rel=points-origin; depth=rel@forward
        uv=np.column_stack([width/2+focal*(rel@right)/depth,height/2-focal*(rel@up)/depth])
        screen=kernel(uv,knots)@coefficients
        displacement=depth[:,None]/focal*(screen[:,0,None]*right-screen[:,1,None]*up)
        # Do not move the rear head/neck just because it projects behind a face landmark.
        gate=np.clip((points[:,2]-.01)/.035,0,1);gate=gate*gate*(3-2*gate)
        displacement*=gate[:,None]
        magnitude=np.linalg.norm(displacement,axis=1)
        displacement*=np.minimum(1,.006/np.maximum(magnitude,1e-12))[:,None]
        return points+displacement
    return warp


def fit_asset(source, output, measurement, camera, allow_refinement=False):
    with zipfile.ZipFile(source) as z:
        skin=next(n for n in z.namelist() if n.endswith('/skin.glb'));root=skin.rsplit('/',1)[0]
        files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    if root+'/identity_fit.json' in files and not allow_refinement:raise ValueError('Use baseline asset, not an already-fitted asset')
    doc,binary=decode_glb(files[skin]); mesh=doc['meshes'][0];p=mesh['primitives'][0]
    base=read_vectors(doc,binary,p['attributes']['POSITION'])
    ply=PlyData.read(io.BytesIO(files[root+'/offset.ply']));v=ply['vertex'].data
    centers=base+np.column_stack([v[n] for n in ('x','y','z')])
    warp=make_warp(measurement,camera)
    new_base=warp(base);new_centers=warp(centers)
    write_vectors(doc,binary,p['attributes']['POSITION'],new_base)
    for t in p['targets']:
        delta=read_vectors(doc,binary,t['POSITION'])
        write_vectors(doc,binary,t['POSITION'],warp(centers+delta)-new_centers)
    for i,key in enumerate(('x','y','z')):v[key]=(new_centers-new_base)[:,i]
    eps=1e-5;J=np.empty((len(centers),3,3))
    for i in range(3):
        step=np.zeros(3);step[i]=eps
        J[:,:,i]=(warp(centers+step)-warp(centers-step))/(2*eps)
    determinants=np.linalg.det(J)
    if not np.isfinite(J).all() or determinants.min()<.2:raise ValueError('Unsafe folding deformation')
    q=np.column_stack([v['rot_'+str(i)] for i in range(4)])
    R=Rotation.from_quat(q[:,[1,2,3,0]]).as_matrix()
    scale=np.exp(np.column_stack([v['scale_'+str(i)] for i in range(3)]))
    T=J@R;cov=(T*scale[:,None,:]**2)@T.transpose(0,2,1)
    eigen,basis=np.linalg.eigh(cov);basis[np.linalg.det(basis)<0,:,0]*=-1
    quat=Rotation.from_matrix(basis).as_quat()[:,[3,0,1,2]]
    for i in range(3):v['scale_'+str(i)]=.5*np.log(np.maximum(eigen[:,i],1e-14))
    for i in range(4):v['rot_'+str(i)]=quat[:,i]
    report={'version':'measured-landmark-fit-v1','max_displacement_m':float(np.linalg.norm(new_centers-centers,axis=1).max()),
            'min_jacobian_determinant':float(determinants.min()),'baseline_error_percent':measurement['error_percent'],
            'measurement':measurement,'camera':camera,'validation':'requires fresh rendered-image measurement'}
    files[skin]=encode_glb(doc,binary);out=io.BytesIO();ply.write(out);files[root+'/offset.ply']=out.getvalue()
    if root+'/identity_fit.json' in files:
        report['previous_pass']=json.loads(files[root+'/identity_fit.json'])
    files[root+'/identity_fit.json']=json.dumps(report,indent=2).encode()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for name,data in files.items():z.writestr(name,data)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('avatar',type=Path);p.add_argument('measurement',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--allow-refinement',action='store_true',help='Explicit further pass using a NEW rendered measurement, never reuse previous residuals')
    args=p.parse_args();record=json.loads((args.avatar/'record.json').read_text())
    camera=record.get('source_camera') or record['generation']['manifest']['source_camera']
    report=fit_asset(args.avatar/'asset.zip',args.output,json.loads(args.measurement.read_text()),camera,args.allow_refinement)
    print(json.dumps({k:v for k,v in report.items() if k not in ('measurement','camera')}))
