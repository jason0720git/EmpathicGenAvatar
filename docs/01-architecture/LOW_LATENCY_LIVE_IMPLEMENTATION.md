# 저지연 라이브 아바타: 구현 직전 설계안

마지막 확인: **2026-08-27**  
상태: **구현 승인 대기**  
목표: 사용자가 발화를 끝낸 뒤 브라우저에서 첫 음성·첫 speaking frame을 **P95 2.5초 이하**에 보이게 한다.

## 1. 이번 설계의 결론

현재 Ditto 단독 경로는 첫 Ditto frame이 약 3.07초이고, TTS와 브라우저 buffer를 합치면 첫 화면이 약 4.8–5초다 [L]. 따라서 Ditto만 최적화해 2–3초 상용 서비스 체감을 만들 수는 없다.

이번 구현은 아래 두 경로를 **한 세션 안에 공존**시키되, 한 발화 중에는 renderer를 바꾸지 않는다.

```text
사용자 음성/텍스트
        │
        ▼
 Turn manager ──→ streaming STT / LLM / TTS ──→ WebRTC audio track
        │                                         │
        ├── fast renderer (기본) ──────────────────┤→ WebRTC video track
        │     목표: 첫 frame ≤ 1.2초                │
        │
        └── Ditto quality renderer (선택) ─────────┘
              목표: 고품질, first frame은 현재 수준
```

- **기본 모드 `live_fast`**: 첫 답변부터 저지연 renderer를 사용한다. 후보는 현재 GPU에서 first-frame 잠재력이 확인된 `LivePortrait motion bank → MuseTalk mouth-last` 경로다. 단, 품질·sync·제어 기준을 통과한 경우에만 기본값으로 승격한다.
- **품질 모드 `ditto_quality`**: 현재 Ditto live 경로를 유지한다. 사용자 또는 운영자가 명시적으로 선택한다.
- **중요**: 빠른 renderer로 시작해서 같은 문장 중간에 Ditto로 갈아타지 않는다. 두 모델의 crop, 얼굴 mask, motion distribution이 달라 전환 순간 얼굴이 튀거나 립싱크가 깨질 가능성이 높다. 전환 연구는 별도 A/B 통과 후에만 연다.

## 2. 이번 범위와 비범위

### 이번에 구현할 것

1. WebSocket JPEG/PCM media path를 **LiveKit WebRTC** audio/video track으로 교체한다.
2. TTS를 전체 WAV가 아닌 **문장(clause) 단위 PCM stream**으로 만든다.
3. `SessionRuntime`이 PCM, 행동 명령, video frame에 동일 PTS와 `generation_id`를 붙인다.
4. `live_fast`, `ditto_quality` capability를 세션 생성 시 협상한다.
5. 사용자 발화가 감지되면 이전 generation의 audio/video를 즉시 publish 차단한다.
6. 브라우저에서 E2E latency, A/V skew, dropped frame을 측정해 API로 전송한다.

### 이번에 하지 않을 것

- Ditto와 fast renderer의 발화 중 자동 crossfade
- 사용자 얼굴 영상의 서버 저장 또는 민감 속성 추정
- 프레임별 `delta_exp`를 LLM이 직접 제어하는 기능
- 다중 GPU autoscaling 및 자체 streaming diffusion 학습

## 3. 사용자에게 보이는 동작

```text
사용자가 말 끝냄
  0.0s   turn detector 확정
  0.2s   LLM의 첫 안전한 절(clause) 확보
  0.4s   첫 TTS PCM + fast renderer 입력
  0.8–1.5s WebRTC에서 첫 음성/얼굴 표시
  이후   같은 발화의 PCM과 video를 계속 stream
  다음 turn부터 필요하면 Ditto quality를 선택 가능
```

수치는 목표 [H]이며, renderer가 RTF(생성 wall time / media duration) 0.9 미만을 달성해야 한다. 이 기준을 못 맞추면 `live_fast`는 기본값이 될 수 없다.

## 4. 구체적인 컴포넌트 설계

### 4.1 Browser — `apps/web`

추가 파일:

| 파일 | 책임 |
|---|---|
| `src/livekitRoom.ts` | token으로 room 연결, mic/audio/video track publish·subscribe |
| `src/telemetry.ts` | `U1`, `AP0`, `V0`, audio/video PTS, RTT를 기록 |
| `src/rendererMode.ts` | fast/quality 선택과 capability 표시 |

