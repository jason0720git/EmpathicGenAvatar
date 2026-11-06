# SOBIA 정책 검토와 Ditto 발화 중 제어 (2026-11-06)

## 검토 출처와 실제 상태

검토 대상은 로컬 `../SOBIA-Unity`의 HEAD `b6185bfed4114754e8a68c853f7fe4d39076dcba` 및 현재 미커밋 작업 파일이다. 원격 최신 상태나 Unity 실행·빌드 성공을 확인한 결과가 아니다. 이 저장소는 읽기만 했으며 기존 변경을 수정하지 않았다. 비교 기준은 이전 적용 때 읽었던 `de16a0d2`와 현재 EmpathicGenAvatar의 `3e45abc`다.

주요 SOBIA 경로의 공통 접두사는 `SharedPackages/com.etri.sobia/`다. 기존 EmpathicEmotion partial들은 현재 작업 트리에서 `Runtime/EmpathicBehavior/Expression/`으로 이동되어 있다. 기존 위치의 삭제와 새 위치의 미추적 파일을 함께 봐야 한다.

`Skills/unity-codex-workflow/references/default-face-policy-design-2026-11-06.md`는 여전히 구현 전 설계, async semantic classifier OFF, 발화 전 tool 계획을 서술한다. 하지만 실제 작업 파일과 씬은 다르다.

- `Expression/EmpathicEmotion.Trajectories.cs`가 존재하고 `Expression/EmpathicEmotion.cs`의 합성 경로가 이를 호출한다. 따라서 시간 궤적은 단순 제안 이름만 남은 상태가 아니다.
- `Runtime/Conversation/RealtimeManager.SemanticEmpathy.cs`의 현재 기본값은 async ON, `gpt-4.1-mini`, 적용 지연 상한 3초, 요청 timeout 3.2초다.
- `SOBIA-Unity-HDRP/Assets/SOBIA/Scenes/Default_HDRP.unity`도 `enableAsyncSemanticEmpathy: 1`, `forceEmpathicStateToolBeforeSpeech: 0`을 저장한다.
- `Runtime/EmpathicBehavior/Base/BaseExpression.cs`의 미커밋 변경은 기본 presence를 L과 분리한다. L0에서도 baseline을 유지하므로 오래된 문서의 “L0이면 모든 얼굴 출력 0”과 동일하지 않다.

이 기록은 설계의 의도, 현재 소스, 실제 검증 결과를 구분한다. 아래 수치는 프로젝트의 구현 설정이며 인간 움직임의 보편적 최적값을 뜻하지 않는다.

## 채택·유지·보류 판단

| 정책 | 근거와 판단 | Ditto 적용 |
| --- | --- | --- |
| 의미는 GPT, 로컬은 실행·제약 | `RealtimeExhibitionTurnRouter.cs`가 `합격` 등의 키워드로 긍정을 확정하던 분기를 제거했다. | 기존 단일 Realtime affect tool 계약 유지. 부정/인용/혼합 문맥을 로컬 키워드로 덮어쓰지 않는다. |
| 늦은 비동기 의미 결과 | 현재 SOBIA는 별도 async 분류를 활성화했다. 속도와 발화 중 표정 변경의 tradeoff가 있다. | 이번에는 복제하지 않는다. Ditto에 별도 의미 모델을 붙이는 대신 이미 정한 감정과 명시적 운영자 제어의 소유권을 분리한다. |
| 완만한 표정 진입·이완 | 신규 `EmpathicEmotion.Trajectories.cs`는 0/50/100ms 지역 지연, .28/.42/.55초 진입, .12 settle을 갖는다. `Companion.cs`는 같은 턴의 후보를 유지한다. | 시간 변화 원리를 채택한다. Ditto의 21개 implicit keypoint를 Unity의 눈썹·볼 등 해부학적 그룹으로 임의 대응시키지 않는다. |
| 채널별 반응 속도 | `EmpathicEyeContact.cs`는 눈 target을 머리보다 빠르게 평활화한다. | pupil·head·expression을 각각 평활화한다. 3D 카메라/월드 좌표 보정은 직접 이식하지 않는다. |
| 경청의 음성·쉼 기준 | `NoddingPolicy.cs`와 `EmpathicNodding.cs`는 기존 누적 유성·쉼·간격·실제 오디오 시작을 사용한다. 해당 노딩 파일은 `de16a0d2` 이후 비교에서 변경되지 않았다. | 기존 경청 정책 유지. 새 문서에 설명된 것만으로 새로운 타이밍 정책이 생겼다고 판단하지 않는다. |
| 응답 시작 제스처 | `PrepareResponse`는 eligible+nonempty text를 받으며 `HasReceiptOpening` helper로 제한하지 않는다. | 모든 응답 시작 노딩을 의미적 동의로 설명하거나 강제하지 않는다. 짧은 답변은 추가 동작이 없어도 된다. |
| 전사·입력 소유권 | 신규 `RealtimeInputOwnership.cs`는 재입력 중 이전 전사와 중복 ID를 거부한다. | 기존 voiceEpoch/visualEpoch 유지. 새 제어는 현재 turn WebSocket과 단조 증가 seq에 귀속한다. |
| 기본 인상과 감정 제약 | Unity L0 baseline 변경은 특정 리그의 baseline 계약이다. | Unity .8 baseline, 5~15도 노딩, 강한 지역 증폭을 복제하지 않는다. 기존 Ditto의 작은 움직임·립싱크·blink 보호를 유지한다. |
| 경청 미믹리 | `EmpathicFaceMimicry.cs`는 MicCaptureIntent와 agent speaking/preparing/interrupted 상태, 추적 대상 변경을 검사한다. | 소유권 원리는 타당하지만 이번 live 제어에 새 미믹리 입력을 섞지 않는다. 현재 제어 채널의 효과를 먼저 검증한다. |

