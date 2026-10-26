"""한미 AI 협력 트래커 — 사건 수집·코딩. 설계: 문서/20261022_설계_한미AI협력트래커_자동화.md

  python collect_ai_coop.py seed    data/seed/*.csv -> data/ai_coop_events.json (연구자 확정 코딩; 사건 파일이 없을 때의 부트스트랩)
  그 밖에는 ai_coop_tasks.py 가 라이브러리로 쓴다(프롬프트·스키마·본문 확보·기관 표기·track).

모델: claude-opus-5-5, effort medium (연구자 확정 2026-10-22, 비교 실험 없이 medium 으로). 구조화 출력(output_config.format)으로 스키마를 강제한다.
프롬프트 v3(2026-10-26): 레코드 = 거래(deal) 하나, lifecycle 은 거래가 도달한 단계(Rumour < Signed < Contracted < Operating < Completed),
canceled 는 0/1, track 은 정부-정부/정부-민간/민간-민간, 금액은 거래금액만, 기사 하나에 거래 여러 개(events 배열),
기관 표기는 reference/ai_coop_orgs.csv 의 표준 표기. 스키마 v2 — 2026-10-25 까지의 v1(사건 단위, form)은 migrate_doc() 이 변환한다.
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

SCHEMA_VERSION = 2
# 거래가 도달한 단계. 서열이며 올라가기만 한다(코드북 패널 2, 연구자 확정 2026-10-26).
LIFECYCLES = ["Rumour", "Signed", "Contracted", "Operating", "Completed"]
STAGE_DATE = {"Rumour": "date_rumour", "Signed": "date_signed", "Contracted": "date_contracted",
              "Operating": "date_operating", "Completed": "date_completed"}
# v1(2026-10-22~25) form → v2 lifecycle. 집행은 Operating 이 기본이고 인수 완료 2건만 Completed(MERGES 에서 지정).
FORM_TO_LIFECYCLE = {"선언": "Rumour", "MOU·의향": "Signed", "확정계약": "Contracted", "집행": "Operating"}
TRACKS = ["정부-정부", "정부-민간", "민간-민간"]
ORGS = HERE / "reference" / "ai_coop_orgs.csv"
SECTORS = ["AI데이터센터", "피지컬AI·로봇", "통상·규제", "파운드리", "반도체·메모리", "AI모델·SW", "안보·국방", "전력·인프라", "인재"]
ADMINISTRATIONS = [("2025-01-20", "트럼프 2기"), ("2021-01-20", "바이든"), ("2017-01-20", "트럼프 1기"), ("2009-01-20", "오바마")]
# 시스템 프롬프트 예시로 쓰는 표본 거래(연구자 확정). 정확도 측정에서는 제외한다.
EXAMPLE_TITLES = [
    "삼성전자–테슬라 AI 칩 파운드리 계약(165억 달러)",
    "현대차그룹–엔비디아 전략적 파트너십(CES 2025, 2026 자율주행 확대)",
    "현대차·기아, 오로라(Aurora) 자율주행 파트너십·전략적 투자",
    "삼성전자, 하만 인수(80억 달러·자율주행 진출)",
    "삼성전자–구글 클라우드 생성AI 파트너십(갤럭시 S24·볼리)",
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


def _blank(v) -> str | None:
    v = (v or "").strip()
    return v or None


def seed_to_events(rows: list[dict]) -> list[dict]:
    """시드 CSV(v2, 거래 단위) → 레코드. 열: id, 일자, 미국 주체, 한국 주체, 원문 링크, 트랙, lifecycle, canceled,
    date_rumour, date_signed, date_contracted, date_operating, date_completed, date_canceled, 분야, 내용, 규모(억 달러), 비고, merged_from."""
    events = []
    for r in rows:
        if "lifecycle" not in r:
            raise SystemExit(f"시드 CSV 가 v1(형태) 형식입니다. data/seed/archive/ 로 옮기고 v2 시드를 쓰세요: {list(r)[:8]}")
        amount = (r.get("규모(억 달러)") or "").strip()
        us, kr = split_parties(r["미국 주체"]), split_parties(r["한국 주체"])
        lifecycle = r["lifecycle"].strip()
        if lifecycle not in LIFECYCLES:
            raise SystemExit(f"{r['id']}: lifecycle 값 오류 {lifecycle!r}")
        stage_dates = {col: _blank(r.get(col)) for col in STAGE_DATE.values()}
        if not stage_dates[STAGE_DATE[lifecycle]]:
            raise SystemExit(f"{r['id']}: lifecycle={lifecycle} 인데 {STAGE_DATE[lifecycle]} 이 비어 있음")
        date = min(d for d in stage_dates.values() if d)
        sources = [{"url": u.strip(), "grade": None} for u in (r.get("원문 링크") or "").split("|") if u.strip()]
        events.append({
            "schema_version": SCHEMA_VERSION,
            "id": r["id"], "date": date,
            "us_parties": us, "kr_parties": kr,
            "track": derive_track(us, kr) or "정부-민간", "track_original": (r.get("트랙") or "").strip(),
            "lifecycle": lifecycle, **stage_dates,
            "canceled": int((r.get("canceled") or "0").strip() or 0), "date_canceled": _blank(r.get("date_canceled")),
            "sectors": split_parties(r["분야"]),
            "title": r["내용"].strip(), "summary": "", "note": (r.get("비고") or "").strip(),
            "amount_usd_bn": float(amount) if amount else None, "amount_is_estimate": False,
            "sources": sources,
            "administration": administration(date),
            "status": "confirmed", "confidence": 1.0,
            "coded_by": "researcher", "coded_at": (r.get("coded_at") or "2026-10-26").strip(), "model": None,
            "merged_from": split_parties(r.get("merged_from")), "updates": [],
        })
    events.sort(key=lambda e: (e["date"], e["title"]))
    return events


def cmd_seed() -> int:
    rows = load_seed_rows()
    events = seed_to_events(rows)
    DATA.mkdir(exist_ok=True)
    EVENTS.write_text(json.dumps({"schema_version": SCHEMA_VERSION, "as_of": datetime.now(timezone.utc).isoformat(), "events": events},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[seed] {len(events)}건 -> {EVENTS.relative_to(HERE)}")
    return 0


# ------------------------------------------------------------------ v1 → v2 변환 (2026-10-26, 거래 단위·lifecycle)
# Release "state" 의 ai_coop_events.json 과 ai_coop_state.json 은 v1 으로 남아 있을 수 있다. 읽는 쪽(ai_coop_tasks·ai_coop_site)이
# 매번 migrate_doc() 을 거치므로 어느 경로로 들어와도 같은 v2 레코드가 된다. 시드 CSV(v2)는 이 변환의 결과를 그대로 적은 것이다.

# 같은 거래의 v1 사건들을 한 레코드로 합친다. 대표(keep)는 가장 이른 사건의 id. stages 는 {lifecycle: 날짜}.
# 연구자 비고에 "선행 단계"·"별건 아님"·"확대"로 적힌 사슬만 합쳤다(코드북 패널 2, 2026-10-26).
MERGES = [
    {"keep": "20180104-9b646ac6", "absorb": ["20190613-90c71a99"],           # 현대차–오로라: CES 2018 파트너십 → 2019 지분 투자
     "title": "현대차·기아, 오로라(Aurora) 자율주행 파트너십·전략적 투자", "lifecycle": "Contracted",
     "stages": {"Signed": "2018-01-04", "Contracted": "2019-06-13"}},
    {"keep": "20250109-324f33a6", "absorb": ["20260316-433e3f76"],           # 현대차–엔비디아: CES 2025 파트너십 → 2026-03 자율주행으로 확대(본계약은 별도 예정)
     "title": "현대차그룹–엔비디아 전략적 파트너십(CES 2025, 2026 자율주행 확대)", "lifecycle": "Signed",
     "stages": {"Signed": "2025-01-09"}},
    {"keep": "20250728-26a1236c", "absorb": ["20260318-09476d05"],           # 삼성–테슬라: 계약 → 2026-03 양산 계획 보도(이행 시작 아님, note 로)
     "lifecycle": "Contracted", "stages": {"Contracted": "2025-07-28"}},
    {"keep": "20200702-27b1331c", "absorb": ["20230827-1ed3dca1"],           # SK하이닉스–엔비디아 HBM: 2020 HBM2E 양산 → 2023 주공급사(같은 공급 관계)
     "title": "SK하이닉스–엔비디아 HBM 공급(2020 HBM2E 양산 개시 → 2023 주공급사)", "lifecycle": "Operating",
     "stages": {"Operating": "2020-07-02"}},
    {"keep": "20240118-838030b4", "absorb": ["20250409-9706968c"],           # 삼성–구글 클라우드: S24 출시 → 2025-04 볼리로 확대(같은 다년 파트너십)
     "title": "삼성전자–구글 클라우드 생성AI 파트너십(갤럭시 S24·볼리)", "lifecycle": "Operating",
     "stages": {"Operating": "2024-01-18"}},
]
# 합치지 않고 단계·날짜만 바로잡는 레코드. 인수 완료 2건은 Completed 이고, 계약 발표일을 변환 때 추가했다(출처 확인 요망 — note 에 표시).
RESTAGE = {
    "20170310-96cac345": {"title": "삼성전자, 하만 인수(80억 달러·자율주행 진출)", "lifecycle": "Completed",
                                                     "stages": {"Contracted": "2016-11-14", "Completed": "2017-03-10"},
                                                     "note_add": "[변환 2026-10-26] 인수 계약 발표일 2016-11-14(삼성 뉴스룸)를 date_contracted 로 추가. 확인 요망."},
    "20210621-709e451f": {"title": "현대차그룹, 보스턴다이내믹스 지분 80% 인수(11억 달러)", "lifecycle": "Completed",
                          "stages": {"Contracted": "2020-12-11", "Completed": "2021-06-21"},
                          "note_add": "[변환 2026-10-26] 인수 계약 발표일 2020-12-11(현대차그룹 발표)을 date_contracted 로 추가. 확인 요망."},
}


def _v1_to_v2_record(e: dict) -> dict:
    """v1 사건 하나 → v2 거래 레코드(합치기 전). form → lifecycle, 사건일 → 그 단계의 날짜."""
    e = dict(e)
    form = e.pop("form", None)
    old_life = e.get("lifecycle")   # v1 진행 상태(announced … cancelled). 취소만 canceled 로 남긴다
    lifecycle = FORM_TO_LIFECYCLE.get(form, "Rumour")
    stages = {col: None for col in STAGE_DATE.values()}
    stages[STAGE_DATE[lifecycle]] = e.get("date")
    canceled = 1 if old_life == "cancelled" else 0
    e.pop("prior_event_id", None); e.pop("prior_event_hint", None)
    e.update({"schema_version": SCHEMA_VERSION, "lifecycle": lifecycle, **stages, "canceled": canceled, "date_canceled": None,
              "merged_from": e.get("merged_from") or []})
    e.setdefault("updates", []).append({"date": "2026-10-26", "field": "schema", "old": f"v1 form={form} lifecycle={old_life}",
                                        "new": f"v2 lifecycle={lifecycle}", "evidence": "거래 단위·lifecycle 변환(연구자 결정 2026-10-26)"})
    return e


def migrate_doc(doc: dict) -> tuple[dict, bool]:
    """사건 파일 전체를 v2 로. (문서, 바뀌었나). 이미 v2 면 그대로."""
    if doc.get("schema_version") == SCHEMA_VERSION:
        return doc, False
    by_id = {e["id"]: _v1_to_v2_record(e) for e in doc.get("events", [])}
    for m in MERGES:
        keep = by_id.get(m["keep"])
        if not keep:
            continue
        for aid in m["absorb"]:
            a = by_id.pop(aid, None)
            if not a:
                continue
            keep["merged_from"].append(aid)
            keep["sources"] = (keep.get("sources") or []) + [s for s in (a.get("sources") or []) if s not in (keep.get("sources") or [])]
            keep["note"] = (keep.get("note") or "") + f"\n[합침 {aid} · {a.get('date')} · {a.get('title')}] {a.get('note') or ''}".rstrip()
            if a.get("amount_usd_bn") is not None and keep.get("amount_usd_bn") is None:
                keep["amount_usd_bn"] = a["amount_usd_bn"]
            for s in a.get("sectors") or []:
                if s not in keep["sectors"]:
                    keep["sectors"].append(s)
            keep["updates"].append({"date": "2026-10-26", "field": "merged_from", "old": None, "new": aid, "evidence": "거래 단위 변환: 같은 거래의 후속 보도"})
        _apply_stages(keep, m)
    for rid, m in RESTAGE.items():
        if rid in by_id:
            _apply_stages(by_id[rid], m)
            if m.get("note_add"):
                by_id[rid]["note"] = (by_id[rid].get("note") or "") + "\n" + m["note_add"]
    events = sorted(by_id.values(), key=lambda e: (e["date"], e["title"]))
    return {"schema_version": SCHEMA_VERSION, "as_of": doc.get("as_of", ""), "events": events}, True


def _apply_stages(e: dict, m: dict) -> None:
    for col in STAGE_DATE.values():
        e[col] = None
    for stage, d in m["stages"].items():
        e[STAGE_DATE[stage]] = d
    e["lifecycle"] = m["lifecycle"]
    if m.get("title"):
        e["title"] = m["title"]
    e["date"] = min(m["stages"].values())
    e["administration"] = administration(e["date"])


def migrate_state(state: dict) -> tuple[dict, bool]:
    """제안 목록(ai_coop_state.json)의 v1 필드(form, prior_event_hint, follow_up/lifecycle 관계)를 v2 로. 미결 제안이 화면과 반영에서 깨지지 않게."""
    if state.get("schema_version") == SCHEMA_VERSION:
        return state, False
    absorbed = {aid: m["keep"] for m in MERGES for aid in m["absorb"]}
    def ev2(ev: dict) -> dict:
        if not ev or "lifecycle" in ev and ev["lifecycle"] in LIFECYCLES:
            return ev
        ev = dict(ev)
        ev["lifecycle"] = FORM_TO_LIFECYCLE.get(ev.pop("form", None), "Rumour")
        ev.pop("prior_event_hint", None)
        return ev
    for p in state.get("proposals", []):
        if p.get("target_id") in absorbed:
            p["target_id"] = absorbed[p["target_id"]]
        pl = p.get("payload") or {}
        if p.get("task") == "A":
            p["payload"] = ev2(pl)
            for s in p.get("extra_sources") or []:
                if "form" in s:
                    s["lifecycle"] = FORM_TO_LIFECYCLE.get(s.pop("form"), None)
            if p.get("form_variants"):
                p["lifecycle_variants"] = [FORM_TO_LIFECYCLE.get(f, f) for f in p.pop("form_variants")]
        elif p.get("task") == "B":
            if pl.get("new_event"):
                pl["new_event"] = ev2(pl["new_event"])
            if pl.get("lifecycle") and pl["lifecycle"] not in LIFECYCLES:   # 옛 진행 상태 → 취소만 뜻이 남는다
                pl["canceled"] = 1 if pl["lifecycle"] == "cancelled" else 0
                pl["note_v1_lifecycle"] = pl.pop("lifecycle")
            pl.setdefault("stage_date", None)
        elif p.get("task") == "C":
            for d in pl.get("diffs", []):
                if d.get("field") == "form":
                    d["field"] = "lifecycle"
                    d["old"] = FORM_TO_LIFECYCLE.get(d.get("old"), d.get("old"))
                    d["new"] = FORM_TO_LIFECYCLE.get(d.get("new"), d.get("new"))
    state["schema_version"] = SCHEMA_VERSION
    return state, True


# ------------------------------------------------------------------ Task A 프롬프트


SYSTEM_RULES = """당신은 한미 AI 협력 거래 데이터베이스의 코딩 보조자다. 기사 한 건을 읽고 스키마에 맞는 거래를 추출한다. 기사에 없는 사실을 만들지 않는다.

