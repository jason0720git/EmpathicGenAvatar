"""Render untouched LAM inference with its native FLAME deformation and rasterizer.

No web rig, oral recoloring, eye calibration, landmark warp or dynamics is used.
Stores the learned Gaussian tensors so this comparison is reproducible.
"""
from pathlib import Path
import json
import numpy as np
import torch
from PIL import Image, ImageDraw


@torch.no_grad()
def render_baseline(model, gaussians, points, shape, tracked: Path, output: Path):
    import imageio.v2 as imageio
    from lam.models.rendering.gaussian_model import GaussianModel
    renderer = model.renderer
    frame = json.loads((tracked / 'transforms.json').read_text())['frames'][0]
    pose = dict(np.load(tracked / frame['flame_param_path']))
    c2w = torch.tensor(frame['transform_matrix'], dtype=torch.float32, device='cuda')
    c2w[:3, 1:3] *= -1
    size = 512
    intr = torch.eye(4, device='cuda')
    intr[0, 0] = frame['fl_x'] * size / frame['w']
    intr[1, 1] = frame['fl_y'] * size / frame['h']
    intr[0, 2] = frame['cx'] * size / frame['w']
    intr[1, 2] = frame['cy'] * size / frame['h']
    gs = gaussians[0]
    torch.save({'gaussians': {k: getattr(gs, k).detach().cpu() for k in
                            ['xyz', 'opacity', 'rotation', 'scaling', 'shs', 'offset']},
                'points': points.cpu(), 'shape': shape.cpu(),
                'camera': frame, 'pose': pose}, output / 'native-gaussians.pt')
    bg = torch.ones((1, 3), device='cuda')
    poses = []
    for name, jaw in [('neutral', 0), ('jaw10', .10), ('jaw25', .25), ('jaw45', .45)]:
        params = {k: torch.tensor(pose[k], device='cuda', dtype=torch.float32).reshape(1, -1)
                  for k in ['expr', 'rotation', 'neck_pose', 'jaw_pose', 'eyes_pose', 'translation']}
        params['expr'].zero_()
        params['jaw_pose'].zero_()
        params['jaw_pose'][0, 0] = jaw
        params['eyes_pose'].zero_()
        params['betas'] = shape[None].cuda()
        poses.append((name, params))
    # Same native recorded performance for both identities, keeping the source camera.
    motion_dir = Path('assets/sample_motion/export/Look_In_My_Eyes/flame_param')
    motion_files = sorted(p for p in motion_dir.glob('*.npz') if not p.name.startswith('.'))
    if not motion_files:
        motion_dir = Path('assets/sample_motion/export/Speeding_Scandal/flame_param')
        motion_files = sorted(p for p in motion_dir.glob('*.npz') if not p.name.startswith('.'))
    samples = []
    for i in np.linspace(0, len(motion_files)-1, min(90, len(motion_files))).astype(int):
        recorded = np.load(motion_files[i])
        params = {k: v.clone() for k, v in poses[0][1].items()}
        for k in ['expr', 'jaw_pose', 'eyes_pose']:
            params[k] = torch.tensor(recorded[k], device='cuda', dtype=torch.float32).reshape(1, -1)
        samples.append((f'motion-{i:04d}', params))
    images = []
    mouth_changes = []
    writer = imageio.get_writer(str(output / 'native-motion.mp4'), fps=25, codec='libx264', quality=8)
    try:
        for index, (name, params) in enumerate(poses + samples):
            animated = renderer.animate_gs_model(gs, points[0], params)
            result = renderer.forward_single_batch(animated, c2w[None], intr[None], size, size, bg)
            pixels = (result['comp_rgb'][0].cpu().numpy().clip(0, 1)*255).astype('uint8')
            image = Image.fromarray(pixels)
            if index < 4:
                image.save(output / f'native-{name}.png')
                images.append(image)
            else:
                writer.append_data(pixels)
                if index in [4, 24, 44, 64, 84]:
                    image.save(output / f'native-{name}.png')
            mouth_changes.append(float((animated[0].xyz-gs.xyz).norm(dim=-1).mean()))
    finally:
        writer.close()
    contact = Image.new('RGB', (size*4, size+32), 'white')
    draw = ImageDraw.Draw(contact)
    for i, im in enumerate(images):
        contact.paste(im, (size*i, 32)); draw.text((size*i+10, 8), poses[i][0], fill='black')
    contact.save(output / 'native-jaw-contact.png')
    (output / 'native-validation.json').write_text(json.dumps({
        'scope': 'unmodified LAM neural output and native FLAME animation; dependency compatibility fixes only',
        'frame_count': len(poses)+len(samples), 'motion_source': str(motion_dir),
        'motion_scope': 'recorded expression, jaw, eyes; source global pose and camera fixed',
        'point_count': len(gs.xyz), 'finite': bool(torch.isfinite(gs.xyz).all()),
        'mean_displacement': mouth_changes,
        'independent_tongue': False,
        'visual_quality_pass': None,
    }, indent=2), encoding='utf8')
