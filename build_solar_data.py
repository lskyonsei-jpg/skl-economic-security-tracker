"""태양광(셀·모듈) 원자료(comtrade_solar_854142_854143_raw.csv)를 solar.html
패널이 쓸 컴팩트 JSON으로 정리한다. build_oil_data.py를 그대로 본떴다.

- HS 코드가 2022년 개정으로 바뀌었다: 2010~2021은 854140(셀·모듈 통합),
  2022~은 854142(셀)·854143(모듈)로 분리돼 있다. 오일과 달리 이 패널은
  품목 토글을 두지 않고 (보고국,상대국,기간,흐름) 기준으로 코드를 모두
  합산해 '태양광 전체'라는 하나의 연속 시계열만 만든다 — 사용자 확인
  결과다(2026-08-30).
- reporterCode/partnerCode(Comtrade 숫자코드) -> ISO3는 build_oil_data.py와
  같은 레퍼런스 파일(comtrade_reporters/partnerAreas.json)을 재사용한다.
  Comtrade 490(Other Asia, nes/S19)은 대만 대용치로 보고 TWN으로 정규화한다.
- ISO3 -> 클럽(US/CN/NON/UNK)도 bloc_site.py의 build_blocs()를 그대로
  재사용한다(BSV 2021 IPD 기준, 다른 패널들과 같은 판단 일관 적용).
- World(W00)·지역 그룹 파트너는 제외한다 — 실제 국가 간 양자무역만 남긴다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import build_oil_data as bod  # ISO3 매핑·클럽 분류 로직 재사용

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW = ROOT / "05_국정원과제/02_원자료/comtrade_solar_854142_854143_raw.csv"


def build(out_dir: Path) -> bool:
    if not RAW.is_file():
        print("[build_solar_data] 원자료 없음 — 건너뜀")
        return False

    code_to_iso3 = bod.load_code_to_iso3()
    iso3_to_name = bod.load_iso3_to_name()
    blocs = bod.build_blocs_by_iso3()

    df = pd.read_csv(RAW, dtype=str)
    df["reporter_iso3"] = df["reporterCode"].map(code_to_iso3)
    df["partner_iso3"] = df["partnerCode"].map(code_to_iso3)
    before = len(df)
    df = df.dropna(subset=["reporter_iso3", "partner_iso3"])
    dropped = before - len(df)

    # 854140(2010-2021)과 854142+854143(2022-)을 (보고국,상대국,기간,흐름)
    # 기준으로 합산한다 — 품목 토글 없이 '태양광 전체' 연속 시계열 하나로 만든다.
    df["primaryValue"] = df["primaryValue"].astype(float)
    grouped = (
        df.groupby(["reporter_iso3", "partner_iso3", "period", "flowCode"])
        ["primaryValue"].sum().reset_index()
    )

    rows = grouped[["reporter_iso3", "partner_iso3", "period", "flowCode", "primaryValue"]].values.tolist()
    rows = [[a, b, c, d, round(e)] for a, b, c, d, e in rows]

    iso3_present = {r[0] for r in rows} | {r[1] for r in rows}
    countries = {
        iso3: {"name": iso3_to_name.get(iso3, iso3), "club": blocs.get(iso3, "UNK")}
        for iso3 in sorted(iso3_present)
    }

    payload = {"rows": rows, "countries": countries, "generated": "2026-08-30",
               "note": "HS 854140(2010-2021) + HS 854142/854143(2022-) 합산, 품목 구분 없음"}
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "solar_trade.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[build_solar_data] 행 {len(rows):,}개(원본 {before:,}, 매핑 실패로 제외 {dropped:,}), "
          f"국가 {len(countries)}개 -> {out_path} ({out_path.stat().st_size/1e6:.1f}MB)")
    return True


if __name__ == "__main__":
    build(HERE / "site")
