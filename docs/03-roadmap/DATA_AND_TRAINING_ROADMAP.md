# 데이터·학습 로드맵

마지막 확인: **2026-08-25**  
핵심 원칙: **관찰·제어·평가 데이터를 먼저 만들고, renderer 학습은 마지막에 결정한다.**

## 1. 무엇이 장기 자산인가

립싱크 데이터만 더 모아서는 Tavus/HeyGen과 다른 제품이 되기 어렵다. 이 프로젝트에 필요한 고유 데이터는 다음 연결을 포함한다.

```text
사용자 신호 + 대화 문맥 + 턴 상태
        ↓
언제, 왜, 얼마나 nod/gaze/expression을 했는가
        ↓
렌더러가 명령을 얼마나 정확히 보였는가
        ↓
사람이 그것을 자연스럽고 상황에 맞다고 느꼈는가
```

따라서 원본 영상의 양보다 **시간 동기화, 권리, 행동 명령, 결과 평가가 한 계보로 묶였는지**가 더 중요하다.

## 2. 현재 데이터의 취급

- 현재 저장소/실행 환경에 남은 WAV, 업로드 이미지, 로그는 자동으로 학습 데이터가 아니다.
- 기존 동의 문구가 제품 처리만 허용했다면 연구·학습으로 소급 사용하지 않는다.
- `consent_scope`, 목적, 보존 기간, 철회 방식이 확인되지 않은 파일은 `quarantine`으로 분류하고 학습 manifest에 넣지 않는다.
- 아바타 이미지의 사용 권리와 인물의 초상권, 음성의 복제 권리는 별도 필드로 관리한다.

## 3. 데이터 계층

### Tier 0 — 운영 telemetry: 지금부터

원본 카메라를 저장하지 않아도 수집할 수 있는 최소 데이터다.

| 그룹 | 저장 필드 | 기본 보존 |
|---|---|---|
| timing | VAD/EOT, STT partial/final, LLM/TTS 시작, frame PTS, browser paint | 30–90일 집계 후 원시 event 삭제 |
| perception | head/gaze/blink/smile proxy, confidence, quality flag | 세션 단위 파생 feature; opt-out 가능 |
| behavior | requested/applied control, reason code, confidence, override | 모델·정책 버전과 함께 보존 |
| renderer | fps, VRAM, queue, drop, A/V skew, failure | 운영 metric 장기 집계 |
| evaluation | thumbs up/down, 선택 이유, pairwise choice | 명시적 품질 개선 동의 필요 |

Tier 0의 목적은 먼저 실패를 attribution하는 것이다. 원본이 없더라도 `부적절한 웃음이 planner에서 나왔는지 renderer drift인지`를 구분할 수 있어야 한다.

### Tier 1 — 아바타 calibration capture

특정 avatar/identity를 안정적으로 제어하기 위한 동의 기반 자료다.

권고 capture script:

1. neutral 정면 30–60초, 자연 blink 포함
2. 한국어 음소·받침·모음 균형 문장 5–10분
3. yaw/pitch/roll grid: 작은 범위부터 ±10°, ±20°
4. gaze 3×3 grid, 고개 고정과 자연스러운 head-eye coordination 두 조건
5. blink single/double, slow blink
6. nod 1회/2회, 작은/중간 amplitude, 다양한 duration
7. 표정 primitive: neutral attentive, soft smile, concern, surprise low intensity, thinking
8. 듣기와 말하기를 각각 촬영

기술 조건:

- 최소 1080p 30fps; 빠른 blink/미세 timing 연구는 60fps도 병행
- 얼굴에 강한 shadow나 auto-exposure 변화가 없는 균일 조명
- 48kHz 분리 audio, capture timestamp와 frame timestamp 보존
- neutral pose/white balance/color chart calibration
- driver/target의 라이선스와 파생 모델 사용 범위를 asset manifest에 기록

### Tier 2 — 한국어 dyadic conversation corpus

nod와 backchannel은 혼자 말하는 영상으로 배울 수 없다. 두 사람이 실제로 상대방을 보고 듣는 동기화 데이터가 필요하다.

수집 장면:

- 일상 대화와 친근한 잡담
- 설명을 듣고 이해 신호를 주는 상황
- 질문-답, 동의/비동의, hesitation
- 발화권 경쟁, 중단, 재진입, 긴 pause
- 위로·불만·사과·나쁜 소식처럼 부적절한 미소가 위험한 문맥
- 농담·축하처럼 positive reaction이 자연스러운 문맥
- 카메라를 바라보는 remote-call 조건과 화면 밖 상대를 보는 조건

각 참여자에 독립 카메라와 근접 마이크를 두고 공통 clock으로 동기화한다. 가능하면 상대방 영상/음성도 원본 채널과 섞지 않고 보존한다.

계획 envelope **[H]**:

| 단계 | 규모 | 목적 | 다음 단계 gate |
|---|---:|---|---|
| pilot | 20명 × 2세션 × 20분 ≈ 13시간 | 프로토콜·동기화·동의·라벨 비용 검증 | 유효 frame ≥95%, A/V offset P95 <20ms |
| policy v1 | 60–100명, 80–150시간 | nod/backchannel/turn policy | held-out identity에서 rule baseline 초과 |
| adapter v1 | 100–300시간의 고품질 calibration+conversation | motion control/identity adapter | 제어·identity·human preference gate 통과 |
| end-to-end 후보 | 수백–수천 시간 여부를 pilot 뒤 산정 | streaming renderer | 비용 대비 상용/오픈 baseline 우위가 증명된 경우만 |

이는 quota가 아니라 측정 가능한 planning 범위다. pilot의 학습곡선과 라벨 분산을 본 뒤 확대한다.

### Tier 3 — counterfactual·preference 데이터

같은 음성과 얼굴에 행동만 바꾼 pair를 만든다.

- nod 없음 vs 적절한 nod vs 너무 잦은 nod
- neutral vs concern vs 부적절한 smile
- direct gaze vs 자연 gaze shift vs staring
- smooth head turn vs high-jerk motion
- 정확한 interruption vs stale lip 300ms

평가자는 다음 중 하나를 고르고 이유 태그를 붙인다.

- 더 자연스러움
- 문맥에 더 맞음
- 덜 기괴함
- 더 attentive해 보임
- identity가 더 안정적임
- 차이를 모르겠음

이 자료는 policy preference model, reward/ranker, regression test에 재사용할 수 있다.

## 4. 공통 schema

### session manifest

```yaml
session_id: sess_...
participant_ids: [p_..., p_...]
captured_at: 2026-08-25T09:00:00Z
locale: ko-KR
scenario_id: empathy_loss_v1
consent:
  product_processing: true
  research_storage: true
  model_training: false
  public_demo: false
  expires_at: 2027-08-25
assets:
  video_left: {sha256: ..., fps: 60, clock: room_001}
  audio_left: {sha256: ..., rate_hz: 48000, clock: room_001}
versions:
  capture_app: 0.3.1
  perception: mediapipe-...
  behavior_schema: behavior.v0.1
rights_record_id: rr_...
```

### frame/segment labels

| 계층 | 라벨 |
|---|---|
| media | frame PTS, audio sample index, drop/occlusion/blur |
| kinematic | yaw/pitch/roll, gaze x/y, blink, landmarks/blendshapes, confidence |
| speech | VAD, word, phoneme, F0, energy, pause, speaker |
| turn | start/end, hold/yield/take, interruption, overlap, backchannel |
| event | nod onset/peak/end, amplitude, repetitions; gaze shift; blink |
| context | dialogue act, empathy need, humor explicit, seriousness, uncertainty |
| quality | lip-sync, identity, flicker, control adherence, uncanny |
| provenance | extractor/annotator/version, confidence, correction history |

저수준 label과 해석 label을 분리한다. `browInnerUp=0.42`와 `sad`를 같은 사실처럼 저장하지 않는다.

## 5. annotation 설계

### 자동 pre-label

- face landmarks/blendshape/pose
- speaker diarization와 VAD
- word/phoneme alignment
- F0/energy/speaking rate
- nod event 후보와 gaze shift 후보
- 출력 영상의 lip/pose/control 측정

자동 label은 model version과 confidence를 반드시 포함하고 사람이 검수한 label을 덮어쓰지 않는다.

### 사람 annotation

