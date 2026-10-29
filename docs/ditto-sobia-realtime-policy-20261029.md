# Ditto Realtime 경청·발화 정책 적용 (2026-10-29)

## 검토 범위와 판단

로컬 `../SOBIA-Unity`의 HEAD `de16a0d2`(2026-10-28)와 현재 작업 파일을 읽었다. 원격 최신 여부를 확인한 것은 아니다. 해당 저장소에는 기존 미커밋 변경이 있으며 읽기만 수행했다. 참고 경로는 `SharedPackages/com.etri.sobia/Runtime/EmpathicBehavior/` 아래다.

| 참고 구현 | Ditto 적용 판단 |
| --- | --- |
| `Nodding/NoddingPolicy.cs`, `NoddingSettings.cs` | 음성 누적·짧은 쉼·최소 간격 기반의 인과적 경청 정책 채택. 의미적 동의 판정이나 학습된 VAP는 아니다. |
| `EmpathicEmotion.ContextDynamics.cs` | 경청·응답 준비·실제 발화의 상태 구분과 이전 동작 정리 원칙 적용. Unity 전체 맥락 유지 정책을 포팅한 것은 아니다. |
| `EmpathicEmotion.SpeechDynamics.cs`, `Interaction/CausalProsodyTracker.cs` | 현재 PCM 에너지로 선택된 표정 강도만 완만하게 조절. -54~-19 dB 정규화 참고. 전체 accent/F0 모델은 미이식. |
| `EmpathicEmotion.cs` | Unity의 강한 표정 증폭과 joy 복귀 기본값은 그대로 복제하지 않았다. 선택된 슬픔/걱정을 임의로 기쁨으로 바꾸지 않는다. |
| `Base/BaseHeadMotion.cs` | 작은 경청 움직임과 동작 중복 억제 원칙 참고. Unity 5~15도 끄덕임은 Ditto 얼굴 왜곡을 고려해 1.6도로 축소. |
| `EmpathicEyeContact.cs` | 로컬 변경의 카메라 전방/해부학적 축 보정은 3D 월드 좌표용이다. Ditto에는 직접 이식하지 않고 기존 LivePortrait 유래 pupil residual 사용. |

## 실제 연결

마이크 RMS → `ListeningPolicy` → 유한 경청 영상 → 기본 idle 복귀로 연결했다. 음성 입력 종료, 응답 준비, 발화 또는 오류로 경청 상태를 벗어나면 정책과 미완료 cue를 정리한다. push-to-talk와 보호된 자동 입력 양쪽에 동일한 연결을 사용한다.

- RMS 0.018 이상을 유성 구간으로 간주한다.
- 누적 유성 0.65초 이후 0.35~2초 쉼에서 끄덕임 후보를 만든다.
- 연속 발화 중 첫 반응은 유성 1.6초 이후, 후속 continuer는 최소 6초 간격이다.
- 모든 cue 사이 최소 간격은 3.2초다. 큐에 오래된 제스처를 쌓지 않는다.
- 경청 5초 및 유성 4초 이후, 말하는 구간에서 한 번만 작은 시선 이탈·복귀를 허용한다.
- 입력 콜백 간격이 0.5초를 넘으면 정책을 리셋한다. 무음만으로 끄덕이지 않는다.

끄덕임 영상은 2.4초/60프레임, 시선 영상은 3초/75프레임이다. 각 영상은 한 번 재생하고 마지막 프레임을 그린 뒤 기본 idle로 돌아간다. 첫/끝 구간은 원본 자세로 완화한다. 생성은 준비 단계에서 캐시하므로 경청 cue마다 GPU 생성을 기다리지 않는다. 캐시 버전은 r13이며 기본 idle 2개, 미리보기 1개, 유한 cue 2개다.

`경청 미리보기`는 별도의 16초 반복 데모다. 실제 경청 정책의 입력 검증을 대신하지 않는다. 위 RMS 임계값과 시선 시간은 제품 엔지니어링 초깃값이며 임상적으로 검증된 공감 정책이 아니다.

## 답변 중 표정·시선

