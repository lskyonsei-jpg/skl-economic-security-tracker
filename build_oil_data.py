"""D-3(석유제품) 원자료를 oil.html 패널이 쓸 컴팩트 JSON으로 정리한다.

- 2026-08-30: HS 2711(LPG 등 석유가스)을 추가했다. 원유(2709)·정제품(2710)과
  같은 스키마로 받아 그냥 이어붙인 파일이라 이 스크립트의 그룹핑 로직은
  그대로다 — cmdCode가 2711인 행이 같이 집계될 뿐이다.
- 2026-08-30(같은 날 두 번째 변경): HS 2711을 4자리 그대로 두지 않고 6자리
  하위코드 7개(comtrade_oil_2711_hs6_raw.csv)로 재수집해 LNG·파이프라인가스·
  LPG·기타가스 네 갈래로 다시 묶는다. "LPG"는 HS에 단일 코드가 없어(프로판
  271112·부탄 271113·기타 액화가스 271119를 합친 업계 관행상 근사치) 세
  코드를 합산한다. 271121(파이프라인 기체상태 천연가스)은 러시아→유럽 가스관
  등 제재 국면에서 물량이 크고 이 사이트 주제(러-우 제재)와 직결돼 "기타"에
  묻지 않고 따로 뺐다. 남는 271114(액화 올레핀류)·271129(기타 기체)는 물량이
  작아 "기타가스"로 합친다. 옛 4자리 comtrade_oil_2711_raw.csv는 더 안 쓴다
  (남겨는 두되 이 스크립트가 읽지 않는다).

- reporterCode/partnerCode(Comtrade 숫자코드) -> ISO3 (comtrade_reporters/
  partnerAreas.json, 2026-08-29 UN Comtrade 공개 레퍼런스에서 받음 — 쿼터 없는
  엔드포인트라 API 키 없이 받았다)
- ISO3 -> 클럽(US/CN/NON/UNK)은 bloc_site.py의 build_blocs()를 그대로 재사용한다
  (BSV 2021 IPD 기준, 같은 판단을 두 화면에 일관되게 적용).
  bloc_site.build_blocs()는 국가명(Countryname) 키인데, BSV tab 파일 자체에
  iso3c 컬럼이 있어서 여기서는 이름 매핑 없이 ISO3로 직접 조인한다 — GTA
  이름표기 문제(NAME_TO_BSV)를 아예 피해간다.
- World(W00)·지역 그룹(코드 472 등, isGroup=True) 파트너는 제외한다 — 실제
  국가 간 양자무역만 남긴다.
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

import pandas as pd

import bloc_site as bs

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RAW_2709_2710 = ROOT / "05_국정원과제/02_원자료/comtrade_oil_2709_2710_raw.csv"
RAW_2711_HS6 = ROOT / "05_국정원과제/02_원자료/comtrade_oil_2711_hs6_raw.csv"
REF_DIR = HERE / "reference"
BSV_PATH = bs.BSV

# HS 2711 6자리 하위코드 -> 이 사이트가 쓰는 4개 버킷. LPG는 HS에 단일 코드가
# 없어 프로판·부탄·기타 액화가스를 합친 업계 관행상 근사치다. 271121(파이프라인
# 천연가스)은 물량이 크고 제재 국면과 직결돼 따로 둔다. 나머지(액화 올레핀류·
# 기타 기체상태)는 물량이 작아 GAS_OTHER로 합친다.
HS2711_BUCKET = {
    "271111": "LNG",
    "271121": "PIPE",
    "271112": "LPG", "271113": "LPG", "271119": "LPG",
    "271114": "GAS_OTHER", "271129": "GAS_OTHER",
}


def load_code_to_iso3() -> dict[str, str]:
    """reporterCode/partnerCode(둘 다 같은 M49 계열 숫자) -> ISO3.
    partnerAreas가 더 넓은 목록(그룹 포함)이라 기본으로 쓰고, reporters로 보강한다.

    UN Comtrade의 490(Other Asia, nes/S19)은 이 사이트에서 대만 대용치로
    고정해 TWN으로 정규화한다. 원자료의 숫자코드는 CSV에 그대로 남는다.
    """
    out: dict[str, str] = {}
    with (REF_DIR / "comtrade_partners.json").open(encoding="utf-8") as fh:
        for row in json.load(fh)["results"]:
            iso3 = row.get("PartnerCodeIsoAlpha3")
            if iso3 and not row.get("isGroup"):
                out[str(row["PartnerCode"])] = iso3
    with (REF_DIR / "comtrade_reporters.json").open(encoding="utf-8") as fh:
        for row in json.load(fh)["results"]:
            iso3 = row.get("reporterCodeIsoAlpha3")
            if iso3 and not row.get("isGroup"):
                out.setdefault(str(row["reporterCode"]), iso3)
    out["490"] = "TWN"
    return out


def load_iso3_to_name() -> dict[str, str]:
    """ISO3 -> 이름. 같은 ISO3에 이름이 여러 개 걸리는 경우(독일 DEU가
    "Germany"(276, 현재)와 "Fed. Rep. of Germany (...1990)"(280, 통일 전
    서독) 둘 다로 잡히는 게 대표적 — 통일 후에도 옛 코드가 무역 상대국
    코드북에 남아 있다)가 있어, "(...연도)"로 끝나는 폐기된 표기보다
    현재 표기를 우선한다. 첫 항목을 그냥 집는 setdefault만 쓰면 파일
    순서에 따라 옛 이름이 뽑힐 수 있다."""
    import re
    STALE = re.compile(r"\(\.\.\.\d{4}\)\s*$")
    out: dict[str, str] = {}
    for row in json.load((REF_DIR / "comtrade_partners.json").open(encoding="utf-8"))["results"]:
        iso3 = row.get("PartnerCodeIsoAlpha3")
        name = row.get("PartnerDesc")
        if not iso3 or not name:
            continue
        if iso3 not in out or (STALE.search(out[iso3]) and not STALE.search(name)):
            out[iso3] = name
    out["TWN"] = "Taiwan"
    return out


def build_blocs_by_iso3() -> dict[str, str]:
    """bloc_site.build_blocs()와 같은 로직(BSV 2021 IPD, 상/하위 25%)이지만
    Countryname이 아니라 iso3c로 키를 잡는다."""
    pos: dict[tuple[int, str], float] = {}
    with BSV_PATH.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter="\t"):
            iso3 = r["iso3c"].strip('"')
            pos[(int(r["year"]), iso3)] = float(r["IdealPointFP"])

    us_y, cn_y = pos[(bs.TARGET_YEAR, "USA")], pos[(bs.TARGET_YEAR, "CHN")]
    seg: dict[str, float] = {}
    all_iso3 = {c for (_, c) in pos}
    for c in all_iso3:
        if c in ("USA", "CHN"):
            continue
        v = bs.seg_at(pos, bs.TARGET_YEAR, c, us_y, cn_y)
        if v is not None:
            seg[c] = v
    seg["USA"], seg["CHN"] = 1.0, -1.0

    have_years: dict[str, set[int]] = defaultdict(set)
    for (y, c) in pos:
        have_years[c].add(y)
    for c in all_iso3 - set(seg) - {"USA", "CHN"}:
        years = sorted(y for y in have_years[c] if y <= bs.TARGET_YEAR)
        if not years:
            continue
        y = years[-1]
        uy, cy = pos.get((y, "USA")), pos.get((y, "CHN"))
        if uy is None or cy is None:
            continue
        v = bs.seg_at(pos, y, c, uy, cy)
        if v is not None:
            seg[c] = v

    items = sorted(seg.items(), key=lambda kv: kv[1])
    n = len(items)
    q = n // 4
    out: dict[str, str] = {}
    for i, (c, _) in enumerate(items):
        out[c] = "CN" if i < q else "US" if i >= n - q else "NON"
    return out


def build(out_dir: Path) -> bool:
    if not RAW_2709_2710.is_file() or not RAW_2711_HS6.is_file():
        print("[build_oil_data] 원자료 없음 — 건너뜀")
        return False

    code_to_iso3 = load_code_to_iso3()
    iso3_to_name = load_iso3_to_name()
    blocs = build_blocs_by_iso3()

    df = pd.concat(
        [pd.read_csv(RAW_2709_2710, dtype=str), pd.read_csv(RAW_2711_HS6, dtype=str)],
        ignore_index=True,
    )
    df["cmdCode"] = df["cmdCode"].replace(HS2711_BUCKET)
    df["reporter_iso3"] = df["reporterCode"].map(code_to_iso3)
    df["partner_iso3"] = df["partnerCode"].map(code_to_iso3)
    before = len(df)
    df = df.dropna(subset=["reporter_iso3", "partner_iso3"])
    dropped = before - len(df)

    # (보고국,상대국,기간,품목,흐름) 은 이미 classic 모드라 유일해야 하지만,
    # 만약을 위해 합산한다.
    df["primaryValue"] = df["primaryValue"].astype(float)
    grouped = (
        df.groupby(["reporter_iso3", "partner_iso3", "period", "cmdCode", "flowCode"])
        ["primaryValue"].sum().reset_index()
    )

    # 페이로드를 줄이기 위해 객체가 아니라 배열로 직렬화한다.
    rows = grouped[["reporter_iso3", "partner_iso3", "period", "cmdCode", "flowCode", "primaryValue"]].values.tolist()
    rows = [[a, b, c, d, e, round(f)] for a, b, c, d, e, f in rows]

    iso3_present = {r[0] for r in rows} | {r[1] for r in rows}
    countries = {
        iso3: {"name": iso3_to_name.get(iso3, iso3), "club": blocs.get(iso3, "UNK")}
        for iso3 in sorted(iso3_present)
    }

    payload = {"rows": rows, "countries": countries, "generated": "2026-08-30"}
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "oil_trade.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    print(f"[build_oil_data] 행 {len(rows):,}개(원본 {before:,}, 매핑 실패로 제외 {dropped:,}), "
          f"국가 {len(countries)}개 -> {out_path} ({out_path.stat().st_size/1e6:.1f}MB)")
    return True


if __name__ == "__main__":
    build(HERE / "site")
