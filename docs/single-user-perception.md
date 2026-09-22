# Single-user face observations (2026-09-21)

## What is implemented

Windows camera -> single-face MediaPipe -> SOBIA V3GuardStrict ONNX classifier
-> bounded in-memory observation window -> API turn snapshot -> response-local
Realtime instructions -> existing `set_avatar_affect(emotion, intensity)` -> Ditto.

The camera is OFF by default, including WAV mode. Open **사용자 얼굴 관측** and
click **얼굴 분석 켜기**. This starts the native local capture service's camera,
not a second browser `getUserMedia` stream. A 320x240 memory-only preview is
returned through the authenticated API. Disable the camera, end the room, or
close the tab to release capture (tab/crash heartbeat timeout: 12 seconds).

The local service supports exactly one session owner. Other sessions receive
409; session switching does not transfer samples. No identity, re-identification,
participant selection, body/hands, rPPG, Unity runtime, OVR mapping, or new LLM
classifier is included. Face landmarks/head pose are observations, not accurate
gaze or an instruction to mirror the user's face.

## Independent installation

From the repository root (Python 3.12 on this machine):

```powershell
python -m venv .venv-perception
.\.venv-perception\Scripts\python.exe -m pip install -r workers/perception/requirements.txt
.\.venv-perception\Scripts\python.exe workers/perception/provision.py ..\SOBIA-Unity
docker cp data/perception/token empathic-avatar-api-1:/data/perception-token
powershell -NoProfile -ExecutionPolicy Bypass -File workers/perception/start.ps1
```

Provisioning copies approved local model assets; no models are downloaded.
Runtime does not reference SOBIA or its virtual environment. Models, SHA256
manifest and generated config live in `models/perception`; the private host
token lives in `data/perception/token`. The Docker token is persisted in the
existing data volume. Native API users can set `PERCEPTION_TOKEN_FILE` to the
host token file and `PERCEPTION_URL=http://127.0.0.1:8020`.

Restart the host service after a machine reboot. `start.ps1 -Camera 1` selects a
different camera index. The service runs hidden; startup logs are under
`data/perception`. It does not open the camera just by starting the service.
Do not run SOBIA/browser/other software against the same camera concurrently.
No firewall/security settings are changed by setup.

For Docker Desktop the host service binds port 8020; all routes require a random
shared token. The API's existing authentication still applies. This remains a
local development configuration, not an authenticated multi-user public service;
do not publish either control endpoint without appropriate access controls.

## Source and behavior

`workers/perception/sobia_face.py` is the dependency closure for the SOBIA bridge's
single-face payload and EmotionClassifierRuntime, extracted on 2026-09-21.
Main/kead serialized mode 3 = V3GuardStrict is pinned, not the newer R2 field
initializer. Original image/blendshape pre-processing, classwise fusion, guards,
and temporal smoothing are retained. Changes: expose the omitted neutral score
and limit ONNX to two intra-op/one inter-op CPU threads. Models and MediaPipe run
on CPU to avoid taking Ditto's GPU inference budget. No wholesale SOBIA service
or multi-person state machine is imported.

Capture target: 640x480, at most 10 analyses/sec. Slow frames are not queued for
catch-up. Memory ring: at most 1800 samples; summaries use at most 120 seconds.
Use whole recorded speech interval (with end-age offset for recognition delay),
or the last 3 seconds for text/WAV. A 1-second freshness limit, minimum 3 usable
samples and >=50% usable ratio gate context. Size and head angle gates are
heuristics, NOT calibrated probability of correctness. Mouth-only surprise while
speaking becomes uncertain, not neutral. Missing face is unavailable, not neutral;
face loss also clears classification history and old observations.

Raw sample scores/blendshapes/head/eye positions remain local diagnostics. The
model gets only an allowlisted short summary (label, score, coverage, smile,
brow tension, speaking). Scores are apparent expression estimates, not a claim
about true emotional state. Spoken words take priority. User facial classes
remain separate from the avatar's eight display emotions; e.g. a happy observed
face can coexist with a manually chosen sad avatar expression.

No new Realtime response or tool call is added. Auto keeps its existing affect
tool + audio continuation; Manual keeps tool_choice=none. Both receive the same
current-turn summary in response-local instructions. No observation item is
appended to conversation history or session instructions. WAV does no model
work, but logs the observation and manual applied expression for diagnosis.
Unavailable camera service fails open to normal dialogue (bounded 0.6s local
request timeout); it cannot force an expression or block model generation.

## Diagnostics / privacy

Expand the face panel for live numerical data and the most recent turn's
observation -> applied motion. Existing feedback supports wrong observation,
missed face and empathy mismatch. The existing JSON report correlates
`observation.snapshot`, behavior decision, renderer application, timing and
operator feedback using the same turn_id. `model_context` is the exact short
observation payload (empty in WAV), not an extra generated explanation.

Raw camera frames/audio are not recorded by this module. Local diagnostics can
include facial feature values and existing conversation text when
EMPATHIC_DEBUG_LOG=true; treat exported reports as sensitive, not anonymous.
Set that flag false to disable disk observation/feedback diagnostics. Live ring
and preview clear on stop/loss/session end. No persistent personal profile.

## Verification

Final automated run: 46 API tests + 40 web tests + 5 host perception tests pass;
TypeScript/Vite production build passes. Existing warnings are Starlette test
client deprecation notices, not failing tests.

- Web regression and component tests cover explicit opt-in, speech window,
  cleanup, manual/WAV behavior and existing transitions.
- API tests cover context allowlisting, invalid numbers, unavailable service,
  Auto/Manual response-local instructions, no accumulation on the next turn,
  WAV zero dialogue calls, report correlation and ended-session rejection.
- Host tests cover freshness, quality, missing face, mouth-only surprise,
  post-speech exclusion, bounded history, authentication and owner isolation.
- `smoke_models.py` ran the real copied models on an existing local face image;
  12 frames averaged 5.42ms after warm-up. A 1600-frame offline run averaged
  6.88ms; these are fixture timings, not a live webcam accuracy benchmark.
- Browser WAV Happy turn `user-1789966667537`: zero JPEG decode errors, zero
  video PTS gaps, zero geometry fallback frames; both 1-second transitions
  retained. Peak geometry draw reached 48.5/71.3ms, so this is not a guarantee
  of no dropped display frames under every load.
- Actual user camera and real empathy quality need opt-in user testing. Camera
  was not activated automatically and no paid Realtime/TTS calls were made.

Official reference for response-local instructions:
https://developers.openai.com/api/docs/guides/realtime-conversations
