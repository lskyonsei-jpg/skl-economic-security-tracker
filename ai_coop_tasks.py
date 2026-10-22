"""한미 AI 협력 트래커 — 일일 자동 판단 요청. AI 는 아무것도 직접 바꾸지 않는다(연구자 결정 2026-10-22).

  python ai_coop_tasks.py daily    탐지 → Task A/B/C → 제안을 data/ai_coop_state.json 에 쌓는다. 사이트의 "판단 대기" 페이지가 보여 준다
  python ai_coop_tasks.py apply    data/ai_coop_decisions.csv(연구자가 GitHub 웹에서 편집)의 승인·기각을 사건 파일에 반영한다

세 절
  A. 새 사건 후보   RSS 질의(최근 2일) → 기관 마스터로 1차 필터 → Task A 코딩 → 제안
  B. 기존 사건 갱신 열린 사건(announced/in_progress)마다 후속 기사 검색 → 관계 판정(same_event/follow_up/correction/lifecycle) → 제안
  C. 기존 판단 재검토 확정 사건을 하루 몇 건씩 다시 코딩해 form/track/금액이 다르면 모델 근거와 함께 제안

제안 id: A-YYYYMMDD-nn, B-…, C-…. 승인된 A 는 사건 추가(status=confirmed, coded_by=model, approved_by=researcher),
B 는 후속 사건 추가 또는 필드 갱신·lifecycle 변경, C 는 필드 갱신. 모든 반영은 updates[] 에 근거와 함께 남는다.

비용 상한: 하루 MAX_DAILY_CALLS 회. 상한에 닿으면 남은 작업은 다음 날로.
필요한 환경변수: ANTHROPIC_API_KEY.
결정 경로 두 가지: (1) 사이트 판단 대기 페이지에서 제출한 GitHub Issue(라벨 ai-coop-decision, 본문 한 줄 = 한 결정)
(2) data/ai_coop_decisions.csv — 열 proposal_id, decision(approve|reject|hold), note, date.
의견(note)에 수정 지시가 있으면 Task D 가 모델로 제안 값을 고친 뒤 반영한다(연구자 의견이 우선). GH_TOKEN 이 있어야 Issue 를 읽는다.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import collect_ai_coop as cc

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
STATE = DATA / "ai_coop_state.json"
EVENTS = cc.EVENTS
MAX_DAILY_CALLS = int(os.environ.get("AI_COOP_MAX_DAILY_CALLS", "60"))
MAX_A_ARTICLES = 20      # 하루 Task A 코딩 상한
MAX_B_EVENTS = 8         # 하루 Task B 점검 사건 수
MAX_B_ARTICLES_PER_EVENT = 2
MAX_C_EVENTS = 6         # 하루 Task C 재코딩 사건 수
C_RECHECK_DAYS = 120
B_RECHECK_DAYS = 7
DECISIONS = DATA / "ai_coop_decisions.csv"

# 탐지 질의. 한국어는 Google News(KR), 영어는 Google News(US)·Bing.
QUERIES_KO = ["한미 AI 협력", "엔비디아 한국", "오픈AI 한국", "앤트로픽 한국", "마이크로소프트 한국 AI", "구글 한국 AI",
              "삼성전자 미국 AI", "SK하이닉스 엔비디아", "현대차 미국 AI", "네이버 미국 AI", "과기정통부 미국 AI",
              "AI 데이터센터 미국 투자 한국", "반도체 한미 협력", "파운드리 미국 계약", "피지컬 AI 한미", "한미 정상 AI"]
QUERIES_EN = ["Korea AI partnership", "Samsung Nvidia", "SK hynix Nvidia", "Hyundai Nvidia AI", "Korea OpenAI",
              "Korea Anthropic", "Korea Microsoft AI", "Korea AI data center", "Samsung foundry contract", "Korea US chips AI"]


# ------------------------------------------------------------------ 상태


def load_state() -> dict:
    if STATE.is_file():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"seen": {}, "checked_b": {}, "checked_c": {}, "proposals": [], "counter": {}}


def save_state(state: dict) -> None:
    DATA.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def load_events() -> dict:
    if not EVENTS.is_file():
        cc.cmd_seed()
    return json.loads(EVENTS.read_text(encoding="utf-8"))


def save_events(doc: dict) -> None:
    doc["as_of"] = dt.datetime.now(dt.timezone.utc).isoformat()
    EVENTS.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")


def new_id(state: dict, task: str, today: str) -> str:
    key = f"{task}-{today}"
    state["counter"][key] = state["counter"].get(key, 0) + 1
    return f"{key}-{state['counter'][key]:02d}"


class Budget:
    def __init__(self, limit: int) -> None:
        self.limit, self.used = limit, 0

    def ok(self) -> bool:
        return self.used < self.limit

    def spend(self) -> None:
        self.used += 1


# ------------------------------------------------------------------ 탐지 (Task A 후보)


def _rss(url: str, params: dict) -> list[dict]:
    import feedparser
    import requests
    try:
        r = requests.get(url, params=params, headers={"User-Agent": cc.UA}, timeout=30)
        return [{"link": e.get("link", ""), "title": e.get("title", ""), "summary": re.sub(r"<[^>]+>", " ", e.get("summary", "") or "")[:400],
                 "published": e.get("published_parsed")} for e in feedparser.parse(r.text).entries]
    except requests.RequestException:
        return []


def discover(window_days: int = 2) -> list[dict]:
    """최근 window_days 의 후보 기사. 제목·요약에 한국 측 기관과 미국 측 기관이 각각 하나 이상 있어야 통과."""
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=window_days)
    out, seen = [], set()
    def add(items, engine):
        for it in items:
            pub = it.get("published")
            if pub and dt.datetime(*pub[:6], tzinfo=dt.timezone.utc) < since:
                continue
            link = it["link"]
            if engine == "google":
                link = cc._decode_gnews(link) or ""
            if not link or link in seen or any(d in link for d in cc.PAYWALL_DOMAINS):
                continue
            seen.add(link)
            out.append({"url": link, "title": it["title"], "summary": it["summary"], "engine": engine,
                        "published": dt.datetime(*pub[:6]).date().isoformat() if pub else None})
    for q in QUERIES_KO:
        add(_rss("https://news.google.com/rss/search", {"q": f"{q} when:{window_days}d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"}), "google")
        time.sleep(0.3)
    for q in QUERIES_EN:
        add(_rss("https://news.google.com/rss/search", {"q": f"{q} when:{window_days}d", "hl": "en-US", "gl": "US", "ceid": "US:en"}), "google")
        add(_rss("https://www.bing.com/news/search", {"q": q, "format": "rss"}), "bing")
        time.sleep(0.3)
    return out


def mentions(text: str) -> tuple[set[str], set[str]]:
    """텍스트에 등장하는 기관(표준 표기) — 미국 측, 한국 측."""
    if cc._ORGS is None:
        cc._ORGS = cc.load_orgs()
    t = cc.norm(text)
    us, kr = set(), set()
    for alias, entry in cc._ORGS.items():
        if len(alias) >= 2 and alias in t:
            (us if entry["country"] == "US" else kr).add(entry["canonical"])
    if re.search(r"한미|韓美|korea.{0,12}(u\.?s\.?|united states|america)", text, re.I):
        us.add("정부(미국)" if "정부" in text or "government" in text.lower() else "(미국 측)")
        kr.add("정부(한국)" if "정부" in text or "government" in text.lower() else "(한국 측)")
    return us, kr


def prefilter(cands: list[dict]) -> list[dict]:
    keep = []
    for c in cands:
        us, kr = mentions(c["title"] + " " + c["summary"])
        if us and kr and re.search(r"AI|인공지능|반도체|데이터센터|로봇|자율주행|파운드리|GPU|HBM|chip|semiconductor|data center|robot", c["title"] + " " + c["summary"], re.I):
            c["hint_us"], c["hint_kr"] = sorted(us), sorted(kr)
            keep.append(c)
    return keep


def dedup_candidates(cands: list[dict], days: int = 3) -> list[dict]:
    """검색 단계의 중복 제거 — 코딩 전에 같은 거래를 다룬 기사를 하나로 합친다(연구자 지시 2026-10-22: 검색 과정의 일부).

    기준은 코딩 뒤의 _same_deal 과 같다: 제목·요약에서 찾은 양측 기관이 각각 Jaccard ≥ 0.5 로 겹치고 보도일이 ±days 안.
    기관 목록에 없는 자리표시("(미국 측)" 등)만 있는 기사는 비교 근거가 없으므로 합치지 않는다.
    대표 기사는 가장 먼저 보도된 것. 나머지는 대표의 others 에 남아 제안의 '다른 기사' 로 보인다.
    """
    groups: list[dict] = []
    for c in sorted(cands, key=lambda x: x.get("published") or "9999-99-99"):
        us = [x for x in c.get("hint_us", []) if not x.startswith("(")]
        kr = [x for x in c.get("hint_kr", []) if not x.startswith("(")]
        key = {"us_parties": us, "kr_parties": kr, "date": c.get("published")}
        home = next((g for g in groups if us and kr and _same_deal(g["_key"], key, days)), None)
        if home is not None:
            home.setdefault("others", []).append({"url": c["url"], "title": c["title"]})
            continue
        c["_key"] = key
        groups.append(c)
    if len(groups) != len(cands):
        print(f"[A] 검색 단계 중복 제거: {len(cands)}건 -> {len(groups)}건")
    return groups


# ------------------------------------------------------------------ Task A


def task_a(client, system: str, state: dict, events: list[dict], budget: Budget, today: str) -> list[dict]:
    cands = prefilter(discover())
    fresh = dedup_candidates([c for c in cands if c["url"] not in state["seen"]])
    print(f"[A] 후보 {len(cands)}건, 처음 보는 것(중복 제거 뒤) {len(fresh)}건")
    proposals = []
    for c in fresh[:MAX_A_ARTICLES]:
        state["seen"][c["url"]] = today
        for o in c.get("others", []):
            state["seen"][o["url"]] = today
        if not budget.ok():
            print("  호출 상한 — 나머지는 내일"); break
        inp = cc.resolve_input(c["title"], None, c["url"], c["summary"])
        meta = dict(inp.get("meta") or {}); meta["url"] = inp["url"] or c["url"]
        try:
            pred, usage = cc.code_article(client, system, meta, cc.clip(inp["text"]), "medium", kind=inp["kind"])
        except Exception as exc:  # noqa: BLE001 — 한 기사 실패가 하루를 멈추지 않게
            print(f"  [A 오류] {c['title'][:40]} — {str(exc)[:100]}"); continue
        budget.spend()
        for ev in pred.get("events") or []:
            ev["us_parties"], unk_us = cc.canonical_parties(ev.get("us_parties", []))
            ev["kr_parties"], unk_kr = cc.canonical_parties(ev.get("kr_parties", []))
            if not ev["us_parties"] or not ev["kr_parties"]:
                continue
            if inp["kind"] == "title":
                ev["confidence"] = min(ev.get("confidence", 0.5), 0.5)
            dup = find_similar(events, ev)
            proposals.append({
                "id": new_id(state, "A", today), "task": "A", "created": today, "status": "proposed",
                "payload": ev, "possible_duplicate_of": dup["id"] if dup else None,
                "unknown_orgs": unk_us + unk_kr,
                "extra_sources": [{"url": o["url"], "title": o["title"], "form": None, "confidence": None} for o in c.get("others", [])],
                "evidence": {"url": inp["url"] or c["url"], "via": inp["via"], "kind": inp["kind"], "chars": inp["chars"],
                             "sha256": inp["sha256"], "excerpt": inp["text"][:500]},
            })
    return dedup_proposals(proposals, [q for q in state["proposals"] if q["task"] == "A" and q["status"] == "proposed"])


def _same_deal(a: dict, b: dict, days: int = 3) -> bool:
    """같은 거래인가: 양측 주체 집합이 겹치고(Jaccard ≥ 0.5) 날짜가 ±days 안."""
    try:
        da, db = dt.date.fromisoformat((a.get("date") or "")[:10]), dt.date.fromisoformat((b.get("date") or "")[:10])
        if abs((da - db).days) > days:
            return False
    except ValueError:
        pass  # 날짜가 없으면 주체만으로 본다
    return cc.jaccard(a.get("us_parties", []), b.get("us_parties", [])) >= 0.5 and cc.jaccard(a.get("kr_parties", []), b.get("kr_parties", [])) >= 0.5


def dedup_proposals(new: list[dict], pending_old: list[dict]) -> list[dict]:
    """코딩 뒤의 중복 제거(안전망). 검색 단계(dedup_candidates)에서 못 거른 같은 거래 — 기사 표기가 달라 기관 목록으로는
    못 잡았지만 모델이 같은 주체로 코딩한 경우 — 를 거래 단위로 하나로 합친다. 확신도 높은 것이 대표, 나머지는 extra_sources.
    이미 미결인 이전 제안과 같은 거래면 그쪽에 출처만 보탠다."""
    kept: list[dict] = []
    for p in sorted(new, key=lambda x: -(x["payload"].get("confidence") or 0)):
        home = next((q for q in pending_old if _same_deal(q["payload"], p["payload"])), None) or \
               next((q for q in kept if _same_deal(q["payload"], p["payload"])), None)
        if home is None:
            p.setdefault("extra_sources", [])
            kept.append(p)
            continue
        home.setdefault("extra_sources", []).append({"url": p["evidence"]["url"], "title": p["payload"].get("title"),
                                                     "form": p["payload"].get("form"), "confidence": p["payload"].get("confidence")})
        home["extra_sources"].extend(p.get("extra_sources", []))
        # 대표보다 강한 form 이 나오면 메모에 남긴다(바꾸지는 않는다)
        if p["payload"].get("form") != home["payload"].get("form"):
            home.setdefault("form_variants", []).append(p["payload"].get("form"))
    print(f"[A] 중복 제거: {len(new)}건 -> {len(kept)}건 (이전 미결에 합쳐진 것 {len(new) - len(kept) - sum(len(k.get('extra_sources', [])) for k in kept)}건)")
    return kept


def find_similar(events: list[dict], ev: dict, days: int = 10) -> dict | None:
    """같은 거래로 보이는 기존 사건(주체 겹침 + 날짜 근접)."""
    if not ev.get("date"):
        return None
    try:
        d = dt.date.fromisoformat(ev["date"][:10])
    except ValueError:
        return None
    best = None
    for e in events:
        try:
            ed = dt.date.fromisoformat(e["date"][:10])
        except ValueError:
            continue
        if abs((ed - d).days) > days:
            continue
        if cc.jaccard(e["us_parties"], ev["us_parties"]) >= 0.5 and cc.jaccard(e["kr_parties"], ev["kr_parties"]) >= 0.5:
            best = e
            break
    return best


# ------------------------------------------------------------------ Task B


B_SYSTEM = """당신은 한미 AI 협력 사건 데이터베이스의 갱신 보조자다. 기존 사건 레코드 하나와 새 기사 하나를 받아 둘의 관계를 판정한다. 기사에 없는 사실을 만들지 않는다. 기존 레코드의 값을 바꾸자고 제안할 때는 기사의 근거 문장을 evidence 에 그대로 인용한다.

