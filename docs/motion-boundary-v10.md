# Controlled pose ownership and shorter boundary settling

## Why v9 still looked wrong

The screenshot endpoints matched, but that alone did not guarantee good motion.
Ditto's default `use_d_keys` drives expression, pitch, yaw, roll and translation
from each independent Audio2Motion run. Idle and speech therefore had different
rigid-motion trajectories. The 480ms RGB blend superimposed those trajectories.
At exit, a 12-frame silent tail was followed by idle's 40-frame coordinate ramp
AND a slow sin² motion envelope. This produced the neutral/paused impression.

## v10

- Speech drives native **expression only** (`use_d_keys=('exp',)`). Lip-sync
  coefficients and speech-safe protection remain; incidental model rotation,
  scale and translation do not drive the portrait.
- Idle drives **no native Audio2Motion coefficients** (`use_d_keys=()`). It
  retains the source expression, SDK blink sequence and explicit head controls.
- Explicit preset yaw/pitch/roll and nod still run. Thus head movement has one
  intentional owner rather than being added to unrelated native pose noise.
- Idle uses small periodic yaw/pitch/roll, with no additional slow sin² start
  envelope. Source-coordinate seam settling is 6 frames (240ms), not 40 (1.6s).
- Speech silent tail is 8 frames (320ms), not 12 (480ms). PCM unchanged.
- Entry image blending is only 160ms; no frame transform or extra audio delay.
  Exit remains direct to the identical anchor frame, with no extra hold.
- Idle cache revision is 10: 400 frames, 16 seconds, four irregular blinks.
  Seoyeon's three variants were regenerated. Other avatars regenerate when
  prepared. No existing avatar source image or old cache was deleted.

## Evidence

Same Seoyeon / Happy 100% / speech_safe / fixed WAV, before and after:

| Optical-flow diagnostic | v9 | v10 |
|---|---:|---:|
| Idle vertical feature-displacement range | 30.95px | 14.13px |
| Speech vertical feature-displacement range | 48.84px | 20.10px |
| First/last speech vs idle anchor pixel MAE | 0 / 0 | 0 / 0 |
| Audio SHA256 | c7e1bfd3… | c7e1bfd3… |

These are full-resolution image-feature measurements, not head-angle estimates
or perceptual quality scores. Eye/expression changes also contribute. Evidence:
`artifacts/motion-v9-before.json`, `artifacts/motion-v10-after.json`, and
`artifacts/motion-v10-comparison.jpg` (old row / new row).

- 27 web tests and TypeScript/Vite production build passed.
- 22 fixture-free worker tests passed, including native-key ownership, preserved
  speech articulation, loop endpoints, shorter skirt, tail and blink schedule.
- GPU Fear/Happy/Happy: 137 frames each, identical original PCM hashes, entry and
  exit anchor MAE 0; last adjacent frame MAE about 0.22–0.32 (0–255 scale).
- Browser WAV Happy verified `controlled_pose_v10`, entry completion, zero exit
  transforms and normal return to ready; no Realtime API calls.
- Doyun all eight emotions also passed WAV streaming: 137 video frames and
  148800 identical PCM bytes each (`artifacts/wav-test-v10-results.json`).

## Tradeoff / scope

This intentionally reduces spontaneous model-generated head movement. Preset
head gestures and natural blink remain. It does not claim one continuous 3D
animation state across arbitrary interruptions; normal completed TRT10 turns
are the tested path. Perceived naturalness still needs user visual feedback.
