"""UN Comtrade 양자무역 원자료 수집 -> data/comtrade/ 의 CSV 3종. GitHub Actions 가 월 1회 돌린다.

  python collect_comtrade.py [--years 2010-2026] [--only oil gas solar] [--preview]

산출(열 이름은 API 응답 그대로. 빌더는 reporterCode, partnerCode, period, cmdCode,
flowCode, primaryValue 를 쓴다)
  comtrade_oil_2709_2710_raw.csv        HS 2709·2710
  comtrade_oil_2711_hs6_raw.csv         HS 2711 하위 6자리 7개
  comtrade_solar_854142_854143_raw.csv  854140(~2021) + 854142·854143(2022~)
  comtrade_manifest.json

호출 단위  (품목 묶음, 연도, 흐름 M/X) 하나에 보고국·상대국 전체. 고전(classic) 집계만:
           partner2Code=0, customsCode=C00, motCode=0. 이 조합이 없으면 세부 행이 섞여 합산이 중복된다.
한도       무료 키: 하루 500회, 호출당 100,000행. 상한에 닿으면 보고국을 나눠 다시 받는다.
           전량 약 136회. 키는 환경변수 COMTRADE_API_KEY.
--preview  키 없는 공개 미리보기(500행 상한)로 열 이름만 확인한다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "comtrade"
REPORTERS = HERE / "reference" / "comtrade_reporters.json"
DATA_URL = "https://comtradeapi.un.org/data/v1/get/C/A/HS"
PREVIEW_URL = "https://comtradeapi.un.org/public/v1/preview/C/A/HS"
HS2711_HS6 = ["271111", "271112", "271113", "271114", "271119", "271121", "271129"]
TARGETS = {
    "oil": ("comtrade_oil_2709_2710_raw.csv", lambda y: ["2709", "2710"]),
    "gas": ("comtrade_oil_2711_hs6_raw.csv", lambda y: HS2711_HS6),
    "solar": ("comtrade_solar_854142_854143_raw.csv", lambda y: ["854140"] if y <= 2021 else ["854142", "854143"]),
}
CORE = ["reporterCode", "partnerCode", "period", "cmdCode", "flowCode", "primaryValue"]


class Api:
    def __init__(self, key: str | None, preview: bool) -> None:
        self.s = requests.Session()
        if key:
            self.s.headers["Ocp-Apim-Subscription-Key"] = key
        self.url, self.cap = (PREVIEW_URL, 500) if preview else (DATA_URL, 100_000)
        self.calls = 0

    def get(self, **params) -> list[dict]:
        q = {"partner2Code": 0, "customsCode": "C00", "motCode": 0, "includeDesc": "false"}
        q.update({k: v for k, v in params.items() if v is not None})
        for attempt in range(6):
            r = self.s.get(self.url, params=q, timeout=180)
            self.calls += 1
            if r.status_code == 200:
                body = r.json()
                if body.get("error"):
                    raise RuntimeError(f"Comtrade 오류: {body['error']}")
                return body.get("data", [])
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "60")))
            elif r.status_code in (401, 403):
                raise RuntimeError(f"인증 실패 {r.status_code}: COMTRADE_API_KEY 확인")
            elif r.status_code >= 500:
                time.sleep(min(60, 5 * 2 ** attempt))
            else:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        raise RuntimeError("재시도 6회 실패")


def reporters() -> list[int]:
    rows = json.loads(REPORTERS.read_text(encoding="utf-8"))["results"]
    return sorted(int(r["reporterCode"]) for r in rows if not r.get("isGroup"))


def block(api: Api, year: int, cmds: list[str], flow: str) -> list[dict]:
    rows = api.get(period=year, cmdCode=",".join(cmds), flowCode=flow)
    if len(rows) < api.cap:
        return rows
    out: list[dict] = []
    codes = reporters()
    for i in range(0, len(codes), 40):
        part = api.get(period=year, cmdCode=",".join(cmds), flowCode=flow, reporterCode=",".join(map(str, codes[i:i + 40])))
        if len(part) >= api.cap:
            for code in codes[i:i + 40]:
                one = api.get(period=year, cmdCode=",".join(cmds), flowCode=flow, reporterCode=code)
                if len(one) >= api.cap:
                    raise RuntimeError(f"보고국 {code} {year} {flow} 단독으로 {api.cap:,}행 초과. 품목을 나눌 것")
                out.extend(one)
                time.sleep(1)
        else:
            out.extend(part)
        time.sleep(1)
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--years", default=f"2010-{datetime.now().year}")
    p.add_argument("--only", nargs="+", choices=list(TARGETS), default=list(TARGETS))
    p.add_argument("--preview", action="store_true")
    a = p.parse_args()
    key = os.environ.get("COMTRADE_API_KEY", "").strip() or None
    if not key and not a.preview:
        print("[collect_comtrade] COMTRADE_API_KEY 없음")
        return 1
    y0, _, y1 = a.years.partition("-")
    years = list(range(int(y0), int(y1 or y0) + 1))
    api = Api(key, a.preview)
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "years": [years[0], years[-1]],
                "preview": a.preview, "files": {}}
    for name in a.only:
        filename, cmds_of = TARGETS[name]
        frames = []
        for year in years:
            for flow in ("M", "X"):
                rows = (api.get(period=year, cmdCode=",".join(cmds_of(year)), flowCode=flow, reporterCode=410)
                        if a.preview else block(api, year, cmds_of(year), flow))
                frames.append(pd.DataFrame(rows))
                print(f"[{name}] {year} {flow} {len(rows):>7,}행 (호출 {api.calls})", flush=True)
                time.sleep(0.3 if a.preview else 1.2)
                if a.preview:
                    break
            if a.preview:
                break
        df = pd.concat([f for f in frames if not f.empty], ignore_index=True) if any(not f.empty for f in frames) else pd.DataFrame()
        missing = [c for c in CORE if c not in df.columns]
        if missing:
            print(f"[{name}] 빌더가 쓰는 열이 응답에 없음: {missing}")
            return 2
        dup = int(df.duplicated(subset=CORE[:5]).sum())
        if dup:
            print(f"[{name}] 경고: 키 중복 {dup:,}행 — classic 집계가 아닐 수 있음")
        path = OUT / (filename.replace("_raw.csv", "_preview.csv") if a.preview else filename)
        df.to_csv(path, index=False, encoding="utf-8")
        manifest["files"][path.name] = {"rows": int(len(df)), "columns": list(df.columns), "duplicate_keys": dup}
        print(f"[{name}] 저장 {path.relative_to(HERE)} ({len(df):,}행)")
    manifest["calls"] = api.calls
    (OUT / ("comtrade_preview_manifest.json" if a.preview else "comtrade_manifest.json")).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"완료: 호출 {api.calls}회")
    return 0


if __name__ == "__main__":
    sys.exit(main())
