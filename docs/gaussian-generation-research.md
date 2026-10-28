# Single-image controllable 3DGS generation: research and implementation

Reviewed 2026-09-23 against official repositories and the local code revisions.

## Chosen path

LAM-20K provides a single-image Gaussian head generator and a separately
renderable artifact. Its official WebGL package already consumes ARKit-style
expression coefficients, matching NVIDIA Audio2Face output and a behavioral
controller without learning an ARKit-to-FLAME inverse mapping. Generation runs
once; conversation streams small control vectors while the browser renders.
The paper's reported feed-forward speed excludes our full preprocessing,
landmark fitting, model loading and ZIP export. We measure the complete path.

Sources: [LAM paper/project](https://aigc3d.github.io/projects/LAM/),
[LAM code](https://github.com/aigc3d/LAM),
[WebRender](https://github.com/aigc3d/LAM_WebRender).

## Compared alternatives

| Candidate | Relevant capability | Integration decision |
|---|---|---|
| LAM, SIGGRAPH 2025 | One portrait to FLAME-bound Gaussian attributes; official ARKit export and WebGL runtime | Implement now: strongest fit for explicit A2F/controller separation |
| GaussianAvatars, CVPR 2024 | Subject-specific rigged 3D Gaussians with FLAME motion and view control | Good controlled-quality benchmark; capture/training workflow is less direct than one-image generation |
| GAGAvatar, NeurIPS 2024 | One-shot head reconstruction and real-time reenactment; 32-channel Gaussian features | Useful comparison; its neural feature rendering path does not drop directly into the lightweight ARKit WebGL artifact |
| ARTalk, 2025 | Audio-to-expression/head-pose sequences; can pair with GAGAvatar | Alternative speech-motion generator; integrating it alongside A2F would require explicit authority between both motion sources |
| LAM Audio2Expression, 2025 | Speech-to-ARKit coefficients | Potential alternative to A2F, not needed for the first user-requested A2F path |

Sources: [GaussianAvatars](https://github.com/ShenhanQian/GaussianAvatars),
[GAGAvatar](https://github.com/xg-chu/GAGAvatar),
[ARTalk](https://github.com/xg-chu/ARTalk),
[LAM Audio2Expression](https://github.com/aigc3d/LAM_Audio2Expression).

LAM's current README also announces PanoLAM (September 2025) and MeshLAM
(CVPR 2026 technical report, April 2026). Those announcements do not establish
that the same deployable ARKit Gaussian artifact and current renderer contract
are available. The implemented baseline remains the audited public LAM-20K
weights rather than silently substituting an untested paper model.

## Exact components and licenses

| Component | Pin / source | Terms observed |
|---|---|---|
| LAM source | `339573649dd93df4cba8093a964e85a80d1b61f3` | Top-level Apache-2.0; individual bundled modules retain their own headers |
| LAM weights | `3DAIGC/LAM-20K`, SHA256 `f527e6e78fd9743aad95cb15b221b864d8b6d356c1d174c0ffad5d74b9a95925` | `LICENSE_WEIGHT`: CC-BY-NC-4.0 |
| LAM_WebRender | `12174e944957fc6445f235c5e0ff7e3e16ba209a`; npm `0.0.9-alpha.1` | MIT |
| FLAME geometry | Official LAM-assets bundle, `model_zoo/human_parametric_models` | Separate Max Planck FLAME terms; top-level LAM Apache license does not replace them |
| VHAP tracker | Bundled in LAM | Per-file Toyota/VHAP restrictions, including commercial use provisions |
| ARKit rig template | Official LAM `sample_oac.tar` | Supplied as official export asset; no standalone commercial-rights conclusion |

License sources: [LAM source license](https://github.com/aigc3d/LAM/blob/master/LICENSE),
[LAM weight license](https://github.com/aigc3d/LAM/blob/master/LICENSE_WEIGHT),
[FLAME](https://flame.is.tue.mpg.de/), and the individual headers under
`vendor/LAM/vhap` and `vendor/LAM/lam/models/rendering/flame_model`.

The download script hashes all downloaded archives and model weights. The
publicly provided research bundle is used for this local research workflow;
distribution or commercial deployment needs the applicable dependency rights.
Do not label the entire dependency stack simply “Apache” or “MIT”.

## Runtime architecture and ownership

```text
Portrait -> local face tracking/FLAME fitting -> LAM canonical Gaussian inference
        -> verified ARKit template export -> avatar.zip stored per identity

OpenAI Realtime PCM -> Audio2Face -> lip/jaw coefficients ----+
User state/context -> empathy controller -> gaze/head/face --+-> timestamped frame
                                                            -> browser 3DGS rig
```

Generation uses an isolated Docker worker with CUDA 12.8, PyTorch 2.11 and
compiled sm_120-compatible PyTorch3D/diff-Gaussian/nvdiffrast components. The
upstream Torch 2.3/CUDA 12.1 instructions are not copied unmodified onto RTX5090.
Each job runs as a child process and relinquishes GPU allocations on exit.
The existing Ditto and A2F services remain separate and running.

The exporter verifies complete vertex topology before applying the fixed
template coordinate translation. It retains every non-position binary byte,
including morph targets and skin weights; tests assert this. Appearance comes
from newly predicted Gaussian attributes, never from the official sample.

51 ARKit targets are present in the official template. `tongueOut` is absent.
Gaze uses eye-look coefficients; head rotation uses the rig's head bone. An
avatar-level gain calibration is still required for believable expression
strength. A face-only artifact cannot acquire hand or full-body gestures just
because the template skeleton has extra bones.

## Verification and limitations

The worker records input/output/model hashes, each generation stage, timings,
dependency errors, compiler output and intermediate FLAME tracking artifacts.
`preview.png` is explicitly a segmented source preview; only the browser-rendered
ZIP is evidence of successful 3D reconstruction.

Relevant tests live under `workers/gaussian/test_export_asset.py`: full topology
correspondence, position injection, binary preservation of morph/rig data,
and rejection of nonfinite or topologically incompatible output. Actual GPU
generation status is recorded under `data/gaussian/jobs` and is distinguished
from model-file availability in `/health`.

Corrected local generation on 2026-09-23 took 30.7s from Python job start to
exported ZIP (31.9s including process/HTTP overhead), with 693ms Gaussian
inference. The main task visually verified the reconstructed woman in the
browser: recognizable identity, correct color, head/shoulder crop, approximately
64FPS. The artifact contains 20,018 vertices and 51 ARKit targets. Evidence is
the persisted `user-portrait-967df7-normfix` job, generation manifest and main
task browser test. This is not a perceptual likeness or lip-sync benchmark.

The initial structurally valid ZIP failed visual inspection. Root cause was
Diffusers 0.30.2 inherited from the Ditto base: its JointAttnProcessor2_0 did not
execute the checkpoint's learned sample/context query/key normalizations.
Pinning 0.32.2 restored correct reconstruction. Startup and every generation
now verify all four normalization layers execute; `test_attention.py` guards
against silent recurrence. Sources:
[0.30.2 processor](https://github.com/huggingface/diffusers/blob/v0.30.2/src/diffusers/models/attention_processor.py),
[0.32.2 processor](https://github.com/huggingface/diffusers/blob/v0.32.2/src/diffusers/models/attention_processor.py).

Quality can degrade for profile views, occluded faces, unusual hair and unseen
back-of-head regions. ARKit control is an actuator interface; neither the
generator nor A2F proves that empathy policy decisions are contextually correct.
Full emotion recognition/control validation remains an experiment independent
of real-time rendering success.