## 이전 기능과 이번 기능의 차이

이전 UI의 발화 시선 선택은 **다음 턴**의 MotionPlan을 정했고, worker는 렌더링 시작 전에 control 배열을 만들었다. 경청은 마이크 음성을 기준으로 캐시된 짧은 영상을 재생했다. 이것만으로 이미 생성 중인 답변의 얼굴·머리·시선을 임의 시점에 바꿀 수 있다고 주장할 수는 없었다.

이번 제어는 기존 미디어 WebSocket `/avatar-stream-trt10/v1/live/{turn_id}`로 JSON 명령을 보내고, worker의 motion stitching 단계에서 최신 target을 소비한다. `DITTO_LIVE_CONTROLS=1`을 설정한 TRT10 경로에서 활성화한다. 기존 바이너리 오디오/영상 패킷과 JSON 상태 메시지가 같은 소켓을 사용한다.

이 제어는 **calibrated residual**을 바꾼다. 이미 시작한 native Audio2Motion의 emotion conditioning은 원래 턴 값을 유지한다. 따라서 표정을 neutral로 바꿔도 원래 native 감정 조건이나 원본 인물 표정까지 완전히 제거하는 제어가 아니다. 머리 값도 최종 얼굴의 절대 자세를 보장하는 값이 아니라 기존 Ditto motion에 적용하는 제어량이다.

## 제어 계약

```json
{"type":"control","seq":1,"expression":"happy","intensity":0.5}
{"type":"control","seq":2,"head":{"yaw_deg":3,"pitch_deg":0,"roll_deg":0}}
{"type":"control","seq":3,"gaze":{"x":0.5,"y":0}}
{"type":"control.reset","seq":4}
```

- `seq`: 현재 턴 내에서 양의 정수로 증가해야 한다. 중복·역순은 거부한다.
- `expression`: angry, disgust, fear, happy, neutral, sad, surprise, contempt.
- `intensity`: 0~1. UI는 더 보수적인 0~.8 범위를 제공한다.
- worker head 범위: yaw ±12°, pitch ±10°, roll ±6°. UI는 ±6/±5/±3°다.
- worker gaze 범위: x/y ±1. UI는 ±.8이다. 해부학적 시선 각도 단위가 아니다.
- 채널 단위 부분 변경을 허용하고 이전 override를 유지한다. head/gaze 객체에서 생략한 축은 모델 기본값 0이므로 각 객체의 축을 모두 보내는 것이 명확하다.
- `control.reset`은 target 없이 보내며 자동 동작으로 부드럽게 돌아간다.
- 알 수 없는 필드, 비유한 수, 범위 초과, 비어 있는 control, target을 포함한 reset은 거부한다.
- 명령 크기는 4096자를 제한한다. 이미 렌더링이 끝난 턴과 닫힌 턴은 변경할 수 없다.
- 빠른 연속 입력은 최신 target을 사용한다. 생성 프레임 사이에 덮어쓴 중간 명령은 독립된 영상 상태로 나타나지 않을 수 있다.

