"""SKL Economic Security Tracker 업데이트.

GTA API 자료를 BERT로 분류해 엑셀 2개(분석용 22열 / 전체 34열)를 만든다.

- 분석 단위: GTA intervention
- 열: GTA API 29개 + BERT 라벨 3개 + BERT 신뢰도 2개
- 실행 모드 두 가지
  - full        START_DATE부터 전량을 받아 직전 스냅숏과 전수 대조한다.
                삭제된 건과 뒤늦게 등재된 과거 건까지 잡힌다.
  - incremental last_updated가 마지막 점검일 이후(포함)인 건만 받는다.
                빠르지만 삭제는 확인하지 못한다.
- BERT는 description SHA-256이 같으면 캐시를 재사용하므로 실제 분류는 증분이다.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html as htmlmod
import json
import os
import platform
import re
import stat
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import numpy as np
import pandas as pd
import requests


HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "output"
CACHE = HERE / "cache"
LOGS = HERE / "logs"
STATE_PATH = CACHE / "state.json"
MASTER_PATH = CACHE / "master.parquet"
PREDICTION_CACHE_PATH = CACHE / "prediction_cache.json"

API_URL = "https://api.globaltradealert.org/api/v2/gta/data/"
# GTA 자료 전체를 받는다. 실측한 가장 이른 발표건이 2008-02-17이고 그 이전은
# 0건이라(2026-08-18 확인), 여유를 두고 그 해 1월 1일을 하한으로 둔다.
# 2026-08-18까지는 2010-01-01이었다. 2008~2009년 4,428건이 이때 들어왔다.
START_DATE = "2008-01-01"
# 산출 엑셀 이름에 들어가는 자료 시작 연도. START_DATE에서 뽑아 쓴다.
START_YEAR = START_DATE[:4]
PAGE_SIZE = 1000

MODEL_REPO = "industrialpolicygroup/industrialpolicy-classifier"
MODEL_REVISION = "2cc47b0c3a1224bd949b6154bb0fd966a864d4df"
MODEL_MAX_TOKENS = 512
# 분류 중간 저장 간격. 중간에 끊겨도 여기까지는 남는다.
CHECKPOINT_EVERY = 2000

LABEL_COLUMNS = ["D_IP_bert_3", "D_OTHER_INTENTION_bert_3", "D_NOT_ENOUGH_INFO_bert_3"]
CONFIDENCE_COLUMNS = ["bert_max_probability", "bert_was_truncated"]

# GTA OpenAPI schema: components.schemas.InterventionFullListPublicSerializerV2
# 29개 property를 스키마 순서 그대로 쓴다.
API_SCALAR_FIELDS = [
    "intervention_id", "state_act_id", "state_act_title", "intervention_url",
    "state_act_url", "is_official_source", "gta_evaluation", "inferred_jurisdictions",
    "implementation_level", "eligible_firm", "intervention_type", "mast_chapter",
    "mast_subchapter", "date_announced", "date_published", "date_implemented",
    "date_removed", "is_in_force", "last_updated", "last_edited",
    "latest_action_date", "latest_action_name",
]
# 객체 배열 필드 -> (컬럼명, 뽑을 하위 키, 구분자)
API_NESTED_FIELDS = {
    "state_act_source": ("state_act_source", "text", "\n\n"),
    "implementing_jurisdictions": ("implementing_jurisdictions", "name", "; "),
    "implementing_jurisdiction_groups": ("implementing_jurisdiction_groups", "name", "; "),
    "affected_jurisdictions": ("affected_jurisdictions", "name", "; "),
    "affected_sectors": ("affected_sectors", "sector_id", ", "),
    "affected_products": ("affected_products", "product_id", ", "),
}
DESCRIPTION_COLUMN = "intervention_description"
# 2026-10-22: GTA 가 공지 없이 응답에서 뺀 필드. 없으면 결측으로 두고 소리 내어 알린다.
# inferred_jurisdictions = AJ 등록 방식(Targeted/Inferred/Excluded/Incidental). 산업정책 화면의
# "Targeted만 보기"가 이 값을 쓴다. 결측이면 그 행은 토글에서 빠진다(없는 값을 만들지 않는다).
OPTIONAL_API_FIELDS = {"inferred_jurisdictions"}
# 이름이 바뀐 경우 여기에 (새 이름 -> 옛 이름)을 적으면 flatten 이 되돌린다. 저장 열 이름은 바꾸지 않는다.
# 2026-10-22: GTA 가 inferred_jurisdictions 를 affected_jurisdictions_type 으로 바꿨다(OpenAPI 스키마
# InterventionFullListPublicSerializerV2, 값은 Targeted/Inferred/Excluded/Incidental 그대로). 같은 때
# distorted_markets·distorted_markets_type 이 추가됐으나 아직 쓰지 않는다.
RENAMED_API_FIELDS: dict[str, str] = {"affected_jurisdictions_type": "inferred_jurisdictions"}

COLUMN_ORDER = [
    "intervention_id", "state_act_id", "state_act_title",
    DESCRIPTION_COLUMN,
    "intervention_url", "state_act_url", "state_act_source", "is_official_source",
    "gta_evaluation", "implementing_jurisdictions", "implementing_jurisdiction_groups",
    "affected_jurisdictions", "inferred_jurisdictions", "implementation_level",
    "eligible_firm", "intervention_type", "mast_chapter", "mast_subchapter",
    "affected_sectors", "affected_products", "date_announced", "date_published",
    "date_implemented", "date_removed", "is_in_force", "last_updated", "last_edited",
    "latest_action_date", "latest_action_name",
] + LABEL_COLUMNS + CONFIDENCE_COLUMNS

# 분석용 파일에 남기는 23개. 나머지 11개는 코드북에 이유를 적어두었다.
# 빼는 것: intervention_description, state_act_source, affected_products,
#          state_act_url, intervention_url, mast_subchapter, latest_action_name,
#          last_edited, latest_action_date, inferred_jurisdictions,
#          bert_max_probability
#
# bert_was_truncated는 2026-08-13에 넣었다. BERT는 512토큰까지만 읽으므로 긴
# 설명문은 앞부분만 보고 판정한다. 실측 1,877건(분류분의 2.3%)이 여기 해당하고
# 반덤핑에 몰려 있다(Anti-dumping 유형의 13.6%). 이 칸이 없으면 분석용 파일만
# 갖고는 그 건들을 걸러낼 수가 없다.
ANALYSIS_COLUMNS = [
    "intervention_id", "state_act_id", "state_act_title",
    "date_announced", "date_published", "date_implemented", "date_removed", "is_in_force",
    "implementing_jurisdictions", "implementing_jurisdiction_groups", "implementation_level",
    "intervention_type", "mast_chapter", "gta_evaluation", "eligible_firm",
    "affected_sectors", "affected_jurisdictions",
    "is_official_source", "last_updated",
] + LABEL_COLUMNS + ["bert_was_truncated"]

# 변경 감지에서 제외하는 열. GTA가 내용 변화 없이도 갱신하는 순수 메타데이터라
# 여기에 두지 않으면 매주 수백 건이 "수정"으로 잡혀 리포트가 무의미해진다.
CHANGE_IGNORE_COLUMNS = {"last_updated", "last_edited", "latest_action_date"}

# 수출통제 조치 = UN MAST Chapter P(Export-related Measures) 정식 유형 9종.
# 생존분석(260804 미중 수출통제 수명)의 씨앗 유형과 같은 목록이다.
# P6(수출보조·인센티브류)은 보조금 성격이라 뺀다.
# GTA가 유형 이름을 공지 없이 바꾼 전례가 있어(2026-08-11: Import price benchmark
# -> Minimum import price (tariff-based)) 매 실행마다 이름이 살아 있는지 확인한다.
EXPORT_CONTROL_TYPES = [
    "Export ban",
    "Export licensing requirement",
    "Export-related non-tariff measure, nes",
    "Export quota",
    "Export tax",
    "Export tariff quota",
    "Export price benchmark",
    "Foreign customer limit",
    "Local supply requirement for exports",
]

ILLEGAL_XLSX_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
XLSX_CELL_LIMIT = 32767

# output에 남겨둘 자료 기준일 수. 이보다 오래된 날짜의 엑셀은 지운다.
# 한 번 실행에 두 파일 72MB가 쌓이는데 지우는 장치가 없었다. 매일 돌리면
# 한 달에 2.2GB고, 이 폴더는 OneDrive라 그게 전부 인터넷으로 올라간다.
KEEP_OUTPUT_DATES = 3
OUTPUT_PREFIX = "SKL_Economic_Security"
# 옛 이름으로 만든 산출물도 정리 대상에 넣는다. 빼면 옛 파일이
# KEEP_OUTPUT_DATES 규칙에서 누락돼 영영 안 지워진다.
# JLOP_BERT: 2026-08 이전. SKL_Export_Control: 2026-08-15 이전.
LEGACY_OUTPUT_PREFIXES = ("JLOP_BERT", "SKL_Export_Control")
OUTPUT_PREFIXES = (OUTPUT_PREFIX,) + LEGACY_OUTPUT_PREFIXES
OUTPUT_PATTERN = re.compile(
    # 연도 자리는 느슨하게 받는다. START_DATE를 바꾸면 파일 이름의 연도도
    # 바뀌는데, 옛 연도로 만든 파일도 정리 대상에 들어와야 하기 때문이다.
    r"^(?:" + "|".join(OUTPUT_PREFIXES) + r")_(?:\d{4})-(\d{8})_(analysis|full)\.xlsx$"
)

# 정상 종료했지만 새 파일을 만들지 않았을 때의 종료 코드.
# 호출하는 쪽(run_update.ps1)이 output 폴더를 열지 말지 판단하는 데 쓴다.
NOTHING_WRITTEN = 3

class Failure(RuntimeError):
    pass


def fail(message: str) -> None:
    raise Failure(message)


def say(message: str = "") -> None:
    print(message, flush=True)


# ---------------------------------------------------------------- GTA API


def strip_url_query(value):
    if not isinstance(value, str):
        return value
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def sanitize(obj):
    if isinstance(obj, list):
        return [sanitize(x) for x in obj]
    if isinstance(obj, dict):
        return {
            k: strip_url_query(v) if k in {"intervention_url", "state_act_url"} else sanitize(v)
            for k, v in obj.items()
        }
    return obj


def unpack_response(obj):
    # Quickstart 기준 응답은 wrapper 없는 bare array다. 스키마에는 paginated
    # wrapper도 정의되어 있어 양쪽을 모두 받아둔다.
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get("results"), list):
        return obj["results"]
    fail(f"예상하지 못한 GTA API 응답 구조: {type(obj).__name__}")


def post_gta(api_key: str, payload: dict, max_attempts: int = 5):
    headers = {"Authorization": f"APIKey {api_key}", "Content-Type": "application/json"}
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=180)
            if response.status_code == 200:
                return sanitize(response.json())
        except (requests.RequestException, ValueError) as exc:
            if attempt == max_attempts:
                fail(f"GTA API 연결에 실패했습니다: {type(exc).__name__}: {exc}")
            say(f"    네트워크 오류, 재시도 {attempt}/{max_attempts - 1}: {type(exc).__name__}")
            time.sleep(min(60, 2**attempt))
            continue
        safe = response.text[:500].replace(api_key, "[REDACTED]")
        if response.status_code not in {429, 500, 502, 503, 504} or attempt == max_attempts:
            fail(f"GTA API 오류 {response.status_code}: {safe}")
        time.sleep(min(60, 2**attempt))


def unlock(path: Path) -> None:
    """읽기 전용 표시를 떼어낸다.

    OneDrive 안에 있는 폴더/파일은 동기화 과정에서 읽기 전용 표시가 붙는 일이
    있고, 그러면 윈도우가 삭제를 거부한다(WinError 5).
    """
    try:
        os.chmod(path, stat.S_IWRITE)
    except OSError:
        pass


def remove_dir(directory: Path) -> None:
    """빈 폴더를 지운다. OneDrive가 잠시 붙잡고 있을 수 있어 몇 번 다시 시도한다."""
    for attempt in range(4):
        try:
            directory.rmdir()
            return
        except FileNotFoundError:
            return
        except OSError:
            unlock(directory)
            if attempt == 3:
                raise
            time.sleep(0.5)


def prune_api_archive(keep: Path) -> None:
    """직전 실행분만 남긴다.

    원응답은 실행마다 수백 MB다(2026-08-10 기준 24페이지 446MB). 과거 실행분은
    master.parquet가 이전 상태를 들고 있어 쓸모가 없으므로 쌓아두지 않는다.
    """
    root = CACHE / "api_pages"
    if not root.exists():
        return
    freed = 0
    stuck: list[str] = []
    for directory in root.iterdir():
        if not directory.is_dir() or directory == keep:
            continue
        try:
            for path in directory.rglob("*"):
                if path.is_file():
                    freed += path.stat().st_size
                    unlock(path)
                    path.unlink()
            for path in sorted(directory.rglob("*"), reverse=True):
                if path.is_dir():
                    remove_dir(path)
            remove_dir(directory)
        except OSError as exc:
            stuck.append(f"{directory.name}({exc.strerror or exc})")
    if freed:
        say(f"    지난 실행분 원응답 정리: {freed / 1e6:,.0f}MB 확보")
    if stuck:
        say(f"    빈 폴더가 남았습니다(다음 실행 때 다시 시도합니다): {', '.join(stuck)}")


def load_archived_pages(raw_dir: Path) -> list[dict] | None:
    """같은 종료일로 오늘 받아둔 응답이 있으면 그대로 쓴다.

    중간에 끊고 다시 돌릴 때 16분짜리 수집을 반복하지 않기 위한 것이다.
    날짜가 다르거나 하루가 지났으면 쓰지 않는다.
    """
    pages = sorted(raw_dir.glob("offset_*.json.gz"))
    if not pages:
        return None
    age = time.time() - max(p.stat().st_mtime for p in pages)
    if age > 24 * 3600:
        return None
    rows: list[dict] = []
    for path in pages:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows.extend(unpack_response(json.load(handle)))
    say(f"    {int(age // 60)}분 전에 받아둔 응답 재사용: {len(rows):,}건 ({len(pages)}페이지)")
    say("    새로 받으려면 cache/api_pages 폴더를 지우고 다시 실행하세요.")
    return rows


def fetch_all(api_key: str, end_date: str) -> list[dict]:
    """START_DATE ~ end_date 발표분 전량. 응답에 count가 없어 누적으로만 표시한다."""
    raw_dir = CACHE / "api_pages" / end_date.replace("-", "")
    raw_dir.mkdir(parents=True, exist_ok=True)

    archived = load_archived_pages(raw_dir)
    if archived:
        prune_api_archive(raw_dir)
        return archived

    prune_api_archive(raw_dir)
    for stale in list(raw_dir.glob("offset_*.json")) + list(raw_dir.glob("offset_*.json.gz")):
        stale.unlink()

    rows: list[dict] = []
    offset = 0
    started = time.monotonic()
    while True:
        payload = {
            "request_data": {"announcement_period": [START_DATE, end_date]},
            "limit": PAGE_SIZE,
            "offset": offset,
            "sorting": "intervention_id",
            "text_format": "html",
        }
        raw = post_gta(api_key, payload)
        page = unpack_response(raw)
        with gzip.open(raw_dir / f"offset_{offset:06d}.json.gz", "wt", encoding="utf-8") as handle:
            json.dump(raw, handle, ensure_ascii=False)
        rows.extend(page)
        say(f"    수집 {len(rows):,}건  ({time.monotonic() - started:,.0f}초)")
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.25)

    if not rows:
        fail("GTA API가 한 건도 반환하지 않았습니다. 필터와 API key를 확인해 주세요.")
    return rows


def fetch_pages(api_key: str, request_data: dict, label: str) -> list[dict]:
    """한 필터 조합에 대해 페이지를 끝까지 넘긴다."""
    rows: list[dict] = []
    offset = 0
    while True:
        payload = {
            "request_data": request_data,
            "limit": PAGE_SIZE,
            "offset": offset,
            "sorting": "intervention_id",
            "text_format": "html",
        }
        page = unpack_response(post_gta(api_key, payload))
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
        time.sleep(0.25)
    say(f"    {label} {len(rows):,}건")
    return rows


def fetch_incremental(api_key: str, since: str, end_date: str) -> list[dict]:
    """last_updated가 since 이후(포함)인 건만 받는다.

    since는 마지막 점검일을 그대로 쓴다. 경계일 하루를 다시 받는 비용은 거의
    없고, 하루 어긋나 누락되는 위험을 없앨 수 있다.

    submission_period(등재일 기준)는 쓰지 않는다. 2026-08-10 스냅숏 실측으로
    date_published의 최댓값이 2026-06-23이었고 7월 이후 발표건 642건은 전부
    값이 비어 있었다. 최근 자료에 값이 없어 항상 0건을 반환한다.

    한계: GTA가 과거 발표건을 오늘 처음 등재할 때 last_updated를 발표일로
    찍으면 이 필터에 안 걸린다. 2022년 이전 건은 last_updated가 발표일과
    정확히 일치하는 비율이 99%라 그럴 가능성이 있다. 전체 점검이 그 안전망이다.
    """
    # 끝날은 하루 뒤까지 넣는다. 2026-10-23 예약 실행이 UTC 날짜 기준 [10-22, 10-22] 하루 창으로 0건을 받았는데,
    # GTA 쪽에는 10-22 갱신분이 있었다. 범위 끝이 배타적일 가능성에 대비한 안전장치이며, 미래 날짜라 더 받을 것은 없다.
    until = (date.fromisoformat(end_date) + timedelta(days=1)).isoformat()
    say(f"    조회 창 last_updated {since} ~ {until}")
    rows = fetch_pages(api_key, {"update_period": [since, until]}, "변경된 건")
    merged = {int(row["intervention_id"]): row for row in rows}
    if len(merged) != len(rows):
        say(f"    중복 제거: {len(rows):,} -> {len(merged):,}건")
    out = list(merged.values())

    # 전량 수집은 announcement_period로 발표일 하한(START_DATE)이 걸리는데
    # update_period에는 그런 제한이 없다. 그대로 두면 범위 밖 발표건이
    # 증분으로만 들어왔다가 다음 전량 점검에서 "GTA에서 삭제됨"으로 잘못
    # 잡힌다. 실제로 2026-08-18 점검의 삭제 1건(ID 16208, 발표 2009-11-06)이
    # 이 경우였고 GTA에는 그대로 살아 있었다. 여기서 미리 걸러낸다.
    kept = [r for r in out if str(r.get("date_announced") or "") >= START_DATE]
    if len(kept) != len(out):
        say(f"    발표일이 {START_DATE} 이전이라 제외: {len(out) - len(kept):,}건")
    return kept


# ------------------------------------------------------- description 처리


# GTA 서버가 markdown 변환에 실패하면 파이썬 객체를 글자로 찍어 보낸다.
# 예: "<builtins.ConversionResult object at 0x710870033050>" (정확히 52자)
# 2026-08-10 스냅숏에서 설명문 666건·출처 535건이 이 상태였다.
BROKEN_TEXT = re.compile(r"<[A-Za-z_][A-Za-z0-9_.]* object at 0x[0-9a-fA-F]+>")

TEXT_FIELDS = ("intervention_description", "state_act_source")
BLOCK_END = re.compile(r"</\s*(p|div|li|h[1-6]|tr|blockquote)\s*>", re.I)
LINE_BREAK = re.compile(r"<\s*br\s*/?\s*>", re.I)
ANY_TAG = re.compile(r"<[^>]*>")
SPACES = re.compile(r"[ \t\r\f\v]+")


def html_to_text(value: str) -> str:
    """html 설명문을 사람이 읽는 글자로 바꾼다.

    태그 자리에 빈칸을 넣는다. 그냥 지우면 `<u>product</u><a>atradius</a>`가
    "productatradius"로 붙어버린다(300건 검사에서 실제로 나온 사례).
    """
    if not isinstance(value, str) or not value:
        return ""
    text = BLOCK_END.sub("\n\n", value)
    text = LINE_BREAK.sub("\n", text)
    text = ANY_TAG.sub(" ", text)
    text = htmlmod.unescape(text).replace("\xa0", " ")
    text = SPACES.sub(" ", text)
    return "\n\n".join(part.strip() for part in text.split("\n") if part.strip())


def strip_html_fields(rows: list[dict]) -> list[dict]:
    """설명문·출처를 html에서 사람이 읽는 평문으로 바꾼다.

    GTA에는 markdown으로도 요청할 수 있지만 쓰지 않는다. GTA 서버의 markdown
    변환기가 일정 비율로 실패해 글자 대신 `<builtins.ConversionResult object
    at 0x...>` 같은 껍데기를 보내기 때문이다(2026-08-18 전량 82,766건 중
    1,211건). html에는 이 문제가 없어 2026-08-18부터 html만 받는다.

    받아둔 원응답(cache/api_pages)에는 html이 그대로 남고, 평문화는 여기서만
    한다. 모든 수집 경로가 flatten을 지나므로 이 한 곳이면 전부 덮인다.
    """
    for row in rows:
        for field in TEXT_FIELDS:
            parts = row.get(field)
            if not isinstance(parts, list):
                continue
            row[field] = [
                {**part, "text": html_to_text(str(part.get("text") or ""))}
                if isinstance(part, dict) else part
                for part in parts
            ]
    return rows


def build_description(value) -> str:
    """설명 조각을 order_nr 순으로 이어 붙인 BERT 입력 전문."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    if any(not isinstance(x, dict) or "text" not in x for x in value):
        fail("intervention_description 배열에 text가 없는 항목이 있습니다.")
    entries = sorted(value, key=lambda x: (x.get("order_nr") is None, x.get("order_nr", 0)))
    texts = [str(x["text"]).strip() for x in entries if str(x.get("text", "")).strip()]
    return "\n\n".join(texts)