[거래의 정의 — 레코드 하나 = 거래 하나]
미국 측 당사자와 한국 측 당사자가 모두 명시된, AI·반도체·데이터센터·로봇·자율주행·전장(차량 AI)·AI 규제 관련 협력 또는 상거래 하나. 한쪽만 있으면 거래가 아니다(events 를 빈 배열로). 미국 국내법·정책이 한국 기업에 영향을 주는 것(예: CHIPS Act)은 양측 주체가 있어도 lifecycle=Rumour, sectors 에 통상·규제를 넣는다.

[기사 하나에 거래 여러 개]
정상회담·서밋·패키지 발표처럼 한 기사가 여러 거래를 묶어 보도하면, 거래마다 하나씩 events 배열에 넣는다(예: 정부 공동선언 1건 + 삼성–브로드컴 MOU 1건 + SK–엔비디아 협력 1건). 각 거래의 parties 에는 그 거래의 당사자만 넣고 기사에 등장한 다른 기관을 섞지 않는다. 묶음 전체를 하나의 우산 거래로 만들지 않는다.

[lifecycle 판정 — 거래가 이 기사 시점에 도달한 단계 (연구자 결정 2026-10-26). 다섯 값 가운데 하나]
- Rumour: 거래가 공개됐으나 양측이 서명한 문서가 없다. 정부 공동성명·팩트시트·회담 결과·협의체 출범, 기업의 투자 계획·협력 의사 발표, "추진 중" 보도.
- Signed: 양측이 서명한 비구속 문서. MOU·LOI·업무협약·양해각서·기본합의. 문서 종류가 특정되지 않았으나 양측이 공동 발표한 "파트너십·협력하기로·선정"도 여기(구속 조항이 확인되지 않으므로).
- Contracted: 구속력 있는 문서 체결. 계약, 인수 계약, 지분 투자 계약, 합작법인 설립, 장기 공급계약, 라이선스 계약, 본계약, 협약(agreement) 체결. 구속 조항이 명시된 MOA·기본계약도 여기. 금액이 비공개여도 인정한다.
- Operating: 이행이 실제로 시작됐다. 자금 집행(1차 납입), 착공, 양산 개시, 제품 출시·공급 개시, 서비스 개시. 기사가 그 거래의 첫 보도라도 이행이 시작됐으면 Operating 이다.
- Completed: 거래가 약속한 산출이 완결됐다. 인수·지분 취득 종결(closing), 시설 준공·가동 개시, 투자금 전액 집행, 계약 물량 납품 완료, 공식 종료 선언. 끝이 정해지지 않은 공급·파트너십은 Operating 에 머문다.
문면으로 가릴 수 없으면 낮은 단계(Rumour < Signed < Contracted < Operating < Completed)를 고르고 confidence 를 낮춘다. "예정·계획·목표"는 그 단계에 도달한 것이 아니다(2027년 양산 예정 → Operating 아님).
[canceled] 기사가 그 거래의 철회·취소·무산·관계 종료를 전하면 true. 지연·축소는 false(note 에 적는다).

