# Avatar GPU worker contract

This is the boundary between the product control API and a CUDA media worker. It makes the browser/API work independently from Ditto, MuseTalk, or a future renderer.

The reference worker supports `stub` mode out of the box, a MuseTalk MP4 fallback, and a Ditto `StreamSDK` MJPEG bring-up path. The GPU Compose default is Ditto. A production low-latency worker should keep a Ditto `StreamSDK` per active avatar/turn, accept 16 kHz mono PCM chunks, and publish frames into a LiveKit video track instead of waiting for an MP4 to finish.

## `POST /v1/avatars/prepare`

Input:

```json
{
  "avatar_id": "8d4f...",
  "avatar_version": 1,
  "source_path": "/data/uploads/8d4f....jpg",
  "quality": { "width": 1024, "height": 1024, "score": 100, "hints": [] }
}
```

Response:

```json
{ "cache_ref": "ditto:8d4f...:1", "state": "ready" }
```

The worker must only accept source paths inside the shared `AVATAR_DATA_ROOT`; never fetch untrusted URLs or reveal the host path to clients. Store a model version, SHA-256 of the source and preprocessing/cache parameters beside the cache reference in production.

## `POST /v1/turns/render`

Input:

```json
{
  "avatar_id": "8d4f...",
  "turn_id": "e1a9...",
  "session_id": "optional-livekit-room",
  "audio_path": "/data/tts/e1a9.wav",
  "text": "Optional caption only",
  "motion_plan": {
    "expression": "warm",
    "head": { "yaw_deg": 5, "pitch_deg": 0, "roll_deg": 0 },
    "gaze": { "x": 0.3, "y": 0 },
    "nod": { "start_ms": 300, "duration_ms": 460, "amplitude_deg": 5 }
  }
}
```

Response from the Ditto streaming path:

```json
{
  "status": "streaming-mjpeg-ditto-controlled",
  "stream_url": "/v1/assets/live/e1a9",
  "audio_url": "/v1/assets/audio/e1a9.wav",
  "visemes": [],
  "applied_motion": { "expression": "warm", "head": { "yaw_deg": 5, "pitch_deg": 0, "roll_deg": 0 } }
}
```

`motion_plan` is bounded at the control API. Ditto receives head pose and nod samples through `ctrl_info`; its documented coarse emotion condition receives `expression`. The current upstream public hook does **not** expose numeric independent pupil gaze, so `gaze` is only a small head-direction cue and must not be presented as eye tracking.

For the realtime implementation, audio is the clock: attach `sequence`, `start_ms`, and 320–640 ms PCM chunks to the request or WebSocket; the worker should return/publish matching 25 fps frames. Keep a 200 ms look-ahead, drop late frames, and reject any frame whose `(session_id, turn_id)` is stale. A barge-in calls `POST /v1/turns/cancel` and must flush TTS/video queues before the next turn.

## `POST /v1/turns/cancel`

```json
{ "session_id": "optional-livekit-room" }
```

The reference batch renderer terminates its subprocess. A streaming worker should cancel the active `StreamSDK` pipeline and return to a precomputed idle loop.

## Required media-plane adaptation

The worker does not invent a video transport. In production, a voice-agent process owns a LiveKit room:

1. VAD/turn detector cancels active turn on user speech.
2. STT → LLM → CosyVoice streams PCM.
3. The agent publishes PCM as the LiveKit audio track and sends the same time-stamped chunk to the Ditto session.
4. Ditto produces 25 fps RGB frames which the agent/worker publishes as H.264 or VP8 video.
5. The client uses a small playout buffer and never renders stale sequence values.

That separation keeps one GPU renderer from owning browser credentials, authorization, or conversation text history.