def join_nested(value, key: str, separator: str):
    if not isinstance(value, list):
        return pd.NA
    parts = [
        str(item[key]).strip()
        for item in value
        if isinstance(item, dict) and item.get(key) not in (None, "")
    ]
    return separator.join(parts) if parts else pd.NA


def flatten(rows: list[dict]) -> pd.DataFrame:
    raw = pd.DataFrame(strip_html_fields(rows))
    raw = raw.rename(columns={new: old for new, old in RENAMED_API_FIELDS.items() if new in raw.columns})
    required = set(API_SCALAR_FIELDS) | set(API_NESTED_FIELDS) | {DESCRIPTION_COLUMN}
    missing = required - set(raw.columns)
    optional_missing = sorted(missing & OPTIONAL_API_FIELDS)
    for field in optional_missing:
        raw[field] = pd.NA
        say(f"    주의: GTA API 응답에 {field} 가 없습니다. 결측으로 둡니다 (받은 필드 {len(raw.columns)}개)")
    missing -= OPTIONAL_API_FIELDS
    if missing:
        say(f"    받은 필드: {sorted(raw.columns)}")
        fail(f"GTA API 응답에 필수 필드가 없습니다: {sorted(missing)}")
    flatten.missing_optional = optional_missing  # 매니페스트용

    out = pd.DataFrame(index=raw.index)
    for field in API_SCALAR_FIELDS:
        out[field] = raw[field]
    for field, (column, key, separator) in API_NESTED_FIELDS.items():
        out[column] = raw[field].map(lambda v, k=key, s=separator: join_nested(v, k, s))
    out[DESCRIPTION_COLUMN] = raw[DESCRIPTION_COLUMN].map(build_description)

    # html에서는 나올 일이 없지만, GTA가 html 변환까지 깨뜨리면 엉터리 글자로
    # 분류하느니 설명문이 없는 것으로 둔다(기존 결측 처리 규칙과 같다).
    # 이 줄이 뜨면 GTA 쪽에 새 문제가 생겼다는 뜻이다.
    for column in (DESCRIPTION_COLUMN, "state_act_source"):
        broken = out[column].fillna("").astype(str).str.contains(BROKEN_TEXT)
        if broken.any():
            say(f"    주의: GTA가 {column} {int(broken.sum()):,}건을 깨진 채 보냈습니다. 결측 처리합니다")
            out.loc[broken, column] = pd.NA

    out["intervention_id"] = pd.to_numeric(out["intervention_id"], errors="raise").astype("Int64")
    out["state_act_id"] = pd.to_numeric(out["state_act_id"], errors="coerce").astype("Int64")
    out["is_in_force"] = pd.to_numeric(out["is_in_force"], errors="coerce").astype("Int64")
    out["intervention_url"] = out["intervention_url"].map(strip_url_query)
    out["state_act_url"] = out["state_act_url"].map(strip_url_query)

    if out["intervention_id"].isna().any():
        fail("intervention_id가 비어 있는 행이 있습니다.")
    if out["intervention_id"].duplicated().any():
        n = int(out["intervention_id"].duplicated().sum())
        fail(f"GTA API 결과에 intervention_id 중복 {n}건이 있습니다.")
    return out


