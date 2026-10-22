"""패널 2 — 한미 AI 협력 트래커. Notion DB 를 읽어 JSON 으로 만들고, 그 JSON 으로 화면을 만든다.

  python ai_coop_site.py fetch      Notion DB -> data/ai_coop.json   (NOTION_TOKEN, NOTION_DB_ID)
  (publish_site.py 가 build(out) 를 호출)  data/ai_coop.json -> site/ai_coop.html, site/ai_coop.json

원칙
- 확정 코딩은 연구자가 Notion 에서 한다. 여기서는 읽기·집계·표시만 한다(자동 탐지·LLM 초벌 코딩은 범위 밖).
- Notion 열 이름은 PROPERTY_ALIASES 로 찾는다. 열 이름이 바뀌면 여기만 고친다. 못 찾은 열은 비워 두고 로그에 남긴다.
- `드라이브 링크` 같은 내부 링크는 내보내지 않는다. 공개 JSON 에는 날짜·주체·유형·형태·분야·내용·규모(원문 그대로)·원문 URL·상태만 들어간다.
- 금액(규모, 억 달러)은 아직 합산하지 않는다. 명목/추정 구분 열이 없어서다. 원문 그대로 보여 준다.
- 분석 단위는 '사건(행)' 하나. count 와 share 를 같이 쓰고 분모는 전체 사건 수다.
"""
from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE / "data" / "ai_coop.json"
NOTION_VERSION = "2022-06-28"

# 화면 필드 -> Notion 열 이름 후보(앞에서부터 먼저 맞는 것). 로드맵 3절의 현재 열 이름 기준.
PROPERTY_ALIASES: dict[str, list[str]] = {
    # 2026-10-22 실제 DB(한미 AI 협력 DB) 열: 일자 · 미국 주체 · 한국 주체 · 원문 링크 · 드라이브 링크 · 트랙 · 형태 · 분야 · 내용 · 규모(억 달러) · 비고
    "date": ["일자", "날짜", "Date"],
    "us": ["미국 주체", "미국 측 주체", "미국측 주체", "US"],
    "kr": ["한국 주체", "한국 측 주체", "한국측 주체", "KR"],
    "actor_type": ["트랙", "주체유형", "주체 유형"],
    "form": ["형태"],
    "sector": ["분야"],
    "content": ["내용", "제목", "Name", "이름"],
    "amount": ["규모(억 달러)", "규모", "금액"],
    "url": ["원문 링크", "원문 URL", "원문", "URL", "출처"],
    "status": ["상태"],
    "note": ["비고"],
}
FORM_ORDER = ["MOU·의향", "선언", "집행", "확정계약"]
# 미국 행정부 경계(타임라인 세로선). 취임일 기준.
ADMINISTRATIONS = [("오바마", "2009-01-20"), ("트럼프 1기", "2017-01-20"), ("바이든", "2021-01-20"), ("트럼프 2기", "2025-01-20")]


# ------------------------------------------------------------------ Notion


def _plain(prop: dict):
    """Notion 속성 객체 -> 평범한 값. 모르는 타입은 None."""
    t = prop.get("type")
    v = prop.get(t)
    if t in ("title", "rich_text"):
        return "".join(x.get("plain_text", "") for x in (v or [])).strip() or None
    if t in ("select", "status"):
        return (v or {}).get("name")
    if t == "multi_select":
        return [x.get("name") for x in (v or []) if x.get("name")]
    if t == "date":
        return (v or {}).get("start")
    if t in ("url", "number", "checkbox", "email", "phone_number"):
        return v
    if t == "people":
        return [x.get("name") for x in (v or []) if x.get("name")]
    if t == "relation":
        return [x.get("id") for x in (v or [])]
    if t == "formula":
        return _plain({"type": v.get("type"), v.get("type"): v.get(v.get("type"))}) if v else None
    if t == "rollup":
        return None
    return None


