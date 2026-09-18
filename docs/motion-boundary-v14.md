# v14: continuous aligned appearance transfer

The 720 ms v13 handoff still had an explicit `progress < 0.5` texture switch.
Slowing the geometry made the residual difference at that switch perceptible.
It was not enough to change duration; the appearance function was discontinuous.

Changes:

- Keep 720 ms entry/tail and existing native speech motion/audio.
- Warp both images into corresponding intermediate geometry, then transfer
  appearance using smoothstep across progress 0.2–0.8. This IS a short RGB blend
  of aligned samples; it is not the original unregistered whole-frame dissolve.
- Remove the hard texture switch at progress 0.5.
- Express incoming UV as `uv + (1-progress)*flow`, guaranteeing exact identity
  at the final endpoint even with an imperfect iterative inverse estimate.
- Limit correspondence updates to 0.35 tracking pixels per axis per frame and
  retain the spatial gradient bound. Native Ditto frames are not stabilized.
- GPU/readback failure uses an explicitly logged continuous, unregistered blend
  fallback (potentially softer), not another hard cut. Normal-mode telemetry is
  `aligned_continuous_warp`, strategy `continuous_geometry_v14`.

Verification:

- 39 web tests and production TypeScript/Vite build pass.
- Actual GPU fixture: identical Happy/idle source pair, progress 0.4999 versus
  0.5001, face-region byte MAE reduced from 6.28149 to 0.007861. This measures the
  mathematical midpoint discontinuity, not general human-motion realism.
- GPU output visually inspected: no abrupt switch of smile/face at that point.
- Repro harness: `artifacts/geometry-handoff-qa/continuity.html`; `old-geometry.js`
  is the preserved compiled v13 renderer and `continuous.js` is compiled v14.
- Original attached video contact sheet: `artifacts/midpoint-jump-before.jpg`.
- Deployed browser WAV test: Seoyeon, Happy 100%, turn
  `user-1789720942624`. Entry rendered 18 aligned frames (peak 19.6 ms), exit
  rendered 16 aligned frames (peak 18.7 ms); both had zero fallback frames.
  Playback logged zero JPEG decode failures and zero video PTS gaps, with the
  live exit tail completed. No Realtime or TTS API calls were used.

Limit: alignment is still approximate 2D correspondence. Occlusion, blink or
large expression differences can leave some softness. This change addresses
the known hard midpoint switch; it is not a shared 3D motion-state renderer.

## Timing follow-up: 1 second

At user request, entry/tail duration is now 1000 ms, with matching worker
lead/tail padding of 25 frames at 25 fps. The final exit sample is fully idle
at 960 ms (the last frame of the 1000 ms tail). The v14 continuous aligned
transfer is unchanged. Updated web regression suite: 39 tests pass; production
build passes. This timing change does not slow the spoken audio or native motion.