[관계]
- unrelated: 다른 사건이거나 관련이 없다.
- same_event: 같은 사건의 추가 보도(새 사실 없음). 출처만 추가한다.
- follow_up: 같은 거래의 다음 단계(MOU → 확정계약 → 집행 등). new_event 에 새 사건을 채운다.
- correction: 기존 레코드의 사실(금액·날짜·주체·형태)이 기사와 다르다. updates 에 field/old/new/evidence.
- lifecycle: 완료·취소·지연·규모 변경·관계 종료. lifecycle 에 completed/cancelled/delayed/superseded/in_progress 중 하나.

[form·track·금액 규칙] 확정계약은 구속력 문서(계약 체결·인수·지분 취득·합작·장기 공급·라이선스·협약 체결)가 명시된 것, MOU·의향은 비구속 문서이거나 문서가 특정되지 않은 발표, 집행은 앞선 거래의 이행·완료, 선언은 정부 성명·회담·투자 계획. track 은 정부-정부/정부-민간/민간-민간. 금액은 거래금액만(억 달러).
"""

B_SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {"type": "string", "enum": ["unrelated", "same_event", "follow_up", "correction", "lifecycle"]},
        "new_event": {"anyOf": [cc.EVENT_SCHEMA, {"type": "null"}]},
        "updates": {"type": "array", "items": {"type": "object", "properties": {
            "field": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}, "evidence": {"type": "string"}},
            "required": ["field", "old", "new", "evidence"], "additionalProperties": False}},
        "lifecycle": {"anyOf": [{"type": "string", "enum": ["announced", "in_progress", "completed", "cancelled", "delayed", "superseded"]}, {"type": "null"}]},
        "evidence": {"type": "string"},
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["relation", "new_event", "updates", "lifecycle", "evidence", "confidence", "note"],
    "additionalProperties": False,
}


def classify_relation(client, event: dict, meta: dict, body: str) -> tuple[dict, dict]:
    record = {k: event.get(k) for k in ("id", "date", "us_parties", "kr_parties", "track", "form", "sectors", "title", "amount_usd_bn", "lifecycle")}
    user = (f"[기존 사건]\n{json.dumps(record, ensure_ascii=False)}\n\n[새 기사]\nURL: {meta.get('url', '')}\n게재일(참고): {meta.get('published', '')}\n"
            f"제목: {meta.get('title', '')}\n\n[본문]\n{body}")
    response = client.messages.create(
        model=cc.MODEL, max_tokens=8000,
        system=[{"type": "text", "text": B_SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": B_SCHEMA}},
    )
    usage = {"input": response.usage.input_tokens, "output": response.usage.output_tokens}
    if response.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"응답 중단: {response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text), usage


def task_b(client, state: dict, events: list[dict], budget: Budget, today: str) -> list[dict]:
    open_events = [e for e in events if e.get("status") == "confirmed" and e.get("lifecycle") in (None, "", "announced", "in_progress")]
    def due(e):
        last = state["checked_b"].get(e["id"])
        return last is None or (dt.date.fromisoformat(today) - dt.date.fromisoformat(last)).days >= B_RECHECK_DAYS
    queue = sorted([e for e in open_events if due(e)], key=lambda e: (state["checked_b"].get(e["id"], "0000-00-00"), e["date"]))[:MAX_B_EVENTS]
    print(f"[B] 열린 사건 {len(open_events)}건, 오늘 점검 {len(queue)}건")
    proposals = []
    for e in queue:
        state["checked_b"][e["id"]] = today
        since = state["checked_b"].get(e["id"] + ":since") or e["date"]
        query = " ".join(e["us_parties"][:2] + e["kr_parties"][:2]) + " " + re.sub(r"[()（）–—,·]", " ", e["title"])[:40]
        cands = _search_since(query, since)
        n = 0
        for c in cands:
            if n >= MAX_B_ARTICLES_PER_EVENT or not budget.ok():
                break
            url = cc._decode_gnews(c["link"]) if c["engine"] == "google" else c["link"]
            if not url or url in state["seen"] or any(d in url for d in cc.PAYWALL_DOMAINS) or url == (e["sources"] or [{}])[0].get("url"):
                continue
            body, meta = cc.fetch_body(url)
            if len(body) < 300:
                continue
            state["seen"][url] = today
            meta["url"] = url
            try:
                rel, _ = classify_relation(client, e, meta, cc.clip(body))
            except Exception as exc:  # noqa: BLE001
                print(f"  [B 오류] {e['title'][:30]} — {str(exc)[:100]}"); continue
            budget.spend(); n += 1
            if rel["relation"] in ("unrelated", "same_event"):
                continue
            if rel.get("new_event"):
                ne = rel["new_event"]
                ne["us_parties"], _ = cc.canonical_parties(ne.get("us_parties", []))
                ne["kr_parties"], _ = cc.canonical_parties(ne.get("kr_parties", []))
            proposals.append({
                "id": new_id(state, "B", today), "task": "B", "created": today, "status": "proposed",
                "target_id": e["id"], "target_title": e["title"], "relation": rel["relation"],
                "payload": {"new_event": rel.get("new_event"), "updates": rel.get("updates", []), "lifecycle": rel.get("lifecycle")},
                "confidence": rel.get("confidence"), "note": rel.get("note", ""),
                "evidence": {"url": url, "excerpt": rel.get("evidence", "")[:500] or body[:500],
                             "sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(), "chars": len(body)},
            })
        state["checked_b"][e["id"] + ":since"] = today
    return proposals


def _search_since(query: str, since: str) -> list[dict]:
    """사건일(또는 마지막 점검일) 이후의 후속 기사 후보."""
    out = []
    q = re.sub(r"[\"'()\[\]–—·,]", " ", query)
    out += [dict(x, engine="google") for x in _rss("https://news.google.com/rss/search", {"q": f"{q} after:{since}", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})[:6]]
    out += [dict(x, engine="google") for x in _rss("https://news.google.com/rss/search", {"q": f"{q} after:{since}", "hl": "en-US", "gl": "US", "ceid": "US:en"})[:4]]
    return out


# ------------------------------------------------------------------ Task C


def task_c(client, system: str, state: dict, events: list[dict], budget: Budget, today: str) -> list[dict]:
    def due(e):
        last = state["checked_c"].get(e["id"])
        return last is None or (dt.date.fromisoformat(today) - dt.date.fromisoformat(last)).days >= C_RECHECK_DAYS
    queue = [e for e in events if e.get("status") == "confirmed" and e.get("sources") and due(e)]
    queue = sorted(queue, key=lambda e: (state["checked_c"].get(e["id"], "0000-00-00"), e["date"]))[:MAX_C_EVENTS]
    print(f"[C] 재검토 대상 {len(queue)}건")
    proposals = []
    for e in queue:
        if not budget.ok():
            break
        state["checked_c"][e["id"]] = today
        inp = cc.resolve_input(e["title"], e["date"], e["sources"][0]["url"])
        if inp["kind"] == "title":
            continue  # 본문 없이 기존 판단을 뒤집자고 하지 않는다
        meta = dict(inp.get("meta") or {}); meta["url"] = inp["url"]
        try:
            pred, _ = cc.code_article(client, system, meta, cc.clip(inp["text"]), "medium")
        except Exception as exc:  # noqa: BLE001
            print(f"  [C 오류] {e['title'][:30]} — {str(exc)[:100]}"); continue
        budget.spend()
        evs = pred.get("events") or []
        for ev in evs:
            ev["us_parties"], _ = cc.canonical_parties(ev.get("us_parties", []))
            ev["kr_parties"], _ = cc.canonical_parties(ev.get("kr_parties", []))
        if not evs:
            diffs = [{"field": "is_event", "old": "사건", "new": "사건 아님", "reason": pred.get("article_note", "")}]
            best = {}
        else:
            best = max(evs, key=lambda ev: cc.jaccard(ev.get("us_parties", []), e["us_parties"]) + cc.jaccard(ev.get("kr_parties", []), e["kr_parties"]) + (0.5 if ev.get("form") == e["form"] else 0))
            diffs = []
            for field in ("form", "track"):
                if best.get(field) and best.get(field) != e.get(field):
                    diffs.append({"field": field, "old": e.get(field), "new": best.get(field), "reason": best.get("note", "")})
            if best.get("amount_usd_bn") != e.get("amount_usd_bn") and (best.get("amount_usd_bn") is not None or e.get("amount_usd_bn") is not None):
                diffs.append({"field": "amount_usd_bn", "old": e.get("amount_usd_bn"), "new": best.get("amount_usd_bn"), "reason": best.get("note", "")})
        if diffs:
            proposals.append({
                "id": new_id(state, "C", today), "task": "C", "created": today, "status": "proposed",
                "target_id": e["id"], "target_title": e["title"], "payload": {"diffs": diffs, "model_event": best},
                "confidence": best.get("confidence"), "note": best.get("note", "") or pred.get("article_note", ""),
                "evidence": {"url": inp["url"], "via": inp["via"], "chars": inp["chars"], "sha256": inp["sha256"], "excerpt": inp["text"][:500]},
            })
    return proposals


# ------------------------------------------------------------------ 판단 기록(md)·결정 반영


def render_judgment(today: str, props: list[dict], budget: "Budget", stats: dict) -> str:
    """사람이 읽는 기록용 마크다운(data/ai_coop_judgment_<날짜>.md). 화면은 ai_coop_site 가 state 에서 직접 그린다."""
    a = [p for p in props if p["task"] == "A"]; b = [p for p in props if p["task"] == "B"]; c = [p for p in props if p["task"] == "C"]
    lines = [f"# 자동 판단 요청 {today}", "", f"탐지 후보 {stats.get('cands', 0)}건 · 모델 호출 {budget.used}회 · 제안 A {len(a)} / B {len(b)} / C {len(c)}", "",
             "승인·기각은 data/ai_coop_decisions.csv 에 `proposal_id,decision,note,date` 한 줄씩. decision 은 approve 또는 reject.", ""]
    for p in props:
        lines.append(f"- **{p['id']}** [{p['task']}] " + (p["payload"].get("title", "") if p["task"] == "A" else p.get("target_title", "")) + f" · conf {p.get('confidence') or p['payload'].get('confidence')}")
        lines.append(f"  - 근거: {p['evidence'].get('url', '')}")
    return "\n".join(lines)


DECISION_WORDS = {"approve": "approved", "승인": "approved", "reject": "rejected", "기각": "rejected", "hold": "hold", "보류": "hold",
                  "other": "hold", "기타": "hold"}   # 기타 = 의견만 남기고 보류
DECISION_LINE = re.compile(r"^[-*]?\s*([ABC]-\d{4}-\d{2}-\d{2}-\d{2}|[ABC]-\d{8}-\d{2})\s*[:：]\s*(approve|reject|hold|other|승인|기각|보류|기타)\s*(?:\|\s*의견\s*[:：]\s*(.*))?\s*$", re.I | re.M)


def read_decisions() -> dict[str, dict]:
    """CSV 결정. {pid: {decision, note, date, source}}"""
    import csv
    if not DECISIONS.is_file():
        return {}
    out = {}
    with DECISIONS.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            pid = (r.get("proposal_id") or "").strip()
            d = DECISION_WORDS.get((r.get("decision") or "").strip().lower())
            if pid and d:
                out[pid] = {"decision": d, "note": (r.get("note") or "").strip(), "date": (r.get("date") or "").strip(), "source": "csv"}
    return out


def _gh():
    import requests
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        return None, None
    sess = requests.Session()
    sess.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    return sess, repo


def read_issue_decisions() -> tuple[dict[str, dict], list[dict]]:
    """사이트에서 제출한 Issue(라벨 ai-coop-decision). 저장소 소유자·협력자가 쓴 것만 인정한다."""
    sess, repo = _gh()
    if not sess:
        return {}, []
    issues = sess.get(f"https://api.github.com/repos/{repo}/issues", params={"labels": "ai-coop-decision", "state": "open", "per_page": 50}, timeout=30).json()
    out, used = {}, []
    for issue in issues if isinstance(issues, list) else []:
        if issue.get("author_association") not in ("OWNER", "MEMBER", "COLLABORATOR"):
            continue
        n = 0
        for m in DECISION_LINE.finditer(issue.get("body") or ""):
            out[m.group(1)] = {"decision": DECISION_WORDS[m.group(2).lower()], "note": (m.group(3) or "").strip(),
                               "date": (issue.get("created_at") or "")[:10], "source": f"issue#{issue['number']}"}
            n += 1
        if n:
            used.append(issue)
    return out, used


D_SYSTEM = """당신은 한미 AI 협력 사건 데이터베이스의 보조자다. 모델이 낸 제안(사건 코딩)과 연구자의 의견을 받아, 의견에 담긴 수정 지시를 사건 값에 반영한 결과를 돌려준다.
규칙: 연구자 의견이 모델 판정보다 우선한다. 의견이 언급하지 않은 필드는 바꾸지 않는다. 의견이 "맞다", "승인" 처럼 수정 지시가 아니면 아무것도 바꾸지 않는다.
형태(form)는 MOU·의향/선언/집행/확정계약, track 은 정부-정부/정부-민간/민간-민간, 분야는 정해진 목록, 금액은 억 달러 숫자. 바꾼 필드마다 changes 에 field/old/new 를 적는다."""

D_SCHEMA = {
    "type": "object",
    "properties": {
        "event": cc.EVENT_SCHEMA,
        "changes": {"type": "array", "items": {"type": "object", "properties": {"field": {"type": "string"}, "old": {"type": "string"}, "new": {"type": "string"}},
                                               "required": ["field", "old", "new"], "additionalProperties": False}},
        "note": {"type": "string"},
    },
    "required": ["event", "changes", "note"],
    "additionalProperties": False,
}


def revise_with_note(event: dict, note: str) -> tuple[dict, list[dict]]:
    """Task D: 연구자 의견으로 제안 값을 고친다. 키가 없거나 실패하면 원안 그대로."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return event, []
    import anthropic
    client = anthropic.Anthropic()
    base = {k: event.get(k) for k in cc.EVENT_SCHEMA["properties"]}
    for k, v in cc.EVENT_SCHEMA["properties"].items():
        if base.get(k) is None and v.get("type") == "array":
            base[k] = []
        if base.get(k) is None and v.get("type") == "string":
            base[k] = ""
        if base.get(k) is None and v.get("type") == "boolean":
            base[k] = False
        if base.get(k) is None and v.get("type") == "number":
            base[k] = 0.5
        if base.get(k) is None and v.get("type") == "integer":
            base[k] = 2
    user = f"[제안]\n{json.dumps(base, ensure_ascii=False)}\n\n[연구자 의견]\n{note}"
    try:
        r = client.messages.create(model=cc.MODEL, max_tokens=6000, system=D_SYSTEM, messages=[{"role": "user", "content": user}],
                                   output_config={"effort": "medium", "format": {"type": "json_schema", "schema": D_SCHEMA}})
        if r.stop_reason in ("refusal", "max_tokens"):
            return event, []
        out = json.loads(next(b.text for b in r.content if b.type == "text"))
        ev = dict(event); ev.update(out["event"])
        ev["us_parties"], _ = cc.canonical_parties(ev.get("us_parties", [])); ev["kr_parties"], _ = cc.canonical_parties(ev.get("kr_parties", []))
        return ev, out.get("changes", [])
    except Exception as exc:  # noqa: BLE001
        print(f"  [D 오류] {str(exc)[:120]}")
        return event, []