응답은 `control.received`, `control.applied`, `control.error`다. `control.applied`의 `pts_ms`는 **처음 영향을 받는 생성 프레임**이며 target 도달 시각이나 사용자 화면 표시 시각이 아니다. UI는 실제 표시한 영상 PTS가 이 지점을 지났을 때 별도로 화면 반영 상태를 표시한다. 수신·생성 반영·화면 반영을 서로 같은 지연으로 기록하지 않는다.

## 연속성과 소유권

현재 초기 설정은 표정 happy .28초, sad/fear .55초, 그 외 .42초의 지수 평활화와 완화 .60초, pupil .22초, head .40초다. head는 25fps에서 프레임당 .24°(6°/s) 이하로 target을 향한다. 이는 SOBIA의 시간 변화 원리를 참고한 Ditto용 값이며 Unity 궤적 코드의 문자 그대로 이식이 아니다.

표정 target은 발음 보호 모드로 해석하고 최종 stitch 단계의 입술 보호·blink 처리를 유지한다. pupil intent와 표정 intensity를 하나의 강도로 곱하지 않는다. 제어하지 않은 채널은 자동 동작의 소유권을 유지한다. 조작 중 새 감정 의미를 임의로 추론하지 않으며, 전환마다 강한 노딩이나 시선 이탈을 추가하지 않는다.

reset이 자동 동작에 수렴하면 override 소유권을 해제하여 이후 native motion을 계속 평활화하지 않는다. 실제 PCM 타임라인의 silent lead/tail 경계에서도 live override를 자동 기준 동작으로 완화하므로, 짧은 응답의 마지막 프레임에 수동 머리·시선 target이 남지 않도록 한다. 자동 표정은 실제 오디오 시계에서 .8초 초기 구간 뒤 1.2초 동안 12% settle하고, 에너지에 의한 변동은 5%로 제한한다. 이 또한 의미 감정의 전환이나 단어별 강조 시점 추정은 아니다.

이미 생성·전송된 프레임은 다시 그릴 수 없다. GPU 생성 대기, 네트워크, 오디오/비디오 재생 버퍼만큼 입력과 화면 사이에 지연이 생긴다. 짧은 응답은 사용자가 화면을 보는 동안 이미 생성이 끝나 있을 수도 있다. 이 경우 명령 거부가 정상이며, UI에 아직 발화 중이라는 사실만으로 즉시 제어 가능하다고 판단하지 않는다. 경청용 캐시 영상의 임의 시점 live deformation이나 LAM/Unity 전체에 대한 제어를 구현한 것도 아니다.

### 실제 표시 시계에 맞춘 생성 제한

첫 GPU 검증에서는 제어 3개가 영상에 반영됐지만, 명령부터 표시까지 지연이 약 2.65/4.29/8.55초로 증가했고 이후에는 이미 생성이 끝나 추가 명령을 적용할 수 없었다. 따라서 이 실행을 실시간 조작 검증 통과로 처리하지 않았다. 원인은 제어 메시지 수신 자체보다 화면 재생에 비해 앞서 진행되는 생성량이었다.

이를 보완하기 위해 브라우저가 실제 canvas에 그린 영상 PTS를 약 160ms 간격으로 worker에 돌려준다. 소켓 시작 시 다음 초기화 메시지를 보내고, 그 뒤 실제 표시 시각을 보낸다.

```json
{"type":"playback","pts_ms":-1}
{"type":"playback","pts_ms":1040}
```

초기화는 턴당 한 번이다. 이후 PTS는 정수·단조 증가여야 하며 생성 시각을 비현실적으로 앞서는 값은 거부한다. 초기 생성 허용 범위는 1200ms이고, 재생이 시작되면 마지막 표시 PTS보다 800ms 앞선 범위까지로 제한한다. 네이티브 stitching thread가 이 범위에서 기다렸다가 새 프레임 생성 직전에 최신 제어 target을 읽는다. 오디오 샘플을 늘이거나 이미 만들어진 오래된 프레임을 빠르게 건너뛰어 맞추는 방식은 아니다.

close/cancel은 대기를 즉시 해제한다. 첫 비음수 stitch 프레임부터 5초 동안 표시 피드백이 없으면 해당 턴의 live control을 비활성화하고 `control.error`를 내보낸 뒤 생성 대기를 해제하여 정리할 수 있게 한다. GPU 초기 로딩 시간 자체가 5초 제한을 소모하지 않도록 했다. 초기화 메시지를 보내지 않는 offline/benchmark 소비자는 기존 생성 처리량을 유지한다. 이 제한이 정한 800ms는 end-to-end 지연 보장이 아니며, 디코딩·네트워크·브라우저 표시 및 평활화 시간은 별도다. 보완 후 실제 지연은 아래 최종 검증에 기록했다.

