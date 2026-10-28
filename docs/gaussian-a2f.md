# NVIDIA A2F and behavior adapter

Implemented on 2026-09-23, without changes to SOBIA, EmpathicAgent or the existing
NVIDIA container. Install `apps/api/requirements-gaussian.txt` into the Gaussian
API environment. The existing video-generation service does not require it.

## Verified local service and protocol

- Existing container: `audio2face-3d`, `nvcr.io/nim/nvidia/audio2face-3d:1.3.16`.
- Host endpoint: `localhost:52000`; a separate Docker client uses its configured
  host gateway endpoint instead of its own `localhost`.
- RPC: `/nvidia_ace.services.a2f_controller.v1.A2FControllerService/ProcessAudioStream`.
- One bidirectional gRPC stream per assistant response. Header first; PCM16 mono
  chunks; `EndOfAudio` last; final success status required.
- Realtime 24 kHz PCM is converted to 16 kHz with a stateful, anti-aliasing 33-tap
  sinc filter. Arbitrary byte/chunk boundaries do not change the result.
- The service returns 71 named channels; this adapter maps all 52 ARKit channels
  by name and deliberately excludes A2F head channels. Never use an unverified
  numeric channel order when connecting a renderer.
- NIM `emotion_strength=0` disables audio-inferred affect. The inspectable behavior
  controller owns the chosen expression; A2F owns pronunciation.

The minimal private protobuf descriptors match the official ACE wire schema;
unknown fields are skipped by protobuf. This avoids a runtime dependency on
another repository's generated Unity code. Protocol validation includes a wire
fixture independent of the descriptor and an actual NIM inference test.

Primary reference: [NVIDIA gRPC documentation](https://docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/interacting/a2f-rpc.html).
The docs include the public proto definitions and their Apache-2.0 notices.

## Interfaces

```python
client = A2FClient("localhost:52000", trace=lambda event, payload: log(event, payload))
status = await client.health()
controller = BehaviorController()
plan = controller.from_affect("sad", .6, intent="supportive", nod=True)
async for frame in client.stream(pcm_chunks, input_sample_rate=24000):
    animation = controller.mix_frame(frame.coefficients, frame.time_seconds, plan)
    # animation: weights, raw_weights, head, head_units, gaze, behavior, composition
```

`head` uses degrees and the keys `pitch`, `yaw`, `roll`; the renderer converts to
its own coordinate convention. `gaze` uses normalized x/y, positive x toward the
avatar's right and positive y up. Eye-direction weights are emitted explicitly.
The LAM asset's supported channels must be checked independently: an unsupported
eye or head rig does not become controllable merely because coefficients exist.

For silent/listening frames, call `mix_frame({}, elapsed, plan, speaking=False)`.
This neutralizes oral articulation while retaining gaze, blinking, upper-face
expression and head motion. Each timed nod is a single smooth envelope, not a
perpetual nod animation. Gaze and head overrides are clamped to bounded ranges.

## Behavior ownership and provenance

The adapter follows the separation documented in SOBIA's
`EmpathicEmotion.IsHardSpeechArticulationChannel`: jaw, tongue and oral aperture
remain speech-provider-owned; only bounded smile/frown/dimple corners contribute
to expression during speech. Eye direction, blink and head pose have separate
owners. Negative or supportive behavior caps bright-smile channels.

This is a **rule-based SOBIA-inspired implementation**, not a port of the entire
Unity controller, not a trained empathy predictor, and not an assertion of
human-data validation. Every frame includes that provenance. Presets are initial
calibration values; facial appearance and head/eye sign conventions require
avatar-specific visual verification. The behavior fields describe intended
display affect, not measurements or diagnoses of a user.

Log the plan, raw A2F coefficients, mixed coefficients, source timestamps and
playout timestamps. `A2FClient` emits connection/header/first-frame/completion/
error lifecycle events. No synthetic lipsync is returned on service failure.
On interruption cancel the consuming task and discard that turn's queued audio
and animation together; gRPC is cancelled in the generator's cleanup path.

Conversation history commits assistant text only after matching browser
`playback.complete`. Interruption intentionally drops the entire unfinished
assistant reply, including any already heard portion, rather than reconstructing
an uncertain partial transcript. Accepted user text or a recognized current-turn
audio transcript is preserved even when generation is interrupted. Audio that
has not been transcribed is not replaced with invented text. Input transcription
events are matched to `input_audio_buffer.committed.item_id`; stale transcripts
from another turn are ignored and logged, never attached to the new turn.

## Verification

```powershell
.venv/Scripts/python.exe -m pytest apps/api/tests/test_gaussian_a2f.py apps/api/tests/test_gaussian_behavior.py -q
$env:GAUSSIAN_A2F_LIVE_TEST = '1'
.venv/Scripts/python.exe -m pytest apps/api/tests/test_gaussian_a2f.py apps/api/tests/test_gaussian_behavior.py -q
```

Initial local real-speech probe: 4 seconds of audio yielded 121 frames, all 52
ARKit channels, maximum `jawOpen=0.389`, first frame after 157 ms, final completion
after 1.86 seconds with input chunks sent faster than playback. A cold first
inference took about 5 seconds; show warming/buffering state and align audible
playback to available animation. These are observations, not guaranteed latency.

The integration test uses an existing local speech fixture, converts it to the
Realtime 24 kHz format and exercises live 24-to-16 kHz streaming. Unit tests cover
chunk-boundary invariance, anti-aliasing, timestamped gRPC output, naming/order,
unreachable-service errors, articulation preservation, smile guard, idle mouth
release, blinking/gaze, single-nod duration, bounds and provenance.
