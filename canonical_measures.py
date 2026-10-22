"""Distortive Industrial Policy Tracker의 표준 표본을 CSV로 고정 출력한다.

목적(2026-08-25): composition 집계에 #DUP_RULE_20260824(반복 공고 접기)를
빠뜨렸던 사고 재발 방지. "이 사이트가 다루는 조치가 정확히 몇 건인가"를
어느 화면이든 다시 계산하지 않고 이 파일 하나를 기준으로 삼게 한다.

조건 3가지(전부 AND):
  1. 산업정책 — ip_us_cn.json의 measures는 이미 D_IP_bert_3==1 AND
     implementing in {United States of America, China} AND
     date_announced >= 2010-01-01로 걸려 있다(industrial_policy_site.py).
  2. GTA 평가 Red 또는 Amber(Green 제외) — ip_risk_site.py와 동일 기준.
  3. 반복 공고 접기 — #DUP_RULE_20260824. 6필드(구현국·피영향국·조치유형·
     대상기업·대상산업·GTA평가)가 전부 같은 반복 공고는 첫 건만 남긴다
     (dup=True인 행 제외).

선택 조건(기본 꺼짐) — build(targeted_only=True)로 GTA의 AJ 등록 방식
(aj_type) 중 Targeted(명시적으로 지목)만 남길 수 있다. ip_risk_site.py의
TARGETED_ONLY와 같은 스위치다. 기본값은 False다 — Targeted가 극소수라서
(미국 35건, 중국 13건) 켜면 표본이 거의 사라진다.

부처 하드코딩 예외(예전 USDA 특례)는 2026-08-25에 완전히 없앴다 — 지금은
3조건만 적용하고 부처를 특별 취급하지 않는다. USDA류 "기관이 수취인에게
상시 프로그램을 제공"하는 패턴(EXIM·OPIC·DFC·에너지부·국방부 등도 포함,
미국에서만 관측, 921건)은 실행할 때마다 실제 수출 대상국이 달라 진짜 다른
선적 건이라 더 접지 않기로 확정했다(2026-08-25) — 6필드 기준을 그대로 쓴다.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "site" / "ip_us_cn.json"
OUT_DIR = HERE / "output"


def build(out_dir: Path = OUT_DIR, targeted_only: bool = False) -> Path:
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = [
        m for m in payload["measures"]
        if m.get("evaluation") in ("Red", "Amber") and m.get("dup") is not True
        and (not targeted_only or m.get("aj_type") == "Targeted")
    ]
    rows.sort(key=lambda m: (m["implementing"], m["date"], m["id"]))

    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = date.today().strftime("%Y%m%d")
    suffix = "_targeted" if targeted_only else ""
    out_path = out_dir / f"Distortive_Industrial_Policy_Canonical_{stamp}{suffix}.csv"

    fields = [
        "id", "implementing", "date", "date_implemented", "date_removed",
        "is_in_force", "evaluation", "aj_type", "type", "chapter", "level",
        "n_affected", "affected", "hs2", "title", "url",
    ]
    with out_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for m in rows:
            w.writerow({
                "id": m["id"], "implementing": m["implementing"], "date": m["date"],
                "date_implemented": m.get("date_implemented") or "",
                "date_removed": m.get("date_removed") or "",
                "is_in_force": m.get("is_in_force"), "evaluation": m["evaluation"],
                "aj_type": m.get("aj_type") or "",
                "type": m.get("type", ""), "chapter": m.get("chapter", ""),
                "level": m.get("level", ""), "n_affected": m.get("n_affected", 0),
                "affected": ";".join(m.get("affected", [])),
                "hs2": ";".join(m.get("hs2", [])),
                "title": m.get("title", ""), "url": m.get("url", ""),
            })

    print(f"  {out_path.name}  {len(rows):,}건 "
          f"(미국 {sum(1 for m in rows if m['implementing']=='United States of America'):,} · "
          f"중국 {sum(1 for m in rows if m['implementing']=='China'):,})")
    return out_path


if __name__ == "__main__":
    build()
