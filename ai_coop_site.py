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
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
EVENTS = HERE / "data" / "ai_coop_events.json"
REPO = "lskyonsei-jpg/skl-economic-security-tracker"
FORM_ORDER = ["선언", "MOU·의향", "집행", "확정계약"]   # 약한 것부터 (연구자 지시 2026-10-22)
# 미국 행정부 경계(타임라인 세로선). 취임일 기준.
ADMINISTRATIONS = [("오바마", "2009-01-20"), ("트럼프 1기", "2017-01-20"), ("바이든", "2021-01-20"), ("트럼프 2기", "2025-01-20")]


GOV_RE = re.compile(r"^정부\((.+)\)$")


def disp(name: str) -> str:
    """화면 표기. 자료의 표준 표기 '정부(미국)' 은 그대로 두고(모델 프롬프트·중복 판정이 이 표기를 쓴다) 화면에서만 '미국(정부)' 로 보인다."""
    m = GOV_RE.match(name or "")
    return f"{m.group(1)}(정부)" if m else name


def load_orgs() -> dict:
    """기관 표기 목록(reference/ai_coop_orgs.csv) → {화면 표기: {country, type}}."""
    import csv
    path = HERE / "reference" / "ai_coop_orgs.csv"
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as f:
        return {disp(r["canonical"]): {"country": r.get("country", ""), "type": r.get("type", "")} for r in csv.DictReader(f)}


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
            "us": [disp(x) for x in e.get("us_parties", [])], "kr": [disp(x) for x in e.get("kr_parties", [])],
            "actor_type": e.get("track") or "미분류", "form": e.get("form") or "미분류",
            "sector": e.get("sectors") or ["미분류"],
            "content": e.get("title", ""), "summary": e.get("summary", ""),
            "amount": (f"{amt:g}억 달러" + (" (추정)" if e.get("amount_is_estimate") else "")) if amt is not None else "",
            "amount_usd_bn": amt,
            "url": (e.get("sources") or [{}])[0].get("url", ""), "sources": [x.get("url", "") for x in (e.get("sources") or []) if x.get("url")],
            "updates": e.get("updates", []), "coded_by": e.get("coded_by", ""),
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


PANEL2_PAGES = ("ai_coop.html", "review.html")  # AI Cooperation 아래 Dashboard · Review


def nav(current: str) -> str:
    links = [("ip_risk.html", "Industrial Policy"), ("ai_coop.html", "AI Cooperation"),
             ("data.html", "Data"), ("codebook.html", "Codebook")]
    cur = ' aria-current="page"'
    if current in PANEL2_PAGES:
        current = "ai_coop.html"
    items = "".join(f'<a href="{h}"{cur if h == current else ""}>{t}</a>' for h, t in links)
    return (f'<nav class="site-nav"><div class="wrap"><a class="brand" href="index.html">'
            f'<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>SKL Economic Security Tracker</a><div class="links">{items}</div></div></nav>')


def subnav(current: str) -> str:
    """AI Cooperation 히어로 아래 탭: Dashboard(ai_coop.html) · Review(review.html)."""
    tabs = [("ai_coop.html", "Dashboard"), ("review.html", "Review")]
    cur = ' aria-current="page"'
    items = "".join(f'<a href="{h}"{cur if h == current else ""}>{t}</a>' for h, t in tabs)
    return f'<nav class="subnav">{items}</nav>'


def with_last_update(body: str, date: str) -> str:
    """히어로(</header>) 바로 아래 왼쪽에 작은 글씨로 Last update 를 넣는다. 날짜가 없으면 그대로."""
    if not date or "</header>" not in body:
        return body
    return body.replace("</header>", f'</header><div class="wrap last-update">Last update {html.escape(date)}</div>', 1)


def footer(asof: str, built: str) -> str:
    sha = os.environ.get("GIT_SHA", "")[:7]
    return (f'<footer class="site-footer"><div class="wrap"><span>SKL Economic Security Tracker · 연구용 자료</span>'
            f'<span class="build">자료 {html.escape(asof)} · 빌드 {html.escape(built)}{(" · " + sha) if sha else ""}</span></div></footer>')


