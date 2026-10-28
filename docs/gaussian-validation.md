# Local integration validation — 2026-09-23

Environment: Windows, RTX 5090, local LAM generation container, NVIDIA
Audio2Face-3D service, configured OpenAI Realtime API, Codex in-app Chromium.
These are single-machine measurements, not a benchmark or perceptual quality study.

## Automated checks

- API, Realtime lifecycle, A2F, behavior controller: **36 passed**, including
  a real request to the running NVIDIA service.
- Browser audio-clock/motion timeline, completion, cancellation and PCM: **9 passed**.
- Worker attention math, rig export and service errors: **7 passed** in the final container.
- TypeScript, Gaussian-specific ESLint and production frontend build passed.
  The optional LAM SDK is a separate dynamically loaded bundle; Vite reports its large size.

Coverage includes input and ZIP validation, traversal and malformed assets, bounded
input, key redaction, logging, repeated cancellation, A2F failure with a full queue,
late ASR event correlation, preservation of recognized user utterances, and delayed
commit of assistant history until actual browser playback completion.

## Actual runtime paths

1. A portrait from the existing project's AI avatar was processed by LAM on this
   GPU. The resulting artifact has **20,018 Gaussians and 51 ARKit targets**.
   The original photo and official example remain distinct artifacts.
2. The generated woman was visually inspected in the browser: recognizable face,
   source appearance, actual expression changes, eye movement and head rotation.
   Rendering was generally **50–70 FPS** during the observed tests.
   After the final container rebuild, the normal browser upload workflow was
   repeated without manual artifact changes. Avatar `caab84036efd4e2f92f4fe68`
   completed in **59.5 seconds** including the restarted worker's first fitting
   run, then rendered correctly at 59–67 FPS. Earlier warm runs took about
   32 seconds; first-run and warm timings must not be conflated.
3. Actual Realtime audio was passed to actual A2F and rendered on the generated
   avatar. Session `2b17022615384b39b0c1b450` completed two turns:

   | Turn | First audio | First motion | Audio length | Motion frames |
   |---|---:|---:|---:|---:|
   | Initial greeting | 2,797 ms | 2,860 ms | 4.2 s | 127 |
   | Subsequent reply | 1,516 ms | 1,579 ms | 7.6 s | 229 |

   Both sent `playback.complete` after audio drained. The browser reported no
   underrun or first-motion wait timeout in these turns. Mouth opening was also
   observed visually while the A2F frame read `jawOpen ≈ 0.24`.
4. A known 24kHz Korean WAV was sent through the actual microphone-input protocol
   after the ASR correlation fix. Session `2e3c135d6a834c398a077fc8` produced
   recognized Korean input, a spoken Korean reply, 32 audio chunks and 379 motion
   frames over 12.6 seconds. Maximum jaw coefficient was 0.443. The archived log
   was retrieved successfully (about 1.1 MB).
5. Browser cancellation was exercised with audio still pending. Audio/motion
   queues cleared and the UI returned to ready; event evidence is session
   `9877ad141ba840cea2bc69e3`, turn `ab58c2949760492c93b20c44`.
6. Feedback was saved through the actual browser form, explicitly labeled as an
   automated UI test rather than a human quality rating. Feedback and log archive
   endpoints were both verified.

## Compatibility problems found and corrected

- RTX 5090 required a CUDA/PyTorch-compatible generation environment instead of
  copying upstream's older setup unchanged.
- Diffusers 0.30.2 ignored learned query/key normalization in LAM attention and
  produced scrambled faces despite completing inference. The worker now pins
  0.32.2 and exercises all four normalization modules in a startup regression guard.
- The official browser loader requires an explicit directory entry in the ZIP.
  The exporter now emits it and the regression test checks it.
- The SDK replaces its avatar scene reference with a skin mesh. Head control now
  finds the actual bone in the skin skeleton. Camera framing uses neutral vertices,
  avoiding the oversized envelope of every morph target.

## Limits of this verification

The actual physical microphone and the user's audible speaker experience still
need their first live try; a known WAV validated the input protocol and recognition,
and browser playback validated the output clock and motion. Browser microphone
capture/resampling code has automated tests. Camera/perception is optional and
was left off during these checks.

No claim is made that expression appropriateness, emotional perception, subjective
lip-sync quality or likeness has been scientifically validated. The controller
is an explicit rule-based prototype, not the research team's trained empathy model.
LAM weights and dependencies retain their separate research/noncommercial terms.

Evidence is stored locally under `data/gaussian/avatars`, `jobs`, `sessions`, and
`smoke-*.json`. It is intentionally excluded from Git along with keys and audio.
