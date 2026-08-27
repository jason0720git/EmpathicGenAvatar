# 기술·비용·로드맵 지속 업데이트 운영

마지막 확인: **2026-08-25**  
목표: 비교표가 한 번 만든 보고서로 끝나지 않고, 가격·코드·라이선스·로컬 재현 결과가 바뀔 때 의사결정까지 추적되게 한다.

## 1. 단일 진실 원천

| 정보 | authoritative file |
|---|---|
| 후보 목록·현재 상태 | [TECHNOLOGY_REGISTRY.csv](TECHNOLOGY_REGISTRY.csv) |
| 사람이 읽는 상세 비교 | [기술 비교표](../02-landscape/TECHNOLOGY_COMPARISON.md) |
| 가격·원가 산식 | [비용·용량 모델](../02-landscape/COST_AND_CAPACITY.md) |
| architecture 선택 | [의사결정 기록](DECISION_LOG.md) |
| 학습 단계와 data gate | [데이터·학습 로드맵](../03-roadmap/DATA_AND_TRAINING_ROADMAP.md) |
| 실측 protocol | [평가·벤치마크 계획](../03-roadmap/EVALUATION_AND_BENCHMARK.md) |

동일 가격·FPS·라이선스 문구를 여러 파일에 복사할 때는 레지스트리의 `last_verified`와 source URL을 함께 갱신한다.

## 2. 근거 등급

### provenance tag

- **[L] Local**: version, HW, command, raw log가 보존된 로컬 재현
- **[O] Official**: 공식 문서, 공식 저장소, 공식 가격표에 명시
- **[P] Paper**: 저자 논문의 조건부 결과; 로컬 미재현
- **[V] Vendor claim**: 공급사 설명/마케팅; 독립 또는 로컬 미검증
- **[H] Hypothesis**: 설계 가설, 목표, planning envelope

### evidence grade

| 등급 | 조건 | 사용 범위 |
|---|---|---|
| A | 재현 가능한 local benchmark + manifest + raw metric | 제품 선택/SLO/용량 계획 |
| B | official code/doc/paper에 조건이 명확하고 현재 날짜에 확인 | spike 우선순위와 예산 가설 |
| C | vendor claim 또는 조건이 불완전한 paper number | watchlist/검증 질문 |
| D | 제3자 글, 데모 인상, snippet만 존재 | 탐색 lead; 비교표의 확정 수치 금지 |

공급사 가격표는 official이어도 미래 가격을 보장하지 않는다. grade B이며 `last_verified`가 30일을 넘으면 stale로 본다.

## 3. 업데이트 주기

### 주간 — 20~40분

- 핵심 GitHub release/tag/README/model card 변화 확인
- 공개 weight 또는 realtime code availability 변화 확인
- 공식 pricing/plan/concurrency/overage 페이지 변화 확인
- 라이선스 파일과 territory 문구 hash 변화 확인
- 주요 paper/project page의 code link 공개 여부 확인
- 레지스트리의 `next_review`와 `status` 갱신

### 월간 — 반나절

- 제품 후보의 latest pinned commit으로 smoke benchmark
- 고정 5초/30초/10분 clip에서 FPS, RTF, VRAM, A/V skew 측정
- 상용 서비스 3개에 동일 script spot-check
- 10분 세션 비용과 예상 월량 scenario 재계산
- `DECISION_LOG`의 재검토 조건 평가
- stale row(30일 초과 가격, 90일 초과 기술)를 issue로 만든다.

### 분기 — 1~2일

- 전체 T0–T3 benchmark와 blind human evaluation
- 라이선스/데이터 권리 법무 재검토
- build-vs-buy-vs-partner 재평가
- 3/6/12개월 roadmap와 data collection gate 수정
- 공급사 demo가 아니라 실제 사용량 invoice/incident를 원가 모델에 반영

## 4. 변경 감지 자동화 계획

문서만으로 자동 업데이트가 일어나지는 않는다. 다음을 작은 CI job으로 구현하고 사람이 승인해야 한다.

| 감지 | 방법 | 자동 action | 사람 검토 |
|---|---|---|---|
| GitHub release/tag | 공식 repo API/RSS | issue에 old/new tag와 date | changelog/weight/license 확인 |
| README/model card | pinned URL content hash | diff artifact 저장 | 성능 조건이 실제 공개판인지 확인 |
| LICENSE | raw file hash | `license_change` P0 issue | 법무/제품 차단 여부 |
| 가격표 | official page snapshot + structured field | old/new plan diff | hidden minimum/rounding/tax 확인 |
| 링크 장애 | weekly link check | broken-link issue | URL 이전 또는 서비스 종료 확인 |
| 레지스트리 stale | date rule | review issue | 실측/결정 갱신 |

자동화가 웹페이지의 문구를 바로 제품 수치로 쓰게 하면 안 된다. 특히 pricing DOM에는 stale content가 같이 남을 수 있으므로 실제 표시 화면과 official API/도움말을 교차검증한다.

## 5. 한 후보 업데이트 절차

1. **식별**: 이름, vendor/lab, category와 기존 row를 찾는다.
2. **공식 출처 확보**: paper, official repo, license, model card, pricing/docs URL.
3. **공개 상태 분해**: paper only / code / weight / training / realtime app를 별도 확인한다.
4. **조건 기록**: resolution, fps, GPU, precision, step, precomputation, 포함/제외 단계.
5. **권리 확인**: code와 weight license, transitive dependency, territory, commercial restriction.
6. **control surface 확인**: semantic API인지, driver video인지, 내부 latent 편집인지 구분한다.
7. **로컬 smoke**: 가능하면 pinned commit과 exact asset으로 benchmark manifest 생성.
8. **비용 재계산**: 분당 가격, 최소 billing unit, 포함량, overage, utilization.
9. **레지스트리 갱신**: status, evidence, last/next review, decision.
10. **결정 영향**: 우선순위가 바뀌면 `DECISION_LOG`에 새 행을 추가한다.

