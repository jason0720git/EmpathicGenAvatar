"""Round and recess procedural dental crowns; preserve learned facial geometry."""
import io,json,zipfile,hashlib,shutil
from pathlib import Path
import numpy as np
from plyfile import PlyData,PlyElement
from export_asset import decode_glb,encode_glb
from calibrate_asset import read_vectors,write_vectors

def upgrade(folder):
    folder=Path(folder);path=folder/'asset.zip';backup=folder/'asset.pre-oral-v3.zip'
    if not backup.exists():
        shutil.copy2(path,backup);shutil.copy2(folder/'record.json',folder/'record.pre-oral-v3.json')
    with zipfile.ZipFile(backup) as z:files={n:z.read(n) for n in z.namelist() if not n.endswith('/')}
    root=next(n.rsplit('/',1)[0] for n in files if n.endswith('/skin.glb'))
    doc,binary=decode_glb(files[root+'/skin.glb']);mesh=doc['meshes'][0];p=mesh['primitives'][0];oral=mesh['extras']['oral']
    assert oral['version']=='explicit-oral-gaussians-v2'
    base=read_vectors(doc,binary,p['attributes']['POSITION']);n=oral['base_count'];anchor=np.array(oral['anchor']);width=oral['halfwidth']
    v=PlyData.read(io.BytesIO(files[root+'/offset.ply']))['vertex'].data.copy()
    # Elliptical crowns in a recessed dental arch. Tapered tips and graded opacity
    # eliminate the rectangular grid silhouette; lateral teeth recede into shadow.
    for lower in (False,True):
        for tooth in range(8):
            u=(tooth-3.5)/3.5;cx=u*width*.72
            length=([.0032,.0038,.0042,.0048,.0048,.0042,.0038,.0032][tooth])*(.72 if lower else 1)
            for ix in range(3):
                for row in range(5):
                    i=n+650+int(lower)*120+tooth*15+ix*5+row;t=row/4
                    taper=np.sqrt(max(.20,1-((t-.40)/.8)**2))
                    x=cx+(ix-1)*width*.057*taper
                    y=(-.005+length*t if lower else -.0012-length*t)-.0022*u*u
                    z=-.009-.010*u*u+.0006*(1-(ix-1)**2)
                    base[i]=anchor+[x,y,z-(.001 if lower else 0)]
                    scales=[width*.049*taper,length*.22,.0007]
                    for k in range(3):v['scale_'+str(k)][i]=np.log(scales[k])
                    shade=(.56+.055*np.sin(np.pi*t))*(1-.34*abs(u)**1.5)*(.65 if lower else 1)
                    for k,c in enumerate([shade,shade*.94,shade*.83]):v['f_dc_'+str(k)][i]=c
                    v['opacity'][i]=1.5 if row in (0,4) else 2.6
    write_vectors(doc,binary,p['attributes']['POSITION'],base)
    oral['version']='explicit-oral-gaussians-v3';oral['dental_surface']='recessed-rounded-arch'
    files[root+'/oral.json']=json.dumps(oral).encode();files[root+'/skin.glb']=encode_glb(doc,binary)
    out=io.BytesIO();PlyData([PlyElement.describe(v,'vertex')]).write(out);files[root+'/offset.ply']=out.getvalue()
    temp=folder/'oral-v3.tmp'
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr(root+'/',b'')
        for name,data in files.items():z.writestr(name,data)
    temp.replace(path)
    record=json.loads((folder/'record.json').read_text(encoding='utf8'));record['asset_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();record['oral_version']=oral['version']
    (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
    print(folder.name,record['asset_sha256'])
if __name__=='__main__':
    import sys
    for folder in sys.argv[1:]:upgrade(folder)
