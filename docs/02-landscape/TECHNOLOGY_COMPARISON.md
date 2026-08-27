# 실시간 empathic avatar 기술 비교

마지막 확인: **2026-08-25**  
범위: 첨부 조사 자료의 후보 + 공식 paper/repo/docs로 확장한 상용·오픈소스·연구 기술

## 1. 결론부터

2026-08-25 공개 상태 기준, 다음을 동시에 만족하는 단일 상용 가능 오픈소스는 확인되지 않았다.

- 실시간 립싱크
- 표정 강도와 시간축의 직접 제어
- head yaw/pitch/roll 직접 제어
- gaze target 직접 제어
- listening 중 즉시 nod/backchannel
- user camera/audio에 반응하는 dyadic motion
- 상업 사용 가능한 code/weights/dependencies
- 1대의 현실적인 GPU에서 25fps 이상

따라서 현재 선택은 “최고 모델 하나”가 아니라 역할 분리다.

| 역할 | 1순위 | 2순위/연구 | 이유 |
|---|---|---|---|
| realtime media/turn | LiveKit + VAD | Pipecat/별도 stack | full-duplex, interruption, WebRTC |
| browser perception | MediaPipe Face Landmarker | 연구용 OpenFace | on-device, low-level feature |
| 발화 렌더러 | Ditto controlled spike | MuseTalk mouth-last | Ditto 내부 pose/expression hook; MuseTalk는 검증된 lip bridge |
| 직접 motion bridge | LivePortrait primitive/control | ARTalk/FLAME teacher | head/expression/eye retargeting과 빠른 frame render |
| listener/nod 정책 | deterministic v0 → 자체 lightweight model | Avatar Forcing/MaAI 연구 참고 | 공개 상용 가능한 완성 dyadic renderer 부재 |
| 미래 lip 교체 | Lip Forcing 1.3B 공개 추적 | 14B research benchmark | 1.3B만 논문상 H100 realtime, 아직 weight 미공개 |
| 장기 north star | StreamAvatar/Avatar Forcing/VASA-1 | Alibaba LiveAvatar | control/dyadic/streaming 방향은 강하지만 공개·자원 제약 |

## 2. 읽는 법

### control 표기

- **D**: numeric/event 형태의 직접 control이 공개 interface/code에 있음
- **I**: driving video, latent/code modification으로 간접 제어
- **A**: 모델이 자율 생성하나 특정 시점/값을 직접 지정할 수 없음
- **—**: 해당 기능의 공개 근거 없음
- **?**: 공급사 설명은 있으나 interface/조건이 불명확

`논문에서 움직인다`와 `제품 API에서 frame별로 지시할 수 있다`는 다르다.

### 성능 표기

- paper/vendor/local 수치를 구분한다.
- 출력 video가 25fps인 것과 25fps보다 빠르게 생성하는 것은 다르다.
- precomputed audio feature, model forward-only, multi-GPU 수치는 E2E service latency가 아니다.
- 공식 VRAM이 없으면 추정하지 않고 `미공개/실측 필요`로 둔다.

## 3. 직접 비교 상용 서비스

