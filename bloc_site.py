"""지정학적 블록 지도 + 표적 조치 흐름도 · 이란/러우 스레드 — D블록(2026-08-28).

블록 정의: Airaudo, de Soyres, Richards & Santacreu (2025, FEDS Notes)의
seg(s) 지수를 그대로 쓴다. seg(s) = [IPD(s,China)-IPD(s,US)] / [IPD(s,US)+IPD(s,China)],
IPD(a,b) = |ideal_point(a)-ideal_point(b)| (Bailey et al. 2017 BSV 자료).
TARGET_YEAR(2021년) 세계 표결 기준 상위 25% = 미국권, 하위 25% = 중국권,
중간 50% = 비동맹.

기준연도를 2021로 고정한 이유(2026-08-28) — 처음엔 "지금 시점에 가장
가깝다"는 이유로 2025년 분포를 썼는데, 임의로 안정적인 해를 고른 게 아니다.
**Fed(2025) 논문 자체의 baseline이 2021 IPD다** — 이 지수는 기준연도 선택에
매우 민감해서(같은 BSV 계열에서 2021 IPD를 2023 IPD로만 바꿔도 41.7%의
국가가 블록을 갈아탄다 — Fed 논문 본문 보고치 48%와 같은 규모, 재현:
02_인덱스/work/260822_Fed_seg_재현검증.py) 매년 최신 연도를 쓰면 같은 나라가
해마다 블록을 오가는 잡음이 생긴다. 원 논문의 기준을 그대로 따르는 게
임의의 최신 연도보다 방어 가능하다. 부수적으로 2021년은 193개국 자료가
완비돼 있어(2025년은 190개국) 결측 보정에 기대는 국가도 더 적다.
`ip_risk_site.py`(Distortive Industrial Policy Tracker)의 fed_bloc/fed_seg
필드도 같은 이유로 2026-08-28부터 BSV 2021 IPD 단일 기준연도로 고정했다 —
같은 판단을 두 화면에 일관되게 적용한 것이다. 상세 근거는 GTA Threads
폴더의 README.md 참고.

흐름도: 각 스레드 CSV에서 `Affected Jurisdictions`가 4개국 이하로 좁게
명시된 조치만 뽑는다 — 대상국이 넓게 나열된(포괄 제재 등) 조치는 "누가
누구를 겨냥했는지"를 그리기에 부적합해 제외했다. 세계지도에 직선을 얹는
방식은 처음 시도했다가 버렸다 — 중동처럼 나라가 밀집한 지역에서 화살표가
겹쳐 뭉개지고, 먼 거리 화살표끼리 서로 교차해 방향을 읽을 수 없었다(2026-
08-28 확인). 대신 지리적 위치와 무관한 이분 배치도(bipartite arc diagram)
를 쓴다 — 왼쪽 열에 시행국, 오른쪽 열에 대상국을, 블록별로 묶고 블록 안에서는
빈도순으로 놓고 곡선으로 잇는다. 시행국·대상국이 여러 개면 조합마다 선 하나씩
그린다(예: EU 27개국이 함께 이란을 겨냥한 조치 1건 → 선 27개). 단, 시행국이
4개국을 넘는 조치는 개별로 펼치지 않고 "OO 외 N개국" 하나의 노드로 묶는다
(EU 27개국 사례가 그렇다) — 안 그러면 선이 27개 늘어서 그 자체가 새로운
잡음이 된다.

2026-08-28: 이란 스레드 전용 xlsx(별도 스키마, `260825 GTA Threads - ...
.xlsx`)에 의존하던 걸 걷어내고, 원자료 폴더의 GTA 공개 CSV 두 개(이란/러우)를
직접 읽는 방식으로 바꿨다 — 그 xlsx는 그날 이후 갱신이 안 돼 CSV보다
낡았고, 러우 스레드는 애초에 그 xlsx 계열로 받아둔 게 없었다.

지도(블록 분류)는 원래 요청대로 그대로 남기고, 흐름도는 그 아래 스레드별
패널로 둔다.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BSV = ROOT / "02_인덱스/원자료/Benchmark/Voeten BSV - Ideal Points/2026 Voeten - Ideal point estimates 1946-2025.tab"
THREAD_DIR = ROOT / "05_국정원과제/02_원자료/GTA Threads"
WORLD = HERE / "reference" / "ne_110m_admin_0_countries.geojson"

THREADS = [
    ("이란 분쟁 (2026)", "Policy Responses to the 2026 Iran Conflict",
     THREAD_DIR / "20260828_GTA Threads_Policy_Responses_to_the_2026_Iran_Conflict.csv"),
    ("러시아-우크라이나 전쟁 제재", "Economic Sanctions Related to the Russian Invasion of Ukraine",
     THREAD_DIR / "20260828_GTA Threads_Economic_Sanctions_Related_to_the_Russian_Invasion_of_Ukraine.csv"),
]

US, CN = "United States", "China"
TARGET_YEAR = 2021
MAX_TARGETS = 4  # 이보다 대상국이 많으면 "좁게 표적한 조치"로 안 본다
MAX_IMPL_FANOUT = 4  # 이보다 시행국이 많으면 개별로 안 펼치고 한 노드로 묶는다

EU27 = {
    "Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark",
    "Estonia", "Finland", "France", "Germany", "Greece", "Hungary", "Ireland",
    "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland",
    "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden",
}

# 표시용 한글 국명 — 없는 나라는 원문(GTA 표기) 그대로 둔다.
KO_NAME = {
    "United States of America": "미국", "United Kingdom": "영국", "China": "중국",
    "Iran": "이란", "Hong Kong": "홍콩", "United Arab Emirates": "UAE",
    "Russia": "러시아", "India": "인도", "Turkiye": "튀르키예", "Singapore": "싱가포르",
    "Qatar": "카타르", "Marshall Islands": "마셜제도", "Switzerland": "스위스",
    "Canada": "캐나다", "Australia": "호주", "Egypt": "이집트", "Thailand": "태국",
    "Iraq": "이라크", "Saudi Arabia": "사우디", "Netherlands": "네덜란드",
    "Vietnam": "베트남", "Venezuela": "베네수엘라", "Germany": "독일",
    "Belgium": "벨기에", "Poland": "폴란드", "Lebanon": "레바논", "Syria": "시리아",
    "Maldives": "몰디브", "Mauritius": "모리셔스", "Liberia": "라이베리아",
    "Italy": "이탈리아", "Spain": "스페인", "Austria": "오스트리아",
    "Ukraine": "우크라이나", "France": "프랑스", "Japan": "일본", "Norway": "노르웨이",
    "Kazakhstan": "카자흐스탄", "Armenia": "아르메니아", "Georgia": "조지아",
    "Belarus": "벨라루스", "Uzbekistan": "우즈베키스탄", "Kyrgyzstan": "키르기스스탄",
    "Moldova": "몰도바", "Serbia": "세르비아", "Sweden": "스웨덴", "Finland": "핀란드",
}


def ko(name: str) -> str:
    return KO_NAME.get(name, name)


# GTA 표기 -> BSV Countryname. 직접 일치하면 매핑 불필요.
NAME_TO_BSV = {
    "Republic of Korea": "South Korea",
    "United States of America": "United States",
    "Turkiye": "Turkey",
    "Turkish Republic of Northern Cyprus": None,
    "Ivory Coast": "Côte d’Ivoire",
    "Congo": "Congo - Brazzaville",
    "Republic of the Congo": "Congo - Brazzaville",
    "DR Congo": "Congo - Kinshasa",
    "Democratic Republic of the Congo": "Congo - Kinshasa",
    "Lao": "Laos",
    "Macedonia": "North Macedonia",
    "Myanmar": "Myanmar (Burma)",
    "Republic of Moldova": "Moldova",
    "Republic of the Sudan": "Sudan",
    "Saint Kitts & Nevis": "St. Kitts & Nevis",
    "Saint Lucia": "St. Lucia",
    "Saint Vincent & the Grenadines": "St. Vincent & Grenadines",
    "Bosnia and Herzegovina": "Bosnia & Herzegovina",
    "Czech Republic": "Czechia",
    "East Timor": "Timor-Leste",
    "Trinidad and Tobago": "Trinidad & Tobago",
    "The Bahamas": "Bahamas",
    "The Gambia": "Gambia",
    "People's Republic of China": "China",
    # 대만은 BSV 자료에 "Taiwan"으로 1946-1971년치가 남아 있다(1971년 유엔
    # 축출 이전 중화민국 대표권 시기). 2021년엔 당연히 값이 없지만, build_blocs
    # 의 결측 보정 로직이 그 국가의 2021 이전 최신 연도(1971년)를 그대로
    # 써서 미국권으로 분류해 낸다 — 실제 표결 기록에 기반한 것이지 임의
    # 배정이 아니다. 예전엔 여기서 None(블록 미상)으로 막아놨었는데, 그러면
    # 지도·흐름도에서만 "이념점 없음"으로 잘못 표시되고 국가 목록(블록 미상
    # 필터를 안 거치는 쪽)에서는 이미 미국권으로 나오는 불일치가 있었다
    # (2026-08-28 확인) — 매핑을 걷어내 둘을 일치시켰다.
    "Chinese Taipei": "Taiwan",
    # 유엔 미가입/의석 없음 — 이념점 자체가 없다(대만과 달리 과거 데이터도
    # 없다). 블록 미상으로 남긴다.
    "Anguilla": None, "Aruba": None, "Bermuda": None, "British Virgin Islands": None,
    "Cayman Islands": None, "Cook Islands": None,
    "French Polynesia": None, "Guam": None, "Hong Kong": None, "Macao": None,
    "Montserrat": None, "New Caledonia": None, "Saint Helena": None, "Tokelau": None,
    "Sao Tome & Principe": None, "Serbia": None, "Kosovo": None, "Palestine": None,
    "Somaliland": None, "Western Sahara": None, "Puerto Rico": None, "Greenland": None,
    "Falkland Islands": None, "French Southern and Antarctic Lands": None, "Antarctica": None,
}


def to_bsv(name: str) -> str | None:
    if name in NAME_TO_BSV:
        return NAME_TO_BSV[name]
    return name


def load_bsv() -> dict[tuple[int, str], float]:
    import csv
    pos = {}
    with BSV.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            pos[(int(r["year"]), r["Countryname"])] = float(r["IdealPointFP"])
    return pos


def seg_at(pos: dict, year: int, country: str, us: float, cn: float) -> float | None:
    v = pos.get((year, country))
    if v is None:
        return None
    d_us, d_cn = abs(us - v), abs(cn - v)
    tot = d_us + d_cn
    return (d_cn - d_us) / tot if tot else None


def build_blocs(pos: dict) -> dict[str, str]:
    """국가 -> 'US'/'CN'/'NON'. TARGET_YEAR 분포로 분위 경계를 잡고,
    그 해가 없는 국가는 그 국가의 최신 연도(TARGET_YEAR 이전) 값을 같은
    경계에 대입한다."""
    us_y, cn_y = pos[(TARGET_YEAR, US)], pos[(TARGET_YEAR, CN)]
    seg: dict[str, float] = {}
    all_countries = {c for (_, c) in pos}
    for c in all_countries:
        if c in (US, CN):
            continue
        v = seg_at(pos, TARGET_YEAR, c, us_y, cn_y)
        if v is not None:
            seg[c] = v
    seg[US], seg[CN] = 1.0, -1.0

    have_years = defaultdict(set)
    for (y, c) in pos:
        have_years[c].add(y)
    for c in all_countries - set(seg) - {US, CN}:
        years = sorted(y for y in have_years[c] if y <= TARGET_YEAR)
        if not years:
            continue
        y = years[-1]
        uy, cy = pos.get((y, US)), pos.get((y, CN))
        if uy is None or cy is None:
            continue
        v = seg_at(pos, y, c, uy, cy)
        if v is not None:
            seg[c] = v

    items = sorted(seg.items(), key=lambda kv: kv[1])
    n = len(items)
    q = n // 4
    out = {}
    for i, (c, _) in enumerate(items):
        if i < q:
            out[c] = "CN"
        elif i >= n - q:
            out[c] = "US"
        else:
            out[c] = "NON"
    return out


def bloc_of(blocs: dict, raw_name: str) -> str:
    bsv_name = to_bsv(raw_name)
    if bsv_name is None:
        return "UNK"
    return blocs.get(bsv_name, "UNK")


OIL_HS_PREFIXES = ("2709", "2710")  # 원유·석유 정제품


def oil_hs_codes(products_raw) -> set[str]:
    if pd.isna(products_raw):
        return set()
    codes = [c.strip() for c in str(products_raw).split(",")]
    return {prefix for prefix in OIL_HS_PREFIXES if any(c.startswith(prefix) for c in codes)}


def is_oil_products(products_raw) -> bool:
    return bool(oil_hs_codes(products_raw))


def count_narrow_rows(csv_path: Path, oil_only: bool = False) -> int:
    """load_narrow_events 와 같은 필터(대상국 4개국 이하)를 원본 행 기준으로
    세기만 한다 — 시행국 팬아웃으로 부풀리기 전의 '조치 건수'."""
    df = pd.read_csv(csv_path)
    n = 0
    for _, r in df.iterrows():
        aff_raw = r["Affected Jurisdictions"]
        if pd.isna(aff_raw) or pd.isna(r["Date Announced"]) or pd.isna(r["Implementing Jurisdictions"]):
            continue
        aff_list = [c.strip() for c in str(aff_raw).split(",") if c.strip()]
        if not aff_list or len(aff_list) > MAX_TARGETS:
            continue
        if oil_only and not is_oil_products(r["Affected Products"]):
            continue
        n += 1
    return n


def load_narrow_events(csv_path: Path) -> list[dict]:
    """GTA 공개 CSV(쉼표 구분)에서 대상국 4개국 이하로 좁게 명시된 조치만
    뽑아, 시행국×대상국 조합마다 연결선 하나씩 만든다. 시행국이
    MAX_IMPL_FANOUT개를 넘으면(EU 공동조치 등) 개별로 안 펼치고 "OO 외
    N개국" 노드 하나로 묶는다. 각 연결선에 'oil' 플래그(원 조치의 Affected
    Products가 HS 2709/2710을 하나라도 포함하는지)를 달아, 나중에 석유만
    모드에서 걸러 쓸 수 있게 한다."""
    df = pd.read_csv(csv_path)
    arrows = []
    for row_id, r in df.iterrows():
        aff_raw, date, impl_raw = r["Affected Jurisdictions"], r["Date Announced"], r["Implementing Jurisdictions"]
        if pd.isna(aff_raw) or pd.isna(date) or pd.isna(impl_raw):
            continue
        aff_list = [c.strip() for c in str(aff_raw).split(",") if c.strip()]
        if not aff_list or len(aff_list) > MAX_TARGETS:
            continue
        impl_list = [c.strip() for c in str(impl_raw).split(",") if c.strip()]
        itype, evaluation, title = r["Intervention Type"], r["GTA Evaluation"], r["State Act Title"]
        hs_codes = oil_hs_codes(r["Affected Products"])

        if set(impl_list) == EU27:
            # GTA는 EU 초국가 조치도 시행국 필드에 27개 회원국을 열거한다.
            # 첫 국가를 딴 "오스트리아 외 26개국"은 오스트리아 주도처럼 보이므로
            # 실체에 맞게 하나의 EU 노드로 표시한다.
            impl_entries = [("EU", impl_list[0])]
        elif len(impl_list) > MAX_IMPL_FANOUT:
            impl_entries = [(f"{ko(impl_list[0])} 외 {len(impl_list) - 1}개국", impl_list[0])]
        else:
            impl_entries = [(ko(impl), impl) for impl in impl_list]

        for impl_disp, impl_key in impl_entries:
            for aff in aff_list:
                arrows.append({
                    "event_id": int(row_id),
                    "date": str(date), "impl": impl_disp, "impl_key": impl_key,
                    "aff": ko(aff), "aff_key": aff,
                    "type": itype, "eval": evaluation, "title": title,
                    "oil": bool(hs_codes), "hs_codes": hs_codes,
                })
    arrows.sort(key=lambda a: a["date"])
    return arrows


# ---- SVG 지도 (semiconductor_site.py 와 같은 등장방형 투영) ----

def project(lon: float, lat: float) -> tuple[float, float]:
    return (lon + 180) * 1000 / 360, (90 - lat) * 510 / 180


def ring_path(ring) -> str:
    pts = []
    for i, (lon, lat) in enumerate(ring):
        x, y = project(lon, lat)
        pts.append(f"{'L' if i else 'M'}{x:.1f},{y:.1f}")
    return "".join(pts) + "Z"


def geom_path(geom: dict) -> str:
    polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
    return "".join("".join(ring_path(ring) for ring in poly) for poly in polys)


BLOC_COLOR = {"US": "#1a5fb4", "CN": "#c62828", "NON": "#8a8a86", "UNK": "#3a3a38"}


def render_map_svg(blocs: dict, geo: dict) -> str:
    paths = []
    for feat in geo["features"]:
        props = feat["properties"]
        name = props.get("NAME_EN") or props.get("ADMIN") or props.get("NAME") or ""
        b = bloc_of(blocs, name)
        color = BLOC_COLOR[b]
        paths.append(
            f'<path class="country" fill="{color}" d="{geom_path(feat["geometry"])}">'
            f"<title>{esc(name)}</title></path>"
        )
    return (
        f'<svg viewBox="0 0 1000 510" aria-label="{TARGET_YEAR}년 지정학적 블록 지도">'
        + "".join(paths)
        + "</svg>"
    )


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


ARROW_COLOR = {"Red": "#c62828", "Amber": "#c62828", "Green": "#2e7d32"}
BLOC_ORDER = ["US", "NON", "CN", "UNK"]
BLOC_LABEL_KO = {"US": "미국 클럽 + 대만", "CN": "중국 클럽", "NON": "비동맹", "UNK": "이념점 없음"}


def _grouped_rows(names: list[str], count: dict[str, int], key_of: dict[str, str], blocs: dict):
    """이름들을 블록별로 묶고 블록마다 빈도순 정렬한다. 각 블록 앞에 헤더
    행을 하나 끼워 넣는다. 반환: [("header", bloc) | ("node", name), ...]"""
    by_bloc: dict[str, list[str]] = defaultdict(list)
    for n in names:
        by_bloc[bloc_of(blocs, key_of[n])].append(n)
    rows: list[tuple[str, str]] = []
    for b in BLOC_ORDER:
        items = by_bloc.get(b)
        if not items:
            continue
        items.sort(key=lambda n: -count[n])
        rows.append(("header", b))
        rows.extend(("node", n) for n in items)
    return rows


def render_flow_diagram(blocs: dict, arrows: list[dict]) -> str:
    """지리적 위치와 무관한 이분 배치도. 왼쪽=시행국, 오른쪽=대상국. 세계지도+
    직선 방식은 중동처럼 나라가 밀집한 곳에서 화살표가 겹쳐 뭉개지고 원거리
    화살표끼리 교차해 버려서(2026-08-28) 이 방식으로 바꿨다. 각 열 안에서는
    블록(미국권/비동맹/중국권/이념점 없음)별로 묶고, 블록 안에서는 빈도순
    정렬한다 — 순수 빈도순으로만 섞어 놓으면 어느 블록이 어느 블록을
    때리는지 한눈에 안 보인다는 지적(2026-08-28)에 따른 것이다."""
    impl_count: dict[str, int] = defaultdict(int)
    aff_count: dict[str, int] = defaultdict(int)
    impl_key_of: dict[str, str] = {}
    aff_key_of: dict[str, str] = {}
    for a in arrows:
        impl_count[a["impl"]] += 1
        aff_count[a["aff"]] += 1
        impl_key_of[a["impl"]] = a["impl_key"]
        aff_key_of[a["aff"]] = a["aff_key"]

    # 우측 수치는 팬아웃된 연결선 수가 아니라 원자료 intervention의 순건수다.
    aff_events: dict[str, dict[int, str]] = defaultdict(dict)
    for a in arrows:
        aff_events[a["aff"]][a["event_id"]] = a["eval"]

    def net_label(name: str) -> str:
        evaluations = aff_events[name].values()
        distortive = sum(v in ("Red", "Amber") for v in evaluations)
        liberalising = sum(v == "Green" for v in evaluations)
        return f"{distortive - liberalising} = {distortive} − {liberalising}"

    left_rows = _grouped_rows(list(impl_count), impl_count, impl_key_of, blocs)
    right_rows = _grouped_rows(list(aff_count), aff_count, aff_key_of, blocs)
    left_i = {name: i for i, (kind, name) in enumerate(left_rows) if kind == "node"}
    right_i = {name: i for i, (kind, name) in enumerate(right_rows) if kind == "node"}

    ROW_H = 22
    PAD_T, PAD_B = 20, 20
    LEFT_X, RIGHT_X = 190, 810
    n_rows = max(len(left_rows), len(right_rows))
    H = PAD_T + n_rows * ROW_H + PAD_B
    left_off = (n_rows - len(left_rows)) * ROW_H / 2
    right_off = (n_rows - len(right_rows)) * ROW_H / 2

    def y_of(i: int, offset: float) -> float:
        return PAD_T + offset + i * ROW_H + ROW_H / 2

    def render_column(rows, x: float, offset: float, count: dict, key_of: dict, align: str):
        anchor = "end" if align == "left" else "start"
        label_x = x - 10 if align == "left" else x + 10
        out = []
        for i, (kind, val) in enumerate(rows):
            y = y_of(i, offset)
            if kind == "header":
                out.append(
                    f'<text class="bloc-header" x="{label_x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
                    f'font-size="10.5" font-weight="700" fill="{BLOC_COLOR[val]}">{BLOC_LABEL_KO[val]}</text>'
                )
            else:
                color = BLOC_COLOR[bloc_of(blocs, key_of[val])]
                suffix = f" ({count[val]})" if align == "left" else f" ({net_label(val)})"
                out.append(f'<circle class="node" cx="{x}" cy="{y:.1f}" r="5" fill="{color}"/>')
                out.append(
                    f'<text class="node-label" x="{label_x:.1f}" y="{y + 4:.1f}" text-anchor="{anchor}" '
                    f'font-size="11">{esc(val)}{suffix}</text>'
                )
        return "".join(out)

    parts = []
    xm = (LEFT_X + RIGHT_X) / 2
    for a in arrows:
        y1 = y_of(left_i[a["impl"]], left_off)
        y2 = y_of(right_i[a["aff"]], right_off)
        color = ARROW_COLOR.get(a["eval"], "#8a8a86")
        tip = f'{esc(a["impl"])} → {esc(a["aff"])}: {esc(a["type"])} ({a["date"]})\n{esc(a["title"])}'
        parts.append(
            f'<path class="flow" data-date="{a["date"]}" '
            f'd="M{LEFT_X + 7},{y1:.1f} C{xm:.1f},{y1:.1f} {xm:.1f},{y2:.1f} {RIGHT_X - 7},{y2:.1f}" '
            f'stroke="{color}" fill="none"><title>{tip}</title></path>'
        )
    # 화살표를 먼저 그려서 뒤로 깔고, 노드·라벨을 그 위에 그린다(가독성).
    parts.append(render_column(left_rows, LEFT_X, left_off, impl_count, impl_key_of, "left"))
    parts.append(render_column(right_rows, RIGHT_X, right_off, aff_count, aff_key_of, "right"))

    return f'<svg viewBox="0 0 1000 {H}" aria-label="시행국-대상국 흐름도(블록별 묶음)">{"".join(parts)}</svg>'


def max_bloc_pair_count(blocs: dict, arrows: list[dict]) -> int:
    counts: dict[str, int] = defaultdict(int)
    for a in arrows:
        pair = f'{bloc_of(blocs, a["impl_key"])}_{bloc_of(blocs, a["aff_key"])}'
        counts[pair] += -1 if a["eval"] == "Green" else 1
    return max((abs(v) for v in counts.values()), default=0)


def render_bloc_flow_diagram(
    blocs: dict, arrows: list[dict], dates: list[str], global_scale_max: int
) -> tuple[str, dict]:
    """시행국/대상국을 국가가 아니라 블록(미국권/비동맹/중국권/이념점 없음)
    4개 노드로 묶은 버전. 선 굵기 = 그 블록쌍의 조치 건수(날짜 누적, JS가
    슬라이더에 맞춰 다시 그림) — 그래서 굵기는 초기값만 파이썬에서 계산하고,
    실제 날짜별 굵기는 cum(블록쌍 -> dates와 같은 길이의 누적 건수 배열)을
    JSON으로 같이 내보내 JS가 매긴다. dates 는 국가별 흐름도와 같은 타임라인
    (전체 모드 날짜 목록)을 그대로 받는다 — 석유만 모드도 같은 타임라인
    인덱스를 써야 슬라이더 하나로 두 모드를 같이 몰 수 있다."""
    daily_red: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    daily_green: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    left_present, right_present = set(), set()
    for a in arrows:
        ib, ab = bloc_of(blocs, a["impl_key"]), bloc_of(blocs, a["aff_key"])
        pair = f"{ib}_{ab}"
        if a["eval"] == "Green":
            daily_green[pair][a["date"]] += 1
        else:
            daily_red[pair][a["date"]] += 1
        left_present.add(ib)
        right_present.add(ab)

    def cumulative(daily: dict[str, dict[str, int]]) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for pair, by_date in daily.items():
            running, arr = 0, []
            for d in dates:
                running += by_date.get(d, 0)
                arr.append(running)
            out[pair] = arr
        return out

    cum_red = cumulative(daily_red)
    cum_green = cumulative(daily_green)
    pairs = set(cum_red) | set(cum_green)
    zeros = [0] * len(dates)
    cum_net = {
        pair: [r - g for r, g in zip(cum_red.get(pair, zeros), cum_green.get(pair, zeros))]
        for pair in pairs
    }

    left = [b for b in BLOC_ORDER if b in left_present]
    right = [b for b in BLOC_ORDER if b in right_present]

    local_max = max((abs(arr[-1]) for arr in cum_net.values() if arr), default=0)
    max_stroke = 140.0 * local_max / max(1, global_scale_max)
    # 기본 72px을 보장하되, 이 화면의 가장 굵은 선보다 24px 더 넓게 벌린다.
    # 전체 품목처럼 선이 굵은 화면만 자동으로 높아진다.
    ROW_H, PAD_T, PAD_B = max(72.0, max_stroke + 24.0), 28, 28
    LEFT_X, RIGHT_X = 190, 810
    n_rows = max(len(left), len(right), 1)
    H = PAD_T + n_rows * ROW_H + PAD_B
    left_off = (n_rows - len(left)) * ROW_H / 2
    right_off = (n_rows - len(right)) * ROW_H / 2

    def y_of(i: int, offset: float) -> float:
        return PAD_T + offset + i * ROW_H + ROW_H / 2

    left_y = {b: y_of(i, left_off) for i, b in enumerate(left)}
    right_y = {b: y_of(i, right_off) for i, b in enumerate(right)}

    def scale_w(c: int) -> float:
        """페이지 전체 공통 최대값 대비 완전 선형 비례, 최대 140px."""
        if c <= 0:
            return 0.0
        return 140.0 * c / max(1, global_scale_max)

    xm = (LEFT_X + RIGHT_X) / 2
    parts = []
    for ib in left:
        for ab in right:
            pair = f"{ib}_{ab}"
            if pair not in cum_net:
                continue
            last = cum_net[pair][-1]
            y1, y2 = left_y[ib], right_y[ab]
            line_color = "#c62828" if last > 0 else "#2e7d32" if last < 0 else "#8a8a86"
            parts.append(
                f'<path class="flow-bloc" data-pair="{pair}" '
                f'd="M{LEFT_X + 10},{y1:.1f} C{xm:.1f},{y1:.1f} {xm:.1f},{y2:.1f} {RIGHT_X - 10},{y2:.1f}" '
                f'stroke="{line_color}" stroke-width="{scale_w(abs(last)):.2f}" fill="none" '
                f'opacity="{0.85 if last != 0 else 0.06}">'
                f'<title>{BLOC_LABEL_KO[ib]} → {BLOC_LABEL_KO[ab]}: Net {last:+d}건(전체 기간)</title></path>'
            )
    for b in left:
        y = left_y[b]
        parts.append(f'<circle cx="{LEFT_X}" cy="{y:.1f}" r="9" fill="{BLOC_COLOR[b]}"/>')
        parts.append(
            f'<text class="node-label" x="{LEFT_X - 16:.1f}" y="{y + 4:.1f}" text-anchor="end" '
            f'font-size="12.5" font-weight="700">{BLOC_LABEL_KO[b]}</text>'
        )
    for b in right:
        y = right_y[b]
        red = sum(arr[-1] for pair, arr in cum_red.items() if pair.endswith(f"_{b}"))
        green = sum(arr[-1] for pair, arr in cum_green.items() if pair.endswith(f"_{b}"))
        net = red - green
        parts.append(f'<circle cx="{RIGHT_X}" cy="{y:.1f}" r="9" fill="{BLOC_COLOR[b]}"/>')
        parts.append(
            f'<text class="node-label" x="{RIGHT_X + 16:.1f}" y="{y + 4:.1f}" '
            f'font-size="12.5" font-weight="700">{BLOC_LABEL_KO[b]}'
            f'<tspan class="bloc-count" data-bloc="{b}"> ({net} = {red} − {green})</tspan></text>'
        )

    svg = f'<svg viewBox="0 0 1000 {H}" aria-label="클럽별 흐름도">{"".join(parts)}</svg>'
    return svg, {"net": cum_net, "red": cum_red, "green": cum_green}


def render_country_list(blocs: dict, geo: dict | None = None) -> str:
    """접었다 펼치는 2021 IPD 블록별 국가 목록. <details> 하나로 열고 닫는다.

    blocs 에는 US/NON/CN 만 들어있다(build_blocs 는 BSV 값이 있는 나라만
    분류한다) — "이념점 없음"(UNK) 국가는 blocs 에 없으므로, geo(세계지도
    지오json)를 같이 받아 지도에는 있지만 blocs 에는 없는 나라 이름을 모아
    네 번째 칸으로 보여준다. geo가 없으면(호출부가 지도를 안 쓰는 페이지)
    UNK 칸은 생략한다."""
    by_bloc: dict[str, list[tuple[str, float | None]]] = defaultdict(list)
    # build_blocs 는 이름만 주므로, seg 값도 다시 계산해 정렬 기준으로 쓴다.
    pos = load_bsv()
    us_y, cn_y = pos[(TARGET_YEAR, US)], pos[(TARGET_YEAR, CN)]
    for c, b in blocs.items():
        v = seg_at(pos, TARGET_YEAR, c, us_y, cn_y)
        if v is None:
            # 결측 보정으로 편입된 국가 — 정렬용으로만 블록 경계 근처 값을 준다.
            v = {"US": 1.0, "CN": -1.0, "NON": 0.0}.get(b, 0.0)
        by_bloc[b].append((c, v))

    if geo is not None:
        seen: set[str] = set()
        for feat in geo["features"]:
            props = feat["properties"]
            name = props.get("NAME_EN") or props.get("ADMIN") or props.get("NAME") or ""
            if not name or name in seen or bloc_of(blocs, name) != "UNK":
                continue
            seen.add(name)
            by_bloc["UNK"].append((name, None))

    sections = []
    for b in ("US", "NON", "CN", "UNK"):
        if b == "UNK" and b not in by_bloc:
            continue
        items = by_bloc.get(b, [])
        items = sorted(items, key=lambda kv: kv[0]) if b == "UNK" else sorted(items, key=lambda kv: -kv[1])
        lis = "".join(
            f"<li>{esc(c)}"
            + ("" if v is None else f" <span class='seg-val'>{'NaN' if c == 'Taiwan' else f'{v:+.3f}'}</span>")
            + "</li>"
            for c, v in items
        )
        sections.append(
            f'<div class="country-col"><h4 style="color:{BLOC_COLOR[b]}">{BLOC_LABEL_KO[b]} ({len(items)}개국)</h4>'
            f"<ul>{lis}</ul></div>"
        )
    return (
        "<details class=\"country-list\"><summary>2021 IPD 국가별 블록 분류 펼치기/접기</summary>"
        f'<div class="country-cols">{"".join(sections)}</div></details>'
    )


PANEL_HTML = r"""
<div class="panel" data-cum-2709="__CUM_2709_JSON__" data-cum-2710="__CUM_2710_JSON__" data-cum-both="__CUM_BOTH_JSON__" data-cum-all="__CUM_ALL_JSON__">
<div class="toggle-row">
<div class="toggle-group agg-toggle">
<button type="button" class="toggle-btn" data-agg="country">국가별</button>
<button type="button" class="toggle-btn active" data-agg="bloc">클럽별</button>
</div>
<div class="toggle-group topic-toggle">
<button type="button" class="toggle-btn" data-topic="2709">HS 2709(원유)</button>
<button type="button" class="toggle-btn" data-topic="2710">HS 2710(정제품)</button>
<button type="button" class="toggle-btn active" data-topic="both">둘 다</button>
<button type="button" class="toggle-btn" data-topic="all">전체(비석유품목 포함)</button>
</div>
</div>
<div class="panel-head">__THREAD_LABEL__ — 시행국 → 대상국 흐름도 (일자별)</div>
<div class="flow-wrap">
<div class="flow-view view-country view-2709">__FLOW_COUNTRY_2709__</div>
<div class="flow-view view-country view-2710">__FLOW_COUNTRY_2710__</div>
<div class="flow-view view-country view-both">__FLOW_COUNTRY_BOTH__</div>
<div class="flow-view view-country view-all">__FLOW_COUNTRY_ALL__</div>
<div class="flow-view view-bloc view-2709">__FLOW_BLOC_2709__</div>
<div class="flow-view view-bloc view-2710">__FLOW_BLOC_2710__</div>
<div class="flow-view view-bloc view-both active">__FLOW_BLOC_BOTH__</div>
<div class="flow-view view-bloc view-all">__FLOW_BLOC_ALL__</div>
</div>
<div class="legend"><span><i class="dot" style="background:#c62828"></i>레드/앰버(차별적)</span><span><i class="dot" style="background:#2e7d32"></i>그린(자유화)</span>
<ul class="legend-meta">
<li>사용 Threads: __THREAD_GTA_NAME__</li>
<li>필터: 대상국 4개국 이하 명시 조치만 (__N_NARROW__/__N_TOTAL__건, 연결선 __N_ARROWS__개)</li>
<li>기준일: __DATE_MIN__ ~ __DATE_MAX__</li>
</ul>
</div>
<div class="slider-row">
<span style="font-size:.8rem;color:var(--muted)">__DATE_MIN__</span>
<input type="range" class="date-slider" min="0" max="__MAX_DATE_IDX__" value="__MAX_DATE_IDX__" step="1" data-dates="__DATES_JSON__">
<span style="font-size:.8rem;color:var(--muted)">__DATE_MAX__</span>
<b class="date-label"></b>
</div>
</div>
"""

HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>석유 산업의 분절화와 재연결 · SKL</title>
<link rel="stylesheet" href="style.css"><style>
.map-wrap{position:relative;padding:8px;overflow:hidden;background:#111;border:2px solid var(--line);border-radius:12px}
.map-wrap svg{width:100%;height:auto;display:block}
.country{stroke:#fff;stroke-width:.45}
.flow-wrap{padding:8px;overflow-x:auto;background:var(--bg);border:2px solid var(--line);border-radius:12px}
.flow-wrap svg{display:block;min-width:640px}
.flow-wrap svg text.node-label{fill:var(--fg)}
.flow-wrap svg text.bloc-header{letter-spacing:.02em}
.flow{opacity:0;stroke-width:1.4;fill:none;transition:opacity .25s,stroke-width .25s}
.flow.shown{opacity:.5}
.flow.today{opacity:1;stroke-width:2.6}
.flow-bloc{transition:stroke-width .25s,opacity .25s}
.flow-view{display:none}
.flow-view.active{display:block}
.legend{display:flex;flex-wrap:wrap;gap:12px;padding:10px 4px;font-size:.8rem;color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:middle}
.legend-meta{flex-basis:100%;margin:2px 0 0;padding-left:1.1em;font-size:.74rem;opacity:.85}
.legend-meta li{margin:1px 0}
.panel-head{padding:10px 2px;font-size:.9rem;color:var(--muted)}
.note{margin:10px 0 20px;padding:10px 14px;border:2px dashed var(--line);border-radius:10px;font-size:.82rem;color:var(--muted)}
.slider-row{display:flex;align-items:center;gap:12px;padding:14px 4px 4px}
.slider-row input[type=range]{flex:1}
.slider-row b{min-width:100px;text-align:right;color:var(--plum)}
.toggle-row{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}
.toggle-group{display:flex;border:2px solid var(--line);border-radius:8px;overflow:hidden}
.toggle-btn{padding:6px 14px;font-size:.8rem;background:var(--card);color:var(--fg);border:none;cursor:pointer;font-family:inherit}
.toggle-btn.active{background:var(--plum);color:#fff}
.toggle-btn.disabled{opacity:.35;cursor:not-allowed}
.country-list{margin:0 0 20px;border:2px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--card)}
.country-list summary{cursor:pointer;font-size:.86rem;color:var(--muted)}
.country-cols{display:flex;flex-wrap:wrap;gap:20px;margin-top:12px}
.country-col{flex:1 1 220px;min-width:200px;max-height:360px;overflow-y:auto}
.country-col h4{margin:0 0 6px;font-size:.86rem}
.country-col ul{margin:0;padding-left:18px;font-size:.78rem;color:var(--fg)}
.country-col li{margin:2px 0}
.seg-val{color:var(--muted);font-size:.72rem}
.oil-controls{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0;align-items:flex-end}
.oil-field{display:flex;flex-direction:column;gap:4px}
.oil-field label{font-size:.76rem;color:var(--muted)}
.oil-field input[type=text]{padding:6px 10px;font-size:.85rem;font-family:inherit;background:var(--card);color:var(--fg);border:2px solid var(--line);border-radius:8px;min-width:200px}
.oil-swap{align-self:flex-end;padding:6px 12px;font-size:.8rem;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer;font-family:inherit}
.oil-chart-wrap{padding:8px;overflow:auto;background:var(--bg);border:2px solid var(--line);border-radius:12px}
.oil-chart-wrap svg{display:block;min-width:640px}
#oil-chart-fullscreen-root:fullscreen,#oil-chart-fullscreen-root:-webkit-full-screen{display:flex;flex-direction:column;width:100vw;height:100vh;padding:16px;box-sizing:border-box;background:var(--bg)}
#oil-chart-fullscreen-root:fullscreen .oil-chart-wrap,#oil-chart-fullscreen-root:-webkit-full-screen .oil-chart-wrap{flex:1 1 auto;min-height:0}
.oil-chart-toolbar{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0;align-items:center}
.oil-chart-toolbar .toggle-btn{border:2px solid var(--line);border-radius:8px;min-width:34px}
.oil-zoom-label{font-size:.78rem;color:var(--muted);min-width:42px;text-align:center}
.oil-summary{font-size:.82rem;color:var(--muted);margin:8px 2px}
.oil-loading{padding:20px;text-align:center;color:var(--muted);font-size:.85rem}
.oil-mini-row{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.oil-mini-label{font-size:.72rem;color:var(--muted)}
.oil-mini-toggle .toggle-btn{padding:3px 9px;font-size:.72rem}
.check-legend{display:flex;flex-wrap:wrap;gap:2px 12px;padding:10px 4px;font-size:.8rem;color:var(--muted)}
.check-item{display:inline-flex;align-items:center;gap:5px;cursor:pointer;padding:2px 0}
.check-item input{margin:0;cursor:pointer}
</style></head><body><div class="wrap">
<a class="back" href="index.html">← 변경 내역</a>
<header class="semi-head" style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
<div><h1 style="margin:0;font-size:1.45rem">석유 산업의 분절화와 재연결</h1>
<p style="margin:4px 0 0;color:var(--muted);font-size:.86rem">GTA Threads 기준 · 이란 분쟁(2026) + 러시아-우크라이나 전쟁 제재</p></div>
</header>
__COUNTRY_LIST__
<p class="note">블록 정의: BSV 이념점 기반 seg(s) 지수, __TARGET_YEAR__년 분포 상위 25%=미국 클럽 · 하위 25%=중국 클럽 · 중간 50%=비동맹.
대만은 2021년 자체 표결 기록이 없지만(1971년 유엔 축출) BSV에 남은 1946-1971년 표결로 대신 분류하면 미국 클럽에 들어간다 —
"이념점 없음"으로 뭉뚱그리지 않고 실제 과거 표결 기록에 기반해 미국 클럽에 포함했다.</p>
<div class="panel-head">__TARGET_YEAR__년 블록 분류</div>
<div class="map-wrap">__MAP_SVG__</div>
<div class="legend"><span><i class="dot" style="background:#1a5fb4"></i>미국 클럽 + 대만</span><span><i class="dot" style="background:#c62828"></i>중국 클럽</span><span><i class="dot" style="background:#8a8a86"></i>비동맹</span><span><i class="dot" style="background:#3a3a38"></i>이념점 없음(비유엔 등)</span></div>
__PANELS__
<div class="oil-panel">
<div class="panel-head">원유·석유제품·석유가스(HS 2709·2710·2711) 무역 탐색기 — 2010~2026</div>
<div class="legend"><ul class="legend-meta">
<li>출처: UN Comtrade, __OIL_ROW_COUNT__행 (보고국·상대국·연도·품목·흐름, breakdownMode=classic)</li>
<li>기간: 2010~2025 연간 + 2026년 1~6월(상반기만, 하반기 미게시)</li>
<li>주의: 막대 2개=수출국/수입국 각자 신고(미러 통계) — 한쪽만 있고 0이면 자체 미신고(러시아 2022~, 베네수엘라 2014~)</li>
</ul></div>
<div class="oil-controls">
<div class="oil-field">
<label for="oil-exporter">수출국(또는 클럽)</label>
<div class="oil-mini-row"><span class="oil-mini-label">단위</span><div class="toggle-group oil-mini-toggle" id="oil-exporter-mode">
<button type="button" class="toggle-btn active" data-mode="country">국가</button>
<button type="button" class="toggle-btn" data-mode="bloc">클럽</button>
</div></div>
<input type="text" id="oil-exporter" list="oil-exporter-list" autocomplete="off">
<datalist id="oil-exporter-list"></datalist>
</div>
<button type="button" class="oil-swap" id="oil-swap" title="수출국·수입국 맞바꾸기">⇄</button>
<div class="oil-field">
<label for="oil-importer">수입국(또는 클럽)</label>
<div class="oil-mini-row"><span class="oil-mini-label">단위</span><div class="toggle-group oil-mini-toggle" id="oil-importer-mode">
<button type="button" class="toggle-btn active" data-mode="country">국가</button>
<button type="button" class="toggle-btn" data-mode="bloc">클럽</button>
</div></div>
<input type="text" id="oil-importer" list="oil-importer-list" autocomplete="off">
<datalist id="oil-importer-list"></datalist>
</div>
<div class="oil-field"><label>품목 (여러 개 누르면 합산)</label><div class="toggle-group" id="oil-hs-toggle">
<button type="button" class="toggle-btn active" data-hs="2709">HS 2709(원유)</button>
<button type="button" class="toggle-btn active" data-hs="2710">HS 2710(정제품)</button>
<button type="button" class="toggle-btn active" data-hs="2711" id="oil-hs-2711-btn">HS 2711(석유가스) ▾</button>
</div>
<div class="oil-mini-row" id="oil-hs-2711-sub"><span class="oil-mini-label">석유가스 세부(여러 개 누르면 합산)</span><div class="toggle-group oil-mini-toggle" id="oil-hs-2711-sub-toggle">
<button type="button" class="toggle-btn active" data-hs="LNG">LNG</button>
<button type="button" class="toggle-btn active" data-hs="PIPE">파이프라인가스</button>
<button type="button" class="toggle-btn active" data-hs="LPG">LPG</button>
<button type="button" class="toggle-btn active" data-hs="GAS_OTHER">기타가스</button>
</div></div>
</div>
<div class="oil-field"><label>보기</label><div class="toggle-group" id="oil-view-toggle">
<button type="button" class="toggle-btn active" data-view="absolute">절대비교</button>
<button type="button" class="toggle-btn" data-view="share">구성비율</button>
</div></div>
<div class="oil-field"><label>유럽</label><div class="toggle-group" id="oil-eu-toggle">
<button type="button" class="toggle-btn active" data-eu="separate">국가별로 보기</button>
<button type="button" class="toggle-btn" data-eu="combined">EU로 보기</button>
</div></div>
<div class="oil-field"><label>통계 기준</label><div class="toggle-group" id="oil-basis-toggle">
<button type="button" class="toggle-btn active" data-basis="export">수출국 신고</button>
<button type="button" class="toggle-btn" data-basis="import">수입국 신고</button>
</div></div>
</div>
<div class="oil-summary" id="oil-summary">데이터 불러오는 중…</div>
<div class="legend" id="oil-rank-legend" style="display:none"></div>
<div id="oil-chart-fullscreen-root">
<div class="oil-chart-toolbar">
<button type="button" class="toggle-btn" id="oil-zoom-out" title="축소">－</button>
<span class="oil-zoom-label" id="oil-zoom-label">100%</span>
<button type="button" class="toggle-btn" id="oil-zoom-in" title="확대">＋</button>
<button type="button" class="toggle-btn" id="oil-zoom-reset" title="확대·축소 초기화">초기화</button>
<button type="button" class="toggle-btn" id="oil-fullscreen" title="전체화면">⛶ 전체화면</button>
<button type="button" class="toggle-btn" id="oil-save-jpg" title="지금 보고 있는 차트를 JPG 그림파일로 저장">⤓ JPG 저장</button>
</div>
<div class="oil-chart-wrap" id="oil-chart-wrap"><div class="oil-loading" id="oil-chart">데이터 불러오는 중…</div></div>
</div>
</div>
</div>
<script>
(function(){
  const CLUB_LABEL = {US:'미국 클럽', CN:'중국 클럽', NON:'비동맹'};
  const EU_LABEL = 'EU(27개국)';
  const HS_LABEL = {'2709':'HS 2709(원유)', '2710':'HS 2710(정제품)', '2711':'HS 2711(석유가스, 전체)',
    'LNG':'LNG(271111)', 'PIPE':'파이프라인 천연가스(271121)', 'LPG':'LPG(271112·271113·271119)', 'GAS_OTHER':'기타가스(271114·271129)'};
  // 국가별 구성 보기에서 EU 27개 회원국을 하나로 묶어볼 때 쓰는 집합 — UN
  // Comtrade가 원유·석유제품·석유가스에서도 EU를 보고국/상대국으로 직접
  // 신고하지 않아, 회원국 각자의 신고를 합산하는 방식으로만 EU 단위를
  // 만들 수 있다(solar_site.py와 동일한 판단).
  const EU27_ISO3 = new Set(['AUT','BEL','BGR','HRV','CYP','CZE','DNK','EST','FIN','FRA',
    'DEU','GRC','HUN','IRL','ITA','LVA','LTU','LUX','MLT','NLD','POL','PRT','ROU','SVK',
    'SVN','ESP','SWE']);
  // '2711'(전체)을 고르면 이 네 세부코드를 합쳐서 보여준다. HS_LABEL·matchesHs 둘 다 이 목록을 쓴다.
  const HS2711_SUB_CODES = ['LNG', 'PIPE', 'LPG', 'GAS_OTHER'];
  const CLUB_COLOR = {US:'#1a5fb4', CN:'#c62828', NON:'#8a8a86', UNK:'#3a3a38'};
  // 클럽별 구성 보기에서만 쓴다 — UNK(이념점 없음)는 exp/imp 선택지에는 없지만
  // countries[iso3].club 값으로는 나올 수 있어(build_oil_data.py), 묶어서 보여준다.
  const CLUB_FULL_LABEL = Object.assign({UNK: '이념점 없음'}, CLUB_LABEL);
  const X_COLOR = '#2f6f9f';   // 수출국 신고
  const M_COLOR = '#c9822f';   // 수입국 신고
  const YEARS = Array.from({length:16}, (_,i) => String(2010+i)).concat(['2026']);

  // 앞뒤로 이어지는 0(데이터 없음) 연도만 잘라낸다 — 중간에 낀 0은 유지한다.
  function trimYears(years, hasValue){
    let start = 0, end = years.length - 1;
    while (start <= end && !hasValue(years[start])) start++;
    while (end >= start && !hasValue(years[end])) end--;
    return start <= end ? years.slice(start, end + 1) : years;
  }

  fetch('oil_trade.json').then(r => r.json()).then(init).catch(err => {
    document.getElementById('oil-chart').textContent = '데이터 로드 실패: ' + err;
  });

  function init(data){
    const rows = data.rows;         // [reporterISO3, partnerISO3, period, cmd, flow, value]
    const countries = data.countries; // {iso3: {name, club}}
    document.getElementById('oil-summary').textContent = '';

    const fsRoot = document.getElementById('oil-chart-fullscreen-root');
    let zoom = 1;
    const ZOOM_MIN = 0.5, ZOOM_MAX = 3, ZOOM_STEP = 0.25;
    function applyZoom(){
      const svg = document.querySelector('#oil-chart svg');
      if (!svg) return;
      const isFs = document.fullscreenElement === fsRoot;
      if (isFs && zoom === 1) {
        // 전체화면 + 기본 배율: 세로 공간까지 채운다 (SVG 원본 비율 유지, 레터박스).
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.maxWidth = 'none';
      } else {
        svg.style.width = (zoom * 100) + '%';
        svg.style.height = 'auto';
        svg.style.maxWidth = 'none';
      }
      document.getElementById('oil-zoom-label').textContent = Math.round(zoom * 100) + '%';
    }
    document.getElementById('oil-zoom-in').addEventListener('click', () => {
      zoom = Math.min(ZOOM_MAX, +(zoom + ZOOM_STEP).toFixed(2)); applyZoom();
    });
    document.getElementById('oil-zoom-out').addEventListener('click', () => {
      zoom = Math.max(ZOOM_MIN, +(zoom - ZOOM_STEP).toFixed(2)); applyZoom();
    });
    document.getElementById('oil-zoom-reset').addEventListener('click', () => {
      zoom = 1; applyZoom();
    });
    document.getElementById('oil-fullscreen').addEventListener('click', () => {
      if (!document.fullscreenElement) {
        (fsRoot.requestFullscreen || fsRoot.webkitRequestFullscreen || function(){}).call(fsRoot);
      } else {
        (document.exitFullscreen || document.webkitExitFullscreen || function(){}).call(document);
      }
    });

    // ── 차트를 JPG 그림파일로 저장 ─────────────────────────────────────
    // 화면의 SVG를 그대로 캔버스에 구워 낸다. 두 군데를 손봐야 그림이
    // 화면과 같아진다. (1) SVG 안의 색이 var(--fg) 같은 CSS 변수로
    // 적혀 있는데 <img>로 띄우는 순간 페이지의 :root와 끊겨 변수가 풀리지
    // 않는다 — 직렬화한 문자열에서 미리 계산값으로 바꿔치기한다.
    // (2) 한글 글꼴도 같은 이유로 페이지 것을 못 쓰므로 woff2를 data URL로
    // 박아 넣는다(가져오기 실패하면 시스템 명조로 떨어진다).
    let jpgFontCssPromise = null;
    function jpgEmbeddedFontCss(){
      if (!jpgFontCssPromise) {
        jpgFontCssPromise = fetch('fonts/noto-serif-kr-900.woff2')
          .then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
          .then(b => new Promise((res, rej) => {
            const fr = new FileReader();
            fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsDataURL(b);
          }))
          .then(u => {
            // <img>로 띄운 SVG는 이 문서와 글꼴을 나눠 쓰지 못한다. 데이터를
            // 박아 넣어도 처음 한 번은 글꼴이 붙기 전에 그려져 한글만 통째로
            // 빠지는 일이 있어, 같은 바이트를 이 문서에도 미리 올려
            // 브라우저 글꼴 캐시를 덥혀 둔다.
            let prime = Promise.resolve();
            try {
              const ff = new FontFace('Noto Serif KR', 'url(' + u + ')', {weight: '900', style: 'normal'});
              prime = ff.load().then(f => { document.fonts.add(f); }).catch(() => {});
            } catch (e) { /* FontFace 미지원 브라우저 — 그냥 넘어간다 */ }
            return prime.then(() => "@font-face{font-family:'Noto Serif KR';font-style:normal;font-weight:900;src:url(" + u + ") format('woff2')}");
          })
          .catch(() => '');
      }
      return jpgFontCssPromise;
    }
    // 파일 이름은 차트 맨 위 제목 글자를 그대로 쓴다 — 따로 이름을 물어보지 않는다.
    function jpgFileName(svg){
      const t = svg.querySelector('text');
      const base = ((t && t.textContent) || '차트')
        .replace(/[\/:*?"<>|]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || '차트';
      const d = new Date(), pad = n => String(n).padStart(2, '0');
      return '' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '_' + base + '.jpg';
    }
    function saveChartJpg(){
      const svg = document.querySelector('#oil-chart svg');
      const btn = document.getElementById('oil-save-jpg');
      if (!svg) { alert('아직 그려진 차트가 없다.'); return; }
      const prevText = btn.textContent;
      btn.disabled = true; btn.textContent = '저장 중…';
      const done = () => { btn.disabled = false; btn.textContent = prevText; };
      const cs = getComputedStyle(document.documentElement);
      const vb = svg.viewBox.baseVal;
      const w = Math.round((vb && vb.width) || svg.clientWidth || 1000);
      const h = Math.round((vb && vb.height) || svg.clientHeight || 600);
      const SCALE = 2;   // 문서에 붙여 넣어도 글자가 뭉개지지 않게 2배로 굽는다
      jpgEmbeddedFontCss().then(fontCss => {
        const clone = svg.cloneNode(true);
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        clone.setAttribute('width', w);
        clone.setAttribute('height', h);
        clone.removeAttribute('style');   // 확대·축소로 박아둔 인라인 크기는 뺀다
        const st = document.createElementNS('http://www.w3.org/2000/svg', 'style');
        st.textContent = fontCss +
          'svg{font-family:"Times New Roman",Times,"Noto Serif KR","본명조","Batang",serif;font-weight:900}';
        clone.insertBefore(st, clone.firstChild);
        const markup = new XMLSerializer().serializeToString(clone)
          .replace(/var\(\s*(--[\w-]+)\s*\)/g, (m, name) => cs.getPropertyValue(name).trim() || '#000');
        const svgUrl = URL.createObjectURL(new Blob([markup], {type: 'image/svg+xml;charset=utf-8'}));
        const img = new Image();
        img.onload = () => {
          const cv = document.createElement('canvas');
          cv.width = w * SCALE; cv.height = h * SCALE;
          const ctx = cv.getContext('2d');
          const paint = () => {
            ctx.fillStyle = cs.getPropertyValue('--bg').trim() || '#ffffff';   // JPG는 투명을 못 담는다
            ctx.fillRect(0, 0, cv.width, cv.height);
            ctx.drawImage(img, 0, 0, cv.width, cv.height);
          };
          paint();
          // 글꼴이 한 박자 늦게 붙는 경우가 있어 잠깐 뒤에 한 번 더 굽는다.
          setTimeout(() => {
          paint();
          URL.revokeObjectURL(svgUrl);
          cv.toBlob(blob => {
            if (!blob) { alert('JPG로 바꾸지 못했다.'); done(); return; }
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = jpgFileName(svg);
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
            done();
          }, 'image/jpeg', 0.95);
          }, 150);
        };
        img.onerror = () => { URL.revokeObjectURL(svgUrl); alert('차트 그림을 만들지 못했다.'); done(); };
        img.src = svgUrl;
      });
    }
    document.getElementById('oil-save-jpg').addEventListener('click', saveChartJpg);
    // flex%만 믿으면 브라우저에 따라 wrap이 콘텐츠 높이로만 잡혀 아래가 비므로,
    // 전체화면일 때 남는 세로 공간을 직접 재서 wrap 높이를 px로 박아넣는다.
    const chartWrapEl = document.getElementById('oil-chart-wrap');
    const chartToolbarEl = document.querySelector('.oil-chart-toolbar');
    function syncFullscreenHeight(){
      if (document.fullscreenElement === fsRoot) {
        const rootStyle = getComputedStyle(fsRoot);
        const padV = (parseFloat(rootStyle.paddingTop) || 0) + (parseFloat(rootStyle.paddingBottom) || 0);
        const toolbarH = chartToolbarEl.getBoundingClientRect().height;
        const toolbarMarginB = parseFloat(getComputedStyle(chartToolbarEl).marginBottom) || 0;
        const avail = window.innerHeight - padV - toolbarH - toolbarMarginB;
        chartWrapEl.style.height = Math.max(200, avail) + 'px';
      } else {
        chartWrapEl.style.height = '';
      }
    }
    document.addEventListener('fullscreenchange', () => {
      document.getElementById('oil-fullscreen').textContent = document.fullscreenElement ? '⛶ 전체화면 종료' : '⛶ 전체화면';
      syncFullscreenHeight();
      applyZoom();
    });
    window.addEventListener('resize', () => { if (document.fullscreenElement === fsRoot) { syncFullscreenHeight(); applyZoom(); } });

    // 마우스 드래그로 상하좌우 이동 (grab & pan)
    (function(){
      let dragging = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;
      chartWrapEl.style.cursor = 'grab';
      chartWrapEl.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX; startY = e.clientY;
        startLeft = chartWrapEl.scrollLeft; startTop = chartWrapEl.scrollTop;
        chartWrapEl.style.cursor = 'grabbing';
        e.preventDefault();
      });
      window.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        chartWrapEl.scrollLeft = startLeft - (e.clientX - startX);
        chartWrapEl.scrollTop = startTop - (e.clientY - startY);
      });
      window.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        chartWrapEl.style.cursor = 'grab';
      });
    })();

    const names = Object.entries(countries).sort((a,b) => a[1].name.localeCompare(b[1].name));

    // #COMBO_INPUT (semiconductor_site.py의 반도체 공급망 지도와 같은 패턴,
    // 2026-08-29 요청) — 별도 검색칸을 안 두고 select 자리를 datalist 딸린
    // input으로 대체한다. 칸을 누르면 비워 전체 목록을 보이고(브라우저가 남은
    // 글자로 알아서 좁힌다), 목록에 있는 글자와 정확히 일치해야 값이 반영된다.
    // 국가 모드는 국가명, 클럽 모드는 클럽명이 유효 목록이라 모드 전환마다
    // resolve 대상이 바뀐다.
    const nameToIso3 = {};
    names.forEach(([iso3, info]) => { nameToIso3[info.name] = iso3; });
    const clubNameToCode = {};
    Object.entries(CLUB_LABEL).forEach(([code, lbl]) => { clubNameToCode[lbl] = code; });

    function optionsFor(mode){
      const base = mode === 'bloc' ? ['US','CN','NON'].map(c => CLUB_LABEL[c]) : [EU_LABEL, ...names.map(([,info]) => info.name)];
      return ['전체', ...base];
    }
    function resolveFor(mode, text){
      if (text === '전체') return 'ALL';
      if (text === EU_LABEL) return 'EU';
      return mode === 'bloc' ? (clubNameToCode[text] || null) : (nameToIso3[text] || null);
    }

    const DEFAULT_BY_MODE = {
      exporter: {country: 'RUS', bloc: 'US'},
      importer: {country: 'CHN', bloc: 'CN'},
    };

    function bindCombo(input, listEl, toggleId, which){
      const state = {mode: 'country', value: null};
      function fillDatalist(){
        listEl.innerHTML = optionsFor(state.mode).map(n => `<option value="${n}">`).join('');
      }
      function setValue(code, silent){
        state.value = code;
        input.value = label(code);
        if (!silent) render();
      }
      function setMode(m, val){
        state.mode = m;
        document.querySelectorAll(`#${toggleId} .toggle-btn`).forEach(b => b.classList.toggle('active', b.dataset.mode === m));
        fillDatalist();
        setValue(val !== undefined ? val : DEFAULT_BY_MODE[which][m], true);
      }
      input.addEventListener('focus', () => { input.dataset.prev = input.value; input.value = ''; });
      input.addEventListener('input', () => {
        const code = resolveFor(state.mode, input.value.trim());
        if (code) { setValue(code); input.blur(); }
      });
      input.addEventListener('blur', () => {
        if (!resolveFor(state.mode, input.value.trim())) input.value = input.dataset.prev || label(state.value);
      });
      document.querySelectorAll(`#${toggleId} .toggle-btn`).forEach(btn => {
        btn.addEventListener('click', () => { setMode(btn.dataset.mode); render(); });
      });
      state.setMode = setMode;
      setMode('country', DEFAULT_BY_MODE[which].country);
      return state;
    }
    const expSel = bindCombo(document.getElementById('oil-exporter'), document.getElementById('oil-exporter-list'), 'oil-exporter-mode', 'exporter');
    const impSel = bindCombo(document.getElementById('oil-importer'), document.getElementById('oil-importer-list'), 'oil-importer-mode', 'importer');

    // 품목 토글 — 예전엔 셋 중 하나만 고르거나 '합계' 버튼으로 전부를
    // 고르는 단일 선택이었는데, 여러 개를 각각 눌러서 그때그때 원하는
    // 조합만 합산해 보고 싶다는 요청(2026-09-03)에 따라 각 버튼이 독립
    // 토글로 바뀌었다 — 켜진 것만 더한다. HS 2711(석유가스)을 켜면 아래
    // 세부코드(LNG/파이프라인가스/LPG/기타가스) 토글이 나타나고, 그중
    // 켜진 세부코드만 합산된다. 최소 하나는 꺼지지 않게 막는다 — 다 끄면
    // 그래프가 텅 빈다.
    const topHsSet = new Set(['2709', '2710', '2711']);
    const gasSubSet = new Set(HS2711_SUB_CODES);
    function matchesHs(cmd){
      if (cmd === '2709' || cmd === '2710') return topHsSet.has(cmd);
      return topHsSet.has('2711') && gasSubSet.has(cmd);
    }
    const hs2711SubRow = document.getElementById('oil-hs-2711-sub');
    function syncHsButtons(){
      document.querySelectorAll('#oil-hs-toggle .toggle-btn').forEach(b => {
        b.classList.toggle('active', topHsSet.has(b.dataset.hs));
      });
      document.querySelectorAll('#oil-hs-2711-sub-toggle .toggle-btn').forEach(b => {
        b.classList.toggle('active', gasSubSet.has(b.dataset.hs));
      });
      hs2711SubRow.style.display = topHsSet.has('2711') ? '' : 'none';
    }
    function toggleInSet(set, code){
      if (set.has(code)) {
        if (set.size === 1) return;   // 마지막 하나는 끌 수 없다
        set.delete(code);
      } else {
        set.add(code);
      }
      syncHsButtons();
      render();
    }
    document.querySelectorAll('#oil-hs-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => toggleInSet(topHsSet, btn.dataset.hs));
    });
    document.querySelectorAll('#oil-hs-2711-sub-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => toggleInSet(gasSubSet, btn.dataset.hs));
    });
    syncHsButtons();

    // 그래프 제목·각주에 쓸 품목 표기 — 켜진 것들을 조합해 만든다. 석유가스
    // 세부코드를 일부만 골랐을 때 제목이 "석유가스"로만 뭉뚱그려져 실제
    // 선택과 안 맞아 보이는 문제(2026-09-03 확인)가 있었다 — 세부 중 일부만
    // 켜졌으면 "석유가스(LNG·LPG)"처럼 큰 이름은 그대로 두고 괄호로 세부를 밝힌다.
    const GAS_SUB_SHORT = {LNG: 'LNG', PIPE: '파이프라인가스', LPG: 'LPG', GAS_OTHER: '기타가스'};
    function currentProductLabel(){
      const parts = [];
      if (topHsSet.has('2709')) parts.push('원유');
      if (topHsSet.has('2710')) parts.push('정제품');
      if (topHsSet.has('2711')) {
        if (gasSubSet.size === HS2711_SUB_CODES.length) {
          parts.push('석유가스');
        } else {
          const subLabel = HS2711_SUB_CODES.filter(c => gasSubSet.has(c)).map(c => GAS_SUB_SHORT[c]).join('·');
          parts.push(`석유가스(${subLabel})`);
        }
      }
      return parts.join('·') || '(품목 선택 없음)';
    }
    function currentHsNote(){
      const bits = [];
      if (topHsSet.has('2709')) bits.push(HS_LABEL['2709']);
      if (topHsSet.has('2710')) bits.push(HS_LABEL['2710']);
      if (topHsSet.has('2711')) {
        if (gasSubSet.size === HS2711_SUB_CODES.length) {
          bits.push(HS_LABEL['2711']);
        } else {
          bits.push(HS2711_SUB_CODES.filter(c => gasSubSet.has(c)).map(c => HS_LABEL[c]).join(' + '));
        }
      }
      return bits.join(' + ') || '(품목 선택 없음)';
    }

    // '국가별 순위' 보기는 한쪽이 '전체'일 때만 의미가 있다(상대가 하나뿐이면
    // 순위를 매길 대상이 없다) — 그 조건이 아니면 버튼을 꺼두고 총액으로
    // 강제하되, 사용자가 골라둔 view 값 자체는 남겨서 다시 '전체'를 고르면
    // 원래 보던 보기로 돌아온다.
    let view = 'absolute';
    document.querySelectorAll('#oil-view-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        view = btn.dataset.view;
        render();
      });
    });

    let rankBasis = 'export';
    document.querySelectorAll('#oil-basis-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        rankBasis = btn.dataset.basis;
        document.querySelectorAll('#oil-basis-toggle .toggle-btn').forEach(b => b.classList.toggle('active', b === btn));
        render();
      });
    });

    let euMode = 'separate';
    document.querySelectorAll('#oil-eu-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        euMode = btn.dataset.eu;
        document.querySelectorAll('#oil-eu-toggle .toggle-btn').forEach(b => b.classList.toggle('active', b === btn));
        render();
      });
    });

    const highlighted = new Set();
    document.getElementById('oil-rank-legend').addEventListener('change', (e) => {
      const cb = e.target.closest('input[type=checkbox]');
      if (!cb) return;
      if (cb.id === 'oil-select-all') {
        const codes = cb.dataset.codes ? cb.dataset.codes.split(',') : [];
        if (cb.checked) codes.forEach(c => highlighted.add(c));
        else codes.forEach(c => highlighted.delete(c));
        render();
        return;
      }
      const c = cb.dataset.country;
      if (cb.checked) highlighted.add(c); else highlighted.delete(c);
      render();
    });
    // 막대 세그먼트를 직접 클릭해도 같은 국가 전체가 색칠되도록 (체크박스와 동기화)
    document.getElementById('oil-chart').addEventListener('click', (e) => {
      const rect = e.target.closest('rect[data-country]');
      if (!rect) return;
      const c = rect.dataset.country;
      if (highlighted.has(c)) highlighted.delete(c); else highlighted.add(c);
      render();
    });

    document.getElementById('oil-swap').addEventListener('click', () => {
      const aMode = expSel.mode, aVal = expSel.value;
      const bMode = impSel.mode, bVal = impSel.value;
      expSel.setMode(bMode, bVal);
      impSel.setMode(aMode, aVal);
      render();
    });

    function matches(iso3, sel){
      if (sel === 'ALL') return true;
      if (sel === 'EU') return EU27_ISO3.has(iso3);
      if (sel === 'US' || sel === 'CN' || sel === 'NON') {
        const c = countries[iso3];
        return c && c.club === sel;
      }
      return iso3 === sel;
    }

    function label(sel){
      if (sel === 'ALL') return '전체';
      if (sel === 'EU') return EU_LABEL;
      if (CLUB_LABEL[sel]) return CLUB_LABEL[sel];
      return (countries[sel] && countries[sel].name) || sel;
    }

    function bucketOf(period){
      return period.length === 4 ? period : (period.slice(0,4) === '2026' ? '2026' : null);
    }

    // '전체'(ALL)를 한쪽에 걸면 그 쪽은 총액 막대가 아니라 상대국별 무역액
    // 추이(선그래프)로 보여준다 — 2026-08-29 요청. 처음엔 순위(y축=등수)로
    // 그렸는데, 등수 밖(20위 밖)으로 밀리는 해마다 선이 뚝뚝 끊겨 보기
    // 안 좋다는 지적을 받고 y축을 순위 대신 실제 금액으로 바꿨다 — 이제는
    // 그 나라가 그 해에 실제로 신고가 없을 때만(값 자체가 0) 끊긴다.
    const RANK_TOP_N = 14;
    const RANK_PALETTE = ['#c62828','#1a5fb4','#2f6f9f','#c9822f','#5b8c5a','#8a4fae','#b8860b','#0f9b8e','#d2691e','#6b6b68',
      '#e91e8c','#4b0082','#2e7d32','#ff7043','#455a64','#9c27b0'];

    const OTHER_COLOR = '#9c9c96';

    // basis: 'export'면 수출국이 자체 신고한 값(flow X)만, 'import'면 수입국이 자체
    // 신고한 값(flow M)만 쓴다 — 두 통계는 미러 괴리가 있을 수 있어 섞지 않고 하나만 쓴다.
    function computeRankSeries(mode, basis, euMode, groupByClub){
      const data = {};
      const wantFlow = basis === 'import' ? 'M' : 'X';
      for (const [rep, par, period, cmd, flow, value] of rows) {
        if (!matchesHs(cmd)) continue;
        if (flow !== wantFlow) continue;
        const bucket = bucketOf(period);
        if (!bucket) continue;
        let country = null;
        if (mode === 'importer') {
          // 수출국(expSel)을 고정하고 수입국별로 나눈다 — 수입국 쪽이 특정 클럽·EU라면 그 구성원으로만 좁힌다.
          if (basis === 'import') { if (!matches(par, expSel.value)) continue; country = rep; }
          else { if (!matches(rep, expSel.value)) continue; country = par; }
          if (!matches(country, impSel.value)) continue;
        } else if (mode === 'exporter') {
          // 수입국(impSel)을 고정하고 수출국별로 나눈다 — 수출국 쪽이 특정 클럽·EU라면 그 구성원으로만 좁힌다.
          if (basis === 'import') { if (!matches(rep, impSel.value)) continue; country = par; }
          else { if (!matches(par, impSel.value)) continue; country = rep; }
          if (!matches(country, expSel.value)) continue;
        } else {
          // global: 세계 전체를 수출국(또는 수입국) 신고 기준으로 나눈다.
          country = rep;
        }
        if (!country) continue;
        // 단위=클럽 + 전체를 고른 경우: 국가별이 아니라 클럽(US/CN/NON/UNK)별로 묶는다.
        if (groupByClub) { country = (countries[country] && countries[country].club) || 'UNK'; }
        else if (euMode === 'combined' && EU27_ISO3.has(country)) country = 'EU';
        if (!data[country]) data[country] = {};
        data[country][bucket] = (data[country][bucket] || 0) + value;
      }
      const combined = {};
      Object.keys(data).forEach(c => {
        combined[c] = {};
        YEARS.forEach(y => { combined[c][y] = data[c][y] || 0; });
      });
      return combined;
    }

    function renderRankChart(mode, basis, euMode, shareMode, groupByClub){
      const combined = computeRankSeries(mode, basis, euMode, groupByClub);
      const displayYears = trimYears(YEARS, y => Object.keys(combined).some(c => (combined[c][y] || 0) > 0));

      function label_of(c){
        if (c === '기타') return '기타';
        if (c === 'EU') return 'EU';
        if (groupByClub) return CLUB_FULL_LABEL[c] || c;
        return (countries[c] && countries[c].name) || c;
      }
      function esc_js(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

      const basisLabel = basis === 'import' ? '수입국 신고' : '수출국 신고';
      const euSuffix = (!groupByClub && euMode === 'combined') ? ' · EU 27개국 통합' : '';
      const shareSuffix = shareMode ? ' · 구성비율(100%)' : '';
      const PRODUCT = currentProductLabel();
      const HS_NOTE = currentHsNote();
      const unitWord = groupByClub ? '클럽별' : '국가별';
      let mainTitle, detailLine1;
      if (mode === 'importer') {
        // impSel이 '전체'면 <A의 국가별/클럽별 수출 구성>, 특정 클럽·EU 하나로 좁혔으면 <A → B 수출 구성>.
        mainTitle = impSel.value === 'ALL'
          ? `<${label(expSel.value)}의 ${unitWord} ${PRODUCT} 수출 구성>`
          : `<${label(expSel.value)} → ${label(impSel.value)} ${PRODUCT} 수출 구성>`;
        detailLine1 = `상대국(수입국)별, 연도별 · ${basisLabel} 기준${euSuffix}${shareSuffix}`;
      } else if (mode === 'exporter') {
        mainTitle = expSel.value === 'ALL'
          ? `<${label(impSel.value)}의 ${unitWord} ${PRODUCT} 수입 구성>`
          : `<${label(expSel.value)} → ${label(impSel.value)} ${PRODUCT} 수입 구성>`;
        detailLine1 = `상대국(수출국)별, 연도별 · ${basisLabel} 기준${euSuffix}${shareSuffix}`;
      } else {
        mainTitle = `<전 세계 ${unitWord} ${PRODUCT} 무역 구성>`;
        detailLine1 = `${basisLabel} 기준, 연도별 구성${euSuffix}${shareSuffix}`;
      }
      const summaryText = `${mainTitle} — ${detailLine1} (${HS_NOTE})`;
      document.getElementById('oil-summary').textContent = summaryText;

      const totalByYear = {};
      displayYears.forEach(y => {
        let s = 0;
        Object.keys(combined).forEach(c => { s += combined[c][y] || 0; });
        totalByYear[y] = s;
      });

      // 연도마다 그 해 자체 상위 N개국을 따로 고른다 (고정된 최근연도 순위가 아니다).
      const topByYear = {};
      displayYears.forEach(y => {
        topByYear[y] = Object.keys(combined)
          .map(c => [c, combined[c][y] || 0])
          .filter(([, v]) => v > 0)
          .sort((a, b) => b[1] - a[1])
          .slice(0, RANK_TOP_N)
          .map(([c]) => c);
      });

      // 어느 해든 상위권에 든 적 있는 국가 전부에 전체 기간 합계 기준으로 고정 색을 준다
      // — 그래야 같은 나라가 해마다 같은 색으로 보인다.
      const everTop = new Set();
      displayYears.forEach(y => topByYear[y].forEach(c => everTop.add(c)));
      const overallTotal = {};
      everTop.forEach(c => { overallTotal[c] = displayYears.reduce((s, y) => s + (combined[c][y] || 0), 0); });
      const colorOrder = [...everTop].sort((a, b) => overallTotal[b] - overallTotal[a]);
      const colorOf = {};
      if (groupByClub) {
        colorOrder.forEach(c => { colorOf[c] = CLUB_COLOR[c] || OTHER_COLOR; });
      } else {
        colorOrder.forEach((c, ci) => { colorOf[c] = RANK_PALETTE[ci % RANK_PALETTE.length]; });
      }

      // 연도별 스택: 그 해 상위 N개국(색은 고정) + 기타(나머지 전부, 총액과의 잔차)
      let hasOther = false;
      const stacks = displayYears.map(y => {
        const yearTop = new Set(topByYear[y]);
        const segs = colorOrder.filter(c => yearTop.has(c)).map(c => ({country: c, value: combined[c][y] || 0, color: colorOf[c]}));
        segs.sort((a, b) => b.value - a.value); // 그 해 1위가 맨 아래로 오도록 그 해 값 기준 정렬
        const topSum = segs.reduce((s, seg) => s + seg.value, 0);
        const total = totalByYear[y] || 0;
        const other = Math.max(0, total - topSum);
        if (other > 0) { segs.push({country: '기타', value: other, color: OTHER_COLOR}); hasOther = true; }
        return {year: y, segs, total};
      });

      const maxV = shareMode ? 100 : Math.max(1, ...displayYears.map(y => totalByYear[y] || 0));
      const fmt = v => {
        if (shareMode) return Math.round(v) + '%';
        if (v >= 1e9) return (v/1e9).toFixed(1) + 'B';
        if (v >= 1e6) return (v/1e6).toFixed(0) + 'M';
        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
        return String(Math.round(v));
      };

      const W = 1000, PAD_L = 90, PAD_R = 20, PAD_T = 58, PAD_B = 34, DETAIL_H = 30;
      const plotW = W - PAD_L - PAD_R, plotH = 420;
      const H = PAD_T + plotH + PAD_B + DETAIL_H;
      const groupW = plotW / displayYears.length;
      const barW = groupW * 0.6;
      const scaleY = v => plotH * v / maxV;

      const title = `<text x="${W/2}" y="34" text-anchor="middle" font-size="24" font-weight="700" fill="var(--fg)">${esc_js(mainTitle)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 13).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(detailLine1)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 26).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(HS_NOTE)}</text>`;

      let grid = '';
      for (let g = 0; g <= 4; g++) {
        const gy = PAD_T + plotH - plotH * g / 4;
        grid += `<line x1="${PAD_L}" y1="${gy.toFixed(1)}" x2="${W-PAD_R}" y2="${gy.toFixed(1)}" stroke="var(--line)" stroke-width="1" opacity=".5"/>`;
        grid += `<text x="${PAD_L-8}" y="${(gy+3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(maxV*g/4)}</text>`;
      }

      const NEUTRAL_FILL = 'var(--card)';
      const BORDER_COLOR = 'var(--line)';
      const MIN_LABEL_H = 13;

      let bars = '';
      stacks.forEach((s, i) => {
        const gx = PAD_L + i * groupW + (groupW - barW) / 2;
        let yCursor = PAD_T + plotH;
        s.segs.forEach(seg => {
          const share = s.total > 0 ? (seg.value / s.total * 100).toFixed(1) : '0';
          const h = scaleY(shareMode ? Number(share) : seg.value);
          const segY = yCursor - h;
          const isHi = highlighted.has(seg.country);
          const fill = isHi ? seg.color : NEUTRAL_FILL;
          bars += `<rect data-country="${esc_js(seg.country)}" x="${gx.toFixed(1)}" y="${segY.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${fill}" stroke="${BORDER_COLOR}" stroke-width="1" style="cursor:pointer"><title>${s.year} ${esc_js(label_of(seg.country))}: $${seg.value.toLocaleString()} (${share}%)</title></rect>`;
          if (h >= MIN_LABEL_H) {
            const textColor = isHi ? '#fff' : 'var(--fg)';
            bars += `<text x="${(gx + barW/2).toFixed(1)}" y="${(segY + h/2 + 3).toFixed(1)}" text-anchor="middle" font-size="9" fill="${textColor}" pointer-events="none">${esc_js(seg.country)}</text>`;
          }
          yCursor = segY;
        });
        bars += `<text x="${(gx + barW/2).toFixed(1)}" y="${(PAD_T + plotH + 16)}" text-anchor="middle" font-size="10" fill="var(--muted)">${s.year === '2026' ? '26(상)' : s.year.slice(2)}</text>`;
      });

      document.getElementById('oil-chart').innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" aria-label="${esc_js(summaryText)}">${title}${grid}${bars}</svg>`;
      applyZoom();

      function checkItem(c, color){
        const checked = highlighted.has(c) ? ' checked' : '';
        const displayName = (c === '기타' || c === 'EU') ? c : `${esc_js(label_of(c))} (${esc_js(c)})`;
        return `<label class="check-item"><input type="checkbox" data-country="${esc_js(c)}"${checked}><i class="dot" style="background:${color}"></i>${displayName}</label>`;
      }
      const legendCodes = hasOther ? [...colorOrder, '기타'] : colorOrder.slice();
      const allSelected = legendCodes.length > 0 && legendCodes.every(c => highlighted.has(c));
      const selectAllItem = `<label class="check-item"><input type="checkbox" id="oil-select-all" data-codes="${esc_js(legendCodes.join(','))}"${allSelected ? ' checked' : ''}><i class="dot" style="background:var(--fg)"></i>전체 선택</label>`;
      const heightNote = shareMode ? '막대 높이=해당 연도 구성비(%), 모든 연도가 100%로 맞춰진다.' : '막대 높이=해당 연도 총액.';
      document.getElementById('oil-rank-legend').innerHTML =
        `<span class="legend-meta" style="flex-basis:100%">막대 안 글자는 국가 ISO3 코드. 테두리선으로만 구분하며, 아래서 체크한 국가만 색이 뜬다. 값은 ${basisLabel} 통계만 쓴다(미러 보완 없음) — 반대쪽 신고를 보려면 위 '기준' 토글을 바꾼다. ${heightNote} 매년 그 해 상위 ${RANK_TOP_N}개국을 표시하고(연도마다 구성 국가가 달라질 수 있다) 나머지는 기타로 묶는다. 색은 전 기간 합계 기준으로 고정한다</span>` +
        `<div class="check-legend" style="flex-basis:100%">` +
        colorOrder.map(c => checkItem(c, colorOf[c])).join('') +
        (hasOther ? checkItem('기타', OTHER_COLOR) : '') +
        selectAllItem +
        `</div>`;
    }

    // 'ALL'(전체) 뿐 아니라 클럽(US/CN/NON)·EU도 여러 국가를 묶은 그룹이라
    // 구성(절대비교/구성비율) 보기가 의미 있다 — 단일 국가일 때만 의미 없다.
    function isGroupSel(sel){ return sel === 'ALL' || sel === 'EU' || !!CLUB_LABEL[sel]; }

    function render(){
      const expV = expSel.value, impV = impSel.value;
      const expIsGroup = isGroupSel(expV), impIsGroup = isGroupSel(impV);
      const hasGroup = expIsGroup || impIsGroup;
      const bothAll = expV === 'ALL' && impV === 'ALL';
      document.querySelectorAll('#oil-view-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
        btn.classList.toggle('active', hasGroup && btn.dataset.view === view);
      });
      document.querySelectorAll('#oil-basis-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
        btn.classList.toggle('active', !hasGroup || btn.dataset.basis === rankBasis);
      });
      document.querySelectorAll('#oil-eu-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
      });

      if (hasGroup) {
        document.getElementById('oil-rank-legend').style.display = '';
        // 어느 쪽을 쪼개지: '전체'로 열어둔 쪽이 있으면 그쪽을 쪼개다.
        // (수출국=전체 · 수입국=EU 처럼 양쪽 다 그룹일 때 EU를 회원국별로
        // 쪼개버리지 않고, 'EU가 어디서 수입했나'를 보여주기 위한 우선순위다.)
        const mode = bothAll ? 'global'
          : expV === 'ALL' ? 'exporter'
          : impV === 'ALL' ? 'importer'
          : impIsGroup ? 'importer' : 'exporter';
        // 단위=클럽으로 놓고 '전체'를 고르면 국가별이 아니라 클럽별(US/CN/NON/UNK)로 묶어 보여준다.
        let groupByClub;
        if (mode === 'importer') groupByClub = impSel.mode === 'bloc' && impV === 'ALL';
        else if (mode === 'exporter') groupByClub = expSel.mode === 'bloc' && expV === 'ALL';
        else groupByClub = rankBasis === 'import' ? (impSel.mode === 'bloc') : (expSel.mode === 'bloc');
        if (groupByClub) {
          document.querySelectorAll('#oil-eu-toggle .toggle-btn').forEach(btn => btn.classList.add('disabled'));
        }
        renderRankChart(mode, rankBasis, euMode, view === 'share', groupByClub);
        return;
      }
      document.getElementById('oil-rank-legend').style.display = 'none';
      const xByYear = {}, mByYear = {};
      YEARS.forEach(y => { xByYear[y] = 0; mByYear[y] = 0; });
      let matchedRows = 0;
      for (const [rep, par, period, cmd, flow, value] of rows) {
        if (!matchesHs(cmd)) continue;
        const bucket = bucketOf(period);
        if (!bucket) continue;
        if (flow === 'X' && matches(rep, expV) && matches(par, impV)) {
          xByYear[bucket] += value; matchedRows++;
        } else if (flow === 'M' && matches(rep, impV) && matches(par, expV)) {
          mByYear[bucket] += value; matchedRows++;
        }
      }

      const displayYears = trimYears(YEARS, y => xByYear[y] > 0 || mByYear[y] > 0);
      const maxV = Math.max(1, ...displayYears.map(y => Math.max(xByYear[y], mByYear[y])));
      const W = 1000, PAD_L = 90, PAD_R = 20, PAD_T = 58, PAD_B = 34, DETAIL_H = 30;
      const plotW = W - PAD_L - PAD_R, plotH = 260;
      const H = PAD_T + plotH + PAD_B + DETAIL_H;
      const groupW = plotW / displayYears.length;
      const barW = groupW * 0.36;
      const scaleY = v => plotH * v / maxV;
      function esc_js(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
      const PRODUCT = currentProductLabel();
      const HS_NOTE = currentHsNote();
      const mainTitle = `<${label(expV)} → ${label(impV)} ${PRODUCT} 무역>`;
      const detailLine1 = `매칭 ${matchedRows.toLocaleString()}건`;
      const summaryText = `${mainTitle} — ${detailLine1} (${HS_NOTE})`;
      const title = `<text x="${W/2}" y="34" text-anchor="middle" font-size="24" font-weight="700" fill="var(--fg)">${esc_js(mainTitle)}</text>` +
        `<rect x="${PAD_L}" y="46" width="10" height="10" fill="${X_COLOR}"></rect>` +
        `<text x="${PAD_L+14}" y="55" font-size="11" fill="var(--fg)">수출국 신고</text>` +
        `<rect x="${PAD_L+100}" y="46" width="10" height="10" fill="${M_COLOR}"></rect>` +
        `<text x="${PAD_L+114}" y="55" font-size="11" fill="var(--fg)">수입국 신고</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 13).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(detailLine1)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 26).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(HS_NOTE)}</text>`;

      const fmt = v => {
        if (v >= 1e9) return (v/1e9).toFixed(1) + 'B';
        if (v >= 1e6) return (v/1e6).toFixed(0) + 'M';
        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
        return String(Math.round(v));
      };

      let bars = '';
      displayYears.forEach((y, i) => {
        const gx = PAD_L + i * groupW;
        const xh = scaleY(xByYear[y]), mh = scaleY(mByYear[y]);
        const xy = PAD_T + plotH - xh, my = PAD_T + plotH - mh;
        bars += `<rect x="${(gx + groupW*0.08).toFixed(1)}" y="${xy.toFixed(1)}" width="${barW.toFixed(1)}" height="${xh.toFixed(1)}" fill="${X_COLOR}"><title>${y} 수출국(${label(expV)}) 신고: $${xByYear[y].toLocaleString()}</title></rect>`;
        bars += `<rect x="${(gx + groupW*0.08 + barW + 3).toFixed(1)}" y="${my.toFixed(1)}" width="${barW.toFixed(1)}" height="${mh.toFixed(1)}" fill="${M_COLOR}"><title>${y} 수입국(${label(impV)}) 신고: $${mByYear[y].toLocaleString()}</title></rect>`;
        bars += `<text x="${(gx + groupW/2).toFixed(1)}" y="${(PAD_T + plotH + 16)}" text-anchor="middle" font-size="10" fill="var(--muted)">${y === '2026' ? '26(상)' : y.slice(2)}</text>`;
      });
      // y축 그리드 4단
      let grid = '';
      for (let g = 0; g <= 4; g++) {
        const gy = PAD_T + plotH - plotH * g / 4;
        grid += `<line x1="${PAD_L}" y1="${gy.toFixed(1)}" x2="${W-PAD_R}" y2="${gy.toFixed(1)}" stroke="var(--line)" stroke-width="1" opacity=".5"/>`;
        grid += `<text x="${PAD_L-8}" y="${(gy+3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(maxV*g/4)}</text>`;
      }

      document.getElementById('oil-chart').innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" aria-label="${esc_js(summaryText)}">${title}${grid}${bars}</svg>`;
      applyZoom();
      document.getElementById('oil-summary').textContent = summaryText;
    }

    render();
  }
})();
</script>
<script>
function scaleWidth(c, maxCount){
  if (c <= 0) return 0;
  return 140 * c / Math.max(1, maxCount);
}

const flowPanels = [...document.querySelectorAll('.panel')];
const globalScaleMax = Math.max(1, ...flowPanels.flatMap(panel => {
  const series = JSON.parse(panel.dataset.cumAll || '{}');
  return Object.values(series.net || {}).map(arr => Math.abs(arr[arr.length - 1] || 0));
}));

flowPanels.forEach(panel => {
  const slider = panel.querySelector('.date-slider');
  const label = panel.querySelector('.date-label');
  const dates = JSON.parse(slider.dataset.dates);
  const cumByTopic = {
    // data-* 이름에서 하이픈 다음이 숫자면 dataset camelCase 변환 대상이
    // 아니다. getAttribute로 직접 읽어야 HS별 누적값이 빈 객체가 되지 않는다.
    '2709': JSON.parse(panel.getAttribute('data-cum-2709') || '{}'),
    '2710': JSON.parse(panel.getAttribute('data-cum-2710') || '{}'),
    'both': JSON.parse(panel.dataset.cumBoth || '{}'),
    'all': JSON.parse(panel.dataset.cumAll || '{}')
  };
  let agg = 'bloc', topic = 'both';

  function showView(){
    panel.querySelectorAll('.flow-view').forEach(v => v.classList.remove('active'));
    const v = panel.querySelector('.view-' + agg + '.view-' + topic);
    if (v) v.classList.add('active');
  }

  function render(){
    const idx = +slider.value;
    const cutoff = dates[idx];
    label.textContent = cutoff;
    panel.querySelectorAll('.view-country .flow').forEach(el => {
      const d = el.dataset.date;
      el.classList.toggle('shown', d <= cutoff);
      el.classList.toggle('today', d === cutoff);
    });
    const series = cumByTopic[topic] || {net:{},red:{},green:{}};
    const cum = series.net || {};
    panel.querySelectorAll('.view-bloc.view-' + topic + ' .flow-bloc').forEach(el => {
      const arr = cum[el.dataset.pair] || [];
      const c = arr[idx] || 0;
      el.style.strokeWidth = scaleWidth(Math.abs(c), globalScaleMax);
      el.style.stroke = c > 0 ? '#c62828' : c < 0 ? '#2e7d32' : '#8a8a86';
      el.style.opacity = c !== 0 ? 0.85 : 0.06;
    });
    panel.querySelectorAll('.view-bloc.view-' + topic + ' .bloc-count').forEach(el => {
      const bloc = el.dataset.bloc;
      const sumBloc = byPair => Object.entries(byPair || {}).reduce((sum, [pair, arr]) =>
        pair.endsWith('_' + bloc) ? sum + (arr[idx] || 0) : sum, 0);
      const red = sumBloc(series.red);
      const green = sumBloc(series.green);
      el.textContent = ' (' + (red - green) + ' = ' + red + ' − ' + green + ')';
    });
  }

  slider.addEventListener('input', render);
  panel.querySelectorAll('.agg-toggle .toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.agg-toggle .toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      agg = btn.dataset.agg;
      showView();
    });
  });
  panel.querySelectorAll('.topic-toggle .toggle-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      panel.querySelectorAll('.topic-toggle .toggle-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      topic = btn.dataset.topic;
      showView();
      render();
    });
  });

  render();
});
</script>
</body></html>
"""


