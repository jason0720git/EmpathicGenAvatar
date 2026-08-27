# 비용·용량 모델

마지막 확인: **2026-08-25**  
통화: 별도 표시가 없으면 USD, 세금·환율·egress·TURN·저장·지원 인력 제외

## 1. 비용을 세 층으로 분리한다

```text
대화 계층: STT + LLM + TTS
아바타 계층: motion + video render + encode
서비스 계층: WebRTC/TURN + egress + storage + observability + operations
```

- 오픈소스 MuseTalk/Ditto/LivePortrait 자체에는 `token 가격`이 없다. GPU-second와 운영비가 든다.
- Tavus/HeyGen Full/Anam Turnkey 같은 상품은 세 층 일부 또는 전부가 conversation minute에 포함된다.
- HeyGen Lite/Beyond S2V/자체 renderer는 STT·LLM·TTS 비용을 별도로 더한다.
- 상용사의 포함 minute와 자체 GPU active minute를 그대로 비교하면 idle, 최소 과금, concurrency를 놓친다.

## 2. 공통 변수와 산식

```text
M      = 월 delivered session-minute
P      = peak concurrent sessions
C      = 한 GPU가 SLO를 지키며 처리한 measured concurrent sessions
u      = 유료 GPU 시간 중 실제 render-capacity utilization (0..1)
G      = GPU hourly price
N_gpu  = ceil(P / C) × headroom

GPU cost per delivered minute = G / (60 × C × u)
monthly active GPU cost        = M × G / (60 × C × u)
monthly always-on floor        = N_gpu × 730 × G
```

`C`는 model batch size가 아니다. 동시에 [평가 계획](../03-roadmap/EVALUATION_AND_BENCHMARK.md)의 latency/fps/A/V gate를 통과한 room 수다.

현재 worker는 global lock으로 render concurrency가 1이고, RTX 5090 MuseTalk 실행 흔적의 RTF가 약 `14.67/12.475 ≈ 1.18`이다 [L]. 즉 현재 상태는 C=1조차 장시간 실시간 gate를 통과하지 않았으며, 아래 자체 hosting 숫자는 최적화 후의 planning sensitivity다.

## 3. 상용 realtime avatar 가격

### Tavus CVI

