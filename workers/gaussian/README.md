# Local portrait to controllable 3DGS worker

This isolated worker uses the official LAM-20K checkpoint and FLAME fitting to
generate actual Gaussian appearance from the submitted image. It exports an
ARKit-rigged ZIP consumed by `gaussian-splat-renderer-for-lam` in the browser.
It never sends portrait images to third-party inference services.

## Setup

From the repository root, using Python 3.11+ and Docker Desktop with GPU access:

```powershell
git clone https://github.com/aigc3d/LAM.git vendor/LAM
git -C vendor/LAM checkout 339573649dd93df4cba8093a964e85a80d1b61f3
git clone https://github.com/aigc3d/LAM_WebRender.git vendor/LAM_WebRender
git -C vendor/LAM_WebRender checkout 12174e944957fc6445f235c5e0ff7e3e16ba209a
python workers/gaussian/bootstrap_assets.py --lam-root vendor/LAM --cache models/lam-downloads
docker compose -f workers/gaussian/compose.yml up -d --build
```

The Dockerfile uses the already-built `empathic-avatar-avatar-worker:latest`
image as its CUDA 12.8 / PyTorch base. Build the project's GPU avatar worker first
on a fresh machine, or pass an equivalent `BASE_IMAGE` build argument.

Models are approximately 3.6GB before extraction. Official weights are
CC-BY-NC-4.0. FLAME and third-party models/code retain separate terms. This setup
is a local research prototype, not a declaration of commercial rights.

## Service contract

Host `127.0.0.1:8040`, container `8020`.

```json
POST /generate
{
  "job_id": "portrait-001",
  "image_path": "/gaussian-data/avatars/portrait/source.png",
  "output_dir": "/gaussian-data/avatars/portrait"
}
```

`/gaussian-data` binds the repository's `data/gaussian` directory. Requests are
synchronous (up to 20 minutes for initial compilation), and only one generation
job may run at once. `/health` remains responsive. A subprocess releases CUDA
memory when the job ends. `ready` checks required assets, CUDA, the pinned
Diffusers version and execution of all four learned attention normalizations;
`verified_generation` separately records whether an actual job has succeeded.

The response includes `asset_path`, `preview_path`, `manifest_path`, `duration_ms`
and the provenance manifest. The preview PNG is the segmented input, **not** a
rendered reconstruction. The app renders `avatar.zip` to inspect the real result.

Logs and troubleshooting:

- `GET /jobs/{job_id}`: current stage and stage timings.
- `data/gaussian/jobs/{job_id}/worker.log`: complete model/compiler output.
- `data/gaussian/jobs/{job_id}/events.jsonl`: structured stages and errors.
- `data/gaussian/jobs/{job_id}/tracking/`: landmark/geometry fitting artifacts.
- `data/gaussian/avatars/{avatar_id}/generation.json`: model/source/output hashes,
  exact upstream commits, elapsed time, supported blendshapes and exporter type.

## Export and control

Every output ZIP contains one `avatar/` folder with `skin.glb`, `offset.ply`,
`animation.glb`, and `vertex_order.json`. The official ARKit template supports
51 facial targets, including eye look, blink, jaw and mouth coefficients. It
does not contain `tongueOut`. Head motion uses the rig's head/neck bones.

`export_asset.py` verifies all 119,712 triangle indices and a sub-micrometer
constant translation between the official template FBX and sample GLB. Only
newly reconstructed canonical vertex positions are injected into the rig.
Gaussian attributes are produced by LAM from the submitted photograph. Existing
template expression deltas and weights are retained, as in the upstream exporter.
This avoids requiring the Python-3.10-only Autodesk SDK and Blender for each job.
The pinned SDK loads `vertex_order.json` but does not apply it. Direct vertex
index correspondence is the operative contract. Revisit this when changing
the renderer version rather than assuming the legacy list remaps buffers.

```powershell
python -m unittest discover -s workers/gaussian -p test_export_asset.py -v
```

The frontend should combine Audio2Face mouth coefficients with its explicit
gaze, head and empathy controller. Suppress unrelated demo animation clips so
automatic gesture playback does not override the requested behavior. Facial
coefficients are renderer-specific, not proof of perceived emotional accuracy.

## Measured local generation

On 2026-09-23 the corrected RTX 5090 worker reconstructed the project's approved
portrait in **30.7s** (**31.9s** including process/HTTP overhead), of which
Gaussian prediction was **693ms**. The browser rendered the recognizable source
woman with correct color and a head/shoulder crop at approximately **64FPS**.
The result has 20,018 points and 51 ARKit targets. Initial native extension
compilation is a one-time cost. Evidence:
`data/gaussian/jobs/user-portrait-967df7-normfix/status.json`, its generation
manifest, and the main task's browser visual test. These are local measurements.

An earlier package-complete prototype was visually corrupted because the Ditto
base's Diffusers 0.30.2 processor ignored LAM's learned query/key normalization.
The generator now pins 0.32.2, executes a four-normalization startup check, and
has a regression test. Structural ZIP validity alone is not a quality test.
