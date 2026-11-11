"""306 real-GPU regression: compare legacy root, native neck and anchored renderer.

Run inside gaussian-official-live with vendor/GaussianAvatars as cwd.
Outputs stay under ignored artifacts/. Assertions include actual JPEG pixels,
not just the numerical invariant of the anchor blend.
"""
import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
import torch

ROOT = Path('/workspace')
sys.path.insert(0, str(ROOT / 'workers/gaussian'))
from official_live import HEAD_DRIVER, renderer as r


def jpeg_pixels(raw):
    return np.asarray(Image.open(io.BytesIO(raw)).convert('RGB'), dtype=np.float32)


def roi_diff(image, ref):
    d = np.abs(image-ref).mean(axis=2)
    # Bottom left/right shoulder patches, omitting white background using the
    # *reference* foreground. This mask is independent of renderer anchor weights.
    rows, cols = np.indices(d.shape)
    shoulder = (rows >= 570) & ((cols < 255) | (cols > 385)) & (ref.min(axis=2) < 225)
    face = (rows >= 170) & (rows <= 400) & (cols >= 230) & (cols <= 410)
    if shoulder.sum() < 500: raise AssertionError('Shoulder ROI is empty')
    return {'shoulder_pixels': int(shoulder.sum()), 'shoulder_mae_255': float(d[shoulder].mean()),
            'face_mae_255': float(d[face].mean())}


async def check_live(out, url):
    import websockets
    results=[]
    async with websockets.connect(url, max_size=2*1024*1024) as ws:
        for i,pitch in enumerate((0, 15, 30, 0)):
            await ws.send(json.dumps({'sequence':i, 'turn_id':'qa-306-neck', 'pts_ms':i*33,
                                      'weights':{}, 'head':{'pitch':pitch}}))
            ack=json.loads(await ws.recv())
            im=jpeg_pixels(await ws.recv())
            if not i: ref=im
            delta=roi_diff(im,ref)
            assert ack['head_driver']==HEAD_DRIVER and ack['sequence']==i
            assert ack['applied_head_deg']['pitch']==min(pitch,25) and ack['torso_drift_mm']<.001
            assert delta['shoulder_mae_255']<1
            if pitch: assert delta['face_mae_255']>2
            else: assert not delta['face_mae_255']
            results.append({**ack,**delta})
    (out/'live-acknowledgments.json').write_text(json.dumps(results,indent=2))
    print('Verified four acknowledged and decoded live frames.')