### 실제 음성 종료와 미디어 전송 종료 구분

생성 제한을 적용한 뒤에는 바이너리 END 패킷이 실제 tail 프레임 전송 완료까지 기다리므로, 이를 받아서야 tail 시작을 계산하면 얼굴의 정상 복귀를 늦게 시작한다. 최초 네 WAV 시나리오는 기존 STT/재생 완료 검사에는 통과했지만 모두 `speech_to_idle` fallback을 사용했다. 이 결과는 `artifacts/mic-policy-20261106/`에 보존했고 자연스러운 정상 tail 전환의 성공으로 처리하지 않았다.

worker는 실제 PCM 입력이 끝나 길이가 확정되면, tail 프레임의 생성·전송이 끝나기 전에 다음 JSON 이벤트를 한 번 보낸다.

```json
{"type":"stream.timing","tail_start_ms":5000,"video_end_ms":6000}
```

예시의 숫자는 설명용이다. 실제 값은 해당 PCM 길이에서 계산하며, tail은 1000ms다. 브라우저는 첫 유효 이벤트를 불변 종료 시각으로 받아 이미 움직이는 영상의 silent tail 안에서 idle 전환을 시작한다. 바이너리 END는 여전히 실제 모든 패킷의 전송 완료를 뜻하며 앞당기지 않는다. 마지막 그림을 늦게 숨기는 fallback만으로 정상 복귀가 됐다고 검사하지 않도록, WAV 자동화에 `fallback=false`와 `live_tail_completed=true` 검사를 추가했다.

## 검증 기록

현재 코드 검증은 web 82개, worker 60개, API 109개 통과·1개 skip이며 build가 성공했다.

실제 GPU 생성·브라우저 표시를 통과한 제어 시험의 기록은 다음과 같다. 시간은 명령을 보낸 뒤 처음 영향을 받는 생성 프레임을 화면에서 관측하기까지이며, target이 완전히 정착하는 시간은 아니다.

| 경로 | 명령 | 최초 영향 프레임 표시 지연(ms) |
| --- | --- | --- |
| 독립 채널 | gaze-left | 697.2 |
| 독립 채널 | gaze-right | 769.7 |
| 독립 채널 | head | 794.1 |
| 독립 채널 | happy | 796.8 |
| 독립 채널 | sad | 808.3 |
| 독립 채널 | reset | 801.4 |
| 실제 UI | expression | 797.8 |
| 실제 UI | gaze-left | 709.9 |
| 실제 UI | head | 801.5 |
| 실제 UI | reset | 812.4 |

- `artifacts/live-control-paced/`: 독립 채널 6개, audio 522/video 572/end 1 패킷, 브라우저 예외 0. 명령→worker 적용 통지 13.1~121.1ms. 분석한 얼굴 362프레임에서 검출 누락 0.
- `artifacts/live-control-ui/`: UI 4개, audio 344/video 394/end 1 패킷, 브라우저 예외 0. 명령→worker 적용 통지 34.5~131.5ms. 분석한 얼굴 274프레임에서 검출 누락 0.
- `artifacts/live-control-ui-final/`: `stream.timing` 변경 후 실제 UI 4개를 다시 검증했다. expression/gaze/head/reset의 첫 화면 반영은 각각 816.9/720.9/795.8/763.6ms, audio 372/video 422/end 1 패킷이며 오류 없이 정상 tail 복귀까지 통과했다.
- 독립 시선 시험의 iris ratio 중앙값은 left 약 (.484,.513), right (.530,.545), reset (.504,.516)으로 변했다. head와 표정의 이미지/기하학 대리지표 변화도 기록한다. 이 값은 해부학적 각도나 사람의 자연스러움 평점이 아니며 native motion·blink·발음 차이를 포함한다.
- happy→sad의 눈썹 간격 중앙값은 (.727,.685)→(.738,.697)로 작게 변했다. 표정 차이가 강하게 인식된다는 증거로 삼지 않으며, 특히 입 모양은 발음과 섞인다. 인물별 감정 식별력은 추가 보정·평가가 필요하다.
- 표정 residual이 발화 중 바뀌는 것과 눈·머리 제어가 실제 영상에 나타나는 것을 검증했다. native Audio2Motion 조건까지 새 감정으로 재생성하거나 모든 인물에서 같은 표정 크기를 보장하는 결과가 아니다.

