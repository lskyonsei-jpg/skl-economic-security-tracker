"""「석유 산업의 분절화와 재연결(검증용)」 — site/oil_verify.html 을 만든다.

bloc.html(탐색기)은 손대지 않는다. 이 화면은 site/oil_trade.json(build_oil_data.py
산출)만 읽어, "분절화와 재연결"이라는 제목이 HS 2709·2710·2711 무역 데이터
(2010~2026)로 뒷받침되는지를 명제 다섯 개로 나눠 그래프와 판정으로 보인다.

- 판정(성립/불성립/판정불가)은 글로 꾸미지 않고 아래 VERDICT_RULES 의 수치
  기준으로 기계적으로 낸다. 기준은 각 절 해석에 그대로 적는다.
- 모든 그래프의 기본선은 수입국 신고다. 러시아(2022~)·이란(2023~)·베네수엘라
  (2014~)는 자체 신고가 끊기므로 수출국 신고를 기본으로 쓰면 선이 통째로
  사라진다(0절에서 보인다). 수출국 신고선은 옅은 점선으로 같이 그려 괴리를
  숨기지 않는다.
- 그래프는 다른 패널처럼 인라인 SVG. 외부 CDN·라이브러리 없음.
- 2026년은 1~6월(월별 period 202601~202606)뿐이라 연간 축에서는 "26 H1"로 표시한다.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import bloc_site as bs
from bloc_site import esc

HERE = Path(__file__).resolve().parent
TITLE = "석유 산업의 분절화와 재연결(검증용)"
YEARS = list(range(2010, 2027))
MONTHS_2026 = [f"2026{m:02d}" for m in range(1, 7)]

EU27 = {
    "AUT", "BEL", "BGR", "HRV", "CYP", "CZE", "DNK", "EST", "FIN", "FRA", "DEU", "GRC",
    "HUN", "IRL", "ITA", "LVA", "LTU", "LUX", "MLT", "NLD", "POL", "PRT", "ROU", "SVK",
    "SVN", "ESP", "SWE",
}
GULF = {"SAU", "ARE", "IRQ", "KWT", "QAT"}
EAST_ASIA = {"CHN", "JPN", "KOR", "IND"}
HS2711 = {"LNG", "PIPE", "LPG", "GAS_OTHER"}  # build_oil_data.py 가 2711 을 네 버킷으로 바꿔 둔다

KO = {
    "RUS": "러시아", "IRN": "이란", "VEN": "베네수엘라", "IND": "인도", "CHN": "중국",
    "TUR": "튀르키예", "MYS": "말레이시아", "JPN": "일본", "KOR": "한국", "SAU": "사우디",
    "ARE": "UAE", "IRQ": "이라크", "KWT": "쿠웨이트", "QAT": "카타르",
}

# 색은 사이트 팔레트(bloc_site.BLOC_COLOR 계열)에서 고른다.
C_PLUM, C_BLUE, C_RED, C_GREEN, C_GRAY, C_AMBER, C_TEAL = (
    "#7b1f52", "#1a5fb4", "#c62828", "#2e7d32", "#6b6b67", "#b26a00", "#00796b",
)

# 판정 기준 — 숫자는 해석문에도 그대로 찍힌다.
VERDICT_RULES = {
    "frag_drop": 0.5,       # ① 2023 EU←RUS 가 2021 의 50% 미만이면 성립
    "redirect_share": 0.5,  # ② (IND+CHN 증가분)/(EU 감소분) ≥ 50% 이면 성립, 2021→2023
    "second_mult": 2.0,     # ③ IND→EU 2710 2023 ≥ 2021 의 2배이면 성립
    "iran_left": 0.2,       # ④ CHN←IRN 2022 가 2018 의 20% 미만이고
    "mys_mult": 2.0,        #    CHN←MYS 2024 ≥ 2021 의 2배이면 성립
}


# ---------------------------------------------------------------- 데이터
def load_payload(out: Path) -> dict | None:
    path = out / "oil_trade.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["_mtime"] = datetime.fromtimestamp(path.stat().st_mtime)
    return payload


def year_of(period: str) -> int:
    return int(period[:4])


def series(rows, exporters: set, importers: set, hs: set, src: str, monthly: bool = False) -> dict:
    """수출국 집합→수입국 집합, 품목 집합의 금액(USD) 합.

    src='M': 수입국 신고(reporter∈importers, partner∈exporters, flow M)
    src='X': 수출국 신고(reporter∈exporters, partner∈importers, flow X)
    monthly=False 면 연도 키(2026 은 1~6월 합), True 면 202601~202606 월 키만.
    """
    out: dict = defaultdict(float)
    for r, p, per, c, f, v in rows:
        if c not in hs or f != src:
            continue
        if src == "M":
            if r not in importers or p not in exporters:
                continue
        else:
            if r not in exporters or p not in importers:
                continue
        if monthly:
            if len(per) == 6:
                out[per] += v
        else:
            out[year_of(per)] += v
    return dict(out)


def coverage(rows) -> dict:
    """(reporter, flow) -> 신고된 period 집합."""
    cov: dict = defaultdict(set)
    for r, p, per, c, f, v in rows:
        cov[(r, f)].add(per)
    return cov


def latest_period(cov: dict, iso3: str, flow: str = "M") -> str:
    ps = cov.get((iso3, flow))
    if not ps:
        return "없음"
    latest = max(ps, key=lambda s: (s[:4], s[4:]))
    return latest if len(latest) == 4 else f"{latest[:4]}.{latest[4:]}"


# ---------------------------------------------------------------- 그래프
def _nice_step(vmax: float) -> float:
    if vmax <= 0:
        return 1.0
    import math
    raw = vmax / 4
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag
    return 10 * mag


def _fmt(v: float) -> str:
    if v >= 100:
        return f"{v:,.0f}"
    if v >= 10:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def _fmt_tick(v: float, step: float) -> str:
    """눈금은 간격에 맞춰 자릿수를 통일한다(0, 50, 100 / 0, 2.5, 5.0)."""
    if step >= 1:
        return f"{v:,.0f}"
    if step >= 0.1:
        return f"{v:,.1f}"
    return f"{v:,.2f}"


def _mark_label(x: float, k: int, label: str, width: int, mr: int, mt: int) -> str:
    """세로 표식 글자. 오른쪽 끝에 가까우면 왼쪽으로 붙이고, 여러 개면 줄을 내린다."""
    yy = mt + 12 + 13 * k
    if x > width * 0.72:
        return f'<text x="{x - 4:.1f}" y="{yy}" text-anchor="end" class="mark-label">{esc(label)}</text>'
    return f'<text x="{x + 4:.1f}" y="{yy}" class="mark-label">{esc(label)}</text>'


def line_chart(series_list: list[dict], *, marks: list[tuple[int, str]] | None = None,
               width: int = 920, height: int = 340, unit: str = "십억 달러") -> str:
    """연간 꺾은선. series_list 항목: label, color, data({year: usd}), faint(bool).
    faint 는 수출국 신고선 — 옅은 점선. 값이 없는 연도는 선을 끊는다."""
    ml, mr, mt, mb = 60, 20, 18, 34
    pw, ph = width - ml - mr, height - mt - mb
    n = len(YEARS)
    vals = [v / 1e9 for s in series_list for v in s["data"].values()]
    vmax = max(vals) if vals else 1.0
    step = _nice_step(vmax)
    top = step * (int(vmax / step) + 1)

    def x(i):
        return ml + i * pw / (n - 1)

    def y(v):
        return mt + (1 - v / top) * ph

    parts = [f'<svg class="vchart" viewBox="0 0 {width} {height}" role="img">']
    # 격자·y축
    t = 0.0
    while t <= top + 1e-9:
        yy = y(t)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width - mr}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" class="tick">{_fmt_tick(t, step)}</text>')
        t += step
    parts.append(f'<text x="{ml - 8}" y="{mt - 6}" text-anchor="end" class="tick unit">{esc(unit)}</text>')
    # x축
    for i, yr in enumerate(YEARS):
        label = "26 H1" if yr == 2026 else f"'{yr % 100:02d}"
        parts.append(f'<text x="{x(i):.1f}" y="{height - mb + 18}" text-anchor="middle" class="tick">{label}</text>')
    # 표식(세로 점선)
    for k, (yr, label) in enumerate(marks or []):
        if yr in YEARS:
            xx = x(YEARS.index(yr))
            parts.append(f'<line x1="{xx:.1f}" y1="{mt}" x2="{xx:.1f}" y2="{mt + ph}" class="mark"/>')
            parts.append(_mark_label(xx, k, label, width, mr, mt))
    # 선
    for s in series_list:
        cls = "ln faint" if s.get("faint") else "ln"
        d, open_ = [], False
        for i, yr in enumerate(YEARS):
            v = s["data"].get(yr)
            if v is None:
                open_ = False
                continue
            d.append(f'{"L" if open_ else "M"}{x(i):.1f},{y(v / 1e9):.1f}')
            open_ = True
        if d:
            parts.append(f'<path d="{" ".join(d)}" class="{cls}" stroke="{s["color"]}"/>')
        if not s.get("faint"):
            for i, yr in enumerate(YEARS):
                v = s["data"].get(yr)
                if v is not None:
                    parts.append(f'<circle cx="{x(i):.1f}" cy="{y(v / 1e9):.1f}" r="3" fill="{s["color"]}">'
                                 f'<title>{esc(s["label"])} {yr}: {_fmt(v / 1e9)} {esc(unit)}</title></circle>')
    parts.append("</svg>")
    legend = "".join(
        f'<span><i class="dot{" faint" if s.get("faint") else ""}" style="background:{s["color"]}"></i>{esc(s["label"])}</span>'
        for s in series_list
    )
    return f'<div class="vchart-wrap">{"".join(parts)}</div><div class="legend">{legend}</div>'


def month_chart(bars: list[dict], lines: list[dict], faint: dict | None, *, width: int = 920,
                height: int = 300, unit: str = "십억 달러") -> str:
    """2026년 1~6월 막대 + 기준선. bars: label,color,data({period: usd}).
    lines: label,color,value(usd, 수평 기준선). faint: label,color,data — 수출국 신고 점선."""
    ml, mr, mt, mb = 60, 20, 18, 34
    pw, ph = width - ml - mr, height - mt - mb
    n = len(MONTHS_2026)
    vals = [v / 1e9 for b in bars for v in b["data"].values()] + [l["value"] / 1e9 for l in lines]
    if faint:
        vals += [v / 1e9 for v in faint["data"].values()]
    vmax = max(vals) if vals else 1.0
    step = _nice_step(vmax)
    top = step * (int(vmax / step) + 1)
    slot = pw / n
    bw = slot * 0.7 / max(1, len(bars))

    def y(v):
        return mt + (1 - v / top) * ph

    parts = [f'<svg class="vchart" viewBox="0 0 {width} {height}" role="img">']
    t = 0.0
    while t <= top + 1e-9:
        yy = y(t)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width - mr}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{ml - 8}" y="{yy + 4:.1f}" text-anchor="end" class="tick">{_fmt_tick(t, step)}</text>')
        t += step
    parts.append(f'<text x="{ml - 8}" y="{mt - 6}" text-anchor="end" class="tick unit">{esc(unit)}</text>')
    for i, per in enumerate(MONTHS_2026):
        cx = ml + slot * (i + 0.5)
        parts.append(f'<text x="{cx:.1f}" y="{height - mb + 18}" text-anchor="middle" class="tick">26.{per[4:]}</text>')
        for j, b in enumerate(bars):
            v = b["data"].get(per)
            if v is None:
                continue
            x0 = cx - slot * 0.35 + j * bw
            parts.append(f'<rect x="{x0:.1f}" y="{y(v / 1e9):.1f}" width="{bw:.1f}" height="{mt + ph - y(v / 1e9):.1f}" fill="{b["color"]}">'
                         f'<title>{esc(b["label"])} {per[:4]}.{per[4:]}: {_fmt(v / 1e9)} {esc(unit)}</title></rect>')
    for l in lines:
        yy = y(l["value"] / 1e9)
        parts.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{width - mr}" y2="{yy:.1f}" class="ref" stroke="{l["color"]}"/>')
        parts.append(f'<text x="{ml + 4}" y="{yy - 4:.1f}" class="mark-label" fill="{l["color"]}">{esc(l["label"])}</text>')
    if faint:
        d, open_ = [], False
        for i, per in enumerate(MONTHS_2026):
            v = faint["data"].get(per)
            if v is None:
                open_ = False
                continue
            d.append(f'{"L" if open_ else "M"}{ml + slot * (i + 0.5):.1f},{y(v / 1e9):.1f}')
            open_ = True
        if d:
            parts.append(f'<path d="{" ".join(d)}" class="ln faint" stroke="{faint["color"]}"/>')
    parts.append("</svg>")
    legend = "".join(f'<span><i class="dot" style="background:{b["color"]}"></i>{esc(b["label"])}</span>' for b in bars)
    legend += "".join(f'<span><i class="dot ref" style="background:{l["color"]}"></i>{esc(l["label"])}</span>' for l in lines)
    if faint:
        legend += f'<span><i class="dot faint" style="background:{faint["color"]}"></i>{esc(faint["label"])}</span>'
    return f'<div class="vchart-wrap">{"".join(parts)}</div><div class="legend">{legend}</div>'


# ---------------------------------------------------------------- 본문 조각
VERDICT_CLASS = {"성립": "v-ok", "불성립": "v-no", "판정불가": "v-na"}


def claim_block(num: str, heading: str, prop: str, chart: str, verdict: str, interp: list[str],
                note: str | None = None) -> str:
    lines = "".join(f"<p class=\"interp\">{line}</p>" for line in interp)
    note_html = f'<p class="note">{note}</p>' if note else ""
    return (
        f'<section class="claim" id="c{num}">'
        f'<h2>{esc(num)} {esc(heading)}</h2>'
        f'<p class="prop"><b>명제</b> {prop}</p>'
        f"{chart}"
        f'<p class="verdict {VERDICT_CLASS[verdict]}">판정: {verdict}</p>'
        f"{lines}{note_html}</section>"
    )


def bn(v: float | None) -> str:
    """USD -> '12.3' (십억 달러). 없으면 '—'."""
    return "—" if v is None else _fmt(v / 1e9)


def pct(a: float | None, b: float | None) -> str:
    if not a or b is None:
        return "—"
    return f"{(b - a) / a * 100:+.0f}%"


# ---------------------------------------------------------------- 부록
def club_diff() -> dict:
    """bloc_site.build_blocs(국가명 키) vs build_oil_data.build_blocs_by_iso3(ISO3 키)
    전 국가 비교. BSV tab 의 (Countryname, iso3c) 짝으로 잇는다. 고치지 않고 보이기만."""
    import build_oil_data as bod
    by_name = bs.build_blocs(bs.load_bsv())
    by_iso = bod.build_blocs_by_iso3()
    pairs: dict[str, set[str]] = defaultdict(set)
    with bs.BSV.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            pairs[r["Countryname"]].add(r["iso3c"].strip('"'))
    iso_names: dict[str, set[str]] = defaultdict(set)
    for n, s in pairs.items():
        for i in s:
            iso_names[i].add(n)
    diffs = []
    for n, club in sorted(by_name.items()):
        for i in sorted(pairs.get(n, ())):
            c2 = by_iso.get(i)
            if c2 != club:
                diffs.append((n, i, club, c2 or "없음"))
    name_isos = {i for n in by_name for i in pairs.get(n, ())}
    only_iso = sorted(set(by_iso) - name_isos)
    return {
        "n_name": len(by_name), "n_iso": len(by_iso), "diffs": diffs, "only_iso": only_iso,
        "dup_iso": {i: sorted(ns) for i, ns in iso_names.items() if len(ns) > 1 and any(n in by_name for n in ns)},
    }


def raw_stats() -> dict:
    """원자료 CSV 가 있으면 행 수·매핑 실패·mtime 을 센다. 없으면 없다고 적는다."""
    import build_oil_data as bod
    out = {"files": []}
    missing = False
    for p in (bod.RAW_2709_2710, bod.RAW_2711_HS6):
        shown = str(p.relative_to(bod.ROOT)) if p.is_relative_to(bod.ROOT) else str(p)
        if p.is_file():
            out["files"].append((shown, datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"), p.stat().st_size))
        else:
            out["files"].append((shown, "없음", 0))
            missing = True
    if missing:
        out["dropped"] = None
        return out
    import pandas as pd
    code_to_iso3 = bod.load_code_to_iso3()
    df = pd.concat([pd.read_csv(p, dtype=str) for p, _, _ in [(bod.RAW_2709_2710, 0, 0), (bod.RAW_2711_HS6, 0, 0)]], ignore_index=True)
    bad_r = ~df["reporterCode"].isin(code_to_iso3)
    bad_p = ~df["partnerCode"].isin(code_to_iso3)
    bad = df[bad_r | bad_p]
    codes = defaultdict(int)
    for _, row in bad.iterrows():
        if row["reporterCode"] not in code_to_iso3:
            codes[("reporter", row["reporterCode"])] += 1
        if row["partnerCode"] not in code_to_iso3:
            codes[("partner", row["partnerCode"])] += 1
    out["raw_rows"] = len(df)
    out["dropped"] = len(bad)
    out["top_codes"] = sorted(codes.items(), key=lambda kv: -kv[1])[:10]
    return out


# ---------------------------------------------------------------- HTML
STYLE_FROM_BLOC = bs.HTML.split("<style>", 1)[1].split("</style>", 1)[0]

EXTRA_STYLE = r"""
.vchart-wrap{padding:8px;background:var(--bg);border:2px solid var(--line);border-radius:12px;overflow-x:auto}
.vchart{display:block;width:100%;min-width:640px;height:auto;font-size:12px}
.vchart .grid{stroke:var(--line);stroke-opacity:.18;stroke-width:1}
.vchart .tick{fill:var(--muted);font-size:11px;font-weight:700}
.vchart .tick.unit{font-size:10px}
.vchart .ln{fill:none;stroke-width:2.4;stroke-linejoin:round}
.vchart .ln.faint{stroke-width:1.6;stroke-opacity:.45;stroke-dasharray:5 4}
.vchart .ref{stroke-width:1.6;stroke-dasharray:7 4;stroke-opacity:.8}
.vchart .mark{stroke:var(--plum);stroke-dasharray:3 4;stroke-width:1.2;stroke-opacity:.7}
.vchart .mark-label{font-size:10px;fill:var(--plum);font-weight:700}
.dot.faint{opacity:.45;border:1px dashed var(--line);background-clip:padding-box}
.dot.ref{height:3px;border-top:3px dashed currentColor;background:none!important}
.claim{margin:34px 0 10px;padding-top:10px;border-top:2px solid var(--line)}
.claim h2{font-size:1.15rem;margin:0 0 8px;color:var(--plum)}
.prop{margin:0 0 10px;font-size:.92rem}
.verdict{display:inline-block;margin:12px 0 6px;padding:4px 14px;border:2px solid var(--line);border-radius:999px;font-size:.9rem}
.verdict.v-ok{background:#dfeedd;border-color:#2e7d32}
.verdict.v-no{background:#f4d3d0;border-color:#c62828}
.verdict.v-na{background:#e6e6e2;border-color:#6b6b67}
.interp{margin:4px 0;font-size:.88rem}
.intro{font-size:.9rem;margin:0 0 14px}
.mini-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.mini-grid h4{margin:0 0 4px;font-size:.84rem}
.mini-grid .vchart{min-width:0}
table.vt{border-collapse:collapse;width:100%;font-size:.84rem;margin:8px 0 14px}
table.vt th,table.vt td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}
table.vt th{background:var(--card)}
table.vt td.num{text-align:right;font-variant-numeric:tabular-nums}
.appendix h3{font-size:.95rem;margin:18px 0 6px}
code{font-size:.82em;background:var(--card);padding:1px 4px;border-radius:4px}
"""

HEAD = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>__TITLE__ · SKL</title>
<link rel="stylesheet" href="style.css"><style>__STYLE__</style></head><body><div class="wrap">
<a class="back" href="index.html">← 변경 내역</a>
<header class="semi-head" style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
<div><h1 style="margin:0;font-size:1.45rem">__TITLE__</h1>
<p style="margin:4px 0 0;color:var(--muted);font-size:.86rem">UN Comtrade HS 2709·2710·2711, 2010~2026(1~6월) · 탐색기(<a href="bloc.html">석유 산업의 분절화와 재연결</a>)와 같은 데이터</p></div>
</header>
<p class="intro">이 페이지는 「석유 산업의 분절화와 재연결」이라는 제목이 무역 데이터로 뒷받침되는지를 확인하는 검증 보고서다.
제목을 다섯 개의 검증 가능한 명제로 쪼개고, 각 명제마다 <b>한 줄 명제 → 그래프 → 판정 → 두 줄 해석</b> 순서로 적는다.
판정은 각 절에 적힌 수치 기준으로 기계적으로 낸다. 금액은 모두 명목 달러(십억 달러)라 물량이 아니라 금액×유가를 본다는 점을 염두에 둔다.</p>
"""

FOOT = "</div></body></html>\n"


def build(out: Path) -> bool:
    payload = load_payload(out)
    if payload is None:
        print("[oil_verify_site] site/oil_trade.json 없음 — 건너뜀")
        return False
    rows = payload["rows"]
    countries = payload["countries"]
    cov = coverage(rows)
    all_iso = set(countries)
    body: list[str] = []

    # ---------------- 0. 데이터 신뢰도
    mirror = []
    for iso, cut in (("RUS", "2022"), ("IRN", "2023"), ("VEN", "2014")):
        self_x = series(rows, {iso}, all_iso, {"2709", "2710"}, "X")
        partner_m = series(rows, {iso}, all_iso, {"2709", "2710"}, "M")
        last_x = latest_period(cov, iso, "X")
        # 자체 신고가 끊긴 뒤는 "값이 없는" 게 아니라 "0 으로 신고된 것과 같은" 상태다 —
        # 선을 끊지 않고 0 으로 내려 그려야 꺼지는 모습이 보인다.
        last_x_year = max((int(p[:4]) for p in cov.get((iso, "X"), ())), default=None)
        if last_x_year is not None:
            for yr in YEARS:
                if yr > last_x_year:
                    self_x[yr] = 0.0
        chart = line_chart([
            {"label": f"상대국(수입국) 신고 — {KO[iso]}산 2709+2710", "color": C_BLUE, "data": partner_m},
            {"label": f"{KO[iso]} 자체(수출국) 신고", "color": C_RED, "data": self_x, "faint": True},
        ], width=460, height=250)
        mirror.append(f'<div><h4>{esc(KO[iso])} — 자체 신고 마지막 연도: {esc(last_x)}</h4>{chart}</div>')
    body.append(
        '<section class="claim" id="c0"><h2>0. 데이터 신뢰도 — 왜 수입국 신고를 기본선으로 쓰는가</h2>'
        '<p class="intro">UN Comtrade 는 같은 거래를 수출국과 수입국이 각자 신고한다(미러 통계). 둘은 원래도 운임·보험·환적·시차 때문에 맞지 않지만,'
        ' 제재 대상국은 아예 신고를 끊는다. 아래 세 나라는 자체 신고가 어느 해 이후 통째로 0으로 꺼지는데, 상대국 신고는 그 뒤에도 이어진다.'
        ' 그래서 이 페이지의 모든 그래프는 <b>수입국 신고를 기본선(실선)</b>으로 쓰고, 수출국 신고는 <b>옅은 점선</b>으로 같이 그려 둘의 괴리를 숨기지 않는다.'
        ' 수입국 신고가 없는 조합(예: 튀르키예는 원유 2709 수입을 상대국별로 신고하지 않는다)은 그 사실을 그대로 적는다.</p>'
        f'<div class="mini-grid">{"".join(mirror)}</div></section>'
    )

    # ---------------- ① 분절화
    eu_rus_m = series(rows, {"RUS"}, EU27, {"2709", "2710"}, "M")
    eu_rus_x = series(rows, {"RUS"}, EU27, {"2709", "2710"}, "X")
    eu_rus_2709 = series(rows, {"RUS"}, EU27, {"2709"}, "M")
    eu_rus_2710 = series(rows, {"RUS"}, EU27, {"2710"}, "M")
    r = VERDICT_RULES
    v21, v22, v23, v24, v25 = (eu_rus_m.get(y) for y in (2021, 2022, 2023, 2024, 2025))
    frag_ok = v21 and v23 is not None and v23 < r["frag_drop"] * v21
    verdict1 = "성립" if frag_ok else ("판정불가" if v21 is None or v23 is None else "불성립")
    chart1 = line_chart([
        {"label": "EU27←러시아 2709+2710 (EU 신고)", "color": C_PLUM, "data": eu_rus_m},
        {"label": "그중 원유 2709", "color": C_BLUE, "data": eu_rus_2709},
        {"label": "그중 정제품 2710", "color": C_TEAL, "data": eu_rus_2710},
        {"label": "러시아 신고 (2022~ 없음)", "color": C_RED, "data": eu_rus_x, "faint": True},
    ], marks=[(2022, "'22.2 침공"), (2023, "EU 금수 발효('22.12 원유 · '23.2 정제품)")])
    body.append(claim_block(
        "①", "분절화 — EU 가 러시아 석유에서 떨어져 나갔는가",
        "EU27 의 러시아산 원유·정제품(HS 2709·2710) 수입이 2021→2023 에 급감한다.",
        chart1, verdict1,
        [f"EU 신고 기준 EU←러시아 2709+2710: 2021 {bn(v21)} → 2022 {bn(v22)} → 2023 {bn(v23)} → 2024 {bn(v24)} → 2025 {bn(v25)} 십억 달러"
         f" (2021→2023 {pct(v21, v23)}, 2022→2023 {pct(v22, v23)}). 기준: 2023 값이 2021 의 {r['frag_drop']:.0%} 미만이면 성립.",
         "2022 는 침공 뒤 금액이 오히려 늘었는데 이는 금수 발효 전(원유 2022.12, 정제품 2023.2) 선적에 유가 급등이 곱해진 결과다. 분절화는 2023 부터 수치로 나타나며 그 뒤로도 계속 줄어든다."],
    ))

    # ---------------- ② 재연결
    ind_m = series(rows, {"RUS"}, {"IND"}, {"2709"}, "M")
    ind_x = series(rows, {"RUS"}, {"IND"}, {"2709"}, "X")
    chn_m = series(rows, {"RUS"}, {"CHN"}, {"2709"}, "M")
    chn_x = series(rows, {"RUS"}, {"CHN"}, {"2709"}, "X")
    tur_m2709 = series(rows, {"RUS"}, {"TUR"}, {"2709"}, "M")
    tur_x2709 = series(rows, {"RUS"}, {"TUR"}, {"2709"}, "X")
    tur_m2710 = series(rows, {"RUS"}, {"TUR"}, {"2710"}, "M")
    eu_drop = (v21 or 0) - (v23 or 0)
    gain = (ind_m.get(2023, 0) - ind_m.get(2021, 0)) + (chn_m.get(2023, 0) - chn_m.get(2021, 0))
    share = gain / eu_drop if eu_drop > 0 else None
    verdict2 = "판정불가" if share is None else ("성립" if share >= r["redirect_share"] else "불성립")
    chart2 = line_chart([
        {"label": "EU27←러시아 2709+2710 (①, 비교용)", "color": C_PLUM, "data": eu_rus_m},
        {"label": "인도←러시아 2709 (인도 신고)", "color": C_AMBER, "data": ind_m},
        {"label": "중국←러시아 2709 (중국 신고, 2024 까지)", "color": C_RED, "data": chn_m},
        {"label": "튀르키예←러시아 2710 정제품 (튀르키예 신고 · 2709 는 미신고)", "color": C_GREEN, "data": tur_m2710},
        {"label": "러시아 신고 →인도 2709", "color": C_AMBER, "data": ind_x, "faint": True},
        {"label": "러시아 신고 →중국 2709", "color": C_RED, "data": chn_x, "faint": True},
        {"label": "러시아 신고 →튀르키예 2709", "color": C_GREEN, "data": tur_x2709, "faint": True},
    ], marks=[(2022, "'22.2 침공")])
    tur_note = ("튀르키예는 원유(2709) 수입을 상대국별로 신고하지 않아(이 데이터에 튀르키예 신고 2709 행이 "
                f"{len(tur_m2709)}개) 러시아→튀르키예 원유는 러시아 자체 신고(2021 까지)로만 보인다. 대신 정제품 2710 을 그렸다: "
                f"2021 {bn(tur_m2710.get(2021))} → 2023 {bn(tur_m2710.get(2023))} → 2025 {bn(tur_m2710.get(2025))}.")
    body.append(claim_block(
        "②", "재연결 — ①에서 빠진 물량이 어디로 갔는가",
        "EU 가 줄인 만큼 러시아 원유가 인도·중국·튀르키예로 옮겨 간다. ①과 같은 축에 겹쳐 그려 흘러간 모습을 본다.",
        chart2, verdict2,
        [f"인도←러시아 2709: 2021 {bn(ind_m.get(2021))} → 2022 {bn(ind_m.get(2022))} → 2023 {bn(ind_m.get(2023))} → 2024 {bn(ind_m.get(2024))} → 2025 {bn(ind_m.get(2025))} · "
         f"중국←러시아 2709: 2021 {bn(chn_m.get(2021))} → 2023 {bn(chn_m.get(2023))} → 2024 {bn(chn_m.get(2024))} (중국은 2024 까지만 신고). "
         f"2021→2023 인도+중국 증가분 {_fmt(gain / 1e9)} 대 EU 감소분 {_fmt(eu_drop / 1e9)} 십억 달러 = {share * 100:.0f}%" if share is not None else "비교 불가",
         f"기준: 증가분/감소분 ≥ {r['redirect_share']:.0%} 이면 성립. 금액 기준이라 물량 이전을 1:1 로 증명하는 것은 아니지만, EU 가 비운 자리의 크기와 인도·중국이 채운 크기가 같은 해에 같은 규모로 맞물린다. {tur_note}"],
        note="주의: 2022 년 금액 급등에는 유가 효과(브렌트 연평균 2021 약 71 → 2022 약 100 달러)가 섞여 있다. 2022 한 해의 '증가'는 물량보다 가격이 올린 몫이 크고, 물량 재배치는 2023 이후 값으로 읽는 편이 안전하다.",
    ))

    # ---------------- ③ 2차 경로
    ind_eu_m = series(rows, {"IND"}, EU27, {"2710"}, "M")
    ind_eu_x = series(rows, {"IND"}, EU27, {"2710"}, "X")
    a21, a23, a24, a25, a26 = (ind_eu_m.get(y) for y in (2021, 2023, 2024, 2025, 2026))
    verdict3 = "판정불가" if not a21 or a23 is None else ("성립" if a23 >= r["second_mult"] * a21 else "불성립")
    chart3 = line_chart([
        {"label": "EU27←인도 2710 정제품 (EU 신고)", "color": C_PLUM, "data": ind_eu_m},
        {"label": "인도←러시아 2709 원유 (②, 비교용)", "color": C_AMBER, "data": ind_m},
        {"label": "인도 신고 →EU27 2710", "color": C_PLUM, "data": ind_eu_x, "faint": True},
    ], marks=[(2022, "'22.2 침공"), (2026, "'26.1 EU 러시아산 원유 정제품 금수")])
    body.append(claim_block(
        "③", "2차 경로 — 러시아 원유가 인도 정제소를 거쳐 EU 로 되돌아오는가",
        "인도→EU27 정제품(HS 2710) 수출이 인도의 러시아 원유 수입과 같은 시기에 급증한다.",
        chart3, verdict3,
        [f"EU 신고 EU←인도 2710: 2021 {bn(a21)} → 2023 {bn(a23)} → 2024 {bn(a24)} → 2025 {bn(a25)} → 2026 상반기 {bn(a26)} 십억 달러"
         f" (2021→2023 {pct(a21, a23)}). 인도 신고는 같은 해 {bn(ind_eu_x.get(2023))} 로 EU 신고의 두 배가 넘는다 — 네덜란드 등 환적항 경유분이 EU 쪽에서는 다른 경로로 잡히는 미러 괴리다. 기준: 2023 ≥ 2021 의 {r['second_mult']:.0f}배이면 성립.",
         "HS 코드는 원산지를 추적하지 않으므로 이 그래프는 '인도산 정제품이 늘었다'까지만 증명하고 '그 원유가 러시아산'이라는 것은 ②와의 동시성으로 추정할 뿐이다. 2026 상반기 값이 2025 의 절반(연간/2)에 크게 못 미치는 것은 2026.1 발효된 EU 의 러시아산 원유 정제품 수입 금지와 시기가 맞는다."],
    ))

    # ---------------- ④ 이란
    mys_m = series(rows, {"MYS"}, {"CHN"}, {"2709"}, "M")
    mys_x = series(rows, {"MYS"}, {"CHN"}, {"2709"}, "X")
    irn_m = series(rows, {"IRN"}, {"CHN"}, {"2709"}, "M")
    irn_x = series(rows, {"IRN"}, {"CHN"}, {"2709"}, "X")
    i18, i22 = irn_m.get(2018), irn_m.get(2022, 0.0)
    m21, m24 = mys_m.get(2021), mys_m.get(2024)
    iran_gone = bool(i18) and i22 < r["iran_left"] * i18
    mys_up = bool(m21) and m24 is not None and m24 >= r["mys_mult"] * m21
    verdict4 = "판정불가" if (i18 is None or m24 is None) else ("성립" if (iran_gone and mys_up) else "불성립")
    chart4 = line_chart([
        {"label": "중국←이란 2709 (중국 신고)", "color": C_RED, "data": irn_m},
        {"label": "중국←말레이시아 2709 (중국 신고)", "color": C_GREEN, "data": mys_m},
        {"label": "이란 신고 →중국 (2022 까지)", "color": C_RED, "data": irn_x, "faint": True},
        {"label": "말레이시아 신고 →중국", "color": C_GREEN, "data": mys_x, "faint": True},
    ], marks=[(2018, "'18.5 미국 JCPOA 탈퇴"), (2019, "'19.5 면제 종료")])
    body.append(claim_block(
        "④", "이란 — 직수입이 사라지고 '말레이시아산'이 그만큼 뛰는가(환적 지표)",
        "중국의 이란산 원유 수입이 2019 이후 0 에 가깝게 사라지고, 같은 시기 말레이시아산 원유 수입이 말레이시아 자체 생산·수출 능력과 무관하게 급증한다.",
        chart4, verdict4,
        [f"중국 신고 중국←이란 2709: 2018 {bn(i18)} → 2019 {bn(irn_m.get(2019))} → 2020 {bn(irn_m.get(2020))} → 2022 {bn(i22)} → 2023·2024 {bn(irn_m.get(2023, 0.0))} 십억 달러. "
         f"중국←말레이시아 2709: 2018 {bn(mys_m.get(2018))} → 2021 {bn(m21)} → 2022 {bn(mys_m.get(2022))} → 2024 {bn(m24)}. 기준: 이란 2022 < 2018 의 {r['iran_left']:.0%} 이고 말레이시아 2024 ≥ 2021 의 {r['mys_mult']:.0f}배.",
         f"말레이시아가 스스로 신고한 대중국 원유 수출은 2024 {bn(mys_x.get(2024))} 십억 달러로, 중국이 '말레이시아산'으로 신고한 {bn(m24)} 의 {(mys_x.get(2024, 0) / m24 * 100) if m24 else 0:.1f}% 뿐이다. 수출국이 모르는 수출이 수입국 장부에만 있는 것이 환적(선상 환적·원산지 바꿔치기)의 전형적 흔적이다. 중국 신고가 2024 에서 끝나 2025~2026 은 볼 수 없다."],
    ))

    # ---------------- ⑤ 2026 이란 분쟁
    g_m = series(rows, GULF, EAST_ASIA, {"2709"}, "M")
    g_x = series(rows, GULF, EAST_ASIA, {"2709"}, "X")
    g_m2711 = series(rows, GULF, EAST_ASIA, HS2711, "M")
    g_x2711 = series(rows, GULF, EAST_ASIA, HS2711, "X")
    have26 = {c for c in EAST_ASIA if any(len(p) == 6 for p in cov.get((c, "M"), ()))}
    have25m = {c for c in EAST_ASIA if any(p.startswith("2025") and len(p) == 6 for p in cov.get((c, "M"), ()))}
    chart5a = line_chart([
        {"label": "걸프5→동아시아4 원유 2709 (수입국 신고)", "color": C_PLUM, "data": g_m},
        {"label": "걸프5→동아시아4 석유가스 2711 (수입국 신고)", "color": C_TEAL, "data": g_m2711},
        {"label": "걸프 신고 2709", "color": C_PLUM, "data": g_x, "faint": True},
        {"label": "걸프 신고 2711", "color": C_TEAL, "data": g_x2711, "faint": True},
    ])
    bars, refs, table_rows = [], [], []
    colors = {"JPN": C_BLUE, "IND": C_AMBER, "KOR": C_GREEN, "CHN": C_RED}
    for c in ("CHN", "JPN", "KOR", "IND"):
        mon = series(rows, GULF, {c}, {"2709"} | HS2711, "M", monthly=True)
        ann = series(rows, GULF, {c}, {"2709"} | HS2711, "M")
        y25 = ann.get(2025)
        h26 = sum(mon.values()) if mon else None
        if mon:
            bars.append({"label": f"{KO[c]}←걸프5 2709+2711 (월별)", "color": colors[c], "data": mon})
            if y25:
                refs.append({"label": f"{KO[c]} 2025 월평균(연간/12)", "color": colors[c], "value": y25 / 12})
        table_rows.append((KO[c], latest_period(cov, c), bn(y25), bn(y25 / 2) if y25 else "—", bn(h26),
                           pct(y25 / 2, h26) if (y25 and h26 is not None) else "—"))
    sau_mon = series(rows, {"SAU"}, EAST_ASIA, {"2709"} | HS2711, "X", monthly=True)
    # 해석문은 숫자에서 만든다 — 방향이 나라마다 다르면 그대로 쓴다.
    half_bits = []
    for c in ("JPN", "IND"):
        mon = series(rows, GULF, {c}, {"2709"} | HS2711, "M", monthly=True)
        ann = series(rows, GULF, {c}, {"2709"} | HS2711, "M")
        if mon and ann.get(2025):
            h26, half25 = sum(mon.values()), ann[2025] / 2
            lo = min(mon, key=mon.get)
            half_bits.append(f"{KO[c]}은 2026 1~6월 {bn(h26)} 대 2025 연간÷2 {bn(half25)} ({pct(half25, h26)}), 월별 최저는 {lo[:4]}.{lo[4:]}")
    half_text = ("; ".join(half_bits) + ". 두 나라의 방향이 엇갈린다." if len(half_bits) == 2 and
                 ((sum(series(rows, GULF, {"JPN"}, {"2709"} | HS2711, "M", monthly=True).values()) > series(rows, GULF, {"JPN"}, {"2709"} | HS2711, "M").get(2025, 0) / 2)
                  != (sum(series(rows, GULF, {"IND"}, {"2709"} | HS2711, "M", monthly=True).values()) > series(rows, GULF, {"IND"}, {"2709"} | HS2711, "M").get(2025, 0) / 2))
                 else "; ".join(half_bits) + ".") if half_bits else "2026 월별 값이 있는 수입국이 없다."
    chart5b = month_chart(bars, refs, {"label": "사우디 신고 →동아시아4 (2026.4 까지)", "color": C_GRAY, "data": sau_mon} if sau_mon else None)
    tbl = ('<table class="vt"><tr><th>수입국</th><th>수입 신고 마지막 기간</th><th>2025 연간</th><th>2025 연간 ÷ 2</th><th>2026 1~6월</th><th>차이</th></tr>'
           + "".join(f'<tr><td>{esc(a)}</td><td>{esc(b)}</td><td class="num">{c}</td><td class="num">{d}</td><td class="num">{e}</td><td class="num">{f}</td></tr>'
                     for a, b, c, d, e, f in table_rows) + "</table>")
    verdict5 = "판정불가" if (have26 != EAST_ASIA or have25m != EAST_ASIA) else "성립"
    body.append(claim_block(
        "⑤", "2026 이란 분쟁 — 걸프→동아시아 흐름이 2025 상반기 대비 꺾였는가",
        "걸프 5개국(사우디·UAE·이라크·쿠웨이트·카타르)→동아시아 4개국(중국·일본·한국·인도) 원유(2709)·석유가스(2711) 수입이 2026 상반기에 2025 상반기보다 줄어든다.",
        chart5a + chart5b + tbl, verdict5,
        [f"2025 년은 월별이 아니라 연간 값만 있어 '2025 상반기'가 데이터에 없다(연간÷2 로 대신했다). 2026 월별 신고가 있는 수입국은 {', '.join(KO[c] for c in sorted(have26)) or '없음'} 뿐이고, "
         f"중국은 {latest_period(cov, 'CHN')}·한국은 {latest_period(cov, 'KOR')} 까지만 신고했다. 걸프 수출국 쪽은 원유·가스를 상대국별로 거의 신고하지 않는다(사우디 신고 →동아시아4 2709·2711 행 {len(sau_mon)}개). 기준: 네 수입국 모두 2025·2026 월별 값이 있어야 판정한다.",
         "그래프는 그래도 둔다 — 다만 위 연간 선의 2025·2026 하락은 중국(2024 까지)·한국(2025 까지) 신고가 빠진 몫이 크다. " + half_text + " 반쪽 수입국·반쪽 기간·금액 기준(유가가 오르면 물량이 줄어도 금액은 는다)이라 '분쟁 때문에 꺾였다'고도 '안 꺾였다'고도 판정하지 않는다."],
    ))

    # ---------------- 6. 종합
    verdicts = [("①", "분절화: EU←러시아 2709+2710 급감", verdict1),
                ("②", "재연결: 러시아 원유의 인도·중국(·튀르키예) 이동", verdict2),
                ("③", "2차 경로: 인도→EU 정제품 동반 급증", verdict3),
                ("④", "이란: 중국의 이란 직수입 소멸 + 말레이시아산 급증", verdict4),
                ("⑤", "2026 이란 분쟁: 걸프→동아시아 상반기 비교", verdict5)]
    ok = [f"{n} {t}" for n, t, v in verdicts if v == "성립"]
    no = [f"{n} {t}" for n, t, v in verdicts if v == "불성립"]
    na = [f"{n} {t}" for n, t, v in verdicts if v == "판정불가"]
    body.append(
        '<section class="claim" id="c6"><h2>6. 종합</h2>'
        '<table class="vt"><tr><th>명제</th><th>내용</th><th>판정</th></tr>'
        + "".join(f'<tr><td>{esc(n)}</td><td>{esc(t)}</td><td><span class="verdict {VERDICT_CLASS[v]}" style="margin:0">{v}</span></td></tr>' for n, t, v in verdicts)
        + "</table>"
        f'<p class="interp"><b>제목이 데이터로 뒷받침되는 부분:</b> {esc("; ".join(ok)) if ok else "없음"}.</p>'
        f'<p class="interp"><b>뒷받침되지 않는 부분:</b> {esc("; ".join(no)) if no else "없음"}.</p>'
        f'<p class="interp"><b>데이터 한계로 말할 수 없는 부분:</b> {esc("; ".join(na)) if na else "없음"}'
        " — 그리고 ②~④ 전부에 걸쳐 '금액'이지 '물량'이 아니며, HS 코드는 원산지를 추적하지 못한다는 한계가 깔려 있다.</p></section>"
    )

    # ---------------- 7. 부록 — 기준선 숫자
    per_year = defaultdict(int)
    for rrow in rows:
        per_year[year_of(rrow[2])] += 1
    periods = sorted({rrow[2] for rrow in rows})
    n_rep25 = len({rp for (rp, f), ps in cov.items() if f == "M" and "2025" in ps})
    n_rep26 = len({rp for (rp, f), ps in cov.items() if f == "M" and any(len(p) == 6 and p.startswith("2026") for p in ps)})
    rs = raw_stats()
    raw_tbl = ('<table class="vt"><tr><th>원자료</th><th>mtime(수집일 근사)</th><th>크기</th></tr>'
               + "".join(f'<tr><td><code>{esc(p)}</code></td><td>{esc(m)}</td><td class="num">{s / 1e6:.1f} MB</td></tr>' for p, m, s in rs["files"]) + "</table>")
    if rs.get("dropped") is None:
        drop_html = ('<p class="interp">매핑 실패 행 수·상위 코드: <b>계산 불가</b> — 위 원자료 CSV 가 이 경로에 없다. '
                     '(build_oil_data.py 를 마지막으로 돌렸을 때의 콘솔 출력이 유일한 기록이며 이 페이지에는 남아 있지 않다.)</p>')
    else:
        drop_html = (f'<p class="interp">원자료 {rs["raw_rows"]:,}행 중 ISO3 매핑 실패로 제외 {rs["dropped"]:,}행. 실패 코드 상위 10:</p>'
                     '<table class="vt"><tr><th>자리</th><th>Comtrade 코드</th><th>행 수</th></tr>'
                     + "".join(f'<tr><td>{esc(k[0])}</td><td>{esc(k[1])}</td><td class="num">{n:,}</td></tr>' for k, n in rs["top_codes"]) + "</table>")
    key_cov = ('<table class="vt"><tr><th>국가</th><th>수입(M) 신고 마지막 기간</th><th>수출(X) 신고 마지막 기간</th></tr>'
               + "".join(f'<tr><td>{esc(KO.get(c, c))} ({c})</td><td>{esc(latest_period(cov, c, "M"))}</td><td>{esc(latest_period(cov, c, "X"))}</td></tr>'
                         for c in ("RUS", "IRN", "VEN", "CHN", "KOR", "JPN", "IND", "TUR", "MYS", "SAU", "ARE", "IRQ", "KWT", "QAT")) + "</table>")
    try:
        cd = club_diff()
        diff_rows = "".join(f'<tr><td>{esc(n)}</td><td>{esc(i)}</td><td>{esc(a)}</td><td>{esc(b)}</td></tr>' for n, i, a, b in cd["diffs"])
        club_html = (f'<p class="interp"><code>bloc_site.build_blocs</code>(국가명 키) {cd["n_name"]}개국 vs <code>build_oil_data.build_blocs_by_iso3</code>(ISO3 키) {cd["n_iso"]}개국. '
                     f'분류가 다른 국가 <b>{len(cd["diffs"])}</b>개'
                     + (f', ISO3 쪽에만 있는 국가 {len(cd["only_iso"])}개({", ".join(cd["only_iso"])})' if cd["only_iso"] else "")
                     + ".</p>"
                     + ('<table class="vt"><tr><th>국가명(BSV)</th><th>ISO3</th><th>build_blocs</th><th>build_blocs_by_iso3</th></tr>' + diff_rows + "</table>" if diff_rows else "")
                     + (('<p class="interp">같은 ISO3 에 BSV 국가명이 둘 이상 걸린 경우: '
                         + "; ".join(f"{i} ← {', '.join(ns)}" for i, ns in sorted(cd["dup_iso"].items()))
                         + ". 국가명 키 구현은 이를 별개 국가로 세어 분위 경계(n//4)가 한 칸 밀린다 — 위 불일치의 원인으로 보이지만 여기서는 고치지 않고 노출만 한다.</p>") if cd["dup_iso"] else ""))
    except Exception as e:  # BSV 가 없으면 비교 자체가 안 된다
        club_html = f'<p class="interp">클럽 분류 비교 불가: {esc(repr(e))}</p>'

    body.append(
        '<section class="claim appendix" id="c7"><h2>7. 부록 — 기준선 숫자</h2>'
        f'<p class="interp">oil_trade.json: 행 <b>{len(rows):,}</b>개, 국가 <b>{len(countries)}</b>개, 기간 {esc(periods[0])}~{esc(periods[-1])} ({len(periods)}개 period, 2026 은 월별). '
        f'payload <code>generated</code>={esc(payload.get("generated", "?"))}, 파일 mtime {payload["_mtime"].strftime("%Y-%m-%d %H:%M")}. '
        f'2025 를 수입 신고한 국가 {n_rep25}개, 2026 월별을 신고한 국가 {n_rep26}개.</p>'
        '<table class="vt"><tr>' + "".join(f"<th>{y}</th>" for y in YEARS) + "</tr><tr>"
        + "".join(f'<td class="num">{per_year.get(y, 0):,}</td>' for y in YEARS) + "</tr></table>"
        '<p class="interp">연도별 행 수. 2025 가 2024 보다 적은 것은 늦게 신고하는 국가 몫이 아직 비어 있다는 뜻이고, 2026 은 1~6월만이다.</p>'
        "<h3>원자료·매핑</h3>" + raw_tbl + drop_html +
        "<h3>주요국 신고 범위</h3>" + key_cov +
        "<h3>클럽 분류 두 구현 비교</h3>" + club_html +
        "</section>"
    )

    html = (HEAD.replace("__TITLE__", esc(TITLE)).replace("__STYLE__", STYLE_FROM_BLOC + EXTRA_STYLE)
            + "".join(body) + FOOT)
    (out / "oil_verify.html").write_text(html, encoding="utf-8")
    print(f"[oil_verify_site] 판정 ①{verdict1} ②{verdict2} ③{verdict3} ④{verdict4} ⑤{verdict5} -> {out / 'oil_verify.html'}")
    return True


if __name__ == "__main__":
    ok = build(HERE / "site")
    print("built" if ok else "missing oil_trade.json — skipped")