`App.tsx`에서 제거/대체할 부분:

- `startRealtime()`의 binary WebSocket, JPEG `createImageBitmap`, `AudioContext` 직접 scheduling을 제거한다.
- `<canvas>` overlay 대신 LiveKit가 구독한 `<video>` element를 동일한 stage rect에 둔다.
- 현재 600ms `initialBufferMs`는 제거한다. WebRTC receiver의 jitter target은 **200ms로 시작**하고, P95 skew/freeze로 150–250ms에서 조정한다.
- 사용자의 첫 음성 capture와 end-of-turn 확정 시간을 `performance.now()`로 기록한다.

### 4.2 API/control plane — `apps/api`

새 API 계약:

```http
POST /api/live/sessions
{
  "avatar_id": "demo-hana",
  "renderer_preference": "live_fast"
}

201
{
  "id": "session-id",
  "room": { "url": "wss://…", "token": "short-lived" },
  "capability": {
    "selected_renderer": "live_fast",
    "fallback_renderer": "ditto_quality",
    "fps": 25,
    "streaming_audio": true,
    "controls": ["lip", "nod", "blink", "head_pose:primitive"]
  }
}
```

추가 endpoint:

```http
POST /api/live/sessions/{id}/telemetry
{
  "turn_id": "…", "u1_ms": 0, "ap0_ms": 930, "v0_ms": 1010,
  "max_av_skew_ms": 43, "dropped_video_frames": 0
}
```

`TurnIn`에는 `renderer_preference`를 넣지 않는다. renderer 결정은 세션별로 고정해 같은 발화의 영상 identity/motion이 흔들리지 않게 한다. 운영자만 다음 turn 전에 mode 변경을 요청할 수 있다.

### 4.3 Agent — 새 `apps/agent`

LiveKit Agent process가 다음만 담당한다.

```text
browser mic track
 → VAD / turn detector
 → streaming STT
 → conversation.stream_reply()
 → clause buffer (문장부호 또는 180–420ms 안전 경계)
 → streaming TTS PCM
 → audio publisher + renderer.push_audio()에 같은 PTS 전달
```

필수 인터페이스:

```python
class TurnRenderer(Protocol):
    capabilities: RendererCapabilities
    async def start_turn(self, turn_id: str, generation_id: int, first_pts_ms: int) -> None: ...
    async def push_audio(self, pcm_s16le: bytes, pts_ms: int) -> None: ...
    async def push_behavior(self, frame: BehaviorFrame) -> None: ...
    async def frames(self) -> AsyncIterator[VideoFrame]: ...
    async def cancel_before(self, generation_id: int) -> None: ...
    async def close_turn(self) -> None: ...
```

`conversation.py`는 `respond()` 외에 아래 streaming API를 제공한다.

```python
async def stream_reply(*, persona: str, user_text: str) -> AsyncIterator[ReplyDelta]:
    """텍스트 token과 안전한 clause boundary를 반환한다."""
```

SafeDemo는 사전 정의된 답을 2–3개 clause로 나눠 즉시 yield한다. Ollama는 `/api/chat`의 `stream:true`를 사용하며, sentence boundary에서만 TTS로 넘긴다. 금지 요청의 guard는 **첫 token 전**에 적용한다.

### 4.4 Renderer worker — `workers/avatar`

새 파일과 책임:

| 파일 | 책임 |
|---|---|
| `app/session_runtime.py` | turn별 queue, audio clock, `generation_id`, deadline |
| `app/fast_runtime.py` | named LivePortrait motion bank 선택 + MuseTalk mouth-last adapter |
| `app/ditto_runtime.py` | 현재 `DittoLiveRuntime`을 quality adapter로 분리 |
| `app/behavior.py` | capability에 맞게 표정/pose/nod 명령을 변환·제한 |

`main.py`에는 준비, capability, health, admission endpoint만 남긴다. 영상 frame은 `VideoFrame(pts_ms, generation_id, rgb)`로 반환하며 Agent가 LiveKit video track에 publish한다.

`fast_runtime`의 준비 산출물은 avatar별 motion bank다.