[track — 양측 당사자의 성격 (연구자 결정 2026-10-22)]
정부-정부(양쪽 모두 정부·공공기관) / 민간-민간(양쪽 모두 기업·민간) / 정부-민간(한쪽만 정부이거나 한쪽에 정부와 기업이 함께). 당사자만 보고 판정하며, 행사 주최·참석은 당사자가 아니다.

[sectors] AI데이터센터, 피지컬AI·로봇, 통상·규제, 파운드리, 반도체·메모리, AI모델·SW, 안보·국방, 전력·인프라, 인재. 복수 가능. 기사에 근거가 있는 것만.
[parties] 아래 [기관 표기] 목록의 표준 표기를 쓴다. 목록에 없으면 기사 표기 그대로. 정부는 "정부(미국)", "정부(한국)" 또는 부처명. 그룹은 기사에 나온 법인만(현대차그룹이면 명시된 계열사; 없으면 현대차).
[amount_usd_bn] 거래금액만, 억 달러 숫자. 기업가치·시가총액·패키지 총액·투자 계획 총액은 금액이 아니라 note 에 적는다(연구자 결정 2026-10-22). 원화만 있으면 amount_krw_bn 에 억 원. 범위("수십억", "최대")면 null 로 두고 note 에 적는다.
[date] 그 단계에 도달한 발표일(YYYY-MM-DD). 기사 게재일과 다르면 발표일.
[title] 20자 안팎, "주체–주체, 내용(금액)" 형식. 단계가 아니라 거래를 가리키는 이름으로 쓴다. [summary] 2~3문장, 기사 사실만.
[confidence] 0~1. lifecycle 판정과 주체 식별이 모두 분명하면 0.9 이상, 어느 하나가 기사 문면으로 확정되지 않으면 0.6 이하.
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
        "lifecycle": {"anyOf": [{"type": "string", "enum": LIFECYCLES}, {"type": "null"}]},
        "canceled": {"type": "boolean"},
        "sectors": {"type": "array", "items": {"type": "string", "enum": SECTORS}},
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "amount_usd_bn": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "amount_is_estimate": {"type": "boolean"},
        "amount_krw_bn": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "source_grade": {"type": "integer", "enum": [1, 2]},
        "confidence": {"type": "number"},
        "note": {"type": "string"},
    },
    "required": ["date", "us_parties", "kr_parties", "track", "lifecycle", "canceled", "sectors", "title", "summary",
                 "amount_usd_bn", "amount_is_estimate", "amount_krw_bn", "source_grade", "confidence", "note"],
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
        # 예시의 date 는 그 거래가 처음 관측된 단계의 날짜(거래 레코드의 date). lifecycle 은 그 시점의 단계 = 레코드의 첫 단계.
        first_stage = next((s for s in LIFECYCLES if e.get(STAGE_DATE[s]) == e["date"]), e["lifecycle"])
        answer = {"date": e["date"], "us_parties": e["us_parties"], "kr_parties": e["kr_parties"],
                  "track": e["track"], "lifecycle": first_stage, "canceled": bool(e.get("canceled")), "sectors": e["sectors"], "title": e["title"],
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
    """출처 확보 순서.
    0) 같은 사건의 정부 공식 문서·기업 보도자료 원문(GRADE1_HINTS)이 검색되면 그것이 1순위 출처. 기사는 article_url 로 보조 출처
       (연구자 지시 2026-10-24: 구글뉴스는 수집처일 뿐 원천이 아니다)
    1) 기사 원문 본문  2) 유료벽·짧음이면 같은 사건의 다른 무료 출처  3) 제목(+RSS 요약)만, 확신도 상한 0.5 (유료벽 3단계, 2026-10-22).
    돌려주는 dict 에 코딩에 쓴 원문(text)을 그대로 담는다 — 재현성."""
    import hashlib as _h
    tried = []

    def pack(kind, url, via, text, extra=None):
        rec = {"kind": kind, "url": url, "via": via, "chars": len(text), "sha256": _h.sha256(text.encode("utf-8")).hexdigest(),
               "text": text, "tried": tried}
        if extra:
            rec.update(extra)
        return rec

    article, article_meta = "", {}
    if source_url:
        article, article_meta = fetch_body(source_url)
        tried.append({"step": 1, "url": source_url, "chars": len(article)})
    has_article = len(article) >= 300
    cands = search_alternatives(title, date) if title else []
    picked = []
    for c in cands[:8]:
        real = _decode_gnews(c["link"]) if c["engine"] == "google" else c["link"]
        if not real or any(d in real for d in PAYWALL_DOMAINS) or real == source_url:
            continue
        official = any(h in real for h in GRADE1_HINTS)
        if has_article and not official:
            continue   # 기사 본문이 이미 있으면 공식 원문만 찾는다
        body, meta = fetch_body(real)
        tried.append({"step": 0 if official else 2, "url": real, "chars": len(body), "title": c.get("title", "")})
        if len(body) >= 300:
            picked.append((0 if official else 1, -len(body), real, body, meta))
            if official:
                break
    picked.sort()
    if picked and (picked[0][0] == 0 or not has_article):
        rank, _, real, body, meta = picked[0]
        return pack("body", real, ("official:" if rank == 0 else "alternative:") + meta.get("via", "direct"), body,
                    {"meta": meta, "article_url": source_url})
    if has_article:
        return pack("body", source_url, article_meta.get("via", "direct"), article, {"meta": article_meta})
    text = title + ("\n\n" + rss_summary if rss_summary else "")
    return pack("title", source_url, "none", text, {"body_missing": True})


def clip(body: str, head: int = 6000, tail: int = 2000) -> str:
    # 토큰이 아니라 글자 기준의 느슨한 상한(한글 1자 ≈ 1~2토큰). 8천 자를 넘으면 앞·뒤만 남긴다.
    return body if len(body) <= head + tail else body[:head] + "\n...(중략)...\n" + body[-tail:]


# ------------------------------------------------------------------ 공통


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
