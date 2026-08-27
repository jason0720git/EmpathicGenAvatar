# 평가·벤치마크 계획

마지막 확인: **2026-08-25**  
목적: “데모가 좋아 보인다”를 제품·연구 의사결정에 쓸 수 있는 재현 가능한 증거로 바꾼다.

## 1. 평가 원칙

1. **사용자 체감 E2E와 모델 내부 latency를 분리**한다.
2. **논문/공급사 수치와 로컬 수치를 같은 열에 섞지 않는다.** 보고 주체와 HW를 기록한다.
3. 단일 평균 대신 P50/P95/P99와 실패율을 본다.
4. lip-sync, identity, control, context fit, latency를 별도 축으로 평가한다.
5. 평균 점수가 좋아도 safety/context gate를 실패하면 제품 후보로 통과시키지 않는다.
6. 같은 원본·스크립트·네트워크 조건과 blind human evaluation을 사용한다.
7. renderer가 지원하지 않는 control은 0점이 아니라 `unsupported`로 명시하고 제품 요구와의 gap을 계산한다.

## 2. 비교 대상과 lane

### Lane A — 현재 제품/오픈소스 renderer

- current MuseTalk + fixed LivePortrait loop
- MuseTalk + named LivePortrait motion bank
- Ditto audio-only baseline
- Ditto controlled
- 승격된 새 open-source adapter

같은 source image, 같은 PCM, 같은 behavior timeline, 같은 GPU에서 비교한다.

### Lane B — 상용 서비스

- Tavus CVI/PAL
- HeyGen LiveAvatar Full/Lite
- PERSO Interactive
- 필요 시 D-ID/Anam/기타 레지스트리 후보

공급사 약관이 허용하는 범위에서 동일한 persona와 한국어 test script를 사용한다. custom avatar 생성 조건이 달라 완전히 같은 identity를 쓸 수 없으면 `asset mismatch`로 표시하고 motion/context/service 축만 비교한다.

### Lane C — 연구 재현

- Avatar Forcing
- PersonaLive
- EmpaAva
- MaAI nod/backchannel
- 기타 watchlist

논문 checkpoint, 공개 code, 재현 code를 분리한다. 공개 repo가 offline inference만 제공하면 realtime 데모 수치를 재현했다고 쓰지 않는다.

## 3. 고정 테스트셋

### T0: media mechanics — 20 turns

- 1초/5초/15초 발화
- silence, plosive-rich, vowel-rich, 빠른/느린 한국어
- turn 3/10/30초 지점 interruption
- packet loss 0/2/5%, RTT 20/100/250ms
- renderer cold/warm cache

### T1: control sweep — 각 3회

- yaw: -10°→0→+10°
- pitch: -6°→+8°; single/double nod
- roll: ±4°
- gaze: center/left/right/down
- blink: single/double/slow
- expression: neutral/soft smile/concern/surprise-low
- 동시에 speech+head, speech+expression, nod+gaze를 수행

### T2: 문맥 적절성 — 최소 50 turns

필수 한국어 scenario:

| ID | 사용자 맥락 | 기대 | 핵심 실패 |
|---|---|---|---|
| E01 | “오늘 가족 일로 너무 슬퍼요.” | neutral attentive/soft concern | smile, excited nod |
| E02 | “발표에 합격했어요!” | soft joy/congratulation | flat or concern |
| E03 | “제가 실수했는데 어떻게 사과할까요?” | calm, nonjudgmental | smirk/contempt |
| E04 | 불만을 길게 설명 | listener nod는 드물고 적절한 boundary | 반복 nod, 말 끊기 |
| E05 | 농담 후 pause | 웃음/미소 허용 | 심각한 concern 유지 |
| E06 | 불확실한 정보 질문 | thinking/neutral | 자신만만한 nod |
| E07 | 사용자 침묵 5초 | gaze/idle 유지 | freeze 또는 과한 gesture |
| E08 | 답변 중 사용자 barge-in | 즉시 입·음성 중단, listening | stale lip/말 계속 |
| E09 | 카메라 얼굴 소실 | neutral fallback | 마지막 표정 고착 |
| E10 | 얼굴은 웃지만 말은 나쁜 소식 | 말/문맥 우선 | mimic smile |

각 scenario에는 gold label 하나가 아니라 `allowed`, `disallowed`, intensity range를 둔다.

### T3: 장시간 안정성

- 30분 conversation soak × 5
- 2시간 idle/listen/speak transition soak
- 100회 rapid interrupt
- avatar 20개 순차 prepare/delete
- worker recycle/reconnect
- 두 session admission 시도와 overload response

## 4. latency와 realtime 지표

### 이벤트 정의

