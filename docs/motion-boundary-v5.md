# Idle and speech boundary continuity — 2026-09-17

## Diagnosis and scope

Reviewed the supplied 18:07 recording and the actual generated idle assets.
Keeping the idle URL stable prevents portrait flashes but does not make its
last pose match its first, or make independently generated speech match idle.
Idle r4's last-to-first face-region mean absolute pixel difference was
7.56 / 9.54 / 8.15 for variants 0/1/2, versus normal adjacent changes around
0.7–2.1 (0–255 BGR units). This is direct evidence of an idle seam.

A dissolve alone changes opacity, not head position; mismatched features can
briefly appear doubled. The chosen approach combines geometric continuity
inside idle generation with bounded image registration at speech boundaries.
Background reference on coordinate warping and image interpolation:
https://research.cs.wisc.edu/graphics/Courses/559-f2007/wiki/pub/Lectures/09-LiZhang-Warping.pdf

## Implementation

- Idle cache revision 5: after motion stitching, interpolate actual implicit
  driving coordinates toward source coordinates at both visible endpoints.
  Quintic weight ramps over 20 frames (0.8 s at 25 fps), accounting separately
  for the 13 preroll frames. First and last visible coordinates are identical;
  the interpolation weight has zero first/second derivative at its endpoints.
  This closes model-generated motion as well as scripted tiny head motion.
- Realtime browser transitions: compare 96×120 luminance samples of the upper
  face, excluding the mouth. Estimate small 2D translations; require improved
  match and reject poor matches. Bound correction to 3.5 sample pixels.
- Align the incoming image initially, relax that correction over 280 ms with
  quintic easing, and mix the outgoing snapshot only during the first 100 ms.
  This is not landmark detection, optical flow, rotation, or 3D pose transfer.
- At speech end, use the current live idle image throughout the handoff, then
  hide the canvas. Preserve existing PCM clock/video PTS scheduling and lip
  protection. Remove the separate listening CSS transform on idle, since it
  was not part of the canvas's coordinate space.
- Record `visual_transition` with direction, normalized dx/dy, and whether
  alignment was accepted in existing local turn telemetry. No extra LLM calls.

## Verification

- Web: 16 tests passed; production build passed.
- API: 37 tests passed.
- Worker: all 19 test functions ran successfully inside the GPU image using
  runpy (the image does not contain pytest).
- GPU proxy smoke: 110 audio packets, 134 video frames, one end marker.
- Regenerated all 3 idle variants. Last-to-first face-region pixel MAE is
  **0.0 for each**; adjacent frames at the seam are ~0.32–0.34, not abrupt.
- Actual browser via Computer Use: Happy 100%, one short sentence,
  `user-1789636679978`. Entry alignment accepted (dx .0078125, dy .0125), exit
  accepted (dx -.0078125, dy -.00625); 0 JPEG decode failures, 0 video PTS gaps,
  clean socket close and return to ready. AudioContext reported running.
- Reproduction: `python -m app.audit_idle_seam` inside the TRT10 worker.
  Local measurements and before/after seam clips: `artifacts/idle-seam-v5/`.

## Remaining limits

Zero endpoint pixel difference is measured for these 3 idle renders, not a
guarantee of perfect perceived motion throughout arbitrary speech. A short
100 ms blend can still produce slight ghosting. Large rotations, changes of
scale, or strong expressions can exceed the 2D translation model; rejected
matches fall back to the short blend without position correction. Fully
continuous 3D head dynamics would require sharing pose and velocity state
between idle and speech generation. Current changes target the realtime
canvas path (including the user's TRT10 mode), not the batch video player.

Deployment: API/web/TRT10 rebuilt and restarted. Start a fresh session after
refreshing the page to load the new JS and regenerated idle cache.