def apply_proposal(p: dict, doc: dict, today: str, note: str = "") -> str:
    events = doc["events"]
    by_id = {e["id"]: e for e in events}
    changed_by_note: list[dict] = []
    if note and p["task"] == "A":
        p["payload"], changed_by_note = revise_with_note(p["payload"], note)
    if note and p["task"] == "B" and p["payload"].get("new_event"):
        p["payload"]["new_event"], changed_by_note = revise_with_note(p["payload"]["new_event"], note)
    def stamp(ev: dict, src: dict | None) -> dict:
        ev = dict(ev)
        ev.setdefault("id", f"{(ev.get('date') or today).replace('-', '')}-{hashlib.sha1((ev.get('date', '') + ev.get('title', '')).encode()).hexdigest()[:8]}")
        ev.update({"status": "confirmed", "coded_by": cc.MODEL, "approved_by": "researcher", "approved_on": today,
                   "administration": cc.administration(ev.get("date") or today), "lifecycle": ev.get("lifecycle") or "announced", "updates": [],
                   "sources": [{"url": src["url"], "grade": ev.get("source_grade")}] if src else [], "proposal_id": p["id"]})
        for k in ("summary", "note"):
            ev.setdefault(k, "")
        ev.setdefault("prior_event_id", None)
        return ev
    if p["task"] == "A":
        ev = stamp(p["payload"], p["evidence"])
        if note:
            ev["researcher_note"] = note
            for ch in changed_by_note:
                ev["updates"].append({"date": today, "field": ch["field"], "old": ch["old"], "new": ch["new"], "evidence": "연구자 의견: " + note, "proposal_id": p["id"]})
        if ev["id"] in by_id:
            return f"{p['id']}: 같은 id 의 사건이 이미 있음 — 건너뜀"
        events.append(ev)
        return f"{p['id']}: 사건 추가 {ev['title']}" + (f" (의견 반영 {len(changed_by_note)}개 필드)" if changed_by_note else "")
    target = by_id.get(p["target_id"])
    if not target:
        return f"{p['id']}: 대상 사건 {p['target_id']} 없음"
    if note:
        target["researcher_note"] = ((target.get("researcher_note") or "") + f" [{today}] " + note).strip()
    if p["task"] == "B":
        pl, done = p["payload"], []
        if pl.get("new_event"):
            ev = stamp(pl["new_event"], p["evidence"]); ev["prior_event_id"] = target["id"]
            events.append(ev); done.append(f"후속 사건 추가 {ev['title']}")
        for u in pl.get("updates", []):
            old = target.get(u["field"]); target[u["field"]] = u["new"]
            target.setdefault("updates", []).append({"date": today, "field": u["field"], "old": old, "new": u["new"], "evidence": u["evidence"], "url": p["evidence"]["url"], "proposal_id": p["id"]})
            done.append(f"{u['field']} 갱신")
        if pl.get("lifecycle"):
            target.setdefault("updates", []).append({"date": today, "field": "lifecycle", "old": target.get("lifecycle"), "new": pl["lifecycle"], "url": p["evidence"]["url"], "proposal_id": p["id"]})
            target["lifecycle"] = pl["lifecycle"]; done.append(f"lifecycle={pl['lifecycle']}")
        return f"{p['id']}: " + ", ".join(done or ["반영할 내용 없음"])
    if p["task"] == "C":
        done = []
        for d in p["payload"]["diffs"]:
            if d["field"] == "is_event":
                target["status"] = "rejected"; done.append("사건 아님 → 제외"); continue
            old = target.get(d["field"]); target[d["field"]] = d["new"]
            target.setdefault("updates", []).append({"date": today, "field": d["field"], "old": old, "new": d["new"], "evidence": d.get("reason", ""), "url": p["evidence"]["url"], "proposal_id": p["id"]})
            done.append(f"{d['field']}: {old} → {d['new']}")
        return f"{p['id']}: " + ", ".join(done)
    return f"{p['id']}: 알 수 없는 task"


