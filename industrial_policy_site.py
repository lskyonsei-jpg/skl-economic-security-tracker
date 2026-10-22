"""미중 산업정책 트래커 — 지정학적 블록(0/1) 대비 산업정책 타겟팅을 본다.

C블록(2026-08-15) 구현. 수출통제가 아니라 산업정책(D_IP_bert_3==1)만,
시행국은 미국·중국 둘로 좁힌다.

=============================================================================
#SIZE_CONFOUND_20260815 — 원시 건수는 지정학이 아니라 경제 규모를 잰다
=============================================================================
첫 판(2026-08-15 오전)은 국가당 조치 건수를 그대로 두 그룹에 놓고
Mann-Whitney 검정을 했고 미국 p=0.006, 중국 p=0.0004로 "둘 다 유의"가
나왔다. **그 결과는 버린다.** 진단이 이렇게 나왔기 때문이다.

  미국이 가장 많이 건드리는 국가: 캐나다·프랑스·중국·스페인·멕시코·이탈리아…
  중국이 가장 많이 건드리는 국가: 미국·독일·이탈리아·프랑스·오스트리아…
  상위 20개국 중 13개국이 겹친다.

즉 산업정책의 `affected_jurisdictions`는 "누구를 겨냥했나"가 아니라
"누가 경쟁 품목을 수출하나"에 가깝다. 선진 교역국은 누가 보조금을 주든
명단에 오른다. 그런데 우리 0/1 분류는 그 선진국들을 미국 기준으로는
'동맹', 중국 기준으로는 '적대'로 찍는다. 같은 사실에 라벨만 뒤집어
붙이니 "미국은 동맹을 때리고 중국은 적대를 때린다"는 정반대 결론이
자동으로 만들어진 것이다. 지정학이 아니라 국가 규모를 잰 것이다.

이는 2026-07-24 회의록의 미완료 항목 —
"GTA Affected Jurisdiction을 정책 타기팅으로 해석할 수 있는지 사례 검증"
— 에 대한 실증적 답이기도 하다. 산업정책에서는 그렇게 해석할 수 없다.

**대응: 기준선 대비 상대 강도(lift)를 쓴다.** 반도체 화면이 "걸렸나"를
버리고 "얼마나 겨냥했나(반도체 비중)"로 간 것과 같은 수다.

    lift(X) = (시행국이 X를 건드린 건수 / 시행국의 전체 건수)
              ÷ (전세계가 X를 건드린 건수 / 전세계 전체 건수)

  lift ≈ 1  그 국가 덩치만큼 걸린 것. 특별히 겨냥한 바 없음
  lift > 1  덩치가 설명하는 것보다 더 걸렸다 = 겨냥의 흔적
  lift < 1  덩치에 비해 덜 걸렸다

원시 건수도 화면에 남기되 **유의성 판단은 lift로 한다.** 두 값이 반대
방향을 가리키는 것 자체가 이 화면의 핵심 내용이다.

=============================================================================
#WITHIN_IP_INSTRUMENT — 산업정책 안의 어떤 변수인가
=============================================================================
'카테고리 내 차이'를 설명할 후보로 **정책 수단(mast_chapter)** 을 넣었다.
보조금이냐, 수출관련 조치냐, 정부조달 제한이냐에 따라 지정학적 패턴이
달라지는지를 수단별로 따로 검정한다.

검정 단위는 계속 '국가'다 — 조치 단위로 세면 한 국가가 여러 건에 반복
등장해 관측치가 독립이 아니고 유의도가 과대추정된다.
"""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
MASTER = HERE / "cache" / "master.parquet"

# 화면에 쓰는 자료의 시작 연도. 수집(auto_update.py의 START_DATE)은 2008-01-01
# 부터지만, 화면은 2010-01-01부터로 유지한다. 2026-08-18에 수집 범위를 넓히면서
# 사용자가 화면 기준은 그대로 두기로 정했다. date_announced는 'YYYY-MM-DD'
# 문자열이라 문자열 비교로 자른다.
SITE_START_DATE = "2010-01-01"
BLOC = HERE / "reference" / "geopolitical_bloc_0_1.json"
HS4_XLSX = HERE / "reference" / "HSCodeandDescription.xlsx"