```text
neutral_breathe (loop)   listen_attentive (loop)  blink_single
nod_small                gaze_left/right/down     concern_soft
```

Motion primitive 전환은 4–8 frame crossfade를 사용하고, MuseTalk가 **마지막 단계**에서 mouth를 합성한다. renderer가 head/gaze를 정밀 제어하지 못하면 capability에 `primitive`로 표시하며, policy는 과도한 약속을 하지 않는다.

## 5. 시간·취소 규칙

### 하나의 시계

- 첫 TTS PCM sample이 `pts=0`이다.
- renderer에 넘기는 PCM과 LiveKit audio track은 같은 16kHz sample clock을 사용한다.
- video frame은 대응하는 audio `pts_ms`를 보유한다.
- 늦은 video는 audio를 늦추지 않는다. jitter 목표(초기 200ms)를 넘긴 frame은 drop하고 telemetry에 남긴다.

### 끼어들기(barge-in)

```text
user VAD onset
 → generation_id 증가
 → outbound audio mute
 → 이전 PCM/behavior/frame queue flush
 → 이전 generation video publish 거부
 → fast renderer cancel; deadline 초과면 worker process recycle
 → listen_attentive primitive publish
```

성공 기준은 VAD onset 뒤 250ms 이후 이전 turn의 frame이 **0장**인 것이다.

## 6. 구현 순서와 완료 조건

| 순서 | 변경 | 완료 조건 |
|---|---|---|
| 1 | LiveKit local + TURN, color-bar video/audio | 5분 통화에서 A/V skew P95 ≤100ms |
| 2 | streaming TTS + Agent clause pipeline | `A0-U1` P95 ≤700ms |
| 3 | `SessionRuntime` + generation cancel | 100회 interrupt에서 stale frame 0 |
| 4 | fast renderer adapter/motion bank | warm first video `V0-U1` P95 ≤1.5s, RTF <0.9 |
| 5 | browser stage/telemetry/capability UI | 각 turn의 U1/A0/AP0/V0 trace 수집률 ≥99% |
| 6 | Ditto quality adapter 분리 + A/B | quality mode가 기존 sync/control 기준 회귀 없음 |

### Release gate

`live_fast`를 기본 모드로 바꾸는 조건은 모두 충족해야 한다.

- 25fps delivered P95, 20fps 미만 연속 1초 없음
- `reply_first_audio` P95 ≤1.8초, `reply_first_video` P95 ≤2.5초
- absolute A/V skew P95 ≤100ms, 최대 ≤160ms
- 30분 soak 5회에서 crash/OOM 없음
- 현재 Ditto 대비 lip-sync·identity human score가 사전 정의한 비열화 한계 내
- `nod`, `concern`, `neutral`의 capability와 실제 결과가 일치

## 7. 운영 옵션과 rollback

```env
MEDIA_TRANSPORT=livekit        # legacy_websocket | livekit
DEFAULT_RENDERER=live_fast     # ditto_quality | live_fast
WEBRTC_JITTER_TARGET_MS=200    # 150–250 only after benchmark
FAST_RENDERER_ENABLED=false    # rollout gate
DITTO_SAMPLING_TIMESTEPS=4     # quality mode may use 10–50
```

- 신규 경로 실패 시 세션 단위로 `ditto_quality` 또는 현재 `legacy_websocket`으로 되돌린다.
- renderer 성능 부족 시 audio를 지연시켜 억지로 동기화하지 않는다. fast path를 종료하고 idle/listening으로 복귀하며 failure reason을 기록한다.
- 캡처 원본은 저장하지 않고 latency/control trace만 세션 보존 정책에 따라 익명화해 저장한다.

## 8. 지금 필요한 의사결정

구현을 시작하려면 다음을 확정한다.

1. **LiveKit self-host**를 기본 media plane으로 사용한다. 외부 SaaS 계정/비용 없이 로컬 Docker부터 검증한다.
2. fast renderer 첫 후보를 **LivePortrait motion bank → MuseTalk**로 둔다. Ditto는 quality mode로 분리한다.
3. `live_fast`는 benchmark gate 통과 전에는 실험 플래그이며, Ditto를 자동으로 대체하지 않는다.

이 세 결정이 승인되면 순서 1부터 실제 코드·컨테이너·테스트를 구현한다.
