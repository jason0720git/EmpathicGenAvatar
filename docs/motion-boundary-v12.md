# Direct live handoff (v12)

## Cause

v8-v11 deliberately pulled speech driving coordinates back to source coordinates
over the silent tail. The browser also parked idle at frame zero. Matching those
endpoints removed a discontinuity but introduced a perceptible neutral-photo
waypoint. This was our transition policy, not a fundamental Ditto limitation.

## Changes

- Speech no longer attaches the source-anchor timeline to motion stitching.
- Speech emotion residuals hold through the native final frame instead of
  releasing before the handoff. Lip protection and SDK native head channels stay.
- Idle keeps decoding while hidden, without parking/restarting on speech states.
- Entry blends live idle into native speech during its existing silent lead;
  the bounded face-local alignment is retained, without global frame movement.
- Exit blends each moving native tail frame directly with the current moving
  idle canvas across the 12-frame silent tail. The final frame is fully idle.
- End handling waits for the final decoded frame to actually be displayed, not
  just its media-clock deadline (regression test exercises timer ordering).
- Late end markers start blending at zero opacity. If the tail cannot finish,
  the fallback blends the last displayed composite to live idle; it never loads
  or generates a source-photo waypoint. This degraded path may hold a residual
  of the last speech image briefly and is logged explicitly.

Idle's own cached-loop seam is unchanged. Native motion is not locked or damped.
Two independently generated motions are still blended in RGB; large pose
differences can cause transient double edges. This does not claim continuous
3D pose/velocity synthesis. The eliminated mechanism is the forced neutral
waypoint, not every possible perceptual transition artifact.

## Verification

- 32 web tests, including live idle retention, moving tail completion and
  presentation-before-teardown; 23 fixture-free worker tests passed.
- TypeScript and production Vite build passed; web and TRT10 worker deployed.
- Actual Happy 100% Seoyeon WAV: 141 frames, identical PCM SHA256 to v11.
- Raw first/last speech versus source-anchor pixel MAE now 5.992/6.241 instead
  of exactly zero. This confirms the generated endpoints are no longer forced
  to the portrait; it is not a perceptual smoothness score.
- Native speech feature vertical range 38.43 px; idle 30.95 px. Motion is present;
  random renders and expression changes make cross-run comparisons approximate.
- Browser turn user-1789718580257: live tail started at PTS 5160 ms, completed
  with source_anchor=false, fallback=false; JPEG failures=0, PTS gaps=0.
- All generation tests used the local fixed WAV, with no Realtime/TTS/tool calls.

Evidence: `artifacts/state-v12-before.jpg`, `artifacts/motion-v12-direct.json`.
Telemetry strategy is `direct_live_handoff_v12` in both directions.