다음은 최소 3인 다중 평가를 권고한다.

- 문맥-표정 적절성
- nod가 acknowledgment/agreement/불안/무관 중 무엇으로 보이는지
- uncanny/naturalness
- empathy/attentiveness perception
- 두 출력의 pairwise preference

평가자에게 `감정을 맞히라`고 하지 말고 관찰 가능한 문항을 묻는다.

- “이 반응은 앞선 발화와 어울리는가?”
- “nod의 시작이 너무 이르거나 늦었는가?”
- “웃는 표정이 부적절했는가?”
- “눈이나 머리가 비현실적으로 움직였는가?”

Krippendorff’s alpha 또는 Fleiss’ kappa로 합의도를 기록하고 낮은 항목은 label 정의를 고친다.

## 6. 학습 순서

### Stage 0 — 학습 없이 rule baseline

- deterministic turn state machine
- 문맥-표정 guard
- cooldown이 있는 nod 후보 규칙
- jerk-limited motion composer
- named primitive bank

모든 학습 모델은 이 baseline을 blind test에서 넘어야 한다.

### Stage 1 — backchannel/nod timing policy

입력:

- 최근 2–6초의 user VAD, prosody, pause, partial text embedding
- turn state와 user head/gaze 변화
- conversation context의 coarse dialogue act

출력:

- 다음 100–800ms의 backchannel/nod hazard
- nod type, amplitude, duration의 분포
- abstain confidence

목표는 작은 causal TCN/Transformer 등으로 CPU 또는 agent GPU의 작은 fraction에서 실시간 동작하는 것이다. renderer를 같이 학습하지 않는다.

### Stage 2 — behavior policy/ranker

- context와 perception에서 expression family/intensity/gaze strategy를 선택
- hard guard는 모델 밖에 유지
- counterfactual preference pair로 ranker 또는 constrained policy를 학습
- calibration error와 abstention을 평가

### Stage 3 — motion adapter

공통 control을 renderer의 control space로 바꾼다.

- Ditto: safe `delta_exp` basis와 pose residual
- LivePortrait: source keypoint/expression trajectory 또는 primitive interpolation
- 향후 model: control token/pose map/latent modulation

입력 control과 출력 영상에서 재추출한 motion 사이의 reconstruction/control loss를 사용한다. identity/temporal/lip-sync loss를 별도 추적해 한 지표가 다른 실패를 숨기지 않게 한다.

### Stage 4 — identity-specific adapter

일반 motion adapter가 통과한 뒤에만 LoRA/adapter 또는 avatar-specific calibration을 학습한다.

- 적은 데이터로 identity를 고정
- 전체 model weight에 한 사람을 과적합하지 않음
- 삭제 요청 시 해당 adapter와 training shard를 제거 가능
- adapter가 없을 때 generic renderer로 안전하게 fallback

### Stage 5 — streaming generative video 학습/증류

다음 조건이 모두 참일 때만 시작한다.

1. 공개/상용 baseline이 제품 SLO 또는 control 요구를 명확히 충족하지 못함
2. 100시간 이상 고품질 동기화 데이터에서 learning curve가 계속 개선됨
3. 데이터의 상업적 학습·파생물 권리가 정리됨
4. GPU-day와 serving 원가 예산이 승인됨
5. 자체 모델이 해결할 정확한 failure metric이 있음

“최신이어서” 또는 “논문 데모가 좋아 보여서” end-to-end 학습하지 않는다.

## 7. 데이터 split과 누수 방지

- train/validation/test를 frame이 아니라 **identity와 session** 단위로 분리한다.
- 대화 상대 pair가 train과 test에 걸치지 않도록 group split한다.
- 같은 원본에서 만든 crop, synthetic variation, compressed version은 같은 split에 둔다.
- avatar-specific adapter 평가는 calibration clip과 자유 대화 clip을 분리한다.
- prompt/scenario 문장도 paraphrase family 단위로 나눠 memorization을 막는다.
- 최종 test set은 versioned read-only로 두고 반복 튜닝에 사용하지 않는다.

## 8. 권리·개인정보·안전

### 동의 scope

각 항목을 별도 선택으로 받는다.

