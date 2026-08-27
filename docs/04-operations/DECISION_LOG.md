# 의사결정 기록

마지막 확인: **2026-08-25**

이 문서는 가벼운 ADR이다. 과거 결정을 덮어쓰지 않고 새 행/항목으로 supersede한다.

## 요약

| ID | 결정 | 상태 | 재검토 시점/trigger |
|---|---|---|---|
| ADR-001 | renderer-independent behavior protocol | Accepted | 공통 schema로 표현 불가능한 필수 control 발견 |
| ADR-002 | WebRTC/LiveKit, audio master clock | Accepted | 측정된 요구를 못 맞추거나 더 단순한 동등 대안 검증 |
| ADR-003 | camera derived features by default | Accepted | privacy review가 더 엄격한 제한 요구 |
| ADR-004 | LLM과 저수준 motion 분리 | Accepted | constrained motion model이 guard 포함 우위 입증 |
| ADR-005 | LivePortrait bank→MuseTalk를 product bridge | Provisional | Ditto controlled가 품질/SLO 모두 우위 또는 bank artifact 실패 |
| ADR-006 | Ditto `ctrl_info`를 첫 control spike | Accepted | clean reproduction 실패 또는 RTF/품질 gate 실패 |
| ADR-007 | Avatar Forcing/EmpaAva 등은 R&D only | Accepted | 상용 license, realtime code, local gate 모두 충족 |
| ADR-008 | training 전에 telemetry/evaluation/data rights | Accepted | 없음; 기본 원칙 |
| ADR-009 | sensitive emotion inference 금지 | Accepted | 법무/윤리 기준이 더 엄격해질 수 있음 |
| ADR-010 | build-vs-buy를 분기별 재계산 | Accepted | 사용량/가격/제품 요구 변화 |

## ADR-001 — renderer-independent behavior protocol

- 날짜: 2026-08-25
- 상태: Accepted
- 맥락: MuseTalk, Ditto, LivePortrait, future DiT는 제어 공간과 지원 채널이 다르다.
- 결정: 공통 시간축에 expression/head/gaze/blink/nod/speech와 provenance를 표현하고 renderer adapter가 mapping한다.
- 이유: perception/policy/data를 특정 model에 잠그지 않고 동일 테스트를 재사용할 수 있다.
- 거절한 대안: LLM prompt→renderer-specific emotion tag 직접 연결, model별 별도 pipeline.
- 결과: unsupported/downgraded control telemetry와 capability negotiation이 필수다.

## ADR-002 — WebRTC/LiveKit과 audio master clock

- 날짜: 2026-08-25
- 상태: Accepted
- 맥락: 현재 MJPEG와 별도 WAV는 서로 다른 clock이며 로컬 MuseTalk가 약 21.4fps로 audio보다 늦어진 흔적이 있다 [L].
- 결정: LiveKit/WebRTC track과 TURN을 사용하고 TTS PCM PTS를 speaking video의 master로 한다.
- 이유: full-duplex, jitter/congestion, synchronized media, barge-in을 제품 수준에서 다룰 수 있다.
- 거절한 대안: MJPEG/WAV 개선만 계속, custom RTP stack.
- 결과: 기존 경로는 디버그 fallback으로 축소한다.

## ADR-003 — camera derived features by default

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: browser on-device face landmark/blendshape/pose를 10–15Hz로 처리하고 raw camera는 연구 opt-in에서만 전송/저장한다.
- 이유: latency/bandwidth/privacy를 낮추며 제품에 필요한 신호 대부분을 얻을 수 있다.
- 결과: 원본 영상이 필요한 model은 별도 consent와 data plane이 필요하다.

## ADR-004 — LLM과 저수준 motion 분리

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: LLM은 text/dialogue act/affect intent를 제안하고 deterministic policy가 저수준 motion을 만든다.
- 이유: frame-level JSON 생성 latency와 jitter를 피하고, 문맥-표정 guard를 재현 가능하게 만든다.
- 거절한 대안: 매 frame LLM 호출, emotion tag를 renderer에 직접 전달.

## ADR-005 — LivePortrait motion bank→MuseTalk product bridge

- 날짜: 2026-08-25
- 상태: Provisional
- 맥락: 현재 공유 트리에 fixed LivePortrait talking-template frames를 MuseTalk base로 순환하는 코드가 있으나 behavior control은 없다.
- 결정: 이를 named primitive bank와 timed selection으로 확장하고 MuseTalk를 mouth-last로 유지한다.
- 이유: 학습 없이 빠른 deterministic listener motion과 safe fallback을 만들 수 있다.
- 한계: arbitrary frame-level control이 아니며 bank transition seam/repetition이 생길 수 있다.
- 재검토: blind naturalness, RTF, seam, repetition detectability가 gate를 실패하거나 Ditto가 우위일 때.

## ADR-006 — Ditto control hook을 첫 연구 spike로 사용

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: vendor의 `delta_pitch/yaw/roll/exp`를 공통 behavior protocol에 연결한다.
- 이유: 새 model 학습 없이 실제 frame-wise pose/nod 가능성을 검증하는 가장 직접적인 로컬 지점이다.
- 선행 조건: compose path, corrupt patch, vendor diff 재현; clean benchmark.
- 승격 조건: control adherence, lip/identity, RTF, cancel SLO를 모두 통과.

## ADR-007 — 최신 연구는 R&D lane에 격리

- 날짜: 2026-08-25
- 상태: Accepted
- 대상: Avatar Forcing, EmpaAva, PersonaLive, StreamAvatar, FLOAT, Alibaba LiveAvatar 등.
- 이유: non-commercial/research-only license, code/weight 미공개, realtime app 부재, H100/H200/multi-GPU 요구 중 하나 이상이 있다.
- 결과: architecture 아이디어와 benchmark로 쓰되 제품 build에 직접 넣지 않는다.

## ADR-008 — 학습 전 telemetry/evaluation/data rights

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: Tier 0 trace와 고정 eval을 먼저 만들고 동의가 확인된 calibration/dyadic data만 수집한다.
- 이유: failure target과 권리가 없으면 학습량이 늘어도 제품 문제를 해결했다는 증거가 없다.
- 결과: 기존 WAV/업로드를 자동 학습 자료로 쓰지 않는다.

## ADR-009 — 감정은 사실이 아닌 불확실한 신호

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: sensitive psychological inference를 금지하고 explicit user statement/context가 camera/audio proxy보다 우선한다.
- 이유: 정확도·윤리·privacy 문제와 “슬픈 말에 웃음” 같은 직접 매핑 오류를 줄인다.
- 결과: low confidence는 neutral attentive로 decay하며, 진단/성격 프로필을 저장하지 않는다.

## ADR-010 — build-vs-buy 분기별 재계산

- 날짜: 2026-08-25
- 상태: Accepted
- 결정: 자체 renderer와 Tavus/HeyGen/PERSO 등의 실제 invoice, concurrency, 품질, control gap을 분기마다 비교한다.
- 이유: API 단가는 빠르게 변하고 자체 hosting 원가는 utilization에 좌우된다.
- 결과: sunk cost보다 현재 요구와 실측을 우선한다.

## 새 결정 작성 양식

```markdown
## ADR-NNN — 제목

- 날짜:
- 상태: Proposed / Accepted / Rejected / Superseded
- 맥락:
- 결정:
- 이유:
- 검토한 대안:
- 결과/위험:
- 재검토 trigger:
- 근거 문서/benchmark ID:
```
