# Source-anchored speech → idle (2026-09-18)

## Root cause

The recorded Fear turn `user-1789705755576` had no decode failures or PTS
gaps. Its v7 exit moved the full frame vertically by -0.00625 of its height
over 480 ms. More importantly, the independent idle stream continued to an
arbitrary motion phase while speech ended using its own driving pose.
Removing rotation in v7 did not fix these pose/phase and translation defects.

## Fix

- Default homepage avatar is Seoyeon, including when Doyun is first in API order.
- Speech motion stitching now uses the live PCM timeline to interpolate final
  implicit driving coordinates to source coordinates, only in the existing
  12-frame silent lead/tail. All speech frames have boundary weight 1.
- A quintic envelope has zero endpoint velocity. The streaming path consults
  actual PCM completion, not its provisional 750-frame allocation.
- While TRT10 speech is visible, IdleCanvas parks on frame zero, cancelling the
  stream instead of accumulating a backlog. On return it restarts from zero at
  ordinary speed. No idle motion phase keeps advancing behind speech.
- Source-anchored exit uses no translation, rotation, scale, or extra 480 ms
  frozen transition. If idle was not prepared, the fallback never translates.
- Existing 16-second idle loop and speaking expression presets are unchanged.
- Worker logs identify `source_anchor_v8`; frontend logs include `anchored`,
  `idle_parked`, duration and actual zero exit transforms.

## Validation

- Worker: 21 fixture-free tests, including streaming-duration tail weight,
  exact final implicit-coordinate equality, and speech-frame preservation.
- Web: 25 tests passed: default selection, parking/unparking, packet burst handling, source-only
  fallback and playback regressions; production TypeScript/Vite build.
- GPU WAV audit: Fear, Happy, Happy, 141 frames each. First and last speech
  frame vs idle frame zero: **MAE 0.0** for all three. Last adjacent frame MAE
  0.2123–0.2232 on the 0–255 scale. PCM hashes identical to the reference WAV.
- Reproduce with `python -m app.check_boundary_anchor` inside the GPU worker.
  Local evidence: `artifacts/boundary-v8-results.json`.

This fixes the normal completed TRT10 speech-to-idle boundary; it does not
claim identical endpoints for interrupted speech or arbitrary other renderers.
