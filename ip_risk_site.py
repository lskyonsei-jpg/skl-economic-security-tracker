"""연도별 BSV 거리 × 미·중 산업정책 피노출도 사이트 데이터 생성."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
import datetime as _dt
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
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
# 빈다. True로 바꾸고 재빌드하면 지도·순위·추이·산점도·구성·canonical CSV
# 전체에 자동 반영된다(Red/Amber 필터와 같은 방식).
TARGETED_ONLY = False


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


def build(out: Path) -> bool:
    source = out / "ip_us_cn.json"
    if not source.is_file() or not BSV.is_file() or not TEMPLATE.is_file():
        return False
    if not DOTS.is_file():
        return False
    payload = json.loads(source.read_text(encoding="utf-8"))
    # ---- GTA Red+Amber(차별적·잠재적 차별적)만 사용 (2026-08-25) ------------
    # NIPO 전략동기 태그(national security/resilience/... — Fed IFDP 1408이
    # 쓰는 것)가 우리 원자료엔 없다. 대신 GTA 자체 3단계 평가(Red/Amber/
    # Green)에서 Green(자유화)만 뺀다 — Red(명백히 왜곡적)·Amber(가능성 있는
    # 차별)는 둘 다 방향이 보호주의/차별 쪽이고, Green만 반대 방향(자유화)이라
    # "distortive"라는 이름과 섞으면 안 된다. 여기서 한 번만 자르면 지도·
    # 순위·추이·산점도·성장률·구성 화면 전체에 자동으로 반영된다.
    # #DUP_RULE_20260824 6필드 중복 묶기 키에 gta_evaluation이 포함돼 있어
    # 중복 그룹은 항상 단일 평가값으로만 구성된다 — 이 절단과 중복 묶기는
    # 순서를 바꿔도 결과가 같다(교환 가능).
    total_measures = len(payload["measures"])
    payload["measures"] = [m for m in payload["measures"] if m.get("evaluation") in ("Red", "Amber")]
    red_count = len(payload["measures"])
    if TARGETED_ONLY:
        payload["measures"] = [m for m in payload["measures"] if m.get("aj_type") == "Targeted"]
    targeted_count = len(payload["measures"])
    positions, countries_by_year = {}, defaultdict(dict)
    with BSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            year = int(r["year"])
            if 2010 <= year <= 2025:
                positions[(year, r["Countryname"])] = (r["iso3c"], float(r["IdealPointFP"]))
                countries_by_year[year][r["Countryname"]] = r["iso3c"]
    # map/rank/trend의 risk_index는 원시 건수를 그대로 쓴다(정의 유지, 제외 없음).
    denominators, exposed = Counter(), Counter()
    for m in payload["measures"]:
        try: year = int(m["date"][:4])
        except (TypeError, ValueError): continue
        if not 2010 <= year <= 2026: continue
        imp = m["implementing"]; denominators[(imp, year)] += 1
        for gta in set(m.get("affected", [])):
            country = ALIASES.get(gta, gta)
            if (min(year, 2025), country) in positions:
                exposed[(imp, year, country)] += 1
    trade = _load_trade()
    gdp = _load_gdp()
    ISO_FIX = {"YUG": "SRB"}  # BSV iso3c의 세르비아는 구 유고 코드다

    # 산점도용 고정 거리(2026-08-22, 연구자 지시): BSV 2010~2025 **전 구간 평균**을
    # 한 번만 계산해 기간 슬라이더와 무관하게 고정한다. 매킨지도 "distance fixed over
    # the period"이고, 슬라이더를 움직일 때마다 x가 같이 변하면 무엇이 움직인 건지
    # 구분이 안 된다. 정책 자료(분자·분모)만 기간에 따라 달라진다.
    # 지도·순위·추이 화면의 risk_index는 기존 연도별 거리를 그대로 쓴다(정의 유지).
    FIXED_YEARS = [y for y in range(2010, 2026)]
    fixed_dist = {}
    for imp, imp_bsv in IMPLEMENTERS.items():
        for country in {c for y in FIXED_YEARS for c in countries_by_year[y]}:
            if country == imp_bsv:
                continue
            d_imp, d_us, own, segs = [], [], [], []
            for y in FIXED_YEARS:
                if (y, country) not in positions:
                    continue
                pc = positions[(y, country)][1]
                own.append(pc)
                du = abs(positions[(y, "United States")][1] - pc)
                dc = abs(positions[(y, "China")][1] - pc)
                d_imp.append(abs(positions[(y, imp_bsv)][1] - pc))
                d_us.append(du)
                # Fed(2025) FEDS Notes 정렬점수. 원문 공식 그대로:
                #   seg(s) = [IPD(s,China) - IPD(s,US)] / [IPD(s,US) + IPD(s,China)]
                # +1 완전 친미 / -1 완전 친중. 연도별로 계산해 기간 평균한다.
                if du + dc:
                    segs.append((dc - du) / (du + dc))
            if d_imp:
                fixed_dist[(imp, country)] = (sum(d_imp) / len(d_imp),
                                              sum(d_us) / len(d_us),
                                              sum(own) / len(own),
                                              (sum(segs) / len(segs)) if segs else None)

    # ---- Fed(2025) seg 블록 3분류 — BSV 2021 IPD 단일 기준연도 고정 ------
    # 2026-08-28 연구자 지시: 매년 seg를 다시 계산해 해마다 하위 25%=CN,
    # 중간 50%=NA, 상위 25%=US로 다시 자르던 이전 구현(annual_blocs)을
    # 폐기하고 BSV **2021 IPD 한 해**로 블록을 고정한다. Fed(2025) 논문
    # 자체의 baseline도 2021 IPD다(02_인덱스/work/260822_Fed_seg_재현검증.py).
    # 바로 아래에서 실측하듯 2021→2023 IPD만 바꿔도 41.7%가 블록을 갈아탈
    # 만큼 이 지수는 연도 선택에 민감해서, 매년 재계산하면 같은 나라가
    # 해마다 미국권·중국권을 오가는 잡음이 지도·순위·추이 화면에 그대로
    # 드러난다. 옛 지정학 블록 지도(bloc_site.py, 2026-10-22 삭제)도 같은 이유로 2021 고정으로
    # 맞췄다. 2010~2025 평균으로 블록을 고정하던 그 이전 구현(연도별 구성
    # 변화를 지워버려 폐기)으로 되돌아간 것도 아니다 — 평균이 아니라 Fed
    # baseline과 같은 단일 연도 스냅샷이다.
    def _pole_dist(pole: str) -> dict:
        out = {}
        for country in {c for y in FIXED_YEARS for c in countries_by_year[y]}:
            ds = [abs(positions[(y, pole)][1] - positions[(y, country)][1])
                  for y in FIXED_YEARS if (y, country) in positions]
            if ds:
                out[country] = sum(ds) / len(ds)
        return out

    def _blocs(d_us: dict, d_cn: dict) -> dict:
        seg = {c: (d_cn[c] - d_us[c]) / (d_us[c] + d_cn[c])
               for c in d_us.keys() & d_cn.keys() if d_us[c] + d_cn[c]}
        ranked = sorted(seg, key=lambda c: (seg[c], c))
        q = len(ranked) // 4
        return {c: ("CN" if i < q else "US" if i >= len(ranked) - q else "NA")
                for i, c in enumerate(ranked)}

    ipd_us, ipd_cn = _pole_dist("United States"), _pole_dist("China")

    def _year_dists(y: int) -> tuple[dict, dict]:
        cs = [c for c in countries_by_year[y] if (y, c) in positions]
        du = {c: abs(positions[(y, "United States")][1] - positions[(y, c)][1]) for c in cs}
        dc = {c: abs(positions[(y, "China")][1] - positions[(y, c)][1]) for c in cs}
        return du, dc

    def _year_blocs(y: int) -> dict:
        du, dc = _year_dists(y)
        return _blocs(du, dc)

    # 연도 선택 민감성 실측 — 고정 기준연도를 2021로 정한 근거. Fed 논문의
    # 요지가 "어느 해를 고르느냐에 따라 블록의 48%가 바뀐다"는 것이므로,
    # 같은 BSV 계열에서 2021 블록과 2023 블록을 만들어 변동률을 실측해
    # 둔다. Fed의 48%는 추정표본까지 다시 잡은 값이라 수치가 정확히
    # 일치할 이유는 없다(우리 것은 측정연도만 바꾼 하한).
    b21, b23 = _year_blocs(2021), _year_blocs(2023)
    shared = set(b21) & set(b23)
    bloc_switch = (sum(1 for c in shared if b21[c] != b23[c]) / len(shared)) if shared else None

    FIXED_BLOC_YEAR = 2021
    fixed_blocs = b21
    # 2026-10-22(연구자 결정): 지도·순위·추이의 risk_index 거리도 블록 분류와 같은 BSV 2021 한 해로
    # 고정한다. 이전엔 조치 연도의 거리를 썼다(기준연도가 화면 안에 두 개였다). 2021년에 BSV 값이
    # 없는 나라는 2010~2025 중 2021과 가장 가까운 해의 값을 쓰고 distance_year_used 에 적는다.
    def _fixed_position(country: str) -> tuple[float, int] | None:
        for y in sorted(range(2010, 2026), key=lambda y: (abs(y - FIXED_BLOC_YEAR), y)):
            if (y, country) in positions:
                return positions[(y, country)][1], y
        return None
    fixed_position_cache: dict[str, tuple[float, int] | None] = {}
    distance_fallback_countries: set[str] = set()
    _fdu, _fdc = _year_dists(FIXED_BLOC_YEAR)
    fixed_seg = {c: (_fdc[c] - _fdu[c]) / (_fdu[c] + _fdc[c])
                 for c in _fdu.keys() & _fdc.keys() if _fdu[c] + _fdc[c]}
    fixed_seg["United States"], fixed_seg["China"] = 1.0, -1.0

    rows = []
    for imp, imp_bsv in IMPLEMENTERS.items():
        for year in range(2010, 2027):
            bsv_year, denom = min(year, 2025), denominators[(imp, year)]
            imp_pos = positions[(bsv_year, imp_bsv)][1]
            us_pos = positions[(bsv_year, "United States")][1]
            cn_pos = positions[(bsv_year, "China")][1]
            for country, iso3 in sorted(countries_by_year[bsv_year].items()):
                if country == imp_bsv: continue
                n = exposed[(imp, year, country)]; share = n / denom if denom else 0.0
                pos = positions[(bsv_year, country)][1]
                distance_annual = abs(imp_pos - pos)
                distance_us = abs(us_pos - pos)
                distance_cn = abs(cn_pos - pos)
                if country not in fixed_position_cache:
                    fixed_position_cache[country] = _fixed_position(country)
                fixed_pos = fixed_position_cache[country]
                imp_fixed = fixed_position_cache.setdefault(imp_bsv, _fixed_position(imp_bsv))
                distance, distance_year = abs(imp_fixed[0] - fixed_pos[0]), fixed_pos[1]
                if distance_year != FIXED_BLOC_YEAR:
                    distance_fallback_countries.add(country)
                tshare = trade.get((DOTS_REPORTER[imp], ISO_FIX.get(iso3, iso3), bsv_year))
                gdp_usd = gdp.get((ISO_FIX.get(iso3, iso3), bsv_year))
                fx = fixed_dist.get((imp, country))
                rows.append({"implementer": imp, "affected_country": country, "affected_iso3": iso3,
                             "year": year, "implementer_ip_total": denom, "exposed_interventions": n,
                             "exposure_share": round(share, 8), "bsv_distance": round(distance, 8),
                             "distance_year_used": distance_year,
                             "bsv_distance_annual": round(distance_annual, 8),
                             "bsv_distance_us": round(distance_us, 8),
                             "bsv_distance_fixed": round(fx[0], 8) if fx else None,
                             "bsv_distance_us_fixed": round(fx[1], 8) if fx else None,
                             "bsv_ideal_point": round(fx[2], 8) if fx else None,
                             "fed_seg": round(fixed_seg[country], 8) if country in fixed_seg else None,
                             "fed_bloc": fixed_blocs.get(country),
                             "ipd_us": round(distance_us, 8),
                             "ipd_cn": round(distance_cn, 8),
                             "trade_share": round(tshare, 10) if tshare is not None else None,
                             "gdp_usd": round(gdp_usd, 2) if gdp_usd is not None else None,
                             "bsv_year_used": bsv_year, "risk_index": round(share * distance, 8),
                             "distance_carried_forward": year > 2025, "partial_policy_year": year == 2026})
    result = {"built_at": date.today().isoformat(), "gta_asof": payload.get("gta_asof"),
              "definition": "exposure_share × BSV AbsIdealDiff fixed at 2021",
              "distance_note": ("bsv_distance = |시행국 ideal point − 피영향국 ideal point|, BSV 2021 한 해로 고정 "
                                "(2026-10-22부터, 연구자 결정. 이전엔 조치 연도의 거리를 썼다 — bsv_distance_annual 에 남김). "
                                "블록 분류(fed_bloc)와 기준연도를 맞춘 것이다. 따라서 추이 그래프의 변화는 전부 노출 비중의 변화다. "
                                "2021년 값이 없는 나라는 가장 가까운 해를 쓰고 distance_year_used 에 적는다. "
                                "BSV는 거리가 아니라 국가별 ideal point를 주며 거리는 절대차로 계산한다(Dataverse dyads 파일의 AbsIdealDiff와 같은 정의)."),
              "distance_fallback_countries": sorted(distance_fallback_countries),
              "distance_us_note": "bsv_distance_us = 미국 ideal point 기준 절대거리. 두 시행국 패널에 같은 축을 쓰기 위한 값.",
              "distance_fixed_note": ("*_fixed = BSV 2010~2025 전 구간 평균 거리(산점도용). risk_index 는 bsv_distance(2021 고정)를 쓴다."),
              "fed_seg_note": (f"fed_seg = Fed(2025) FEDS Notes 정렬점수, BSV {FIXED_BLOC_YEAR} IPD 고정. "
                                "seg(s)=[IPD(s,China)-IPD(s,US)]/[IPD(s,US)+IPD(s,China)], 모든 연도·행에 같은 값. "
                                "+1 완전 친미 / -1 완전 친중. 원 논문은 이 값의 **수준**을 쓰지 않고 순위로만 쓴다 "
                                "— 화면에서는 쓰지 않는다(가로축 지표는 fed_bloc). 재현·대조용으로만 남긴 필드다."),
              "fed_bloc_note": (f"fed_bloc = seg 순위 블록 3분류, BSV {FIXED_BLOC_YEAR} IPD 단일 기준연도로 고정 "
                                "(2026-08-28부터; 이전엔 연도별로 다시 계산했다). 상위 25%=US, 하위 25%=CN, 중간 50%=NA. "
                                f"연도 선택 민감성(2021 블록 vs 2023 블록 변동률) 실측 {bloc_switch*100:.1f}% — "
                                "이만큼 흔들리는 지표를 매년 재계산하면 같은 나라가 해마다 블록을 오가는 잡음이 "
                                "화면에 그대로 드러나서 2021로 고정했다. Fed 보고치 48%는 추정표본까지 다시 잡은 "
                                "값이라 직접 비교 대상이 아니다."),
              "ipd_note": ("ipd_us / ipd_cn = 해당 연도의 각 극과의 절대 IPD(참고용, 연도별로 변한다). "
                           f"fed_seg/fed_bloc 산출에는 더 이상 쓰이지 않는다 — 그 둘은 BSV {FIXED_BLOC_YEAR} 고정값이다."),
              "ideal_point_note": ("bsv_ideal_point = 해당국 자신의 BSV ideal point(2010~2025 평균). 산점도 x축은 이 값을 쓴다. "
                                    "미국이 분포 최댓값이라 '미국 기준 거리'는 이 값의 부호만 뒤집은 아핀변환이었다 "
                                    "(실측 상관 -0.999996). 이중(dyadic) 구성은 정보를 더하지 않으므로 원 척도를 쓴다."),
              "scatter_note": ("산점도는 ip_sectors.json의 조치 단위 원자료에서 매번 다시 집계한다(서버 사전계산 아님). "
                                "#DUP_RULE_20260824(6필드 전부 같은 반복 공고 1건으로 묶기)만 기본 반영한다 — "
                                "부처별 하드코딩 예외는 2026-08-25 전부 없앴다(표준 3조건: 산업정책·"
                                "GTA Red/Amber·중복 묶기 외에는 특례를 두지 않는다). 화면에서 산업(HS2)을 추가로 걸 수 있다. "
                                "map/rank/trend의 risk_index는 이 제외를 반영하지 않는다."),
              "trade_share_note": ("trade_share = 시행국 총 상품무역 대비 해당국 비중(IMF DOTS, 2026-08-05 갱신). "
                                    "시행국별 자기 기준. 산점도 원 크기 선택지 중 하나."),
              "gdp_note": ("gdp_usd = 피영향국 자체 GDP, 경상 USD(World Bank WDI, 2026-08-22 갱신). "
                           "trade_share와 달리 시행국과 무관한 그 나라 경제 규모 자체다. 산점도 원 크기 선택지 중 하나."),
              "denominator": "implementer-year industrial-policy interventions (D_IP_bert_3 == 1) AND gta_evaluation in (Red, Amber)",
              "red_filter_note": (f"GTA 평가 Red+Amber만 포함(Green 제외). 필터 전 {total_measures:,}건 → Red+Amber {red_count:,}건 "
                                   f"({red_count/total_measures*100:.1f}%). NIPO 전략동기 태그가 없어 대신 쓰는 최소 기준 — "
                                   "Green(자유화)만 방향이 반대라 뺀다."),
              "targeted_only": TARGETED_ONLY,
              "targeted_note": (f"aj_type=='Targeted'(GTA가 명시적으로 지목한 AJ)만 남기는 빌드타임 스위치. "
                                 f"현재 {'켜짐' if TARGETED_ONLY else '꺼짐'} — Red+Amber {red_count:,}건 → "
                                 f"{targeted_count:,}건. Targeted는 극소수(대부분 Inferred=$100만 교역 기준 "
                                 "기계적 등재)라 켜면 표본이 크게 준다."),
              "note_2026": "2026 policy data are partial-year; BSV 2025 distance carried forward",
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

    def _build_composition_asof() -> list:
        out_rows = []
        for imp in IMPLEMENTERS:
            imp_measures = [m for m in payload["measures"] if m["implementing"] == imp]
            for year in range(2010, 2027):
                cutoff = f"{min(year, 2026)}-12-31"
                counts = Counter(); excluded_count = 0; all_count = 0
                by_name = fixed_blocs
                for m in imp_measures:
                    if m.get("dup") is True: continue  # #DUP_RULE_20260824 — 반복 공고 묶기
                    if not _alive_on(m, cutoff): continue
                    for gta in m.get("affected", []):
                        all_count += 1
                        country = ALIASES.get(gta, gta)
                        bloc_name = by_name.get(country)
                        if bloc_name is None:
                            excluded_count += 1
                        else:
                            counts[bloc_name] += 1
                classified = sum(counts.values())
                own = counts["US" if imp == "United States of America" else "CN"]
                other = counts["CN" if imp == "United States of America" else "US"]
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

    def _build_composition_annual() -> list:
        out_rows = []
        for imp in IMPLEMENTERS:
            for year in range(2010, 2027):
                counts = Counter(); excluded_count = 0; all_count = 0
                by_name = fixed_blocs
                for m in payload["measures"]:
                    try: myear = int(m["date"][:4])
                    except (TypeError, ValueError): continue
                    if m["implementing"] != imp or myear != year: continue
                    if m.get("dup") is True: continue  # #DUP_RULE_20260824 — 반복 공고 묶기
                    for gta in m.get("affected", []):
                        all_count += 1
                        country = ALIASES.get(gta, gta)
                        bloc_name = by_name.get(country)
                        if bloc_name is None:
                            excluded_count += 1
                        else:
                            counts[bloc_name] += 1
                classified = sum(counts.values())
                own = counts["US" if imp == "United States of America" else "CN"]
                other = counts["CN" if imp == "United States of America" else "US"]
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

    result["composition"] = _build_composition_asof()
    result["composition_annual"] = _build_composition_annual()
    (out / "ip_risk.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # ---- 산업(HS4) 필터용 조치 단위 원자료 (2026-08-24) --------------------
    # 산점도는 이 파일을 매번 클라이언트에서 다시 집계한다. map/rank/trend의
    # risk_index(위 rows)와는 독립된 경로다 — 산업 필터가 그 화면들에는 영향을
    # 주지 않는다.
    name_to_iso3 = {name: v[0] for (_, name), v in positions.items()}
    IMP_CODE = {"United States of America": 0, "China": 1}
    sector_measures = []
    for m in payload["measures"]:
        try: year = int(m["date"][:4])
        except (TypeError, ValueError): continue
        if not 2010 <= year <= 2026: continue
        imp = m["implementing"]; imp_bsv = IMPLEMENTERS[imp]
        excluded = m.get("dup") is True  # #DUP_RULE_20260824만 쓴다. 부처 하드코딩
        # 예외(구 USDA 특례)는 2026-08-25 제거했다.
        aj = []
        for gta in set(m.get("affected", [])):
            country = ALIASES.get(gta, gta)
            if country == imp_bsv or country not in name_to_iso3:
                continue
            aj.append(name_to_iso3[country])
        if not aj:
            continue
        sector_measures.append({
            "i": m["id"], "m": IMP_CODE[imp], "y": year,
            "x": 1 if excluded else 0,
            "t": 1 if m.get("aj_type") == "Targeted" else 0,
            "h": m.get("hs2", []), "a": aj,
        })
    sectors_out = {
        "measures": sector_measures,
        "hs2_labels": payload.get("hs2_labels", {}),
        "hs2_counts": payload.get("hs2_counts", []),
    }
    (out / "ip_sectors.json").write_text(
        json.dumps(sectors_out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    # 배포본이 실제로 갱신됐는지 눈으로 확인할 수 있게 빌드 시각을 심는다(캐시 진단용).
    html = TEMPLATE.read_text(encoding="utf-8").replace(
        "</body>", f'<p class="reg-note">빌드: {_dt.datetime.now().strftime("%Y-%m-%d %H:%M")}</p></body>')
    (out / "ip_risk.html").write_text(html, encoding="utf-8")
    return True
