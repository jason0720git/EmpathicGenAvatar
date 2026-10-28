# Shared resting mouth contour

The source portrait's lower-lip contour remains the baseline for both idle and
speech. Emotion-only changes do not relax this contour consistently, and the
speech-protection pass deliberately restores audio-driven lip coordinates.

`REST_MOUTH_GAIN = 2.0` in `workers/avatar/app/main.py` applies a small bounded
LivePortrait lip-variation-three-style bias (point 19 y/z, point 17 y) after
speech protection and boundary interpolation. It changes only the driving
implicit coordinates; source warp coordinates, head motion, emotion selection,
and audio timing are unchanged. Ditto adds expression after rotation and before
scale, so the offset is multiplied by source scale, not rotated.

This is a conservative contour adjustment, not a held-open jaw. The same bias
exists at idle loop endpoints and talk boundaries. Idle asset version 11 forces
regeneration instead of mixing old unadjusted idle frames with new speech.
Worker `ditto.affect_applied` logs include the profile and gain. There is no
additional AI request or per-frame neural-network inference.

Local verification:

- `.venv-perception/Scripts/python.exe -m pytest -o pythonpath=workers/avatar workers/avatar/tests -q`
- GPU worker: `python -m app.calibrate_affect --rest-mouth` compares gains 0, 1, 2.
- GPU worker: `python -m app.verify_rest_mouth` rebuilds three Seoyeon idle loops
  and renders `/data/test-audio/reference.wav` through the live media path.

The numerical tests preserve temporal audio-coordinate differences; they do not
prove phoneme-level perceptual lip-sync. Inspect the generated speech and idle
contact sheets and listen to the normal WAV-mode playback. MediaPipe lip-gap and
mouth-roll scores in the calibration output are visual proxies, not anatomical
measurements. Avoid increasing gain beyond 2 without renewed closure testing.
The cache revision is 11; revisions 7–10 were already used by earlier local
experiments and must not be reused.
