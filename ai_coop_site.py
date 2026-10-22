"""패널 2 — 한미 AI 협력 트래커 화면. data/ai_coop_events.json 을 읽어 site/ai_coop.html, site/ai_coop.json 을 만든다.

사건 파일은 collect_ai_coop.py 가 만든다(seed: 연구자 확정 코딩 CSV, 이후 Task A/B 자동 수집). 파일이 없으면
시드에서 즉석 생성한다. 2026-10-22 Notion 연동은 폐기했다(연구자 결정).

원칙
- 분석 단위는 사건 하나. count 와 share 를 같이 쓰고 분모는 전체 사건 수다.
- status(confirmed/auto/rejected) 를 화면에 그대로 보인다. 모델 코딩을 확정 라벨처럼 보이지 않게 한다.
- 금액은 명시된 억 달러만 쓰고 추정치는 합산하지 않는다.
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
EVENTS = HERE / "data" / "ai_coop_events.json"
FORM_ORDER = ["MOU·의향", "선언", "집행", "확정계약"]
# 미국 행정부 경계(타임라인 세로선). 취임일 기준.
ADMINISTRATIONS = [("오바마", "2009-01-20"), ("트럼프 1기", "2017-01-20"), ("바이든", "2021-01-20"), ("트럼프 2기", "2025-01-20")]


def load_events() -> tuple[list[dict], dict]:
    """data/ai_coop_events.json -> 화면용 사건 목록. 없으면 시드에서 만든다. rejected 는 뺀다."""
    if not EVENTS.is_file():
        import collect_ai_coop
        if any(collect_ai_coop.SEED_DIR.glob("*.csv")):
            collect_ai_coop.cmd_seed()
    if not EVENTS.is_file():
        return [], {"as_of": ""}
    raw = json.loads(EVENTS.read_text(encoding="utf-8"))
    events = []
    for e in raw.get("events", []):
        if e.get("status") == "rejected" or not e.get("date"):
            continue
        amt = e.get("amount_usd_bn")
        events.append({
            "id": e["id"], "date": e["date"][:10],
            "us": e.get("us_parties", []), "kr": e.get("kr_parties", []),
            "actor_type": e.get("track") or "미분류", "form": e.get("form") or "미분류",
            "sector": e.get("sectors") or ["미분류"],
            "content": e.get("title", ""), "summary": e.get("summary", ""),
            "amount": (f"{amt:g}억 달러" + (" (추정)" if e.get("amount_is_estimate") else "")) if amt is not None else "",
            "amount_usd_bn": amt,
            "url": (e.get("sources") or [{}])[0].get("url", ""),
            "source_grade": (e.get("sources") or [{}])[0].get("grade"),
            "status": e.get("status", "auto"), "lifecycle": e.get("lifecycle", ""),
            "confidence": e.get("confidence"), "administration": e.get("administration", ""),
            "prior_event_id": e.get("prior_event_id"), "note": e.get("note", ""),
        })
    events.sort(key=lambda x: (x["date"], x["content"]))
    return events, {"as_of": raw.get("as_of", "")}


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
        "status": dict(Counter(e["status"] for e in events)),
        "amount_confirmed_total": round(sum(e["amount_usd_bn"] for e in events if e["amount_usd_bn"] and e["form"] == "확정계약"), 1),
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
        body = ('<div class="wrap section"><div class="empty">아직 사건 자료가 없습니다. data/seed 의 CSV 나 자동 수집 결과가 들어오면 채워집니다.</div></div>')
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
                 f'<div>확정계약<b>{agg["form_total"].get("확정계약", 0)}건</b></div><div>확정 코딩<b>{agg["status"].get("confirmed", 0)}건</b></div><div>자료 기준<b>{html.escape(asof)}</b></div></div>')

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
      <div class="panel-body" style="overflow-x:auto"><table id="records"><thead><tr><th>날짜</th><th>상태</th><th>형태</th><th>분야</th><th>미국 측</th><th>한국 측</th><th>내용</th><th>규모</th><th>원문</th></tr></thead><tbody></tbody></table></div></div>
  </section>
  <details><summary>방법론</summary><p class="note">분석 단위는 사건 하나다. 상태 '확정'은 연구자가 코딩한 사건, '자동'은 모델(Claude)이 기사에서 추출한 사건이며 확정 라벨이 아니다. 형태(MOU·의향/선언/집행/확정계약)는 발표 시점의 구속력 기준이다. 규모는 통화와 명목·추정이 섞여 있어 합산하지 않고 원문 그대로 보인다. 행정부 경계선은 미국 대통령 취임일이다.</p></details>
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
  const draw=q=>{{const qq=(q||'').toLowerCase(); tb.innerHTML=[...E].reverse().filter(e=>!qq||JSON.stringify(e).toLowerCase().includes(qq)).map(e=>`<tr><td style="white-space:nowrap">${{e.date}}</td><td><span class="chip" style="cursor:default">${{e.status==='confirmed'?'확정':'자동'}}</span></td><td>${{esc(e.form)}}</td><td>${{esc(e.sector.join(', '))}}</td><td>${{esc(e.us.join(', '))}}</td><td>${{esc(e.kr.join(', '))}}</td><td>${{esc(e.content)}}</td><td>${{esc(e.amount)}}</td><td>${{e.url?`<a href="${{esc(e.url)}}" target="_blank" rel="noopener">원문</a>`:''}}</td></tr>`).join('');}};
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
<p>미국과 한국의 정부·민간 주체가 맺은 AI 협력 사건을 날짜·형태(MOU·의향/선언/집행/확정계약)·분야별로 추적한다. 연구자 확정 코딩과 모델 자동 코딩을 상태로 구분해 보인다.</p>{hero_meta}</div></header>
{body}
{footer(asof, built)}
</body></html>'''


def build(out: Path) -> bool:
    events, meta = load_events()
    agg = aggregate(events)
    (out / "ai_coop.json").write_text(json.dumps({"as_of": meta["as_of"], "n": agg["n"], "events": events, "agg": agg},
                                                 ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "ai_coop.html").write_text(render(agg, {"fetched_at": meta["as_of"]}), encoding="utf-8")
    print(f"[ai_coop_site] 사건 {agg['n']}건 (확정 {agg['status'].get('confirmed', 0)}, 자동 {agg['status'].get('auto', 0)})")
    return agg["n"] > 0


if __name__ == "__main__":
    print(__doc__)
