import io,json,zipfile,sys,numpy as np,shutil,hashlib
from pathlib import Path
sys.path.insert(0,'workers/gaussian')
from export_asset import decode_glb,encode_glb
from calibrate_asset import read_vectors
from plyfile import PlyData
for aid in ['2a80fe76d5f44beba2a3c0ac','88546d4a362b4a97979c5360']:
 folder=Path('data/gaussian/avatars')/aid;path=folder/'asset.zip'
 if not (folder/'asset.pre-visibility-v4.zip').exists():shutil.copy2(path,folder/'asset.pre-visibility-v4.zip');shutil.copy2(folder/'record.json',folder/'record.pre-visibility-v4.json')
 with zipfile.ZipFile(path) as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
 skin=next(n for n in files if n.endswith('/skin.glb'));root=skin.rsplit('/',1)[0];d,b=decode_glb(files[skin]);m=d['meshes'][0];p=m['primitives'][0];names=m['extras']['targetNames'];base=read_vectors(d,b,p['attributes']['POSITION']);v=PlyData.read(io.BytesIO(files[root+'/offset.ply']))['vertex'].data;centers=base+np.column_stack([v[k] for k in ['x','y','z']]);rgb=np.column_stack([v['f_dc_'+str(i)] for i in range(3)])
 eyes={}
 for side in ['Left','Right']:
  look=read_vectors(d,b,p['targets'][names.index('eyeLookOut'+side)]['POSITION']);blink=read_vectors(d,b,p['targets'][names.index('eyeBlink'+side)]['POSITION']);mask=(np.linalg.norm(look,axis=1)>.0005)&(np.linalg.norm(blink,axis=1)>.003)
  c=np.median((centers+blink)[mask],axis=0)
  sm=(abs(centers[:,0]-c[0])<.012)&(centers[:,1]>c[1]+.010)&(centers[:,1]<c[1]+.02)&(centers[:,2]>.065)&(rgb[:,0]>rgb[:,1])&(rgb[:,1]>rgb[:,2])
  color=np.median(rgb[sm],axis=0);eyes[side]={'skin':color.tolist(),'seam':c.tolist()};print(aid,side,color,len(rgb[sm]))
 m['extras']['eyeSurface']=eyes;files[skin]=encode_glb(d,b)
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr(root+'/',b'')
  for k,val in files.items():z.writestr(k,val)
 r=json.loads((folder/'record.json').read_text(encoding='utf8'));r['asset_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();(folder/'record.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8')
