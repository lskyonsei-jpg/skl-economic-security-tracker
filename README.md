# SKL Economic Security Tracker

사이트: https://lskyonsei-jpg.github.io/skl-economic-security-tracker/
저장소: https://github.com/lskyonsei-jpg/skl-economic-security-tracker

사람이 실행하는 것은 없다. GitHub Actions 가 매일 06:00 KST 에 자료를 받아 분류하고 사이트를 다시 배포한다.

## 패널

| 패널 | 자료 | 빌더 |
|---|---|---|
| 1. Distortive Industrial Policy Tracker | GTA(매일 API) × BSV ideal point(Dataverse) × IMF DOTS·WDI(API, 월 1회 `collect_reference.py`) | `industrial_policy_site.py` → `ip_risk_site.py` + `ip_risk_template.html` |
| 2. 한미 AI 협력 트래커 | `data/seed/` 연구자 확정 코딩 + 매일 자동 제안(`ai_coop_tasks.py`, 연구자 승인 후 반영) | `ai_coop_site.py` |

반도체 지도·석유·태양광·석유 검증 화면은 코드만 남아 있다(`SITE_EXTRA_PANELS=1` 로 빌드하면 생성). 석유·태양광은 Comtrade 원자료가 있어야 한다.

## 파이프라인 (`.github/workflows/pipeline.yml`)

1. Release `state` 자산 내려받기 — `master.parquet`(GTA 전량 + BERT 라벨), `prediction_cache.json`, `state.json`, `logs.tar.gz`(변경 리포트), `reference.tar.gz`(BSV·DOTS·WDI), 있으면 `comtrade.tar.gz`·`ai_coop_events.json`
2. `auto_update.py --mode incremental|full --yes` — GTA API 수집, BERT 분류(새 건만), 직전 스냅숏과 대조, 변경 리포트. 일요일은 full(전량 재대조, 삭제 확인)
   - 멈춤 조건(`guard()`): 수출통제 9종 유형명 0건, `intervention_id` 결측, 열 수 불일치, 표본 5% 초과 감소, full 삭제 500건 초과 → 실패, Release 는 그대로
3. 매월 4일: `collect_reference.py`(BSV·IMF DOTS·WDI, 키 불필요), `collect_comtrade.py`(키 있을 때)
4. `ai_coop_tasks.py apply` → `daily` — 연구자 결정(사이트 판단 대기 페이지에서 제출한 Issue 또는 `data/ai_coop_decisions.csv`) 반영 후, 탐지 → A 새 사건·B 기존 사건 갱신·C 기존 판단 재검토 제안을 `review.html` 에 게시. AI 는 직접 반영하지 않는다
5. 바뀐 자산만 Release `state` 에 다시 올림
6. `publish_site.py` → `site/` → GitHub Pages

코드만 push 하면 자료 갱신 없이 빌드·배포만 한다. 수동 실행(Actions → pipeline → Run workflow)에서 모드와 Comtrade 수집 여부를 고른다.

## 비밀값 (Settings → Secrets and variables → Actions)

| 이름 | 용도 | 없으면 |
|---|---|---|
| `GTA_API_KEY` | GTA 수집 | 파이프라인 실패 |
| `ANTHROPIC_API_KEY` | 패널 2 자동 코딩(Claude Opus 5.5) | 재코딩·자동 수집 단계 건너뜀 |
| `COMTRADE_API_KEY` | 석유·태양광 원자료(현재 미사용 패널) | 수집 건너뜀 |

패널 2 설계(탐지·코딩·갱신·게시)는 `문서/20261022_설계_한미AI협력트래커_자동화.md`.

## 상태 보관

무거운 파일은 git 에 넣지 않는다. Release `state` 가 유일한 상태 저장소이고 워크플로가 매 실행 뒤 덮어쓴다. 사라지면 BERT 재분류에 약 4시간이 든다.

## 디자인

`assets/site.css` 하나가 토큰과 구성요소를 정한다. 규칙은 `문서/20261022_디자인시스템.md`.

## 데이터 해석

- `D_IP_bert_3 == 1` 은 산업정책 후보군이다. 확정 라벨이 아니다.
- GTA Red/Amber 는 외국 상업이익에 해로운 조치, Green 은 비차별적 자유화. 환경 분류가 아니다.
- `Affected Jurisdiction` 은 수혜국이 아니라 상업적 이해가 영향받는 국가다.
- 분석 단위는 intervention. 열 정의와 GTA 가 공지 없이 바꾸는 것들은 `문서/코드북.md`.

## 로컬에서 확인하고 싶을 때(선택)

```
python -m venv .venv && .venv/Scripts/pip install -r requirements-site.txt
gh release download state -D cache   # master.parquet, logs.tar.gz(→ logs/) 등
PYTHONUTF8=1 python publish_site.py   # site/ 생성
```
