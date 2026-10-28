# Photo-based Gaussian avatar conversation system

Design date: 2026-09-23. This is an additional experimental renderer; the existing Ditto application and work in progress remain intact.

## Architecture and decision

Use LAM for an animatable Gaussian head reconstructed once from a source portrait. Persist the exported asset with a source hash and generation metadata. Use the official LAM WebGL renderer for local rendering. A static Gaussian point cloud is not sufficient: the asset must contain compatible expression deformation data.

OpenAI Realtime receives microphone PCM or typed user input through a server-owned WebSocket. Its output PCM feeds NVIDIA Audio2Face-3D and browser playback. A2F supplies articulation; a separate behavior controller supplies bounded expression, gaze and head trajectories. The adapter merges channels with explicit ownership. The browser audio clock is the master time for the rendered motion. Interruptions invalidate the turn, cancel remote generation and A2F, and purge browser audio/motion queues.

The initial controller is an inspectable implementation informed by SOBIA's channel ownership and behavioral architecture. It must not be labeled a trained human-interaction model or exact port of all SOBIA policies. Record the source of every command and expose manual controls for calibration.

## Isolation and interfaces

- Additional backend: `app.gaussian_main`, localhost port 8030; does not replace existing API on 8000.
- Additional UI: `/gaussian`, using `/gaussian-api/` HTTP and `/gaussian-ws/` WebSocket proxy routes.
- Source, generation outputs and logs: ignored `data/gaussian/`.
- Generation worker: independent process/container with lazy GPU loading and one generation at a time.
- Existing A2F service: host port 52000, `A2FControllerService/ProcessAudioStream`.
- No secrets in browser source, WebSocket packets or diagnostic records.

HTTP: readiness, avatar upload/generation/import/list/assets, create session, retrieve logs and feedback. A session has one live socket. Each turn has a unique ID, immutable timestamps and one audio master clock.

WebSocket commands: `input.audio` (24 kHz mono PCM16 base64), `input.commit`, `input.text`, `interrupt`, `control`, `telemetry`, `feedback`. Server events: `session.ready`, `state`, `turn.started`, `transcript.delta/final`, `audio.chunk`, `animation.frame`, `behavior`, `turn.done`, `turn.cancelled`, `diagnostics`, `error`.

Audio events carry `turn_id, seq, pts_ms, pcm_base64, sample_rate`. Animation events carry `turn_id, pts_ms, weights` (named ARKit coefficients), `head` (degrees), `gaze` (normalized), and channel-source diagnostics. No arbitrary model-authored commands execute as code.

## Observability

Persist session configuration with redacted credentials, source/model versions, inbound/outbound transcripts, Realtime event metadata, audio PCM/WAV, A2F raw and mixed coefficients, behavior plans, timing counters, cancellations, errors, playback telemetry and user feedback. Display whether services are truly connected; never silently replace A2F or 3DGS with an amplitude-driven or static mock. Logging status and local location remain visible. Log downloads must be limited to the requested session.

## Validation gates

1. Verify actual source-photo reconstruction and exported asset schema.
2. Render asset in browser; test named expression, eye and head changes against rendered output.
3. Send a known WAV through the running A2F service, confirm nonzero time-ordered coefficients.
4. Call the configured Realtime API with typed and audio input; verify actual audio and transcript output.
5. Integrate A2F and playback with aligned timestamps; test interrupt/restart and no stale motion.
6. Test upload validation, ZIP traversal/expansion limits, session boundary checks, bounded buffers, redaction and log/feedback persistence.
7. Build frontend, run relevant tests, and open the ready local UI for user feedback.

## Research basis

- LAM (SIGGRAPH 2025): https://github.com/aigc3d/LAM — single-image rigged Gaussian reconstruction, released weights and export pathway.
- LAM WebRender: https://github.com/aigc3d/LAM_WebRender — browser rendering and named expression input.
- GaussianAvatars (CVPR 2024): https://github.com/ShenhanQian/GaussianAvatars — explicit FLAME-rigged Gaussian head baseline.
- ARTalk: https://github.com/xg-chu/ARTalk — alternative audio-to-FLAME motion; not selected because the requested path is NVIDIA A2F.
- EmpaAva: https://arxiv.org/html/2608.04709v1 — perception/planning/rendering decomposition; its end-to-end latency is not a generic 3DGS limit.
- OpenAI Realtime: https://developers.openai.com/api/docs/guides/realtime-conversations — server-side PCM events, GA configuration and response lifecycle.

Code availability does not establish rights for every weight, FLAME asset, dataset or likeness. LAM's code and model weights have distinct terms. Keep license provenance with assets and use the research route accurately.