def description_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ BERT


def load_prediction_cache() -> dict[str, dict]:
    """확률값까지 갖춘 항목만 유효 캐시로 인정한다."""
    if not PREDICTION_CACHE_PATH.exists():
        return {}
    stored = json.loads(PREDICTION_CACHE_PATH.read_text(encoding="utf-8"))
    return {
        key: value
        for key, value in stored.items()
        if isinstance(value, dict) and value.get("max_probability") is not None
    }


def save_prediction_cache(cache: dict[str, dict]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = PREDICTION_CACHE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(PREDICTION_CACHE_PATH)


class Classifier:
    """모델을 한 번만 올려두고 재사용한다."""

    def __init__(self) -> None:
        self._ready = False

    def _load(self) -> None:
        if self._ready:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        from transformers import logging as hf_logging

        # 512토큰을 넘는 입력마다 tokenizer가 영어 경고를 찍는다. 자르는 것은
        # 의도한 동작이고(truncation=True), 잘린 건수는 아래에서 따로 세어
        # 한 줄로 알려주므로 원시 경고는 덮는다. 오류는 그대로 나온다.
        hf_logging.set_verbosity_error()

        say("    BERT 모델 준비 중 (최초 1회는 내려받기 때문에 몇 분 걸립니다)")
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(MODEL_REPO, revision=MODEL_REVISION)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            MODEL_REPO, revision=MODEL_REVISION
        )
        observed = {int(k): v for k, v in self.model.config.id2label.items()}
        if observed != {0: "LABEL_0", 1: "LABEL_1", 2: "LABEL_2"}:
            fail(f"BERT label mapping 변경 감지: {observed}")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model.to(self.device).eval()
        self.batch_size = 32 if self.device.type == "cuda" else 16
        self._ready = True

    def ensure_loaded(self) -> None:
        """모델을 미리 올려둔다. 진행률 타이머가 로딩 시간을 삼키지 않게 한다."""
        self._load()

    def predict(self, texts: list[str], progress_label: str,
                done_before: int = 0, total: int = 0, started: float | None = None) -> list[dict]:
        """호출자가 길이순으로 정렬해 넘긴다는 전제로 배치를 만든다.

        done_before/total/started를 받으면 여러 번 나눠 불러도 진행률과 남은
        시간이 전체 기준으로 이어진다.
        """
        if not texts:
            return []
        self._load()
        results: list[dict] = []
        total = total or len(texts)
        started = started if started is not None else time.monotonic()
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            lengths = [
                len(self.tokenizer.tokenize(x))
                + self.tokenizer.num_special_tokens_to_add(pair=False)
                for x in batch
            ]
            encoded = self.tokenizer(
                batch, padding=True, truncation=True,
                max_length=MODEL_MAX_TOKENS, return_tensors="pt",
            )
            encoded = {k: v.to(self.device) for k, v in encoded.items()}
            with self.torch.inference_mode():
                probs = self.torch.softmax(self.model(**encoded).logits, dim=-1).cpu().numpy()
            for length, p in zip(lengths, probs):
                results.append({
                    "label_id": int(np.argmax(p)),
                    "max_probability": float(p.max()),
                    "was_truncated": bool(length > MODEL_MAX_TOKENS),
                    "token_count_untruncated": int(length),
                    "prob_ip_goal": float(p[0]),
                    "prob_no_ip_goal": float(p[1]),
                    "prob_not_enough_information": float(p[2]),
                    "model_revision": MODEL_REVISION,
                })
            done_here = min(start + self.batch_size, len(texts))
            done = done_before + done_here
            elapsed = time.monotonic() - started
            if done_here == len(texts) or (start // self.batch_size) % 20 == 0:
                rate = done / elapsed if elapsed else 0
                remain = (total - done) / rate if rate else 0
                say(
                    f"    {progress_label} {done:,}/{total:,}"
                    f"  ({rate:.1f}건/초, 남은 시간 약 {format_duration(remain)})"
                )
        return results


def format_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}초"
    if seconds < 3600:
        return f"{seconds // 60}분"
    return f"{seconds // 3600}시간 {(seconds % 3600) // 60}분"


def classify(frame: pd.DataFrame, cache: dict[str, dict], classifier: Classifier,
             progress_label: str) -> tuple[pd.DataFrame, int]:
    """description 해시 기준으로 미분류분만 돌리고 라벨 열을 채운다."""
    frame = frame.copy()
    text = frame[DESCRIPTION_COLUMN].fillna("").astype(str)
    frame["_key"] = text.map(lambda x: description_hash(x) if x.strip() else None)

    key_to_text = {}
    for key, value in zip(frame["_key"], text):
        if key is not None and key not in key_to_text:
            key_to_text[key] = value
    pending = [key for key in key_to_text if key not in cache]

    if pending:
        # 길이가 비슷한 것끼리 묶이도록 정렬한다. 섞여 있으면 배치 전체가 가장
        # 긴 항목 길이로 패딩되어 짧은 항목까지 그 비용을 치른다.
        pending.sort(key=lambda k: len(key_to_text[k]))
        say(f"    분류 대상 {len(pending):,}건 (길이순 정렬, {CHECKPOINT_EVERY:,}건마다 저장)")
        # 모델 로딩을 타이머 밖에서 끝낸다. 안에서 하면 로딩에 걸린 몇 분이
        # 분류 속도에 섞여 43건짜리 작업에 "0.1건/초, 남은 시간 3분"처럼
        # 실제와 열 배 어긋난 표시가 나온다.
        classifier.ensure_loaded()
        started = time.monotonic()
        for offset in range(0, len(pending), CHECKPOINT_EVERY):
            chunk = pending[offset : offset + CHECKPOINT_EVERY]
            predictions = classifier.predict(
                [key_to_text[k] for k in chunk], progress_label,
                done_before=offset, total=len(pending), started=started,
            )
            cache.update(dict(zip(chunk, predictions)))
            # 중간 저장. 여기서 끊겨도 다시 실행하면 남은 것부터 이어서 간다.
            save_prediction_cache(cache)

        # tokenizer의 영어 경고를 덮은 대신 여기서 센다. 잘린 건은 뒷부분을
        # 못 보고 분류한 것이라 라벨을 그대로 믿기 어렵다.
        truncated = sum(1 for k in pending if (cache.get(k) or {}).get("was_truncated"))
        if truncated:
            say(f"    512토큰을 넘어 뒷부분이 잘린 채 분류한 건 {truncated:,}건"
                f" (전체 {len(pending):,}건 중)")

    hit = frame["_key"].map(lambda k: cache.get(k) if k is not None else None)
    classified = hit.notna()
    for column, label_id in zip(LABEL_COLUMNS, [0, 1, 2]):
        frame[column] = pd.Series(pd.NA, index=frame.index, dtype="Int64")
        frame.loc[classified, column] = (
            hit[classified].map(lambda x: x["label_id"]).eq(label_id).astype("Int64")
        )
    frame["bert_max_probability"] = pd.Series(
        [h["max_probability"] if isinstance(h, dict) else None for h in hit],
        index=frame.index, dtype="Float64",
    )
    frame["bert_was_truncated"] = pd.Series(
        [h["was_truncated"] if isinstance(h, dict) else None for h in hit],
        index=frame.index, dtype="boolean",
    )
    return frame.drop(columns="_key"), len(pending)


