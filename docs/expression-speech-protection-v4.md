# Expression / speech debugging v4

Happy's default and SDK concurrency handling are superseded by
[v5 notes](expression-v5-smile-and-concurrency.md). The feedback workflow below remains valid.

## What changed

`speech_safe` is the default in both the API and UI. Audio motion uses the neutral
condition, while expression residuals remain on non-lip points. Lip points
6, 12, 14, 17, 19, 20 are restored to a no-residual baseline **after stitching**,
so the stitching network cannot reintroduce direct expression offsets there.
The baseline and expression pass start from the same stitch state; state advances
only once. This adds a small stitch pass, not another diffusion/decoder pass.

This is conservative keypoint protection, not learned speech/emotion disentanglement.
The renderer is spatially coupled, so it does not guarantee identical lip pixels.
Happy loses much of its broad smile. Do not label this as a complete quality fix.

## Manual evaluation

1. Reload http://localhost:4173 and start a TensorRT 10 conversation.
2. Select Happy (or another emotion), intensity, and a compositor:
   - **발음 보호**: neutral audio motion + non-lip residual + final lip protection.
   - **표정 없음**: neutral audio motion, no expression residual.
   - **감정 조건만**: native emotion condition, no custom expression residual.
   - **기존 증폭**: previous v3 native-condition/residual combination.
3. Send a short test phrase. Settings affect the next answer, not the current one.
   Manual emotion selection still skips the affect tool; compositor selection adds
   no LLM request. Auto retains the existing affect tool.
4. Open **표정·립싱크 피드백 / 진단 로그**, select the actual response, issue,
   severity, optional seconds from response start, and a note. Save feedback.
5. Download that response's diagnostic JSON after playback finishes.

The UI remembers up to 50 responses during the current live view. The saved server
records remain independent of this list. Audio/video is not automatically recorded.
Debug logs can contain conversation text; treat exported JSON as private.

## Correlated evidence

Debug endpoints require `EMPATHIC_DEBUG_LOG` enabled:

- POST `/api/debug/expression-feedback`: bounded issue/severity/time/note plus
  session_id and turn_id, persisted under `/data/telemetry/expression-feedback.jsonl`.
- GET `/api/debug/expression-turn/{turn_id}`: matching decision, worker application,
  browser playback and feedback entries, last 10,000 lines per log file only.

Worker `ditto.speech_protection` records policy, mode, protected points, frame count
and maximum removed lip displacement. Browser events record requested mode,
AudioContext state, video scheduling lateness, audio scheduling delay and WebSocket
termination. Scheduling telemetry is not a phoneme/viseme alignment score and is
not a measurement of physical speaker/display latency.

## Reproducible synthetic A/B

`python3 -m app.benchmark_affect --speech-ab` in the TRT10 worker generates eight
Happy/Angry × compositor runs with one synthetic audio input, intensity 1, and zero
head pose/nod. Outputs are under `/data/benchmarks/speech-ab-v4`. Native audio-motion
sampling is not seeded, so outputs are not pixel-identical counterfactuals.
`*-av.mp4` muxes audio packets at their recorded PTS. Contact sheets separately
show speech and trailing silence. Ordinary live conversations are not a strict
A/B because every response has new audio.

`python3 -m app.check_media_proxy` tests the web proxy → TRT10 WebSocket media path
without an LLM request. Existing v3 documentation describes the legacy preset,
not the new default compositor.

## Verification on 2026-09-17

- API: 31 tests; worker controls: 14 tests; web: 10 tests.
- Eight GPU synthetic renders: each 134 video frames, 110 audio packets, end marker.
- Proxy media smoke test: 134 video frames, 110 audio packets, end marker.
- Visual sheet: protected Happy mouth closer to off baseline, but smile weaker.
- No claim of perfect perceived Korean lip sync or guaranteed absence of blur.

Next quality work should measure lip closure/aperture and perceived sync over
paired Korean speech, then recover smile only within validated articulation limits.
Large expressive speech may require a model trained to separate expression and
articulation rather than escalating fixed residual gains.
