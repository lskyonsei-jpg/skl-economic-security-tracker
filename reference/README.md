# reference/ — 사이트 빌드가 읽는 외부 자료 사본

이 폴더 밖의 파일은 어떤 빌더도 읽지 않는다(예외: GTA Threads·Comtrade 원자료, HANDOFF 3단계에서 정리). 밖에서 가져온 파일은 원본 파일명을 그대로 두고 여기에 사본을 둔다.

## 2026-10-22 추가 — 볼트 `02_인덱스/원자료/Benchmark/` 사본

### `2026 Voeten - Ideal point estimates 1946-2025.tab`

- 쓰는 곳: `ip_risk_site.py`(BSV), `bloc_site.py`(BSV), `build_oil_data.py`(`bs.BSV` 재사용)
- 내용: Bailey–Strezhnev–Voeten UNGA 투표 ideal point, 국가–연도 11,610행, 197개 국가·실체. 열 `ccode, iso3c, Countryname, year, NVotesFP, IdealPointFP, Q5%FP…Q95%FP`
- 출처: Harvard Dataverse https://doi.org/10.7910/DVN/LEJUQZ (Bailey, Strezhnev and Voeten 2017, https://doi.org/10.1177/0022002715595700)
- 사본 원본 파일 날짜: 2026-07-29
- 갱신: Dataverse에서 최신 "Ideal point estimates" tab 파일을 내려받아 같은 이름으로 덮어쓴다. 연도 범위가 바뀌면 파일명과 위 세 스크립트의 경로를 함께 바꾼다
- 주의: 세르비아는 구 유고 코드 `YUG`로 들어 있어 코드에서 `SRB`로 매핑한다. 2025년 1차원 점수 해석이 불안정할 수 있다는 제작자 경고가 있다

### `20260822_IMF_DOTS_US_CN_total_trade_2010-2025.csv`

- 쓰는 곳: `ip_risk_site.py`(DOTS) — 산점도 speck country 절단용 무역 비중
- 내용: 미국·중국의 상대국별 상품무역 총액(수출 FOB + 수입 CIF 합계), 2010–2025 연간, 7,221행. 열 `reporter, partner_iso3, year, trade_total_usd`. 파트너 `G001` = World
- 출처: IMF SDMX 2.1 API, dataflow `IMF.STA:IMTS(1.0.0)`. 엔드포인트 `https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS/{COUNTRY}.{INDICATOR}.{COUNTERPART}.{FREQ}`, 질의 `USA.XG_FOB_USD+MG_CIF_USD..A` / `CHN.XG_FOB_USD+MG_CIF_USD..A`
- 수집일 2026-08-22, 자료 갱신일(`UPDATE_DATE`) 2026-08-05
- 갱신: 같은 질의로 다시 받아 두 지표를 합산해 저장한다. 파일명 앞 날짜를 수집일로 바꾸고 `ip_risk_site.py`의 경로를 맞춘다
- 주의: 상품무역만이다. 안도라·리히텐슈타인·모나코는 별도 보고가 없다

### `20260822_WDI_GDP_current_USD_2010-2025.csv`

- 쓰는 곳: `ip_risk_site.py`(GDP) — 산점도 절단의 대안 기준(GDP 상위 N)
- 내용: World Bank WDI `NY.GDP.MKTP.CD`(GDP, current US$), 2010–2025, 집계 단위 제외 217개 경제, 결측 제거 후 3,339행. 열 `iso3, country, year, gdp_usd`
- 출처: `https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD`
- 수집일 2026-08-22, 자료 갱신일(API `lastupdated`) 2026-07-13
- 갱신: 같은 엔드포인트에서 받아 `region == "Aggregates"`를 제외하고 저장한다. 파일명과 `ip_risk_site.py` 경로를 맞춘다
- 주의: 8개국(CUB·ERI·PRK·SMR·SSD·SYR·YEM·YUG 일부 연도)은 관측이 없다

## 그 이전부터 있던 파일

| 파일 | 쓰는 곳 | 출처 |
|---|---|---|
| `comtrade_reporters.json`, `comtrade_partners.json` | `build_oil_data.py`, `build_solar_data.py` — Comtrade 숫자코드 → ISO3 | UN Comtrade 참조 API(reporterAreas / partnerAreas). 파일 날짜 2026-08-29 |
| `ne_110m_admin_0_countries.geojson` | `semiconductor_site.py`, `bloc_site.py` — 지도 | Natural Earth 1:110m Admin 0(공개 도메인) |
| `hs2017_to_hs2022.json` | `semiconductor_site.py` — HS 판 대조 | WCO HS 2017→2022 상관표를 정리한 것 |
| `oecd_semiconductor_hs.json` | `semiconductor_site.py` — 반도체 HS 코드 집합 | OECD (2019) *Measuring distortions in international markets: the semiconductor value chain*. 원문 PDF가 `OECD_2019_Measuring_distortions_semiconductor_value_chain.pdf` |
| `geopolitical_bloc_0_1.json` | `industrial_policy_site.py` — 진영 분류 | 자체 코딩 |
| `HSCodeandDescription.xlsx` | `industrial_policy_site.py` — HS4 명칭 | UN Comtrade HS 코드 목록 |

위 표의 수집일·정리 방법은 코드 주석 수준으로만 남아 있다. 갱신할 때 이 README에 날짜와 절차를 보강한다.