# ------------------------------------------------------------- 변경 대조


NULL_TOKEN = "\x00NULL"


def as_text(frame: pd.DataFrame) -> pd.DataFrame:
    """비교용 문자열 변환. 결측 표현을 하나로 통일한다.

    parquet 왕복을 거치면 object 열의 pd.NA가 None으로 바뀐다. 그대로
    astype(str)을 하면 "<NA>"와 "None"이 달라져 멀쩡한 행이 전부 '수정'으로
    잡힌다. notna() 기준으로 한 번 눌러 두면 어느 쪽이든 같게 나온다.
    """
    return frame.astype("object").where(frame.notna(), NULL_TOKEN).astype(str)


def compare(previous: pd.DataFrame | None, current: pd.DataFrame,
            last_update: str | None, detect_removals: bool = True) -> dict:
    """직전 스냅숏과 대조해 새로 들어온 것·수정·삭제를 분류한다.

    detect_removals가 False면(증분 모드) 삭제는 판단하지 않는다. 증분에서는
    받지 않은 건과 사라진 건을 구분할 수 없다.

    2026-08-13 이전에는 새로 들어온 건을 발표일 기준으로 '신규'(직전 기준일 이후
    발표)와 '지연 등재'(그 이전 발표)로 나눴다. 없앴다. GTA는 발표 2~4주 뒤에
    올리는데 이제 매일 받으므로 '신규'가 구조적으로 항상 0이었다(실측: 2026-08-12
    0/41, 08-13 0/47). 지금은 하나로 묶고, 발표 후 얼마나 지나서 들어왔는지는
    경보가 아니라 분포로만 보여준다.
    """
    if previous is None:
        return {"first_run": True, "new": [], "new_no_date": [], "changed": [],
                "removed": [], "changed_fields": {}, "detect_removals": detect_removals}

    prev = previous.set_index("intervention_id")
    curr = current.set_index("intervention_id")
    new_ids = curr.index.difference(prev.index)
    gone_ids = prev.index.difference(curr.index)
    common = curr.index.intersection(prev.index)

    # 발표일이 비어 있으면 경과일을 잴 수 없다. 예전에는 이런 건이 조용히
    # '신규'로 밀려 들어갔다. 이제 따로 세어 보여준다.
    announced = pd.to_datetime(curr.loc[new_ids, "date_announced"], errors="coerce")
    no_date = announced.isna()

    # intervention_id는 인덱스로 빠졌고, 라벨·신뢰도는 description에서 파생되므로
    # 원자료 변화만 본다.
    compare_columns = [
        c for c in current.columns
        if c != "intervention_id"
        and c not in CHANGE_IGNORE_COLUMNS
        and c not in LABEL_COLUMNS
        and c not in CONFIDENCE_COLUMNS
    ]
    a = as_text(prev.loc[common, compare_columns])
    b = as_text(curr.loc[common, compare_columns])
    differs = (a != b).any(axis=1)
    changed_ids = common[differs.values]

    # 열 이름만 남기면 "무엇이 무엇으로 바뀌었나"를 나중에 복원할 수 없다(전에는
    # 그랬다). 이전값·이후값을 같이 들고 나간다. 키만 돌면 예전처럼 열 이름 목록으로
    # 쓸 수 있어서 건수 집계 쪽은 그대로 둔다.
    changed_fields: dict[int, dict[str, tuple[str, str]]] = {}
    for cid in changed_ids:
        row_a, row_b = a.loc[cid], b.loc[cid]
        changed_fields[int(cid)] = {
            c: (row_a[c], row_b[c]) for c in compare_columns if row_a[c] != row_b[c]
        }

    return {
        "first_run": False,
        "new": [int(i) for i in new_ids],
        "new_no_date": [int(i) for i in new_ids[no_date.values]],
        "changed": [int(i) for i in changed_ids],
        "changed_fields": changed_fields,
        "removed": [int(i) for i in gone_ids] if detect_removals else [],
        "detect_removals": detect_removals,
    }


# 발표 후 며칠 만에 우리 자료에 들어왔나. 상한(미만) 기준이다.
# 예전에는 각 칸에 "확인해볼 것" 같은 경보 문구가 붙어 있었는데 뗐다. 30일~1년
# 칸이 매일 수십 건씩 차는데(2026-08-13: 35건) 들여다보면 GTA가 인도 지방조달
# 건을 한꺼번에 늦게 올린 것 같은 정상 처리였다. 매일 울리는 경보는 아무도 안 본다.
# 실제로 눈여겨볼 것은 1년 이상 칸 하나뿐이다.
LAG_BUCKETS = [
    (30, "30일 이내"),
    (365, "30일~1년"),
    (None, "1년 이상"),
]


def registration_lag(current: pd.DataFrame, ids: list[int], last_update: str | None) -> pd.Series:
    """발표 후 며칠 만에 우리 자료에 들어왔는지.

    엄밀히는 'GTA에 등재된 날'이 아니라 '우리가 처음 본 날' 기준이다. GTA가
    등재일(date_published)을 최근 자료에 채워주지 않아 그것으로는 잴 수 없다.
    매일 받으면 둘이 거의 같지만, 이 숫자를 인용할 때는 그 점을 밝혀야 한다.
    발표일이 없는 건은 NaN으로 남는다.
    """
    if not ids or last_update is None:
        return pd.Series(dtype="float64")
    announced = pd.to_datetime(
        current.set_index("intervention_id").reindex(ids)["date_announced"], errors="coerce"
    )
    return (pd.Timestamp(last_update) - announced).dt.days


def lag_bucket_counts(lag: pd.Series) -> list[int]:
    """LAG_BUCKETS 순서대로 건수를 센다.

    경계일보다 뒤에 발표된 건은 경과일이 음수가 되는데(당일 발표·당일 등재),
    그것도 '30일 이내'로 본다. 그래서 between이 아니라 상한 미만으로 자른다.
    """
    counts, lo = [], float("-inf")
    for hi, _ in LAG_BUCKETS:
        top = float("inf") if hi is None else hi
        counts.append(int(((lag >= lo) & (lag < top)).sum()) if not lag.empty else 0)
        lo = top
    return counts


def sort_by_lag(current: pd.DataFrame, ids: list[int], last_update: str | None) -> list[int]:
    """오래된 것부터. 눈에 띄어야 할 것이 위로 온다. 발표일 없는 건은 맨 뒤."""
    lag = registration_lag(current, ids, last_update)
    if lag.empty:
        return ids
    return [int(i) for i in lag.sort_values(ascending=False, na_position="last").index]


def description_lengths(frame: pd.DataFrame, ids: list[int]) -> pd.Series:
    sub = frame.set_index("intervention_id").reindex(ids)[DESCRIPTION_COLUMN]
    return sub.fillna("").astype(str).str.len()


def length_note(before: int, after: int) -> str:
    """설명문 길이 변화를 한 줄로. 라벨이 왜 뒤집혔는지 진단하는 단서."""
    if before == after:
        return f"설명문 {before:,}자 (그대로)"
    pct = (after - before) / before * 100 if before else float("inf")
    arrow = "줄어듦" if after < before else "늘어남"
    if before == 0:
        return f"설명문 없음 → {after:,}자"
    return f"설명문 {before:,}자 → {after:,}자 ({abs(pct):.0f}% {arrow})"


# BERT one-hot 3열(D_IP_bert_3 / D_OTHER_INTENTION_bert_3 / D_NOT_ENOUGH_INFO_bert_3)을
# 표에 한 칸으로 적기 위한 이름. 열 셋을 나란히 보여주면 읽는 사람이 매번
# 1이 어디 붙었는지 눈으로 찾아야 해서, 표에서는 텍스트 한 칸으로만 쓴다.
# '목적 불명확'은 설명문이 부실하다는 뜻이 아니다. 문서에 정책 목적을 서술한
# 문장이 없어 산업정책 의도를 판정할 근거가 없다는 뜻이다. 세율·기준가를 주기적으로
# 조정하는 반복 고시가 여기 몰린다(Mexico 연료 세액공제 64건 전량 등).
IP_LABEL_NAMES = ["산업정책", "산업정책 아님", "목적 불명확"]

# 산업정책 절 머리글. 분류 기준은 우리가 정한 것이 아니라 모델을 만든 논문의
# 주석 코드북(Appendix I.2 Definition 1)에 있다. 기준을 리포트 안에 적어 두지
# 않으면 읽는 사람이 "산업정책"을 각자 뜻으로 읽는다.
IP_CRITERION_NOTE = (
    "BERT가 설명문에 적힌 목적을 보고 붙인 라벨 기준이다. 정의: "
    "“A policy or measure has an Industrial Policy Intentionality when it "
    "(i) seeks to change the relative prices across sectors or direct resources "
    "towards certain selectively targeted activities (e.g., exporting, R&D), "
    "with (ii) the purpose of shifting the long-run composition of economic "
    "activity.” 반덤핑·세이프가드·국가안보·보건·통화안정처럼 다른 목적인 "
    "경우 `산업정책 아님`, 목적을 아예 적지 않으면 `목적 불명확`이다.\n\n"
    "> Juhász, R., Lane, N., Oehlsen, E., & Pérez, V. C. (2025). "
    "*Measuring Industrial Policy: A Text-Based Approach.*"
)
IP_LABEL_MISSING = "미분류"  # 설명문이 없어 분류하지 않은 건


def ip_label_of_row(row) -> str:
    """행 하나의 one-hot 3열을 라벨 텍스트 하나로 접는다."""
    for name, column in zip(IP_LABEL_NAMES, LABEL_COLUMNS):
        value = row.get(column)
        if pd.notna(value) and int(value) == 1:
            return name
    return IP_LABEL_MISSING