def render(agg: dict, meta: dict) -> str:
    n = agg["n"]
    asof = meta.get("fetched_at", "")[:10] or "—"
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    if n == 0:
        body = ('<div class="wrap section"><div class="empty">아직 사건 자료가 없습니다.</div></div>')
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
                   f'<p class="note">건수 · 전체 {n}건 대비 비중. 여러 분야에 걸친 사건은 분야마다 집계.</p>')

    # 형태별 막대
    bars = "".join(
        f'<div class="row"><span>{html.escape(f)}</span><div><div class="bar" style="width:{agg["form_total"].get(f, 0) / n * 100:.1f}%"></div></div>'
        f'<span class="n">{agg["form_total"].get(f, 0)} · {pct(agg["form_total"].get(f, 0))}</span></div>' for f in agg["forms"])

    pairs = "".join(
        f'<li><span>{html.escape(p["us"])}</span><span class="arrow">↔</span><span>{html.escape(p["kr"])}</span><span class="n">{p["n"]}</span></li>'
        for p in agg["pairs"][:15])

    hero_meta = ""   # 수치 없이 제목만 (연구자 지시 2026-10-22)
    _unused = (f'<div class="meta"><div>사건<b>{n:,}건</b></div><div>기간<b>{agg["years"][0]}–{agg["years"][-1]}</b></div>'
                 f'<div>확정계약<b>{agg["form_total"].get("확정계약", 0)}건</b></div><div>확정 코딩<b>{agg["status"].get("confirmed", 0)}건</b></div><div>자료 기준<b>{html.escape(asof)}</b></div></div>')

    body = f'''
<div class="wrap">
  <section class="section">
    <span class="eyebrow">Timeline</span>
    <div class="panel"><div class="panel-head"><span>사건 타임라인</span><span id="tl-legend" class="legend"></span><a href="codebook.html#panel2">코드북</a></div>
      <div class="panel-body timeline-wrap"><svg id="timeline" viewBox="0 0 1000 420" aria-label="한미 AI 협력 사건 타임라인"></svg><div id="tl-tip" class="tooltip"></div></div></div>
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
    <div class="panel"><details class="records-toggle" id="records-box"><summary><span class="btn small"></span><span>사건 목록 {n}건 (최신순)</span><input id="q" type="search" placeholder="검색" onclick="event.preventDefault()"></summary>
      <div class="tablebox"><div id="org-card"></div><table id="records"><thead><tr><th>날짜</th><th>제목</th><th>형태</th><th>분야</th><th>미국 측</th><th>한국 측</th><th>규모</th><th>상태</th></tr></thead><tbody></tbody></table></div></details></div>
  </section>
</div>
<script>
const FORMS={json.dumps(agg["forms"], ensure_ascii=False)};
const ADMIN={json.dumps(ADMINISTRATIONS, ensure_ascii=False)};
const css=v=>getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const FORM_COLOR={{}};FORMS.forEach((f,i)=>FORM_COLOR[f]=css('--cat-'+(i+1)));
fetch('ai_coop.json',{{cache:'no-store'}}).then(r=>r.json()).then(D=>{{
  const E=D.events; const tip=document.getElementById('tl-tip');
  document.getElementById('tl-legend').innerHTML=FORMS.map(f=>`<span><i style="background:${{FORM_COLOR[f]}}"></i>${{f}}</span>`).join('');
  const svg=document.getElementById('timeline'); const W=1000,H=420,L=150,R=24,T=44,B=50;
  const t0=new Date(E[0].date+'T00:00:00Z'), t1=new Date(E[E.length-1].date+'T00:00:00Z');
  const y0=t0.getUTCFullYear(), y1=t1.getUTCFullYear()+1;
  const x=d=>L+(new Date(d+'T00:00:00Z')-Date.UTC(y0,0,1))/(Date.UTC(y1,0,1)-Date.UTC(y0,0,1))*(W-L-R);
  let s='';
  for(let y=y0;y<=y1;y++){{const xx=x(y+'-01-01');s+=`<line x1="${{xx}}" x2="${{xx}}" y1="${{T}}" y2="${{H-B}}" stroke="${{css('--line')}}"/>`; if((y-y0)%2===0||y1-y0<8) s+=`<text class="tl-axis" x="${{xx+4}}" y="${{H-B+26}}">${{y}}</text>`;}}
  ADMIN.forEach(([name,d])=>{{const yy=d.slice(0,4); if(yy<y0||yy>y1)return; const xx=x(d); s+=`<line x1="${{xx}}" x2="${{xx}}" y1="${{T-14}}" y2="${{H-B}}" stroke="${{css('--ink')}}" stroke-dasharray="3 3"/><text class="tl-admin" x="${{xx+6}}" y="${{T-2}}">${{name}}</text>`;}});
  const lanes=FORMS.length, laneH=(H-T-B-20)/Math.max(lanes,1);
  FORMS.forEach((f,i)=>{{const yy=T+20+laneH*i+laneH/2; s+=`<text class="tl-axis" x="${{L-10}}" y="${{yy+8}}" text-anchor="end">${{f}}</text>`;}});
  // 같은 줄에서 가로로 16 단위 안에 있는 점은 위아래 칸(±16)으로 비켜 놓는다 — 점마다 따로 집을 수 있게 (연구자 지시 2026-10-23)
  const placed=FORMS.map(()=>[]); const STEP=16, MINDX=16;
  E.map((e,i)=>({{e,i,li:Math.max(FORMS.indexOf(e.form),0),cx:x(e.date)}})).sort((a,b)=>a.cx-b.cx).forEach(d=>{{
    const order=[0,1,-1,2,-2,3,-3]; let k=order.find(k=>!placed[d.li].some(q=>q.k===k&&Math.abs(q.cx-d.cx)<MINDX)); if(k===undefined)k=0;
    placed[d.li].push({{k,cx:d.cx}}); const yy=T+20+laneH*d.li+laneH/2+k*STEP;
    s+=`<circle data-i="${{d.i}}" cx="${{d.cx}}" cy="${{yy}}" r="7" fill="${{FORM_COLOR[d.e.form]||css('--muted')}}" fill-opacity=".9"/>`;}});
  svg.innerHTML=s;
  svg.addEventListener('mousemove',ev=>{{const c=ev.target.closest('circle'); if(!c){{tip.style.display='none';return;}} const e=E[+c.dataset.i]; tip.innerHTML=`<b>${{e.date}}</b><br>${{e.us.join(', ')}} ↔ ${{e.kr.join(', ')}}`; const r=svg.parentElement.getBoundingClientRect(); tip.style.left=(ev.clientX-r.left+12)+'px'; tip.style.top=(ev.clientY-r.top+12)+'px'; tip.style.display='block';}});
  svg.addEventListener('mouseleave',()=>tip.style.display='none');
  const tb=document.querySelector('#records tbody'); const esc=t=>String(t).replace(/[&<>"]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
  const ORGS=D.orgs||{{}}; let orgSel=null;
  const orgLink=n=>`<a href="#" class="org" data-org="${{esc(n)}}">${{esc(n)}}</a>`;
  const detail=e=>{{const ups=(e.updates||[]).map(u=>`<li>${{esc(u.date||'')}} ${{esc(u.field||u.kind||'')}}${{u.old!==undefined?` ${{esc(u.old)}} → ${{esc(u.new)}}`:''}}${{u.evidence?` <span class="small">${{esc(u.evidence)}}</span>`:''}}</li>`).join('');
    const srcs=(e.sources||[]).map((u,i)=>`<a href="${{esc(u)}}" target="_blank" rel="noopener">원문${{i?i+1:''}}</a>`).join(' · ');
    return `<div class="ev-detail"><div class="ev-grid"><span>구분</span><span>${{esc(e.actor_type)}} · ${{e.status==='confirmed'?'연구자 확정':'모델 코딩'}}${{e.lifecycle?' · 진행 '+esc(e.lifecycle):''}}${{e.administration?' · '+esc(e.administration):''}}</span>`+
      (e.summary?`<span>요약</span><span>${{esc(e.summary)}}</span>`:'')+(e.note?`<span>비고</span><span>${{esc(e.note)}}</span>`:'')+(e.amount?`<span>규모</span><span>${{esc(e.amount)}}</span>`:'')+
      (e.prior_event_id?`<span>선행</span><span>${{esc((E.find(x=>x.id===e.prior_event_id)||{{}}).content||e.prior_event_id)}}</span>`:'')+
      (ups?`<span>후속 갱신</span><span><ul class="ev-updates">${{ups}}</ul></span>`:'')+(srcs?`<span>출처</span><span>${{srcs}}</span>`:'')+`</div></div>`;}};
  const draw=q=>{{const qq=(q||'').toLowerCase(); const rows=[...E].reverse().filter(e=>(!orgSel||e.us.includes(orgSel)||e.kr.includes(orgSel))&&(!qq||JSON.stringify(e).toLowerCase().includes(qq)));
    tb.innerHTML=rows.map((e,i)=>`<tr class="ev-row" data-i="${{i}}" data-id="${{esc(e.id)}}"><td class="d">${{e.date}}</td><td><a href="#" class="ev-title">${{esc(e.content)}}</a></td><td>${{esc(e.form)}}</td><td>${{esc(e.sector.join(', '))}}</td><td>${{e.us.map(orgLink).join(', ')}}</td><td>${{e.kr.map(orgLink).join(', ')}}</td><td>${{esc(e.amount)}}</td><td><span class="chip" style="cursor:default">${{e.status==='confirmed'?'확정':'자동'}}</span></td></tr><tr class="ev-more" hidden><td colspan="8">${{detail(e)}}</td></tr>`).join('');
    const card=document.getElementById('org-card');
    if(orgSel){{const o=ORGS[orgSel]||{{}}; const forms={{}}; rows.forEach(e=>forms[e.form]=(forms[e.form]||0)+1); const partners={{}}; rows.forEach(e=>(e.us.includes(orgSel)?e.kr:e.us).forEach(p=>partners[p]=(partners[p]||0)+1));
      card.innerHTML=`<div class="org-box"><b>${{esc(orgSel)}}</b> <span class="small">${{o.type?esc(o.type)+' · ':''}}${{o.country?esc(o.country)+' · ':''}}사건 ${{rows.length}}건 · ${{FORMS.filter(f=>forms[f]).map(f=>f+' '+forms[f]).join(' · ')}}</span><br><span class="small">상대: ${{Object.entries(partners).sort((a,b)=>b[1]-a[1]).map(([p,n])=>orgLink(p)+' '+n).join(', ')||'-'}}</span> <button class="btn small" id="org-clear" type="button">전체 보기</button></div>`;
      document.getElementById('org-clear').onclick=()=>{{orgSel=null;draw(q);}};}} else card.innerHTML='';}};
  tb.addEventListener('click',ev=>{{const t=ev.target.closest('a.ev-title'); if(t){{ev.preventDefault(); const more=t.closest('tr').nextElementSibling; more.hidden=!more.hidden; return;}}
    const o=ev.target.closest('a.org'); if(o){{ev.preventDefault(); orgSel=o.dataset.org; draw(document.getElementById('q').value); document.getElementById('records-box').open=true; document.getElementById('org-card').scrollIntoView({{block:'nearest'}});}}}});
  document.getElementById('org-card').addEventListener('click',ev=>{{const o=ev.target.closest('a.org'); if(o){{ev.preventDefault(); orgSel=o.dataset.org; draw(document.getElementById('q').value);}}}});
  draw(''); const q=document.getElementById('q');
  const goHash=()=>{{const h=decodeURIComponent(location.hash.slice(1)); if(!h)return; const tr=tb.querySelector(`tr[data-id="${{h.replace(/"/g,'')}}"]`); if(!tr)return;
    document.getElementById('records-box').open=true; tr.nextElementSibling.hidden=false; tb.querySelectorAll('tr.hl').forEach(r=>r.classList.remove('hl')); tr.classList.add('hl'); tr.scrollIntoView({{block:'center'}});}};
  goHash(); window.addEventListener('hashchange',goHash); q.addEventListener('input',ev=>{{draw(ev.target.value); if(ev.target.value) document.getElementById('records-box').open=true;}});
}});
</script>'''
    return _page("한미 AI 협력 트래커", hero_meta, body, asof, built)