def _load_hs2_labels() -> dict[str, str]:
    """HS 2자리(류) 코드 -> 품명. 사용자가 보낸 분류표(Level==2 행)만 쓴다."""
    import pandas as pd

    hs = pd.read_excel(HS4_XLSX)
    lvl2 = hs[hs["Level"] == 2]
    return {str(r.Code).zfill(2): str(r.Description) for r in lvl2.itertuples()}


def _hs2_of(affected_products) -> list[str]:
    """affected_products(HS6, 5~6자리 콤마열)에서 2자리(류) 코드 집합을 뽑는다.

    5자리로 잘려 있는 코드는 앞자리 0이 빠진 것이라 6자리로 zero-pad 후 자른다
    (관측 코드 길이는 5·6뿐이었다. 2026-08-24 확인). 2026-08-24 4자리(호)에서
    2자리(류)로 낮췄다 — 필터 목록이 1,224개라 너무 많다는 지적을 받았다.
    """
    codes = set()
    for part in _split(affected_products, ","):
        part = part.strip()
        if not part:
            continue
        codes.add(part.zfill(6)[:2])
    return sorted(codes)

IMPLEMENTERS = ["United States of America", "China"]

# 화면에 따로 검정해 보여줄 정책 수단. 나머지는 건수가 적어 묶지 않는다.
TOP_INSTRUMENTS = 6

# ---------------------------------------------------------------------------
# #DUP_RULE_20260824 — 같은 프로그램의 반복 공고를 1건으로 접는다
# ---------------------------------------------------------------------------
# 아래 6개 필드가 **전부 값이 있으면서 전부 같은** intervention은 GTA가 행정
# 공고 단위로 쪼개 올린 같은 조치로 본다. 하나만 남기고 나머지에 dup=True를
# 찍는다. 필드 중 하나라도 비어 있으면 접지 않는다 — "결측끼리 같다"를 같은
# 조치로 오인하면 서로 무관한 조치가 한 덩어리가 된다.
#
# 이 규칙은 기존 USDA 보일러플레이트 하드코딩 제외를 일반화한 것이다. 실제로
# 최대 그룹이 2022년 USDA 생산보조 302건이고, 그다음이 재무부 1603 재생에너지
# 그랜트(수혜기업만 다른 동일 프로그램) 171·124·95건이다.
# 산업정책 2010+ 기준 제거량: 미국 5,863 -> 4,000 / 중국 1,743 -> 1,645.
DUP_KEYS = [
    "implementing_jurisdictions", "affected_jurisdictions", "intervention_type",
    "eligible_firm", "affected_sectors", "gta_evaluation",
]


def _dup_ids(ip) -> set[int]:
    """6필드가 전부 유효하고 전부 같은 그룹에서 첫 건 외 나머지 intervention_id."""
    valid = ip[~ip[DUP_KEYS].map(lambda v: _text(v).strip() == "").any(axis=1)]
    ordered = valid.sort_values("intervention_id")
    dropped = ordered[ordered.duplicated(subset=DUP_KEYS, keep="first")]
    return {int(v) for v in dropped["intervention_id"]}





def _split(value, sep: str) -> list[str]:
    if value is None:
        return []
    try:
        if math.isnan(value):
            return []
    except (TypeError, ValueError):
        pass
    return [part.strip() for part in str(value).split(sep) if part.strip()]


def _text(value) -> str:
    if value is None:
        return ""
    try:
        if math.isnan(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def mann_whitney_u(a: list[float], b: list[float]) -> tuple[float | None, float]:
    """두 그룹의 분포 비교(순위합). scipy 없이 직접 계산.

    표본이 작아(그룹당 9~40개국) 정규근사가 거칠다 — 화면에 명시한다.
    동률은 평균 순위로 처리. 반환: (a그룹 U통계량, 양측 p값)
    """
    n1, n2 = len(a), len(b)
    if n1 == 0 or n2 == 0:
        return None, 1.0
    tagged = sorted([(v, 0) for v in a] + [(v, 1) for v in b], key=lambda t: t[0])
    n = len(tagged)
    ranks = [0.0] * n
    i = 0
    tie_term = 0
    while i < n:
        j = i
        while j < n and tagged[j][0] == tagged[i][0]:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for k in range(i, j):
            ranks[k] = avg_rank
        t = j - i
        tie_term += t ** 3 - t
        i = j
    r1 = sum(r for (_, g), r in zip(tagged, ranks) if g == 0)
    u1 = r1 - n1 * (n1 + 1) / 2.0
    mu = n1 * n2 / 2.0
    if n <= 1:
        return u1, 1.0
    sigma2 = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1)))
    if sigma2 <= 0:
        return u1, 1.0
    z = (u1 - mu) / math.sqrt(sigma2)
    p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
    return u1, min(1.0, p)