[공식 가격표](https://www.tavus.io/pricing) [O]

| plan | 월 가격 | 포함 conversation min | 포함분 실효 | 동시성 | 최대 세션 | overage |
|---|---:|---:|---:|---:|---:|---:|
| Free | $0 | 20 | — | 1 | 5분 | 없음 |
| Starter | $22 | 60 | $0.367/min | 1 | 5분 | 표시 상충, 계약 확인 |
| Builder | $59 | 175 | $0.337/min | 3 | 15분 | $0.35/min |
| Growth | $397 | 1,300 | $0.305/min | 10 | 제한 없음 | $0.31/min |
| Business | $975 | 4,000 | $0.244/min | 15 | 제한 없음 | $0.26/min |
| Enterprise | 견적 | 협의 | — | 협의 | 협의 | 협의 |

- 최초 30초 최소 과금, 이후 6초 단위 반올림.
- LLM, TTS, ASR, WebRTC가 conversation minute에 포함.
- Starter 카드의 pay-as-you-go 문구와 비교표의 overage 표시가 상충하므로 구매 전에 서면 확인.
- pricing page의 숨은 stale DOM에 과거 수치가 남을 수 있어 실제 화면과 plan comparison을 기준으로 확인했다.

### HeyGen LiveAvatar

[공식 시작·가격 안내](https://help.heygen.com/en/articles/10035615-how-to-get-started-with-liveavatar) [O]

| plan | 월 가격 | Full / Lite 포함분 | 동시성 | 최대 세션 | 해상도 |
|---|---:|---:|---:|---:|---|
| Free | $0 | 5 / 10분 | 1 | 2분 | 제한형 |
| Starter | $19 | 75 / 150분 | 5 | 5분 | 720p |
| Essential | $99 | 500 / 1,000분 | 20 | 20분 | custom 720p, public 1080p |
| Business | $475 | 2,500 / 5,000분 | 40 | 60분 | 720p/1080p |
| Enterprise | 견적 | 협의 | 협의 | 협의 | 협의 |

- credit overage는 $0.10.
- Full은 2 credits/min = $0.20/min. GPT-4o-mini, ElevenLabs Flash 2.5, Deepgram/AssemblyAI ASR를 포함하는 턴키 구성.
- Lite는 1 credit/min = $0.10/min. avatar rendering 중심 BYO 구성이라 voice stack을 별도 가산.
- 최소 과금/반올림 단위는 공개 문서에서 확인되지 않음.

### PERSO Interactive

[공식 가격표](https://platform.perso.ai/services/pricing/) [O]

- 모든 공개 pack이 `1 credit = $0.20`.
- Interactive는 `1 credit/min`, 즉 **$0.20/min**.
- credit 만료 없음.
- 동시성, 최대 세션, 반올림, FPS/해상도 미공개.
- STT/LLM/TTS가 완전히 포함되는지, customer API key provider의 pass-through가 있는지 계약 확인.

### D-ID V4 Streaming

[공식 API 가격표](https://www.d-id.com/pricing/api?from=studio_settings)의 연간 결제 표시 [O]

| plan | 표시 월 환산 | 연간 청구 | streaming 포함분 | 실효 단가 |
|---|---:|---:|---:|---:|
| Trial | $0 / 14일 | — | 10분 | — |
| Build | $14.40 | $172.80 | 32분 | $0.450/min |
| Launch | $35 | $420 | 90분 | $0.389/min |
| Scale | $138.60 | $1,663.20 | 400분 | $0.347/min |
| Enterprise | 견적 | 견적 | 협의 | — |

overage, 동시성, 최대 세션, 최소 과금은 미공개. Build는 개인/워터마크 조건이고 Launch/Scale부터 상업 사용 조건을 확인한다.

### Beyond Presence

[공식 가격표](https://www.beyondpresence.ai/pricing) [O]

| plan | 월 가격 | S2V / Managed 포함분 | 동시성 | S2V overage | Managed overage |
|---|---:|---:|---:|---:|---:|
| Free | €0 | 40 / 20분 | 1 | — | — |
| Starter | €49 | 280 / 140분 | 10 | €0.175 | €0.35 |
| Growth | €149 | 1,490 / 745분 | 25 | €0.10 | €0.20 |
| Scale | €349 | 4,000 / 2,000분 | 50 | €0.0875 | €0.175 |
| Enterprise | 견적 | 협의 | 협의 | 협의 | 협의 |

- S2V는 avatar video layer, Managed는 agent stack이다.
- Scale부터 controllable emotions를 표기한다.
- 정확한 시간 반올림은 미공개.

### Anam

[공식 가격표](https://anam.ai/pricing) [O]

| plan | 월 가격 | 포함분 | 동시성 | 최대 세션 | overage |
|---|---:|---:|---:|---:|---:|
| Free | $0 | 30 | 1 | 3분 | 없음 |
| Starter | $12 | 50 | 1 | 5분 | $0.16/min |
| Explorer | $49 | 250 | 3 | 10분 | $0.14/min |
| Growth | $299 | 2,000 | 5 | 2시간 | $0.12/min |
| Professional | $999 | 5,000 | 10 | 2시간 | $0.11/min |
| Enterprise | 견적 | 협의 | 협의 | 협의 | 협의 |

- 전체 session wall-clock을 초 단위로 과금.
- Turnkey는 STT/LLM/TTS/avatar 포함.
- BYO/custom TTS의 provider 비용은 별도.

### 공개 가격 없음/별도

- Synthesia Interactive Avatars: closed beta, realtime 가격·동시성 미공개.
- NVIDIA ACE/NIM: production NVIDIA AI Enterprise는 [공식 NIM 문서](https://docs.api.nvidia.com/nim/docs/run-anywhere) 기준 **$4,500/GPU/year부터**, GPU infra 별도 [O].
- KLEVER ONE: 공개 가격/동시성 미확인.

## 4. 월 10,000 session-minute 시나리오

가정: 포함분을 모두 사용, overage 공개값 적용. 세금·egress·storage·support 제외. 공급사별 동시성이 다르므로 단가만으로 capacity가 같다고 보면 안 된다.

| 구성 | 계산 | 월 비용 | 포함 범위/주의 |
|---|---|---:|---|
| Tavus Business | $975 + 6,000×$0.26 | **$2,535** | full stack, concurrency 15 |
| HeyGen Business Full | $475 + 15,000 credits×$0.10 | **$1,975** | full stack, concurrency 40 |
| HeyGen Business Lite | $475 + 5,000×$0.10 | **$975** | avatar only; BYO voice 추가 |
| D-ID | Scale 범위 초과 | **견적** | 공개 overage 없음 |
| Beyond S2V Scale | €349 + 6,000×€0.0875 | **€874** | STT/LLM/TTS 별도 |
| Beyond Managed Scale | €349 + 8,000×€0.175 | **€1,749** | provider 포함 범위 확인 |
| Anam Growth | $299 + 8,000×$0.12 | **$1,259** | turnkey, concurrency 5 |
| Anam Professional | $999 + 5,000×$0.11 | **$1,549** | turnkey, concurrency 10 |
| PERSO | 10,000 credits | **$2,000** | pass-through/동시성 확인 |

### 10분 세션 직관값

최소 과금·plan 포함량을 무시한 marginal/effective 근사다.

| 서비스 | 10분 |
|---|---:|
| Tavus Growth 포함분/overage | 약 $3.05 / $3.10 |
| HeyGen Full / Lite | $2.00 / $1.00 + BYO voice |
| PERSO | $2.00 |
| Anam Growth overage | $1.20 |
| Beyond Managed Scale overage | €1.75 |
| Beyond S2V Scale overage | €0.875 + BYO voice |

Tavus는 10분 세션도 최초 30초, 이후 6초 단위 규칙을 적용한다. 사용자가 10초만 접속한 세션이 많으면 nominal $/min보다 비싸다.

## 5. STT·LLM·TTS token/audio 비용

공식 단가:

| 계층 | 모델 | 단가 |
|---|---|---:|
| STT | [gpt-live-transcribe](https://developers.openai.com/api/docs/models/gpt-live-transcribe) | $0.017/audio min [O] |
| STT | [gpt-transcribe](https://developers.openai.com/api/docs/models/gpt-transcribe) | $0.0045/audio min [O] |
| LLM | [GPT-5.6 Luna](https://developers.openai.com/api/docs/models/gpt-5.6-luna) | $0.20/M input, $0.02/M cached, $1.20/M output tokens [O] |
| LLM | [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) | $0.40/M input, $1.60/M output tokens [O] |
| TTS | [TTS-1](https://developers.openai.com/api/docs/models/tts-1) | $15/M characters [O] |
| TTS | TTS-1 HD | $30/M characters [O] |

산식:

```text
voice cost =
  user_audio_minutes × STT_rate
  + input_tokens / 1,000,000 × LLM_input_rate
  + output_tokens / 1,000,000 × LLM_output_rate
  + output_characters / 1,000,000 × TTS_character_rate
```

### 보수적 월 10,000 session-minute 예시 [H]

가정:

- STT가 세션 전체 10,000분을 처리 — VAD silence gating 전의 상한 성격
- 매 session-minute LLM input 2,000, output 500 tokens
- 매 session-minute TTS 900 characters
- GPT-5.6 Luna + TTS-1

| 항목 | live STT | non-live STT |
|---|---:|---:|
| STT | 10,000×$0.017 = $170 | 10,000×$0.0045 = $45 |
| LLM input | 20M×$0.20/M = $4 | $4 |
| LLM output | 5M×$1.20/M = $6 | $6 |
| TTS | 9M×$15/M = $135 | $135 |
| 합계 | **$315 = $0.0315/session-min** | **$190 = $0.019/session-min** |

실제 대화에서는 user speech ratio와 avatar speech ratio를 따로 넣어야 한다. VAD로 silence를 보내지 않고, context를 매 turn 무한 재전송하지 않으면 비용은 낮아진다. 반대로 긴 system prompt, RAG, tool output, premium voice를 쓰면 높아진다.

### 10분 세션 예시 [H]

가정: user speech 4분, output 4분×900 chars, aggregate LLM input 8,000 tokens/output 1,500 tokens.

```text
STT(gpt-transcribe) = 4 × 0.0045                         = $0.0180
LLM input           = 8,000 / 1M × 0.20               = $0.0016
LLM output          = 1,500 / 1M × 1.20               = $0.0018
TTS                 = 3,600 / 1M × 15                 = $0.0540
voice total                                               $0.0754
```

즉 이 가정에서 voice 계층은 약 **$0.0075/session-min**다. avatar GPU/서비스, WebRTC/TURN, 저장은 별도다.

## 6. 자체 GPU hosting

공식 on-demand/list 가격 [O]:

| 공급자·GPU | 시간당 | 730h 상시 | 10,000 active min, C=1·u=1 |
|---|---:|---:|---:|
| [AWS g5.xlarge, A10G 24GB](https://aws.amazon.com/ec2/instance-types/g5/) | $1.006 | $734.38 | $167.67 |
| [GCP g2-standard-4, L4 24GB](https://cloud.google.com/products/compute/pricing/accelerator-optimized) | $0.706832276 | $515.99 | $117.81 |
| [Lambda A10 24GB](https://lambda.ai/instances) | $1.29 | $941.70 | $215.00 |
| [RunPod L4 24GB](https://www.runpod.io/pricing) | $0.49 | $357.70 | $81.67 |
| RunPod A5000 24GB | $0.27 | $197.10 | $45.00 |
| RunPod serverless L4/A5000/3090 active | $0.69 | 사용량 기반 | $115.00 |

각 GPU에서 동일 model이 SLO를 지킨다는 뜻이 아니다. Ditto official A100, MuseTalk V100 수치를 L4/A5000 capacity로 대입하지 않고 직접 측정한다.

### utilization sensitivity: GCP L4 예시 [H]

| measured C | paid utilization u | renderer GPU $/delivered min | 10,000분 |
|---:|---:|---:|---:|
| 1 | 50% | $0.02356 | $235.61 |
| 1 | 70% | $0.01683 | $168.29 |
| 1 | 100% | $0.01178 | $117.81 |
| 2 | 70% | $0.00841 | $84.15 |
| 4 | 70% | $0.00421 | $42.07 |

10,000분이 한 달에 고르게 오지 않고 peak concurrency가 10이면 C=1 GPU 10대를 상시 준비해야 할 수 있다. 그러면 active-minute 계산이 아니라 `10×730×G`가 capacity floor가 된다. autoscaling cold start와 avatar cache warm-up을 측정해야 한다.

### 현재 프로젝트의 현실적 범위

- 현재 global lock: C≤1 [L].
- 현재 MuseTalk 로그 RTF≈1.18: audio보다 생성이 느려 실시간 gate 미통과 [L].
- RTX 5090은 로컬 자산이므로 현금 cloud GPU rate는 0처럼 보여도 감가, 전력, 장애, 개발 시간, 다른 연구 opportunity cost가 있다.
- 한 GPU에 STT/LLM/TTS/renderer를 모두 올리면 VRAM contention과 tail latency가 생긴다. 처음에는 media/agent CPU, renderer GPU, LLM/TTS local 또는 managed profile을 분리 측정한다.

## 7. 자체 hosting 10,000분 예시

다음은 견적이 아니라 sensitivity다.

가정:

- GCP L4 1대급 가격, renderer C=1, paid utilization 70%
- managed voice: 위 non-live STT 예시 $190/month
- egress/TURN/storage/ops 제외

```text
renderer GPU = $168.29
voice stack  = $190.00
subtotal     = $358.29 / 10,000 min
             = $0.0358/session-min
```

하지만 실제 peak 때문에 GPU를 1대 항상 켜면 renderer floor는 $515.99이고 subtotal은 **$705.99**, $0.0706/min다. C, u, peak, SLO가 없는 “오픈소스는 무료” 계산은 쓸 수 없다.

또한 이 자체 경로가 Tavus와 같은 visual perception/agent 품질을 자동으로 제공하는 것은 아니다. behavior policy와 제품 운영의 인건비가 별도다.

## 8. NVIDIA ACE 참고 원가

NVIDIA production license hourly equivalent:

```text
$4,500 / 8,760h ≈ $0.5137/GPU-hour
```

GCP L4와 합치면 약 $1.2205/GPU-hour다. [Audio2Face-3D 공식 성능표](https://docs.nvidia.com/ace/audio2face-3d-microservice/latest/text/interacting/performance.html)는 예시 L4 처리량으로 regression 30 streams, diffusion 16 streams를 제시한다 [O]. 완전히 채운 얼굴 animation inference만 계산하면:

```text
diffusion: $1.2205 / 60 / 16 ≈ $0.00127/session-min
regression: $1.2205 / 60 / 30 ≈ $0.00068/session-min
```

3D renderer, STT/LLM/TTS, WebRTC, GPU 분리 권고, idle, 운영은 빠진 이론적 하한이다. gen-video와 동일 품질 범주도 아니다.

## 9. buy/build 판단

### PoC와 고객 발견

- Tavus/HeyGen/D-ID/Anam/PERSO 중 2–3개로 빠르게 full-stack 품질·latency 기준선을 만든다.
- 핵심 frame-level control은 SaaS 공개 API가 거의 없으므로, 자체 behavior bus와 Ditto/LivePortrait 연구를 중단하지 않는다.
- 초기 사용량이 작고 불확실하면 고정 GPU/운영팀보다 hosted minute가 합리적일 수 있다.

### 자체 hosting이 유리해지는 조건

- 동일 renderer가 target GPU에서 RTF<0.9와 C≥1을 안정적으로 증명
- 월 사용량과 peak가 예측 가능하고 u가 50–70% 이상
- dynamic control이 매출/품질에 실제 기여
- privacy/ZDR/on-prem 요구가 hosted premium보다 큼
- GPU/ML/WebRTC on-call 비용을 감당

### SaaS가 유리한 조건

- 고객 검증 단계, 변동 사용량, 빠른 출시
- frame-level control보다 자연스러운 기본 품질이 중요
- multi-region/TURN/abuse/consent 운영을 내부에서 감당하기 어려움
- custom avatar 제작/운영의 총비용이 hosted plan보다 큼

### hybrid 권고

- hosted service를 quality/reliability fallback 또는 A/B 기준선으로 유지
- perception/behavior policy와 평가 데이터는 자체 소유
- renderer adapter를 교체 가능하게 유지
- sensitive/raw camera는 가능한 한 client-side 처리

## 10. 견적 요청 질문

공개 가격으로 답할 수 없는 항목:

- billing이 connection, audio, rendered frame 중 무엇을 기준으로 하는가
- idle/listening도 동일 과금인가
- 최초/최소/rounding과 failed/reconnected session 과금
- peak concurrency와 burst, region별 capacity
- 720p/1080p/4K, vision, recording 추가 비용
- custom avatar/voice 제작·재학습·삭제 비용
- BYO STT/LLM/TTS 시 credit 할인
- ZDR, data residency, SLA, support minimum
- input/output/model ownership과 service improvement license
- 카메라 frame retention 및 subprocessor
- emotion/head/gaze/nod custom control roadmap

## 11. 관리 규칙

- 가격은 30일마다 확인하고 source URL/screenshot/hash를 기록한다.
- 실제 invoice에서는 billed second/minute, rounding, abandoned session을 분리한다.
- 매월 `M`, `P`, `C`, `u`, P95 latency, incident hour를 함께 보고한다.
- plan 단가가 15% 변하거나 concurrency가 바뀌면 build-vs-buy ADR을 다시 연다.
- 구독 포함분의 실효 단가는 `plan price / 실제 사용분`도 보고한다. 포함분 100% 소진 가정만 쓰지 않는다.
