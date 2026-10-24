"""한미 AI 협력 트래커 — 사건 수집·코딩. 설계: 문서/20261022_설계_한미AI협력트래커_자동화.md

  python collect_ai_coop.py seed    data/seed/*.csv -> data/ai_coop_events.json (연구자 확정 코딩; 사건 파일이 없을 때의 부트스트랩)
  그 밖에는 ai_coop_tasks.py 가 라이브러리로 쓴다(프롬프트·스키마·본문 확보·기관 표기·track).

모델: claude-opus-5-5, effort medium (연구자 확정 2026-10-22, 비교 실험 없이 medium 으로). 구조화 출력(output_config.format)으로 스키마를 강제한다.
프롬프트 v2(2026-10-22): form 은 문서의 법적 성격 기준, track 은 정부-정부/정부-민간/민간-민간, 금액은 거래금액만,
기사 하나에 사건 여러 개(events 배열), 기관 표기는 reference/ai_coop_orgs.csv 의 표준 표기.
키:   환경변수 ANTHROPIC_API_KEY (GitHub Secrets). 비용 상한은 ai_coop_tasks.MAX_DAILY_CALLS.

유료벽 3단계(연구자 결정 2026-10-22): 원문 본문 → 같은 사건의 다른 무료 출처(보도자료·정부 문서 우선) → 제목만(확신도 상한 0.5).
재현성: 제안마다 입력 원문의 URL·수집 경로·길이·SHA-256·앞 500자를 기록한다.
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

FORMS = ["MOU·의향", "선언", "집행", "확정계약"]
TRACKS = ["정부-정부", "정부-민간", "민간-민간"]
ORGS = HERE / "reference" / "ai_coop_orgs.csv"
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


def norm(s: str) -> str:
    return re.sub(r"[\s·\-–()（）]", "", s).lower()


def administration(date: str) -> str:
    for start, name in ADMINISTRATIONS:
        if date >= start:
            return name
    return "이전"


def split_parties(v) -> list[str]:
    if v is None or (isinstance(v, float)) or str(v).strip() in ("", "nan"):
        return []
    return [p.strip() for p in str(v).split(",") if p.strip()]


def load_orgs() -> dict:
    """reference/ai_coop_orgs.csv -> {alias_norm: {canonical, country, type}}."""
    table = {}
    with ORGS.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            entry = {"canonical": r["canonical"], "country": r["country"], "type": r["type"]}
            for name in [r["canonical"]] + [a for a in r["aliases"].split("|") if a]:
                table[norm(name)] = entry
    return table


_ORGS: dict | None = None


def org_lookup(name: str) -> dict | None:
    global _ORGS
    if _ORGS is None:
        _ORGS = load_orgs()
    return _ORGS.get(norm(name))


def canonical_parties(names: list[str]) -> tuple[list[str], list[str]]:
    """표기 정규화. (정규화된 목록, 마스터에 없는 이름 목록)"""
    out, unknown = [], []
    for n in names:
        hit = org_lookup(n)
        if hit:
            if hit["canonical"] not in out:
                out.append(hit["canonical"])
        else:
            unknown.append(n)
            if n not in out:
                out.append(n)
    return out, unknown


def side_type(names: list[str]) -> str | None:
    """한쪽 주체 묶음의 성격: 정부 / 민간 / 혼합 / None(미상)."""
    kinds = set()
    for n in names:
        hit = org_lookup(n)
        kinds.add(hit["type"] if hit else ("정부" if re.search(r"정부|부처|청와대|백악관|상무부|국무부|대통령|육군|해군|공군|국방|NSF|Commerce|Department", n) else "민간"))
    if not kinds:
        return None
    if kinds == {"정부"}:
        return "정부"
    if kinds == {"민간"}:
        return "민간"
    return "혼합"


def derive_track(us: list[str], kr: list[str]) -> str | None:
    """연구자 결정 2026-10-22: 정부-정부 / 정부-민간 / 민간-민간. 양쪽이 모두 정부면 정부-정부,
    모두 민간이면 민간-민간, 그 외(한쪽만 정부이거나 한쪽에 정부·민간이 섞임)는 정부-민간."""
    a, b = side_type(us), side_type(kr)
    if a is None or b is None:
        return None
    if a == b == "정부":
        return "정부-정부"
    if a == b == "민간":
        return "민간-민간"
    return "정부-민간"


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
            "track": derive_track(split_parties(r["미국 주체"]), split_parties(r["한국 주체"])) or "정부-민간",
            "track_original": r["트랙"].strip(), "form": r["형태"].strip(), "sectors": split_parties(r["분야"]),
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


SYSTEM_RULES = """당신은 한미 AI 협력 사건 데이터베이스의 코딩 보조자다. 기사 한 건을 읽고 스키마에 맞는 사건을 추출한다. 기사에 없는 사실을 만들지 않는다.

[사건의 정의]
미국 측 주체와 한국 측 주체가 모두 명시된, AI·반도체·데이터센터·로봇·자율주행·전장(차량 AI)·AI 규제 관련 협력 또는 거래. 한쪽만 있으면 사건이 아니다(events 를 빈 배열로). 미국 국내법·정책이 한국 기업에 영향을 주는 것(예: CHIPS Act)은 양측 주체가 있어도 form=선언, sectors 에 통상·규제를 넣는다.