@torch.inference_mode()
def run(out):
    out.mkdir(parents=True, exist_ok=True)
    z = torch.zeros(1, 3, device='cuda')
    e = torch.zeros(1, 100, device='cuda')
    v0 = r.vertices(e,z)[0]
    pos0,_,_ = r.bound_splats(v0)
    # Check the native FLAME neck ring and independent outer lateral bust region.
    face_ids = r.flame.mask.v.nose
    features = torch.cat([face_ids,r.flame.mask.v.forehead,r.flame.mask.v.left_ear,r.flame.mask.v.right_ear]).unique()
    lower = (pos0[:,1] < -.155) & (pos0[:,0].abs() > .075)
    if lower.sum() < 500: raise AssertionError('Independent bust mask is empty')
    neutral, _ = r.render({})
    ref = jpeg_pixels(neutral)
    (out/'neutral.jpg').write_bytes(neutral)
    report = {'driver': HEAD_DRIVER, 'gpu':torch.cuda.get_device_name(0),
              'anchored_splats':r.anchor_ids.numel(), 'independent_bust_splats':int(lower.sum()), 'poses':{}}
    poses = {'nod-down':{'pitch':15},'nod-up':{'pitch':-12}, 'look-left':{'yaw':15},
             'look-right':{'yaw':-15},'roll':{'roll':12},
             'speech-nod':{'pitch':12,'yaw':-5,'roll':3},'clamped-nod':{'pitch':30}}
    p = r.params
    for name, head in poses.items():
        frame = {'head':head}
        if name == 'speech-nod':
            frame.update(weights={'jawOpen':.35,'mouthSmileLeft':.45,'mouthSmileRight':.45,
                                  'eyeBlinkLeft':.35,'eyeBlinkRight':.35},gaze={'x':.4,'y':-.18})
        v = r.vertices(e,z,head)[0]
        neck,rotation,scale = r.bound_splats(v)
        anchored,_,_ = r.anchor_splats(neck,rotation,scale)
        aa = torch.tensor([[head.get(k,0.) for k in ['pitch','yaw','roll']]],device='cuda')*np.pi/180
        legacy,_ = r.flame(p['shape'][None],e,aa,z,z,z.repeat(1,2),
                          p['translation'][[r.rest]],return_landmarks=False,return_verts_cano=True,
                          static_offset=p['static_offset'],dynamic_offset=p['dynamic_offset'][[r.rest]]*0)
        old,_,_ = r.bound_splats(legacy[0])
        old_d = (old[lower]-pos0[lower]).norm(dim=-1)*1000
        native_d = (neck[lower]-pos0[lower]).norm(dim=-1)*1000
        fixed_d = (anchored[lower]-pos0[lower]).norm(dim=-1)*1000
        raw, ack = r.render(frame)
        base_for_pose,_ = r.render({**frame,'head':{}})
        delta = roi_diff(jpeg_pixels(raw),jpeg_pixels(base_for_pose))
        m = dict(**delta, face_nose_mean_mm=float((v[face_ids]-v0[face_ids]).norm(dim=-1).mean()*1000),
                 head_features_mean_mm=float((v[features]-v0[features]).norm(dim=-1).mean()*1000),
                 legacy_bust_p95_mm=float(old_d.quantile(.95)), native_neck_bust_p95_mm=float(native_d.quantile(.95)),
                 anchored_bust_max_mm=float(fixed_d.max()), telemetry=ack)
        report['poses'][name]=m
        assert ack['head_driver']==HEAD_DRIVER and ack['body_root_deg']==[0,0,0]
        assert ack['torso_drift_mm']<1e-4 and m['anchored_bust_max_mm']<.001
        # A rolling head rotates around a line near the nose: use distributed
        # landmarks, not the displacement at a near-pivot point, for this gate.
        assert m['head_features_mean_mm']>3 and m['face_mae_255']>2 and m['legacy_bust_p95_mm']>2, (name,m)
        assert m['shoulder_mae_255']<1., (name,m)
        if name=='clamped-nod': assert ack['applied_head_deg']['pitch']==25.
        if name=='nod-down': assert (v[face_ids,1]-v0[face_ids,1]).mean()<0
        (out/(name+'.jpg')).write_bytes(raw)
    again, _ = r.render({})
    assert np.array_equal(jpeg_pixels(again),ref), 'Returning to neutral changed the image'
    # Interleave motion, blinks and articulation, and retain true end-to-end timings.
    peaks=[]; ms=[]
    for i in range(75):
        phase = float(i)/74
        raw,a=r.render({'head':{'pitch':14*np.sin(phase*np.pi*4),'yaw':7*np.sin(phase*np.pi*2)},
                        'weights':{'jawOpen':.32*abs(np.sin(phase*np.pi*8)), 'eyeBlinkLeft':max(0,1-abs(i-40)/4),
                                   'eyeBlinkRight':max(0,1-abs(i-40)/4)}})
        peaks.append(a['torso_drift_mm']); ms.append(a['render_ms'])
    assert max(peaks)<.001
    report['trajectory']={'frames':len(ms),'max_anchor_mm':max(peaks),'p95_render_ms':float(np.percentile(ms,95))}
    report['scope']='Matched 640px JPEG; lower lateral shoulder foreground MAE, independent canonical lateral-bust splat displacement, nose vertex displacement. Stress cases are not a human-likeness score.'
    (out/'validation.json').write_text(json.dumps(report,indent=2))
    sheet=Image.new('RGB',(320*4,352),'white'); draw=ImageDraw.Draw(sheet)
    for i,name in enumerate(['neutral','nod-down','look-left','speech-nod']):
        im=Image.open(out/(name+'.jpg')).resize((320,320))
        sheet.paste(im,(i*320,32));draw.text((i*320+10,10),name,fill='black')
    sheet.save(out/'official-neck-comparison.jpg',quality=95)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    args=argparse.ArgumentParser()
    args.add_argument('--output',type=Path,default=ROOT/'artifacts/sobia-306-neck')
    args.add_argument('--check-live',action='store_true', help='Also test the running 306 websocket inside this container')
    opts=args.parse_args()
    run(opts.output)
    if opts.check_live: asyncio.run(check_live(opts.output, 'ws://127.0.0.1:8041/gaussian-render/ws'))
