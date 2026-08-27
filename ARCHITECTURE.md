# Architecture and renderer decision

## Recommended open-source production route

The implementation separates the control plane from the GPU media plane so models can change without rewriting the product:

```text
Browser mic (WebRTC / Opus)
  -> LiveKit room -> VAD / turn detector -> streaming STT -> LLM -> streaming TTS
                                                                  |             |
                                                             audio track    PCM chunks
                                                                  |             v
Browser <------------------------- H.264 video track <- avatar renderer <- avatar cache
```

For a self-hosted production version, use:

| Layer | Default choice | Reason |
| --- | --- | --- |
| Realtime transport | LiveKit + TURN | WebRTC rooms, cancellation, SFU, and client SDKs |
| Voice pipeline | LiveKit Agents or Pipecat | streaming STT → LLM → TTS and interruption handling |
| STT | faster-whisper / Whisper | local multilingual transcription |
| LLM | Ollama or vLLM-served model | tenant-controlled local inference |
| TTS | Fun-CosyVoice3 | Korean-capable bi-streaming choice; pin and audit exact weight snapshot |
| Head / eye / expression base | LivePortrait | one-photo learned motion-template cache; preserve source identity with relative motion |
| Product lip renderer | MuseTalk 1.5 | one-photo cache + 25fps mouth-last render; check all model/data licenses before commercial deployment |
| Future single-model R&D | Ditto | optional unified head-motion/lip-speech research, not the active product path |
| Offline quality fallback | LatentSync / Hallo | use only for non-live regeneration and QA |

The first production version should treat audio as the master clock. TTS emits 320–640 ms chunks; video worker uses ~200 ms look-ahead, stamps `turn_id` and sequence number on every frame, and drops late/stale frames. On interruption, cancel the LLM/TTS task and purge pending frames before accepting new user audio. Target metrics—not guarantees—are end-of-turn to first audio P50 < 1.2 s, first moving video < 1.5 s, and A/V drift < 80 ms.

## Why the app has a preview engine

An actual single-photo video renderer depends on model checkpoints, CUDA builds, GPU availability, and upstream model/data licenses. Pretending that a front-end-only mock is photorealistic video would make testing misleading. `preview` therefore gives a fully usable UX and protocol implementation without hiding the dependency; `remote` is the exact handoff point for the GPU worker.

The renderer API is intentionally small:

- `POST /v1/avatars/prepare` receives a source image path/id and immutable avatar version metadata, then returns a cache reference.
- `POST /v1/turns/render` receives a cache reference plus timestamped PCM/audio URL chunks and returns a WebRTC/HLS output reference or frame manifests.
- `POST /v1/turns/cancel` must stop a turn within the configured barge-in budget.

See [workers/avatar/CONTRACT.md](workers/avatar/CONTRACT.md) for JSON examples.

The current local GPU implementation lives in `workers/avatar/app/main.py`. At avatar preparation, LivePortrait loads the approved source once and applies its official compact `talking.pkl` template to create a small relative-motion loop (pose, eyes, cheeks, expression). MuseTalk caches an aligned latent and lower-face mask for every base frame. At turn time MuseTalk is the sole final mouth renderer; the worker paces JPEG frames at 25fps over MJPEG while the matching WAV is played in the browser. This validates motion/audio alignment locally; it is not the WebRTC media plane shown above.

## Model and rights checks

Ditto’s code and released model repository are Apache-2.0, and its upstream repo provides an online TensorRT configuration. Its tested environment is A100 / TensorRT 8.6.1 / Python 3.10, so do not assume the reported model latency transfers to a different GPU. MuseTalk’s code is MIT but its model-card and all transitive components still need audit. LivePortrait’s repository license calls out a commercial constraint around an InsightFace detector dependency; use a cleared detector or obtain the appropriate license. Do not use sample/test data from upstream models as product data. Keep the exact model version, weight hash, source license, and avatar-preparation metadata with each immutable avatar version.

## What moves to production after this prototype

1. Replace SQLite/filesystem with Postgres, Redis queue, and S3/MinIO signed object storage.
2. Require auth/tenant isolation and move source upload directly to signed object storage.
3. Add LiveKit server, TURN, VAD/turn detection, and a GPU admission queue.
4. Replace the local MJPEG/WAV bridge with a LiveKit video/audio publisher, then run model-specific load/quality tests before enabling it.
5. Add image/voice/prompt/output moderation, consent evidence, watermark/provenance, abuse reporting, and deletion/retention jobs.
