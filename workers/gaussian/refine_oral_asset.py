"""Add an explicit, jaw-driven Gaussian oral cavity, teeth and tongue.

Experimental supplemental oral surfaces. LAM already has teeth support in its
FLAME implementation; do not interpret this augmentation as missing native teeth.
Disabled by default in the web renderer after floating-teeth regressions (2026-09-29).
Original assets are retained.
"""
import argparse
import io
import json
import zipfile
from pathlib import Path
import numpy as np
from plyfile import PlyData, PlyElement
from scipy.spatial import cKDTree
from export_asset import decode_glb, encode_glb, accessor_array
from calibrate_asset import read_vectors, write_vectors


def write_attribute(doc, binary, index, values, kind, component=5126):
    dtype={5126:'<f4',5123:'<u2',5121:'u1',5125:'<u4'}[component]
    values=np.asarray(values,dtype=dtype); binary.extend(b'\0'*(-len(binary)%4))
    view=len(doc['bufferViews']);doc['bufferViews'].append({'buffer':0,'byteOffset':len(binary),'byteLength':values.nbytes})
    binary.extend(values.tobytes());doc['accessors'][index]={'bufferView':view,'componentType':component,'count':len(values),'type':kind}
    doc['buffers'][0]['byteLength']=len(binary)


def augment(source, output, measurement, camera):
    with zipfile.ZipFile(source) as z: files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    skin=next(n for n in files if n.endswith('/skin.glb'));root=skin.rsplit('/',1)[0]
    if root+'/oral.json' in files: raise ValueError('Use an asset without oral augmentation')
    doc,binary=decode_glb(files[skin]);mesh=doc['meshes'][0];p=mesh['primitives'][0]
    base=read_vectors(doc,binary,p['attributes']['POSITION']); n=len(base)
    v=PlyData.read(io.BytesIO(files[root+'/offset.ply']))['vertex'].data.copy()
    centers=base+np.column_stack([v[k] for k in ('x','y','z')])
    origin=np.array(camera['position']);forward=np.array(camera['target'])-origin;forward/=np.linalg.norm(forward)
    right=np.cross(forward,camera['up']);right/=np.linalg.norm(right);up=np.cross(right,forward)
    h,w=measurement['render_size'];f=h/(2*np.tan(np.radians(camera['fov'])/2));rel=centers-origin;depth=rel@forward
    uv=np.column_stack([w/2+f*(rel@right)/depth,h/2-f*(rel@up)/depth])
    lm=np.array(measurement['target_landmarks'])
    # Use visible lip points to locate each identity, rather than fixed head dimensions.
    def anchor(index):
        ids=np.argsort(np.linalg.norm(uv-lm[index],axis=1))[:20]
        ids=ids[np.argsort(depth[ids])[:8]]
        return np.median(centers[ids],axis=0)
    upper,lower=anchor(62),anchor(66);middle=(upper+lower)/2
    halfwidth=np.linalg.norm(anchor(54)-anchor(48))*.39
    halfwidth=float(np.clip(halfwidth,.014,.025))
    jaw=read_vectors(doc,binary,p['targets'][mesh['extras']['targetNames'].index('jawOpen')]['POSITION'])
    # Reconstructed hidden points carry invented bright colors. Suppress only
    # the recessed oral volume, leaving the visible lip surface unchanged.
    x,y,z=(centers-middle).T
    recessed=(abs(x)<halfwidth*.95)&(y>-.007)&(y<.012)&(z<-.004)&(z>-.045)
    bright=np.column_stack([v['f_dc_'+str(i)] for i in range(3)]).mean(1)>.52
    # Visibility-dependent shading belongs in the renderer. A permanent color
    # change can darken the closed mouth corners, so retain all learned colors.
    repair=recessed&bright&False
    for i,col in enumerate((.13,.045,.04)): v['f_dc_'+str(i)][repair]=col
    positions=[];colors=[];scales=[];motion=[];groups=[]
    def point(pos,color,scale,delta,group):
        positions.append(pos+middle);colors.append(color);scales.append(scale);motion.append(delta);groups.append(group)
    # Back wall: curved, dark, extends behind the opening under jaw movement.
    for u in np.linspace(-1,1,25):
        for t in np.linspace(0,1,15):
            point(np.array([u*halfwidth,.007-t*.015,-.019-.005*(1-u*u)]),
                  [.075,.025,.022],[.0017,.0015,.0012],[0,-.030*t,-.006*t],'cavity')
    # Tongue dome: muted red, attached to the lower oral floor; no tongueOut
    # claim. The surface follows jawOpen and lateral jaw articulation.
    for u in np.linspace(-1,1,23):
        for t in np.linspace(-1,1,17):
            if u*u+t*t>1:continue
            dome=np.sqrt(max(0,1-u*u-t*t))
            point(np.array([u*halfwidth*.72,-.003+.0025*dome,-.009+t*.004]),
                  [.40+.035*dome,.14+.015*dome,.16+.015*dome],[.00135,.0010,.00135],[0,-.018,-.004],'tongue')
    # Distinct crowns instead of a continuous white sheet. Shaded at gum/root.
    for lower_row in (False,True):
        for tooth in range(8):
            cx=(tooth-3.5)*halfwidth*.22
            for dx in np.linspace(-.0015,.0015,3):
                for t in np.linspace(0,1,5):
                    yy=(.001+.005*t) if not lower_row else (-.001-.004*t)
                    zz=-.005-.004*(cx/halfwidth)**2-(.002 if lower_row else 0)
                    shade=.76-.12*t
                    point(np.array([cx+dx,yy,zz]),[shade,shade*.94,shade*.85],
                          [.00085,.0008,.0006],[0,0,0] if not lower_row else [0,-.031,-.008],
                          'upper_teeth' if not lower_row else 'lower_teeth')
    added=np.asarray(positions);delta=np.asarray(motion);count=len(added)
    nearest=cKDTree(base).query(added)[1]
    for name,index in p['attributes'].items():
        a=doc['accessors'][index];dims={'VEC2':2,'VEC3':3,'VEC4':4,'SCALAR':1}[a['type']]
        if name=='POSITION':write_vectors(doc,binary,index,np.vstack([base,added]));continue
        view=doc['bufferViews'][a['bufferView']]
        dtype={5126:'<f4',5123:'<u2',5121:'u1',5125:'<u4'}[a['componentType']]
        old=np.frombuffer(binary,dtype=dtype,count=n*dims,offset=view.get('byteOffset',0)+a.get('byteOffset',0)).reshape(n,dims).copy()
        write_attribute(doc,binary,index,np.vstack([old,old[nearest]]),a['type'],a['componentType'])
    for i,target in enumerate(p['targets']):
        name=mesh['extras']['targetNames'][i]
        old=read_vectors(doc,binary,target['POSITION']);extra=np.zeros_like(added)
        if name=='jawOpen':extra=delta
        elif name=='mouthClose':extra=-delta*.65
        elif name in ('jawLeft','jawRight','jawForward'):
            extra=old[nearest].copy();extra[np.array(groups)=='upper_teeth']=0
        write_vectors(doc,binary,target['POSITION'],np.vstack([old,extra]))
    # The base rig has 51 channels. Add a genuine tongueOut channel confined
    # to the new tongue surface, so A2F can drive it without moving the lips.
    tongue_delta=np.zeros((n+count,3),dtype=np.float32)
    tongue_ids=n+np.flatnonzero(np.array(groups)=='tongue')
    tongue_delta[tongue_ids]=[0,.0015,.009]
    tongue_accessor=len(doc['accessors']);doc['accessors'].append({})
    write_vectors(doc,binary,tongue_accessor,tongue_delta)
    p['targets'].append({'POSITION':tongue_accessor});mesh['extras']['targetNames'].append('tongueOut')
    if 'weights' in mesh:mesh['weights'].append(0.)
    for node in doc.get('nodes',[]):
        if node.get('mesh')==0 and 'weights' in node:node['weights'].append(0.)
    extra=np.zeros(count,dtype=v.dtype)
    for i in range(3):extra['f_dc_'+str(i)]=np.asarray(colors)[:,i];extra['scale_'+str(i)]=np.log(np.asarray(scales)[:,i])
    extra['opacity']=3.6;extra['rot_0']=1
    output_ply=PlyData([PlyElement.describe(np.concatenate([v,extra]),'vertex')]);buf=io.BytesIO();output_ply.write(buf)
    files[root+'/offset.ply']=buf.getvalue()
    files[root+'/vertex_order.json']=json.dumps(list(range(n+count))).encode()
    report={'version':'explicit-oral-gaussians-v1','anchor':middle.tolist(),'halfwidth':halfwidth,
            'recessed_bright_points_repaired':int(repair.sum()),'added':count,
            'base_count':n,'parts':{k:groups.count(k) for k in set(groups)},'tongue_control':'jawOpen + supplemental tongueOut'}
    mesh['extras']['oral']=report
    files[skin]=encode_glb(doc,binary)
    files[root+'/oral.json']=json.dumps(report,indent=2).encode()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for k,value in files.items():z.writestr(k,value)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('record',type=Path);p.add_argument('measurement',type=Path);p.add_argument('output',type=Path)
    args=p.parse_args();record=json.loads(args.record.read_text())
    print(json.dumps(augment(args.source,args.output,json.loads(args.measurement.read_text()),record['source_camera'])))
