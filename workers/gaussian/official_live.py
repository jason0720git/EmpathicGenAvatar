"""Local GPU renderer for the original GaussianAvatars 306 checkpoint.

ARKit offsets are fitted to the FLAME expression/jaw basis, not played back
from the example video. Original binding, dental geometry and SH are retained.
"""
import inspect
import io
import json
import math
import time
import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import numpy as np
for key, val in {'bool':bool,'int':int,'float':float,'complex':complex,'object':object,'unicode':str,'str':str}.items():
    if key not in np.__dict__: setattr(np,key,val)
if not hasattr(inspect,'getargspec'): inspect.getargspec=inspect.getfullargspec
import torch
from PIL import Image
from plyfile import PlyData
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from flame_model.flame import FlameHead
from utils.graphics_utils import compute_face_orientation, getProjectionMatrix
from pytorch3d.transforms import matrix_to_quaternion, quaternion_multiply
from diff_gaussian_rasterization import GaussianRasterizationSettings, GaussianRasterizer

ROOT=Path('/workspace')
LOG=ROOT/'data/gaussian/official-live'
LOG.mkdir(parents=True,exist_ok=True)
torch.set_num_threads(4)

class OfficialRenderer:
    @torch.inference_mode()
    def __init__(self):
        self.flame=FlameHead(300,100,add_teeth=True).cuda()
        self.params={k:torch.tensor(v,device='cuda') for k,v in np.load('media/306/flame_param.npz').items()}
        p=self.params
        self.rest=int(torch.linalg.norm(p['jaw_pose'],dim=1).argmin())
        a=PlyData.read('media/306/point_cloud.ply')['vertex'].data
        def cols(prefix,n): return torch.tensor(np.column_stack([a[prefix+str(i)] for i in range(n)]),device='cuda')
        self.xyz=torch.tensor(np.column_stack([a[k] for k in ['x','y','z']]),device='cuda')
        self.binding=cols('binding_',1).long().flatten()
        self.sh=torch.cat([cols('f_dc_',3)[:,None,:],cols('f_rest_',45).reshape(-1,3,15).transpose(1,2)],dim=1).contiguous()
        self.scales=cols('scale_',3).exp()
        self.rot=torch.nn.functional.normalize(cols('rot_',4),dim=-1)
        self.opacity=torch.tensor(a['opacity'].copy(),device='cuda')[:,None].sigmoid()
        zero=torch.zeros((1,100),device='cuda'); jaw=torch.zeros((1,3),device='cuda')
        self.neutral=self.vertices(zero,jaw)[0,:5023]
        # Linearized 100 FLAME expression + three physical jaw-rotation axes.
        exp=self.vertices(torch.eye(100,device='cuda'),jaw.expand(100,-1))[:,:5023]-self.neutral
        jb=(self.vertices(zero.expand(3,-1),torch.eye(3,device='cuda')*.01)[:,:5023]-self.neutral)/.01
        basis=torch.cat([exp,jb]).flatten(1).T
        assets=ROOT/'vendor/LAM/model_zoo/human_parametric_models/flame_assets'
        self.names=json.loads((assets/'pred_expression.json').read_text())['names']
        offsets=torch.tensor(np.load(assets/'flame_arkit_bs.npy'),device='cuda',dtype=torch.float32).flatten(1).T
        assert offsets.shape==(5023*3,len(self.names))
        norm=basis.norm(dim=0).clamp_min(1e-6)
        normalized=basis/norm
        self.mapping=torch.linalg.solve(normalized.T@normalized+torch.eye(103,device='cuda')*.015,normalized.T@offsets)/norm[:,None]
        residual=(basis@self.mapping-offsets).reshape(5023,3,-1).norm(dim=1).mean(0)*1000
        self.fit={n:round(float(v),3) for n,v in zip(self.names,residual)}
        (LOG/'retarget-fit.json').write_text(json.dumps({'rest_frame':self.rest,'mean_vertex_error_mm':self.fit,'driver':'ARKit to FLAME ridge fit; not recorded motion'},indent=2))
        cam=torch.tensor([0.,.03,1.0],device='cuda')
        view=torch.eye(4,device='cuda');view[1,1]=-1;view[2,2]=-1;view[:3,3]=-view[:3,:3]@cam;view=view.T.contiguous()
        fov=math.radians(28);proj=getProjectionMatrix(.01,100,fov,fov).cuda().T.contiguous()
        settings=GaussianRasterizationSettings(image_height=640,image_width=640,tanfovx=math.tan(fov/2),tanfovy=math.tan(fov/2),bg=torch.ones(3,device='cuda'),scale_modifier=1.,viewmatrix=view,projmatrix=view@proj,sh_degree=3,campos=cam,prefiltered=False,debug=False)
        self.raster=GaussianRasterizer(raster_settings=settings)

    def vertices(self,expr,jaw,head=None,gaze=None):
        p=self.params;n=len(expr)
        rotation=torch.zeros((n,3),device='cuda')
        eyes=torch.zeros((n,6),device='cuda')
        if head:
            rotation[:]=torch.tensor([head.get('pitch',0),head.get('yaw',0),head.get('roll',0)],device='cuda').clamp(-20,20)*math.pi/180
        if gaze:
            eyes[:,0]=eyes[:,3]=float(np.clip(gaze.get('y',0),-1,1))*.15
            eyes[:,1]=eyes[:,4]=float(np.clip(gaze.get('x',0),-1,1))*.20
        v,_=self.flame(p['shape'][None].expand(n,-1),expr,rotation,torch.zeros_like(rotation),jaw,eyes,
            p['translation'][[self.rest]].expand(n,-1),return_landmarks=False,return_verts_cano=True,
            static_offset=p['static_offset'],dynamic_offset=torch.zeros_like(p['dynamic_offset'][[self.rest]]).expand(n,-1,-1))
        return v

    @torch.inference_mode()
    def render(self,frame):
        start=time.perf_counter()
        weights=frame.get('weights',{})
        values=[float(np.clip(weights.get(name,0),0,1)) for name in self.names]
        if not np.isfinite(values).all(): raise ValueError('Non-finite weights')
        # The rank-limited FLAME fit under-closes eyelids; calibrated against
        # rendered full-blink poses. Gaze uses physical eyeball rotations below.
        values=[value*1.65 if name.startswith('eyeBlink') else 0.0 if name.startswith('eyeLook') else value for name,value in zip(self.names,values)]
        coeff=self.mapping@torch.tensor(values,device='cuda')
        expr=coeff[:100].clamp(-8,8)[None]
        jaw=coeff[100:].clamp(-.10,.55)[None]
        jaw[:,0].clamp_(0,.55)
        v=self.vertices(expr,jaw,frame.get('head'),frame.get('gaze'))[0]
        orient,scale=compute_face_orientation(v,self.flame.faces,return_scale=True)
        center=v[self.flame.faces].mean(1);b=self.binding
        means=(orient[b]@self.xyz[:,:,None]).squeeze(-1)*scale[b]+center[b]
        rotations=quaternion_multiply(matrix_to_quaternion(orient[b]),self.rot)
        result=self.raster(means3D=means,means2D=torch.zeros_like(means),shs=self.sh,colors_precomp=None,opacities=self.opacity,scales=self.scales*scale[b],rotations=rotations,cov3D_precomp=None)
        im=(result[0].clamp(0,1).permute(1,2,0).cpu().numpy()*255).astype('uint8')
        out=io.BytesIO();Image.fromarray(im).save(out,format='JPEG',quality=90)
        return out.getvalue(),{'render_ms':round((time.perf_counter()-start)*1000,2),'jaw':jaw[0].tolist(),'expression_norm':float(expr.norm()),'splats':len(self.xyz)}

renderer=OfficialRenderer()
app=FastAPI()

@app.get('/health')
def health():
    return {'ready':True,'engine':'GaussianAvatars 306 live FLAME','splats':len(renderer.xyz),'driver':'a2f-arkit-to-flame-v1','fit':renderer.fit}

@app.websocket('/gaussian-render/ws')
async def stream(ws:WebSocket):
    if ws.headers.get('origin') not in {None,'http://127.0.0.1:5174','http://localhost:5174'}:
        await ws.close(code=1008);return
    await ws.accept()
    count=0
    try:
        while True:
            frame=await ws.receive_json()
            raw,stats=renderer.render(frame)
            count+=1
            if count%30==1 or len(str(frame.get('turn_id','')))==24:
                with (LOG/'frames.jsonl').open('a') as log:
                    log.write(json.dumps({'at':time.time(),'sequence':frame.get('sequence'),'turn':frame.get('turn_id'),'pts_ms':frame.get('pts_ms'),'weights':frame.get('weights'),**stats})+'\n')
            await ws.send_json({'sequence':frame.get('sequence'),**stats})
            await ws.send_bytes(raw)
    except WebSocketDisconnect:
        pass

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='0.0.0.0',port=8041,ws_max_size=65536)
