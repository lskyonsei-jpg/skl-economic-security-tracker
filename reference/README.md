# reference/ — 사이트 빌드가 읽는 외부 자료 사본

빌더가 읽는 정적 참조 파일만 둔다. API 로 받는 자료(GTA, Comtrade, BSV·DOTS·WDI, Notion)는 `data/` 에 생기며 git 에 넣지 않는다.

## BSV · IMF DOTS · WDI — 더 이상 여기 두지 않는다

2026-10-22부터 `collect_reference.py` 가 API 로 받아 `data/reference/`(git 제외)에 쓰고, 워크플로가 매월 4일 갱신해 Release `state` 의 `reference.tar.gz` 로 보관한다. 출처·질의·주의사항은 그 스크립트 머리말에 있다. BSV 는 Dataverse 파일 ID 로 고정한다(판마다 재추정되어 값이 달라지므로).

## 그 이전부터 있던 파일

| 파일 | 쓰는 곳 | 출처 |
|---|---|---|
| `comtrade_reporters.json`, `comtrade_partners.json` | `build_oil_data.py`, `build_solar_data.py` — Comtrade 숫자코드 → ISO3 | UN Comtrade 참조 API(reporterAreas / partnerAreas). 파일 날짜 2026-08-29 |
| `ne_110m_admin_0_countries.geojson` | `semiconductor_site.py`, `bloc_site.py` — 지도 | Natural Earth 1:110m Admin 0(공개 도메인) |
| `hs2017_to_hs2022.json` | `semiconductor_site.py` — HS 판 대조 | WCO HS 2017→2022 상관표를 정리한 것 |
| `oecd_semiconductor_hs.json` | `semiconductor_site.py` — 반도체 HS 코드 집합 | OECD (2019) *Measuring distortions in international markets: the semiconductor value chain*. 원문 PDF(`OECD_2019_Measuring_distortions_semiconductor_value_chain.pdf`)는 저작권 때문에 저장소에 넣지 않는다(.gitignore). 필요하면 OECD iLibrary에서 받는다 |
| `geopolitical_bloc_0_1.json` | `industrial_policy_site.py` — 진영 분류 | 자체 코딩 |
| `HSCodeandDescription.xlsx` | `industrial_policy_site.py` — HS4 명칭 | UN Comtrade HS 코드 목록 |

위 표의 수집일·정리 방법은 코드 주석 수준으로만 남아 있다. 갱신할 때 이 README에 날짜와 절차를 보강한다.
