# Empathic Generative Avatar R&D 설계 문서

기준일: **2026-08-25**  
대상 저장소: `EmpathicGenAvatar`

## 한 문장 결론

지금은 거대한 end-to-end 비디오 모델을 새로 학습할 때가 아니다. 먼저 **사용자 관찰 → 대화 상태 → 타임스탬프가 있는 행동 명령 → 교체 가능한 렌더러**를 분리하고, 현재의 MuseTalk + LivePortrait 경로와 Ditto의 제어 지점을 이용해 측정 가능한 실시간 제품을 만드는 것이 최단 경로다.

이 프로젝트의 장기적인 차별점은 특정 립싱크 모델이 아니라 다음 자산에 있다.

1. 사용자의 말하기·시선·고개·표정 신호를 과장 없이 해석하는 `Perception State`
2. 문맥과 턴 상태를 얼굴·머리·시선·nod의 시간축으로 바꾸는 `Behavior Policy`
3. 어떤 렌더러에도 같은 명령을 보낼 수 있는 `Behavior Control Protocol`
4. 실제 대화에서 “자연스럽고 상황에 맞는 반응”을 판단하는 동기화 데이터와 평가셋

## 권고안 요약

| 기간 | 제품 경로 | 연구 경로 | 통과 조건 |
|---|---|---|---|
| 0–6주 | LiveKit/WebRTC + 스트리밍 STT/LLM/TTS + MuseTalk mouth-last + 제어 가능한 LivePortrait motion bank | Ditto의 `ctrl_info`/`motion_stitch` 연결 실험 | barge-in, A/V sync, 24fps, 표정 모순률을 실측 |
| 6–12주 | 행동 버스·카메라 파생 feature·상태기계 고도화, 렌더러 A/B | Ditto 통합 제어, PersonaLive/Avatar Forcing 재현성 조사 | 고정 테스트셋에서 현재 베이스라인을 유의하게 개선 |
| 3–9개월 | 검증된 렌더러를 서비스 풀로 운영 | nod/시선/표정 정책 및 motion adapter 학습 | identity/session 분리 평가와 사용자 선호도 통과 |
| 9개월 이후 | 비용·품질에 따라 자체 renderer adapter 또는 distillation | streaming generative video 학습 | 데이터 권리·GPU 예산·품질 우위가 모두 증명된 경우만 진행 |

## 문서 지도

### 01. 구현 설계

- [단기 구현 설계](01-architecture/NEAR_TERM_IMPLEMENTATION.md): 현재 코드 진단, 목표 아키텍처, 단계별 변경안, 6주 실행 계획
- [저지연 라이브 구현 설계](01-architecture/LOW_LATENCY_LIVE_IMPLEMENTATION.md): Ditto 품질 모드와 fast renderer, WebRTC 전환의 구현 직전 계약·순서·통과 기준
- [행동 제어 프로토콜](01-architecture/BEHAVIOR_CONTROL_PROTOCOL.md): 표정·머리·시선·blink·nod의 공통 시간축 계약

### 02. 기술·비용 비교

- [기술 비교표](02-landscape/TECHNOLOGY_COMPARISON.md): 상용/오픈소스/연구 기술의 기능, 라이선스, HW, 실시간성, 통제 가능성
- [비용·용량 모델](02-landscape/COST_AND_CAPACITY.md): API token 비용, 상용 분당 가격, GPU 원가와 동시성 산식

### 03. 데이터·학습·검증

- [데이터·학습 로드맵](03-roadmap/DATA_AND_TRAINING_ROADMAP.md): 무엇을 언제 수집하고 어떤 순서로 학습할지, 권리·보존·삭제 원칙
- [평가·벤치마크 계획](03-roadmap/EVALUATION_AND_BENCHMARK.md): latency, lip-sync, control adherence, 상황 일치성, uncanny 평가

### 04. 지속 관리

- [리서치 유지관리](04-operations/RESEARCH_MAINTENANCE.md): 주간/월간/분기 업데이트 절차와 근거 등급
- [기술 레지스트리](04-operations/TECHNOLOGY_REGISTRY.csv): 비교 대상의 기계 판독 가능한 최신 스냅샷
- [의사결정 기록](04-operations/DECISION_LOG.md): 선택·가정·재검토 조건을 남기는 ADR-lite 로그

## 지금 하지 않을 것

- 카메라 영상에서 사용자의 심리 상태, 성격, 질병 같은 민감한 속성을 단정하지 않는다.
- “감정 인식” 점수 하나를 그대로 아바타 표정에 매핑하지 않는다.
- MJPEG와 완성 WAV 경로 위에 기능을 계속 덧붙이지 않는다.
- 논문 데모의 FPS나 상용사의 홍보 문구를 로컬 서비스 SLO로 간주하지 않는다.
- 비상업 라이선스 모델을 제품 기본 경로에 넣지 않는다.
- 동의·철회·삭제 계보가 없는 대화 영상을 학습 데이터로 축적하지 않는다.

## 문서의 사실 표기 규칙

- **[L] Local**: 이 저장소 또는 사내 장비에서 직접 확인한 사실
- **[O] Official**: 공식 문서·공식 저장소·공식 가격표
- **[P] Paper**: 논문 저자가 보고한 결과로, 로컬 재현 전
- **[V] Vendor claim**: 공급사 주장으로 독립 검증 전
- **[H] Hypothesis**: 설계 가설 또는 계획 수치

가격·모델·라이선스는 변한다. 각 문서의 `마지막 확인` 날짜와 [기술 레지스트리](04-operations/TECHNOLOGY_REGISTRY.csv)를 함께 갱신해야 한다.
