# Ditto + LivePortrait 공감 비언어 제어 현황과 1차 개선

2026-10-29. 현재 저장소 코드, 과거 실험 기록, 이번 GPU 고정 입력 검증 기준.

## 실제 구현 구조

주 경로는 Ditto Audio2Motion → motion stitching → warp/decode이며, LivePortrait의 표정 제어 좌표를 참고한 `delta_exp`를 그 안에 추가한다. Ditto 영상을 별도의 LivePortrait 모델로 다시 처리하는 직렬 경로가 아니다. `liveportrait_runtime.py`의 학습된 동작 템플릿은 MuseTalk 보조 경로로 구분해야 한다.

주요 근거: `workers/avatar/app/main.py`의 `facial_template`, `build_ditto_ctrl_info`, `BlinkAwareMotionStitch`; `apps/api/app/behavior.py`; `docs/native8-expression-v3.md`, `docs/expression-speech-protection-v4.md`, `docs/expression-v5-smile-and-concurrency.md`.

## 무엇을 제어하는가

| 항목 | 기존 구현 | 한계 / 이번 변경 |
| --- | --- | --- |
| 표정 | neutral/happy/sad/angry/disgust/fear/surprise/contempt 8종, 강도 0–1, 시작/종료 변화 | 독립 AU 제어가 아닌 결합된 암시적 좌표. 공감·경청·안심이 각각 독립 프리셋인 것은 아님 |
| 발음과 표정 병행 | 기본 speech_safe는 중립 음성 동작에 상안면 보정. Happy는 입 중심 보호 + 제한된 입꼬리/볼 보정 | Sad/Contempt의 입가 특징도 보호 정책으로 약해질 수 있음. 강한 표정과 정확한 발음의 절충이 남음 |
| 눈꺼풀 | 네이티브 깜빡임, Fear/Surprise의 제한된 눈뜨기, 깜빡일 때 눈뜨기 보정 감쇠 | 사용자 지정 윙크/눈감기 이벤트나 좌우 독립 눈꺼풀 API는 없음 |
| 눈동자 | 기존 gaze.x/y는 머리에 yaw ±3°, pitch ±2°를 더함. Ditto 내부의 머리 자세 기반 시선 보정도 존재 | 이번에 opt-in `gaze.mode="pupil"` 추가. 머리에 gaze를 더하지 않고 눈동자 좌표 11/15를 제어 |
| 머리 | yaw ±12°, pitch ±10°, roll ±6° 요청 오프셋, 한 번의 끄덕임 | 이번에 gaze와 nod 합산 후 오프셋 제한 적용. 생성된 기본 자세까지 포함한 절대 각도 보장은 아님 |
| 끄덕임 | 시작 시각 0–10초, 길이 260–1200ms, 진폭 2–8° | 짧은 발화에서 남은 시간에 압축하던 동작 제거. 완주할 수 없으면 생략. sin² 곡선으로 진입/복귀를 부드럽게 변경 |
| 대화 정책 | LLM의 emotion/intensity를 BehaviorPlanner가 변환. Sad/Happy/Surprise 자세 단서; 수동 Happy 시험의 nod | 발화 중 의미 단위별 시선·고개 이벤트, 경청 반응, 시선 이탈→복귀 정책은 아직 없음 |
| 대기 상태 | 준비된 idle 영상에서 자연스러운 머리/깜빡임 | 이번 pupil 제어는 생성 턴에 적용. 이미 만들어진 idle 영상에 실시간 시선을 주입하지는 않음 |

## 이번 눈동자 제어의 범위

- 기본 `head_cue`를 유지해 기존 자동 대화를 바꾸지 않았다. `pupil`을 명시하면 표정 강도 0이나 표정 off에서도 시선 제어를 별도로 사용할 수 있다.
- 설치된 `vendor/LivePortrait/src/gradio_pipeline.py:update_delta_new_eyeball_direction`의 좌우 비대칭 계수와 보정 후 수직 계수를 참고했다. 입력 ±1을 upstream slider ±4 단위로 매핑한다. **시선 각도 단위가 아니다.** 수직 제어에 따른 추가 눈꺼풀 변형은 제외했다.
- 240ms smoothstep 진입/복귀, 네이티브 깜빡임 시 pupil 잔차 감쇠, 기존 speech_safe 입 보호를 함께 적용한다. 표정 템플릿의 pupil 보호는 유지한다.
- Ditto의 기존 머리 자세 보정도 여전히 적용된다. 따라서 pupil은 독립적인 추가 오프셋이지 카메라를 정확히 응시하게 하는 추적 제어가 아니다. 좌우 방향/감도는 아바타별 캘리브레이션이 필요하다.
- 긴 실시간 스트리밍에서는 예상 프레임 길이를 사용하고 기존 boundary 처리가 종료를 담당한다. 이번 변경으로 의미에 맞춘 중간 시선 전환이나 임의 시각의 제어 업데이트까지 구현한 것은 아니다.

