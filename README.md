# SKL Economic Security Tracker

사이트: https://lskyonsei-jpg.github.io/skl-economic-security-tracker/
저장소: https://github.com/lskyonsei-jpg/skl-economic-security-tracker

사람이 실행하는 것은 없다. GitHub Actions 가 매일 06:00 KST 에 자료를 받아 분류하고 사이트를 다시 배포한다.

## 사이트

| 화면 | 내용 | 코드 |
|---|---|---|
| `index.html` | 랜딩 — 핵심 수치, 패널 2개, 판단 대기 배너, 최근 변경 리포트 | `publish_site.py` |
| `ip_risk.html` 패널 1 | Distortive Industrial Policy Tracker — GTA(매일 API) × BSV ideal point × IMF DOTS·WDI. 산점도·회귀, 블록 구성 (지도·순위·추이·HS 필터는 2026-10-22 삭제) | `ip_risk_site.py`(자료) + `ip_risk_template.html`(패널 CSS·본문·스크립트) |
| `ai_coop.html` 패널 2 | 한미 AI 협력 트래커 Dashboard — 거래 타임라인(단계별 날짜, 같은 거래는 선으로 연결, 점 클릭 → 거래 목록의 그 행), 단계(lifecycle)별 건수, 이행 사다리(첫 관측 단계 → 현재 단계), 분야×단계, 주체 조합 | `ai_coop_site.py` |
| `records.html` | 거래 목록(레코드 1개 = 거래 1건, 스키마 v2 2026-10-26) — 열 이름은 변수명 그대로(lifecycle·canceled 포함). title 클릭 → 나머지 변수(단계별 날짜·summary·note·merged_from·updates·sources 등), 기관명 클릭 → 그 기관의 현황. `ai_coop_events.xlsx`(레코드 전체, rejected 제외) 다운로드 | `ai_coop_site.py` |
| `review.html` | 판단 대기 — 자동 제안(A 새 사건·B 갱신·C 재검토)에 승인·기각·보류를 적어 GitHub Issue 로 제출 | `ai_coop_site.py` |
| `data.html` | 사이트 JSON, 저장소, 연결된 API 목록, GTA 변경 리포트 목록 | `publish_site.py` (`APIS`) |
| `codebook.html` | 화면 산식·코딩 규칙(`문서/코드북_패널.md`) + GTA 열 정의(`문서/코드북.md`) | `publish_site.py` |
| `r/*.html` | GTA 변경 리포트 | `publish_site.py` |

모든 페이지의 틀(내비·히어로 띠·Last update·푸터)은 `publish_site.page()` 하나가 만든다. 패널 모듈은 JSON 과 본문만 만들고 페이지 사양을 돌려준다(2026-10-23, 패널 1 만 손으로 쓴 내비를 들고 있다가 어긋난 일 이후).

화면 글자는 본문 15pt·보조 13pt, 제목은 Noto Serif KR + 제목색(`--title`). SVG 차트 글자는 viewBox 단위 21px 로 따로 둔다(`assets/site.css`, 연구자 지시 2026-10-22). 주체 표기 `정부(미국)` 은 자료 표준이고 화면에서만 `미국(정부)` 로 보인다(`ai_coop_site.disp`).
2026-10-22 반도체 지도·석유·태양광·석유 검증 화면과 Comtrade 수집은 삭제했다(git 이력에 남아 있다).

## 파이프라인 (`.github/workflows/pipeline.yml`)

패널 1과 패널 2는 독립된 작업(job)으로 병렬로 돈다. 한쪽이 실패해도 다른 쪽과 사이트 배포는 진행된다(실패한 패널은 어제 자료 그대로).