def cmd_apply(today: str) -> int:
    state = load_state(); doc = load_events()
    # 미결 A 제안 중 같은 거래는 하나로 합친다(예전 실행이 남긴 중복 정리)
    pending_a = [p for p in state["proposals"] if p["task"] == "A" and p["status"] == "proposed"]
    kept_ids = {k["id"] for k in dedup_proposals(pending_a, [])}
    merged = 0
    for p in pending_a:
        if p["id"] not in kept_ids:
            p["status"] = "merged"; merged += 1
    if merged:
        save_state(state); print(f"[apply] 중복 제안 {merged}건을 대표 제안에 합침")
    pending = {p["id"]: p for p in state["proposals"] if p["status"] == "proposed"}
    decisions = read_decisions()
    issue_decisions, issues = read_issue_decisions()
    decisions.update(issue_decisions)
    lines = []
    for pid, d in decisions.items():
        p = pending.get(pid)
        if not p:
            continue
        if d["decision"] == "hold":
            if d["note"]:
                p["hold_note"] = d["note"]
            lines.append(f"{pid}: 보류" + (f" ({d['note'][:60]})" if d["note"] else "")); continue
        if d["decision"] == "approved":
            lines.append(apply_proposal(p, doc, today, note=d["note"])); p["status"] = "applied"
        else:
            lines.append(f"{pid}: 기각" + (f" ({d['note'][:60]})" if d["note"] else "")); p["status"] = "rejected"
        p["decided"] = d["date"] or today; p["decision_note"] = d["note"]; p["decision_source"] = d["source"]
    if lines:
        save_events(doc); save_state(state)
        print("[apply] " + "; ".join(lines))
    else:
        print(f"[apply] 반영할 결정 없음 (미결 {len(pending)}건)")
    sess, repo = _gh()
    if sess:
        for issue in issues:
            mine = [l for l in lines if any(l.startswith(pid) for pid, d in issue_decisions.items() if d["source"] == f"issue#{issue['number']}")]
            body = f"반영 결과 ({today})\n\n" + ("\n".join(f"- {l}" for l in mine) if mine else "- 해당 제안이 미결 목록에 없어 반영할 것이 없었습니다.")
            sess.post(issue["comments_url"], json={"body": body}, timeout=30)
            sess.patch(issue["url"], json={"state": "closed"}, timeout=30)
    return 0


