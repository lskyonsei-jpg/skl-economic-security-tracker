"""한미 AI 협력 트래커 — 사건 수집·코딩. 설계: 문서/20261022_설계_한미AI협력트래커_자동화.md

  python collect_ai_coop.py seed                       data/seed/*.csv -> data/ai_coop_events.json (연구자 확정 코딩)
  python collect_ai_coop.py recode [--effort high] [--limit N]
                                                       표본 사건의 원문을 다시 받아 Task A 로 코딩하고 연구자 코딩과 대조
  (예정) discover / run                                 신규 기사 탐지 -> Task A/B -> 병합 -> 게시

모델: claude-opus-5-5 (연구자 확정 2026-10-22). 구조화 출력(output_config.format)으로 스키마를 강제한다.
키:   환경변수 ANTHROPIC_API_KEY (GitHub Secrets). 로컬에는 없으므로 recode 는 CI 에서 돈다.
비용 안전장치: 한 번 실행에 MAX_CALLS 회 이상 호출하지 않는다.

유료벽 3단계(연구자 결정 2026-10-22): 원문 본문 → 같은 사건의 다른 무료 출처(보도자료·정부 문서 우선) → 제목만(확신도 상한 0.5).
재현성: 코딩에 쓴 입력 원문을 그대로 기록한다(ai_coop_*_inputs.jsonl, 실행 아티팩트). 공개 결과에는 URL·수집 경로·길이·SHA-256·앞 500자.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
SEED_DIR = DATA / "seed"
EVENTS = DATA / "ai_coop_events.json"
MODEL = "claude-opus-5-5"
MAX_CALLS = int(os.environ.get("AI_COOP_MAX_CALLS", "120"))

FORMS = ["MOU·의향", "선언", "집행", "확정계약"]
TRACKS = ["정부", "민간", "정부-민간"]
SECTORS = ["AI데이터센터", "피지컬AI·로봇", "통상·규제", "파운드리", "반도체·메모리", "AI모델·SW", "안보·국방", "전력·인프라", "인재"]
ADMINISTRATIONS = [("2025-01-20", "트럼프 2기"), ("2021-01-20", "바이든"), ("2017-01-20", "트럼프 1기"), ("2009-01-20", "오바마")]
# 시스템 프롬프트 예시로 쓰는 표본 사건(연구자 확정). 정확도 측정에서는 제외한다.
EXAMPLE_TITLES = [
    "삼성전자–테슬라 AI 칩 파운드리 계약(165억 달러)",
    "현대차그룹–엔비디아 전략적 파트너십(CES 2025)",
    "현대차·기아–엔비디아 자율주행 파트너십 확대",
    "삼성 테일러 팭, 테슬라 칩 2027년 하반기 양산 계획",
    "삼성전자–구글 클라우드 생성AI 파트너십(갤럭시 S24)",
    "한미 정상 공동성명(윤석열-바이든) — AI·반도체·자율로봇 협력 명시",
    "한미 차세대 핵심·신흥기술 대화(NCET) 출범",
    "AWS, 한국에 2027년까지 59억 달러 추가 투자 발표",
    "미국 CHIPS and Science Act 서명(삼성·SK 영향)",
    "과기정통부·현대차그룹–엔비디아 피지컬 AI MOU",
]


def administration(date: str) -> str:
    for start, name in ADMINISTRATIONS:
        if date >= start:
            return name
    return "이전"


def split_parties(v) -> list[str]:
    if v is None or (isinstance(v, float)) or str(v).strip() in ("", "nan"):
        return []
    return [p.strip() for p in str(v).split(",") if p.strip()]


# ------------------------------------------------------------------ seed


def load_seed_rows() -> list[dict]:
    rows = []
    for path in sorted(SEED_DIR.glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            rows += list(csv.DictReader(fh))
    return rows


def seed_to_events(rows: list[dict]) -> list[dict]:
    events = []
    for r in rows:
        amount = r.get("규모(억 달러)", "").strip()
        events.append({
            "id": r["id"], "date": r["일자"],
            "us_parties": split_parties(r["미국 주체"]), "kr_parties": split_parties(r["한국 주체"]),
            "track": r["트랙"].strip(), "form": r["형태"].strip(), "sectors": split_parties(r["분야"]),
            "title": r["내용"].strip(), "summary": "", "note": r.get("비고", "").strip(),
            "amount_usd_bn": float(amount) if amount else None, "amount_is_estimate": False,
            "sources": [{"url": r["원문 링크"].strip(), "grade": None}] if r.get("원문 링크", "").strip() else [],
            "administration": administration(r["일자"]),
            "status": "confirmed", "lifecycle": "announced", "confidence": 1.0,
            "coded_by": "researcher", "coded_at": "2026-10-22", "model": None,
            "prior_event_id": None, "updates": [],
        })
    events.sort(key=lambda e: (e["date"], e["title"]))
    return events


def cmd_seed() -> int:
    rows = load_seed_rows()
    events = seed_to_events(rows)
    DATA.mkdir(exist_ok=True)
    EVENTS.write_text(json.dumps({"as_of": datetime.now(timezone.utc).isoformat(), "events": events},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[seed] {len(events)}건 -> {EVENTS.relative_to(HERE)}")
    return 0


# ------------------------------------------------------------------ Task A 프롬프트


SYSTEM_RULES = """당신은 한미 AI 협력 사건 데이터베이스의 코딩 보조자다. 기사 한 건을 읽고 스키마에 맞는 사건 하나를 추출한다. 기사에 없는 사실을 만들지 않는다.

