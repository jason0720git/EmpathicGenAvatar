# Full-frame rotation fix (2026-09-18)

The reported second Happy playback (`user-1789705154728`) ended with a
`canvas_similarity_v6` speech-to-idle correction of -1 degree, scale 1.
The face-only luminance match was applied to the entire canvas, rotating the
portrait background as though the camera had rolled. This was a frontend
transition artifact, not an emotion preset or TensorRT generation change.

## Change

- Remove rotation/scale search from frame registration.
- Remove rotation/scale application from the compositor, including legacy values.
- Keep bounded translation, 480 ms quintic easing, and the 160 ms short blend.
- Log `canvas_translation_v7`, with angle 0 and scale 1 in both directions.
- Keep 16-second idle assets, emotion presets, and audio/lip-sync unchanged.

This does not claim to solve anatomical pose continuity with 2D registration.
Future head-roll matching must happen in motion generation or an independently
validated face-local compositor, never by rotating the full background.

## Verification

- Web suite: 23 tests passed; TypeScript and production build passed.
- Synthetic rotated/scaled face input never yields a camera rotation/zoom.
- Legacy nonzero rotation/zoom is ignored at start, mid-transition and endpoint,
  in both transition directions.
- Browser Happy WAV 100% / speech_safe, Seoyeon: repeated playback without
  Realtime API calls. See local turn telemetry for exact applied transforms.
