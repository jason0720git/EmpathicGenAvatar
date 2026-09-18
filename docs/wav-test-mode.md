# Fixed-WAV expression evaluation — 2026-09-18

Homepage defaults: WAV test, Doyun, Ditto Realtime TensorRT 10, neutral,
100% intensity, speech-safe compositor. The only primary mode choices are
WAV test and Realtime conversation. Avatar selection stays available;
old promotional dashboard/renderer picker are not part of this homepage.
Advanced compositor comparisons and existing feedback/log controls are folded.

## Fixed audio

User-supplied source (unchanged):
`C:/Users/USER/Downloads/marin_gpt-4o-mini-tts_1x_2026-09-18T04_03_21-696Z.wav`.
Normalized with FFmpeg to 16 kHz, mono, signed 16-bit PCM for the existing
Ditto input contract: `apps/api/app/assets/test-reference.wav`.
Length is 4.65 seconds / 74,400 samples / 148,800 PCM bytes.
The API seeds a copy at `/data/test-audio/reference.wav` when absent.
`GET /api/test-audio` serves this local copy for preview; no TTS/STT is used.

## No paid conversation calls in WAV mode

Session `mode` is persisted in SQLite (existing sessions migrate to realtime).
Creating a WAV session prepares the renderer but does not start the conversation
provider. REST turns require a manual affect selection and route the fixed WAV
straight to the same render/playout path used by live conversation. Missing WAV
fails explicitly, never falls back to speech generation. The live conversation
WebSocket is rejected for WAV sessions; captions return a completed test label.
The browser hides Auto/microphone/chat controls and does not poll live captions.
Choosing Realtime explicitly remounts a separate realtime session; its behavior
and per-avatar voices (including Doyun echo) remain unchanged.

`wav_test.input` diagnostic events correlate input SHA-256, session and turn ID;
normal expression parameters, media timing, transition and feedback logs remain.
The SHA proves the input is unchanged, not that the stochastic motion model
generates identical video on repeated runs.

## Verification

- API 40 tests; web 22 tests; production build passes.
- The WAV integration test makes provider start/respond raise on any call:
  all 8 emotions still render, auto/missing-file requests fail safely, and
  WebSocket conversation is blocked. UI test verifies WAV/TRT10 defaults,
  no caption polling, and explicit transition into Realtime mode (mocked only).
- Actual GPU through API/web proxy: 8 emotions × 141 video frames each, normal
  end marker. Every output PCM hash is identical:
  `c7e1bfd30aa9d7886509d48627475a2d323855fbf2ed6957b70de3934cf19e4e`.
  Results: `artifacts/wav-test-results.json`.
- Computer Use browser test: Happy 100%, turn `user-1789704860499`; normal
  audio/video playback completion, zero JPEG failures or PTS gaps, both v6
  visual transitions applied. No OpenAI Realtime session/metrics lines appeared
  in API logs during the WAV checks. No real Realtime requests were needed.
- Reproduce the no-LLM GPU audit with `workers/avatar/app/check_wav_test.py`
  inside the GPU container against the local web/API services.

To compare: choose avatar → emotion → intensity → Generate/play. The same WAV
is rendered again with that selection. Use the folded feedback controls to
associate observations with a turn. Existing 16-second idle and handoffs stay.