def build(out: Path) -> bool:
    if not BSV.is_file() or not WORLD.is_file() or not all(p.is_file() for _, _, p in THREADS):
        return False
    pos = load_bsv()
    blocs = build_blocs(pos)
    geo = json.loads(WORLD.read_text(encoding="utf-8"))
    map_svg = render_map_svg(blocs, geo)
    country_list_html = render_country_list(blocs, geo)

    arrows_by_path = {csv_path: load_narrow_events(csv_path) for _, _, csv_path in THREADS}
    global_scale_max = max(
        (max_bloc_pair_count(blocs, arrows) for arrows in arrows_by_path.values()),
        default=1,
    )

    panels = []
    for label, gta_name, csv_path in THREADS:
        total = len(pd.read_csv(csv_path))
        n_narrow = count_narrow_rows(csv_path)
        n_narrow_oil = count_narrow_rows(csv_path, oil_only=True)
        arrows_all = arrows_by_path[csv_path]
        arrows_2709 = [a for a in arrows_all if "2709" in a["hs_codes"]]
        arrows_2710 = [a for a in arrows_all if "2710" in a["hs_codes"]]
        arrows_oil = [a for a in arrows_all if a["oil"]]
        dates = sorted({a["date"] for a in arrows_all})

        flow_country_all = render_flow_diagram(blocs, arrows_all)
        flow_country_2709 = render_flow_diagram(blocs, arrows_2709)
        flow_country_2710 = render_flow_diagram(blocs, arrows_2710)
        flow_country_oil = render_flow_diagram(blocs, arrows_oil)
        flow_bloc_all, cum_all = render_bloc_flow_diagram(blocs, arrows_all, dates, global_scale_max)
        flow_bloc_2709, cum_2709 = render_bloc_flow_diagram(blocs, arrows_2709, dates, global_scale_max)
        flow_bloc_2710, cum_2710 = render_bloc_flow_diagram(blocs, arrows_2710, dates, global_scale_max)
        flow_bloc_oil, cum_oil = render_bloc_flow_diagram(blocs, arrows_oil, dates, global_scale_max)

        panels.append(
            PANEL_HTML.replace("__THREAD_LABEL__", esc(label))
            .replace("__THREAD_GTA_NAME__", esc(gta_name))
            .replace("__N_TOTAL__", str(total))
            .replace("__N_NARROW__", str(n_narrow))
            .replace("__N_NARROW_OIL__", str(n_narrow_oil))
            .replace("__N_ARROWS__", str(len(arrows_all)))
            .replace("__N_ARROWS_OIL__", str(len(arrows_oil)))
            .replace("__FLOW_COUNTRY_2709__", flow_country_2709)
            .replace("__FLOW_COUNTRY_2710__", flow_country_2710)
            .replace("__FLOW_COUNTRY_BOTH__", flow_country_oil)
            .replace("__FLOW_COUNTRY_ALL__", flow_country_all)
            .replace("__FLOW_BLOC_2709__", flow_bloc_2709)
            .replace("__FLOW_BLOC_2710__", flow_bloc_2710)
            .replace("__FLOW_BLOC_BOTH__", flow_bloc_oil)
            .replace("__FLOW_BLOC_ALL__", flow_bloc_all)
            .replace("__CUM_2709_JSON__", esc(json.dumps(cum_2709, separators=(",", ":"))))
            .replace("__CUM_2710_JSON__", esc(json.dumps(cum_2710, separators=(",", ":"))))
            .replace("__CUM_BOTH_JSON__", esc(json.dumps(cum_oil, separators=(",", ":"))))
            .replace("__CUM_ALL_JSON__", esc(json.dumps(cum_all, separators=(",", ":"))))
            .replace("__DATE_MIN__", dates[0] if dates else "-")
            .replace("__DATE_MAX__", dates[-1] if dates else "-")
            .replace("__MAX_DATE_IDX__", str(max(0, len(dates) - 1)))
            .replace("__DATES_JSON__", esc(json.dumps(dates)))
        )
        print(f"[bloc_site] {label}: 원문 {total}건 · 좁게 표적한 조치 {n_narrow}건(연결선 {len(arrows_all)}) · "
              f"석유 {n_narrow_oil}건(연결선 {len(arrows_oil)})")

    import build_oil_data
    oil_ok = build_oil_data.build(out)
    oil_row_count = "0"
    if oil_ok:
        oil_payload = json.loads((out / "oil_trade.json").read_text(encoding="utf-8"))
        oil_row_count = f"{len(oil_payload['rows']):,}"

    html = (
        HTML.replace("__MAP_SVG__", map_svg)
        .replace("__COUNTRY_LIST__", country_list_html)
        .replace("__PANELS__", "".join(panels))
        .replace("__TARGET_YEAR__", str(TARGET_YEAR))
        .replace("__OIL_ROW_COUNT__", oil_row_count)
    )
    (out / "bloc.html").write_text(html, encoding="utf-8")
    (out / "bloc.json").write_text(
        json.dumps({"blocs": blocs, "target_year": TARGET_YEAR}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    return True


if __name__ == "__main__":
    site_dir = HERE / "site"
    ok = build(site_dir)
    print("built" if ok else "missing source files — skipped")