def label_of(frame: pd.DataFrame, ids: list[int]) -> pd.Series:
    """one-hot 3열을 라벨 문자열 하나로 접는다. 미분류는 '미분류'."""
    sub = frame.set_index("intervention_id").reindex(ids)[LABEL_COLUMNS]

    def pick(row):
        for name, value in zip(IP_LABEL_NAMES, row):
            if pd.notna(value) and int(value) == 1:
                return name
        return IP_LABEL_MISSING

    return sub.apply(pick, axis=1)


def report_changes(diff: dict, previous: pd.DataFrame, current: pd.DataFrame,
                   last_update: str, end_date: str) -> dict:
    say()
    say("=" * 66)
    say("  검증 결과")
    say("=" * 66)
    say(f"  직전 업데이트  {last_update}")
    say(f"  이번 종료일    {end_date}")
    say()

    say(f"  새로 들어온 것 {len(diff['new']):>6,}건   (직전 자료에 없던 건)")
    say(f"  수정           {len(diff['changed']):>6,}건   (발표일 전 구간, 포함)")
    if diff.get("detect_removals", True):
        say(f"  삭제           {len(diff['removed']):>6,}건   (GTA에서 사라짐)")
    else:
        say("  삭제              확인 안 함   (빠른 업데이트 모드. 잠수함 패치 점검에서 확인됩니다)")

    if diff["new"]:
        say()
        say("  ── 발표 후 며칠 만에 들어왔나 (우리가 처음 본 날 기준) ──")
        lag = registration_lag(current, diff["new"], last_update)
        counts = lag_bucket_counts(lag)
        for (hi, name), n in zip(LAG_BUCKETS, counts):
            mark = "   ← 오래 묵은 건. 확인해볼 것" if hi is None and n else ""
            say(f"    {name:<12} {n:>4,}건{mark}")
        if diff["new_no_date"]:
            say(f"    {'발표일 없음':<12} {len(diff['new_no_date']):>4,}건"
                "   ← 경과일을 잴 수 없음")

        ordered = sort_by_lag(current, diff["new"], last_update)
        say()
        say("    오래된 것부터")
        sample = current.set_index("intervention_id").reindex(ordered[:10])
        for cid, row in sample.iterrows():
            days = lag.get(cid, float("nan"))
            title = str(row["state_act_title"])[:50]
            if pd.isna(days):
                say(f"      발표일 없음                 {title}")
                continue
            # 경계일보다 뒤에 발표된 건은 음수가 나온다. 발표하자마자 들어온 것이다.
            days_txt = "  발표 직후" if days < 0 else f"{int(days):>4}일 전"
            say(f"      발표 {row['date_announced']} ({days_txt})  {title}")
        if len(ordered) > 10:
            say(f"      ... 외 {len(ordered) - 10:,}건")

    label_changed: list[int] = []
    before = after = None
    if diff["changed"]:
        before = label_of(previous, diff["changed"])
        after = label_of(current, diff["changed"])
        moved = (before.astype(str) != after.astype(str))
        label_changed = [int(i) for i in before.index[moved.values]]

        say()
        say(f"  ── 수정 {len(diff['changed']):,}건의 내역 ──")
        say(f"    BERT 라벨 바뀜   {len(label_changed):>6,}건")
        say(f"    라벨은 그대로    {len(diff['changed']) - len(label_changed):>6,}건")

        counter: dict[str, int] = {}
        for fields in diff.get("changed_fields", {}).values():
            for field in fields:
                counter[field] = counter.get(field, 0) + 1
        if counter:
            say()
            say("    바뀐 항목 (많은 순)")
            ranked = sorted(counter.items(), key=lambda x: -x[1])
            for field, count in ranked[:8]:
                say(f"      {field:<34} {count:>6,}건")
            if len(ranked) > 8:
                say(f"      ... 외 {len(ranked) - 8}개 항목")

        if label_changed:
            say()
            say("    라벨이 바뀐 건  (설명문 길이 변화가 원인 단서다)")
            titles = current.set_index("intervention_id").reindex(label_changed)
            len_before = description_lengths(previous, label_changed)
            len_after = description_lengths(current, label_changed)
            for cid in label_changed[:10]:
                title = str(titles.loc[cid, "state_act_title"])[:46]
                say(f"      {before.loc[cid]} → {after.loc[cid]}")
                say(f"               {length_note(int(len_before[cid]), int(len_after[cid]))}"
                    f"   {title}")
            if len(label_changed) > 10:
                say(f"      ... 외 {len(label_changed) - 10:,}건")

    if diff["removed"]:
        say()
        say("  ── 삭제 ──")
        sample = previous.set_index("intervention_id").reindex(diff["removed"][:10])
        for cid, row in sample.iterrows():
            say(f"    발표 {row['date_announced']}  {str(row['state_act_title'])[:52]}")
        if len(diff["removed"]) > 10:
            say(f"    ... 외 {len(diff['removed']) - 10:,}건")

    say()
    say("=" * 66)
    return {"label_changed": label_changed, "before": before, "after": after}


def export_control_changes(diff: dict, previous: pd.DataFrame,
                           current: pd.DataFrame) -> dict[str, list[int]]:
    """이번 변경분 중 수출통제 조치만 골라낸다.

    새로 들어온 것·수정은 지금 자료에서, 삭제는 사라지기 전 자료에서 유형을 본다.
    """
    def pick(ids: list[int], frame: pd.DataFrame) -> list[int]:
        if not ids or frame is None:
            return []
        types = frame.set_index("intervention_id").reindex(ids)["intervention_type"]
        return [int(i) for i in types[types.isin(EXPORT_CONTROL_TYPES)].index]

    return {
        "new": pick(diff["new"], current),
        "changed": pick(diff["changed"], current),
        "removed": pick(diff["removed"], previous),
    }


def industrial_policy_changes(diff: dict, previous: pd.DataFrame,
                              current: pd.DataFrame) -> dict[str, list[int]]:
    """이번 변경분 중 BERT가 산업정책으로 분류한 건만 골라낸다.

    유형 이름으로 거르는 수출통제와 달리 여기서는 BERT 라벨을 본다. 라벨은
    설명문에서 나오므로 설명문이 없어 미분류인 건은 여기 안 들어온다.
    새로 들어온 것·수정은 지금 자료에서, 삭제는 사라지기 전 자료에서 라벨을 본다.
    """
    column = LABEL_COLUMNS[0]   # D_IP_bert_3

    def pick(ids: list[int], frame: pd.DataFrame) -> list[int]:
        if not ids or frame is None or column not in frame.columns:
            return []
        flags = frame.set_index("intervention_id").reindex(ids)[column]
        return [int(i) for i in flags[flags == 1].index]

    return {
        "new": pick(diff["new"], current),
        "changed": pick(diff["changed"], current),
        "removed": pick(diff["removed"], previous),
    }


def check_export_control_types(current: pd.DataFrame) -> list[str]:
    """9종 이름이 자료에 살아 있는지 확인한다.

    GTA가 이름을 바꾸면 그 유형이 통째로 안 잡히는데 오류가 나지 않는다.
    표본이 조용히 작아지므로 여기서 시끄럽게 알린다.
    """
    counts = current["intervention_type"].value_counts()
    return [t for t in EXPORT_CONTROL_TYPES if counts.get(t, 0) == 0]


def report_export_controls(diff: dict, previous: pd.DataFrame, current: pd.DataFrame,
                           summary: dict, args) -> dict[str, list[int]]:
    """수출통제 조치 변경만 따로 보여주는 두 번째 화면."""
    gone = check_export_control_types(current)
    if gone:
        say()
        say("  " + "!" * 62)
        say("  경고: 아래 수출통제 유형 이름이 자료에서 사라졌습니다.")
        say("        GTA가 이름을 바꿨을 수 있습니다. 표본이 조용히 작아집니다.")
        for name in gone:
            say(f"          - {name}")
        say("  " + "!" * 62)

    ec = export_control_changes(diff, previous, current)
    total = sum(len(v) for v in ec.values())

    say()
    say("-" * 66)
    if total == 0:
        say("  수출통제 조치(MAST Chapter P 9종) 변경 없음")
        say("-" * 66)
        return ec
    say(f"  이 중 수출통제 조치(MAST Chapter P 9종)가 {total:,}건 있습니다.")
    say("-" * 66)

    say()
    say("=" * 66)
    say("  수출통제 조치 변경 내역")
    say("=" * 66)
    say(f"  새로 들어온 것 {len(ec['new']):,}건 "
        f"· 수정 {len(ec['changed']):,}건 · 삭제 {len(ec['removed']):,}건")

    label_changed = set(summary.get("label_changed") or [])
    fields = diff.get("changed_fields", {})

    for key, title, frame in (
        ("new", "새로 들어온 것", current),
        ("changed", "수정", current),
        ("removed", "삭제", previous),
    ):
        ids = ec[key]
        if not ids:
            continue
        say()
        say(f"  ── {title} {len(ids):,}건 ──")
        sub = frame.set_index("intervention_id").reindex(ids)
        for cid, row in sub.head(15).iterrows():
            say(f"    {str(row['intervention_type'])[:32]:<32} "
                f"발표 {row['date_announced']}")
            say(f"              {str(row['implementing_jurisdictions'])[:24]:<24} "
                f"{str(row['state_act_title'])[:46]}")
            if key == "changed":
                marks = []
                if cid in label_changed:
                    marks.append("BERT 라벨 바뀜")
                touched = [c for c in fields.get(int(cid), []) if c not in {"state_act_source"}]
                if touched:
                    marks.append("바뀐 항목: " + ", ".join(touched[:4]))
                if marks:
                    say("              " + " · ".join(marks))
        if len(ids) > 15:
            say(f"    ... 외 {len(ids) - 15:,}건")

    say()
    say("=" * 66)
    return ec


REPORT_ROW_CAP = 500

# 변경 내역의 모든 표가 공유하는 기본 열. 표마다 열이 달라서 같은 건을 표 사이에서
# 눈으로 잇기 어려웠다. 이 여섯 개는 어느 표에나 같은 순서로 들어간다.
# 표별 고유 열(라벨 이전 분류, 바뀐 항목 등)은 이 뒤에 붙인다.
# 경과일은 표에 넣지 않는다(2026-08-12 지시). ID는 2026-08-21에 되살렸다.
# 한 state act가 여러 intervention 으로 쪼개지면 공통 여섯 열이 똑같이 찍혀
# 같은 건이 두 번 들어간 것처럼 보인다(전체 행의 24.4%가 그런 짝을 갖는다).
# 실측상 언제나 갈리는 열은 ID뿐이라(implementation_level 은 6.2%만 갈린다)
# GTA 원문 링크를 겸해 마지막 열로 붙인다.
REPORT_HEAD = "| 발표일 | 시행 관할 | 제목 | 유형 | GTA 평가 | 산업정책 분류 | ID "
REPORT_SEP = "|---|---|---|---|---|---|---"
GTA_INTERVENTION_URL = "https://globaltradealert.org/intervention/{}"


