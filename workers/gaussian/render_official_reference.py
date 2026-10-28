"""Render the actual official subject 306 checkpoint, not a photo reconstruction.
Uses its recorded FLAME sequence; does not pretend to accept ARKit/A2F weights.
"""
import sys,inspect,math,json
from pathlib import Path
import numpy as np
for key,val in {'bool':bool,'int':int,'float':float,'complex':complex,'object':object,'unicode':str,'str':str}.items():
 if key not in np.__dict__:setattr(np,key,val)
if not hasattr(inspect,'getargspec'):inspect.getargspec=inspect.getfullargspec
import torch
from plyfile import PlyData
from PIL import Image
sys.path.insert(0,str(Path.cwd()))
from flame_model.flame import FlameHead
from utils.graphics_utils import compute_face_orientation,getProjectionMatrix
from pytorch3d.transforms import matrix_to_quaternion,quaternion_multiply
from diff_gaussian_rasterization import GaussianRasterizationSettings,GaussianRasterizer
out=Path('/workspace/data/gaussian/reference306');out.mkdir(exist_ok=True,parents=True)
f=FlameHead(300,100,add_teeth=True).cuda()
p={k:torch.tensor(v,device='cuda') for k,v in np.load('media/306/flame_param.npz').items()}
a=PlyData.read('media/306/point_cloud.ply')['vertex'].data
def cols(prefix,n):return torch.tensor(np.column_stack([a[prefix+str(i)] for i in range(n)]),device='cuda')
xyz=torch.tensor(np.column_stack([a[k] for k in ['x','y','z']]),device='cuda');binding=cols('binding_',1).long().flatten()
sh=torch.cat([cols('f_dc_',3)[:,None,:],cols('f_rest_',45).reshape(-1,3,15).transpose(1,2)],dim=1).contiguous()
scales=cols('scale_',3).exp();rot=torch.nn.functional.normalize(cols('rot_',4),dim=-1);opacity=cols('opacity',0) if False else torch.tensor(a['opacity'].copy(),device='cuda')[:,None].sigmoid()
frames=int(sys.argv[1]) if len(sys.argv)>1 else 1
with torch.no_grad():
 for i in range(frames):
  t=i%len(p['expr'])
  v,_=f(p['shape'][None],p['expr'][[t]],p['rotation'][[t]],p['neck_pose'][[t]],p['jaw_pose'][[t]],p['eyes_pose'][[t]],p['translation'][[t]],zero_centered_at_root_node=False,return_landmarks=False,return_verts_cano=True,static_offset=p['static_offset'],dynamic_offset=p['dynamic_offset'][[t]])
  v=v[0];faces=f.faces
  orient,scale=compute_face_orientation(v,faces,return_scale=True);center=v[faces].mean(1)
  means=(orient[binding]@xyz[:,:,None]).squeeze(-1)*scale[binding]+center[binding]
  rotations=quaternion_multiply(matrix_to_quaternion(orient[binding]),rot)
  if i==0:
   mid=v[:5023].median(0).values;print('bounds',v.min(0).values.tolist(),v.max(0).values.tolist(),flush=True)
   cam=torch.tensor([0.,.03,1.0],device='cuda')
   view=torch.eye(4,device='cuda');view[1,1]=-1;view[2,2]=-1;view[:3,3]=-view[:3,:3]@cam;view=view.T.contiguous()
   fov=math.radians(28);proj=getProjectionMatrix(.01,100,fov,fov).cuda().T.contiguous();full=view@proj
   settings=GaussianRasterizationSettings(image_height=640,image_width=640,tanfovx=math.tan(fov/2),tanfovy=math.tan(fov/2),bg=torch.ones(3,device='cuda'),scale_modifier=1.,viewmatrix=view,projmatrix=full,sh_degree=3,campos=cam,prefiltered=False,debug=False)
   raster=GaussianRasterizer(raster_settings=settings)
  result=raster(means3D=means,means2D=torch.zeros_like(means),shs=sh,colors_precomp=None,opacities=opacity,scales=scales*scale[binding],rotations=rotations,cov3D_precomp=None)
  im=result[0].clamp(0,1).permute(1,2,0).cpu().numpy();Image.fromarray((im*255).astype('uint8')).save(out/f'frame-{i:04}.png')
  if i%25==0:print('frame',i,flush=True)
(out/'provenance.json').write_text(json.dumps({'repository':'https://github.com/ShenhanQian/GaussianAvatars','subject':'306','frames':frames,'splats':len(a),'driver':'original recorded FLAME parameters','a2f_compatible':False},indent=2))
