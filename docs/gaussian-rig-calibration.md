# 3DGS 얼굴 비율·눈 감김 보정 (2026-09-23)

## V4 수정 — V3 비율 보정 철회

사용자 확인에서 V3의 하관 축소·입 주변 확장이 과도해 얼굴이 납작하고 목에 비해 작아 보였다. 아래 V3의 수동 형상 프로필은 더 이상 권장하지 않는다. 테스트 통과와 사용자 관점의 외형 품질은 별개다.

현재 기본 선택은 `57f19b81b75546458028bbf2` (**서연 v4 · 원본 비율·사진 시점**). V2의 변형 없는 중립 형상을 사용하고 눈 감김 보정만 유지한다. `source_camera.py`가 FLAME 추적에서 저장한 초점거리·global pose·root joint와 GLB 좌표 이동을 반영해 원본 촬영 시점을 복원한다. renderer의 공통 FOV/카메라 배치 대신 이 자산별 정보를 사용한다. **사진 기준 정면 복원** 및 **초기화**로 카메라를 복원할 수 있다.

새 생성에도 source_camera를 manifest에 저장한다. 실제 생성 검증 로그: `data/gaussian/jobs/source-camera-smoke-20260923/` (35.1초). 카메라 역변환의 3D 투영 동등성 테스트를 포함해 워커 10개, 웹 9개 통과. 웹 빌드·lint 통과. 검사 화면에서 입력 사진과 나란히 비교할 수 있다(구도/배율은 다름).

이 복원은 촬영 시점 추정치의 적용이며 사진과 픽셀 단위 일치를 보장하지 않는다. 원본의 expression/neck pose는 중립 ARKit rig에 굽지 않았다. LAM의 단일 사진 재구성 및 중립 표정 변환에서 남는 입술·윤곽 차이는 별도 문제다. 인종별 정확도를 비교한 평가가 없어 이 문제를 한국인 얼굴 탓으로 결론 내릴 근거가 없다.

## V3 기록 (이전 구현)

사용 아바타: `111dd3d667564d5599c0df4c` / **서연 v3 · 얼굴 리그 보정**.
원본 V2와 입력 PNG는 보존했다. 이미지 재생성 대신 네이티브 GLB/PLY를 수정했다.

## 수정 내용

- `workers/gaussian/calibrate_asset.py`: 실제 Gaussian 중심에서 주변 메시의 눈 감김 변위를 보간한다. 학습된 offset 때문에 중심과 원래 메시 앵커가 어긋나는 문제를 완화한다.
- 이 아바타만 `--lower-face` 프로필을 적용했다. 정면 하안부의 입과 턱 위치를 위로 이동하고 입 주변 폭을 완만하게 늘린다. 모든 morph와 Gaussian 공분산도 함께 변환한다. 자동 사진 정합 결과가 아니라 사용자 피드백에 따른 수동 비율 보정이다.
- 렌더러: SDK Idle 애니메이션을 중지해 기본 목/몸 자세가 수동 제어를 덮어쓰지 않게 한다. 세로 FOV 22도와 더 먼 카메라로 원근 왜곡을 줄인다.
- `blinkOcclusion.ts`: 감기는 눈꺼풀 위로 이동하는 안구 영역 splat의 알파를 줄이는 가시성 보정을 추가한다. 입력 색상은 바꾸지 않는다. 독립적인 안구/눈꺼풀 메시를 재구성한 것은 아니며, LAM 좌표계에 맞춘 근사 보정이다.
- 새 사진 생성에는 눈 변위 보정만 자동 적용한다. 하안부 비율 보정은 다른 인물에 자동 적용하지 않는다.

## 재현 및 검사

```powershell
docker exec gaussian-gaussian-worker-1 python /gaussian-worker/calibrate_asset.py /gaussian-data/avatars/fb9fb5de68514e48b4268b7e/asset.zip /gaussian-data/seoyeon-rig-v3.zip --lower-face
docker exec -w /gaussian-worker gaussian-gaussian-worker-1 python -m unittest test_calibrate_asset test_export_asset test_service test_attention
pnpm --dir apps/web test src/gaussian
pnpm --dir apps/web build
```

대화 화면 하단 **눈 감김·입 모양 검사** 링크(`/gaussian/rig-check`)에서 자동 깜빡임 없이 눈 감김, 턱, 좌우 회전을 고정해 관찰할 수 있다. 검사 페이지는 마이크나 외부 음성 API를 사용하지 않는다.

검증: 워커 9개 + 웹 9개 테스트, 웹 빌드 및 gaussian 디렉터리 lint 통과. 실제 사진→아바타 생성→자동 보정도 완료(33.4초). 로그: `data/gaussian/jobs/rig-calibration-smoke-20260923/worker.log`, 출력 및 manifest: `data/gaussian/rig-calibration-smoke/`.

자산 ZIP의 `calibration.json`에 프로필과 눈 보정 범위를 기록한다. 렌더러 진단/대화 telemetry에 `eyeOcclusion`, `portraitFov`를 추가했다. 브라우저에서 중간·완전 눈 감김, ±12도 회전, 턱 벌림 0.3을 시각적으로 점검했다. 완전히 닫힌 눈의 위쪽에 보이던 큰 눈동자 잔상은 제거되었다. 극단적인 표정 조합 및 다른 인물에 대한 무결함은 보장하지 않는다. 단일 사진 기반 고정색 splat 특성상 눈 경계와 큰 회전의 품질은 추가 보정 여지가 있다.