자동 감정 선택에 `temporal_policy=sobia`와 약한 pupil `avert_return`을 부여한다. TRT10 Realtime worker는 현재 40ms PCM 창에서 표정 강도를 계산한다. 유효 음성 창에서는 선택 강도의 70~100%, lead/tail에서는 0을 목표로 하고 상승 0.18초/하강 0.32초로 평활화한다. 기존 Ditto 입술 보호와 눈 깜빡임 보정을 유지한다. 표정 강도 조절이 pupil 제어를 함께 줄이지 않도록 채널을 분리했다.

시선 이벤트는 영상 시계 2초에서 시작하여 0.36초 이탈 → 0.44초 유지 → 0.60초 복귀한다. 이는 SOBIA의 수치를 그대로 옮긴 것이 아닌 Ditto용 프리셋이다. Realtime에는 1초 lead가 있으므로 발화 시작 2초 후를 뜻하지 않는다. 길이가 사전에 알려진 3.64초 미만 영상에서는 이벤트를 생략한다. 길이가 미리 알려지지 않은 짧은 스트리밍 응답은 전체 이벤트가 끝나기 전에 종료될 수 있다.

UI의 `발화 시선`에서 자동/정면/좌/우/이탈·복귀를 다음 턴에 지정할 수 있다. 수동 표정 테스트는 steady 정책을 유지한다. 감정 도구 계약이 없는 fallback 응답에는 자동 정책을 추측해서 넣지 않는다. 이번 실동작 검증 대상은 Ditto TRT10이며 LAM/Unity/A2F 전체에 적용한 변경은 아니다.

## 검증 기록

- API: 109 passed, 1 skipped(선택적 A2F).
- Worker: 41 passed. gaze 복귀/짧은 영상 생략, 독립 채널, 경청 primitive 경계, PCM 표정 강도를 포함한다.
- Web: 77 passed. 유한 영상 마지막 프레임 완료, 마이크 경청 cue 연결·중단, 경청 타이밍 정책을 포함한다.
- `pnpm build` 및 Docker web/API/TRT10 이미지 빌드 성공. web Dockerfile에 빌드 시 필요한 emotion_profiles.json 복사를 보완했다.
- 한국어 테스트 WAV 4.65초 + 무음 1초로 baseline/left/right/avert-return 4조건 GPU 생성. 각 조건 142 audio packets, 192 video frames. 조건별 96개 분석 프레임에서 얼굴 검출 누락 0.
- 무음 구간 입 벌어짐/입 너비 비율 중앙값: baseline 0.00175, left 0.00140, right 0.00152, avert-return 0.00182. 측정은 기하학적 대리지표이며 자연스러움의 객관적 점수가 아니다. 타임라인 및 무음 비교 이미지도 육안 확인했다.
- 실제 웹 프록시에서 cue 3은 60프레임/2.47초, cue 4는 75프레임/3.06초로 정상 종료했다. peak/last 이미지 확인.
- 실제 OpenAI Realtime 대화: 합성 테스트 문장 입력 → 감정 도구 happy 0.5 → GPU 음성/영상 스트림 → 대화 준비 상태 복귀 성공. worker에서 `audio_streaming=true`, `expression_test=false`, `temporal_policy=sobia`, pupil avert_return 확인. 재현용 turn: `user-1793236307915`.
- 실제 사용자 마이크/STT까지 포함한 청취 평가는 아직 하지 않았다. 마이크 RMS 경청 cue 연결과 중단 정리는 mock 기반 통합 테스트로 확인했다. 인물·조명·잡음 환경별 자연스러움은 사용자 평가가 필요하다.

재생·분석 산출물은 git에서 제외된 `artifacts/gaze-speech-v1/`에 있다. 재생성은 worker의 `python -m app.benchmark_affect --gaze-ab`, 분석은 `audit_gaze_speech.py`를 사용한다. 원본 음성과 합성 영상, JPEG, 로그를 커밋하지 않는다.

## 직접 테스트

`http://localhost:4173` → Realtime 대화 → 감정/발화 시선 자동 → 음성 입력 시작. 몇 초 말하고 짧게 쉰 뒤 이어 말하면 경청 cue를 확인할 수 있다. 입력을 마치면 응답의 표정·시선과 대기 복귀를 확인한다. 브라우저 마이크 권한 및 음성 인식 지원이 필요하다.
