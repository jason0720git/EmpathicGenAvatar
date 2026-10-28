"""Exercise CAP4D's gsplat forward/backward on this GPU independently of gated FLAME."""
import json
from pathlib import Path
import time
import torch
from gsplat import rasterization

start = time.monotonic()
means = torch.tensor([[0., 0., 2.]], device='cuda', requires_grad=True)
quats = torch.tensor([[1., 0., 0., 0.]], device='cuda', requires_grad=True)
scales = torch.full((1, 3), .10, device='cuda', requires_grad=True)
opacities = torch.tensor([.8], device='cuda', requires_grad=True)
colors = torch.tensor([[.8, .4, .2]], device='cuda', requires_grad=True)
K = torch.tensor([[[40., 0., 16.], [0., 40., 16.], [0., 0., 1.]]], device='cuda')
rgb, alpha, meta = rasterization(means, quats, scales, opacities, colors,
                                  torch.eye(4, device='cuda')[None], K, 32, 32)
loss = rgb.mean() + alpha.mean()
loss.backward()
torch.cuda.synchronize()
result = {'gpu': torch.cuda.get_device_name(0), 'torch': torch.__version__,
          'cuda': torch.version.cuda, 'render_shape': list(rgb.shape),
          'forward_finite': bool(torch.isfinite(rgb).all()),
          'backward_finite': all(t.grad is not None and bool(torch.isfinite(t.grad).all())
                                 for t in [means, quats, scales, opacities, colors]),
          'seconds_including_first_compile': time.monotonic()-start,
          'scope': 'gsplat kernel only; not CAP4D end-to-end generation'}
Path('/workspace/data/gaussian/reconstruction-v9/cap4d-cuda-probe.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result))
assert result['forward_finite'] and result['backward_finite']
