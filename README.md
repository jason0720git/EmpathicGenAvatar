# Empathic Avatar

One approved portrait photo can be prepared once and reused for live, AI-labelled voice conversations. This repository is a working product prototype: it includes a polished browser studio, a persistent control API, explicit consent recording, deletion, live-turn orchestration, browser speech fallback, and a swappable GPU avatar-renderer contract.

## What runs now

`preview` mode runs on a laptop without a GPU:

- Photo upload, quality hints, explicit likeness/age consent, and persistent private avatar records
- Live room with microphone input, browser speech recognition where supported, text fallback, captions, barge-in, and browser TTS
- An audio-reactive portrait preview that makes the conversation flow testable end-to-end
- SQLite persistence, asset deletion cascade, session history disabled by default, and a FastAPI WebSocket turn channel

It deliberately does **not** claim to synthesize photorealistic streaming video without a GPU model. GPU compose defaults to Ditto's realtime PTS transport: the worker sends 40 ms 16 kHz PCM and JPEG frames on one WebSocket, both carrying the same 25-fps presentation timestamp. The browser schedules PCM with `AudioContext` and draws each JPEG against that same clock. `ditto_batch` remains the offline sync-reference path. LivePortrait + MuseTalk remains a fallback; see [ARCHITECTURE.md](ARCHITECTURE.md).

## Quick start

### Docker (recommended)

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Open `http://localhost:4173`. The API is available at `http://localhost:8000/docs`.

The bundled compose configuration is explicitly a **local development** deployment (`APP_ENV=development`). Before exposing it outside localhost/private infrastructure, put an OIDC/auth gateway in front of the API, set `APP_ENV=production` and a non-empty `API_ACCESS_TOKEN`, remove the API host port if it is not needed, and use mTLS/service authentication for the GPU worker.

### Local development

Use Python 3.11+ and Node 22+.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r apps/api/requirements.txt
uvicorn app.main:app --app-dir apps/api --reload --port 8000

# another terminal
pnpm install
pnpm dev
```

Open `http://localhost:5173`.

## Tests

```powershell
pnpm build
pnpm test:api
```

## Safety boundary

This prototype is private-avatar only. The creation flow requires the operator to confirm that the subject is an adult and that they hold the right to use the likeness. Public sharing, celebrity/public-figure impersonation, voice cloning, and exports without a persistent AI label are intentionally outside this build. Before any public launch, add identity/liveness verification, trained-image moderation, prompt/output moderation, authenticated tenants, signed uploads, rate limiting, retention enforcement, audit controls, watermark/provenance, and local legal/privacy review.

## Ditto GPU renderer bring-up

The default compose stack deliberately remains GPU-free. The GPU extension starts Ditto's realtime renderer with the checked-in Ditto source and audited PyTorch checkpoints:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

`workers/avatar` implements the control-plane contract and validates the mounted model layout. The default GPU extension starts `ditto_live`: it returns quickly, then streams audio PCM and Ditto JPEGs under one PTS clock through `/avatar-stream/`. On an RTX 5090 it uses PyTorch weights; the supplied TensorRT-8/Ampere engines are incompatible with the newer Blackwell runtime. `ditto_batch` remains available for offline quality baselines. [workers/avatar/README.md](workers/avatar/README.md) documents the model files and remaining token-level TTS/WebRTC work.
