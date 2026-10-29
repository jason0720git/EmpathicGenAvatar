# 지속적인 개발 작업 규칙

설정일: 2026-10-29. 적용 대상: EmpathicGenAvatar의 현재 로컬 체크아웃.

## 매 응답 종료 시 저장

사용자 요청에 따라 변경이 있는 응답은 검토와 관련 검증 후 커밋하고 origin의 같은 이름 브랜치로 푸시한다. 질문만 답하고 파일 변경이 없으면 빈 커밋을 만들지 않는다. 이전 푸시가 실패한 경우 기존 커밋을 재전송한다.

1. `AGENTS.md`가 응답 전에 `scripts/finish_turn.py --message "변경 설명"` 실행을 요구한다.
2. Codex의 공식 `notify` / `agent-turn-complete` 이벤트도 같은 스크립트를 실행한다. 이전 데스크톱 종료 알림은 그대로 전달한다. 이벤트의 `cwd`가 이 체크아웃에 속할 때만 Git 작업을 수행한다.
3. 변경 없는 재실행은 커밋을 추가하지 않는다. 기존 Git LFS pre-push 훅을 유지한다.

참고: [Codex 공식 notify 문서](https://learn.chatgpt.com/docs/config-file/config-advanced). Stop 훅과 별개의 공식 종료 알림 기능을 사용한다. 새 프로세스/채팅에서 설정이 로드된다. 실행 중인 채팅의 설정 자동 재로드는 보장하지 않으므로, 최초 실제 종료 이벤트 수신 여부는 아래 로그로 확인한다. 응답 전 실행 규칙은 이와 별도로 적용한다.

```powershell
.\.venv\Scripts\python.exe scripts/install_codex_notify.py
.\.venv\Scripts\python.exe scripts/finish_turn.py --message "Describe the completed change"
.\.venv\Scripts\python.exe -m unittest discover -s scripts -p test_finish_turn.py -v
Get-Content .git/codex-finish-turn.jsonl -Tail 5
```

- 설치 위치: 사용자 Codex 홈의 `repository-notifiers/EmpathicGenAvatar/`.
- 설정: 사용자 Codex 홈의 `config.toml`에서 `notify`만 변경한다. 기존 설정 백업과 원래 알림 명령은 설치 위치에 보관한다. 이 로컬 설정/백업은 저장소에 커밋하지 않는다.
- 해제: 설치 위치의 `codex_notify.json`에 있는 `previous_notify` 배열을 `config.toml`의 `notify` 값으로 복원한다. 이후 다른 설정이 바뀌었을 수 있으므로 전체 백업 덮어쓰기는 피한다. 자동 저장 자체를 중단하려면 `AGENTS.md`의 종료 시 저장 규칙도 변경한다.
- 오류: `.git/codex-finish-turn.jsonl`에 기록한다. 네트워크/인증/원격 충돌로 푸시가 실패해도 로컬 커밋을 보존한다. 자동 force push, pull, merge, rebase는 하지 않는다.
- 실행 중 다른 Git 작업, detached HEAD, 같은 이름의 origin upstream 부재, 10 MiB 초과 일반 Git blob을 거부한다. 필요한 바이너리는 먼저 LFS를 설정한다.
- 락 파일은 중복 finalizer 실행을 막는다. 비정상 종료 후 락이 남으면 실제 실행 중인 finalizer가 없는지 확인한 뒤 `.git/codex-finish-turn.lock`만 제거한다.
- **동일 체크아웃에서 여러 편집 채팅을 동시에 실행하지 않는다.** 저장할 때 기존 staged 변경을 포함한 모든 non-ignored 변경을 포함한다. 병렬 작업은 별도 체크아웃을 사용한다. 새 체크아웃의 자동 알림은 별도 설정이 필요하다.
- 후처리 콜백은 테스트 통과 여부를 판정하지 않는다. 에이전트가 응답 전에 검증하고 그 결과를 보고해야 한다. 실패한 검사나 미완성 작업은 완성된 기능으로 설명하지 않는다.

## 설치한 스킬

[OpenAI 공식 curated skills](https://github.com/openai/skills/tree/main/skills/.curated)에서 skill-installer로 설치했다. 설치 범위는 사용자 Codex 홈의 `skills/`이며 저장소 외 다른 채팅에서도 사용할 수 있다. 새 스킬은 다음 턴부터 사용 가능하다.

| 스킬 | 이 프로젝트에서의 용도 |
| --- | --- |
| gh-fix-ci | GitHub Actions 실패 로그와 원인 분석, 수정 검증 |
| gh-address-comments | PR 리뷰 의견 추적 및 반영 |
| playwright | 브라우저에서 표정/시선/아바타 UI 흐름 검증 |
| jupyter-notebook | Ditto/LAM 실험, 지연시간·품질 비교를 재현 가능한 노트북으로 기록 |
| security-best-practices | Python/FastAPI 및 TypeScript/웹 보안 검토 요청 시 사용 |
| security-threat-model | 업로드, 미디어 처리, 모델 실행 경계의 위협 분석 요청 시 사용 |

스킬 설치와 실행 의존성 설치는 별개다. GitHub 스킬 실행 시 `gh`와 인증, Playwright 실행 시 Node/npm의 `npx`를 확인한다. 현재 셸에서는 `gh`와 `npx`가 PATH에서 발견되지 않았다. 기존 앱 번들 런타임이나 설치 경로를 먼저 확인하고 해당 작업 시 필요한 실행 환경을 준비한다. 이번 설정 작업에서 새 브라우저나 GPU 모델을 다운로드하지 않았다.

문서/PDF/스프레드시트/프레젠테이션, OpenAI Docs 등 이미 제공되는 스킬은 중복 설치하지 않았다. 저장소 전용 판단 기준은 `AGENTS.md`에 유지한다. 설치만으로 무관한 배포, 외부 메시지 발송, 보안 전면 개편을 수행하지 않는다.

## 실험을 기능으로 발전시키는 절차

1. 기존 코드와 실험 문서에서 현재 제어 가능 범위를 먼저 확인한다.
2. 공감 표현의 표정·눈·머리 제어 개선 목표와 관찰 가능한 성공 기준을 정한다.
3. 논문/공식 코드 근거와 실제 측정 결과를 구분해 기록한다. Ditto와 LAM 기존 경로를 비교 기준으로 유지한다.
4. 작은 변경을 구현하고 영향받은 모듈의 테스트 및 필요한 시각 검증을 수행한다.
5. 결과와 한계를 문서에 남기고, 생성 출력은 `artifacts/` 또는 `tmp/`에 보관한다. 필요한 코드/문서/배포 자산만 커밋·푸시한다.