- **plan** — 예약 실행이면 매일 incremental, 일요일(한국 시간) full, 매월 4일 기준자료. 수동 실행이면 입력값. 코드 push 면 둘 다 건너뛰고 빌드만.
- **panel1** (산업정책): 보관함(Release `state`)에서 GTA 자료 내려받기 → `auto_update.py`(GTA API 수집, BERT 분류, 변경 리포트; 멈춤 조건 `guard()`) → 매월 4일 `collect_reference.py` → 바뀐 자산만 보관함에 올림
- **panel2** (한미 AI 협력): 보관함에서 사건·제안 파일 내려받기 → `ai_coop_tasks.py apply`(연구자 결정 반영) → 반영 결과 올림 → `daily`(검색·중복 제거·코딩·제안) → 사건·제안 파일 올림. 단계별 설명은 코드북 "업데이트 Agent 작동 순서"
- **site** (둘 다 끝난 뒤, 실패해도): 보관함 전부 내려받기 → `publish_site.py` → GitHub Pages 배포(마지막 배포와 같은 커밋이면 `.deploy_stamp` 커밋을 만들고 그 커밋으로 배포 실행을 새로 띄운다 — Pages 가 같은 SHA 재배포를 무시하기 때문) → 아티팩트·30일 지난 실행 기록 정리 → 메일(`MAIL_USER`·`MAIL_PASS` 있을 때: 예약 실행 결과와 모든 실패, 수동 실행의 `mail` 입력이나 커밋 메시지 `[mail]` 로도)

코드만 push 하면 자료 갱신 없이 빌드·배포만 한다. `문서/` 는 코드북 2종(`코드북_패널.md`, `코드북.md`)만 빌드를 일으킨다. 수동 실행(Actions → pipeline → Run workflow)에서 패널 1 GTA 모드·기준자료, 패널 2 일일 실행, 메일 여부를 따로 고른다.

## 비밀값 (Settings → Secrets and variables → Actions)

| 이름 | 용도 | 없으면 |
|---|---|---|
| `GTA_API_KEY` | GTA 수집 | 파이프라인 실패 |
| `ANTHROPIC_API_KEY` | 패널 2 자동 코딩(Claude Opus 5.5, effort medium) | panel2 작업 전체(결정 반영 포함) 건너뜀 |
| `MAIL_USER` + `MAIL_PASS` | 매일 예약 실행 결과와 실패를 Gmail 로 보냄(자기 자신에게). `MAIL_USER` = Gmail 주소, `MAIL_PASS` = Google 계정 [앱 비밀번호](https://myaccount.google.com/apppasswords) 16자리(2단계 인증 필요) | 메일 단계 건너뜀 |

연결된 API 전체 목록은 사이트 `data.html`(코드는 `publish_site.py` 의 `APIS`). 패널 2 설계는 `문서/20261022_설계_한미AI협력트래커_자동화.md`.

## 상태 보관

무거운 파일은 git 에 넣지 않는다. Release `state` 가 유일한 상태 저장소이고 워크플로가 매 실행 뒤 덮어쓴다. 사라지면 BERT 재분류에 약 4시간이 든다.

## 디자인

`assets/site.css` 하나가 토큰과 구성요소를 정한다. 규칙은 `문서/20261022_디자인시스템.md`.

## 데이터 해석

- `D_IP_bert_3 == 1` 은 산업정책 후보군이다. 확정 라벨이 아니다.
- GTA Red/Amber 는 외국 상업이익에 해로운 조치, Green 은 비차별적 자유화. 환경 분류가 아니다.
- `Affected Jurisdiction` 은 수혜국이 아니라 상업적 이해가 영향받는 국가다.
- 분석 단위는 intervention. 열 정의와 GTA 가 공지 없이 바꾸는 것들은 `문서/코드북.md`, 화면 산식은 `문서/코드북_패널.md`.

## 로컬에서 확인하고 싶을 때(선택)

```
python -m venv .venv && .venv/Scripts/pip install -r requirements-site.txt
gh release download state -D cache   # master.parquet, logs.tar.gz(→ logs/) 등
PYTHONUTF8=1 python publish_site.py   # site/ 생성
```
