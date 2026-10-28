# 공식 306 실시간 대화와 LAM 구강 문제

## 적용 결과

공식 306은 이제 녹화 동작 재생 항목이 아니라 실제 GPU 렌더링 항목이다.
기존 녹화 MP4는 비교 자료로 디스크에 보존한다. 공식 체크포인트의
89,021개 Gaussian, FLAME face binding, 구강 외형과 SH3 색상을 그대로
사용한다. 임의의 치아 이미지·혀 이미지를 덧씌우지 않는다.

경로: Realtime 음성 → NVIDIA A2F → 공감 행동 합성 → ARKit–FLAME 변환
→ GaussianAvatars GPU 렌더링 → 브라우저. WAV 테스트도 같은 렌더러를 쓴다.
전용 워커 `gaussian-official-live`는 localhost 8041에서 동작한다.
`start-gaussian.ps1 -SkipGenerator` 실행 시 함께 시작한다. Docker 자체의
자동 재시작 정책은 추가하지 않았다.

ARKit 52개 원본 변형을 동일한 FLAME 5,023개 정점의 표현 100차원과
jaw 회전 3차원에 정규화된 ridge least-squares로 적합했다. 계수는 채널
이름 순서로 매핑한다. 눈 깜빡임의 과소 폐쇄는 실제 렌더링을 보고
1.65배로 보정했고, 시선은 눈 회전으로 처리하여 이중 적용을 피했다.
이 변환은 새로 구현한 근사 매핑이며, 논문 저자의 A2F 공식 지원이나
학습된 audio-to-FLAME 모델이라고 주장하지 않는다.

브라우저는 한 프레임만 전송 대기한다. GPU가 느려져도 과거 입 모양을
큐에 쌓지 않는다. 비활성 탭은 초기 로딩 이후 프레임 요청을 멈춘다.
렌더링 시간과 왕복 시간을 화면에 표시하고, 연결 오류는 오류 상태로
표시한다. 기존 마이크/텍스트 입력 및 Auto/manual 행동 경로를 유지했다.

## 첨부 영상에서 확인한 원인

`bandicam 2026-09-29 13-02-56-835.mp4`를 프레임 추출해 확인했다.
입 주변 경계는 A2F 값이 전달되지 않아서 생긴 것이 아니다. 이전 v5의
화면 투영 기반 색상 마스크는 실제 입 내부 표면을 분리하지 못하므로,
변형되는 사진 기반 구강 외형 위에 색 경계를 만들 수 있다. 해당 v5
색상 마스크 경로를 제거했다. 추가했던 890개 인공 구강 Gaussian도
계속 숨긴다. Emma/서연의 이름을 `LAM 원본 구강`으로 바꿔 이를 명시한다.

LAM 원본에서도 큰 입 벌림의 구강이 완전히 복구되지는 않는다. 활성
설정은 `add_teeth=false`, `teeth_bs_flag=false`, `oral_mesh_flag=false`이며,
원본 사진은 입 안쪽을 보여주지 않는다. 따라서 치아처럼 밝게 보이는
영역이 독립적인 치아/혀 구조라고 단정할 수 없다. 단일 시점에서 학습
모델이 추정한 색과 Gaussian 분포를 변형하는 것에 한계가 있다.

동양인/서양인에 따른 문제라고 입증한 근거는 없다. 두 결과 모두 같은
단일 사진 생성·템플릿 변형·보정 경로의 영향을 받는다.

## 사진 한 장과 여러 장의 차이

| 경로 | 입력 및 구동 | 이번 검토 판단 |
| --- | --- | --- |
| LAM | 단일 사진 생성, ARKit 계열 변형 | 대화 호환 자체는 가능. 현재 두 자산의 구강 추정 품질이 한계 |
| GaussianAvatars | 사람별 촬영 시퀀스 학습, FLAME face binding | 공식 306을 실제 음성으로 구동 완료. 새 인물은 별도 데이터와 학습 필요 |
| ARTalk | 음성에서 FLAME 표현/머리 움직임 생성 | 모션 생성 대안. 기존 LAM의 잘못된 구강 외형을 복원하는 기술은 아님 |
| GAGAvatar | 단일 사진에서 FLAME 구동 아바타 재구성 | 다른 생성 모델 비교 후보. 이 작업에서 설치/품질 검증까지 완료한 것은 아님 |