def _median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 2) if xs else None


def _mean(xs: list[float]) -> float | None:
    return round(statistics.mean(xs), 1) if xs else None


def build_data() -> dict:
    import pandas as pd

    bloc = json.loads(BLOC.read_text(encoding="utf-8"))
    df = pd.read_parquet(MASTER)
    df = df[df["date_announced"].fillna("") >= SITE_START_DATE]
    ip = df[df["D_IP_bert_3"] == 1].copy()
    dup_ids = _dup_ids(ip)

    # ---- 기준선: 전세계 산업정책이 각 국가를 몇 번 건드렸나 -----------------
    world = Counter()
    world_total = 0
    for row in ip.to_dict("records"):
        for country in _split(row.get("affected_jurisdictions"), ";"):
            world[country] += 1
            world_total += 1

    countries_out: dict[str, list[dict]] = {}
    measures_out: list[dict] = []
    summary_out: dict[str, dict] = {}
    instruments_out: dict[str, list[dict]] = {}
    hs2_labels = _load_hs2_labels() if HS4_XLSX.is_file() else {}
    hs2_counts: Counter = Counter()

    for implementer in IMPLEMENTERS:
        ally = list(bloc[implementer]["ally"])
        adversary = list(bloc[implementer]["adversary"])

        rows = ip[
            ip["implementing_jurisdictions"].fillna("").apply(
                lambda s, imp=implementer: imp in [p.strip() for p in s.split(";")]
            )
        ]

        per_country: Counter = Counter()
        per_country_acts: dict[str, set] = {}
        by_instrument: dict[str, Counter] = {}
        imp_total = 0
        unassigned_missing = 0
        instrument_totals: Counter = Counter()

        for row in rows.to_dict("records"):
            affected = _split(row.get("affected_jurisdictions"), ";")
            chapter = _text(row.get("mast_chapter")) or "미상"
            rid = int(row["intervention_id"])
            hs2 = _hs2_of(row.get("affected_products"))
            for h in hs2:
                hs2_counts[h] += 1
            # 설명문은 싣지 않는다(2026-08-15 결정) — 파일이 13.6MB까지
            # 부풀었고 이 화면은 원문 열람이 목적이 아니다. 원문은 GTA 링크로.
            measures_out.append({
                "id": rid,
                "implementing": implementer,
                "date": _text(row.get("date_announced"))[:10],
                "date_implemented": _text(row.get("date_implemented"))[:10] or None,
                "date_removed": _text(row.get("date_removed"))[:10] or None,
                "is_in_force": int(row.get("is_in_force")) if row.get("is_in_force") is not None else None,
                # aj_type = GTA의 AJ 등록 방식 4종 중 하나(Targeted/Inferred/Excluded/
                # Incidental). Targeted만 남기는 빌드타임 스위치를 ip_risk_site.py에 뒀다.
                "aj_type": _text(row.get("inferred_jurisdictions")) or None,
                "evaluation": _text(row.get("gta_evaluation")),
                "type": _text(row.get("intervention_type")),
                "chapter": chapter,
                "title": _text(row.get("state_act_title")),
                "url": _text(row.get("intervention_url")),
                "affected": affected,
                "n_affected": len(affected),
                "dup": rid in dup_ids,
                "level": _text(row.get("implementation_level")),
                "hs2": hs2,
            })
            if not affected:
                unassigned_missing += 1
                continue
            slot = by_instrument.setdefault(chapter, Counter())
            for country in affected:
                per_country[country] += 1
                per_country_acts.setdefault(country, set()).add(rid)
                slot[country] += 1
                imp_total += 1
                instrument_totals[chapter] += 1

        def lift(country: str, counter: Counter, total: int) -> float | None:
            """기준선 대비 상대 타깃 강도. 기준선이 없는 국가는 None."""
            if total == 0 or world.get(country, 0) == 0:
                return None
            return round(
                (counter.get(country, 0) / total) / (world[country] / world_total), 2
            )

        countries = []
        for country in sorted(set(list(per_country) + ally + adversary)):
            group = 0 if country in ally else (1 if country in adversary else None)
            if group is None and per_country.get(country, 0) == 0:
                continue
            countries.append({
                "country": country,
                "group": group,
                "count": per_country.get(country, 0),
                "acts": len(per_country_acts.get(country, set())),
                "lift": lift(country, per_country, imp_total),
                "world": world.get(country, 0),
            })
        countries.sort(key=lambda x: -(x["lift"] if x["lift"] is not None else -1))

        ally_counts = [per_country.get(c, 0) for c in ally]
        adversary_counts = [per_country.get(c, 0) for c in adversary]
        ally_lift = [v for c in ally if (v := lift(c, per_country, imp_total)) is not None]
        adversary_lift = [
            v for c in adversary if (v := lift(c, per_country, imp_total)) is not None
        ]

        _, p_raw = mann_whitney_u(ally_counts, adversary_counts)
        _, p_lift = mann_whitney_u(ally_lift, adversary_lift)

        # ---- 정책 수단별로 같은 검정을 따로 --------------------------------
        instruments = []
        for chapter, _n in instrument_totals.most_common(TOP_INSTRUMENTS):
            counter = by_instrument[chapter]
            total = instrument_totals[chapter]
            a_l = [v for c in ally if (v := lift(c, counter, total)) is not None]
            v_l = [v for c in adversary if (v := lift(c, counter, total)) is not None]
            _, p_i = mann_whitney_u(a_l, v_l)
            instruments.append({
                "chapter": chapter,
                "total": total,
                "ally_lift": _median(a_l),
                "adversary_lift": _median(v_l),
                "p_value": round(p_i, 4),
            })

        summary_out[implementer] = {
            "ally_total": len(ally),
            "adversary_total": len(adversary),
            "ally_mean": _mean(ally_counts),
            "adversary_mean": _mean(adversary_counts),
            "ally_lift": _median(ally_lift),
            "adversary_lift": _median(adversary_lift),
            "p_raw": round(p_raw, 4),
            "p_lift": round(p_lift, 4),
            "measure_total": len(rows),
            "dup_dropped": sum(1 for m in measures_out
                               if m["implementing"] == implementer and m["dup"]),
            "unassigned_missing": unassigned_missing,
            "unclassified_country_count": sum(1 for c in countries if c["group"] is None),
            "median_affected": int(
                statistics.median([m["n_affected"] for m in measures_out
                                   if m["implementing"] == implementer and m["n_affected"]])
            ),
        }
        countries_out[implementer] = countries
        instruments_out[implementer] = instruments

    import datetime as _dt
    asof = _dt.datetime.fromtimestamp(MASTER.stat().st_mtime).strftime("%Y-%m-%d")
    return {
        "built_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "gta_asof": asof,
        "bloc_note": bloc.get("note", ""),
        "implementers": IMPLEMENTERS,
        "bloc": {k: v for k, v in bloc.items() if k != "note"},
        "countries": countries_out,
        "summary": summary_out,
        "instruments": instruments_out,
        "measures": measures_out,
        "world_total": world_total,
        # 산업(HS4) 필터용(2026-08-24). affected_products(HS6)를 4자리로 접어 태깅했다
        # (건당 여러 산업에 걸치는 경우 각 산업 카운트에 전부 잡힌다 — 중복 집계가
        # 정상이다, measure 자체를 중복 제거하는 게 아니라 산업별 노출을 세는 것이므로).
        "hs2_labels": {k: hs2_labels[k] for k in hs2_counts if k in hs2_labels},
        "hs2_counts": hs2_counts.most_common(),
    }


def build(out: Path) -> bool:
    """ip_us_cn.json만 만든다 — ip_risk_site.py가 이 데이터로 BSV 거리를 계산한다.

    독립된 화면(ip_us_cn.html)은 2026-08-19에 index에서 내리면서 함께 없앴다.
    JSON은 계속 만든다. 지정학적 산업정책 리스크 화면이 이걸 그대로 읽는다.
    """
    if not all(p.is_file() for p in (MASTER, BLOC)):
        return False
    data = build_data()
    (out / "ip_us_cn.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return True
