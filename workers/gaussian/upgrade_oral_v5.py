"""Separate soft oral tissue from native dental appearance; preserve identity rig."""
import io,json,zipfile,sys,hashlib,shutil
from pathlib import Path
import numpy as np
from plyfile import PlyData,PlyElement
from export_asset import decode_glb,encode_glb
from calibrate_asset import read_vectors,write_vectors

def upgrade(folder):
 folder=Path(folder);path=folder/'asset.zip';backup=folder/'asset.pre-hybrid-v5.zip'
 if not backup.exists():shutil.copy2(path,backup);shutil.copy2(folder/'record.json',folder/'record.pre-hybrid-v5.json')
 with zipfile.ZipFile(backup) as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
 skin=next(n for n in files if n.endswith('/skin.glb'));root=skin.rsplit('/',1)[0];d,b=decode_glb(files[skin]);m=d['meshes'][0];p=m['primitives'][0];oral=m['extras']['oral'];base=read_vectors(d,b,p['attributes']['POSITION']);v=PlyData.read(io.BytesIO(files[root+'/offset.ply']))['vertex'].data.copy();n=oral['base_count'];a=np.array(oral['anchor']);w=oral['halfwidth']
 ids=np.arange(n+375,n+650)
 for i in ids:
  u=(base[i,0]-a[0])/(w*.72);z=(base[i,2]-a[2]+.006)/.004;dome=np.sqrt(max(0,1-u*u-z*z))
  base[i,1]=a[1]-.005+.003*dome;base[i,2]=a[2]-.003+z*.004
  for k,c in enumerate([.42+.045*dome,.16+.025*dome,.18+.022*dome]):v['f_dc_'+str(k)][i]=c
  for k,scale in enumerate([.00135,.0012,.0015]):v['scale_'+str(k)][i]=np.log(scale)
 write_vectors(d,b,p['attributes']['POSITION'],base)
 for name,target in zip(m['extras']['targetNames'],p['targets']):
  if name not in ['jawOpen','mouthClose','tongueOut']:continue
  delta=read_vectors(d,b,target['POSITION'])
  if name=='jawOpen':delta[ids]=[0,-.025,-.004]
  if name=='mouthClose':delta[ids]=[0,.025*.65,.004*.65]
  if name=='tongueOut':delta[ids]=[0,.001,.006]
  write_vectors(d,b,target['POSITION'],delta)
 oral['version']='hybrid-oral-v5';oral['policy']='runtime preserves native topology and shades lower oral tissue; all supplemental surfaces disabled after visual QA'
 files[skin]=encode_glb(d,b);files[root+'/oral.json']=json.dumps(oral).encode();out=io.BytesIO();PlyData([PlyElement.describe(v,'vertex')]).write(out);files[root+'/offset.ply']=out.getvalue()
 temp=folder/'hybrid.tmp'
 with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr(root+'/',b'')
  for k,value in files.items():z.writestr(k,value)
 temp.replace(path);r=json.loads((folder/'record.json').read_text(encoding='utf8'));r['asset_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();r['oral_version']='hybrid-oral-v5';(folder/'record.json').write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf8');print(folder.name,r['asset_sha256'])
if __name__=='__main__':
 for folder in sys.argv[1:]:upgrade(folder)