[사건의 정의]
미국 측 주체와 한국 측 주체가 모두 명시된, AI·반도체·데이터센터·로봇·AI 규제 관련 협력 또는 거래. 한쪽만 있으면 is_event=false. 미국 국내법·정책이 한국 기업에 영향을 주는 것(예: CHIPS Act)은 양측 주체가 있어도 track=정부, form=선언, sectors 에 통상·규제를 넣는다.

[form 판정 — 기사 문면의 구속력 기준]
- 확정계약: 계약 체결·지분 취득·인수 완료·공급계약 서명이 명시. 금액이나 지분율이 있으면 강한 근거.
- 집행: 이미 체결된 계약·협약의 이행 사실(양산 개시, 제품 출시, 인수 완료 후 통합, 공급 진행). 선행 사건이 있으면 prior_event_hint 에 적는다.
- MOU·의향: 파트너십·협력 발표이나 계약 조건이 비공개이거나 "본계약은 별도 체결" 문구가 있는 것. LOI, 양해각서, 투자 의향.
- 선언: 정부 공동성명·팩트시트·회담·정상회의·협의체 출범·투자 발표(기업이 금액만 밝히고 계약 상대가 없는 투자 계획 포함).
판정이 두 범주 사이면 더 약한 쪽(선언 < MOU·의향 < 집행 < 확정계약)을 고르고 confidence 를 낮춘다.

[track] 정부 / 민간 / 정부-민간. 정부 기관이 당사자로 서명·발표하면 정부. 정부와 기업이 함께 당사자면 정부-민간.
[sectors] AI데이터센터, 피지컬AI·로봇, 통상·규제, 파운드리, 반도체·메모리, AI모델·SW, 안보·국방, 전력·인프라, 인재. 복수 가능. 기사에 근거가 있는 것만.
[parties] 기관명은 기사 표기 그대로. 정부는 "정부(미국)", "정부(한국)" 또는 부처명(과기정통부, 백악관 등). 그룹 계열사는 기사에 나온 법인만. 한국 측 주체가 미국 법인의 자회사인 경우도 한국 측으로 둔다.
[amount_usd_bn] 억 달러 단위 숫자. 기사에 달러 금액이 명시된 경우만. 원화만 있으면 amount_krw_bn 에 억 원으로 적고 달러 환산은 하지 않는다. "수십억", "최대" 같은 범위면 null 로 두고 note 에 적는다.
[date] 발표일(YYYY-MM-DD). 기사 게재일과 다르면 발표일.
[title] 20자 안팎, "주체–주체, 내용(금액)" 형식. [summary] 2~3문장, 기사 사실만.
[confidence] 0~1. form 판정과 주체 식별이 모두 분명하면 0.9 이상, 어느 하나가 기사 문면으로 확정되지 않으면 0.6 이하.
[source_grade] 기사가 정부·기업의 1차 발표(보도자료·공시·공식 뉴스룸)면 1, 언론 보도면 2.