[기사 하나에 사건 여러 개]
정상회담·서밋·패키지 발표처럼 한 기사가 여러 거래를 묶어 보도하면, 거래마다 사건 하나씩 events 배열에 넣는다(예: 정부 공동선언 1건 + 삼성–브로드컴 MOU 1건 + SK–엔비디아 협력 1건). 각 사건의 parties 에는 그 거래의 당사자만 넣고 기사에 등장한 다른 기관을 섞지 않는다. 묶음 전체를 하나의 우산 사건으로 만들지 않는다.

[form 판정 — 문서의 법적 성격 기준 (연구자 결정 2026-10-22)]
- 확정계약: 구속력 있는 문서가 명시된 것. 계약 체결, 인수 계약, 지분 취득·투자 집행, 합작법인 설립, 장기 공급계약, 라이선스 계약, 본계약 서명, 파트너십 "협약(agreement) 체결". 금액이 없어도 인정한다.
- MOU·의향: 비구속 문서(MOU·LOI·업무협약·양해각서·기본합의)이거나, "파트너십 발표·협력하기로·선정" 처럼 문서 종류가 특정되지 않은 협력 발표.
- 집행: 앞선 구속력 거래의 이행·완료. 인수 완료, 지분 취득 완료, 양산 개시, 제품 출시, 공급 개시, 설비 착공. 기사가 그 거래의 첫 보도라도 "완료"면 집행이다. prior_event_hint 에 선행 거래를 적는다.
- 선언: 정부 공동성명·팩트시트·회담·정상회의·협의체 출범, 기업의 투자 계획 발표(계약 상대가 없는 것).
문면으로 가릴 수 없으면 더 약한 쪽(선언 < MOU·의향 < 집행 < 확정계약)을 고르고 confidence 를 낮춘다.

[track — 양측 당사자의 성격 (연구자 결정 2026-10-22)]
정부-정부(양쪽 모두 정부·공공기관) / 민간-민간(양쪽 모두 기업·민간) / 정부-민간(한쪽만 정부이거나 한쪽에 정부와 기업이 함께). 당사자만 보고 판정하며, 행사 주최·참석은 당사자가 아니다.

[sectors] AI데이터센터, 피지컬AI·로봇, 통상·규제, 파운드리, 반도체·메모리, AI모델·SW, 안보·국방, 전력·인프라, 인재. 복수 가능. 기사에 근거가 있는 것만.
[parties] 아래 [기관 표기] 목록의 표준 표기를 쓴다. 목록에 없으면 기사 표기 그대로. 정부는 "정부(미국)", "정부(한국)" 또는 부처명. 그룹은 기사에 나온 법인만(현대차그룹이면 명시된 계열사; 없으면 현대차).
[amount_usd_bn] 거래금액만, 억 달러 숫자. 기업가치·시가총액·패키지 총액·투자 계획 총액은 금액이 아니라 note 에 적는다(연구자 결정 2026-10-22). 원화만 있으면 amount_krw_bn 에 억 원. 범위("수십억", "최대")면 null 로 두고 note 에 적는다.
[date] 발표일(YYYY-MM-DD). 기사 게재일과 다르면 발표일.
[title] 20자 안팎, "주체–주체, 내용(금액)" 형식. [summary] 2~3문장, 기사 사실만.
[confidence] 0~1. form 판정과 주체 식별이 모두 분명하면 0.9 이상, 어느 하나가 기사 문면으로 확정되지 않으면 0.6 이하.
[source_grade] 기사가 정부·기업의 1차 발표(보도자료·공시·공식 뉴스룸)면 1, 언론 보도면 2.

[기관 표기]
{orgs}

[예시] 아래는 연구자가 확정한 코딩이다. 같은 기준을 적용한다. 각 예시의 '기사 요지'는 연구자 메모이며, 실제 입력은 기사 본문이다.
"""

EVENT_SCHEMA = {
    "type": "object",
    "properties": {
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
    "required": ["date", "us_parties", "kr_parties", "track", "form", "sectors", "title", "summary",
                 "amount_usd_bn", "amount_is_estimate", "amount_krw_bn", "source_grade", "prior_event_hint",
                 "confidence", "note"],
    "additionalProperties": False,
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {"type": "array", "items": EVENT_SCHEMA},
        "article_note": {"type": "string", "description": "사건이 없거나 범위 밖이면 이유"},
    },
    "required": ["events", "article_note"],
    "additionalProperties": False,
}


def build_system(events: list[dict]) -> str:
    by_title = {e["title"]: e for e in events}
    org_lines = []
    with ORGS.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            org_lines.append(f"- {r['canonical']} ({r['country']}, {r['type']}): {r['aliases'].replace('|', ', ')}")
    parts = [SYSTEM_RULES.replace("{orgs}", "\n".join(org_lines))]
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
        model=MODEL, max_tokens=16000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
    )
    usage = {"input": response.usage.input_tokens, "output": response.usage.output_tokens,
             "cache_read": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
             "cache_write": getattr(response.usage, "cache_creation_input_tokens", 0) or 0}
    if response.stop_reason == "refusal":
        return {"events": [], "article_note": "refusal", "refusal": True}, usage
    if response.stop_reason == "max_tokens":
        raise RuntimeError("출력 잘림(max_tokens)")
    text = next(b.text for b in response.content if b.type == "text")
    try:
        return json.loads(text), usage
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"JSON 파싱 실패: {exc}") from exc


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


def jaccard(a: list[str], b: list[str]) -> float:
    A, B = {norm(x) for x in a}, {norm(x) for x in b}
    return len(A & B) / len(A | B) if A | B else 1.0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("seed")
    p.parse_args()
    return cmd_seed()


if __name__ == "__main__":
    sys.exit(main())
