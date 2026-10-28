"""Non-destructive native rig calibration; source portrait pixels are unchanged."""
from __future__ import annotations
import argparse
import io
import json
from pathlib import Path
import zipfile
import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from plyfile import PlyData
from export_asset import accessor_array, decode_glb, encode_glb


def read_vectors(doc, binary, index):
    a = doc['accessors'][index]
    out = np.zeros((a['count'], 3), dtype=np.float32)
    if 'bufferView' in a:
        plain = dict(a); plain.pop('sparse', None)
        temporary = dict(doc); temporary['accessors'] = list(doc['accessors']); temporary['accessors'][index] = plain
        out[:] = accessor_array(temporary, binary, index).reshape(-1, 3)
    if 'sparse' in a:
        s = a['sparse']; si = s['indices']; sv = s['values']
        iv = doc['bufferViews'][si['bufferView']]; vv = doc['bufferViews'][sv['bufferView']]
        ids = np.frombuffer(binary, dtype={5121:'u1',5123:'<u2',5125:'<u4'}[si['componentType']], count=s['count'], offset=iv.get('byteOffset',0)+si.get('byteOffset',0))
        out[ids] = np.frombuffer(binary, dtype='<f4', count=s['count']*3, offset=vv.get('byteOffset',0)+sv.get('byteOffset',0)).reshape(-1,3)
    return out


def write_vectors(doc, binary, index, values):
    values = np.asarray(values, dtype='<f4')
    binary.extend(b'\0' * (-len(binary) % 4))
    view = len(doc['bufferViews'])
    doc['bufferViews'].append({'buffer':0, 'byteOffset':len(binary), 'byteLength':values.nbytes})
    binary.extend(values.tobytes())
    doc['accessors'][index] = {'bufferView':view, 'componentType':5126, 'count':len(values), 'type':'VEC3', 'min':values.min(0).tolist(), 'max':values.max(0).tolist()}
    doc['buffers'][0]['byteLength'] = len(binary)


def calibrate(source: Path, output: Path, lower_face: bool = False):
    with zipfile.ZipFile(source) as z:
        skin = next(n for n in z.namelist() if n.endswith('/skin.glb') and not n.startswith('__MACOSX'))
        root = skin.rsplit('/',1)[0]
        files = {n:z.read(n) for n in z.namelist() if not n.endswith('/') and n.startswith(root+'/')}
    doc, binary = decode_glb(files[skin]); mesh = doc['meshes'][0]; p = mesh['primitives'][0]
    if root+'/calibration.json' in files:
        raise ValueError('Already calibrated; use the original uncalibrated asset')
    vertices = read_vectors(doc,binary,p['attributes']['POSITION'])
    ply = PlyData.read(io.BytesIO(files[root+'/offset.ply'])); v = ply['vertex'].data
    offsets = np.column_stack([v[k] for k in ('x','y','z')])
    centers = vertices + offsets
    if vertices.shape != (20018,3) or not np.isfinite(centers).all():
        raise ValueError('Expected 20,018 finite LAM Gaussian centers')
    names = mesh['extras']['targetNames']
    morphs = {n:read_vectors(doc,binary,p['targets'][i]['POSITION']) for i,n in enumerate(names)}
    report = {'version':'native-calibration-v1','lower_face_profile':('seoyeon-shorter-lower-face-v1' if lower_face else None),'eyes':{}}
    # Learned Gaussian centers are offset from their canonical mesh anchors.
    # Interpolate eyelid motion at the actual center rather than blindly using
    # the original anchor's movement (which can carry iris pixels onto the lid).
    tree = cKDTree(vertices)
    distances, neighbors = tree.query(centers, k=8)
    weights = 1 / np.maximum(distances, 0.00015)**3
    weights /= weights.sum(1,keepdims=True)
    for side in ('Left','Right'):
        name = 'eyeBlink'+side; delta = morphs[name]
        active = np.linalg.norm(delta,axis=1) > .0025
        if not active.any():
            raise ValueError('Missing usable eyelid displacement: '+name)
        lo,hi = vertices[active].min(0),vertices[active].max(0)
        region = np.all((centers > lo - [.008,.010,.008]) & (centers < hi + [.008,.010,.018]),axis=1)
        replacement = (delta[neighbors] * weights[:,:,None]).sum(1)
        delta[region] = replacement[region]
        report['eyes'][side] = {'rebound_gaussians':int(region.sum()),'bounds':[lo.tolist(),hi.tolist()]}
    # Explicit per-avatar art-direction profile. Never silently apply these
    # proportions to every identity: the public CLI defaults to eye repair only.
    def warp(points):
        if not lower_face: return points.copy()
        result = points.copy(); y = points[:,1]
        frontal = np.clip((points[:,2]-.005)/.045,0,1)
        frontal = frontal*frontal*(3-2*frontal)
        dy = np.interp(y,[1.48,1.555,1.587,1.628,1.657,1.71,1.81],[0,0,.011,.006,0,0,0])
        result[:,1] += dy*frontal
        width = .045*np.exp(-((y-1.632)/.032)**2)*frontal
        result[:,0] *= 1+width
        return result
    new_vertices, new_centers = warp(vertices), warp(centers)
    write_vectors(doc,binary,p['attributes']['POSITION'],new_vertices)
    for i,n in enumerate(names):
        transformed = warp(centers+morphs[n])-new_centers
        write_vectors(doc,binary,p['targets'][i]['POSITION'],transformed)
    for axis,key in enumerate(('x','y','z')):v[key] = (new_centers-new_vertices)[:,axis]
    if lower_face:
        # Transform Gaussian covariance under the same local deformation.
        eps = 1e-5; J = np.empty((len(centers),3,3))
        for axis in range(3):
            step=np.zeros(3);step[axis]=eps
            J[:,:,axis]=(warp(centers+step)-warp(centers-step))/(2*eps)
        q=np.column_stack([v['rot_'+str(i)] for i in range(4)])
        R=Rotation.from_quat(q[:,[1,2,3,0]]).as_matrix()
        scale=np.exp(np.column_stack([v['scale_'+str(i)] for i in range(3)]))
        T=J@R; cov=(T*scale[:,None,:]**2)@T.transpose(0,2,1)
        eigen,basis=np.linalg.eigh(cov)
        bad=np.linalg.det(basis)<0;basis[bad,:,0]*=-1
        quat=Rotation.from_matrix(basis).as_quat()[:,[3,0,1,2]]
        for i in range(3):v['scale_'+str(i)]=.5*np.log(np.maximum(eigen[:,i],1e-14))
        for i in range(4):v['rot_'+str(i)]=quat[:,i]
    files[skin]=encode_glb(doc,binary)
    out=io.BytesIO();ply.write(out);files[root+'/offset.ply']=out.getvalue()
    files[root+'/calibration.json']=json.dumps(report,indent=2).encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for n,raw in files.items():z.writestr(n,raw)
    return report


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('source',type=Path);ap.add_argument('output',type=Path);ap.add_argument('--lower-face',action='store_true')
    a=ap.parse_args();print(json.dumps(calibrate(a.source,a.output,a.lower_face)))