[예시] 아래는 연구자가 확정한 코딩이다. 같은 기준을 적용한다. 각 예시의 '기사 요지'는 연구자 메모이며, 실제 입력은 기사 본문이다.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "is_event": {"type": "boolean"},
        "date": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "YYYY-MM-DD"},
        "us_parties": {"type": "array", "items": {"type": "string"}},
        "kr_parties": {"type": "array", "items": {"type": "string"}},
        "track": {"anyOf": [{"type": "string", "enum": TRACKS}, {"type": "null"}]},
        "form": {"anyOf": [{"type": "string", "enum": FORMS}, {"type": "null"}]},
        "sectors": {"type": "array", "items": {"type": "string", "enum": SECTORS}},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "amount_usd_bn": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "amount_is_estimate": {"type": "boolean"},
        "amount_krw_bn": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "source_grade": {"type": "integer", "enum": [1, 2]},
        "prior_event_hint": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["is_event", "date", "us_parties", "kr_parties", "track", "form", "sectors", "title", "summary",
                 "amount_usd_bn", "amount_is_estimate", "amount_krw_bn", "source_grade", "prior_event_hint",
                 "confidence", "note"],
    "additionalProperties": False,
}


def build_system(events: list[dict]) -> str:
    by_title = {e["title"]: e for e in events}
    parts = [SYSTEM_RULES]
    for i, title in enumerate(EXAMPLE_TITLES, 1):
        e = by_title.get(title)
        if not e:
            continue
        answer = {"is_event": True, "date": e["date"], "us_parties": e["us_parties"], "kr_parties": e["kr_parties"],
                  "track": e["track"], "form": e["form"], "sectors": e["sectors"], "title": e["title"],
                  "amount_usd_bn": e["amount_usd_bn"]}
        parts.append(f"예시 {i}. 기사 요지: {e['note'][:400]}\n정답: {json.dumps(answer, ensure_ascii=False)}\n")
    return "\n".join(parts)


