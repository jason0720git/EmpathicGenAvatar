# Idle → speech entry correction (2026-09-18)

## Confirmed defect

V8 changed the exit only. In user turn `user-1789714196907`, entry still
used `canvas_translation_v7` with dy -0.0125 while exit correctly used
`source_anchor_v8`. Entry also faded a frozen idle snapshot over only 160 ms
and immediately parked the underlying idle stream at frame zero.

## Change

- TRT10 entry now uses `live_idle_blend_v9`: no full-frame translation,
  rotation, or zoom; the outgoing image is the still-playing idle canvas.
- Blend across the existing 480 ms silent lead, using the audio/media clock,
  not a fresh clock started by a possibly late JPEG callback. No PCM timing
  changes, new silence, or extra API calls.
- Only after entry ends may IdleCanvas park at frame zero for the already
  working v8 exit. `entrySettled` resets on stop/new turn. A new diagnostic
  `visual_transition` phase `completed` records the completion PTS using the
  existing API event allowlist.
- Non-TRT10 fallback also disables full-frame entry registration. Its old
  short snapshot blend remains; only TRT10 advertises the silent lead contract.

## Validation and limits

- 27 web tests passed; TypeScript/Vite build passed.
- Unit tests cover live-canvas identity, zero geometry operations, fade weights
  at 0/160/240/440 ms, and incoming-only frames at/after 480 ms.
- Playback regression covers idle remaining live while speech canvas is visible,
  then parking only after the silent lead, including actual effect/RAF cleanup.
- This is a presentation blend, not recovered 3D pose continuity. A large
  pose mismatch can still produce a short dissolve/ghosting; it no longer
  translates the portrait/background or masks the speaking mouth after lead-in.
