"""패널 1 의 기준자료 3종을 API 로 받아 data/reference/ 에 쓴다. GitHub Actions 가 월 1회 돌린다.

  python collect_reference.py [--only bsv dots wdi] [--bsv-file-id N | --bsv-latest]

산출(열 이름은 옛 정적 사본과 같다. ip_risk_site.py 가 읽는다)
  bsv_ideal_points.tab          탭 구분. ccode iso3c Countryname year NVotesFP IdealPointFP Q5%FP … Q95%FP
  imf_dots_us_cn_total_trade.csv  reporter, partner_iso3, year, trade_total_usd (= 수출 FOB + 수입 CIF)
  wdi_gdp_current_usd.csv       iso3, country, year, gdp_usd (집계 단위 제외)
  reference_manifest.json       수집 시각·출처·행 수

출처
  BSV  Harvard Dataverse doi:10.7910/DVN/LEJUQZ (Bailey·Strezhnev·Voeten, CC0). 파일은 BSV_FILE_ID 로 고정한다.
       같은 이름의 파일이라도 판(version)마다 다시 추정돼 값이 달라진다(2026-10-22 실측: v39 vs 로컬 사본
       상관 0.9993, 최대 차이 0.76). 블록 분류가 흔들리므로 올릴 때는 ID 를 바꾸고 결과 변화를 확인한다.
       --bsv-latest 는 최신 판의 IdealpointestimatesFP_*.csv 를 고른다(점검용).
  DOTS IMF SDMX 2.1, dataflow IMF.STA:IMTS. 질의 {USA,CHN}.XG_FOB_USD+MG_CIF_USD..A, 2010~. 상대국 G001 = World.
  WDI  World Bank API NY.GDP.MKTP.CD, 2010~. /v2/country 의 region == "Aggregates" 를 제외.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
OUT = HERE / "data" / "reference"
DATAVERSE = "https://dataverse.harvard.edu"
BSV_DOI = "doi:10.7910/DVN/LEJUQZ"
BSV_FILE_ID = 14098429          # IdealpointestimatesFP_2026FP.csv, dataset v39 (2026-07-30)
BSV_COLUMNS = ["ccode", "iso3c", "Countryname", "year", "NVotesFP", "IdealPointFP",
               "Q5%FP", "Q10%FP", "Q50%FP", "Q90%FP", "Q95%FP"]
IMF = "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,IMTS"
WB = "https://api.worldbank.org/v2"
START_YEAR = 2010
UA = {"User-Agent": "skl-economic-security-tracker (github.com/lskyonsei-jpg)"}


def get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=300, **kw)
    r.raise_for_status()
    return r


# ------------------------------------------------------------------ BSV


def bsv_latest_file_id() -> tuple[int, str]:
    d = get(f"{DATAVERSE}/api/datasets/:persistentId/", params={"persistentId": BSV_DOI}).json()["data"]
    files = [(f["dataFile"]["id"], f["dataFile"]["filename"]) for f in d["latestVersion"]["files"]
             if f["dataFile"]["filename"].startswith("IdealpointestimatesFP_") and f["dataFile"]["filename"].endswith(".csv")]
    if not files:
        raise RuntimeError("Dataverse 최신 판에 IdealpointestimatesFP_*.csv 가 없습니다.")
    return sorted(files, key=lambda x: x[1])[-1]


def collect_bsv(file_id: int) -> dict:
    raw = get(f"{DATAVERSE}/api/access/datafile/{file_id}", params={"format": "original"}).content
    df = pd.read_csv(io.BytesIO(raw))
    missing = [c for c in BSV_COLUMNS if c not in df.columns]
    if missing:
        raise RuntimeError(f"BSV 파일에 기대한 열이 없습니다: {missing} (있는 열: {list(df.columns)})")
    df = df[BSV_COLUMNS].copy()
    df["year"] = df["year"].astype(int)
    df = df.dropna(subset=["iso3c", "IdealPointFP"]).sort_values(["ccode", "year"])
    path = OUT / "bsv_ideal_points.tab"
    df.to_csv(path, sep="\t", index=False, quoting=csv.QUOTE_NONNUMERIC)
    return {"file": path.name, "rows": int(len(df)), "entities": int(df["iso3c"].nunique()),
            "years": [int(df["year"].min()), int(df["year"].max())], "dataverse_file_id": file_id}


# ------------------------------------------------------------------ IMF DOTS(IMTS)


def collect_dots() -> dict:
    rows = []
    for reporter in ("USA", "CHN"):
        d = get(f"{IMF}/{reporter}.XG_FOB_USD+MG_CIF_USD..A", params={"startPeriod": START_YEAR},
                headers={"Accept": "application/json"}).json()
        dims = d["structure"]["dimensions"]
        series_dims = [[v["id"] for v in dim["values"]] for dim in dims["series"]]
        time_values = [v["id"] for v in dims["observation"][0]["values"]]
        pos = {dim["id"]: i for i, dim in enumerate(dims["series"])}
        agg: dict[tuple[str, int], float] = {}
        for key, ser in d["dataSets"][0]["series"].items():
            idx = [int(k) for k in key.split(":")]
            partner = series_dims[pos["COUNTERPART_COUNTRY"]][idx[pos["COUNTERPART_COUNTRY"]]]
            for t, obs in ser["observations"].items():
                if obs[0] is None:
                    continue
                year = int(time_values[int(t)])
                agg[(partner, year)] = agg.get((partner, year), 0.0) + float(obs[0])
        rows += [{"reporter": reporter, "partner_iso3": p, "year": y, "trade_total_usd": v} for (p, y), v in agg.items()]
    df = pd.DataFrame(rows).sort_values(["reporter", "partner_iso3", "year"])
    if not {("USA"), ("CHN")} <= set(df["reporter"]) or "G001" not in set(df["partner_iso3"]):
        raise RuntimeError("DOTS 응답에 USA/CHN 또는 World(G001) 가 없습니다.")
    path = OUT / "imf_dots_us_cn_total_trade.csv"
    df.to_csv(path, index=False)
    return {"file": path.name, "rows": int(len(df)), "years": [int(df["year"].min()), int(df["year"].max())],
            "partners": int(df["partner_iso3"].nunique())}


# ------------------------------------------------------------------ World Bank WDI


def collect_wdi() -> dict:
    countries = get(f"{WB}/country", params={"format": "json", "per_page": 400}).json()[1]
    economies = {c["id"] for c in countries if (c.get("region") or {}).get("value") != "Aggregates"}
    year_now = datetime.now().year
    meta, data = get(f"{WB}/country/all/indicator/NY.GDP.MKTP.CD",
                     params={"format": "json", "date": f"{START_YEAR}:{year_now}", "per_page": 20000}).json()
    rows = [{"iso3": r["countryiso3code"], "country": r["country"]["value"], "year": int(r["date"]), "gdp_usd": r["value"]}
            for r in data if r.get("value") is not None and r.get("countryiso3code") in economies]
    df = pd.DataFrame(rows).sort_values(["iso3", "year"])
    path = OUT / "wdi_gdp_current_usd.csv"
    df.to_csv(path, index=False)
    return {"file": path.name, "rows": int(len(df)), "economies": int(df["iso3"].nunique()),
            "years": [int(df["year"].min()), int(df["year"].max())], "lastupdated": meta.get("lastupdated")}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="+", choices=["bsv", "dots", "wdi"], default=["bsv", "dots", "wdi"])
    p.add_argument("--bsv-file-id", type=int, default=BSV_FILE_ID)
    p.add_argument("--bsv-latest", action="store_true", help="고정 ID 대신 최신 판의 파일을 쓴다")
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"run_at_utc": datetime.now(timezone.utc).isoformat(), "sources": {}}
    if "bsv" in a.only:
        fid = a.bsv_file_id
        if a.bsv_latest:
            fid, name = bsv_latest_file_id()
            print(f"[bsv] 최신 판 파일 {name} (id {fid})")
        manifest["sources"]["bsv"] = collect_bsv(fid)
        print(f"[bsv] {manifest['sources']['bsv']}")
    if "dots" in a.only:
        manifest["sources"]["dots"] = collect_dots()
        print(f"[dots] {manifest['sources']['dots']}")
    if "wdi" in a.only:
        manifest["sources"]["wdi"] = collect_wdi()
        print(f"[wdi] {manifest['sources']['wdi']}")
    (OUT / "reference_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