def cell(value) -> str:
    """표 칸 하나. 결측이 'nan'·'<NA>'로 새는 것을 막는다."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return ""
    return str(value).replace("|", "\\|")


def report_cells(row) -> list[str]:
    """모든 표에 공통으로 들어가는 일곱 칸. 마지막이 GTA 원문 링크다."""
    cid = row.name
    link = ""
    if cid is not None and not pd.isna(cid):
        url = cell(row.get("intervention_url")) or GTA_INTERVENTION_URL.format(int(cid))
        link = f"[{int(cid)}]({url})"
    return [
        cell(row.get("date_announced")),
        cell(row.get("implementing_jurisdictions"))[:30],
        cell(row.get("state_act_title"))[:90],
        cell(row.get("intervention_type")),
        cell(row.get("gta_evaluation")),
        ip_label_of_row(row),
        link,
    ]


# 이전값·이후값을 표 칸에 그대로 넣을 수 있는 길이. 넘으면 글자 수만 적는다.
# 설명문은 수천 자짜리가 흔해서 원문을 넣으면 표가 읽을 수 없게 된다. 제목과
# 출처 URL은 이 선 안에 들어와 원문이 그대로 보인다(제목 실측 최대 90자대).
CHANGE_VALUE_CAP = 120


def change_value_cells(before: str, after: str) -> list[str]:
    """수정 표의 '이전'·'이후' 두 칸.

    긴 열(설명문·출처)은 원문 대신 글자 수로 눌러 적는다. 길이만으로도 GTA가
    내용을 갈아끼웠는지 문장 하나 고쳤는지는 구분된다.
    """
    def shown(value: str) -> str:
        return "" if value == NULL_TOKEN else value

    a, b = shown(before), shown(after)
    if max(len(a), len(b)) > CHANGE_VALUE_CAP:
        return [f"{len(a):,}자" if a else "없음", f"{len(b):,}자" if b else "없음"]
    return [cell(a) if a else "(없음)", cell(b) if b else "(없음)"]


def changed_field_order(fields: dict[str, tuple[str, str]]) -> list[str]:
    """값이 보이는 짧은 열을 앞에, 글자 수로만 적는 긴 열을 뒤에."""
    def long(name: str) -> int:
        before, after = fields[name]
        return int(max(len(before), len(after)) > CHANGE_VALUE_CAP)
    return sorted(fields, key=lambda name: (long(name), name))


def changed_detail_lines(diff: dict, curr: pd.DataFrame) -> list[str]:
    """수정사항 목록. 어느 조치의 어느 항목이 무엇에서 무엇으로 바뀌었나.

    한 조치가 여러 항목을 고쳤으면 항목 수만큼 줄이 붙는데, 공통 여섯 열은
    첫 줄에만 적고 이어지는 줄은 비운다. 같은 조치가 여러 건으로 보이던 문제를
    막는다. 사이트는 이 빈 칸을 rowspan 으로 합쳐 한 칸으로 보여준다.
    curr는 intervention_id를 인덱스로 잡아 둔 현재 자료다.
    """
    fields_by_id = diff.get("changed_fields", {})
    if not diff.get("changed") or not fields_by_id:
        return []
    rows: list[list[str]] = []
    for cid in diff["changed"]:
        fields = fields_by_id.get(int(cid))
        # 값 없이 열 이름만 들어오는 옛 형식이면(dict가 아니면) 펼 수 없다.
        if not isinstance(fields, dict) or cid not in curr.index:
            continue
        common = report_cells(curr.loc[cid])
        blank = [""] * len(common)
        for n, name in enumerate(changed_field_order(fields)):
            before, after = fields[name]
            head = common if n == 0 else blank
            rows.append(head + [f"`{name}`"] + change_value_cells(before, after))
    if not rows:
        return []
    out = [f"## 전체 수정사항 목록 ({len(diff['changed']):,}건, 항목 {len(rows):,}개)", ""]
    out.append("설명문·출처처럼 긴 열은 원문 대신 글자 수만 적는다 — 크게 줄었으면 "
               "GTA가 내용을 갈아끼운 것이고, 비슷하면 문장 하나 고친 것이다.")
    out.append("")
    out.append(REPORT_HEAD + "| 바뀐 항목 | 이전 | 이후 |")
    out.append(REPORT_SEP + "|---|---|---|")
    for row in rows[:REPORT_ROW_CAP]:
        out.append("| " + " | ".join(row) + " |")
    if len(rows) > REPORT_ROW_CAP:
        out.append(f"| | | 외 {len(rows) - REPORT_ROW_CAP:,}개 항목 생략 | | | | | | | |")
    out.append("")
    return out


def build_change_report(diff: dict, summary: dict, previous: pd.DataFrame,
                        current: pd.DataFrame, last_update: str | None,
                        end_date: str, mode: str, first_run: bool) -> str:
    """화면에 스쳐 지나간 변경 내역을 마크다운으로 남긴다.

    manifest에는 건수와 ID만 들어가서, 나중에 "지난번에 뭐가 바뀌었더라"를
    확인할 방법이 없다. 이 파일이 그 기록이다.
    """
    out: list[str] = []
    add = out.append
    # 최초 구축은 "변경 내역"이 아니다. 대조할 직전 자료가 없어 새로 만든
    # 것이므로 제목과 실행 모드를 그에 맞게 쓴다. first_run일 때 mode는 항상
    # "full"로 강제되는데, 그걸 그대로 "잠수함 패치 점검"이라고 찍으면 있지도
    # 않은 직전 자료와 대조한 것처럼 읽힌다.
    add(f"# {'최초 구축' if first_run else '변경 내역'} {end_date}")
    add("")
    if first_run:
        add(f"- 자료 범위: {START_DATE} ~ {end_date} (발표일 기준, 양끝 포함)")
        add("- 실행 모드: 최초 구축")
    else:
        add(f"- 자료 기준일: {end_date}")
        add(f"- 직전 기준일: {last_update}")
        add(f"- 실행 모드: {'잠수함 패치 점검' if mode == 'full' else '빠른 업데이트'}")
    add(f"- 전체 표본: {len(current):,}건")
    add(f"- 작성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    add("")
    if first_run:
        announced = pd.to_datetime(current["date_announced"], errors="coerce")
        jurisdictions = (current["implementing_jurisdictions"].fillna("")
                         .str.split(";").explode().str.strip())

        add("## 자료 구성")
        add("")
        add("| 항목 | 값 |")
        add("|---|---:|")
        add(f"| 전체 조치 | {len(current):,}건 |")
        add(f"| 열 개수 (분석용 / 전체) | {len(ANALYSIS_COLUMNS)} / {len(COLUMN_ORDER)} |")
        add(f"| 가장 이른 발표일 | {announced.min():%Y-%m-%d} |")
        add(f"| 가장 늦은 발표일 | {announced.max():%Y-%m-%d} |")
        add(f"| 시행 관할 수 | {jurisdictions[jurisdictions != ''].nunique():,}곳 |")
        add(f"| 조치 유형 수 | {current['intervention_type'].dropna().nunique():,}종 |")
        missing = int(current[DESCRIPTION_COLUMN].fillna("").str.strip().eq("").sum())
        add(f"| 설명문 없는 건 | {missing:,}건 ({missing / len(current):.1%}) |")
        add("")

        add("## 산업정책 분류 (BERT)")
        add("")
        labels = current.apply(ip_label_of_row, axis=1).value_counts()
        add("| 분류 | 건수 | 비중 |")
        add("|---|---:|---:|")
        for name in IP_LABEL_NAMES + [IP_LABEL_MISSING]:
            n = int(labels.get(name, 0))
            add(f"| {name} | {n:,} | {n / len(current):.1%} |")
        add("")

        add("## 수출통제 조치 (MAST Chapter P 9종)")
        add("")
        ec = current[current["intervention_type"].isin(EXPORT_CONTROL_TYPES)]
        add(f"전체 {len(ec):,}건. 전체 표본의 {len(ec) / len(current):.1%}다.")
        add("")
        add("| 유형 | 건수 |")
        add("|---|---:|")
        ec_counts = ec["intervention_type"].value_counts()
        for name in EXPORT_CONTROL_TYPES:
            add(f"| {name} | {int(ec_counts.get(name, 0)):,} |")
        add("")

        add("## 발표연도 분포")
        add("")
        add("| 연도 | 건수 |")
        add("|---|---:|")
        for year, count in announced.dt.year.value_counts().sort_index().items():
            add(f"| {int(year)} | {count:,} |")
        add("")
        return "\n".join(out)

    add("## 표 보는 법")
    add("")
    add("아래 모든 표는 같은 일곱 열로 시작한다. 표마다 필요한 열은 그 뒤에 붙는다.")
    add("")
    add("| 열 | 뜻 |")
    add("|---|---|")
    add("| 발표일 | `date_announced`. 조치를 발표한 날 (등재일이 아니다) |")
    add("| 시행 관할 | `implementing_jurisdictions`. 조치를 시행하는 국가 |")
    add("| 제목 | `state_act_title` |")
    add("| 유형 | `intervention_type` |")
    add("| GTA 평가 | `gta_evaluation`. GTA의 3단계 평가 체계(Red/Amber/Green)다. "
        "Red·Amber = 외국 상업이익에 해로움, Green = 비차별적 자유화 |")
    add("| 산업정책 분류 | "
        f"{' / '.join(IP_LABEL_NAMES)} / {IP_LABEL_MISSING}(설명문 없어 분류 안 함) |")
    add("| ID | `intervention_id`. GTA 원문으로 가는 링크 |")
    add("")
    add("## 요약")
    add("")
    add("| 구분 | 건수 |")
    add("|---|---:|")
    add(f"| 신규 (직전 자료에 없던 건) | {len(diff['new']):,} |")
    add(f"| 수정 | {len(diff['changed']):,} |")
    add(f"| ㄴ BERT 라벨 바뀜 | {len(summary['label_changed']):,} |")
    add(f"| ㄴ 라벨은 그대로 | {len(diff['changed']) - len(summary['label_changed']):,} |")
    if diff.get("detect_removals", True):
        add(f"| 삭제 | {len(diff['removed']):,} |")
    else:
        add("| 삭제 | 확인 안 함 (빠른 업데이트 모드. 잠수함 패치 점검에서 확인) |")
    add("")
    curr = current.set_index("intervention_id")

    def table(ids: list[int], frame: pd.DataFrame, title: str, note: str = "") -> None:
        if not ids:
            return
        add(f"## {title} ({len(ids):,}건)")
        add("")
        if note:
            add(note)
            add("")
        add(REPORT_HEAD + "|")
        add(REPORT_SEP + "|")
        sub = frame.reindex(ids[:REPORT_ROW_CAP])
        for _, row in sub.iterrows():
            add("| " + " | ".join(report_cells(row)) + " |")
        if len(ids) > REPORT_ROW_CAP:
            add(f"| | | 외 {len(ids) - REPORT_ROW_CAP:,}건 생략 | | | | |")
        add("")

    if diff["new"]:
        lag = registration_lag(current, diff["new"], last_update)
        add("## 신규 — 발표 후 경과일별")
        add("")
        add("| 경과 | 건수 |")
        add("|---|---:|")
        for (_, name), n in zip(LAG_BUCKETS, lag_bucket_counts(lag)):
            add(f"| {name} | {n:,} |")
        if diff["new_no_date"]:
            add(f"| 발표일 없음 (경과일 못 잼) | {len(diff['new_no_date']):,} |")
        add("")
        ordered = sort_by_lag(current, diff["new"], last_update)
        add(f"### 신규 전체 목록 ({len(ordered):,}건, 오래된 것부터)")
        add("")
        add(REPORT_HEAD + "|")
        add(REPORT_SEP + "|")
        sub = curr.reindex(ordered[:REPORT_ROW_CAP])
        for _, row in sub.iterrows():
            add("| " + " | ".join(report_cells(row)) + " |")
        if len(ordered) > REPORT_ROW_CAP:
            add(f"| | | 외 {len(ordered) - REPORT_ROW_CAP:,}건 생략 | | | | |")
        add("")

    if diff["new_no_date"]:
        table(diff["new_no_date"], curr, "발표일이 비어 있는 건",
              "발표일이 없어 경과일을 잴 수 없다. GTA 원본을 확인해볼 것.")

    # before/after 없이 label_changed만 넘어오면 표를 만들 수 없다. 건너뛴다.
    if summary["label_changed"] and summary.get("before") is not None:
        ids = summary["label_changed"]
        len_before = description_lengths(previous, ids)
        len_after = description_lengths(current, ids)
        add(f"## BERT 라벨이 바뀐 건 ({len(ids):,}건)")
        add("")
        add("GTA가 설명문을 고쳐 분류 결과가 달라진 건이다. **설명문 길이 변화가 원인 단서다** — "
            "크게 줄었으면 GTA가 내용을 갈아끼운 것이고, 길이가 비슷한데 라벨이 바뀌었으면 "
            "경계선에 있던 건이라 따로 봐야 한다.")
        add("")
        # 공통 열의 '산업정책 분류'가 바뀐 뒤(=지금) 값이다. 그 앞이 무엇이었는지만 덧붙인다.
        add(REPORT_HEAD + "| 이전 분류 | 설명문 길이 |")
        add(REPORT_SEP + "|---|---|")
        for cid in ids[:REPORT_ROW_CAP]:
            row = curr.loc[cid]
            cells = report_cells(row)
            cells.append(str(summary["before"].loc[cid]))
            cells.append(f"{int(len_before[cid]):,} → {int(len_after[cid]):,}")
            add("| " + " | ".join(cells) + " |")
        add("")

    def subset_section(subset: dict[str, list[int]], heading: str,
                       label: str, short: str, note: str = "") -> None:
        """변경분의 부분집합 하나를 절로 쓴다. 수출통제·산업정책이 같이 쓴다."""
        total = sum(len(v) for v in subset.values())
        add(heading)
        add("")
        if note:
            add(note)
            add("")
        stamp = end_date.replace("-", "")[2:]   # 2026-08-21 -> 260821
        if total == 0:
            add(f"이번 변경분({stamp})에 {label}는 없다.")
            add("")
            return
        add(f"이번 변경분({stamp}) 중 {label} **{total:,}건**.")
        add("")
        add("| 구분 | 건수 |")
        add("|---|---:|")
        for key, title in (("new", "신규"),
                           ("changed", "수정"), ("removed", "삭제")):
            add(f"| {title} | {len(subset[key]):,} |")
        add("")
        label_changed = set(summary.get("label_changed") or [])
        fields_by_id = diff.get("changed_fields", {})
        for key, title, frame in (("new", "신규", current),
                                  ("changed", "수정", current),
                                  ("removed", "삭제", previous)):
            if not subset[key]:
                continue
            add(f"### {short} — {title} ({len(subset[key]):,}건)")
            add("")
            head = REPORT_HEAD + "|"
            sep = REPORT_SEP + "|"
            if key == "changed":
                head = REPORT_HEAD + "| 분류 바뀜 | 바뀐 항목 |"
                sep = REPORT_SEP + "|---|---|"
            add(head)
            add(sep)
            sub = frame.set_index("intervention_id").reindex(subset[key][:REPORT_ROW_CAP])
            for cid, row in sub.iterrows():
                cells = report_cells(row)
                if key == "changed":
                    cells.append("예" if cid in label_changed else "")
                    touched = [c for c in fields_by_id.get(int(cid), [])
                               if c != "state_act_source"]
                    cells.append(", ".join(f"`{c}`" for c in touched[:5]))
                add("| " + " | ".join(cells) + " |")
            add("")

    ec = export_control_changes(diff, previous, current)
    subset_section(ec, "## 수출통제 조치 (MAST Chapter P 9종)", "수출통제 조치", "수출통제")

    gone = check_export_control_types(current)
    if gone:
        add("### 경고 — 유형 이름이 사라졌다")
        add("")
        add("아래 유형이 자료에서 0건이다. GTA가 이름을 바꿨을 수 있고, "
            "그러면 표본이 조용히 작아진다.")
        add("")
        for name in gone:
            add(f"- `{name}`")
        add("")

    subset_section(
        industrial_policy_changes(diff, previous, current),
        "## 산업정책 조치 (BERT 분류)", "산업정책 조치", "산업정책", IP_CRITERION_NOTE)

    # 예전에는 여기서 열별 건수만 셌다. 어느 조치가 어떻게 바뀌었는지는
    # 그 표로 알 수 없어서, 조치별 목록으로 갈음한다.
    for line in changed_detail_lines(diff, curr):
        add(line)

    if diff["removed"]:
        table(diff["removed"], previous.set_index("intervention_id"), "삭제",
              "GTA에서 사라진 건. 이번 스냅숏부터 표본에서 빠진다.")

    if not any(diff[k] for k in ("new", "changed", "removed")):
        add("바뀐 것이 없다.")
        add("")
    return "\n".join(out)


# --------------------------------------------------------------- 파일 출력




def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# 무인 실행(GitHub Actions)의 멈춤 조건. 걸리면 Failure -> 종료코드 1 이고
# master.parquet·state.json 을 쓰지 않으므로 Release 의 직전 상태가 그대로 남는다.
MAX_DROP_PCT = float(os.environ.get("MAX_DROP_PCT", "5"))     # 전체 표본 감소 허용 %
MAX_REMOVED = int(os.environ.get("MAX_REMOVED", "500"))      # full 모드 삭제 건수 상한


def guard(previous: pd.DataFrame | None, current: pd.DataFrame, diff: dict,
          mode: str, first_run: bool) -> None:
    gone = check_export_control_types(current)
    if gone:
        fail(f"수출통제 유형명 {len(gone)}개가 자료에 0건입니다 (GTA 가 이름을 바꿨을 수 있음): {', '.join(gone)}")
    if current["intervention_id"].isna().any():
        fail("intervention_id 결측이 있습니다.")
    if list(current.columns) != COLUMN_ORDER:
        fail(f"열 구조가 기준({len(COLUMN_ORDER)}개)과 다릅니다: {len(current.columns)}개")
    if first_run or previous is None or len(previous) == 0:
        return
    drop_pct = (len(previous) - len(current)) / len(previous) * 100
    if drop_pct > MAX_DROP_PCT:
        fail(f"전체 표본이 {len(previous):,} -> {len(current):,}건으로 {drop_pct:.1f}% 줄었습니다 (한도 {MAX_DROP_PCT}%).")
    if mode == "full" and len(diff["removed"]) > MAX_REMOVED:
        fail(f"삭제 {len(diff['removed']):,}건이 한도 {MAX_REMOVED:,}건을 넘습니다.")


def validate(plain: pd.DataFrame, expanded: pd.DataFrame) -> None:
    if list(plain.columns) != ANALYSIS_COLUMNS:
        fail(f"분석용 열 구조가 기준({len(ANALYSIS_COLUMNS)}개)과 다릅니다: {len(plain.columns)}개")
    if list(expanded.columns) != COLUMN_ORDER:
        fail(f"확장판 열 구조가 기준({len(COLUMN_ORDER)}개)과 다릅니다: {len(expanded.columns)}개")
    if len(plain) != len(expanded):
        fail("두 파일의 행 수가 다릅니다.")
    if not plain["intervention_id"].equals(expanded["intervention_id"]):
        fail("두 파일의 intervention_id 순서가 다릅니다.")
    if plain["intervention_id"].duplicated().any():
        fail("출력에 intervention_id 중복이 있습니다.")
    sums = plain[LABEL_COLUMNS].sum(axis=1, min_count=1)
    if not (sums.eq(1) | plain[LABEL_COLUMNS].isna().all(axis=1)).all():
        fail("BERT 라벨 one-hot 구조가 잘못된 행이 있습니다.")
    has_label = plain[LABEL_COLUMNS].notna().all(axis=1)
    has_text = expanded[DESCRIPTION_COLUMN].fillna("").str.strip().ne("")
    if (has_label & ~has_text).any():
        fail("description이 없는데 BERT 라벨이 붙은 행이 있습니다.")


# ------------------------------------------------------------------ 실행


def load_state() -> dict | None:
    if not STATE_PATH.exists():
        return None
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def load_master() -> pd.DataFrame | None:
    if not MASTER_PATH.exists():
        return None
    return pd.read_parquet(MASTER_PATH)


def ask_yes_no(question: str, default: bool = True) -> bool:
    """대화형이 아니면 default를 쓴다. 덮어쓰기처럼 되돌릴 수 없는 물음은 False.

    isatty()가 참이어도 입력이 닫혀 있으면 EOFError가 난다(리디렉션·작업 스케줄러
    등). 그때도 죽지 않고 default로 넘어간다.
    """
    if not sys.stdin or not sys.stdin.isatty():
        return default
    hint = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{question} {hint} ").strip().lower()
        except EOFError:
            say(f"\n    입력을 받을 수 없어 기본값({'예' if default else '아니오'})으로 진행합니다.")
            return default
        if answer == "":
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        say("    y 또는 n 을 입력해 주세요.")


def main() -> int:
    parser = argparse.ArgumentParser(description="SKL Economic Security Tracker 업데이트")
    parser.add_argument("--end-date", help="자료 종료일 YYYY-MM-DD (기본: 오늘)")
    parser.add_argument(
        "--mode", choices=["incremental", "full"], default="full",
        help="incremental=빠른 업데이트, full=잠수함 패치 점검 (기본: full)",
    )
    parser.add_argument("--yes", action="store_true", help="확인 없이 진행")
    args = parser.parse_args()

    api_key = os.environ.get("GTA_API_KEY", "").strip()
    if not api_key:
        fail("GTA_API_KEY가 없습니다. 원클릭 실행 파일로 실행해 주세요.")

    end_date = args.end_date or date.today().isoformat()
    try:
        end = date.fromisoformat(end_date)
    except ValueError:
        fail(f"종료일 형식이 잘못되었습니다: {end_date} (YYYY-MM-DD 로 입력)")
    if end > date.today():
        fail(f"종료일이 미래입니다: {end_date}")
    if end < date.fromisoformat(START_DATE):
        fail(f"종료일이 시작일({START_DATE})보다 앞섭니다: {end_date}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    state = load_state()
    previous = load_master() if state else None
    last_update = state.get("data_end_date") if state else None
    first_run = previous is None
    mode = "full" if first_run else args.mode

    say()
    if first_run:
        say(f"  최초 구축입니다. {START_DATE}부터 전량을 받아 BERT로 분류합니다.")
        say("  BERT 분류에 여러 시간이 걸립니다 (GPU 없이 약 2.3건/초).")
        if args.mode == "incremental":
            say("  (보유 자료가 없어 증분 모드를 쓸 수 없습니다. 전체 구축으로 진행합니다.)")
    else:
        say(f"  직전 업데이트  {last_update}  ({state.get('rows', 0):,}건)")
        say("  실행 모드      "
            + ("최초 구축" if first_run
               else "빠른 업데이트" if mode == "incremental" else "잠수함 패치 점검"))
    say(f"  이번 종료일    {end_date}")
    say()

    cache = load_prediction_cache()
    classifier = Classifier()

    if mode == "full":
        say(f"1/5  GTA 자료 전량 수집 ({START_DATE} ~ {end_date})")
        current = flatten(fetch_all(api_key, end_date))
        say(f"    전체 {len(current):,}건")

        say()
        say("2/5  BERT 분류")
        current, newly_classified = classify(current, cache, classifier, "분류")
        say(f"    새로 분류한 description {newly_classified:,}건 (나머지는 캐시 재사용)")
    else:
        say(f"1/5  변경분 수집 (last_updated {last_update} ~ {end_date}, 포함)")
        raw = fetch_incremental(api_key, last_update, end_date)
        say()
        say("2/5  BERT 분류")
        if raw:
            increment, newly_classified = classify(flatten(raw), cache, classifier, "분류")
            say(f"    새로 분류한 description {newly_classified:,}건 (나머지는 캐시 재사용)")
            # 받아온 건만 교체하고 나머지는 직전 결과의 라벨을 그대로 유지한다.
            # 전체를 다시 classify하면 캐시에 없는 과거 건의 라벨이 지워진다.
            keep = previous[~previous["intervention_id"].isin(increment["intervention_id"])]
            current = pd.concat([keep, increment], ignore_index=True)
        else:
            say("    변경분이 없습니다.")
            newly_classified = 0
            current = previous.copy()

    current = current.sort_values(
        ["date_announced", "intervention_id"], kind="stable", na_position="last"
    ).reset_index(drop=True)
    current = current[COLUMN_ORDER]
    if current["intervention_id"].duplicated().any():
        fail("병합 결과에 intervention_id 중복이 있습니다.")

    say()
    say("3/5  직전 스냅숏과 대조")
    diff = compare(previous, current, last_update, detect_removals=(mode == "full"))
    if first_run:
        say("    최초 구축이라 대조 대상이 없습니다.")
        summary = {"label_changed": []}
        export_control = {k: [] for k in ("new", "changed", "removed")}
        industrial_policy = {k: [] for k in ("new", "changed", "removed")}
        gone = check_export_control_types(current)
        if gone:
            say(f"    경고: 수출통제 유형 {len(gone)}개가 자료에 없습니다 — {', '.join(gone)}")
    else:
        summary = report_changes(diff, previous, current, last_update, end_date)
        no_change = not any(diff[k] for k in ("new", "changed", "removed"))
        if no_change:
            say("  바뀐 것이 없습니다. 엑셀을 새로 만들지 않고 종료합니다.")
            return NOTHING_WRITTEN
        export_control = report_export_controls(diff, previous, current, summary, args)
        industrial_policy = industrial_policy_changes(diff, previous, current)
        say()
        if not args.yes and not ask_yes_no("  이대로 엑셀을 만들까요?"):
            say("  취소했습니다. 파일을 만들지 않았습니다.")
            return NOTHING_WRITTEN

    say()
    say("4/5  멈춤 조건 검사")
    guard(previous, current, diff, mode, first_run)
    validate(current[ANALYSIS_COLUMNS].copy(), current.copy())
    say("    통과")

    say()
    say("5/5  저장")
    current.to_parquet(MASTER_PATH, index=False)
    missing_desc = int(current[DESCRIPTION_COLUMN].fillna("").str.strip().eq("").sum())
    # 삭제를 실제로 확인했는지. 증분 모드는 받지 않은 건과 사라진 건을 구분할 수
    # 없어 판단하지 않는다. 0과 "모름"을 같은 자리에 적으면 안 된다.
    removals_checked = bool(diff.get("detect_removals", True))
    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "analysis_unit": "GTA intervention",
        "data_period": [START_DATE, end_date],
        "previous_data_end_date": last_update,
        "first_run": first_run,
        "mode": mode,
        "rows": len(current),
        "columns_analysis": len(ANALYSIS_COLUMNS),
        "columns_full": len(COLUMN_ORDER),
        "missing_descriptions_count": missing_desc,
        "missing_descriptions_share": missing_desc / len(current),
        "newly_classified_descriptions": newly_classified,
        "missing_api_fields": getattr(flatten, "missing_optional", []),
        "removals_checked": removals_checked,
        "changes": {
            "new": len(diff["new"]),
            "new_no_date": len(diff["new_no_date"]),
            "changed": len(diff["changed"]),
            "removed": len(diff["removed"]) if removals_checked else None,
            "bert_label_changed": len(summary["label_changed"]),
            "new_ids": diff["new"][:200],
            "changed_ids": diff["changed"][:200],
            "new_no_date_ids": diff["new_no_date"][:200],
            "removed_ids": diff["removed"][:200] if removals_checked else None,
            "bert_label_changed_ids": summary["label_changed"][:200],
        },
        "export_control": {
            "types": EXPORT_CONTROL_TYPES,
            "new": len(export_control["new"]),
            "changed": len(export_control["changed"]),
            "removed": len(export_control["removed"]) if removals_checked else None,
            "ids": {k: v[:200] for k, v in export_control.items()},
        },
        "industrial_policy": {
            "basis": LABEL_COLUMNS[0],
            "new": len(industrial_policy["new"]),
            "changed": len(industrial_policy["changed"]),
            "removed": len(industrial_policy["removed"]) if removals_checked else None,
            "ids": {k: v[:200] for k, v in industrial_policy.items()},
        },
        "model_repo": MODEL_REPO,
        "model_revision": MODEL_REVISION,
        "python": platform.python_version(),
        "outputs": {"master.parquet": {"bytes": MASTER_PATH.stat().st_size, "sha256": sha256_file(MASTER_PATH)}},
    }
    run_stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOGS / f"run_manifest_{run_stamp}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    report_path = LOGS / f"change_report_{run_stamp}.md"
    report_path.write_text(
        build_change_report(diff, summary, previous, current, last_update,
                            end_date, mode, first_run),
        encoding="utf-8",
    )
    STATE_PATH.write_text(json.dumps({
        "data_end_date": end_date,
        "rows": len(current),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "last_mode": mode,
        # 마지막으로 전체 점검을 한 날. 증분 실행은 이 값을 건드리지 않는다.
        "last_full_rebuild": end_date if mode == "full" else (state or {}).get("last_full_rebuild"),
        "last_output": None,  # 2026-10-22 엑셀 생성 중단(CI 전환)
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    say()
    say("=" * 66)
    say("  완료")
    say("=" * 66)
    say(f"  자료 기준일   {end_date}")
    say(f"  전체          {len(current):,}건")
    if not first_run:
        say(f"  새로 들어온 것 {len(diff['new']):,}건"
            + (f"  (그중 발표일 없음 {len(diff['new_no_date']):,}건)"
               if diff["new_no_date"] else ""))
        say(f"  수정          {len(diff['changed']):,}건  (라벨 바뀜 {len(summary['label_changed']):,}건)")
        # 증분 모드는 삭제를 판단하지 않는다. 여기서 0건이라고 찍으면 나중에
        # 로그만 보는 사람이 "삭제가 없었다"로 잘못 읽는다.
        removed_text = f"{len(diff['removed']):,}건" if removals_checked else "확인 안 함"
        say(f"  삭제          {removed_text}")
        ec_total = sum(len(v) for v in export_control.values())
        ec_removed = f"{len(export_control['removed']):,}" if removals_checked else "확인 안 함"
        say(f"  ㄴ 수출통제    {ec_total:,}건  (새로 들어온 것 {len(export_control['new']):,} "
            f"· 수정 {len(export_control['changed']):,} "
            f"· 삭제 {ec_removed})")
        ip_total = sum(len(v) for v in industrial_policy.values())
        ip_removed = f"{len(industrial_policy['removed']):,}" if removals_checked else "확인 안 함"
        say(f"  ㄴ 산업정책    {ip_total:,}건  (새로 들어온 것 {len(industrial_policy['new']):,} "
            f"· 수정 {len(industrial_policy['changed']):,} "
            f"· 삭제 {ip_removed})")
    say(f"  description 없음  {missing_desc:,}건 ({missing_desc / len(current):.1%})")
    say()
    say(f"  변경 내역   logs/{report_path.name}")
    say()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Failure as exc:
        print(f"\n[실패] {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[중단] 사용자가 취소했습니다.", file=sys.stderr)
        sys.exit(130)
