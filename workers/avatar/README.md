# Ditto avatar worker

The worker is intentionally a narrow GPU adapter, not a second application server. It uses a shared `/data` volume with the control API, so private source images never need to be uploaded from the API to another public endpoint.

## Modes

- `AVATAR_RENDER_MODE=stub`: validates avatar preparation and persists cache metadata only.
- `AVATAR_RENDER_MODE=ditto_live` (`Ditto Default`): stable baseline. It keeps `StreamSDK` loaded, renders the completed local TTS WAV, and emits 40 ms 16 kHz PCM plus JPEG frames carrying the same 25-fps PTS over one WebSocket.
- `AVATAR_RENDER_MODE=ditto_realtime` (`Ditto Realtime`): separate experimental worker. It uses Ditto's online `run_chunk` interface and a PCM-owned 25-fps clock: the local TTS segments are prepared concurrently, concatenated in text order, and their exact duration limits the generated motion and PCM packets together. This is the low-latency implementation track; it does not modify the Default worker.
- `AVATAR_RENDER_MODE=ditto_batch`: uses Ditto's official offline pipeline and muxes its generated video with the exact WAV into one MP4. This is the offline sync-reference path.
- `AVATAR_RENDER_MODE=musetalk_live`: retained as a mouth-rendering fallback. It prepares LivePortrait base frames and then performs MuseTalk lower-face inpainting.

In both Ditto modes, avatar preparation runs a silent Ditto dry-run to move CUDA/ONNX/PyTorch initialization out of the first spoken turn. `DITTO_WARM_MEDIA_PATH=true` additionally exercises the JPEG encoder and event-loop packet callback with one discarded frame. This option is off by default: on the RTX 5090 test it added preparation cost without reducing Ditto's intrinsic first-frame inference time. Realtime uses a 600 ms browser playout buffer so pre-decoded JPEG frames do not stutter at playback start.

`Ditto Realtime · Fast Lane` is a separate **session choice** that sends the named `fast` profile to the same Realtime worker. It uses `DITTO_FAST_SAMPLING_TIMESTEPS=2`; ordinary `Ditto Realtime` always remains at `DITTO_REALTIME_SAMPLING_TIMESTEPS=4`. Clients cannot submit arbitrary step counts. Fast Lane is experimental: compare it with the 4-step path for identity, mouth quality, flicker, and lip sync before using it in a demo.

## Realtime latency benchmark

Use the same avatar and text for every sampling-step comparison. Start one worker at a time with `DITTO_REALTIME_SAMPLING_TIMESTEPS` set to `4`, `3`, then `2`, wait for `/health`, prepare the avatar once, and run:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T avatar-worker-realtime python3 -m app.benchmark_realtime --label step-4 --runs 10
```

The probe saves raw first-frame JPEGs and a JSON result under `/data/benchmarks`. It measures render-response time, first packet, completion time, audio/video packet counts, and final A/V PTS skew. Worker logs additionally contain the internal TTS, Ditto setup, and first-frame timestamps.

For one semantic, media-free GPU-pipeline trace, set `DITTO_PROFILE_FIRST_TURN=true` when starting the Realtime worker and run one turn. The worker consumes the flag after that turn, and writes `/data/benchmarks/profiles/<turn>-pipeline.json`. The trace reports HuBERT, diffusion, motion stitching, warp, decode, put-back, and JPEG/packet wall-times. Its stage times overlap because Ditto uses parallel worker threads; `first_finished_ms` identifies the first-frame critical path rather than a sum of all rows.

The browser records timing-only events under the same turn ID at `/data/telemetry/turn-events.jsonl`: submission, API response, socket open, first packet, first decoded JPEG, playback start/end, decode failures, and video PTS gaps. It records no prompt text, PCM, or image payload. The browser starts at a 350 ms playout target and adapts between 200–600 ms only after a completed turn; decode failures or PTS gaps raise the next target.

`fast_preroll9` and `fast_preroll5` are worker-benchmark-only profiles. They expose causal context frames earlier but do **not** reduce Ditto computation and can advance mouth motion relative to the speech clock. They are intentionally absent from the API/UI renderer choices.

## MuseTalk product-prototype prerequisites

`docker-compose.gpu.yml` mounts `vendor/MuseTalk` and `models/musetalk` at the paths expected by the official MuseTalk code. The model directory must contain:

```text
models/musetalk/
  musetalkV15/{musetalk.json,unet.pth}
  sd-vae/{config.json,diffusion_pytorch_model.bin}
  whisper/{config.json,pytorch_model.bin,preprocessor_config.json}
  face-parse-bisent/{79999_iter.pth,resnet18-5c106cde.pth}
