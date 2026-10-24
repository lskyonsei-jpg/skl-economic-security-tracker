"""패널 1 — Distortive Industrial Policy Tracker.

cache/master.parquet(GTA + BERT 라벨)에서 미·중 산업정책 조치를 뽑고, BSV ideal point·IMF DOTS·WDI 와 엮어
site/ip_risk.json(국가·연도 행: ideal point·블록·무역비중·GDP, 블록 구성)과 site/ip_sectors.json(조치 단위 — 산점도는 브라우저에서 다시 집계)을 쓴다.
화면 본문은 ip_risk_template.html(패널 전용 CSS·본문·스크립트), 페이지 틀은 publish_site.page() 가 씌운다.

2026-10-23 industrial_policy_site.py 를 합쳤다. 그 모듈은 조치 목록을 site/ip_us_cn.json(5.8MB, 공개 폴더)으로
써서 여기 넘겼는데, 같이 계산하던 lift·Mann-Whitney·정책수단 검정(옛 ip_us_cn 화면, 2026-08-19 삭제)은 아무도 읽지 않았다.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "cache" / "master.parquet"
# 화면 자료의 시작일. 수집(auto_update.py START_DATE)은 2008-01-01부터지만 화면은 2010-01-01부터(2026-08-18 결정).
SITE_START_DATE = "2010-01-01"
# 기준자료 3종은 collect_reference.py 가 API 로 받아 data/reference/ 에 둔다(2026-10-22, git 제외).
# CI 는 Release "state" 의 reference.tar.gz 에서 내려받는다. 출처는 collect_reference.py 머리말.
REF = HERE / "data" / "reference"
BSV = REF / "bsv_ideal_points.tab"
# 버블 크기용 무역 비중(2026-08-22). McKinsey Exhibit 2는 "Circle size = value of goods
# trade"(절대 금액)를 쓰지만, 여기서는 시행국 총무역 대비 비중을 쓴다.
DOTS = REF / "imf_dots_us_cn_total_trade.csv"
# 버블 크기 대안(2026-08-25) — 피영향국 자체 GDP(절대 규모). trade_share와 달리
# 시행국과 무관한, 그 나라 경제 규모 자체를 나타낸다.
GDP = REF / "wdi_gdp_current_usd.csv"
TEMPLATE = HERE / "ip_risk_template.html"
ALIASES = {
    "United States of America": "United States", "Republic of Korea": "South Korea",
    "DPR Korea": "North Korea", "Turkiye": "Turkey", "Myanmar": "Myanmar (Burma)",
    "Macedonia": "North Macedonia", "Brunei Darussalam": "Brunei", "Lao": "Laos",
    "Ivory Coast": "Côte d’Ivoire", "Republic of Moldova": "Moldova",
    "Congo": "Congo - Brazzaville", "DR Congo": "Congo - Kinshasa",
    "Saint Kitts & Nevis": "St. Kitts & Nevis", "Saint Lucia": "St. Lucia",
    "Saint Vincent & the Grenadines": "St. Vincent & Grenadines",
    "Republic of the Sudan": "Sudan", "Serbia": "Yugoslavia",
    "Sao Tome & Principe": "São Tomé & Príncipe",
    # 2026-08-24 추가 — 역방향 점검(BSV 193개국 중 GTA 이름으로 매핑되지 않는
    # 나라 찾기)에서 유일하게 걸린 alias 누락. 미크로네시아연방은 UN 표결국이라
    # BSV에 ideal point가 있는데도 이름이 달라 "BSV에 없는 관할권"으로 잘못
    # 빠지고 있었다. GTA 전체로는 293건, 미·중 산업정책 표본에는 0건이라
    # 화면 수치는 바뀌지 않는다.
    "Micronesia": "Micronesia (Federated States of)",
}
IMPLEMENTERS = {"United States of America": "United States", "China": "China"}
DOTS_REPORTER = {"United States of America": "USA", "China": "CHN"}
# 빌드타임 스위치(2026-08-25) — GTA의 AJ 등록 방식 4종(Targeted/Inferred/
# Excluded/Incidental) 중 명시적으로 지목(Targeted)된 것만 남길지. 기본은
# False(전체 AJ 유지) — Targeted는 극소수라서(미국 산업정책 Red/Amber 6,263건
# 중 35건, 중국 1,646건 중 13건) 켜면 대부분 화면이 표본 부족으로 사실상
# 빈다. True로 바꾸고 재빌드하면 산점도·구성 전체에 반영된다(Red/Amber 필터와 같은 방식).
TARGETED_ONLY = False

# #DUP_RULE_20260824 — 같은 프로그램의 반복 공고를 1건으로 합친다.
# 아래 6개 필드가 **전부 값이 있으면서 전부 같은** intervention 은 GTA 가 행정 공고 단위로 쪼개 올린 같은 조치로 본다.
# 하나만 남기고 나머지에 dup=True 를 찍는다. 하나라도 비어 있으면 합치지 않는다("결측끼리 같다"를 같은 조치로 오인하지 않게).
# 최대 그룹은 2022년 USDA 생산보조 302건, 다음이 재무부 1603 재생에너지 그랜트 171·124·95건.
DUP_KEYS = [
    "implementing_jurisdictions", "affected_jurisdictions", "intervention_type",
    "eligible_firm", "affected_sectors", "gta_evaluation",
]
MASTER_COLUMNS = sorted(set(DUP_KEYS) | {
    "intervention_id", "date_announced", "date_implemented", "date_removed", "D_IP_bert_3",
    "inferred_jurisdictions"})   # 설명문 등 큰 열은 읽지 않는다


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _split(value, sep: str) -> list[str]:
    return [part.strip() for part in _text(value).split(sep) if part.strip()]


def _dup_ids(ip) -> set[int]:
    """DUP_KEYS 6필드가 전부 유효하고 전부 같은 그룹에서 첫 건 외 나머지 intervention_id."""
    valid = ip[~ip[DUP_KEYS].map(lambda v: _text(v).strip() == "").any(axis=1)]
    ordered = valid.sort_values("intervention_id")
    dropped = ordered[ordered.duplicated(subset=DUP_KEYS, keep="first")]
    return {int(v) for v in dropped["intervention_id"]}


def load_measures() -> list[dict]:
    """master.parquet → 미·중 산업정책(D_IP_bert_3 == 1, 2010+) 조치 목록.

    한 조치의 시행국에 미·중이 둘 다 있으면 양쪽에 한 번씩 들어간다. 평가(Red/Amber/Green) 절단은 build() 에서 한다."""
    import pandas as pd

    df = pd.read_parquet(MASTER, columns=MASTER_COLUMNS)
    df = df[df["date_announced"].fillna("") >= SITE_START_DATE]
    ip = df[df["D_IP_bert_3"] == 1]
    dup_ids = _dup_ids(ip)
    measures = []
    for implementer in IMPLEMENTERS:
        rows = ip[ip["implementing_jurisdictions"].fillna("").apply(
            lambda s, imp=implementer: imp in [p.strip() for p in s.split(";")])]
        for row in rows.to_dict("records"):
            rid = int(row["intervention_id"])
            measures.append({
                "id": rid, "implementing": implementer,
                "date": _text(row.get("date_announced"))[:10],
                "date_implemented": _text(row.get("date_implemented"))[:10] or None,
                "date_removed": _text(row.get("date_removed"))[:10] or None,
                # GTA 의 AJ 등록 방식(Targeted/Inferred/Excluded/Incidental). API 의 affected_jurisdictions_type 을
                # auto_update.py 가 옛 열 이름 inferred_jurisdictions 로 받아 둔다.
                "aj_type": _text(row.get("inferred_jurisdictions")) or None,
                "evaluation": _text(row.get("gta_evaluation")),
                "affected": _split(row.get("affected_jurisdictions"), ";"),
                "dup": rid in dup_ids,
            })
    return measures


def _load_gdp() -> dict:
    """(iso3, year) -> GDP(경상 USD). World Bank WDI, 2010~2025."""
    out = {}
    with GDP.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            if r["gdp_usd"]:
                out[(r["iso3"], int(r["year"]))] = float(r["gdp_usd"])
    return out


def _load_trade() -> dict:
    """(reporter, iso3, year) -> 시행국 총무역 대비 비중."""
    raw = {}
    with DOTS.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            raw[(r["reporter"], r["partner_iso3"], int(r["year"]))] = float(r["trade_total_usd"])
    share = {}
    for (rep, iso, year), v in raw.items():
        if iso == "G001":
            continue
        total = raw.get((rep, "G001", year))
        if total:
            share[(rep, iso, year)] = v / total
    return share


def build(out: Path, asof: str) -> list[dict]:
    """ip_risk.json·ip_sectors.json 을 쓰고 ip_risk.html 의 페이지 사양을 돌려준다. 입력이 없으면 []. asof = GTA 자료 기준일.

    2026-10-23(연구자 결정): 화면이 읽는 필드만 쓴다. 지도·순위·추이(2026-10-22 삭제)용 risk_index·거리·노출 비중,
    재현용 fed_seg·ipd, 산업(HS2) 필터용 필드를 뺐다(ip_risk.json 3.9MB → 1.3MB). 정의는 git 이력과 코드북에 있다."""
    if not all(p.is_file() for p in (MASTER, BSV, DOTS, GDP, TEMPLATE)):
        return []
    measures = load_measures()
    # ---- GTA Red+Amber(차별적·잠재적 차별적)만 사용 (2026-08-25) ------------
    # NIPO 전략동기 태그(national security/resilience/... — Fed IFDP 1408이 쓰는 것)가 우리 원자료엔 없다.
    # 대신 GTA 자체 3단계 평가에서 Green(자유화)만 뺀다 — Red·Amber 는 방향이 보호주의/차별 쪽이고 Green 만 반대라
    # "distortive"라는 이름과 섞으면 안 된다. #DUP_RULE_20260824 키에 gta_evaluation 이 있어 중복 그룹은 늘 평가가
    # 하나라서, 이 절단과 중복 제거는 순서를 바꿔도 결과가 같다.
    total_measures = len(measures)
    measures = [m for m in measures if m.get("evaluation") in ("Red", "Amber")]
    red_count = len(measures)
    if TARGETED_ONLY:
        measures = [m for m in measures if m.get("aj_type") == "Targeted"]
    targeted_count = len(measures)
    positions, countries_by_year = {}, defaultdict(dict)
    with BSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            year = int(r["year"])
            if 2010 <= year <= 2025:
                positions[(year, r["Countryname"])] = (r["iso3c"], float(r["IdealPointFP"]))
                countries_by_year[year][r["Countryname"]] = r["iso3c"]
    trade = _load_trade()
    gdp = _load_gdp()
    ISO_FIX = {"YUG": "SRB"}  # BSV iso3c의 세르비아는 구 유고 코드다

    # 산점도 x축(2026-08-22, 연구자 지시): 각국 BSV ideal point 의 2010~2025 **전 구간 평균**. 기간 슬라이더와 무관하게
    # 고정한다(매킨지도 "distance fixed over the period"). 슬라이더를 움직일 때 x까지 변하면 무엇이 움직인 건지 구분이 안 된다.
    FIXED_YEARS = range(2010, 2026)
    ideal_point = {}
    for country in {c for y in FIXED_YEARS for c in countries_by_year[y]}:
        own = [positions[(y, country)][1] for y in FIXED_YEARS if (y, country) in positions]
        if own:
            ideal_point[country] = sum(own) / len(own)

    # ---- Fed(2025) seg 블록 3분류 — BSV 2021 IPD 단일 기준연도 고정 ------
    # 2026-08-28 연구자 지시: 매년 seg 를 다시 계산해 해마다 하위 25%=CN, 중간 50%=NA, 상위 25%=US 로 다시 자르던
    # 구현을 폐기하고 BSV **2021 IPD 한 해**로 블록을 고정한다. Fed(2025) 논문의 baseline 도 2021 IPD 다
    # (02_인덱스/work/260822_Fed_seg_재현검증.py). 아래에서 실측하듯 2021→2023 만 바꿔도 40% 안팎이 블록을 갈아탈 만큼
    # 연도 선택에 민감해서, 매년 재계산하면 같은 나라가 해마다 미국권·중국권을 오가는 잡음이 생긴다.
    #   seg(s) = [IPD(s,China) - IPD(s,US)] / [IPD(s,US) + IPD(s,China)]   (+1 완전 친미 / -1 완전 친중)
    def _year_blocs(y: int) -> dict:
        cs = [c for c in countries_by_year[y] if (y, c) in positions]
        du = {c: abs(positions[(y, "United States")][1] - positions[(y, c)][1]) for c in cs}
        dc = {c: abs(positions[(y, "China")][1] - positions[(y, c)][1]) for c in cs}
        seg = {c: (dc[c] - du[c]) / (du[c] + dc[c]) for c in cs if du[c] + dc[c]}
        ranked = sorted(seg, key=lambda c: (seg[c], c))
        q = len(ranked) // 4
        return {c: ("CN" if i < q else "US" if i >= len(ranked) - q else "NA") for i, c in enumerate(ranked)}

    # 연도 선택 민감성 실측 — 고정 기준연도를 2021로 정한 근거(Fed 보고치 48%는 추정표본까지 다시 잡은 값이라
    # 직접 비교 대상이 아니다. 우리 것은 측정연도만 바꾼 하한).
    FIXED_BLOC_YEAR = 2021
    fixed_blocs, b23 = _year_blocs(FIXED_BLOC_YEAR), _year_blocs(2023)
    shared = set(fixed_blocs) & set(b23)
    bloc_switch = (sum(1 for c in shared if fixed_blocs[c] != b23[c]) / len(shared)) if shared else 0.0

    # 국가 × 연도 행. 무역비중·GDP 는 연도별(2026 은 2025 값), ideal point·블록은 고정값. 산점도가 기간 평균을 낸다.
    rows = []
    for imp, imp_bsv in IMPLEMENTERS.items():
        for year in range(2010, 2027):
            bsv_year = min(year, 2025)
            for country, iso3 in sorted(countries_by_year[bsv_year].items()):
                if country == imp_bsv:
                    continue
                tshare = trade.get((DOTS_REPORTER[imp], ISO_FIX.get(iso3, iso3), bsv_year))
                gdp_usd = gdp.get((ISO_FIX.get(iso3, iso3), bsv_year))
                ip = ideal_point.get(country)
                rows.append({"implementer": imp, "affected_country": country, "affected_iso3": iso3, "year": year,
                             "bsv_ideal_point": round(ip, 8) if ip is not None else None,
                             "fed_bloc": fixed_blocs.get(country),
                             "trade_share": round(tshare, 10) if tshare is not None else None,
                             "gdp_usd": round(gdp_usd, 2) if gdp_usd is not None else None})
    result = {"built_at": date.today().isoformat(), "gta_asof": asof,
              "ideal_point_note": ("bsv_ideal_point = 해당국 자신의 BSV ideal point(2010~2025 평균). 산점도 x축. "
                                   "미국이 분포 최댓값이라 '미국 기준 거리'는 이 값의 부호만 뒤집은 아핀변환이었다(실측 상관 -0.999996)."),
              "fed_bloc_note": (f"fed_bloc = Fed(2025) seg 순위 블록 3분류, BSV {FIXED_BLOC_YEAR} IPD 단일 기준연도로 고정 "
                                "(2026-08-28부터). 상위 25%=US, 하위 25%=CN, 중간 50%=NA. "
                                f"연도 선택 민감성(2021 블록 vs 2023 블록 변동률) 실측 {bloc_switch*100:.1f}%."),
              "trade_share_note": "trade_share = 시행국 총 상품무역 대비 해당국 비중(IMF DOTS). 산점도 원 크기 선택지 중 하나.",
              "gdp_note": "gdp_usd = 피영향국 자체 GDP, 경상 USD(World Bank WDI). 산점도 원 크기 선택지 중 하나.",
              "red_filter_note": (f"GTA 평가 Red+Amber만 포함(Green 제외). 필터 전 {total_measures:,}건 → Red+Amber {red_count:,}건 "
                                  f"({red_count/total_measures*100:.1f}%)."),
              "targeted_only": TARGETED_ONLY,
              "targeted_note": (f"aj_type=='Targeted'만 남기는 빌드타임 스위치, 현재 {'켜짐' if TARGETED_ONLY else '꺼짐'} "
                                f"(Red+Amber {red_count:,}건 → {targeted_count:,}건). 화면의 'Targeted만 보기'는 이와 별개로 브라우저에서 거른다."),
              "note_2026": "2026 policy data are partial-year; 2025 trade share·GDP carried forward",
              "years": list(range(2010, 2027)), "implementers": list(IMPLEMENTERS), "rows": rows}

    # 연도별 AJ 구성. 분석 단위는 intervention-AJ 등장 1회이며 한 intervention에
    # AJ가 여러 개면 모두 센다. BSV가 없어 seg 블록을 부여할 수 없는 관할권은
    # 100% 분모에서 제외하되 excluded_count/share로 그대로 공개한다.
    #
    # 두 갈래(2026-08-25, 재정의) —
    # · 연도별: 그 해에 "발표"된 조치만(발표연도==year), 생존 여부 무관.
    # · 누적: 그 해 "12월 31일 기준으로 생존 중"인 조치 전부 — 발표연도가
    #   그 이전 어느 해든 상관없다. 예전 구현은 "오늘 시점 is_in_force"를
    #   발표연도별로 나눠 앞으로만 누적했는데, 그러면 (a) 이미 폐지된 조치는
    #   살아있던 해에도 전혀 안 잡히고 (b) 아직 살아있는 조치는 폐지 전 해까지도
    #   실제로 없었던 해에 잡히는 이중 오류였다. date_implemented/date_removed로
    #   그 해 12/31 시점 상태를 직접 재구성한다.
    def _alive_on(m: dict, cutoff: str) -> bool:
        start = m.get("date_implemented") or m.get("date")
        if not start or start > cutoff:
            return False
        removed = m.get("date_removed")
        return not (removed and removed <= cutoff)

    def _announced_in(m: dict, year: int) -> bool:
        try:
            return int(m["date"][:4]) == year
        except (TypeError, ValueError):
            return False

    def _composition(selects) -> list:
        """selects(m, year) — 그해 집계에 넣을 조치인가. 누적(그해 말 생존)과 연도별(그해 발표)이 이것만 다르다."""
        out_rows = []
        for imp in IMPLEMENTERS:
            imp_measures = [m for m in measures
                            if m["implementing"] == imp and m.get("dup") is not True]   # #DUP_RULE_20260824
            own_key, other_key = ("US", "CN") if imp == "United States of America" else ("CN", "US")
            for year in range(2010, 2027):
                counts = Counter(); excluded_count = 0; all_count = 0
                for m in imp_measures:
                    if not selects(m, year):
                        continue
                    for gta in m.get("affected", []):
                        all_count += 1
                        bloc_name = fixed_blocs.get(ALIASES.get(gta, gta))
                        if bloc_name is None:
                            excluded_count += 1
                        else:
                            counts[bloc_name] += 1
                classified = sum(counts.values())
                own, other = counts[own_key], counts[other_key]
                out_rows.append({
                    "implementer": imp, "year": year, "classified_count": classified,
                    "all_aj_count": all_count, "excluded_count": excluded_count,
                    "excluded_share": round(excluded_count / all_count, 8) if all_count else 0,
                    "own_bloc_count": own, "nonaligned_count": counts["NA"],
                    "opposing_bloc_count": other,
                    "own_bloc_share": round(own / classified, 8) if classified else 0,
                    "nonaligned_share": round(counts["NA"] / classified, 8) if classified else 0,
                    "opposing_bloc_share": round(other / classified, 8) if classified else 0,
                })
        return out_rows

    result["composition"] = _composition(lambda m, year: _alive_on(m, f"{min(year, 2026)}-12-31"))
    result["composition_annual"] = _composition(_announced_in)
    (out / "ip_risk.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- 조치 단위 원자료 — 산점도가 브라우저에서 기간·Targeted 조건으로 다시 집계한다 ----
    # i=id, m=시행국(0 미국·1 중국), y=발표연도, x=중복 제거 대상(#DUP_RULE_20260824), t=Targeted, a=피영향국 ISO3
    name_to_iso3 = {name: v[0] for (_, name), v in positions.items()}
    IMP_CODE = {"United States of America": 0, "China": 1}
    sector_measures = []
    for m in measures:
        try: year = int(m["date"][:4])
        except (TypeError, ValueError): continue
        if not 2010 <= year <= 2026: continue
        imp_bsv = IMPLEMENTERS[m["implementing"]]
        aj = [name_to_iso3[c] for c in (ALIASES.get(g, g) for g in dict.fromkeys(m.get("affected", [])))   # 순서 유지 중복 제거
              if c != imp_bsv and c in name_to_iso3]
        if not aj:
            continue
        sector_measures.append({"i": m["id"], "m": IMP_CODE[m["implementing"]], "y": year,
                                "x": 1 if m.get("dup") is True else 0,
                                "t": 1 if m.get("aj_type") == "Targeted" else 0, "a": aj})
    (out / "ip_sectors.json").write_text(
        json.dumps({"measures": sector_measures}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 템플릿 = 패널 전용 <style> + 본문·스크립트. JSON 주소에 빌드 시각을 붙여, 배포마다 새로 받고 그 사이엔 브라우저 캐시를 쓴다
    # (전에는 고정된 ?v=20260824 에 cache:'no-store' 라 방문마다 5MB 를 다시 받았다).
    style, body = TEMPLATE.read_text(encoding="utf-8").split("</style>", 1)
    body = body.replace("__BUILD__", datetime.now().strftime("%Y%m%d%H%M"))
    return [{"file": "ip_risk.html", "title": "Distortive Industrial Policy Tracker · SKL",
             "hero": '<span class="eyebrow">Panel 1 · GTA × BSV</span><h1>Distortive Industrial Policy Tracker</h1>',
             "head": "\n" + style + "</style>", "body": body.strip(), "current": "ip_risk.html", "asof": asof}]
