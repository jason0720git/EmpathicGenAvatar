# v11: restore native motion; constrain correction to entry

## Rollback

v10 removed native head channels via `use_d_keys`. This reduced measured motion
but defeated Ditto's natural performance. Both speech and idle now use the SDK
defaults again (expression, pitch, yaw, roll, translation). Idle assets return to
version 6, including the original procedural movement and 40-frame boundary
envelope. The silent tail returns to 12 frames. No vendor code was changed.

## Entry handoff

The browser estimates a small upper-face translation between the live idle
canvas and first speech frame. A face-local triangle mesh applies the accepted
translation only during the existing 480 ms silent lead, decaying with quintic
easing. Every outer image edge remains fixed. The live idle canvas is blended
over this incoming image until the handoff completes, then parked.

Corrections exceeding 2% on either axis or failing confidence checks are rejected.
At 480 ms and thereafter the incoming frame is drawn without registration or
crossfade. Native speech motion is not stabilized, damped, or replaced. Existing
source-anchor exit and lip/audio preservation remain unchanged.

This is bounded 2D registration, not continuous 3D pose/velocity synthesis.
Large yaw/roll mismatches can still produce a visible blend; transient softness
is possible. It must not be described as complete perceptual continuity.

## Verification (2026-09-18)

- Web: 31 tests passed; TypeScript/Vite build passed.
- Worker: 22 fixture-free tests passed, including native-key rollback checks.
- Actual Seoyeon Happy WAV rendering: 141 frames, entry/exit/idle-loop anchor MAE 0.
- Optical-flow vertical range: idle 30.95 px; speech 46.13 px. Prior v10 measured
  14.13/20.10 px; prior v9 measured 30.95/48.84 px. These are feature-motion
  measurements, not head angles, and stochastic speech renders need not match.
- PCM SHA256 unchanged: c7e1bfd30aa9d7886509d48627475a2d323855fbf2ed6957b70de3934cf19e4e.
- Actual Canvas QA fixture: accepted dy=-0.0145833, matching error improvement
  63.2%; post-lead pixels exactly equal native input (maximum difference 0).
- Browser WAV turn `user-1789716321523`: entry registration accepted, 480 ms,
  no full-frame transform, rendering peak 1.3 ms; returned to ready/idle.
- No Realtime, TTS, or emotion API calls used in tests.

Diagnostics retain strategy `face_local_handoff_v11`, accepted alignment,
dx/dy, completion PTS, and render peak. WAV default, Seoyeon default, emotion
presets, feedback controls and native 16-second idle duration are preserved.

Reproduction artifacts: `artifacts/motion-v11-restored.json` and
`artifacts/transition-qa/index.html` (compiled actual renderer plus test images).