| 기술 | 유형·입력 | user perception | 공개 control surface | realtime/HW 공개 근거 | 현재 판단 |
|---|---|---|---|---|---|
| [Tavus CVI/PAL](https://docs.tavus.io/sections/conversational-video-interface/conversation/overview) | hosted generative conversational video | Raven이 audio/visual user state를 분석한다고 설명 [V] | emotion category/tag와 prompt control [O]; frame-level head/gaze/nod trajectory API는 확인되지 않음 | Phoenix가 live 40fps라고 공급사 설명 [V]; HW 비공개 | full-stack UX/latency 기준선. “슬픈 말에 약한 미소” 관찰은 제품 eval 가설로 관리 |
| [HeyGen LiveAvatar](https://help.heygen.com/en/articles/12758866-liveavatar-faq) | hosted Full/Lite live avatar | Full mode built-in agent; Lite는 외부 agent 연결 | 공식 FAQ가 live stream 중 gesture를 동적으로 제어할 수 없다고 명시 [O] | resolution/session/concurrency plan 공개; 내부 HW/FPS 비공개 | 빠른 buy baseline이지만 핵심 frame-level control과 구조적 gap |
| [PERSO Interactive](https://estsoft.ai/en/perso-interactive) | hosted generative AI human | Station/VLM은 vision interaction 주장 [V]; Cloud WebSDK는 camera 권한이 필요 없다고 명시 [O] | 자연 gesture/expression 주장 [V]; public pose/gaze/nod API 미확인 | Station <0.5s 주장 [V]; WebSDK FPS, latency, HW, concurrency 미공개 | WebSDK와 Station을 분리해 한국어·국내 사업 비교 |
| [D-ID V4 Visual Agents](https://www.d-id.com/v4-expressive-visual-avatars-tech-specs/) | hosted diffusion visual agent | optional Eyesight가 user frame/gesture/object/context를 분석 [V] | sentiment/EQ 기반 자세·표정 자동 변화; numeric head/gaze/nod API 미공개 | E2E <500ms, core <120ms, 내부 diffusion 200+fps 주장 [V]; 실제 stream fps 미공개 | Tavus와 함께 camera-aware closed-loop benchmark |
| [Beyond Presence](https://www.beyondpresence.ai/help-center) | hosted S2V 또는 managed agent | managed tier optional webcam perception [V] | head/expression 자동, Scale 이상 controllable emotion; gaze/nod numeric API 없음 | 1080p 35fps; foundation/S2V/managed가 각각 약 100/250/1000–1200ms 주장 [V] | 모듈·가격 경쟁력, latency 시작점 분리 검증 |
| [Anam Cara-4](https://anam.ai/blog/meet-our-most-expressive-model-yet-cara-4) | hosted customizable avatar | native camera 미수신; 외부 MediaPipe/vision 필요 [O] | Director Notes의 emotion prompt/expressivity/turn 내 shift [V]; kinematic API 없음 | 25fps, avatar generation 약 150ms, user EOT→first frame median <1s 주장 [V] | 외부 perception+자체 policy 조합의 저비용 buy baseline |
| [NVIDIA ACE Audio2Face-3D](https://developer.nvidia.com/ace) | 3D blendshape/animation microservice | 별도 vision 필요 | emotion weights와 animation graph의 nod/head-shake event [O] | animation 30fps; 공식 예시 평균 약 42ms [O] | gen-video는 아니지만 explicit event control·capacity 기준선 |
| [KLEVER ONE](https://www.metabuild.co.kr/klever/one) | 3D/kinematic digital human | dialogue/perception integration | 3D expression/gesture/motion SDK 계열 [V] | 공개 상세 수치·가격 미확인 | generative video 직접 경쟁이 아니라 명시적 control의 UX 기준선 |

상용 서비스는 STT/LLM/TTS/WebRTC를 포함하는지에 따라 renderer 단독과 비교할 수 없다. [비용·용량 모델](COST_AND_CAPACITY.md)과 [평가 계획](../03-roadmap/EVALUATION_AND_BENCHMARK.md)에서 `full stack`과 `renderer` lane을 분리한다.

### Tavus에 대한 해석

[Tavus emotion control 공식 문서](https://docs.tavus.io/sections/conversational-video-interface/quickstart/emotional-expression)는 neutral, angry, excited, elated, content, sad, dejected, scared, contempt, disgusted, surprised 등 category를 prompt/Echo tag로 유도한다 [O]. 이것은 `t=3.7s에 pitch 5° nod`, `gaze x=-0.2` 같은 kinematic contract가 아니다.

따라서 사용자 관찰인 “실시간성과 lip-sync는 좋지만 상황 반대 표정이 나온다”는 다음 세 failure로 나눠 평가한다.

1. perception이 사용자 상태를 잘못 추정
2. conversation planner가 잘못된 emotion tag 선택
3. renderer가 tag를 시각적으로 약하거나 반대로 표현

공급사 demo 인상만으로 원인을 단정하지 않고 동일 negative-context test에서 event trace와 human rating을 모은다.

### HeyGen에 대한 해석

[LiveAvatar FAQ](https://help.heygen.com/en/articles/12758866-liveavatar-faq)는 gesture와 appearance가 training input video에 기반하며 live stream 중 gesture를 dynamic control할 수 없다고 명시한다 [O]. 따라서 품질이 좋아도 본 프로젝트의 “임의 frame의 head/gaze/nod” 요구에는 API 수준 gap이 있다.

### PERSO에 대한 해석

[공식 제품 페이지](https://estsoft.ai/en/perso-interactive)는 realtime communication, visual-language interaction, natural facial expression/gesture를 주장한다 [V]. 다만 [Cloud WebSDK 설치 문서](https://perso-platform.readme.io/docs/installing-web-sdk)는 camera 권한이 필요 없다고 명시하므로 Station/VLM의 perception을 동일 제품 기능으로 간주하면 안 된다 [O]. 공개 자료만으로 숫자 control, latency distribution, GPU, 동시성, cancellation을 확인할 수 없다. NDA/기술 미팅 질문은 다음과 같다.

- expression/head/gaze/nod를 timestamp 또는 event API로 외부 제어 가능한가
- user camera raw/feature의 처리·저장 위치와 retention
- Korean STT/TTS/LLM을 교체 가능한가
- E2E P50/P95, A/V skew, barge-in, max session, concurrency
- idle/listening/speaking billing과 최소 charge
- custom avatar training data와 파생 모델의 권리·삭제

## 4. 즉시 구현 가능한 오픈소스

### 핵심 기능 비교

| 기술 | Lip | expression | head pose | gaze | blink | nod/listen | 공개·라이선스 | 제품 판단 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|---|---|
| [Ditto](https://github.com/antgroup/ditto-talkinghead) | A | I/D* | D* | I/D* | I | I/D* | code/weights/training, Apache-2.0 | 발화+unified control 1순위 spike |
| [MuseTalk 1.5](https://github.com/TMElyralab/MuseTalk) | A | — | 입력 보존 | — | — | — | code/weights/training, MIT; deps 별도 | mouth-only product bridge/fallback |
| [LivePortrait](https://github.com/KlingAIResearch/LivePortrait) | driving | D/I | D/I | I | D | pitch로 D | code/weights, MIT; 기본 InsightFace model NC | motion primitive/control layer |
| [ARTalk](https://github.com/xg-chu/ARTalk) | A | D FLAME | D FLAME | — | A | pose로 I | core MIT; FLAME 별도 | 빠른 motion teacher/intermediate |
| [Real3D-Portrait](https://github.com/yerfor/Real3DPortrait) | A | I 3DMM | I/D | 제한 | A | I | MIT | offline 3D-aware 연구 후보 |
| [Lip Forcing](https://github.com/cvlab-kaist/LipForcing) | A | 입력 보존 | 입력 보존 | 입력 보존 | 입력 보존 | — | Apache-2.0; 1.3B weight 미공개 | 미래 MuseTalk 대체 watch |

`*` Ditto의 D는 현재 공식 고수준 product API가 아니라 공개/로컬 code의 motion control hook을 adapter로 노출할 때 가능하다는 뜻이다.

### 성능·자원 비교

| 기술 | 공식 측정 조건 | 공식 결과 | 빠진 조건 | 판정 |
|---|---|---|---|---|
| Ditto | 1×A100, 512² head, online | FFD 385ms, RTF 0.895; Audio2Feat 23ms, Motion DiT 62ms, render 15ms [P] | VRAM; RTX 5090 clean local; network/encode | realtime 가능성 높음, 로컬 gate 필요 |
| MuseTalk 1.5 | Tesla V100, 256² face region | 30fps+ 주장, realtime output 25fps [O] | E2E/VRAM | 현재 로컬은 약 21.4fps 흔적 [L], 최적화 필요 |
| LivePortrait | RTX 4090, PyTorch, 512² | 12.8ms/frame [P] | source prep/face detector/pasteback/encode/VRAM | motion layer로 충분히 가벼움 |
| ARTalk | 1×A100 | 1초 motion 생성 0.01초; 학습 13 GPU-hour [P] | final renderer/TTFF/VRAM | motion generator/teacher에 적합 |
| Lip Forcing 1.3B | 1×H100, 512² | 31.58fps, memory 8.78GB allocated, TTFF 0.32ms [P] | weight 현재 미공개; TTFF 범위 제한 | 공개 전 제품 사용 불가 |
| Lip Forcing 14B | 1×H100, 512² | 15.11fps, 40.63GB allocated [P] | E2E | 현재 공개 weight는 realtime 미달 |

Lip Forcing의 paper TTFF는 camera-to-display가 아니며 preprocessing/audio buffering/network를 포함한다고 볼 근거가 없다. paper의 1.3B와 현재 다운로드 가능한 14B를 혼동하지 않는다.

### Ditto

[공식 paper](https://arxiv.org/abs/2411.19509)와 [repo](https://github.com/antgroup/ditto-talkinghead)는 motion-space diffusion, online path와 Apache-2.0 code/weights/training을 제공한다 [O/P]. 논문은 pose, gaze, emotion, eye/mouth editing을 보이지만 high-level semantic control API는 아니다.

로컬 vendor code에는 frame별 `delta_pitch/yaw/roll`과 `delta_exp`, eye/head 보정 지점이 확인됐다 [L]. 현재 worker가 전달하지 않는 이 `ctrl_info`가 가장 가치 있는 단기 통합 지점이다. 다만 공개 code는 A100/Python 3.10/TensorRT 8.6.1을 테스트 환경으로 제시하고 현재 RTX 5090 경로는 clean benchmark가 없다.

### MuseTalk

[MuseTalk 공식 repo](https://github.com/TMElyralab/MuseTalk)는 audio-conditioned latent inpainting으로 256×256 얼굴의 입 영역을 바꾼다 [O]. pose, gaze, blink, nod를 생성/제어하지 않는다. 현재 저장소의 LivePortrait base sequence와 결합하면 빠른 bridge가 되지만 두 모델 경계의 seam/jitter와 전체-frame copy/JPEG 비용을 실측해야 한다.

### LivePortrait

[LivePortrait paper](https://arxiv.org/abs/2407.03168)와 [repo](https://github.com/KlingAIResearch/LivePortrait)는 implicit keypoint, stitching/retargeting, regional/precise editing을 제공한다 [O/P]. audio-driven conversation model은 아니지만 직접 head/expression/eye primitive를 만들기에 가장 유용하다.

중요한 license trap: core code는 MIT지만 공식 [LICENSE](https://github.com/KlingAIResearch/LivePortrait/blob/main/LICENSE)는 bundled InsightFace detection model의 non-commercial 조건을 구분한다. 제품에서는 detector를 상업 사용 가능한 대안으로 교체하고 weights/dependencies manifest를 감사한다.

### ARTalk/FLAME

[ARTalk](https://github.com/xg-chu/ARTalk)은 audio와 2초 style reference에서 frame-wise FLAME expression/global/base/jaw pose를 생성한다 [O/P]. final photoreal renderer가 아니라 motion intermediate다. `FLAME/ARKit-like canonical control → renderer adapter`의 teacher와 synthetic control trajectory 생성에 가치가 있다. FLAME asset/license는 core MIT와 별도다.

## 5. 사용자 인식·turn-taking 구성요소

| 기술 | 출력 | 공식 license/상태 | 역할과 주의 |
|---|---|---|---|
| [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker) | 3D landmark, blendshape, face transform | Apache-2.0 [O] | browser on-device pose/blink/coarse gaze; 감정 단정 금지 |
| [Silero VAD](https://github.com/snakers4/silero-vad) | speech probability/event | MIT, 약 2MB [O] | interruption/turn signal; 한국어 실제 소음에서 threshold 튜닝 |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | word timestamp/ASR | MIT [O] | local STT; streaming wrapper와 EOT는 별도 |
| [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) | ASR/language/audio event/speech emotion | official repo; 한국어 포함 [O] | 보조 acoustic hypothesis, 표정 직접 입력 금지 |
| [emotion2vec](https://github.com/ddlBoJack/emotion2vec) | utterance emotion embedding/class | official repo/paper [O/P] | 장기 affect trend 연구; frame 즉시 명령에 부적합 |
| [OpenFace](https://github.com/TadasBaltrusaitis/OpenFace) | gaze/head/AU/landmark | 연구 사용 중심; 상업 별도 확인 | offline annotation/eval, 제품 기본 dependency 아님 |
| [MaAI](https://github.com/MaAI-Kyoto/MaAI) | turn-taking/backchannel/nod timing 계열 | MIT, CPU 지향 [O/P] | behavior policy 후보; 한국어/최신 model 공개 범위 실측 필요 |

perception fusion의 올바른 방향:

```text
observable camera/audio features + confidence + expiry
    → user-state hypothesis
    → transcript/context/turn policy
    → avatar intent
    → bounded behavior timeline
```

`user smile → avatar smile` 직접 복사는 피한다.

## 6. 장기 연구·north-star 비교

| 기술 | 공개/권리 | 직접 관련성 | 공식 자원·속도 | 제품 blocker |
|---|---|---|---|---|
| [Avatar Forcing](https://github.com/TaekyungKi/AvatarForcing) | checkpoint/minimal inference, CC BY-NC 4.0 | user audio+motion에 반응하는 speaking/listening, nod/laughter [P] | 1×H100, 10 NFE, 0.5s motion generation; audio feature pre-extracted [P] | NC; realtime app/acceleration 미공개 |
| [EmpaAva](https://github.com/1114531938/EmpaAva_System) | authored Apache-2.0이나 full stack NC/research deps | perception→response→FLAME/Gaussian 3D 구조 | H200 warm turn 평균 45.8s, render/export 41.5s; 약 140GB [O/P] | 실시간 아님; full renderer 상업 라이선스 불가 |
| [FLOAT](https://github.com/deepbrainai-research/float) | inference/weight, non-commercial; LICENSE 표기 불일치 | 7 emotion/intensity, pose latent 편집 | 1×V100, NFE10 논문 41.37fps; clip window [P] | NC, clip/noncausal, gaze/nod API 없음 |
| [PersonaLive](https://github.com/GVCLab/PersonaLive) | repo Apache 표기+academic-only disclaimer | live driving video→head/expression generative portrait | 1×H100 15.82fps; TinyVAE 20fps; 12GB long stream [P] | 25fps 미달, audio-driven 아님, 상업 확인 |
| [StreamAvatar](https://streamavatar.github.io/) | paper/project, code 없음 | talking/listening audio stream | 1×H20 25fps, first output 1.20s [P] | 구현/weight/license 없음 |
| [Alibaba LiveAvatar](https://github.com/Alibaba-Quark/LiveAvatar) | Apache-2.0 | long streaming audio→avatar | 14B, realtime TPP 5×80GB+; multi-H800 45fps; FP8 48GB path [O/P] | GPU 비용, training/integrated UI 미완 |
| [VASA-1](https://www.microsoft.com/en-us/research/project/vasa-1/) | paper/demo only | direct gaze vector, head distance, emotion offset | RTX 4090에서 paper 40fps online, preceding latency 170ms [P] | code/weight/API 없음 |
| [GaussianTalker](https://github.com/cvlab-kaist/GaussianTalker) | Gaussian license research-only | identity-specific audio+pose 3DGS | paper 98fps, training 1.5h [P] | person-specific capture, non-commercial |
| [HunyuanVideo-Avatar](https://github.com/Tencent-Hunyuan/HunyuanVideo-Avatar) | community license | high-quality offline image+audio+emotion reference | 24GB minimum/96GB recommended, offline [O] | 공식 Territory가 대한민국을 제외 — 한국 사용 후보 제외 |

### Avatar Forcing

[CVPR 2026 공식 공개 paper](https://openaccess.thecvf.com/content/CVPR2026/papers/Ki_Avatar_Forcing_Real-Time_Interactive_Head_Avatar_Generation_for_Natural_Conversation_CVPR_2026_paper.pdf)는 사용자의 audio와 motion을 avatar audio와 함께 condition해 자연스러운 nod/laughter/reaction을 생성하는 방향으로, 본 프로젝트의 장기 목표와 가장 가깝다 [P]. 그러나 공식 repo는 prerecorded input을 쓰는 최소 offline PyTorch inference이며 논문의 realtime application/acceleration 전체가 아니다 [O]. CC BY-NC라 제품 code로 사용할 수 없다.

권고: architecture/평가 기준으로 삼고, 자사 동의 기반 한국어 dyadic data로 listener policy를 별도로 학습한다.

### EmpaAva

[EmpaAva paper](https://arxiv.org/abs/2608.04709)는 Perception/Response/Render agent와 FLAME/Gaussian 3D pipeline으로 개념 구조가 매우 유사하다 [P]. 하지만 공식 측정에서 H200 warm turn 평균 45.8초 중 Gaussian render/export가 41.5초다. 공식 repo의 `mock` mode는 UI/API smoke이지 실제 renderer가 아니다 [O]. 사용자가 demo를 현재 prototype과 유사하게 느낀 것은 단순 인상이 아니라 공개 latency/renderer 구조와도 일치한다.

또한 GaussianAvatars/VHAP, Gaussian Splatting, ImageBind 등 full stack에 non-commercial/research-only dependency가 있어 architecture reference로만 사용한다.

### KAIST Lip Forcing

[Lip Forcing paper](https://arxiv.org/abs/2606.11180)는 streaming lower-face inpainting의 최신 후보다 [P]. Apache-2.0 code/training은 긍정적이지만 2026-08-25 현재 공식 repo에서 바로 쓸 수 있는 weight는 14B이고 논문상 15.11fps다. realtime 31.58fps의 1.3B weight는 roadmap상 coming soon이다 [O/P]. 공개 즉시 동일 input으로 MuseTalk A/B를 예약한다.

## 7. 직접 control 요구 적합도

| 후보 | frame-level head | frame-level gaze | timed nod | expression intensity | user-reactive listener | commercial path |
|---|---:|---:|---:|---:|---:|---:|
| Tavus | 0 | 0 | 0 | 2 category/tag | 2 autonomous | 3 hosted |
| HeyGen LiveAvatar | 0 | 0 | 0 | 1 training/autonomous | 1 autonomous | 3 hosted |
| PERSO | ? | ? | ? | ? | 2 claim | 3 hosted |
| D-ID V4 | 0 | 0 | 0 | 2 autonomous | 2 optional Eyesight | 3 hosted |
| Beyond Presence | 0 | 0 | 0 | 2 tier-dependent | 2 managed | 3 hosted |
| Anam | 0 | 0 | 0 | 2 prompt | 0 native camera | 3 hosted |
| NVIDIA ACE | 2 event/graph | 1 | 3 event | 3 weights/state | 0 without policy | 2 3D/NIM license |
| Ditto adapted | 3 | 1–2 | 3 via pitch | 2 via safe basis | 0 without policy | 3 Apache path |
| LivePortrait bank/direct | 3 | 1–2 | 3 | 2–3 | 0 without policy | 2 detector replacement |
| MuseTalk | 0 | 0 | 0 | 0 | 0 | 3 MIT path |
| Avatar Forcing | 1 autonomous | 1 autonomous | 2 reactive | 2 reactive | 3 | 0 NC/offline repo |
| EmpaAva | 3 FLAME | 1 | 2 | 3 FLAME | 2 architecture | 0 full stack NC/slow |

점수: 0 없음, 1 간접/약함, 2 제한적, 3 요구에 가까움. `?`는 점수 대신 공급사 확인이 필요하다. 이 표는 영상 미학 품질 점수가 아니라 control surface 적합도다.

## 8. 채택/보류/제외

### 채택: 지금 구현

- MediaPipe derived perception
- LiveKit/turn/interruption
- 공통 behavior protocol
- LivePortrait named motion bank→MuseTalk mouth-last
- Ditto `ctrl_info` controlled spike
- rule-based nod/context guard

### 보류: 조건 충족 시 spike

- Lip Forcing 1.3B: weight 공개+commercial dependency audit
- ARTalk/FLAME: motion teacher mapping PoC
- MaAI: 한국어 timing/최신 nod model 재현
- PersonaLive: commercial clarification+25fps/consumer GPU 개선
- StreamAvatar: code/weights/license 공개
- Alibaba LiveAvatar: single practical GPU 또는 비용 하락

### 제품 제외, 연구 참고

- Avatar Forcing/FLOAT/GaussianTalker: non-commercial
- EmpaAva full renderer: non-commercial dependencies+realtime 실패
- VASA-1/EMO/OmniHuman: executable artifact 없음
- HunyuanVideo-Avatar: 대한민국 territory 제외

## 9. 정기 재평가 질문

모든 후보에 같은 질문을 한다.

1. code, weight, training, realtime app 중 실제 공개된 것은 무엇인가?
2. code/weight/dependency/driver asset이 한국에서 상업 사용 가능한가?
3. lip/head/gaze/expression/nod가 numeric/event API인가, driving video인가, 자율 생성인가?
4. listening 중 새 user cue를 몇 ms 뒤 output에 반영할 수 있는가?
5. FPS 수치에 audio encoder, VAE, composite, encode, network가 포함되는가?
6. 1 GPU에서 SLO를 지키는 concurrent session은 몇 개인가?
7. barge-in 시 stale audio/video를 실제로 중단할 수 있는가?
8. 30분 동안 identity/flicker/drift가 안정적인가?
9. 10분 세션 총원가와 최소 청구는 얼마인가?
10. 실패 시 neutral fallback과 데이터 삭제가 가능한가?

업데이트 절차는 [리서치 유지관리](../04-operations/RESEARCH_MAINTENANCE.md), 실측 방식은 [평가·벤치마크 계획](../03-roadmap/EVALUATION_AND_BENCHMARK.md)을 따른다.
