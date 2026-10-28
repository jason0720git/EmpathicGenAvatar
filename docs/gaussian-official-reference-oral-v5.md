# Official reference and oral correction — 2026-09-29

## What differs

The active LAM configuration (`vendor/LAM/configs/inference/lam-20k-8gpu.yaml`)
sets `add_teeth`, `teeth_bs_flag`, and `oral_mesh_flag` to false. The existence
of a teeth implementation in FLAME does not mean that our active avatar uses it.
The base exported topology contains a face and two eyeballs, not a separate
teeth or tongue mesh. Closed-mouth source photos do not observe oral anatomy.

GaussianAvatars official checkpoint 306 contains 89,021 splats with mesh-face
bindings and a subject-specific FLAME motion sequence. Its implementation uses
`FlameHead(..., add_teeth=True)`. This is a different reconstruction and driver
from single-photo LAM plus ARKit/A2F. This comparison does not establish an
ethnicity-specific failure. Neither implementation's existence proves that a
separate anatomically reconstructed tongue is present in our generated assets.

Sources: https://github.com/ShenhanQian/GaussianAvatars and its
`scene/flame_gaussian_model.py`, `local_viewer.py`, `doc/download.md`.

## Reference library entry

ID `306000000000000000000001` is pinned before all ordinary avatars, including
future imports. `workers/gaussian/render_official_reference.py` renders the
actual bundled checkpoint and FLAME parameters, preserving SH3 appearance.
The library plays a 250-frame, 25fps rendered reference clip. It is explicitly
NOT an A2F-controllable import. Voice sessions are rejected for this entry,
and motion controls are disabled. The earlier male screenshot reconstruction
remains a separately labelled LAM avatar. Source licensing remains applicable.

## Generated avatars

Emma `2a80fe76d5f44beba2a3c0ac` and Seoyeon `88546d4a362b4a97979c5360`
use the v5 correction. Experimental supplemental teeth, cavity and tongue
splats are disabled because they introduced floating crowns and hard oval
boundaries. Native deformation and opacity are preserved. A soft lower-mouth
appearance correction follows the projected animated lip aperture and
preserves luminance while separating soft-tissue color from dental color.
The upper dental appearance is retained. Closed mouths disable the correction.

This is an appearance correction, NOT recovered tongue anatomy, nor an
independently articulated tongue. The diagnostic tongue flag is therefore
false. Remaining tooth/floor shape can still be blurred because it is inferred
by the source model. Wide jaw poses and oblique views remain lower quality than
the subject-trained reference. Do not report complete anatomical restoration.
The rig-check checkbox compares the correction against native LAM appearance.
Existing blink visibility correction is retained.

Backups: each affected avatar has `asset.pre-hybrid-v5.zip` and
`record.pre-hybrid-v5.json`; earlier backups remain intact.

## Validation

- Browser visual comparisons of both identities, jaw 0.3/0.6, full blink and
  20-degree head turn; experimental opaque cavity was rejected during QA.
- Actual A2F WAV runs: Emma session `b1d07f02c4f14a05bd825d44` and Seoyeon
  `d7a94d57b15c4a67af30c044`, each 4.7 seconds, 140 motion frames.
- Official clip loaded in browser; library first position and disabled
  controls verified. API regression test verifies pinning, clip routing and
  rejection of voice sessions for the reference.
- Frontend 61 tests passed; backend 44 passed, one optional test skipped.
- Production build passed. Visual quality is not established by tests alone.