사진 한 장으로 아바타 생성이 원천적으로 불가능한 것은 아니다. 다만
보이지 않는 혀·치열의 **정확한 복원**과 자연스러운 생성은 다른 목표다.
현재 LAM 추론 경로에는 사진 여러 장을 같은 인물로 합쳐 재학습하는
기능이 없다. 사진 개수만 늘려서 이 기능이 생기지는 않는다.

사람별 모델을 새로 학습하려면 정면/측면과 다양한 입 벌림·입술 모양이
일관되게 관측된 시퀀스, 카메라/FLAME 추적, 학습과 별도 검증이 필요하다.
AI가 각각 생성한 사진은 치열·얼굴 구조·조명이 서로 달라질 수 있어서,
실제 일관된 다중 시점 촬영을 대체한다고 검증 없이 가정하면 안 된다.
이번에는 다중 사진이 필요한 생성 경로를 새로 도입하지 않았으므로,
합성 사진 생성/다중 사진 학습 실험은 수행하지 않았다.

## 검증과 남은 한계

- 공식 모델 neutral, jaw .3/.6, pucker, smile, full blink 렌더링을 저장했다.
- 실제 기본 WAV → A2F 140프레임 → 공식 렌더러 영상을 만들었다:
  `artifacts/oral-v6/official-a2f-wav.mp4`. 최대 입력 jawOpen 약 .526.
- 브라우저 최종 WAV 세션 `b371f900d4f04291977debed`: 입력 모션 140개,
  실제 렌더링된 발화 프레임 135개, PTS 2.7–4633.3ms, 평균 GPU 렌더
  8.88ms. 서로 다른 표시 주기에 따라 브라우저가 최신 포즈를 샘플링하므로
  입력과 표시 프레임 수가 반드시 같지는 않다.
- 브라우저 Realtime 시험 세션 `e1dee5a6707d4509914bddcc`:
  “좋은 소식이 있어!” → LLM happy/celebrating 75%, 음성 5.6초,
  모션 169프레임, underrun 0, sync timeout 0. 마이크 실제 녹음은 이번
  검증에 포함하지 않았으며 텍스트 입력 → 음성 답변 경로를 검증했다.
- 단독 워커 검사 렌더 약 8–14ms/프레임. 브라우저/다른 GPU 작업과
  겹칠 때 FPS와 지연이 증가했다. 최대 FPS를 지속 성능으로 보장하지 않는다.
- 자동 검증: frontend 63 통과, Gaussian backend 46 통과/1 선택적 검사 생략,
  build 및 변경 파일 lint 통과.
- 입 내부는 공식 모델이 학습한 외형이며 별도의 혀 제어 채널은 없다.
  FLAME 근사 변환의 극단 표정/조합까지 무결점이라고 주장하지 않는다.
  원래 녹화 시퀀스보다 학습 분포 밖의 표정은 낮은 품질일 수 있다.

## 로그와 재현

- `data/gaussian/sessions/<id>/`: 음성·원시 A2F·합성 표정·클라이언트 telemetry.
- `data/gaussian/official-live/frames.jsonl`: 발화 프레임 입력, PTS, FLAME jaw,
  expression norm, 렌더 시간. idle은 30프레임마다 기록한다.
- `data/gaussian/official-live/retarget-fit.json`: 채널별 FLAME 적합 잔차.
- `workers/gaussian_lab/check_official_live.py`: 고정 포즈 실제 GPU 검사.
- `workers/gaussian_lab/render_official_wav.py`: 실제 A2F WAV 동영상 재현.

출처:
- https://github.com/aigc3d/LAM
- https://github.com/ShenhanQian/GaussianAvatars
- https://github.com/ShenhanQian/GaussianAvatars/blob/main/doc/download.md
- https://github.com/xg-chu/ARTalk
- https://github.com/xg-chu/GAGAvatar