def code_article(client, system: str, meta: dict, body: str, effort: str, kind: str = "body") -> tuple[dict, dict]:
    """기사 하나를 Task A 로 코딩한다. (결과, usage). kind='title' 이면 제목만 있는 입력이다."""
    if kind == "title":
        user = (f"[입력 수준] 제목(과 짧은 요약)만 있다. 본문을 확보하지 못했다. 본문 없이 확정할 수 없는 필드는 null 로 두고 "
                f"confidence 는 0.5 를 넘기지 않는다.\nURL: {meta.get('url', '')}\n\n[제목·요약]\n{body}")
    else:
        user = (f"[기사 메타]\nURL: {meta.get('url', '')}\n매체/도메인: {meta.get('domain', '')}\n게재일(참고): {meta.get('published', '')}\n"
                f"제목: {meta.get('title', '')}\n\n[본문]\n{body}")
    response = client.messages.create(
        model=MODEL, max_tokens=4000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    usage = {"input": response.usage.input_tokens, "output": response.usage.output_tokens,
             "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0}
    if response.stop_reason == "refusal":
        return {"is_event": False, "note": "refusal", "refusal": True}, usage
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), usage


# ------------------------------------------------------------------ 본문 수집


UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0.0.0 Safari/537.36")


def _extract(html_text: str, url: str) -> tuple[str, dict]:
    import trafilatura
    text = trafilatura.extract(html_text, include_comments=False, favor_recall=True, url=url) or ""
    meta = trafilatura.extract_metadata(html_text, default_url=url)
    domain = re.sub(r"^https?://([^/]+).*$", lambda m: m.group(1), url)
    info = {"title": getattr(meta, "title", "") or "", "published": getattr(meta, "date", "") or "",
            "domain": getattr(meta, "sitename", "") or domain}
    return text.strip(), info


def fetch_body(url: str) -> tuple[str, dict]:
    """본문 추출. 1) 브라우저 UA 직접 요청, 2) 실패·차단·짧음이면 Wayback Machine 스냅숏.
    어느 쪽을 썼는지 info['via'] 에 남긴다. 원문은 저장하지 않는다."""
    import requests
    best, best_info = "", {}
    try:
        r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "ko,en;q=0.8"}, timeout=30)
        if r.status_code == 200 and r.text:
            best, best_info = _extract(r.text, url); best_info["via"] = "direct"
    except requests.RequestException:
        pass
    if len(best) >= 300:
        return best, best_info
    try:
        avail = requests.get("https://archive.org/wayback/available", params={"url": url}, timeout=30).json()
        snap = (avail.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available") and snap.get("url"):
            r = requests.get(snap["url"], headers={"User-Agent": UA}, timeout=60)
            if r.status_code == 200:
                text, info = _extract(r.text, url); info["via"] = f"wayback:{snap.get('timestamp', '')[:8]}"
                if len(text) > len(best):
                    best, best_info = text, info
    except (requests.RequestException, ValueError):
        pass
    return best, best_info


PAYWALL_DOMAINS = ("wsj.com", "ft.com", "bloomberg.com", "nytimes.com", "economist.com", "reuters.com", "nikkei.com")
GRADE1_HINTS = ("newsroom", "news.", "press", "pr.", ".gov", ".go.kr", "korea.kr", "whitehouse", "investors.", "ir.", "semiconductor.samsung", "nvidianews")


def _decode_gnews(link: str) -> str | None:
    """Google News RSS 의 리다이렉트 링크 -> 실제 기사 URL. 옛 형식은 base64 안에 URL, 새 형식은 batchexecute."""
    import base64
    import requests
    m = re.search(r"/articles/([^?/]+)", link)
    if not m:
        return link if "news.google.com" not in link else None
    tok = m.group(1)
    try:
        raw = base64.urlsafe_b64decode(tok + "=" * (-len(tok) % 4))
        u = re.search(rb"https?://[^\x00-\x1f\x7f\"'<> ]+", raw)
        if u:
            return u.group(0).decode("utf-8", "ignore")
    except Exception:
        pass
    try:
        page = requests.get(link, headers={"User-Agent": UA}, timeout=30).text
        sig = re.search(r'data-n-a-sg="([^"]+)"', page)
        ts = re.search(r'data-n-a-ts="([^"]+)"', page)
        if not (sig and ts):
            return None
        req = (f'["garturlreq",[["ko","KR",["FINANCE_TOP_INDICES","WEB_TEST_1_0_0"],null,null,1,1,"KR:ko",null,180,'
               f'null,null,null,null,null,0,null,null,[1608992183,723341000]],"ko","KR",1,[2,3,4,8],1,0,"655000234",0,0,null,0],'
               f'"{tok}",{ts.group(1)},"{sig.group(1)}"]')
        resp = requests.post("https://news.google.com/_/DotsSplashUi/data/batchexecute",
                             data={"f.req": json.dumps([[["Fbv4je", req, None, "generic"]]])},
                             headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                             timeout=30).text
        for line in resp.splitlines():
            if line.startswith("[["):
                data = json.loads(line)
                inner = json.loads(data[0][2])
                return inner[1]
    except Exception:
        return None
    return None


def search_alternatives(query: str, date: str | None, window_days: int = 21, limit: int = 8) -> list[dict]:
    """같은 사건을 다룬 다른 기사 후보. Google News RSS(날짜 필터 가능) + Bing News RSS(직접 링크, 날짜는 사후 필터)."""
    import datetime as dt
    import feedparser
    import requests
    out, seen = [], set()
    q = re.sub(r"[\"'()\[\]–—·,]", " ", query)
    lo = hi = None
    if date:
        d = dt.date.fromisoformat(date[:10])
        lo, hi = d - dt.timedelta(days=window_days), d + dt.timedelta(days=window_days)
    try:
        gq = q + (f" after:{lo.isoformat()} before:{hi.isoformat()}" if date else "")
        r = requests.get("https://news.google.com/rss/search", params={"q": gq, "hl": "ko", "gl": "KR", "ceid": "KR:ko"},
                         headers={"User-Agent": UA}, timeout=30)
        for e in feedparser.parse(r.text).entries[:limit]:
            out.append({"engine": "google", "link": e.get("link", ""), "title": e.get("title", ""), "published": e.get("published", "")})
    except requests.RequestException:
        pass
    try:
        r = requests.get("https://www.bing.com/news/search", params={"q": q, "format": "rss"}, headers={"User-Agent": UA}, timeout=30)
        for e in feedparser.parse(r.text).entries[:limit]:
            pub = e.get("published_parsed")
            if date and pub:
                pd = dt.date(*pub[:3])
                if not (lo <= pd <= hi):
                    continue
            out.append({"engine": "bing", "link": e.get("link", ""), "title": e.get("title", ""), "published": e.get("published", "")})
    except requests.RequestException:
        pass
    uniq = []
    for c in out:
        if c["link"] and c["link"] not in seen:
            seen.add(c["link"])
            uniq.append(c)
    return uniq


def resolve_input(title: str, date: str | None, source_url: str | None, rss_summary: str = "") -> dict:
    """유료벽 3단계(연구자 결정 2026-10-22).
    1) 원문 URL 본문  2) 같은 사건의 다른 무료 출처(보도자료·정부 문서 우선)  3) 제목(+RSS 요약)만, 확신도 상한 0.5.
    돌려주는 dict 에 코딩에 쓴 원문(text)을 그대로 담는다 — 재현성."""
    import hashlib as _h
    tried = []

    def pack(kind, url, via, text, extra=None):
        rec = {"kind": kind, "url": url, "via": via, "chars": len(text), "sha256": _h.sha256(text.encode("utf-8")).hexdigest(),
               "text": text, "tried": tried}
        if extra:
            rec.update(extra)
        return rec

    if source_url:
        body, meta = fetch_body(source_url)
        tried.append({"step": 1, "url": source_url, "chars": len(body)})
        if len(body) >= 300:
            return pack("body", source_url, meta.get("via", "direct"), body, {"meta": meta})
    cands = search_alternatives(title, date) if title else []
    picked = []
    for c in cands[:8]:
        real = _decode_gnews(c["link"]) if c["engine"] == "google" else c["link"]
        if not real or any(d in real for d in PAYWALL_DOMAINS) or real == source_url:
            continue
        body, meta = fetch_body(real)
        tried.append({"step": 2, "url": real, "chars": len(body), "title": c.get("title", "")})
        if len(body) >= 300:
            grade1 = any(h in real for h in GRADE1_HINTS)
            picked.append((0 if grade1 else 1, -len(body), real, body, meta))
            if grade1:
                break
    if picked:
        picked.sort()
        _, _, real, body, meta = picked[0]
        return pack("body", real, "alternative:" + meta.get("via", "direct"), body, {"meta": meta, "alternative_of": source_url})
    text = title + ("\n\n" + rss_summary if rss_summary else "")
    return pack("title", source_url, "none", text, {"body_missing": True})


def clip(body: str, head: int = 6000, tail: int = 2000) -> str:
    # 토큰이 아니라 글자 기준의 느슨한 상한(한글 1자 ≈ 1~2토큰). 8천 자를 넘으면 앞·뒤만 남긴다.
    return body if len(body) <= head + tail else body[:head] + "\n...(중략)...\n" + body[-tail:]


# ------------------------------------------------------------------ recode


def norm(s: str) -> str:
    return re.sub(r"[\s·\-–()（）]", "", s).lower()


def jaccard(a: list[str], b: list[str]) -> float:
    A, B = {norm(x) for x in a}, {norm(x) for x in b}
    return len(A & B) / len(A | B) if A | B else 1.0


def cmd_recode(effort: str, limit: int | None) -> int:
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[recode] ANTHROPIC_API_KEY 없음"); return 1
    if not EVENTS.is_file():
        cmd_seed()
    events = json.loads(EVENTS.read_text(encoding="utf-8"))["events"]
    system = build_system(events)
    client = anthropic.Anthropic()
    out_path = DATA / f"ai_coop_recode_{effort}.json"
    results, calls, usage_total = [], 0, {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    started = time.monotonic()
    targets = [e for e in events if e["sources"]][: (limit or None)]
    inputs_path = DATA / f"ai_coop_recode_inputs_{effort}.jsonl"
    inputs_fh = inputs_path.open("w", encoding="utf-8")
    for e in targets:
        url = e["sources"][0]["url"]
        inp = resolve_input(e["title"], e["date"], url)
        rec = {"id": e["id"], "title": e["title"], "url": url, "in_examples": e["title"] in EXAMPLE_TITLES,
               "truth": {"form": e["form"], "track": e["track"], "sectors": e["sectors"],
                         "us": e["us_parties"], "kr": e["kr_parties"], "amount": e["amount_usd_bn"], "date": e["date"]},
               "input": {k: v for k, v in inp.items() if k not in ("text", "meta")} | {"excerpt": inp["text"][:500]}}
        inputs_fh.write(json.dumps({"id": e["id"], "kind": inp["kind"], "url": inp["url"], "via": inp["via"],
                                    "sha256": inp["sha256"], "text": inp["text"]}, ensure_ascii=False) + "\n")
        if calls >= MAX_CALLS:
            rec["fetch"] = "skipped_max_calls"; results.append(rec); continue
        meta = dict(inp.get("meta") or {}); meta["url"] = inp["url"] or url
        try:
            pred, usage = code_article(client, system, meta, clip(inp["text"]), effort, kind=inp["kind"])
        except anthropic.APIStatusError as exc:
            rec["fetch"] = "ok"; rec["error"] = f"{exc.status_code} {exc.message}"; results.append(rec)
            print(f"  [API 오류] {exc.status_code} {str(exc.message)[:160]}")
            if exc.status_code == 400 and sum(1 for x in results if str(x.get("error", "")).startswith("400")) >= 3:
                print("  400 오류 3회 — 요청 형식 문제로 보고 중단"); break
            continue
        calls += 1
        for k in usage_total:
            usage_total[k] += usage[k]
        if inp["kind"] == "title" and isinstance(pred.get("confidence"), (int, float)):
            pred["confidence"] = min(pred["confidence"], 0.5)
        rec["fetch"] = inp["kind"]; rec["pred"] = pred
        rec["match"] = {
            "is_event": bool(pred.get("is_event")),
            "form": pred.get("form") == e["form"], "track": pred.get("track") == e["track"],
            "sectors_jaccard": round(jaccard(pred.get("sectors", []), e["sectors"]), 2),
            "us_jaccard": round(jaccard(pred.get("us_parties", []), e["us_parties"]), 2),
            "kr_jaccard": round(jaccard(pred.get("kr_parties", []), e["kr_parties"]), 2),
            "amount": (pred.get("amount_usd_bn") == e["amount_usd_bn"]),
            "date": pred.get("date") == e["date"],
        }
        results.append(rec)
        m = rec["match"]
        print(f"  {e['date']} {e['title'][:30]:<30} [{inp['kind']:<5} {inp['via'][:14]:<14}] form {'O' if m['form'] else 'X'}({pred.get('form')}) "
              f"track {'O' if m['track'] else 'X'} sec {m['sectors_jaccard']} us {m['us_jaccard']} kr {m['kr_jaccard']} amt {'O' if m['amount'] else 'X'} conf {pred.get('confidence')}")
        time.sleep(0.5)
    inputs_fh.close()

    coded = [r for r in results if "match" in r]
    held = [r for r in coded if not r["in_examples"]]
    def rate(rs, key): return (sum(1 for r in rs if r["match"][key] is True) / len(rs)) if rs else None
    def mean(rs, key): return (sum(r["match"][key] for r in rs) / len(rs)) if rs else None
    summary = {
        "effort": effort, "model": MODEL, "targets": len(targets), "fetched": len(coded),
        "input_kinds": {k: sum(1 for r in results if r.get("fetch") == k) for k in ("body", "title")},
        "errors": sum(1 for r in results if "error" in r), "calls": calls, "usage": usage_total,
        "cost_usd": round(usage_total["input"] * 4 / 1e6 + usage_total["output"] * 20 / 1e6
                          + usage_total["cache_read"] * 0.2 / 1e6 + usage_total["cache_write"] * 5 / 1e6, 3),
        "seconds": round(time.monotonic() - started),
        "heldout_n": len(held),
        "heldout_by_kind": {k: {"n": sum(1 for r in held if r["fetch"] == k),
                                "form": rate([r for r in held if r["fetch"] == k], "form")} for k in ("body", "title")},
        "heldout": {"form": rate(held, "form"), "track": rate(held, "track"), "sectors_jaccard": mean(held, "sectors_jaccard"),
                    "us_jaccard": mean(held, "us_jaccard"), "kr_jaccard": mean(held, "kr_jaccard"), "amount": rate(held, "amount"),
                    "date": rate(held, "date"), "is_event": rate(held, "is_event")},
        "examples_n": len(coded) - len(held),
        "examples": {"form": rate([r for r in coded if r["in_examples"]], "form")},
    }
    out_path.write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        h = summary["heldout"]
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## 한미 AI 협력 — 표본 재코딩 ({effort})\n\n"
                     f"- 대상 {summary['targets']}건, 코딩 {summary['fetched']}건(본문 {summary['input_kinds']['body']} · 제목만 {summary['input_kinds']['title']}), 호출 {calls}회, 비용 ${summary['cost_usd']}\n"
                     f"- 입력 종류별 form 일치율(보류 표본): {summary['heldout_by_kind']}\n"
                     f"- 보류 표본(예시 제외) {summary['heldout_n']}건 일치율: form {h['form']}, track {h['track']}, sectors J {h['sectors_jaccard']}, "
                     f"미국 주체 J {h['us_jaccard']}, 한국 주체 J {h['kr_jaccard']}, 금액 {h['amount']}, 날짜 {h['date']}\n\n"
                     "| 날짜 | 사건 | 입력 | form 정답 | form 예측 | track | sectors J | conf |\n|---|---|---|---|---|---|---|---|\n")
            for r in coded:
                m, p = r["match"], r["pred"]
                fh.write(f"| {r['truth']['date']} | {r['title'][:40]}{' (예시)' if r['in_examples'] else ''} | {r['fetch']}/{r['input']['via'][:12]} | {r['truth']['form']} | {p.get('form')} | "
                         f"{'O' if m['track'] else 'X'} | {m['sectors_jaccard']} | {p.get('confidence')} |\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    r = sub.add_parser("recode"); r.add_argument("--effort", default="high", choices=["low", "medium", "high"]); r.add_argument("--limit", type=int)
    a = p.parse_args()
    if a.cmd == "seed":
        return cmd_seed()
    return cmd_recode(a.effort, a.limit)


if __name__ == "__main__":
    sys.exit(main())
