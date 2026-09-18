# v13: geometry-only handoff instead of an opacity dissolve

## Timing follow-up (2026-09-18)

At the user's request, the same geometry handoff now runs more slowly:
720 ms entry instead of 480 ms; 720 ms silent tail instead of 480 ms (the
last tail frame is fully idle at 680 ms instead of 440 ms). Worker lead/tail
are both 18 frames at 25 fps. This adds 240 ms before speech and 240 ms after
speech; it does not time-stretch the voice or extend warping into spoken frames.
Web timing constants, scheduled-tail calculation and timing regression tests
were updated together. Geometry matching, texture selection and native head
motion are unchanged. Web 38 tests and worker 23 fixture-free tests pass.

## Why v12 looked blurred

v12 mixed two independently moving portraits at their original pixel locations.
Misaligned eyes, nose, lips and hair remained simultaneously visible. The
attached recording shows the resulting double face during the closing handoff.
Shortening the dissolve alone would trade this for a faster positional jump.

## Implemented path (TRT10)

1. During the existing silent lead/tail, sample both live frames at 128x160.
2. Estimate A-to-B patch correspondences on a 17x21 grid. Use a global search
   initializer, local/subpixel refinement, texture/error checks, neighbor
   regularization and temporal smoothing. This is image correspondence, NOT
   anatomical landmark detection and NOT learned dense optical flow.
3. Bound the displacement gradient to prevent folded/inverted image cells;
   the outer grid vertices remain fixed rather than rotating the whole screen.
4. Warp toward the intermediate geometry on the GPU. Before the midpoint use
   only the outgoing texture; after it use only the incoming texture at the
   corresponding geometry. There is **no two-image RGB alpha blend**.
5. Sample the original-resolution texture with Catmull-Rom interpolation (nine
   bilinear fetches). The tracking thumbnail is never enlarged as output.
6. At either endpoint draw the exact source image. After the silent lead, all
   native speech frames bypass this processing. Ditto head motion, speech-lip
   protection, audio packets and frame PTS are unchanged.

The scratch GPU renderer is shared across turns. GPU shader and CPU matching
warm-up run while idle to avoid first-use compilation at the handoff. Idle stays
live throughout; no neutral/source-photo waypoint or idle-frame-zero parking.

Late-end fallback also uses geometry handoff. Unavailable GPU/readback or very
poor correspondence uses a logged unwarped source switch, **not** a hidden
opacity dissolve. That degraded path can have a visible positional jump.

## Diagnostic telemetry

Uses the existing accepted `visual_transition` event, strategy
`geometry_handoff_v13`. `phase=geometry_metrics` records mode, frame count,
peak processing milliseconds, correspondence reliability/residual/displacement,
fallback frame count and last error. `rgb_crossfade=false` identifies the new
TRT10 path. First prototype used an unrecognized event name (HTTP 422); this was
corrected before final validation to avoid silently missing diagnostics.

## Verification

- 38 web tests passed; production TypeScript/Vite build passed.
- Tests cover translation direction, fixed borders, bounded gradients,
  identical/flat input, exact endpoints, no shader RGB mixture, explicit
  failure behavior, live idle retention and presentation-before-teardown.
- Actual cached Happy tail vs idle fixture: old dissolve visibly doubles the
  eyes/nose/mouth; geometry output has one contour in inspected intermediate
  frames. `artifacts/geometry-handoff-qa/` is a standalone reproduction harness.
- In that fixture, face-region Laplacian energy at midpoint was 196 with old
  dissolve and about 254 with cubic geometry sampling. This is a diagnostic
  on one fixture, NOT a general perceptual-quality score or percentage claim.
- Fixed WAV browser tests verify GPU path, idle return, no dropped JPEG/PTS
  gaps, and zero Realtime/TTS/emotion-tool calls. See turn logs for timing.
- Final Happy turn `user-1789720067731`: entry 23.5 ms peak, exit 14.7 ms peak;
  both single_texture_warp, fallback_frames=0, JPEG failures=0, PTS gaps=0,
  source_anchor=false and live_tail_completed=true. An earlier cold prototype
  had a 73.5 ms spike; CPU/GPU prewarming and nine-fetch cubic sampling were
  added before these final measurements. These are observed timings, not an
  all-devices performance guarantee.

## Limits and next architectural step

This removes double exposure; it does not produce a physically continuous 3D
performance. Texture ownership switches at the midpoint. Unmatched teeth,
blink states, large rotations/occlusions or lighting differences can still show
an appearance change. Image warping can also cause local deformation. Do not
claim these tests prove indistinguishable human motion.

For stricter continuity the renderer must carry pose/expression/velocity state
across idle and speech, interpolate those states, and decode ONE face for each
output frame. That requires a shared motion timeline rather than independent
cached idle and generated talk clips. It is not implemented by this browser fix.

## Research considered

- [Occlusion Reasoning for Temporal Interpolation using Optical Flow](https://www.microsoft.com/en-us/research/publication/occlusion-reasoning-for-temporal-interpolation-using-optical-flow/)
- [Context-aware Synthesis for Video Frame Interpolation](https://arxiv.org/abs/1803.10967)
- [OCAI, CVPR 2024](https://openaccess.thecvf.com/content/CVPR2024/papers/Jeong_OCAI_Improving_Optical_Flow_Estimation_by_Occlusion_and_Consistency_Aware_CVPR_2024_paper.pdf)

These motivate correspondence/warping and explicit occlusion limitations. We
do not ship those papers' models or claim to reproduce their results.