def fetch() -> int:
    import requests

    token = os.environ.get("NOTION_TOKEN", "").strip()
    db_id = os.environ.get("NOTION_DB_ID", "").strip()
    if not token or not db_id:
        print("[ai_coop] NOTION_TOKEN / NOTION_DB_ID 가 없습니다.")
        return 1
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}", "Notion-Version": NOTION_VERSION,
                      "Content-Type": "application/json"})
    rows, cursor = [], None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = s.post(f"https://api.notion.com/v1/databases/{db_id}/query", json=body, timeout=60)
        if r.status_code != 200:
            print(f"[ai_coop] Notion {r.status_code}: {r.text[:300]}")
            return 1
        payload = r.json()
        for page in payload.get("results", []):
            props = {name: _plain(p) for name, p in page.get("properties", {}).items()}
            rows.append({"id": page["id"], "created": page.get("created_time"),
                         "edited": page.get("last_edited_time"), "props": props})
        if not payload.get("has_more"):
            break
        cursor = payload.get("next_cursor")
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps({"fetched_at": datetime.now(timezone.utc).isoformat(), "database_id": db_id,
                               "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    names = Counter(k for row in rows for k in row["props"])
    print(f"[ai_coop] {len(rows)}행, 열 {len(names)}개: {', '.join(sorted(names))}")
    return 0


# ------------------------------------------------------------------ 정규화·집계


def _pick(props: dict, field: str):
    for name in PROPERTY_ALIASES[field]:
        if name in props and props[name] not in (None, "", []):
            return props[name]
    return None


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [p.strip() for p in str(v).replace("/", ",").replace(";", ",").split(",") if p.strip()]


def normalize(raw: dict) -> tuple[list[dict], dict]:
    """Notion 행 -> 사건 목록. 날짜가 없는 행은 뺀다(타임라인·연도 집계가 불가능)."""
    events, dropped, unmapped = [], 0, Counter()
    for row in raw.get("rows", []):
        p = row["props"]
        date = _pick(p, "date")
        if not date:
            dropped += 1
            continue
        for name in p:
            if not any(name in aliases for aliases in PROPERTY_ALIASES.values()):
                unmapped[name] += 1
        events.append({
            "id": row["id"], "date": str(date)[:10],
            "us": _as_list(_pick(p, "us")), "kr": _as_list(_pick(p, "kr")),
            "actor_type": _pick(p, "actor_type") or "미분류",
            "form": _pick(p, "form") or "미분류",
            "sector": _as_list(_pick(p, "sector")) or ["미분류"],
            "content": (_pick(p, "content") or "").strip(),
            "amount": (str(_pick(p, "amount")) if _pick(p, "amount") not in (None, "") else ""),
            "url": _pick(p, "url") or "",
            "status": _pick(p, "status") or "",
            "note": (_pick(p, "note") or "").strip(),
        })
    events.sort(key=lambda e: (e["date"], e["content"]))
    return events, {"dropped_no_date": dropped, "unmapped_columns": dict(unmapped)}


def aggregate(events: list[dict]) -> dict:
    n = len(events)
    forms = [f for f in FORM_ORDER if any(e["form"] == f for e in events)]
    forms += sorted({e["form"] for e in events} - set(forms))
    sectors = sorted({s for e in events for s in e["sector"]})
    years = sorted({e["date"][:4] for e in events})

    by_year_form = {y: Counter() for y in years}
    for e in events:
        by_year_form[e["date"][:4]][e["form"]] += 1
    matrix = {s: Counter() for s in sectors}
    for e in events:
        for s in e["sector"]:
            matrix[s][e["form"]] += 1
    pairs = Counter()
    for e in events:
        for u in e["us"] or ["(미국 측 미기재)"]:
            for k in e["kr"] or ["(한국 측 미기재)"]:
                pairs[(u, k)] += 1
    actor_type = Counter(e["actor_type"] for e in events)
    return {
        "n": n, "forms": forms, "sectors": sectors, "years": years,
        "by_year_form": {y: dict(c) for y, c in by_year_form.items()},
        "matrix": {s: dict(c) for s, c in matrix.items()},
        "pairs": [{"us": u, "kr": k, "n": c} for (u, k), c in pairs.most_common(30)],
        "actor_type": dict(actor_type),
        "form_total": dict(Counter(e["form"] for e in events)),
    }


# ------------------------------------------------------------------ 화면


def nav(current: str) -> str:
    links = [("ip_risk.html", "Industrial Policy"), ("ai_coop.html", "AI Cooperation"), ("data.html", "Data")]
    cur = ' aria-current="page"'
    items = "".join(f'<a href="{h}"{cur if h == current else ""}>{t}</a>' for h, t in links)
    return (f'<nav class="site-nav"><div class="wrap"><a class="brand" href="index.html">'
            f'<span class="mark"></span>SKL Economic Security Tracker</a><div class="links">{items}</div></div></nav>')


def footer(asof: str, built: str) -> str:
    sha = os.environ.get("GIT_SHA", "")[:7]
    return (f'<footer class="site-footer"><div class="wrap"><span>SKL Economic Security Tracker · 연구용 자료</span>'
            f'<span class="build">자료 {html.escape(asof)} · 빌드 {html.escape(built)}{(" · " + sha) if sha else ""}</span></div></footer>')


def render(agg: dict, meta: dict) -> str:
    n = agg["n"]
    asof = meta.get("fetched_at", "")[:10] or "—"
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    if n == 0:
        body = ('<div class="wrap section"><div class="empty">아직 연결된 자료가 없습니다. Notion DB 통합 토큰과 '
                'DB ID 가 GitHub Secrets 에 들어가면 다음 실행부터 여기에 채워집니다.</div></div>')
        return _page("한미 AI 협력 트래커", "", body, asof, built)

    def pct(c: int) -> str:
        return f"{c / n * 100:.1f}%"

    # 매트릭스(분야 x 형태)
    head = "".join(f'<th class="num">{html.escape(f)}</th>' for f in agg["forms"])
    rows = []
    for s in agg["sectors"]:
        cells = "".join(
            f'<td class="cell">{agg["matrix"][s].get(f, 0)}<small>{pct(agg["matrix"][s].get(f, 0))}</small></td>'
            for f in agg["forms"])
        total = sum(agg["matrix"][s].values())
        rows.append(f'<tr><td>{html.escape(s)}</td>{cells}<td class="cell"><b>{total}</b><small>{pct(total)}</small></td></tr>')
    matrix_html = (f'<table class="matrix"><thead><tr><th>분야</th>{head}<th class="num">합계</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table>'
                   f'<p class="note">셀 = 사건 수와 전체 {n}건 대비 비중. 한 사건이 분야 여러 개에 걸리면 각 분야에 센다(분야 합계는 {n}건을 넘을 수 있다).</p>')

    # 형태별 막대
    bars = "".join(
        f'<div class="row"><span>{html.escape(f)}</span><div><div class="bar" style="width:{agg["form_total"].get(f, 0) / n * 100:.1f}%"></div></div>'
        f'<span class="n">{agg["form_total"].get(f, 0)} · {pct(agg["form_total"].get(f, 0))}</span></div>' for f in agg["forms"])

    pairs = "".join(
        f'<li><span>{html.escape(p["us"])}</span><span class="arrow">↔</span><span>{html.escape(p["kr"])}</span><span class="n">{p["n"]}</span></li>'
        for p in agg["pairs"][:15])

    hero_meta = (f'<div class="meta"><div>사건<b>{n:,}건</b></div><div>기간<b>{agg["years"][0]}–{agg["years"][-1]}</b></div>'
                 f'<div>확정계약<b>{agg["form_total"].get("확정계약", 0)}건</b></div><div>자료 기준<b>{html.escape(asof)}</b></div></div>')

    body = f'''
<div class="wrap">
  <section class="section">
    <span class="eyebrow">Timeline</span>
    <div class="panel"><div class="panel-head"><span>사건 타임라인 — 형태별 마커, 행정부 경계</span><span id="tl-legend" class="legend"></span></div>
      <div class="panel-body timeline-wrap"><svg id="timeline" viewBox="0 0 1000 300" aria-label="한미 AI 협력 사건 타임라인"></svg><div id="tl-tip" class="tooltip"></div></div></div>
  </section>
  <section class="section grid grid-2">
    <div><span class="eyebrow">Form</span><div class="panel"><div class="panel-head">형태별 건수 · 비중 (분모 {n}건)</div><div class="panel-body bars">{bars}</div></div></div>
    <div><span class="eyebrow">Actors</span><div class="panel"><div class="panel-head">미국 주체 ↔ 한국 주체 (상위 15 조합)</div><div class="panel-body"><ul class="pairs" style="list-style:none;margin:0;padding:0">{pairs}</ul></div></div></div>
  </section>
  <section class="section">
    <span class="eyebrow">Sector × Form</span>
    <div class="panel"><div class="panel-head">분야 × 형태 매트릭스</div><div class="panel-body" style="overflow-x:auto">{matrix_html}</div></div>
  </section>
  <section class="section">
    <span class="eyebrow">Records</span>
    <div class="panel"><div class="panel-head"><span>사건 목록 (최신순)</span><input id="q" type="search" placeholder="검색…" style="min-height:34px"></div>
      <div class="panel-body" style="overflow-x:auto"><table id="records"><thead><tr><th>날짜</th><th>형태</th><th>분야</th><th>미국 측</th><th>한국 측</th><th>내용</th><th>규모</th><th>원문</th></tr></thead><tbody></tbody></table></div></div>
  </section>
  <details><summary>방법론</summary><p class="note">분석 단위는 사건(Notion DB 의 행) 하나다. 형태(MOU·의향/선언/집행/확정계약)와 분야는 연구자가 Notion 에서 확정한 코딩이며 이 화면은 읽기만 한다. 날짜가 없는 행은 제외했다(제외 {meta.get("dropped_no_date", 0)}건). 규모는 통화와 명목·추정이 섞여 있어 합산하지 않고 원문 그대로 보인다. 행정부 경계선은 미국 대통령 취임일이다.</p></details>
</div>
<script>
const FORMS={json.dumps(agg["forms"], ensure_ascii=False)};
const ADMIN={json.dumps(ADMINISTRATIONS, ensure_ascii=False)};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const FORM_COLOR={{}};FORMS.forEach((f,i)=>FORM_COLOR[f]=css('--cat-'+(i+1)));
fetch('ai_coop.json',{{cache:'no-store'}}).then(r=>r.json()).then(D=>{{
  const E=D.events; const tip=document.getElementById('tl-tip');
  document.getElementById('tl-legend').innerHTML=FORMS.map(f=>`<span><i style="background:${{FORM_COLOR[f]}}"></i>${{f}}</span>`).join('');
  const svg=document.getElementById('timeline'); const W=1000,H=300,L=40,R=20,T=30,B=40;
  const t0=new Date(E[0].date+'T00:00:00Z'), t1=new Date(E[E.length-1].date+'T00:00:00Z');
  const y0=t0.getUTCFullYear(), y1=t1.getUTCFullYear()+1;
  const x=d=>L+(new Date(d+'T00:00:00Z')-Date.UTC(y0,0,1))/(Date.UTC(y1,0,1)-Date.UTC(y0,0,1))*(W-L-R);
  let s='';
  for(let y=y0;y<=y1;y++){{const xx=x(y+'-01-01');s+=`<line x1="${{xx}}" x2="${{xx}}" y1="${{T}}" y2="${{H-B}}" stroke="${{css('--line')}}"/><text class="tl-axis" x="${{xx+3}}" y="${{H-B+16}}">${{y}}</text>`;}}
  ADMIN.forEach(([name,d])=>{{const yy=d.slice(0,4); if(yy<y0||yy>y1)return; const xx=x(d); s+=`<line x1="${{xx}}" x2="${{xx}}" y1="${{T-10}}" y2="${{H-B}}" stroke="${{css('--ink')}}" stroke-dasharray="3 3"/><text class="tl-admin" x="${{xx+4}}" y="${{T-2}}">${{name}}</text>`;}});
  const lanes=FORMS.length, laneH=(H-T-B-20)/Math.max(lanes,1);
  FORMS.forEach((f,i)=>{{const yy=T+20+laneH*i+laneH/2; s+=`<text class="tl-axis" x="${{L-4}}" y="${{yy+4}}" text-anchor="end">${{f.slice(0,4)}}</text>`;}});
  E.forEach((e,i)=>{{const li=Math.max(FORMS.indexOf(e.form),0); const yy=T+20+laneH*li+laneH/2+((i%5)-2)*3; s+=`<circle data-i="${{i}}" cx="${{x(e.date)}}" cy="${{yy}}" r="4.5" fill="${{FORM_COLOR[e.form]||css('--muted')}}" fill-opacity=".85"/>`;}});
  svg.innerHTML=s;
  svg.addEventListener('mousemove',ev=>{{const c=ev.target.closest('circle'); if(!c){{tip.style.display='none';return;}} const e=E[+c.dataset.i]; tip.innerHTML=`<b>${{e.date}} · ${{e.form}}</b><br>${{e.content}}<br><span style="opacity:.8">${{e.us.join(', ')}} ↔ ${{e.kr.join(', ')}}${{e.amount?' · '+e.amount:''}}</span>`; const r=svg.parentElement.getBoundingClientRect(); tip.style.left=(ev.clientX-r.left+12)+'px'; tip.style.top=(ev.clientY-r.top+12)+'px'; tip.style.display='block';}});
  svg.addEventListener('mouseleave',()=>tip.style.display='none');
  const tb=document.querySelector('#records tbody'); const esc=t=>String(t).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
  const draw=q=>{{const qq=(q||'').toLowerCase(); tb.innerHTML=[...E].reverse().filter(e=>!qq||JSON.stringify(e).toLowerCase().includes(qq)).map(e=>`<tr><td style="white-space:nowrap">${{e.date}}</td><td>${{esc(e.form)}}</td><td>${{esc(e.sector.join(', '))}}</td><td>${{esc(e.us.join(', '))}}</td><td>${{esc(e.kr.join(', '))}}</td><td>${{esc(e.content)}}</td><td>${{esc(e.amount)}}</td><td>${{e.url?`<a href="${{esc(e.url)}}" target="_blank" rel="noopener">원문</a>`:''}}</td></tr>`).join('');}};
  draw(''); document.getElementById('q').addEventListener('input',ev=>draw(ev.target.value));
}});
</script>'''
    return _page("한미 AI 협력 트래커", hero_meta, body, asof, built)


def _page(title: str, hero_meta: str, body: str, asof: str, built: str) -> str:
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · SKL</title><link rel="stylesheet" href="site.css"></head>
<body>{nav("ai_coop.html")}
<header class="hero"><div class="wrap"><span class="eyebrow">Panel 2</span><h1>{html.escape(title)}</h1>
<p>미국과 한국의 정부·민간 주체가 맺은 AI 협력 사건을 날짜·형태(MOU·의향/선언/집행/확정계약)·분야별로 추적한다. 코딩은 연구자가 Notion 에서 확정하고, 이 화면은 야간에 한 번 그 결과를 읽어 그린다.</p>{hero_meta}</div></header>
{body}
{footer(asof, built)}
</body></html>'''


def build(out: Path) -> bool:
    if not RAW.is_file():
        print("[ai_coop_site] data/ai_coop.json 없음 — 빈 화면으로 생성")
        raw = {"rows": []}
    else:
        raw = json.loads(RAW.read_text(encoding="utf-8"))
    events, meta = normalize(raw)
    meta["fetched_at"] = raw.get("fetched_at", "")
    agg = aggregate(events)
    (out / "ai_coop.json").write_text(json.dumps({"as_of": meta["fetched_at"], "n": agg["n"], "events": events, "agg": agg},
                                                 ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "ai_coop.html").write_text(render(agg, meta), encoding="utf-8")
    if meta["unmapped_columns"]:
        print(f"[ai_coop_site] 매핑되지 않은 열: {', '.join(meta['unmapped_columns'])}")
    print(f"[ai_coop_site] 사건 {agg['n']}건 (날짜 없음 제외 {meta['dropped_no_date']}건)")
    return agg["n"] > 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "fetch":
        sys.exit(fetch())
    print(__doc__)