## 6. 수치 입력 체크리스트

FPS 하나를 넣기 전에:

- output fps 설정인가, 실제 generation throughput인가?
- model forward만인가, audio feature/VAE/composite/encode/network도 포함하는가?
- batch/parallelism 때문에 단일 세션 latency와 다른가?
- cold/warm 어느 조건인가?
- reference video/audio feature가 미리 계산됐는가?
- 해상도, frame count, precision, sampling step은?
- paper model과 현재 공개 weight가 같은가?
- report date와 release date는?

VRAM 하나를 넣기 전에:

- allocated, reserved, process peak 중 무엇인가?
- detector/encoder/VAE/TTS가 포함되는가?
- single/multi GPU인가?
- offload와 품질 손실은?

가격 하나를 넣기 전에:

- 통화, tax, 지역, annual/monthly billing
- 포함 minute/credit와 실제 환산
- overage, 최소 charge/rounding
- idle/listening time도 과금되는가
- LLM/STT/TTS/WebRTC가 포함되는가
- concurrency/session limit
- custom avatar/voice 비용
- enterprise minimum/egress/support

## 7. 로컬 benchmark ID

```text
<date>-<renderer>-<commit8>-<gpu>-<precision>-<profile>

예:
20260825-musetalk-0a89dec4-rtx5090-fp16-speaking30s
```

manifest 필수 항목:

```yaml
run_id: 20260825-...
code:
  repo: ...
  commit: ...
  dirty: false
model:
  weight_sha256: ...
  license_snapshot_sha256: ...
environment:
  gpu: RTX 5090
  driver: ...
  cuda: ...
  runtime: ...
input:
  asset_id: cleared_test_avatar_v1
  audio_sha256: ...
  duration_s: 30.0
config:
  resolution: 512x512
  target_fps: 25
metrics_artifact: metrics/<run_id>.json
```

dirty tree 결과는 탐색 자료로 보존할 수 있지만 grade A가 될 수 없다.

## 8. 재평가 trigger

달력 주기와 무관하게 즉시 검토한다.

- Lip Forcing 1.3B weight 또는 realtime app 공개
- Ditto official control API/새 model release
- Avatar Forcing realtime/acceleration code 또는 상업 가능 license 공개
- StreamAvatar code/weight 공개
- Tavus/HeyGen/PERSO의 frame-level gesture/head/gaze API 공개
- price ≥15% 변화 또는 billing unit 변경
- license/territory 변화, 특히 대한민국 포함 여부
- 로컬 GPU/runtime 변경
- benchmark에서 제품 기본 renderer가 RTF ≥1 또는 safety gate 실패
- 10건 이상 같은 표정 모순 failure가 누적
- 월간 사용량이 상용/자체 hosting 손익분기점의 ±20%에 도달

## 9. 업데이트 PR/checklist template

```markdown
## Technology update: <name>

- 확인일:
- 공식 source URL:
- old → new:
- 공개 artifact: code / weight / training / realtime app
- license/territory impact:
- performance condition:
- local reproduction run id:
- price/capacity impact:
- affected docs/registry rows:
- decision change: yes/no
- next review:
```

검토자는 최소 다음을 확인한다.

- [ ] source가 검색 snippet/제3자 블로그가 아닌가
- [ ] vendor/paper/local 숫자가 구분됐는가
- [ ] 동일 이름의 commercial product와 research model을 혼동하지 않았는가
- [ ] code license와 weight/dependency license를 모두 확인했는가
- [ ] 한국에서 사용할 수 있는가
- [ ] 제품 SLO 정의와 같은 측정인가
- [ ] 비용 산식의 사용량·utilization 가정이 드러나는가
- [ ] 레지스트리와 decision log가 함께 갱신됐는가

## 10. 역할

초기 소규모 팀에서는 사람 이름 대신 역할을 둔다.

| 역할 | 책임 |
|---|---|
| R&D owner | model/repo/paper, local reproduction |
| Platform owner | latency/concurrency/GPU/transport |
| Product/UX owner | context fit, user study, failure taxonomy |
| Privacy/Legal reviewer | likeness/voice/data/license/territory |
| Finance owner | invoice, utilization, monthly scenario |

한 사람이 여러 역할을 맡을 수 있지만 license와 가격 변화는 개발자 한 명의 암묵지로 남기지 않는다.

## 11. 초기 추적 backlog

- [ ] 전체 untracked 작업 트리를 검토해 첫 재현 가능한 commit과 release tag 생성
- [ ] vendor/model manifest와 third-party license SBOM 작성
- [ ] 손상된 Ditto patch를 current vendor diff에서 재생성
- [ ] RTX 5090 MuseTalk/LivePortrait/ Ditto grade-A baseline 생성
- [ ] Lip Forcing 1.3B release watcher
- [ ] commercial plan snapshot과 월량 cost sheet 연결
- [ ] LICENSE/territory hash watcher
- [ ] 30일 stale-price / 90일 stale-tech issue 자동화
- [ ] 분기 blind comparison calendar 지정

## 12. 변경 기록

| 날짜 | 변경 | 근거/영향 |
|---|---|---|
| 2026-08-25 | 최초 registry, architecture, cost/data/eval 체계 생성 | 첨부 조사 PDF, 저장소 감사, 공식 문서·repo·paper 조사 |