기존 세션의 `POST /api/live/sessions/{session_id}/turns`에서 수동 override로 시험할 수 있다. UI에는 아직 별도 시선 슬라이더를 추가하지 않았다.

```json
{
  "text": "천천히 이야기해 주세요. 듣고 있어요.",
  "motion_override": true,
  "motion_plan": {
    "expression": "neutral",
    "intensity": 0,
    "expression_render_mode": "speech_safe",
    "head": {"yaw_deg": 0, "pitch_deg": 0, "roll_deg": 0},
    "gaze": {"mode": "pupil", "x": 0.5, "y": 0},
    "nod": null
  }
}
```

`gaze.y=-1`은 아래, `+1`은 위 의도이다. x는 암시적 좌표의 부호이며, 화면 미러링에 따라 보이는 좌우를 확인해야 한다. 모드를 생략하면 기존 head_cue이다. 이 스키마는 API → worker 및 웹 타입에 반영했다.

## 검증 결과

- 워커 테스트 37개 통과: 머리/표정 강도와 pupil 독립성, 표정 합성, blink 감쇠와 캐시 불변, 합산 pose 제한, 짧은 턴 nod 생략 포함.
- API 테스트 108개 통과, 선택적 의존성 테스트 1개 skip. 수동 요청의 pupil 모드와 좌표가 applied_motion까지 보존되는 것을 확인했다.
- 웹 TypeScript 및 프로덕션 빌드 통과. 기존 LAM 번들 크기 경고는 유지된다.
- 기존 TRT10 GPU 이미지와 설치된 모델로 demo-seoyeon의 고정 머리 자세에서 center/x±/y± 5방향을 렌더링했다. 좌우·상하 변화는 작게 나타나며, 과장된 시선 이탈 표현으로 보기에는 약하다. Surprise+pupil 조합의 15개 blink 단계를 확인했고 양쪽 눈이 감겼다가 다시 열렸다.
- 생성 비교 이미지: 로컬 `artifacts/gaze-v1/directions.jpg`, `blink.jpg`. Git 제외. 재현 도구: `python -m app.audit_gaze --output /audit` (기존 GPU worker 모델/데이터 마운트 필요).
- 이 검증은 단일 인물, 정지 자세, 무음 조건이다. 발화 중 시선 정확도·다양한 얼굴·인지된 공감 개선을 입증하지 않으므로 자동 대화 기본값으로 승격하지 않았다. 서비스 컨테이너를 배포/재시작한 것은 아니며, 실행 중 서비스 적용에는 새 코드 반영이 필요하다.

## 다음 개선 우선순위

1. **여러 아바타에서 시선·발음 조합을 검증**: 머리 고정 상태의 방향/감도, 말하는 동안 입 보호, 눈꺼풀 충돌을 비교한 뒤 pupil 모드의 자동 적용 여부를 결정한다.
2. **경청 반응의 타이밍**: 항상 Sad로 동조시키기보다 중립/약한 온화함, 짧은 끄덕임, 시선 유지·이탈·복귀를 대화 상태에 맞춰 배치한다. 표정 선택과 반응 타이밍은 분리한다.
3. **표정 제어를 세분화**: 눈썹 긴장·이완, 약한 미소, 눈꺼풀 완화를 입 중심과 분리해 검증한다. 먼저 기존 speech_safe의 Sad/Contempt 약화 정도를 측정한다.
4. **대기 영상과 연결**: 경청 중에도 이벤트를 반영하려면 idle 영상을 선택/연결하거나 저비용 실시간 idle 생성 경로가 필요하다. 몸은 반복 패턴으로 유지해도 현재 목표에 부합한다.