| 기호 | 이벤트 |
|---|---|
| `U0` | user speech onset at browser capture |
| `U1` | user end-of-turn accepted by agent |
| `S0` | first stable STT partial |
| `L0/L1` | first/final LLM token |
| `A0` | first TTS PCM generated |
| `AP0` | first avatar audio sample played in browser |
| `V0` | first matching speaking frame painted |
| `B0` | barge-in detected |
| `AS` | outbound audio becomes silent |
| `VS` | last stale-generation frame painted |

필수 산식:

```text
turn_detection_latency = U1 - actual_user_speech_end
reply_first_audio       = AP0 - U1
reply_first_video       = V0 - U1
av_skew(frame)          = video_pts - audio_playout_pts
barge_in_audio_stop     = AS - B0
barge_in_video_stop     = VS - B0
renderer_rtf            = render_wall_time / generated_media_duration
```

`first_frame_s`가 renderer 함수 내부 시작점부터라면 `reply_first_video`로 보고하지 않는다.

### 목표 gate [H]

| 지표 | Alpha P95 | 실패 기준 |
|---|---:|---:|
| `reply_first_audio` | ≤1.2s | >1.8s |
| `reply_first_video` | ≤1.5s | >2.0s |
| `barge_in_audio_stop` | ≤150ms | >250ms |
| stale video | 200ms 이후 0 frame | 1 frame 이상 |
| absolute A/V skew | ≤100ms | >160ms |
| delivered fps | ≥24 | <20 지속 1초 |
| renderer RTF | <0.90 | ≥1.0 |

RTF가 1 이상이면 queue가 길어져 장시간 대화에서 실시간을 잃는다. 순간 first frame이 빠른 것만으로 통과할 수 없다.

## 5. motion/control 지표

output 영상에서 같은 pose/gaze/blendshape extractor를 다시 실행한다. extractor 자체 bias가 있으므로 실제 landmark를 소량 수동 검증한다.

| 제어 | 지표 | Alpha gate [H] |
|---|---|---:|
| head yaw/pitch/roll | MAE, Pearson/Spearman correlation, lag | MAE ≤3°, corr ≥0.85, lag ≤120ms |
| gaze | target classification, normalized error, dwell | 3×3 target accuracy ≥80% |
| nod | event precision/recall/F1, onset MAE, amplitude/duration error | F1 ≥0.80, onset MAE ≤120ms |
| blink | event F1, duration distribution | F1 ≥0.85; 80–450ms 범위 |
| expression | requested→output coefficient correlation, family confusion | corr ≥0.70; disallowed family <2% |
| speech+control | control delta while lip metric maintained | lip metric baseline 대비 비열화 |

또한 다음 artifact를 count한다.

- 얼굴 bbox/mask seam
- frame transition pop
- hair/background warping
- teeth/tongue instability
- eye asymmetry, stuck gaze
- head-body disconnect
- identity drift
- freeze/repeated-loop detectability

## 6. lip-sync와 영상 품질

자동 metric은 상대 비교로 사용하고 사람이 최종 판단한다.

### 자동

- SyncNet 계열 LSE-D/LSE-C 또는 동일 공개 모델의 audio-video sync score
- phoneme closure test: /p/, /b/, /m/에 mouth closure가 있는지
- audio-video cross-correlation과 drift over time
- identity embedding cosine similarity의 평균/하위 5%와 temporal variance
- optical flow jerk, landmark acceleration, LPIPS/temporal difference
- no-reference blur/blocking과 face seam ratio

metric extractor의 라이선스, version, crop rule을 benchmark manifest에 고정한다. identity embedding은 민감 정보이므로 평가 환경 밖으로 반출하지 않는다.

### 사람 평가

5점 척도:

1. 입술이 음성과 맞는가
2. 머리·눈·표정이 자연스러운가
3. 같은 사람/캐릭터로 안정적으로 보이는가
4. 반응 timing이 대화와 맞는가
5. 표정이 문맥에 맞는가
6. 기괴함/불편함이 없는가
7. 상대가 나를 듣고 있다고 느껴지는가

`자연스러움` 하나로 합치지 않고 문항별로 보고한다.

## 7. 문맥-표정 평가

### contradiction rate

```text
contradiction_rate = disallowed_expression_frames / evaluable_expression_frames
```

frame 수가 긴 영상에 유리/불리하지 않도록 event-level도 병행한다.

```text
contradiction_event_rate = turns_with_any_disallowed_expression / evaluable_turns
```

예: E01에서 smile intensity >0.08이 300ms 이상 유지되면 contradiction event로 센다. 숫자는 initial policy threshold이며 평가자 합의로 calibration한다.

### calibration과 abstention

- confidence가 낮을 때 neutral로 물러나는 비율
- 잘못 확신한 expression의 expected calibration error
- perception 소실 후 stale expression duration
- explicit user statement와 visual proxy 충돌 시 문맥 우선 성공률

제품에서는 많은 표정을 보여주는 것보다 **모를 때 neutral로 돌아가는 능력**을 점수화한다.

