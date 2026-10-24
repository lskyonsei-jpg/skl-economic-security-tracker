# reference/ — 사이트 빌드가 읽는 외부 자료 사본

빌더가 읽는 정적 참조 파일만 둔다. API 로 받는 자료(GTA, BSV·DOTS·WDI, AI 협력 사건)는 `data/` 에 생기며 git 에 넣지 않는다.

2026-10-23: 패널 1 지도·HS 필터·옛 0·1 진영 화면의 잔재 `ne_110m_admin_0_countries.geojson`, `HSCodeandDescription.xlsx`, `geopolitical_bloc_0_1.json` 을 지웠다(git 이력에 남아 있다).
2026-10-22: 반도체·석유·태양광 화면 삭제로 `comtrade_*.json`, `hs2017_to_hs2022.json`, `oecd_semiconductor_hs.json` 을 지웠다(git 이력에 남아 있다).

## BSV · IMF DOTS · WDI — 더 이상 여기 두지 않는다

2026-10-22부터 `collect_reference.py` 가 API 로 받아 `data/reference/`(git 제외)에 쓰고, 워크플로가 매월 4일 갱신해 Release `state` 의 `reference.tar.gz` 로 보관한다. 출처·질의·주의사항은 그 스크립트 머리말에 있다. BSV 는 Dataverse 파일 ID 로 고정한다(판마다 재추정되어 값이 달라지므로).

## 그 이전부터 있던 파일

| 파일 | 쓰는 곳 | 출처 |
|---|---|---|
| `ai_coop_orgs.csv` | `collect_ai_coop.py`, `ai_coop_tasks.py` — 패널 2 기관 표기 마스터(표준 표기·type) | 자체 코딩 |

위 표의 수집일·정리 방법은 코드 주석 수준으로만 남아 있다. 갱신할 때 이 README에 날짜와 절차를 보강한다.
