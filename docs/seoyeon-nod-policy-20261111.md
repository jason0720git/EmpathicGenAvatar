# 서연의 경청과 발화 동작 검증

2026-11-11 기준. 서연 기본 사진(`demo-seoyeon`)과 Ditto Realtime / TensorRT 10 경로에서 측정했다. 사이트에서 **Realtime 대화 → 경청 동작**을 열면 한 번·두 번 끄덕임을 각각 재생할 수 있다. 답변 재생 중에는 실시간 표정·시선·머리 조절을 사용할 수 있다.

## SOBIA-Unity에서 반영한 동작

인접 저장소의 기본 HDRP 장면과 해당 장면에서 활성화된 Companion 정책을 대조했다. 참조한 코드는 `SharedPackages/com.etri.sobia/Runtime/EmpathicBehavior` 아래의 `EmpathicNodding.cs`, `Nodding/NoddingPolicy.cs`, `Nodding/NoddingSettings.cs`, 그리고 `Expression/EmpathicEmotion.{Companion,Trajectories,ContextDynamics}.cs`다. 11월의 변경은 주로 표정에 있었다. 끄덕임에서는 Unity에 이미 있던 한 번·두 번의 구분을 Ditto 경청에 연결했다. [참조한 SOBIA-Unity 리비전](https://github.com/jason0720git/SOBIA-Unity/tree/b4ee194b9235efc31d0a600bb7dc8c6ba600ef2c)

| 대화 상황 | 서연에게 적용한 행동 |
| --- | --- |
| 0.65초 이상 말한 뒤 0.35~2초간 짧게 쉼 | 한 번 끄덕인다. 같은 쉼은 한 번만 사용한다. |
| 말이 1.6초 이상 이어짐 | 첫 경청 신호는 두 번 끄덕이고, 이후에는 한 번과 두 번을 번갈아 사용한다. 이어 말하는 동안 다음 끄덕임까지 최소 6초를 둔다. |
| 경청이 길어짐 | 발성 누적 4초, 경청 경과 5초를 넘으면 짧은 시선 이탈·복귀를 한 번 허용한다. 동작 간 최소 간격은 2.2초다. 이미 실행 중인 머리 동작과 겹치는 요청은 재생하지 않고 그 이유를 기록한다. |
| 서연이 답하기 시작함 | 답변의 역할과 정서를 기존 8개 표정 선택에 반영한다. 위로는 천천히, 놀람은 빠르게 시작한다. 눈썹·눈꺼풀·볼의 시작과 풀리는 시점에 차이를 두고 실제 음성의 강세와 쉼을 따라 표정 강도를 바꾼다. 같은 턴은 같은 변화를 재현할 수 있다. |
| 답변 중 수동 조작 또는 말 끊기 | 수동 입력이 해당 부위의 제어를 이어받고 해제할 때 점차 돌아온다. 경청과 발화 사이 전환에서도 얼굴 주변만 변형한다. |

Unity의 의미 분류기를 새로 호출하는 대신 기존 Realtime 표정 선택 단계에서 답변의 기능, 복합 감정, 인용 등을 고려하도록 했다. 생성기는 기존 Ditto의 표정 잔차를 사용한다. 발음용 입 모양, 깜박임, 동공 제어는 기존 경로가 담당한다. Unity의 본 회전값은 생성 영상의 각도와 단위 대응이 달라 서연의 출력 영상으로 강도를 보정했다.

## 머리만 움직이도록 수정한 지점

이전 버전에도 작은 끄덕임이 있었다. 다만 무음 입력에서 기본 자세가 달라지면서 서연의 코가 끄덕이기 전에 위로 14.21픽셀 이동했고, 입이 벌어지는 변화도 겹쳤다. 새 경청 클립은 원본 사진의 얼굴 자세를 기준으로 머리를 내렸다가 되돌린다. 한 번은 4.0°, 두 번은 4.0° 다음에 1.8°를 생성기에 요청한다. 각 횟수에서 240ms 동안 내리고 320ms 동안 돌아오며 양 끝과 정점에서 속도와 가속도를 0으로 연결한다.

생성기 쪽에서는 서연의 얼굴 점 478개로 턱에서 목까지 합성 경계를 정해 옷과 배경을 원본 사진에 고정했다. 초기 수정 후에도 답변이 끝날 때 **브라우저의 화면 전환**이 어깨를 약 0.4초간 끌어당기는 것이 발견됐다. 최종판은 브라우저에서 적용하는 변형도 서연의 얼굴·머리 주변으로 제한한다. 두 보정 모두 기존 아바타 생성기를 사용한다.

## 실제 출력 측정

아래 값은 같은 서연 영상의 가로를 512픽셀로 맞춰 얼굴 특징점과 옷의 추적점을 측정한 결과다. 끄덕임 각도는 각 동작 시작 자세 대비 영상에서 추정한 숙임이다. 옷 변위는 각 프레임에서 추적점 변위의 90백분위를 구한 뒤 그중 최댓값을 택했다.

| 측정 항목 | 이전 | 최종 |
| --- | ---: | ---: |
| 한 번 끄덕일 때 숙임 / 코 하강 | 1.62° / 4.84px | 2.37° / 8.35px |
| 끄덕임 시작 전 코의 상향 이동 | 14.21px | 1.17px |
| 무음 끄덕임 중 입 벌어짐의 변화 폭 | 9.19px | 0.12px |
| 한 번 끄덕이는 클립의 옷깃 변위 | 1.42px | 0.030px |
| 대화가 끝나 경청으로 전환할 때 어깨선 변위 | 4.72px | 0.002px 미만 |

- 두 번 끄덕일 때 두 번째 숙임은 0.97°였다. 두 동작은 각각 시작 각도에서 0.04° 이내로 돌아왔다. 브라우저에서 한 번·두 번 버튼 모두 60/60프레임을 재생했고, 두 번의 정점은 재생 후 0.60초와 1.29초에 화면에서 관측됐다.
- 실제 답변 하나에서 표정, 시선, 머리 좌우 전환, 해제까지 5개 명령을 보냈다. 머리의 좌우 전환 폭은 영상 추정치 8.33°였다. 왼쪽 시선 조작에서 양쪽 눈동자는 각각 눈 너비의 약 2.5%, 3.1% 이동했다. 클릭부터 해당 명령을 반영한 첫 프레임 표시까지 0.72~0.83초가 걸렸다.
- 합성 한국어 WAV를 Chrome의 마이크 입력에 넣고 실제 음성 인식·Realtime 응답·GPU 렌더링을 연결했다. 일반 발화(353장), 짧은 답변(127장), 말 끊기와 후속 답변(591장), 자동 전송(312장) 모두 통과했다. 최종 화면 1,383장에서 어깨선 변위는 0.002px 미만, 목둘레는 0.32px 이하였다. 도중에 끊긴 재생도 백엔드에서 구별됐다.
- 수치는 해당 사진, 호스트, 녹화 세션에서 얻었다. 물리적 마이크의 방 소음, 사람의 공감·자연스러움 평정, 음소별 입 모양 정확도는 이번 측정 범위 밖이다.

## 로그 비교와 재실행

API는 `/data/telemetry/turn-events.jsonl`에 동작을 요청한 이유와 시점, 첫 화면 표시, 완료·취소·실패, 실제 표시 프레임 수를 기록한다. 서연 사진 해시, 경청 캐시 버전과 정책 버전으로 실행 조건을 확인할 수 있다. `ditto-affect-applied.jsonl`에는 생성기의 구간별 표정 제어량과 수동 제어가 적용된 프레임 수가 남는다. 제어값의 크기와 최종 영상에서 측정한 움직임은 서로 다른 측정치다.

운영 로그를 로컬의 무시된 폴더에 복사한 뒤 최근 실행 또는 특정 턴을 조회할 수 있다. 비교기는 대화 내용 없이 공통 턴 ID로 브라우저·생성기 기록을 연결한다. 시간차에는 사용한 시계가 표시된다.

```powershell
$logs = 'artifacts/motion-log-comparison'
New-Item -ItemType Directory -Force $logs | Out-Null
docker cp empathic-avatar-api-1:/data/telemetry/turn-events.jsonl "$logs/turn-events.jsonl"
docker cp empathic-avatar-api-1:/data/telemetry/ditto-affect-applied.jsonl "$logs/ditto-affect-applied.jsonl"
.venv/Scripts/python.exe scripts/compare_motion_runs.py --telemetry-dir $logs --avatar demo-seoyeon --limit 5
# --avatar 대신 --turn <첫 번째 턴 ID> --turn <두 번째 턴 ID>로 직접 비교할 수 있다.
```

재실행은 서비스가 열린 상태에서 진행한다. Node가 Playwright를 찾을 수 있도록 설정하는 방법은 [기존 실시간 조작 검증 문서](sobia-live-controls-20261106.md)에 있다. `--before`에는 기존 버전에서 보관한 한 번 끄덕임의 60프레임을 지정한다. 사진과 리플레이, 실행별 로그는 `artifacts/` 아래에 로컬로만 보관한다.

```powershell
$env:NOD_UI_OUTPUT = 'artifacts/repeat-nod/ui'
node scripts/check_listening_preview.cjs
$idle = 'http://localhost:4173/api/avatars/demo-seoyeon/idle'
.venv-perception/Scripts/python.exe scripts/measure_listening_nod.py --before artifacts/nod-locality-20261111/before --after artifacts/repeat-nod/single --double artifacts/repeat-nod/double --capture-after "$idle/3/mjpeg" --capture-double "$idle/5/mjpeg" --output artifacts/repeat-nod --ui-dir $env:NOD_UI_OUTPUT
$env:LIVE_CONTROL_OUTPUT = 'artifacts/repeat-live'
node scripts/live_control_e2e.cjs --ui --head-range
./scripts/create_mic_fixtures.ps1
$env:MIC_E2E_OUTPUT = 'artifacts/repeat-mic'
node scripts/mic_e2e.cjs normal short interrupt auto
.venv-perception/Scripts/python.exe scripts/measure_listening_nod.py --live-dir "$env:MIC_E2E_OUTPUT/interrupt" --output artifacts/repeat-interrupt-measurement
```