## 8. human study 설계

### 내부 alpha

- 8–12명, 각 20–30분
- 같은 renderer를 반복 노출하되 Latin square로 순서 균형
- renderer/서비스 브랜드와 조건 이름을 숨김
- 최소 3개의 negative, 2개의 positive, 2개의 interruption scenario
- 세션 직후 MOS와 pairwise preference, 자유서술 failure tag

### 외부 beta

- 타깃 사용군을 반영한 30명 이상
- avatar identity/성별/스타일과 조명/네트워크 조건 분산
- 개인정보·민감 대화가 필요 없는 scripted scenario 우선
- effect size와 confidence interval 보고; p-value만 보고하지 않음

### 상용 서비스 blind 비교 주의

- 각 서비스의 공식 training recipe를 지킨다.
- 해상도, 화면 crop, 음량, 대화 script, 평가 UI를 맞춘다.
- 공급사가 gesture를 동적으로 제어할 수 없다면 해당 실험은 `autonomous behavior`로 분류한다.
- vendor의 자체 STT/LLM/TTS가 강제로 포함되면 `full stack` 결과이며 renderer 단독 결과와 섞지 않는다.

## 9. 서비스성·HW 벤치마크

### 환경 matrix

최소 다음을 기록한다.

- GPU model/VRAM/driver/CUDA/TensorRT/PyTorch
- CPU/RAM/storage
- model/weight hash와 precision
- avatar resolution/output codec/fps
- warm/cold, batch, sampling steps
- session concurrency와 admission 정책
- network RTT/loss/bandwidth

### 측정값

- peak/steady VRAM, host RAM
- prepare time와 avatar cache size
- first/warm turn latency
- RTF, delivered fps, encode time
- GPU utilization, power if available
- concurrent sessions 1→N의 P95 latency와 quality
- OOM/crash/recovery time
- 30분당 cache/memory 증가
- GPU-hour당 delivered session-minute

동시성은 UI plan의 숫자나 내부 batch size가 아니라 SLO를 동시에 지킨 room 수다.

## 10. 비용 연결

각 benchmark row에 다음을 붙인다.

```text
renderer_gpu_cost_per_delivered_minute
voice_api_cost_per_minute
network_egress_per_minute
storage/logging_per_session
operator_incident_time
```

산식과 시나리오는 [비용·용량 모델](../02-landscape/COST_AND_CAPACITY.md)을 사용한다. 상용 서비스의 구독 포함분은 100% 소진 가정과 실제 예상 소진율을 둘 다 계산한다.

## 11. scorecard와 의사결정

### must-pass gates

- commercial-use license/territory/rights clear
- no unresolved critical safety/privacy failure
- barge-in, A/V skew, RTF gate 통과
- disallowed context expression event <5% alpha
- 30분 crash-free ≥95%

### 가중 점수 — gate 통과 후만

| 축 | 가중치 |
|---|---:|
| 문맥 적절성/attentiveness | 25 |
| motion control adherence | 20 |
| lip-sync/영상 품질 | 20 |
| realtime/serviceability | 20 |
| 비용/확장성 | 10 |
| 개발·운영 복잡도 | 5 |

한 총점만 보고하지 않고 raw 축 점수, confidence interval, unsupported control을 함께 공개한다.

### 결정 예

- Track A가 품질과 안정성은 좋지만 gaze unsupported: alpha 기본, gaze는 명시적 limitation.
- Track B가 control은 좋지만 RTF ≥1: 연구 유지, 제품 미승격.
- 상용 A가 자연스럽지만 dynamic gesture API 없음: 비교 baseline/고객 검증용, 핵심 제어 제품과 동일 범주로 보지 않음.

## 12. benchmark artifact 구조

```text
benchmarks/
  manifests/<run_id>.yaml
  metrics/<run_id>.json
  traces/<run_id>.jsonl
  samples/<consented_or_synthetic_only>/
  reports/YYYY-MM.md
```

각 run은 다음을 포함한다.

- code commit와 dirty flag
- model/source/weight hash
- exact command/config/env
- input asset rights id
- start/end time와 operator
- raw metric과 aggregation script version
- known anomaly/exclusion reason

현재 저장소에는 versioned commit이 없으므로 첫 benchmark보다 먼저 재현 가능한 baseline을 만든다.

## 13. 회귀 테스트

매 PR 또는 nightly GPU run에서:

- schema golden timeline
- 5초 phoneme-rich lip clip
- head pose/nod scripted sweep
- negative-context no-smile case
- user interruption stale-generation test
- 10분 memory/RTF smoke

월간에는 full T0–T3와 상용 spot check를 실행한다. 결과는 [리서치 유지관리](../04-operations/RESEARCH_MAINTENANCE.md)의 증거 등급과 함께 비교표에 반영한다.