# ------------------------------------------------------------------ daily


def cmd_daily(today: str) -> int:
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("[daily] ANTHROPIC_API_KEY 없음"); return 1
    state = load_state(); doc = load_events(); events = doc["events"]
    system = cc.build_system(events)
    client = anthropic.Anthropic()
    budget = Budget(MAX_DAILY_CALLS)
    stats = {}
    cands = prefilter(discover()); stats["cands"] = len(cands)
    stats["filtered"] = len(cands)
    props = []
    props += task_a(client, system, state, events, budget, today)
    stats["coded_a"] = sum(1 for _ in props)
    props += task_b(client, state, events, budget, today)
    props += task_c(client, system, state, events, budget, today)
    state["proposals"] += props
    save_state(state)
    body = render_judgment(today, props, budget, stats)
    (DATA / f"ai_coop_judgment_{today}.md").write_text(body, encoding="utf-8")
    pending_total = sum(1 for p in state["proposals"] if p["status"] == "proposed")
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write(f"## 한미 AI 협력 — 일일 판단 요청 {today}\n\n- 제안 A {sum(p['task']=='A' for p in props)} · B {sum(p['task']=='B' for p in props)} · C {sum(p['task']=='C' for p in props)} · 호출 {budget.used}회 · 누적 미결 {pending_total}건\n"
                     "- 사이트의 review.html 에 표시. 결정은 data/ai_coop_decisions.csv 에.\n")
    print(f"[daily] A {sum(p['task']=='A' for p in props)} B {sum(p['task']=='B' for p in props)} C {sum(p['task']=='C' for p in props)}, 호출 {budget.used}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["daily", "apply", "discover"])
    p.add_argument("--date", default=dt.date.today().isoformat())
    a = p.parse_args()
    if a.cmd == "discover":
        cands = prefilter(discover())
        for c in cands:
            print(f"  {c['engine']:<6} {c['hint_us']} / {c['hint_kr']}  {c['title'][:70]}  {c['url'][:60]}")
        print(f"후보 {len(cands)}건"); return 0
    if a.cmd == "apply":
        return cmd_apply(a.date)
    return cmd_daily(a.date)


if __name__ == "__main__":
    sys.exit(main())
