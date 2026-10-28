# LAM 기준 복구 및 CAP4D 실행 기록

2026-09-29. 사용자 요청: 두 얼굴의 무수정 LAM 비교와 CAP4D 재생성을 자동 수행하고 테스트.

## 완료 / 미완료

- **LAM 기준 비교 완료**: Emma·서연 원본 사진으로 재생성, 프로젝트의 비율·눈·구강 보정 제외. 각 20,018 Gaussian. 공식 Python 변형/렌더러로 중립·턱 회전 4개와 동일 기록된 FLAME 표정 90프레임을 렌더링했다. 웹에서도 원본/기존 자산을 중립·blink=1·jawOpen=.6 조건으로 대조했다.
- **CAP4D 생성 미완료**: 공식 `flame2023_no_jaw.pkl` 누락으로 upstream smoke 실행이 FileNotFoundError에서 중단됐다. 사용자가 해당 파일을 보유하지 않았다고 확인했다. 다른 `flame2023.pkl`로 대체하지 않았다.
- CAP4D의 환경·가중치·CUDA 커널 검증은 완료했으나, 전체 생성·개인화 학습·품질 검증은 아직 수행하지 못했다. Pixel3DMM의 Python 패키지는 설치했지만 MICA/PIPNet/facer 등 전처리 종속 저장소·가중치 구성과 맞춤 얼굴 추적은 미완료다.
- 기존 자산과 서비스는 보존했다. 생성 테스트 동안 정지했던 `audio2face-3d`, `gaussian-official-live`를 복원했다. 생성 워커는 기존처럼 정지 상태다.

## 실제 결과

### 구강

웹 렌더러·색 보정·추가 구강 geometry를 사용하지 않는 공식 LAM Python 경로에서도 두 얼굴 모두 큰 입 벌림에서 밝은 살색의 평평한 구강 내부가 나타났다. 따라서 추가 치아/화면 셰이더만 제거하면 해결되는 문제가 아니다. 사진에서 관측하지 못한 구강 생성 품질과 표현 모델이 원인의 일부다. 독립적으로 움직이는 혀가 복원된 것으로 해석할 수 없다.

`native-jaw-contact.png`의 jaw 값은 FLAME 관절 회전 0, .10, .25, .45 **radian**이다. 웹 ARKit jawOpen의 0~1 값과 같은 단위가 아니므로 Python/웹 프레임을 수치가 같은 정확한 모션 대조라고 주장하지 않는다.

### 눈

두 무보정 웹 아바타 모두 blink=1이 requested/applied/uploaded까지 전달되지만 눈꺼풀 위로 안구가 노출된다. 기존 보정본은 노출을 줄이지만 눈꺼풀이 평평한 면으로 보이는 한계가 남는다. 채널 전달 오류와 외형/리그/가림 문제를 분리했다. Python의 개별 ARKit blink=1 동등 조건은 검사하지 않았으므로, 이 눈 결과를 공식 Python FLAME 렌더러 전체의 실패로 일반화하지 않는다.

### 자산 변화

같은 topology의 처음 20,018 정점을 비교했을 때 기존 보정본과 새 기준 자산의 평균 위치 차이는 Emma 1.211mm, 서연 1.253mm, 최대 차이는 각각 9.911mm, 8.592mm다. 이것은 **보정으로 바뀐 정점량**이며 원본 사진 대비 오차나 품질 점수가 아니다. 표정 morph도 다수 변경돼 있었다.

정면 사진과 중립 렌더링에는 목 자세·중립화·카메라 등의 차이가 남는다. 무보정 기준을 원본 사진과 완전히 일치하는 생성 결과로 주장하지 않는다. 인종 원인도 결론 내리지 않는다.

## 사용 가능한 결과

- 비교 페이지: http://127.0.0.1:5174/gaussian-review-v9/index.html
- 직접 조작: http://127.0.0.1:5174/gaussian/rig-check
- 새 진단용 라이브러리 항목:
  - `Emma · LAM 무보정 비교용 v9` / `b90000000000000000000001`
  - `서연 · LAM 무보정 비교용 v9` / `b90000000000000000000002`
- 위 두 항목은 **개선된 최종 아바타가 아닌 비교 기준**이며 generation.quality_pass=false로 기록했다.
- 리그 검사에 `눈·구강 셰이더 보정 해제 (원인 비교)`를 추가했다. 기본 동작은 기존 보정 유지이며 진단 화면에서만 끌 수 있다. 자산/설정 전환 시 이전 진단값을 지우고 로딩 상태를 보여준다.

증거 파일은 `data/gaussian/reconstruction-v9/`에 있다:

- `emma/`, `seoyeon/`: native 중립·개구 캡처, 90프레임 영상, Gaussian tensor, 생성 manifest, 원본 ZIP, native-validation.json
- `web/`: 두 캐릭터 × 무보정/현재 × 중립/눈 감김/입 벌림 캡처
- `asset-comparison.json`: 정점 및 채널별 보정 차이
- `baseline-library.json`: 등록 ID와 asset hash
- `logs/lam-*.log`: 생성·추적·렌더링 전체 로그