- 실시간 제품 처리
- 파생 feature와 telemetry 저장
- 원본 audio/video 연구 저장
- 모델 학습
- 내부 demo
- 외부 공개/논문
- 음성 복제
- 초상 기반 avatar 생성

철회는 미래 사용 중단만이 아니라 raw, crop, feature, embedding, adapter, checkpoint lineage를 찾아 삭제할 수 있어야 한다.

### 최소화와 보안

- raw capture와 운영 계정을 분리 저장
- participant pseudonym과 연락처 key 분리
- transit/at-rest encryption
- 역할 기반 접근과 audit log
- 얼굴/음성 embedding export 금지
- raw retention은 프로젝트별 명시; 무기한 기본값 금지
- 공개 benchmark에는 동의된 identity 또는 synthetic/stock asset만 포함

### 생성물 안전

- 사용자에게 AI avatar임을 명시
- 가능하면 invisible/visible watermark와 provenance metadata 적용
- 타인의 사진·음성 소유권 확인과 liveness/consent 절차
- 사칭, 협박, 성적 합성, 미성년자 대상 사용 금지
- 고위험 도메인에서는 아바타의 공감 표현이 전문가 판단처럼 보이지 않도록 고지

## 9. 데이터 계보와 도구

권고 구조:

```text
datasets/
  manifests/        # 권리·동의·hash·split; Git에는 비식별 metadata만
  schemas/          # JSON Schema / protobuf
  cards/            # dataset card
  annotations/      # versioned label refs
  pipelines/        # reproducible extraction configs
  evaluations/      # immutable test manifests
```

- 큰 object는 object storage, manifest는 DVC/lakeFS와 같은 versioned pointer 계층을 사용한다.
- extractor/model/container hash까지 기록한다.
- 수동 correction은 append-only event로 남긴다.
- checkpoint는 정확한 training manifest, code commit, seed, config를 참조한다.
- 권리 상태가 바뀌면 영향받는 dataset/model을 reverse lookup할 수 있어야 한다.

이 구조를 실제 저장소에 추가할 때 raw 데이터와 비밀키를 Git에 넣지 않는다.

## 10. 각 단계 go/no-go

| 단계 | Go | No-go / 되돌림 |
|---|---|---|
| Tier 0 logging | session의 ≥98%에 end-to-end trace 연결 | PII 과수집, clock 불일치 |
| dyadic pilot | 유효 sync ≥95%, 철회 rehearsal 성공 | 동의가 모호하거나 annotation 합의도 낮음 |
| nod policy | unseen identity에서 rule 대비 timing/preference 개선 | nod 빈도만 늘고 문맥 적절성 악화 |
| motion adapter | pose/gaze adherence 개선, lip/identity 비열화 | uncanny 또는 drift 증가 |
| identity adapter | 적은 데이터로 안정적, 완전 삭제 가능 | source 영상 memorization/leakage |
| end-to-end renderer | 품질·latency·원가 모두 baseline 우위 | 한 지표만 좋거나 상업 권리 불명확 |

세부 metric과 테스트 방법은 [평가·벤치마크 계획](EVALUATION_AND_BENCHMARK.md)에 정의한다.

## 11. 12개월 로드맵

| 시기 | 데이터 | 학습 | 산출물 |
|---|---|---|---|
| 0–1개월 | Tier 0 schema/trace, 기존 자료 권리 분류 | 없음 | 실패 attribution baseline |
| 1–3개월 | calibration capture + dyadic pilot | rule policy, control calibration | motion bank, Ditto control map |
| 3–6개월 | 80–150h 여부를 pilot로 결정, preference pair | nod/backchannel policy, behavior ranker | 한국어 listener behavior v1 |
| 6–9개월 | high-quality control/output pairs | renderer motion adapter, identity adapter | renderer-independent control v1 |
| 9–12개월 | learning curve와 권리 audit | 필요할 때만 distillation/streaming model spike | train/buy/partner 재결정 |

매 분기 [기술 비교표](../02-landscape/TECHNOLOGY_COMPARISON.md)를 다시 확인한다. 외부 모델이 같은 control과 SLO를 더 낮은 비용으로 제공하면 데이터 투자는 renderer 복제보다 behavior policy와 평가셋에 집중한다.
