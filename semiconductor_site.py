"""반도체 공급망 지도용 정적 데이터와 화면을 만든다."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "cache" / "master.parquet"

# 화면에 쓰는 자료의 시작 연도. 수집(auto_update.py의 START_DATE)은 2008-01-01
# 부터지만, 화면은 2010-01-01부터로 유지한다. 2026-08-18에 수집 범위를 넓히면서
# 사용자가 화면 기준은 그대로 두기로 정했다. date_announced는 'YYYY-MM-DD'
# 문자열이라 문자열 비교로 자른다.
SITE_START_DATE = "2010-01-01"
OECD = HERE / "reference" / "oecd_semiconductor_hs.json"
WORLD = HERE / "reference" / "ne_110m_admin_0_countries.geojson"
HSMAP = HERE / "reference" / "hs2017_to_hs2022.json"

# =============================================================================
# #BASELINE
# HS2022 명목 소호 5,612개 중 OECD Annex D 반도체가 59개.
# 반도체를 겨냥하지 않고 관세표를 통째로 건드려도 자동으로 이만큼 걸린다.
# 화면의 10% 기준선은 이 값의 약 10배라는 뜻이며, 화면에 반드시 표기한다.
# =============================================================================
HS_NOMENCLATURE_SIZE = 5612

EXPORT_TYPES = {
    "Export ban", "Export licensing requirement",
    "Export-related non-tariff measure, nes", "Export quota", "Export tax",
    "Export tariff quota", "Export price benchmark", "Foreign customer limit",
    "Local supply requirement for exports",
}

# =============================================================================
# #DATA_CONTRACT #HS_VERSIONING
# OECD Annex D는 HS2017, GTA affected_products는 HS2022다. UNSD 공식 상관표
# (reference/hs2017_to_hs2022.json)로 대조 코드 집합을 만든다.
#
# 상관표 넣기 전에는 문자 그대로 같은 코드만 봤고, 그래서 실제로 놓치고 있었다:
#   811292 갈륨·게르마늄 → HS2022에서 811231·811241·811292 로 분할
#   811299              → 811239·811249·811299
#   842139              → 842132·842139
#   854140              → 854141·854142·854143·854149 (원 코드 소멸)
#   854150              → 대응 없음. 유일하게 대조 불가
# GTA 자료에 위 코드가 전부 실재하므로, 안 넣으면 조용히 과소집계된다.
# =============================================================================
STATUS_LABEL = {
    "exact": "HS2022에서 코드 그대로",
    "split": "HS2022에서 분할 — 대응 코드를 함께 대조",
    "split_renumbered": "HS2022에서 코드 소멸·분할 — 대응 코드로 대조",
    "unclear": "HS2022 대응 없음 — 대조하지 않음",
}


def _split(value, sep: str) -> list[str]:
    if value is None:
        return []
    try:
        if math.isnan(value):
            return []
    except (TypeError, ValueError):
        pass
    return [part.strip() for part in str(value).split(sep) if part.strip()]


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def build_data() -> dict:
    import pandas as pd

    ref = json.loads(OECD.read_text(encoding="utf-8"))
    codes = {str(row["hs2017"]).zfill(6): dict(row) for row in ref["codes"]}

    hsmap = json.loads(HSMAP.read_text(encoding="utf-8"))["codes"] if HSMAP.is_file() else {}
    # match_set: OECD 코드 하나가 대조해야 할 HS2022 코드 집합
    match_set: dict[str, set[str]] = {}
    for code, row in codes.items():
        entry = hsmap.get(code)
        if entry is None:
            row["version_status"], row["version_targets"] = "exact", [code]
        else:
            row["version_status"] = entry["status"]
            row["version_targets"] = entry["hs2022"] or []
        row["version_note"] = STATUS_LABEL.get(row["version_status"], "")
        if row["version_targets"] and row["version_status"] != "unclear":
            row["version_note"] += " (" + ", ".join(row["version_targets"]) + ")"
        match_set[code] = set(row["version_targets"])
    lookup: dict[str, list[str]] = {}
    for code, targets in match_set.items():
        for target in targets:
            lookup.setdefault(target, []).append(code)

    df = pd.read_parquet(MASTER)
    df = df[df["date_announced"].fillna("") >= SITE_START_DATE]
    df = df[df["intervention_type"].isin(EXPORT_TYPES)].copy()
    measures = []
    affected_names: set[str] = set()
    implementing_names: set[str] = set()
    # #FILTER_SEMANTICS: no is_in_force filter. The screen is an event history,
    # not a reconstructed current legal state. Only the 10% semiconductor-share
    # threshold and the nine UN MAST P export-control types are applied.
    for row in df.to_dict("records"):
        # #HS6_NORMALISE: 앞자리 0이 떨어진 값이 섞이면 분모에만 세어져 비중이
        # 조용히 낮아진다. 양쪽을 똑같이 6자리로 맞춘다.
        products = sorted({code.zfill(6) for code in _split(row.get("affected_products"), ",")})
        # 대조는 HS2022 쪽에서 하고, 화면에는 OECD(HS2017) 코드로 되돌려 담는다.
        hit2022 = sorted(set(products) & set(lookup))
        matched = sorted({oecd for x in hit2022 for oecd in lookup[x]})
        if not products or not matched or len(hit2022) / len(products) < 0.10:
            continue
        affected = _split(row.get("affected_jurisdictions"), ";")
        implementing = _split(row.get("implementing_jurisdictions"), ";")
        implementing_groups = _split(row.get("implementing_jurisdiction_groups"), ";")
        if not implementing:
            continue
        affected_names.update(affected)
        implementing_names.update(implementing)
        rid = int(row["intervention_id"])
        measures.append({
            "id": rid,
            "date": _text(row.get("date_announced"))[:10],
            "implemented": _text(row.get("date_implemented"))[:10],
            "removed": _text(row.get("date_removed"))[:10],
            "evaluation": _text(row.get("gta_evaluation")),
            "type": _text(row.get("intervention_type")),
            "title": _text(row.get("state_act_title")),
            "description": _text(row.get("intervention_description")),
            "url": _text(row.get("intervention_url")),
            "implementing": implementing,
            "implementing_groups": implementing_groups,
            "affected": affected,
            "affected_missing": not affected,
            "hs": matched,
            "hs2022": hit2022,
            "hs_total": len(products),
            "hs_semi": len(hit2022),
            "share": round(100 * len(hit2022) / len(products), 1),
        })

    import datetime as _dt
    asof = _dt.datetime.fromtimestamp(MASTER.stat().st_mtime).strftime("%Y-%m-%d")
    return {
        "built_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gta_asof": asof,
        "threshold": 10,
        "baseline": round(100 * len(codes) / HS_NOMENCLATURE_SIZE, 2),
        "baseline_note": f"{len(codes)}/{HS_NOMENCLATURE_SIZE:,} — HS2022 명목 전체 대비 OECD 반도체 몫",
        "groups": ref["groups"],
        "codes": list(codes.values()),
        "measures": measures,
        "affected": sorted(affected_names),
        "implementing": sorted(implementing_names),
        "default_affected": "Republic of Korea",
    }


def render_html(stamp: str) -> str:
    # #CACHE_BUSTING
    # 브라우저가 semi.json 을 캐시해 옛 화면을 보여주는 사고가 있었다(2026-08-14).
    # 빌드할 때마다 바뀌는 스탬프를 붙여 강제로 새로 받게 한다.
    return HTML.replace("__STAMP__", stamp)


def build(out: Path) -> bool:
    required = [MASTER, OECD, WORLD]
    if not all(path.is_file() for path in required):
        return False
    data = build_data()
    stamp = str(data["built_at"]).replace("-", "").replace(":", "").replace(" ", "")
    (out / "semi.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    shutil.copy2(WORLD, out / "world.geojson")
    (out / "semi.html").write_text(render_html(stamp), encoding="utf-8")
    return True


HTML = r'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>반도체 공급망 지도 · SKL</title>
<link rel="stylesheet" href="style.css"><style>
:root{--bg:#fff1e5;--card:#f7ded2;--fg:#000;--muted:#000;--line:#302824;--accent:#000}html,body{background:#fff1e5;color:#000;font-weight:700}body *{font-weight:700}a{color:#000}
.semi-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px}.semi-head h1{margin:0;font-size:1.45rem}.semi-head p{margin:4px 0 0;color:var(--muted);font-size:.86rem}.filters{display:grid;grid-template-columns:1fr 1fr auto auto;gap:10px;padding:14px;background:var(--card);border:2px solid var(--line);border-radius:12px;margin-bottom:14px}.filters label{font-size:.78rem;color:var(--muted)}input,button{width:100%;margin-top:4px;padding:8px 10px;border:2px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}button{cursor:pointer}.help{margin:0 0 14px;padding:10px 14px;background:var(--card);border:2px solid var(--line);border-radius:10px;font-size:.8rem;color:var(--muted)}.help summary{cursor:pointer;color:var(--fg)}.help ul{margin:8px 0;padding-left:18px}.help li{margin:2px 0}.dashboard{display:grid;grid-template-columns:minmax(360px,1fr) minmax(480px,1.45fr);gap:14px}.panel{border:2px solid var(--line);border-radius:12px;background:var(--bg);overflow:hidden}.panel-head{padding:12px 14px;border-bottom:2px solid var(--line);font-size:.86rem;color:var(--muted)}.chain{padding:12px;max-height:650px;overflow:auto}.allnote{margin:12px 0 0;font-size:.76rem;color:var(--muted)}.group-picker{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin-bottom:14px}.group-choice{margin:0;padding:9px;text-align:left;min-height:58px}.group-choice strong{display:block;font-size:.78rem}.group-choice small{display:block;margin-top:4px;font-size:.68rem;color:var(--muted)}.gbar{display:flex;height:7px;margin-top:5px;border:1.5px solid var(--line);border-radius:3px;overflow:hidden}.gbar i{display:block;height:100%}.group-choice.active{background:#302824;color:#fff}.group-choice.active small{color:#fff}.group-title{display:flex;justify-content:space-between;align-items:baseline;gap:8px;padding-top:12px;border-top:2px solid var(--line);font-size:.88rem;margin:0 0 8px}.chips{display:grid;grid-template-columns:1fr;gap:6px}.hs{margin:0;padding:7px 9px;text-align:left;display:grid;grid-template-columns:62px 1fr;gap:8px;align-items:start}.hs-code{font-family:Consolas,monospace}.hs-label{font-size:.73rem;line-height:1.3}.hs.red{background:#c62828;color:#fff;border-color:#302824}.hs.green{background:#6fba8c;color:#000;border-color:#302824}.hs.amber{background:#dc8b00;color:#fff;border-color:#302824}.hs.mixed{background:linear-gradient(135deg,#c62828 0 55%,#6fba8c 55%);color:#fff}.hs.history{background:#6f7780;color:#fff}.hs.unmatched{border-style:dashed;opacity:.65}.hs.split{border-style:double;border-width:4px}.hs.selected{outline:3px solid var(--fg);outline-offset:1px}.map-wrap{position:relative;padding:8px;min-height:410px;overflow:hidden;background:#111}.map-wrap svg{width:100%;height:auto;display:block;touch-action:none;cursor:grab;background:#111}.map-wrap svg.dragging{cursor:grabbing}.map-tools{position:absolute;right:12px;top:12px;display:flex;gap:4px;z-index:2}.map-tools button{width:34px;height:34px;margin:0;padding:0;background:#fff;font-size:1rem}.country{fill:#e3e6e8;stroke:#fff;stroke-width:.45;cursor:pointer}.country:hover{stroke:#111;stroke-width:1.2}.country.red{fill:#c62828}.country.green{fill:#6fba8c}.country.amber{fill:#dc8b00}.country.expired{fill:#6f7780}.country.joint{stroke:#6b38b6;stroke-width:2.2;stroke-dasharray:4 2}.country.selected{stroke:#111;stroke-width:2}.legend{display:flex;flex-wrap:wrap;gap:12px;padding:8px 14px 14px;font-size:.76rem;color:var(--muted)}.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px}.tooltip{position:absolute;display:none;pointer-events:none;background:#111;color:#fff;padding:7px 9px;border-radius:7px;font-size:.76rem;max-width:270px;z-index:3}.unmapped{padding:8px 14px 14px;font-size:.76rem;color:var(--muted)}.details{margin-top:14px}.details h2{font-size:1.05rem;margin:0;padding:14px;border-bottom:2px solid var(--line)}.measure{padding:14px;border-bottom:2px solid var(--line);color:#000}.measure.active-red{background:#e76f61}.measure.active-green{background:#6fba8c}.measure.active-amber{background:#e8aa3d}.measure.active-red *,.measure.active-green *,.measure.active-amber *{color:#000}.measure:last-child{border-bottom:0}.measure .meta{font-size:.78rem;color:#000;margin-bottom:4px}.measure h3{font-size:.94rem;margin:0 0 6px;color:#000}.measure p{font-size:.83rem;margin:6px 0;white-space:pre-wrap}.tag{display:inline-block;padding:1px 7px;border-radius:999px;border:2px solid #302824;margin-right:4px;font-size:.72rem}.tag.dead{background:#302824;color:#fff}.tag.unrev{background:#fff;border-style:dashed}.measure.dead{opacity:.62}.measure.dead h3{text-decoration:line-through}.baseline{margin:0 0 12px;padding:9px 14px;border:2px dashed var(--line);border-radius:10px;font-size:.8rem}.empty{padding:30px;text-align:center;color:var(--muted)}@media(max-width:900px){.dashboard{grid-template-columns:1fr}.filters{grid-template-columns:1fr}.chain{max-height:440px}.map-wrap{min-height:300px}}@media(max-width:430px){.group-picker{grid-template-columns:1fr}}
.filters{grid-template-columns:1fr 1fr auto}.year-control{padding:12px 14px 10px;border-top:2px solid var(--line);background:var(--card)}.year-control label{display:flex;justify-content:space-between;align-items:baseline;gap:12px;font-size:.8rem}.year-control output{font-size:.86rem}.year-control input[type=range]{display:block;width:100%;box-sizing:border-box;margin:8px 0 2px;padding:0;border:0;background:transparent;accent-color:#302824;cursor:grab}.year-control input[type=range]:active{cursor:grabbing}.year-ends{display:flex;justify-content:space-between;font-size:.68rem;color:var(--muted)}
.map-wrap{min-height:0}.date-control-head{display:flex;align-items:center;justify-content:space-between;gap:12px}.date-control-head label{font-size:.8rem}.date-control-head input[type=date]{width:auto;min-width:150px;margin:0;padding:5px 8px;background:var(--bg)}.year-ends output{font-size:.72rem}
</style></head><body><div class="wrap">
<a class="back" href="index.html">← 변경 내역</a><header class="semi-head"><div><h1>반도체 공급망 지도</h1><p>OECD 반도체 값사슬 HS 59개 × GTA 수출통제 9종</p></div><div id="summary"></div></header>
<p class="baseline" id="baseline"></p><p class="baseline" id="allwarn" style="display:none"></p>
<details class="help"><summary>색 기준</summary><ul><li>HS·국가 색 = 고른 조건(과 기준일자까지)에 쌓인 조치 중 <b>레드+앰버 건수 vs 그린 건수 다수결</b></li>
<li>동률이면 <b>가장 최근 조치</b>의 색을 따름. 앰버는 별도 색 없이 레드로 합쳐 집계</li>
<li>연회색 = 해당 조치 없음</li></ul>
<ul><li>GTA는 <b>조치 발생 기록</b>. 현재 유효 여부는 보증하지 않음 — 만료·철회 여부는 색이 아니라 타임라인에 표기</li>
<li>다수결은 <b>지금까지의 이력 전체</b>를 본다. 만료된 조치도 집계에 포함</li>
<li>색은 GTA 구조화 필드와 화면 규칙으로만 결정하며, 별도의 사람 판정을 포함하지 않음</li>
<li>피영향국 미기재 조치 = 어느 국가를 골라도 항상 포함 (단, 시행국과 같은 국가로 좁히면 자기표시를 막기 위해 제외)</li></ul></details>
<section class="filters"><label>피영향국 검색<input id="affected" list="affected-list" placeholder="(전체)" autocomplete="off"><datalist id="affected-list"></datalist></label><label>시행국 검색<input id="implementing" list="implementing-list" placeholder="(전체)" autocomplete="off" value="(전체)"><datalist id="implementing-list"></datalist></label><button id="reset">HS 선택 해제</button></section>
<main class="dashboard"><section class="panel"><div class="panel-head">OECD 7개 상품군 · 선택 시 지도 범위 축소</div><div id="chain" class="chain"></div></section><section class="panel"><div class="panel-head" id="map-head">국가별 조치 다수결</div><div class="map-wrap"><div class="map-tools"><button id="zoom-in" title="확대">＋</button><button id="zoom-out" title="축소">−</button><button id="zoom-reset" title="전체 보기">⌂</button></div><svg id="map" viewBox="0 0 1000 510" aria-label="세계지도"></svg><div id="tip" class="tooltip"></div></div><div class="year-control"><div class="date-control-head"><label for="cutoff-date">기준일자</label><input id="cutoff-date" type="date" aria-label="기준일자 직접 선택"></div><input id="cutoff-slider" type="range" min="0" max="0" value="0" step="1" aria-label="기준일자 드래그"><div class="year-ends"><span id="date-min"></span><output id="date-label"></output><span id="date-max"></span></div></div><div class="legend"><span><i class="dot" style="background:#c62828"></i>레드(앰버 포함) 다수</span><span><i class="dot" style="background:#6fba8c"></i>그린 다수</span><span><i class="dot" style="background:#e3e6e8"></i>조치 이력 없음</span><span style="color:#6b38b6">┄ EU 공동조치 있음 (색은 자국 조치 우선)</span><span>▤ 겹테두리 · HS2022에서 분할된 품목</span><span>┈ 점선 · HS2022 대응 코드 없어 대조 불가</span></div><div id="unmapped" class="unmapped"></div></section></main>
<section class="panel details"><h2 id="detail-title">조치 타임라인</h2><div id="details"></div></section>
<footer class="site">색 = 현재 규제 상태가 아니라 고른 조건(과 기준일자)까지 쌓인 조치의 다수결(레드+앰버 vs 그린, 동률은 최근 색) · 지도 = Natural Earth(공개 도메인)</footer></div>
<script>
// =============================================================================
// #UI_STATE #FILTER_SEMANTICS #LATEST_EVENT
// Latest = date_announced descending, intervention_id descending on ties.
// Search fields accept only values generated from the local GTA snapshot.
// =============================================================================
const $=s=>document.querySelector(s), today=new Date().toISOString().slice(0,10), ALL='(전체)';let D,G,state={affected:'Republic of Korea',implementing:'',hs:'',group:'',cutoff:''} // group='' = 전체 상품군, cutoff='' = 전체 기간;
const aliases={'United States of America':'United States of America','Republic of Korea':'South Korea','China':"People\'s Republic of China",'Chinese Taipei':'Taiwan','Russia':'Russia','Czechia':'Czech Republic','Lao':'Laos','Vietnam':'Vietnam','Turkiye':'Turkey','Brunei Darussalam':'Brunei','Republic of Moldova':'Moldova'};

const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function latest(rows){return rows.slice().sort((a,b)=>(b.date||'').localeCompare(a.date||'')||b.id-a.id)[0]}
function expired(m){return m.removed&&m.removed<=today}
// #COLOUR_RULE_20260814
// 색 = '가장 최근 조치' 1건이 아니라 '지금까지 쌓인 조치의 다수결'이다.
// 이전 방식(최신 1건 승자)은 UAE 우대 조치 하나가 미국 칩 코드 5개를 통째로
// 뒤집는 등 단발성 사건에 색 전체가 흔들리는 문제가 있었다(설계문서 3-D).
// 규칙: 레드+앰버 건수 vs 그린 건수 중 많은 쪽. 동률이면 가장 최근 조치의 색.
// 앰버는 별도 색을 쓰지 않고 레드 쪽으로 합쳐 집계한다.
// 만료·철회 여부는 다수결에서 빼지 않는다 — '지금까지의 track record'를 보는
// 것이므로 이미 끝난 조치도 그대로 센다. 만료 사실은 색이 아니라 타임라인에
// 개별 표기한다(expired()).
function bucket(ev){return ev==='Green'?'green':'red'}
function tally(rows){let red=0,green=0;for(const m of rows){if(bucket(m.evaluation)==='green')green++;else red++}return{red,green}}
// #FILTER_LAYERS #BUGFIX_20260814
// countryRows drives every HS tile colour and MUST NOT depend on state.hs.
// relevant applies the optional HS selection only to the map and timeline.
// Otherwise clicking one HS recolours unrelated HS tiles; clicking again appears
// to change them back. This was the common cause of the 854233/Argon screenshots.
// #FILTER_LAYERS: 피영향국이 비어 있는 건은 '아무에게도 영향 없음'이 아니라
// 미기재다. 그래서 예전에는 어느 국가를 골라도 미기재 건을 포함했다.
// #CHANGED_20260819: 그 규칙을 없앴다. 피영향국을 특정 국가로 고르면 미기재
// 건은 빼고, 그 국가가 실제로 적혀 있는 건만 본다.
// 이유: '피영향국=China'로 걸러도 중국 자신의 미기재 조치가 딸려 들어와
// 지도에서 중국이 초록으로 칠해졌다(실측: 2025-11-07 "China: Temporary
// suspension of additional export controls for rare earth-related", Green,
// 피영향국 미기재. 중국 시행 조치가 이것 하나뿐이라 1대 0으로 그린 승).
// 특정국을 골랐다는 것은 '그 나라가 영향받은 건만 보겠다'는 뜻이므로, 근거
// 없이 딸려오는 미기재 건은 오히려 색을 왜곡한다. 피영향국을 고르지 않으면
// (전체) 종전대로 미기재 건도 전부 포함한다.
// 이 변경으로 #BUGFIX_20260814_SELFTARGET(같은 국가 필터일 때만 미기재를
// 빼던 예외)은 필요 없어져 함께 제거했다.
// #DATE_CUTOFF: 기준일자를 고르면 그 날짜까지 발표된(date_announced)
// 조치만 다수결에 넣는다. state.cutoff=''는 전 기간을 본다.
function countryRows(){
 return D.measures.filter(m=>(!state.cutoff||(m.date&&m.date<=state.cutoff))&&(!state.affected||m.affected.includes(state.affected))&&(!state.implementing||m.implementing.includes(state.implementing)))}
// 지도·타임라인은 선택한 상품군(HS를 하나 고르면 그 HS)까지 좁힌다.
// 좌측 타일 색은 countryRows()만 쓰므로 여기 좁혀도 흔들리지 않는다.
function groupCodes(id){return new Set(D.codes.filter(c=>c.group===id).map(c=>c.hs2017))}
function relevant(){const rows=countryRows();if(state.hs)return rows.filter(m=>m.hs.includes(state.hs));
 if(!state.group)return rows;   // 전체 상품군
 const gc=groupCodes(state.group);return rows.filter(m=>m.hs.some(h=>gc.has(h)))}
// #EU_JOINT #COUNTRY_OWN_ACT_WINS
// EU 공동조치의 implementing 에는 회원국 27개가 그대로 들어 있다. 그대로 두면
// EU 목록 연례 개정 하나가 회원국의 자국 조치를 덮어버린다(네덜란드 ASML 통제가
// EU Amber 개정에 가려지는 사고가 실제로 났다).
// 규칙: 자국 단독 조치가 하나라도 있으면 그 조치들만으로 다수결을 정한다.
// 공동조치밖에 없는 국가만 공동조치로 다수결하고, 어느 쪽이든 공동조치가 섞여
// 있으면 보라 점선으로 표시한다.
function perCountry(rows){let out={};for(const m of rows){for(const c of m.implementing)(out[c]??=[]).push(m)}
 return Object.fromEntries(Object.entries(out).map(([c,x])=>{const own=x.filter(m=>!m.implementing_groups.length);
  const pool=own.length?own:x,{red,green}=tally(pool),rec=latest(pool);
  const colour=red===green?bucket(rec.evaluation):(red>green?'red':'green');
  return[c,{...rec,colour,red_count:red,green_count:green,has_joint:x.some(m=>m.implementing_groups.length),from_joint:!own.length}]}))}
// HS 타일은 여러 국가의 조치가 한꺼번에 걸리므로 국가별로 나누지 않고
// rows 전체를 그대로 다수결한다(레드+앰버 vs 그린, 동률은 최근 색).
function status(rows){if(!rows.length)return'';const{red,green}=tally(rows);if(red===green)return bucket(latest(rows).evaluation);return red>green?'red':'green'}
function project(p){return[(p[0]+180)*1000/360,(90-p[1])*510/180]}function ringPath(r){return r.map((p,i)=>`${i?'L':'M'}${project(p)[0].toFixed(1)},${project(p)[1].toFixed(1)}`).join('')+'Z'}
function geomPath(g){const ps=g.type==='Polygon'?[g.coordinates]:g.coordinates;return ps.map(poly=>poly.map(ringPath).join('')).join('')}
function countryName(f){return f.properties.NAME_EN||f.properties.ADMIN||f.properties.NAME||''}
function fillSelects(){$('#affected').value=state.affected||ALL;
 const opts=xs=>[ALL,...xs].map(x=>`<option value="${esc(x)}">`).join('');
 $('#affected-list').innerHTML=opts(D.affected);$('#implementing-list').innerHTML=opts(D.implementing)}
function drawBaseMap(){$('#map').innerHTML=G.features.map((f,i)=>`<path class="country" data-name="${esc(countryName(f))}" d="${geomPath(f.geometry)}"><title>${esc(countryName(f))}</title></path>`).join('')}
function render(){const rows=relevant(),colourRows=countryRows(),pc=perCountry(rows);$('#summary').innerHTML=`${state.cutoff?`<span class="tag">${esc(state.cutoff)} 기준</span> `:''}${state.affected?'':'<span class="tag dead">피영향국 전체</span> '}<span class="tag">조치 ${rows.length}건</span> <span class="tag">HS ${state.hs?1:new Set(rows.flatMap(m=>m.hs)).size}개</span>`;
 let by={};for(const c of D.codes)(by[c.group]??=[]).push(c);if(state.group&&!D.groups.some(g=>g.id===state.group))state.group='';const activeGroup=D.groups.find(g=>g.id===state.group);
 // #GROUP_COLOUR: 상품군 버튼도 소속 HS의 색 분포를 그대로 띠로 보여준다.
 const SEG={red:'#c62828',green:'#6fba8c','':'#e3e6e8'};
 const SEGNAME={red:'레드(앰버 포함) 다수',green:'그린 다수',['']:'조치 없음'};
 const groupButtons=D.groups.map(g=>{const codes=by[g.id]||[];const cnt={};for(const c of codes){const s=status(colourRows.filter(m=>m.hs.includes(c.hs2017)));cnt[s]=(cnt[s]||0)+1}
  const lit=codes.length-(cnt['']||0);
  const bar=['red','green',''].filter(k=>cnt[k]).map(k=>`<i style="width:${100*cnt[k]/codes.length}%;background:${SEG[k]}" title="${SEGNAME[k]} ${cnt[k]}개"></i>`).join('');
  return`<button class="group-choice ${state.group===g.id?'active':''}" data-group="${g.id}"><strong>${esc(g.name_ko)}</strong><small>점등 ${lit} / 전체 ${codes.length}</small><span class="gbar">${bar}</span></button>`}).join('');
 const tile=c=>{const x=colourRows.filter(m=>m.hs.includes(c.hs2017)),s=status(x);return`<button class="hs ${s} ${c.version_status==='unclear'?'unmatched':(c.version_status==='exact'?'':'split')} ${state.hs===c.hs2017?'selected':''}" data-hs="${c.hs2017}" title="${esc(c.version_note)}"><span class="hs-code">${c.hs2017}</span><span class="hs-label">${esc(c.label)}${c.version_status==='unclear'?'<br>⚠ HS2022 대응 없음 — 대조 불가':(c.version_status!=='exact'?`<br>↔ HS2022 ${c.version_targets.join('·')}`:'')}</span></button>`};
 $('#map-head').innerHTML=`<b>${esc(state.hs||(activeGroup?activeGroup.name_ko:'전체 상품군'))}</b> 기준 · 국가별 조치 다수결${state.cutoff?' · '+esc(state.cutoff)+'까지':''} · 국가 클릭 시 해당 시행국만`;
 const section=g=>`<h3 class="group-title"><span>${esc(g.name_ko)}</span><small>${(by[g.id]||[]).length}개 HS</small></h3><div class="chips">${(by[g.id]||[]).map(tile).join('')}</div>`;
 const body=activeGroup?section(activeGroup):D.groups.map(section).join('');
 $('#chain').innerHTML=`<div class="group-picker">${groupButtons}</div>${activeGroup?'':'<p class="allnote">상품군 클릭 = 해당 군만 · 다시 클릭 = 전체</p>'}${body}`;
 const mapped=new Set;document.querySelectorAll('.country').forEach(el=>{el.setAttribute('class','country');const natural=el.dataset.name;const gta=Object.keys(pc).find(k=>(aliases[k]||k)===natural);if(!gta)return;const m=pc[gta];mapped.add(gta);el.classList.add(m.colour);if(m.has_joint)el.classList.add('joint');if(state.implementing===gta)el.classList.add('selected');el.onmousemove=e=>{const t=$('#tip');t.style.display='block';t.style.left=(e.offsetX+18)+'px';t.style.top=(e.offsetY+18)+'px';t.innerHTML=`<b>${esc(gta)}</b>${m.from_joint?' <i>(EU 공동조치로 채색)</i>':(m.has_joint?' <i>(EU 공동조치도 있음)</i>':'')}<br>레드+앰버 ${m.red_count}건 · 그린 ${m.green_count}건 → <b>${m.colour==='red'?'레드':'그린'}</b>${m.red_count===m.green_count?' (동률, 최근 색)':''}<br>최근 조치 ${esc(m.date)} · ${esc(m.evaluation)}${expired(m)?' · 만료/철회':''}<br>${esc(m.title)}<br>관련 HS ${m.hs.length}개 · 비중 ${m.share}%${m.removed?`<br>${esc(m.removed)} 만료/철회일`:''}`};el.onmouseleave=()=>$('#tip').style.display='none';el.onclick=()=>{$('#implementing').value=gta;state.implementing=gta;render()}});
 const miss=Object.keys(pc).filter(x=>!mapped.has(x));$('#unmapped').innerHTML=miss.length?`지도 미매핑 시행 관할: ${miss.map(x=>`<button class="tag missing" data-country="${esc(x)}">${esc(x)}</button>`).join('')}`:'';
 $('#allwarn').style.display=state.affected?'none':'block';
 if(!state.affected)$('#allwarn').innerHTML='<b>피영향국 전체</b> 기준 — 특정국을 겨냥하지 않은 조치까지 포함. 지도 색이 그 국가의 반도체 정책을 뜻하지 않을 수 있음 (예: 미국의 아랍에미리트 수출 우대 → 미국 칩 코드가 완화로 표시)';
 renderDetails(rows);document.querySelectorAll('.group-choice').forEach(b=>b.onclick=()=>{state.group=(state.group===b.dataset.group)?'':b.dataset.group;state.hs='';render()});document.querySelectorAll('.hs').forEach(b=>b.onclick=()=>{state.hs=state.hs===b.dataset.hs?'':b.dataset.hs;render()});document.querySelectorAll('.missing').forEach(b=>b.onclick=()=>{$('#implementing').value=b.dataset.country;state.implementing=b.dataset.country;render()})}
// #TIMELINE_ACTIVE_TITLE
// 국가별 '가장 최근 조치' 카드에만 색 있는 제목을 준다(다수결 색이 아니라
// 그 카드 자신의 evaluation). 다수결로 정해진 지도 색과 다를 수 있음 — 그게
// 정상이다. 이건 '최근에 무슨 일이 있었는지'를 알려주는 표시일 뿐이다.
function renderDetails(rows){const ordered=rows.slice().sort((a,b)=>(b.date||'').localeCompare(a.date||'')||b.id-a.id),active=new Set(Object.values(perCountry(rows)).map(m=>m.id));$('#detail-title').textContent=`${state.hs||(D.groups.find(g=>g.id===state.group)||{}).name_ko||'전체 상품군'} · ${state.affected||'전체 피영향국'}${state.implementing?' ← '+state.implementing:''} 조치 타임라인`;$('#details').innerHTML=ordered.length?ordered.map(m=>`<article class="measure ${active.has(m.id)?'active-'+m.evaluation.toLowerCase():''}"><div class="meta">${esc(m.date)} · ${esc(m.implementing.join(', '))} · <span class="tag">${esc(m.evaluation)}</span> <span class="tag">${esc(m.type)}</span> <span class="tag">반도체 비중 ${m.share}% (${m.hs_total}개 중 ${m.hs_semi})</span>${m.removed?` <span class="tag">${esc(m.removed)} 만료·철회</span>`:''}${m.affected_missing?' <span class="tag unrev">피영향국 미기재</span>':''}</div><h3>${esc(m.title||'제목 없음')}</h3><div class="meta">HS ${esc(m.hs.join(', '))} · 피영향국 ${m.affected_missing?'미기재':m.affected.length+'개'}</div>${m.description?`<details><summary>설명문</summary><p>${esc(m.description)}</p></details>`:''}${m.url?`<a href="${esc(m.url)}" target="_blank" rel="noopener">GTA 원문 ↗</a>`:''}</article>`).join(''):'<div class="empty">선택 조건에 해당하는 조치가 없습니다.</div>'}

// =============================================================================
// #MAP_INTERACTION #ZOOM_PAN
// SVG viewBox zoom keeps the site dependency-free. Wheel/buttons zoom around
// the pointer or centre; pointer drag pans. Bounds prevent losing the map.
// =============================================================================
let mapView={x:0,y:0,w:1000,h:510},drag=null;
function applyMapView(){$('#map').setAttribute('viewBox',`${mapView.x} ${mapView.y} ${mapView.w} ${mapView.h}`)}
function zoomMap(f,cx=.5,cy=.5){const nw=Math.max(180,Math.min(1000,mapView.w*f)),nh=nw*510/1000;mapView.x+=mapView.w*cx-nw*cx;mapView.y+=mapView.h*cy-nh*cy;mapView.w=nw;mapView.h=nh;applyMapView()}
function initMapInteraction(){const m=$('#map');$('#zoom-in').onclick=()=>zoomMap(.75);$('#zoom-out').onclick=()=>zoomMap(1.33);$('#zoom-reset').onclick=()=>{mapView={x:0,y:0,w:1000,h:510};applyMapView()};m.onwheel=e=>{e.preventDefault();const r=m.getBoundingClientRect();zoomMap(e.deltaY<0?.82:1.22,(e.clientX-r.left)/r.width,(e.clientY-r.top)/r.height)};m.onpointerdown=e=>{drag={x:e.clientX,y:e.clientY,vx:mapView.x,vy:mapView.y};m.setPointerCapture(e.pointerId);m.classList.add('dragging')};m.onpointermove=e=>{if(!drag)return;const r=m.getBoundingClientRect();mapView.x=drag.vx-(e.clientX-drag.x)*mapView.w/r.width;mapView.y=drag.vy-(e.clientY-drag.y)*mapView.h/r.height;applyMapView()};m.onpointerup=()=>{drag=null;m.classList.remove('dragging')}}
// =============================================================================
// #COMBO_INPUT
// datalist 는 입력칸에 남은 글자로 목록을 걸러낸다. 칸에 'Republic of Korea'가
// 차 있으면 화살표를 눌러도 그 한 줄만 뜬다(2026-08-14 신고). 그래서 칸을
// 누르는 순간 비워 전체 목록을 보이고, 고르지 않고 빠져나가면 원래 값을 되돌린다.
// allowEmpty 는 시행국처럼 빈 값이 '전체'로 유효한 칸에 쓴다.
// =============================================================================
function bindCombo(input,values,emptyLabel,apply,current){
  const norm=v=>(v===ALL?'':v);
  input.addEventListener('focus',()=>{input.dataset.prev=input.value;input.value='';});
  input.addEventListener('mousedown',()=>{if(document.activeElement===input)input.value='';});
  input.addEventListener('input',()=>{const v=input.value.trim();
    if(v===''){apply('');return}
    if(v===ALL){input.value=emptyLabel;apply('');input.blur();return}
    if(values().includes(v)){apply(v);input.blur()}});
  input.addEventListener('blur',()=>{const v=input.value.trim();
    if(v===''||v===ALL){input.value=emptyLabel;apply('');return}
    if(!values().includes(v))input.value=input.dataset.prev||current()||emptyLabel;});
}
function acceptSearch(input,values,allValue=''){const v=input.value.trim();if(v===allValue||values.includes(v))return v;input.setCustomValidity('목록에 있는 관할을 선택하세요.');input.reportValidity();input.setCustomValidity('');return null}
// #DATE_SELECT: 슬라이더는 하루 단위, 달력 입력은 날짜 직접 선택에 쓴다.
// 두 입력은 항상 동기화하고 기준일까지 발표된 조치로 다수결을 다시 계산한다.
function fillDates(){const dates=D.measures.map(m=>m.date).filter(d=>/^\d{4}-\d{2}-\d{2}$/.test(d)).sort(),min=dates[0],max=dates.at(-1),slider=$('#cutoff-slider'),picker=$('#cutoff-date');
 $('.date-control-head label').append(' ',$('#date-label'));
 const toDay=d=>Math.floor(Date.parse(d+'T00:00:00Z')/86400000),toDate=n=>new Date(n*86400000).toISOString().slice(0,10),minDay=toDay(min),maxDay=toDay(max);
 slider.min=minDay;slider.max=maxDay;slider.value=state.cutoff?toDay(state.cutoff):maxDay;picker.min=min;picker.max=max;picker.value=state.cutoff||max;
 $('#date-min').textContent=min;$('#date-max').textContent=max;
 const apply=d=>{state.cutoff=d;slider.value=toDay(d);picker.value=d;$('#date-label').textContent=d;render()};
 slider.oninput=()=>apply(toDate(Number(slider.value)));picker.onchange=()=>{if(picker.value)apply(picker.value)};apply(picker.value)}
Promise.all([fetch('semi.json?v=__STAMP__',{cache:'no-store'}).then(r=>r.json()),fetch('world.geojson?v=__STAMP__').then(r=>r.json())]).then(([d,g])=>{D=d;G=g;state.affected=D.default_affected;$('#baseline').innerHTML=`수록 기준 — 조치가 지정한 HS 중 반도체 <b>${D.threshold}% 이상</b>. 관세표 전면 개정에 반도체 코드가 딸려 들어오는 것을 거르기 위함<br>GTA 자료 기준일 ${esc(D.gta_asof)}`;fillSelects();fillDates();drawBaseMap();initMapInteraction();bindCombo($('#affected'),()=>D.affected,ALL,v=>{state.affected=v;state.hs='';render()},()=>state.affected);bindCombo($('#implementing'),()=>D.implementing,ALL,v=>{state.implementing=v;render()},()=>state.implementing);$('#reset').onclick=()=>{state.hs='';render()};render()}).catch(e=>{$('#details').innerHTML=`<div class="empty">데이터를 불러오지 못했습니다: ${esc(e)}</div>`});
</script></body></html>'''
