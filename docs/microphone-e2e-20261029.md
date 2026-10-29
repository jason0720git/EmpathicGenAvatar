# 가상 마이크 Realtime 검증 (2026-10-29)

## 테스트 경로

Windows Microsoft Heami Desktop으로 한국어 사용자 WAV를 생성했다. Chrome의 fake audio capture 장치에 파일을 연결하고 **실제 getUserMedia MediaStreamTrack**을 RMS/VAD 및 네이티브 SpeechRecognition에 함께 전달했다. 인식 결과가 UI에 도착하면 실제 API·OpenAI Realtime·Ditto TRT10 worker·브라우저 A/V 재생을 실행한다. 음성 인식 결과나 서버 응답을 mock으로 대체하지 않는다. 테스트용 브라우저만 가상 마이크/권한 플래그를 사용하며 OS 기본 마이크 설정을 변경하지 않는다.

개인 마이크 오디오는 수집하지 않았다. 합성 음성이 브라우저 음성 인식 서비스에 전달되고 그 전사가 설정된 Realtime 서버로 전달된다. 실제 방의 잡음·반향·스피커 누설·하드웨어 권한 환경은 별도 실기 테스트 대상이다. 보호된 자동 모드는 아바타가 말하는 동안 마이크를 닫으며, 자동 음성 끼어들기 검증을 뜻하지 않는다. 끼어들기는 Push to talk에서 마이크 버튼을 다시 누르는 동작이다.

## 수정한 문제

1. 기존 RMS용 getUserMedia와 별도로 열리는 음성 인식 입력을 하나의 트랙으로 연결했다. 이 환경의 독립 입력 시도는 no-speech/무전사였고 공유 트랙에서는 한국어 실전사가 성공했다. Chrome에서 확인했으며 타 브라우저 동일 지원을 보장하지 않는다.
2. 중단 시 발화 canvas를 즉시 숨기던 동작을 바꿨다. 음성·소켓은 즉시 취소하고 마지막 표시 합성 화면에서 현재 idle로 320ms geometry 전환한다. 새 턴이 시작하면 이전 전환/소켓 콜백을 무효화한다.
3. 이전 recognizer의 늦은 result/end/error와 지연된 마이크 권한 응답이 새 입력 세션을 덮어쓰지 못하도록 세대 번호를 확인한다. 음성 입력 방식 변경 시 취소 상태도 명시적으로 복원한다.
4. 경청 cue로 전환하거나 cue를 중간에 끝낼 때 생기는 자세 차이를 320ms 전환으로 완화했다. 일반/경청 영상은 계속 현재 프레임으로 진행한다.
5. 스트리밍 응답의 임시 프레임 할당 길이 대신 실제 PCM 종료에 맞춰 pupil residual을 silent tail에서 0으로 돌린다. 발화가 끝난 뒤 예약된 시선 이탈이 새로 시작되는 것도 차단한다. 네이티브 입술/머리 동작 전체를 원본 사진에 고정하지 않는다.

## 시나리오와 증거

- `normal`: 약 9.5초 합성 사용자 발화 → 경청 cue → 수동 전송 → 한 문장 응답 → idle.
- `short`: “네 라고만 짧게 대답해 주세요” 인식 → 짧은 응답 → idle. STT가 일부 실행에서 “짧게”를 “할게”로 인식했다. 테스트는 실제 전사를 기록하며 대본으로 교체하지 않는다.
- `interrupt`: 긴 설명 요청 → 발화 화면 시작 2.2초 뒤 마이크 재개 → 경청 → 두 번째 WAV 입력 → 두 번째 응답 종료.
- `auto`: normal WAV → 1.1초 무음 감지 → 자동 전송 → 응답 종료. 종료 직후 재청취 대기 구간까지 확인한다.

브라우저가 실제 표시한 canvas를 80ms마다 256×320으로 저장하고, 입/눈을 포함한 얼굴 영역의 인접 프레임 픽셀 차이와 전환 경계를 비교했다. 초기 경청 cue 진입의 차이 약 17.3/255에 비해 전환 추가 후 관측한 cue 경계는 약 0~3.6/255였다. 이는 동일 타이밍을 고정한 통제 실험이나 공감/자연스러움 점수가 아니며, 렌더링·깜빡임·샘플링 위상에도 영향을 받는다. 짧은 응답과 중단 전환의 접촉 시트도 확인했다. 정확한 각 실행 결과는 로컬 report.json/analysis.json에 남는다.

웹 회귀 테스트 79개, worker 테스트 42개 통과. Docker web/worker 빌드 및 배포 성공. 기존 큰 LAM 번들 경고 및 FastAPI lifespan 권고는 남아 있다.

최종 산출물 기준 normal/short/interrupt/auto 모두 통과했고 브라우저 예외는 0개다. short의 실제 발화 구간은 2.48초(lead/tail 제외), interrupt는 첫 응답을 취소한 뒤 후속 발화 13.28초의 재생 완료를 확인했다. 완료된 응답에서 JPEG decode 실패·video PTS gap·socket error가 없는지 자동 검사한다. normal 283, short 256, interrupt 501, auto 332개 표시 프레임을 저장했다. normal은 경청 전환 수정 후 실행, 나머지는 최종 worker 시선 종료 수정 후 재실행한 기록이다.

## 재실행

프로젝트 루트에서 API/web/TRT10 서비스를 실행한 뒤:

```powershell
./scripts/create_mic_fixtures.ps1
# Node가 playwright를 찾을 수 있도록 설치 경로를 NODE_PATH로 지정하거나
# 해당 패키지가 제공되는 Node 환경에서 실행한다.
node scripts/mic_e2e.cjs
.venv-perception/Scripts/python.exe scripts/analyze_mic_e2e.py
```

`mic_e2e.cjs short auto interrupt`처럼 일부 시나리오만 선택할 수 있다. 기본 URL은 localhost:4173이며 TEST_URL로 바꿀 수 있다. 실제 Realtime 호출을 수행하므로 실행에는 설정된 API 자격증명과 사용량이 필요하다. 네이티브 음성 인식에는 네트워크 연결이 필요하다.

산출물은 git에서 제외되는 `artifacts/mic-e2e/` 아래다. `fixtures.json`, 입력 WAV, 시나리오별 `report.json`, 프레임 JPEG, `site.png`, `handoff.jpg`, `display-replay.mp4`가 생성된다. display-replay는 12.5fps로 샘플링한 무음 시각 기록이며 원본 A/V 녹화가 아니다. Git에는 재현 스크립트·회귀 테스트·수정 코드·문서만 포함한다.
