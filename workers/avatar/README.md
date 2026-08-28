# Ditto avatar worker

The worker is intentionally a narrow GPU adapter, not a second application server. It uses a shared `/data` volume with the control API, so private source images never need to be uploaded from the API to another public endpoint.

## Modes

- `AVATAR_RENDER_MODE=stub`: validates avatar preparation and persists cache metadata only.
- `AVATAR_RENDER_MODE=ditto_live` (`Ditto Default`): stable baseline. It keeps `StreamSDK` loaded, renders the completed local TTS WAV, and emits 40 ms 16 kHz PCM plus JPEG frames carrying the same 25-fps PTS over one WebSocket.
- `AVATAR_RENDER_MODE=ditto_realtime` (`Ditto Realtime`): separate experimental worker. It uses Ditto's online `run_chunk` interface and a PCM-owned 25-fps clock: the local TTS segments are prepared concurrently, concatenated in text order, and their exact duration limits the generated motion and PCM packets together. This is the low-latency implementation track; it does not modify the Default worker.
- `AVATAR_RENDER_MODE=ditto_batch`: uses Ditto's official offline pipeline and muxes its generated video with the exact WAV into one MP4. This is the offline sync-reference path.
- `AVATAR_RENDER_MODE=musetalk_live`: retained as a mouth-rendering fallback. It prepares LivePortrait base frames and then performs MuseTalk lower-face inpainting.

In both Ditto modes, avatar preparation runs two silent Ditto windows and discards their frames. This deliberately moves the one-time CUDA/ONNX/PyTorch kernel warm-up from the first spoken turn to the avatar-ready phase. Realtime uses a 220 ms browser playout buffer; Default retains its conservative 600 ms stability buffer.

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