```

The first successful preparation loads model weights and builds the one-photo cache; leave the worker running afterwards. MuseTalk is intentionally the final facial stage, so any future LivePortrait head-motion base frames must be applied before it. Do not append a second mouth renderer after MuseTalk.

## Ditto prerequisites

1. On the GPU host, clone and pin the audited official [Ditto repository](https://github.com/antgroup/ditto-talkinghead) commit `c3e47eee2e626500017a0556b470d6d4182f85e8` into `vendor/ditto-talkinghead`, then apply `workers/avatar/patches/ditto-livekit-frame-sink.patch`. The patch now reverse-checks against the current vendor change and adds a per-session `frame_sink` plus cached source registration.
2. Download and audit the published checkpoint set into `models/ditto`. The default compose path is the portable PyTorch checkpoint route:

   ```text
   /models/ditto/ditto_pytorch
   /models/ditto/ditto_cfg/v0.4_hubert_cfg_pytorch.pkl
   ```

   The bundled `ditto_trt_Ampere_Plus` engines are **not** used on RTX 50-series hardware.

### TensorRT 10 / RTX 5090 build gate

Generate fresh artifacts only inside the GPU worker; the builder writes to
`/data/engines/ditto-trt10` and never overwrites checkpoint mounts or changes
the live PyTorch route:

```powershell
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T avatar-worker-realtime python -m app.trt10_ditto audit --all
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T avatar-worker-realtime python -m app.trt10_ditto build --supported
docker compose -f docker-compose.yml -f docker-compose.gpu.yml exec -T avatar-worker-realtime python -m app.trt10_ditto verify --supported
```

The JSON manifests include hardware/runtime versions, input profiles, engine
sizes and parser/build/execute failures. Do not enable a TensorRT renderer
until `warp_network` GridSample3D has a TensorRT 10-compatible plugin and a
full frame-parity test passes. Details: `docs/ditto-tensorrt10-rtx5090.md`.
3. The upstream reference environment is A100 / TensorRT 8.6.1 / Python 3.10. The RTX 5090 uses Blackwell (SM120) and a much newer CUDA/TensorRT stack. TensorRT engine files are tied to their TensorRT runtime, GPU architecture, and custom plugin ABI, so the supplied TensorRT-8/Ampere engine/plugin set cannot simply deserialize on the 5090. Use the PyTorch checkpoint config in this repository, or rebuild every ONNX engine and custom plugin for the exact 5090 runtime.
4. Start with one warm session and `DITTO_SAMPLING_TIMESTEPS=10`; benchmark first-frame time, RTF, VRAM, and A/V skew before admitting a second session.

```powershell
$env:AVATAR_RENDER_MODE = 'ditto_live'
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

## Motion controls in this prototype

`POST /v1/turns/render` accepts an optional bounded `motion_plan`. The Ditto adapter applies `head.yaw_deg`, `head.pitch_deg`, `head.roll_deg`, and a smooth nod envelope through upstream `ctrl_info`; it maps `expression` to Ditto's documented coarse emotion condition. The current public Ditto hook has no independent numeric pupil-gaze API, so `gaze` produces only a small head cue and is deliberately labelled as such in the UI.

```json
{
  "motion_plan": {
    "expression": "concern",
    "head": { "yaw_deg": 3, "pitch_deg": 0, "roll_deg": 0 },
    "gaze": { "x": 0, "y": 0 },
    "nod": { "start_ms": 320, "duration_ms": 460, "amplitude_deg": 5 }
  }
}
```

## Realtime handoff

Ditto’s upstream `stream_pipeline_online.py` exposes `StreamSDK.setup(...)` and `StreamSDK.run_chunk(...)` for online audio chunks. This checkout is patched to accept an in-process frame sink; `app/main.py` uses that sink to publish a bounded newest-frame MJPEG stream. The current engine resamples its local TTS to 16 kHz and feeds 6,480-sample chunks. For a public product, replace MJPEG/WAV with WebRTC (LiveKit plus TURN), streaming TTS PCM, VAD, and an admission-controlled per-room renderer pool. The interface and cancellation rules are specified in [CONTRACT.md](CONTRACT.md).

`DITTO_SAMPLING_TIMESTEPS` defaults to `10` for live responsiveness. The upstream-quality default is `50`, but it adds several seconds of motion diffusion latency on this prototype path.

Do not promise immediate GPU cancellation: upstream `StreamSDK.close()` is graceful/blocking. On barge-in, stop accepting new PCM, clear the local frame queue, increment an immutable generation, and drop delayed frames. If hard cancellation is required, isolate each Ditto session in a renderer process and terminate/recreate it after testing.

Do not expose this worker directly to the public internet. The compose extension keeps port 8010 internal and supports `WORKER_SHARED_TOKEN` as a temporary service-to-service gate; set a non-empty value before remote testing. Replace it with mTLS/service auth, queue admission, cache deletion, tracing, and metrics before deployment.