def _page(title: str, hero_meta: str, body: str, asof: str, built: str) -> str:
    return f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · SKL</title><link rel="stylesheet" href="site.css"></head>
<body>{nav("ai_coop.html")}
<header class="hero"><div class="wrap"><span class="eyebrow">Panel 2 · AI Cooperation</span><div class="hero-row"><h1>{html.escape(title)}</h1>{subnav("ai_coop.html")}</div>
{hero_meta}</div></header>
{with_last_update("</header>", built[:10])[len("</header>"):]}
{body}
{footer(asof, built)}
</body></html>'''


# ------------------------------------------------------------------ 판단 대기(review.html)

STATE_FILE = HERE / "data" / "ai_coop_state.json"


def pending_proposals() -> list[dict]:
    if not STATE_FILE.is_file():
        return []
    st = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return [p for p in st.get("proposals", []) if p.get("status") == "proposed"]


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def render_review(props: list[dict], events_by_id: dict) -> str:
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    by_task = {k: [p for p in props if p["task"] == k] for k in ("A", "B", "C")}
    hero_meta = (f'<div class="meta"><div>판단 대기<b>{len(props)}건</b></div><div>A 새 사건<b>{len(by_task["A"])}</b></div>'
            f'<div>B 갱신<b>{len(by_task["B"])}</b></div><div>C 재검토<b>{len(by_task["C"])}</b></div></div>')
    def ev_line(ev: dict) -> str:
        return (f'{_esc(ev.get("date"))} · {_esc(ev.get("form"))} · {_esc(ev.get("track"))} · {_esc(", ".join(ev.get("sectors", [])))} · '
                f'금액 {_esc(ev.get("amount_usd_bn"))} · conf {_esc(ev.get("confidence"))}')
    FIELD_KO = {"amount_usd_bn": "금액(억 달러)", "amount_krw_bn": "금액(억 원)", "form": "형태", "track": "track", "sectors": "분야", "date": "날짜",
                "title": "제목", "us_parties": "미국 측", "kr_parties": "한국 측", "lifecycle": "진행 상태", "is_event": "사건 여부", "summary": "요약"}
    def _lab(field) -> str:
        return FIELD_KO.get(field, _esc(field))
    def _old(v) -> str:   # 기존 판단 값. 비어 있으면 '없음'
        return "없음" if v in (None, "", [], "null") else _esc(", ".join(v) if isinstance(v, list) else v)
    def _new(v, field=None) -> str:   # 모델 판단 값. 그 항목만 비우자는 제안은 '값 삭제 권장', 사건 자체를 빼자는 제안은 '사건 삭제 권장'
        if field == "is_event":
            return "사건 삭제 권장"
        return "값 삭제 권장" if v in (None, "", [], "null") else _esc(", ".join(v) if isinstance(v, list) else v)
    def ev_link(tgt: dict) -> str:   # 기존 사건 → 대시보드 사건 목록의 그 행으로 (a 태그라 Ctrl-클릭·가운데 클릭으로 새 탭)
        if not tgt:
            return "기존: -"
        return f'기존: <a class="ev-link" href="ai_coop.html#{_esc(tgt.get("id"))}" title="대시보드에서 이 사건 보기">{ev_line(tgt)}</a>'
    def _diff_line(d: dict) -> str:   # 한 줄 요약: '형태 확정계약 → MOU·의향', '금액(억 달러) 80.0 → 값 삭제 권장', '사건 삭제 권장'
        if d.get("field") == "is_event":
            return "사건 삭제 권장"
        return f'{_lab(d.get("field"))} {_old(d.get("old"))} → {_new(d.get("new"), d.get("field"))}'
    def card(p: dict, title: str, meta: str, body: str) -> str:
        """한 줄 요약(제목·요지) + 결정 라디오를 항상 보이고, 상세는 '열기' 뒤에 둔다."""
        e = p.get("evidence", {})
        link = f'<a href="{_esc(e.get("url"))}" target="_blank" rel="noopener">원문</a>' if e.get("url") else ""
        pid = _esc(p["id"])
        return (f'<div class="panel rcard" data-id="{pid}"><div class="rhead"><span class="small">{pid}{" · " + link if link else ""}</span>'
                f'<b class="rtitle">{title}</b><span class="small rmeta">{meta}</span></div>'
                f'<div class="decide" data-id="{pid}">'
                f'<label><input type="radio" name="d-{pid}" value="approve"> 승인</label>'
                f'<label><input type="radio" name="d-{pid}" value="reject"> 기각</label>'
                f'<label><input type="radio" name="d-{pid}" value="hold"> 보류</label>'
                f'<label><input type="radio" name="d-{pid}" value="other"> 기타</label>'
                f'<input type="text" class="other-note" data-note="{pid}" placeholder="의견·수정 지시 (예: 금액은 20으로, 형태는 집행, 주체에 기아 추가)" hidden>'
                + (f'<span class="small hold-note">어제 의견: {_esc(p.get("hold_note"))}</span>' if p.get("hold_note") else "") +
                f'<details class="rmore"><summary><span class="btn small"></span></summary>{body}'
                f'<p class="note">원문 발췌({_esc(e.get("via", ""))} · {_esc(e.get("chars", ""))}자): {_esc(str(e.get("excerpt", ""))[:300])}…</p>'
                f'</details></div></div>')
    sections = []
    titles = {"A": "새 사건 후보", "B": "기존 사건 갱신 후보", "C": "기존 판단 재검토"}
    for k in ("A", "B", "C"):
        items = by_task[k]
        cards = []
        for p in items:
            if k == "A":
                ev = p["payload"]
                extra = (f'<p class="small">기존 사건과 중복 가능: {_esc(p.get("possible_duplicate_of"))}</p>' if p.get("possible_duplicate_of") else "") + \
                        (f'<p class="small">기관 목록(reference/ai_coop_orgs.csv)에 없는 표기: {_esc(", ".join(p.get("unknown_orgs", [])))}</p>' if p.get("unknown_orgs") else "")
                more = p.get("extra_sources") or []
                if more:
                    extra += '<p class="small">같은 거래를 다룬 다른 기사 ' + str(len(more)) + '건: ' + " · ".join(
                        f'<a href="{_esc(m.get("url"))}" target="_blank" rel="noopener">{_esc((m.get("title") or "")[:30])}</a>' + (f' ({_esc(m.get("form"))}, {_esc(m.get("confidence"))})' if m.get("form") else '') for m in more) + '</p>'
                if p.get("form_variants"):
                    extra += f'<p class="small">다른 기사의 form 판정: {_esc(", ".join(sorted(set(p["form_variants"]))))}</p>'
                title, meta = _esc(ev.get("title")), ev_line(ev)
                body = (f'<p>미국 측 {_esc(", ".join(disp(x) for x in ev.get("us_parties", [])))} / 한국 측 {_esc(", ".join(disp(x) for x in ev.get("kr_parties", [])))}</p>'
                        f'<p>{_esc(ev.get("summary"))}</p><p class="note">모델 메모: {_esc(ev.get("note"))}</p>{extra}')
            else:  # B 갱신 · C 재검토 — 설명 세 부분(왜 다시 보나 / 기존 ↔ 검색 결과 / 권장 수정안). 2026-10-23
                pl = p["payload"]; tgt = events_by_id.get(p.get("target_id"), {}); ex = p.get("explain") or {}
                if k == "B":
                    title = f'갱신: {_esc(p.get("target_title"))}'
                    what = "후속 사건 추가" if pl.get("new_event") else (f'진행 상태 → {_esc(pl.get("lifecycle"))}' if pl.get("lifecycle") else "필드 갱신")
                    meta = f'{what} · conf {_esc(p.get("confidence"))}'
                else:
                    title = f'재검토: {_esc(p.get("target_title"))}'
                    meta = ""   # 표와 중복이라 비움 (연구자 지시 2026-10-23)
                rec = []
                if pl.get("new_event"):
                    rec.append(f'<p>후속 사건 추가: <b>{_esc(pl["new_event"].get("title"))}</b> — {ev_line(pl["new_event"])}</p>')
                for u in pl.get("updates", []):
                    rec.append(f'<p><b>{_lab(u.get("field"))}</b> 기존 판단 {_old(u.get("old"))} → 모델 판단 {_new(u.get("new"), u.get("field"))}<br><span class="small">{_esc(u.get("evidence"))}</span></p>')
                if pl.get("lifecycle"):
                    rec.append(f'<p>진행 상태: {_esc(tgt.get("lifecycle") or "announced")} → <b>{_esc(pl["lifecycle"])}</b></p>')
                if pl.get("diffs"):
                    rows = "".join(f'<tr><td>{_lab(d.get("field"))}</td><td>{_old(d.get("old"))}</td><td>{_new(d.get("new"), d.get("field"))}</td><td class="small">{_esc(d.get("reason"))}</td></tr>' for d in pl["diffs"])
                    rec.append(f'<table><thead><tr><th>항목</th><th>기존 판단</th><th>모델 판단</th><th>기사 근거</th></tr></thead><tbody>{rows}</tbody></table>')
                if ex:
                    body = (f'<div class="explain"><p><b>1. 왜 다시 보나</b><br>{_esc(ex.get("reason")) or "—"}</p>'
                            f'<p><b>2. 기존 코딩 ↔ 검색 결과</b><br>{ev_link(tgt)}<br>검색: {_esc(ex.get("found")) or "—"}</p>'
                            f'<p><b>3. 권장 수정안</b><br>{_esc(ex.get("recommendation")) or "—"}</p>{"".join(rec)}</div>')
                else:  # 2026-10-23 이전 방식으로 만들어진 제안(설명 세 부분 없음)
                    if pl.get("diffs"):
                        rows = "".join(f'<tr><td>{_lab(d.get("field"))}</td><td>{_old(d.get("old"))}</td><td>{_new(d.get("new"), d.get("field"))}</td></tr>' for d in pl["diffs"])
                        rec = [f'<table><thead><tr><th>항목</th><th>기존 판단</th><th>모델 판단</th></tr></thead><tbody>{rows}</tbody></table>']
                    body = f'<p>{ev_link(tgt)}</p>{"".join(rec)}<p class="note">모델 메모: {_esc(p.get("note"))}</p>'
            cards.append(card(p, title, meta, body))
        toggle = '<button class="btn small open-all" type="button">모두 열기</button>' if cards else ''
        sections.append(f'<section class="section rsec"><div class="wrap"><div class="rsec-head"><span class="eyebrow">{k}. {titles[k]} ({len(items)}건)</span>{toggle}</div>'
                        + ("".join(cards) if cards else '<div class="empty">없음</div>') + '</div></section>')
    howto = ('<div class="wrap howto"><details><summary>제출 방법</summary><p class="note">'
             '카드마다 승인·기각·보류를 고르고, 고칠 내용이 있으면 의견란에 적습니다. "GitHub으로 제출"을 누르면 내용이 채워진 GitHub Issue 화면이 열리고, 거기서 등록 버튼만 누르면 됩니다(GitHub 로그인 필요). '
             '다음 날 06:00 자동 실행이 반영합니다. 승인은 그대로, 의견에 수정 지시가 있으면 고쳐서 반영하고, 기각은 기록만 남깁니다. 선택하지 않은 항목은 이월 및 축적됩니다. '
             '선택은 이 브라우저에 임시 저장됩니다.</p></details></div>')
    submit_bar = ('<div class="submit-bar"><span id="decided-count">선택 0건</span><span class="hint">제출하면 선택이 초기화됩니다</span>'
                  '<span><button class="btn" id="clear-decisions" type="button">초기화</button> '
                  '<button class="btn solid" id="submit-decisions" type="button">GitHub으로 제출</button></span></div>')
    script = """
<script>
(function(){
  const KEY='aicoop-decisions-v1'; const REPO=%s;
  const load=()=>{try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){return {}}};
  const save=d=>{try{localStorage.setItem(KEY,JSON.stringify(d))}catch(e){}};
  let D=load();
  const cards=[...document.querySelectorAll('.decide')];
  const count=()=>{const n=Object.values(D).filter(x=>x.decision).length;document.getElementById('decided-count').textContent='선택 '+n+'건';};
  cards.forEach(c=>{const id=c.dataset.id; const d=D[id]||{};
    const ta=c.querySelector('input.other-note'); const showNote=on=>{ta.hidden=!on; if(on)ta.focus();};
    c.querySelectorAll('input[type=radio]').forEach(r=>{if(d.decision===r.value)r.checked=true; r.addEventListener('change',()=>{D[id]=Object.assign(D[id]||{},{decision:r.value});save(D);count();showNote(r.value==='other'||!!(D[id].note&&D[id].note.trim()));});});
    if(d.note)ta.value=d.note; if(d.decision==='other'||d.note)ta.hidden=false; ta.addEventListener('input',()=>{D[id]=Object.assign(D[id]||{},{note:ta.value});save(D);});
  });
  count();
  document.querySelectorAll('.open-all').forEach(b=>b.addEventListener('click',()=>{const ds=[...b.closest('.rsec').querySelectorAll('details.rmore')];const open=ds.some(d=>!d.open);ds.forEach(d=>d.open=open);b.textContent=open?'모두 닫기':'모두 열기';}));
  const word=x=>x==='other'?'hold':(x||'hold');   // 기타 = 보류 + 의견 (자동 반영 없음, 다음 날 카드에 의견이 남는다)
  const lines=()=>Object.entries(D).filter(([id,d])=>d.decision||(d.note&&d.note.trim())).map(([id,d])=>'- '+id+': '+word(d.decision)+(d.note&&d.note.trim()?' | 의견: '+d.note.trim().replace(/\\s*\\n+\\s*/g,' / '):''));
  document.getElementById('submit-decisions').addEventListener('click',()=>{const L=lines(); if(!L.length){alert('선택된 결정이 없습니다.');return;}
    const today=new Date().toISOString().slice(0,10); const body='## 결정 '+today+'\\n\\n'+L.join('\\n')+'\\n\\n(판단 대기 페이지에서 제출. 다음 자동 실행 때 반영됩니다.)';
    const url='https://github.com/'+REPO+'/issues/new?labels=ai-coop-decision&title='+encodeURIComponent('[결정] '+today)+'&body='+encodeURIComponent(body);
    window.open(url,'_blank'); D={}; save(D); cards.forEach(c=>{c.querySelectorAll('input[type=radio]').forEach(r=>r.checked=false); const t=c.querySelector('input.other-note'); t.value=''; t.hidden=true;}); count();});
  document.getElementById('clear-decisions').addEventListener('click',()=>{D={};save(D);cards.forEach(c=>{c.querySelectorAll('input[type=radio]').forEach(r=>r.checked=false);const t=c.querySelector('input.other-note'); t.value=''; t.hidden=true;});count();});
})();
</script>""" % json.dumps(REPO)
    body = howto + "".join(sections) + submit_bar + script
    head = '<!doctype html>\n<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">\n<title>판단 대기 · SKL</title><link rel="stylesheet" href="site.css"></head>\n'
    hero = ('<header class="hero"><div class="wrap"><span class="eyebrow">Panel 2 · AI Cooperation</span><div class="hero-row"><h1>한미 AI 협력 트래커</h1>' + subnav("review.html") + '</div>'
            + hero_meta + '</div></header>'
            + with_last_update("</header>", built[:10])[len("</header>"):] + '\n')
    return head + "<body>" + nav("review.html") + "\n" + hero + body + "\n" + footer("", built) + "\n</body></html>"


def build(out: Path) -> bool:
    events, meta = load_events()
    agg = aggregate(events)
    (out / "ai_coop.json").write_text(json.dumps({"as_of": meta["as_of"], "n": agg["n"], "events": events, "agg": agg, "orgs": load_orgs()},
                                                 ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    (out / "ai_coop.html").write_text(render(agg, {"fetched_at": meta["as_of"]}), encoding="utf-8")
    props = pending_proposals()
    raw_by_id = {e["id"]: e for e in json.loads(EVENTS.read_text(encoding="utf-8")).get("events", [])} if EVENTS.is_file() else {}
    (out / "review.html").write_text(render_review(props, raw_by_id), encoding="utf-8")   # 원 레코드(track·sectors) 기준
    (out / "review.json").write_text(json.dumps({"pending": len(props), "by_task": {k: sum(1 for p in props if p["task"] == k) for k in "ABC"}}, ensure_ascii=False), encoding="utf-8")
    print(f"[ai_coop_site] 사건 {agg['n']}건 (확정 {agg['status'].get('confirmed', 0)}, 자동 {agg['status'].get('auto', 0)})")
    return agg["n"] > 0


if __name__ == "__main__":
    print(__doc__)