`stream.timing` 보완 후 최종 WAV 재검증은 `artifacts/mic-policy-final-20261106/`에 따로 기록했다. 전체 프로세스 exit 0이며 네 시나리오 모두 완료된 응답에서 `live_tail_completed=true`, `fallback=false`를 확인했다. 브라우저 예외·미디어 오류는 없었다.

| 가상 마이크 시나리오 | 표시 프레임 수 | 결과 |
| --- | ---: | --- |
| normal | 358 | 실제 STT → 경청 → 응답 → 정상 tail 복귀 통과 |
| short | 135 | 짧은 응답 완료와 정상 tail 복귀 통과 |
| interrupt | 486 | 첫 응답 중단 → 재경청 → 후속 응답 완료와 정상 tail 복귀 통과 |
| auto | 318 | 무음 감지 자동 전송 → 응답 → 정상 tail 복귀 통과 |

최종 화면 전환 지점의 얼굴 영역 평균 픽셀 차이는 normal 1.96, short 1.40, interrupt의 중단 1.46·후속 종료 1.45, auto 1.81/255였다. 각 영상 전체의 95백분위 변화 4.21~7.02/255보다 작았다. 짧은 답변과 중단의 연속 프레임도 검토했으며 큰 위치 도약은 관측되지 않았다. 이는 제한된 샘플의 연속성 보조 지표이며 사람 같은 자연스러움이나 립싱크 정확도의 점수가 아니다.

제어 파라미터가 바뀐 사실과 영상에서 의도한 움직임이 보이는 사실을 구분하며, 영상 관찰을 인간 수준 자연스러움의 객관적 증명으로 확대하지 않는다. 실제 물리 마이크의 반향·소음, 다른 얼굴 이미지, 장시간 대화의 피로감·반복감 평가는 이 자동화 결과만으로 통과했다고 할 수 없다.

생성 WAV/영상/프레임/진단 로그는 `artifacts/` 또는 `tmp/`에 보관하고 커밋하지 않는다.

## 재실행

프로젝트 루트에서 API/web/TRT10 서비스를 실행하고 설정된 Realtime 제공자에 접속할 수 있어야 한다. 아래 브라우저 검증은 실제 모델 호출을 하므로 사용량이 발생한다. `create_mic_fixtures.ps1`는 개인 녹음 대신 Windows Heami 합성 음성을 만들며, 네이티브 Chrome 음성 인식에는 네트워크 연결이 필요하다.

현재 호스트의 번들 Node/Playwright 경로를 사용하는 예시다. 번들 경로가 달라졌다면 해당 환경에서 제공하는 Node 및 Playwright 경로로 바꾼다.

```powershell
$taskNode = 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
$env:NODE_PATH = 'C:/Users/USER/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'

$env:LIVE_CONTROL_OUTPUT = 'artifacts/live-control-repeat-isolated'
& $taskNode scripts/live_control_e2e.cjs --isolated
.venv-perception/Scripts/python.exe scripts/analyze_live_controls.py --root $env:LIVE_CONTROL_OUTPUT

$env:LIVE_CONTROL_OUTPUT = 'artifacts/live-control-repeat-ui'
& $taskNode scripts/live_control_e2e.cjs --ui
.venv-perception/Scripts/python.exe scripts/analyze_live_controls.py --root $env:LIVE_CONTROL_OUTPUT

./scripts/create_mic_fixtures.ps1
$env:MIC_E2E_OUTPUT = 'artifacts/mic-policy-repeat'
& $taskNode scripts/mic_e2e.cjs
.venv-perception/Scripts/python.exe scripts/analyze_mic_e2e.py
```

기본 URL은 `http://localhost:4173`이며 `TEST_URL`로 바꿀 수 있다. live 제어 시험은 제어할 시간이 충분하도록 테스트 세션의 응답 길이 지시를 설정하며 서버 응답·음성·영상은 대체하지 않는다. UI 시험은 화면의 실제 컨트롤을 조작한다. 가상 마이크 시험의 WAV 입력은 `artifacts/mic-e2e/`에서 읽고, 출력만 `MIC_E2E_OUTPUT`으로 분리한다. 각 실행의 `report.json`과 분석 JSON을 먼저 확인한 뒤 영상/접촉 시트를 함께 검토한다. 분석의 픽셀·랜드마크 지표만으로 자연스러움을 판정하지 않는다.