## CAP4D 준비 및 외부 차단 조건

- CAP4D commit `1f25e99702ab5c0b38aa5e195fdd6cd963fa528c`
- Pixel3DMM commit `98b5d79f18bc478282494be02f984dc93f5c9fe9` (CAP4D의 지정 버전)
- 독립 컨테이너 `gaussian-cap4d-lab`, 기존 CUDA 12.8/Torch 2.11 이미지 기반. 종료 후 컨테이너와 캐시를 보존한다.
- MMDM checkpoint 3,597,740,988 bytes. SHA-256 `13799d7215dcfe7d197cf98584fcd23a51521b87a9d22b463e98bd9073e75ff0`가 공식 Hugging Face LFS hash와 일치했다. 830개 tensor를 읽고 유한값을 확인했다.
- gsplat 1.5.3: RTX 5090에서 CUDA extension 빌드 및 forward/backward 유한값 검사 통과. 이는 전체 MMDM의 VRAM 적합성·학습 성공·품질을 입증하지 않는다.
- Python 패키지 충돌을 NumPy 1.26.4 / OpenCV 4.11 / ml-dtypes 0.5.4 등으로 정리했다. 최종 freeze는 `logs/cap4d-environment-final.txt`.
- 잔여 `pip check` 경고: Decord 0.6.0 배포 wheel의 cp36 태그와 Python 3.12가 불일치한다. 실제 import와 테스트 영상 90프레임 디코딩은 성공했다. 후속 실행 실패가 생기면 소스 빌드/교체가 필요하며 경고를 숨기기 위해 wheel metadata를 바꾸지 않았다.

**사용자에게 필요한 작업**: [FLAME 공식 사이트](https://flame.is.tue.mpg.de/)에서 본인 계정과 이용 조건으로 FLAME2023을 받아 `flame2023_no_jaw.pkl`을 제공한다. CAP4D 맞춤 추적 설치 스크립트는 MICA용 FLAME2020 `generic_model.pkl`도 요구하므로 FLAME2020 아카이브도 함께 확보하는 것이 좋다. 비밀번호는 공유할 필요가 없다.

공식 파일이 준비되면 계속할 순서:

1. 정식 FLAME 자산을 해당 폴더에 배치하고 upstream pickle 호환 변환을 수행한다.
2. Pixel3DMM 전처리 종속 저장소·가중치 설치를 마치고 입력 사진의 tracking 결과를 확인한다.
3. CAP4D 공식 Tesla debug smoke를 생성→학습→렌더까지 통과시킨다. 아직 이 단계는 통과하지 못했다.
4. Emma·서연 동일 입력의 CAP4D 생성 및 학습을 각각 수행한다. checkpoint와 실패 로그를 보존한다.
5. 동일 native driver로 입·눈·정체성·조합 표정을 평가하고, 품질이 확인된 모델만 live renderer adapter에 연결한다.

CAP4D/Pixel3DMM의 FLAME 모델은 학습된 표현 기저와 결합돼 있으므로 표준 FLAME 파일의 이름만 바꾸는 우회는 부정확하다. 실행 권한 재확인이 필요한 것이 아니라, 현재 없는 공식 모델 파일이 필요한 상태다.

## 검증

- LAM 생성 2건 성공 / 각 native 94개 포즈(정적 4+기록 모션 90), 영상 2건.
- 웹 12개 대조 캡처, native splats=20,018 / derived splats=20,908 확인.
- 웹 build 성공, 변경된 TS 파일 ESLint 성공, Gaussian 기존 테스트 29개 통과.
- ZIP validation 두 자산 통과, Python 파일 syntax 검사 통과.
- CAP4D 공식 smoke: 실패 재현, 누락 파일 명시. `cap4d-preflight.json`에 generation_complete=false, quality_test_complete=false 기록.
- CAP4D checkpoint hash / tensor finite / GPU kernel forward+backward 검사 통과.
- A2F health ready 확인. 생성 워커는 테스트 종료 후 정지 상태.

## 재실행 도구

- `workers/gaussian/generate.py --upstream-baseline`: 기존 기본 생성 동작은 유지하고 진단용 무보정 출력/공식 렌더를 선택 실행.
- `workers/gaussian/native_baseline.py`: native 모션 캡처.
- `workers/gaussian_lab/register_baselines.py`: 기존 ID를 바꾸지 않는 진단용 자산 등록.
- `workers/gaussian_lab/compare_baseline_assets.py`: native 정점·채널 비교.
- `workers/gaussian_lab/build_baseline_review.py`: 로컬 비교 페이지 생성.
- `workers/gaussian_lab/cap4d_preflight.py`: 공식 파일과 가중치 확인. 누락 시 nonzero 종료.
- `workers/gaussian_lab/cap4d_cuda_probe.py`: FLAME 없이 가능한 gsplat 하드웨어 검사.
- `workers/gaussian_lab/Dockerfile.cap4d`: CAP4D 기본 패키지 환경 재현용. Pixel3DMM 전체 전처리 설치 완료 이미지라고 주장하지 않는다.
