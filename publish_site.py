"""SKL Economic Security Tracker — 변경 내역을 정적 웹사이트로 만든다.

logs/change_report_*.md 를 읽어 site/ 아래에 HTML을 쓴다. 비밀값은 다루지
않는다. 배포는 GitHub Actions(.github/workflows/pipeline.yml)가 site/ 를
GitHub Pages 로 올린다(2026-10-22, Cloudflare Pages 에서 이전).

  site/
    index.html              랜딩(띠 + 패널 2개 + 최근 변경)
    ip_risk.html, ai_coop.html, review.html, data.html
    codebook.html           문서/코드북_패널.md + 문서/코드북.md 를 접힌 절로
    r/<stamp>.html          변경 리포트 하나

markdown 변환은 markdown 라이브러리에 맡긴다. 직접 짜지 않는 이유는 리포트
표 칸이 GTA 원문을 그대로 담기 때문이다. auto_update.py 의 cell() 은 `|` 만
escape 하고 `&`·`<` 는 통과시킨다. 'R&D' 같은 흔한 제목이 그대로 HTML 로
새면 화면이 깨진다.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import ai_coop_site
import industrial_policy_site
import ip_risk_site

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"
SITE = HERE / "site"
DOCS = HERE / "문서"
CODEBOOK_PANELS = DOCS / "코드북_패널.md"   # 화면 방법론(패널 1·2) — codebook.html 앞부분
CODEBOOK_GTA = DOCS / "코드북.md"           # GTA 자료 코드북 — codebook.html 뒷부분
REPO_URL = "https://github.com/lskyonsei-jpg/skl-economic-security-tracker"
STATE_PATH = HERE / "cache" / "state.json"
STATE: dict = json.loads(STATE_PATH.read_text(encoding="utf-8")) if STATE_PATH.is_file() else {}

SITE_TITLE = "SKL Economic Security Tracker"
REPORT_GLOB = "change_report_*.md"
REPORT_STAMP = re.compile(r"^change_report_(\d{8})_(\d{6})\.md$")

# 리포트 머리말의 "- 이름: 값" 줄. 값이 없으면 None 으로 둔다.
META_LINE = re.compile(r"^-\s*([^:]+?)\s*:\s*(.+?)\s*$", re.M)

# "## 요약" 표의 각 줄. 건수 자리에 "확인 안 함 (...)" 같은 글도 들어온다.
SUMMARY_ROW = re.compile(r"^\|\s*(?!구분|-)([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$", re.M)

# 2026-08-21부터 변경 리포트가 두 관심군의 합계를 본문에 직접 쓴다.
# 이전 리포트도 목록에서 빠지지 않도록 아래 Report.topic_counts()에서 호환 처리한다.
CHANGED_TOPIC_COUNT = re.compile(
    r"이번 변경분(?:\([^)]*\))? 중 (수출통제|산업정책) 조치 \*\*([\d,]+)건\*\*"
)


def parse_stamp(name: str) -> datetime | None:
    matched = REPORT_STAMP.match(name)
    if not matched:
        return None
    try:
        return datetime.strptime(matched.group(1) + matched.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def section(text: str, heading: str) -> str:
    """`## heading` 부터 다음 `## ` 직전까지."""
    start = re.search(rf"^##\s+{re.escape(heading)}\s*$", text, re.M)
    if not start:
        return ""
    rest = text[start.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def summary_of(text: str) -> dict[str, str]:
    """요약 표를 {구분: 건수} 로. 없으면 빈 dict."""
    block = section(text, "요약")
    if not block:
        return {}
    out: dict[str, str] = {}
    for label, value in SUMMARY_ROW.findall(block):
        if set(label) <= set("-: "):      # 구분선 행
            continue
        out[label.strip()] = value.strip()
    return out


def meta_of(text: str) -> dict[str, str]:
    head = text.split("##", 1)[0]
    return {k.strip(): v.strip() for k, v in META_LINE.findall(head)}


def pick(summary: dict[str, str], prefix: str) -> str | None:
    """'신규 (발표일 ...)' 처럼 뒤에 괄호가 붙는 열쇠를 앞부분으로 찾는다."""
    for key, value in summary.items():
        if key.startswith(prefix):
            return value
    return None


class Report:
    def __init__(self, path: Path, when: datetime):
        self.path = path
        self.when = when
        self.text = path.read_text(encoding="utf-8")
        self.meta = meta_of(self.text)
        self.summary = summary_of(self.text)

    @property
    def slug(self) -> str:
        return self.when.strftime("%Y%m%d_%H%M%S")

    @property
    def data_date(self) -> str:
        return self.meta.get("자료 기준일") or self.when.strftime("%Y-%m-%d")

    @property
    def mode(self) -> str:
        return self.meta.get("실행 모드") or ""

    @property
    def rows(self) -> str:
        return self.meta.get("전체 표본") or ""

    def counts(self) -> list[tuple[str, str]]:
        """목록 화면에 배지로 띄울 값. 없는 항목은 조용히 뺀다.

        2026-08-13에 '신규'(직전 기준일 이후 발표)와 '지연 등재'(그 이전 발표)를
        나누지 않기로 했다. 매일 받으면 '신규'가 구조적으로 늘 0이라 뜻이 없다.
        auto_update.py 는 그날부터 '새로 들어온 것' 한 줄로 쓰지만, 그 전에 만든
        리포트는 두 줄로 남아 있다. 여기서 합쳐 화면 표기를 하나로 맞춘다.
        """
        new_total = 0
        found_new = False
        for key, value in self.summary.items():
            if not key.startswith(("새로 들어온 것", "신규", "지연 등재")):
                continue
            digits = value.split("(")[0].strip().replace(",", "")
            if digits.isdigit():
                new_total += int(digits)
                found_new = True

        out: list[tuple[str, str]] = []
        if found_new:
            out.append(("신규", f"{new_total:,}"))
        for label in ("수정", "삭제"):
            value = pick(self.summary, label)
            if not value:
                continue
            # 삭제 칸에는 '확인 안 함 (빠른 업데이트 모드)' 처럼 사유가 붙는다.
            # 배지에는 앞부분만 쓴다. 전문은 리포트 안 요약표에 그대로 있다.
            out.append((label, value.split("(")[0].strip() or value))
        out.extend(self.topic_counts(found_new))
        return out

    def topic_counts(self, is_change_report: bool) -> list[tuple[str, str]]:
        """이번 변경분 중 수출통제·산업정책 건수를 목록 배지로 돌려준다.

        새 형식은 본문의 명시적 합계를 사용한다. 2026-08-19~20 구형 리포트는
        수출통제 0건 문구와 신규 전체 목록의 BERT 라벨을 읽는다. 최초 구축
        리포트에는 변경분이 없으므로 당시 전체 표본의 두 관심군 총수를 쓴다.
        """
        explicit = {
            label: int(value.replace(",", ""))
            for label, value in CHANGED_TOPIC_COUNT.findall(self.text)
        }
        export_block = section(self.text, "수출통제 조치 (MAST Chapter P 9종)")

        if "수출통제" not in explicit and "수출통제 조치는 없다" in export_block:
            explicit["수출통제"] = 0

        if is_change_report and "산업정책" not in explicit:
            # 전용 산업정책 절이 생기기 전 리포트: 수출통제 절 앞의 주 변경표만
            # 대상으로 삼아 분포표나 전용 표의 중복을 피한다.
            main_changes = re.split(r"^##\s+수출통제 조치", self.text, maxsplit=1, flags=re.M)[0]
            explicit["산업정책"] = sum(
                1 for line in main_changes.splitlines()
                if line.startswith("|") and "산업정책" in [cell.strip() for cell in line.strip("|").split("|")]
            )

        if not is_change_report:
            if "수출통제" not in explicit:
                matched = re.search(r"전체\s+([\d,]+)건", export_block)
                if matched:
                    explicit["수출통제"] = int(matched.group(1).replace(",", ""))
            if "산업정책" not in explicit:
                ip_block = section(self.text, "산업정책 분류 (BERT)")
                matched = re.search(r"^\|\s*산업정책\s*\|\s*([\d,]+)\s*\|", ip_block, re.M)
                if matched:
                    explicit["산업정책"] = int(matched.group(1).replace(",", ""))

        return [
            (label, f"{explicit[label]:,}")
            for label in ("수출통제", "산업정책") if label in explicit
        ]



def page(title: str, body: str, depth: int = 0, current: str = "") -> str:
    up = "../" * depth
    nav = ai_coop_site.nav(current)
    foot = ai_coop_site.footer(STATE.get("data_end_date", "—"), datetime.now().strftime("%Y-%m-%d %H:%M"))
    if depth:
        nav = nav.replace('href="', f'href="{up}')
        foot = foot.replace('href="', f'href="{up}')
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{up}site.css">
</head>
<body>
{nav}
{body}
{foot}
</body>
</html>
"""


ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.S)
CELL_RE = re.compile(r"<td[^>]*>.*?</td>", re.S)
EMPTY_CELL_RE = re.compile(r"^<td[^>]*>\s*</td>$", re.S)


def merge_blank_cells(html_text: str) -> str:
    """빈 칸으로 이어지는 줄을 위 칸의 rowspan 으로 합친다.

    마크다운 표에는 rowspan 이 없다. 수정사항 목록은 한 조치가 여러 줄을
    차지하면서 공통 여섯 열을 첫 줄에만 적고 나머지는 비워 두는데, 그대로
    두면 줄마다 칸 테두리가 생겨 같은 조치가 여러 건처럼 보인다. 여기서
    이어지는 빈 칸을 없애고 위 칸을 그만큼 늘린다.

    왼쪽부터 연속으로 비어 있는 칸만 합친다. 표 중간의 빈 칸(값이 없어서 빈
    것)은 건드리지 않는다.
    """
    rows = [(m.start(1), m.end(1), CELL_RE.findall(m.group(1)))
            for m in ROW_RE.finditer(html_text)]
    # 각 줄의 칸을 (남길 것, 위 칸에 더할 rowspan) 으로 정리한다.
    keep: list[list[str]] = [list(cells) for _, _, cells in rows]
    span: list[dict[int, int]] = [{} for _ in rows]
    owner: dict[int, int] = {}   # 열 -> 그 열을 열어 둔 줄 번호
    for i, cells in enumerate(keep):
        # "외 N건 생략" 줄도 앞 칸이 비어 있지만 위 조치의 일부가 아니다.
        if any("생략" in c for c in cells):
            owner = {}
            continue
        for col, cell in enumerate(cells):
            if EMPTY_CELL_RE.match(cell.strip()) and col in owner:
                src = owner[col]
                span[src][col] = span[src].get(col, 1) + 1
                keep[i][col] = ""
            elif EMPTY_CELL_RE.match(cell.strip()):
                break            # 왼쪽부터 이어지지 않으면 합치지 않는다
            else:
                owner[col] = i
        # 칸 수가 다른 표(줄)를 만나면 열 소유권을 버린다.
        if not cells:
            owner = {}
    out, last = [], 0
    for (start, end, _), cells, spans in zip(rows, keep, span):
        out.append(html_text[last:start])
        if not cells:
            # 머리줄(<th>)에는 손댈 것이 없다. 원문 그대로 둔다.
            out.append(html_text[start:end])
            last = end
            continue
        row = []
        for col, cell in enumerate(cells):
            if not cell:
                continue
            n = spans.get(col)
            row.append(cell.replace("<td", f'<td rowspan="{n}"', 1) if n else cell)
        out.append("".join(row) if row else "".join(cells))
        last = end
    out.append(html_text[last:])
    return "".join(out)


# 표가 든 절은 제목만 남기고 접어 둔다. 신규 전체 목록처럼 100줄이 넘는 표가
# 페이지를 다 차지해 다음 절로 넘어가기 힘들었다(2026-08-27 지시).
# h2/h3 하나부터 다음 제목 직전까지를 한 절로 본다. 겹쳐 싸지 않는다.
SECTION_RE = re.compile(r"<h([23])>(.*?)</h\1>(.*?)(?=<h[23]>|\Z)", re.DOTALL)


def wrap_tables(html_text: str) -> str:
    """표를 가로 스크롤 상자에 넣는다."""
    return html_text.replace("<table>", '<div class="tablebox"><table>') \
                    .replace("</table>", "</table></div>")


def collapse_sections(html_text: str) -> str:
    """표가 있는 절을 <details> 로 접는다. 제목 줄이 그대로 여닫는 손잡이다."""
    def one(match: re.Match) -> str:
        level, title, body = match.group(1), match.group(2), match.group(3)
        if "<table>" not in body:
            return match.group(0)   # 표 없는 절은 접을 것이 없다
        return (f'<details class="sec lv{level}">'
                f"<summary>{title}</summary>"
                f'<div class="secbody">{body}</div></details>')

    return SECTION_RE.sub(one, html_text)


def to_html(md_text: str) -> str:
    import markdown as md

    out = md.markdown(md_text, extensions=["tables", "sane_lists"])
    out = merge_blank_cells(out)
    # 넓은 표가 화면 밖으로 밀려나지 않게 가로 스크롤 상자로 감싼다.
    return collapse_sections(wrap_tables(out))


def render_report(report: Report) -> str:
    body = to_html(report.text)
    head = '<main class="wrap" style="padding-top:32px"><a class="back" href="../index.html">← 전체 목록</a>\n<article>\n'
    return page(f"{report.data_date} 변경 내역 · {SITE_TITLE}",
                head + body + "\n</article></main>", depth=1, current="index.html")


def render_index(reports: list[Report]) -> str:
    newest = reports[0] if reports else None
    asof = STATE.get("data_end_date") or (newest.data_date if newest else "—")
    rows = STATE.get("rows")
    meta = [("자료 기준일", asof), ("전체 표본", f"{rows:,}건" if rows else (newest.rows if newest else "—")),
            ("변경 리포트", f"{len(reports)}건"), ("마지막 전량 점검", STATE.get("last_full_rebuild") or "—")]
    meta_html = "".join(f"<div>{html.escape(k)}<b>{html.escape(str(v))}</b></div>" for k, v in meta)
    hero = (f'<header class="hero"><div class="wrap"><span class="eyebrow">Research Dashboard</span>'
            f'<h1>{html.escape(SITE_TITLE)}</h1>'
            f'<p>GTA 개입 조치를 매일 수집해 BERT로 산업정책 후보를 가려내고, 지정학적 거리와 교차해 봅니다. 두 번째 패널은 한미 AI 협력 사건을 추적합니다.</p>'
            f'<div class="meta">{meta_html}</div></div></header>')
    pending = ai_coop_site.pending_proposals()
    banner = ""
    if pending:
        by = {k: sum(1 for p in pending if p["task"] == k) for k in "ABC"}
        banner = (f'<section class="section" style="padding:20px 0"><div class="wrap"><a class="panel-card muted" href="review.html" style="min-height:0;padding:18px 24px">'
                  f'<span class="eyebrow" style="margin-bottom:6px">판단 대기</span><h2 style="margin:0">제안 {len(pending)}건 — 새 사건 {by["A"]} · 갱신 {by["B"]} · 재검토 {by["C"]}</h2>'
                  f'<span class="go">열기 →</span></a></div></section>')
    cards = ('<section class="section"><div class="wrap"><span class="eyebrow">Panels</span><div class="grid grid-2">'
             '<a class="panel-card" href="ip_risk.html"><span class="eyebrow">Panel 1</span><h2>Distortive Industrial Policy Tracker</h2>'
             '<p>GTA Red·Amber 산업정책 조치의 피영향국 노출 × BSV 지정학적 거리 — 지도·순위·추이·산점도·블록 구성</p>'
             '<span class="go">열기 →</span></a>'
             '<a class="panel-card" href="ai_coop.html"><span class="eyebrow">Panel 2</span><h2>한미 AI 협력 트래커</h2>'
             '<p>한미 정부·민간의 AI 협력 사건을 형태·분야별 타임라인과 매트릭스로</p>'
             '<span class="go">열기 →</span></a></div></div></section>')
    items = []
    for report in reports[:10]:
        badges = "".join(f'<span class="badge">{html.escape(l)} <b>{html.escape(v)}</b></span>' for l, v in report.counts())
        items.append(f'<li><span class="d"><a href="r/{report.slug}.html">{html.escape(report.data_date)}</a></span>'
                     f'<span>{badges}</span><span class="m">{html.escape(report.mode)} · {report.when.strftime("%m-%d %H:%M")}</span></li>')
    changes = ('<section class="section"><div class="wrap"><span class="eyebrow">Recent changes</span>'
               '<div class="panel"><div class="panel-head"><span>GTA 변경 리포트 (최신순)</span><a href="data.html">자료 내려받기 →</a></div>'
               f'<div class="panel-body"><ul class="changes">{"".join(items) or "<li>아직 리포트가 없습니다.</li>"}</ul></div></div></div></section>')
    return page(SITE_TITLE, hero + banner + cards + changes, current="index.html")


# 파이프라인이 실제로 호출하는 외부 API. 코드의 상수와 같이 바뀌어야 한다.
#   (이름, 끝점, 용도, 주기, 키, 코드 위치)
APIS = [
    ("Global Trade Alert API v2", "api.globaltradealert.org/api/v2/gta/data/", "개입 조치 전량 수집 (패널 1)", "매일", "GTA_API_KEY", "auto_update.py"),
    ("Hugging Face Hub", "industrialpolicygroup/industrialpolicy-classifier", "BERT 산업정책 분류 모델 (revision 고정)", "매일 (새 건만 분류)", "없음", "auto_update.py"),
    ("Harvard Dataverse", "dataverse.harvard.edu · doi:10.7910/DVN/LEJUQZ", "BSV UN 표결 ideal point (파일 ID 고정)", "매월 4일", "없음", "collect_reference.py"),
    ("IMF Data SDMX 2.1", "api.imf.org/external/sdmx/2.1 · IMF.STA,IMTS", "DOTS 양자 상품무역 (미·중 기준)", "매월 4일", "없음", "collect_reference.py"),
    ("World Bank API v2", "api.worldbank.org/v2 · NY.GDP.MKTP.CD", "WDI 경상 GDP", "매월 4일", "없음", "collect_reference.py"),
    ("Anthropic API", "claude-opus-5-5 (effort medium)", "AI 협력 사건 탐지·코딩·재검토 제안 (패널 2)", "매일", "ANTHROPIC_API_KEY", "collect_ai_coop.py · ai_coop_tasks.py"),
    ("Google News RSS · Bing News", "news.google.com/rss/search · bing.com/news/search", "AI 협력 기사 탐지", "매일", "없음", "ai_coop_tasks.py"),
    ("Internet Archive Wayback", "archive.org/wayback/available", "유료벽 기사 본문 대체 수집", "필요 시", "없음", "collect_ai_coop.py"),
    ("GitHub REST API", "api.github.com/repos/…/issues", "판단 대기 페이지에서 제출한 결정 회수", "매일", "GITHUB_TOKEN (Actions 기본)", "ai_coop_tasks.py"),
    ("GitHub Release “state”", "gh release download/upload", "master.parquet·예측 캐시·기준자료·사건 파일 보관", "매 실행", "GITHUB_TOKEN (Actions 기본)", "pipeline.yml"),
]


def render_data(reports: list[Report]) -> str:
    repo = REPO_URL
    files = [("ip_risk.json", "패널 1 — 국가·연도별 리스크·노출·거리"), ("ip_sectors.json", "패널 1 — 조치 단위 원자료(산점도·회귀)"),
             ("ai_coop.json", "패널 2 — 사건 목록과 집계"), ("world.geojson", "지도 (Natural Earth 1:110m)")]
    rows = "".join(f'<tr><td><a href="{f}" download>{f}</a></td><td>{html.escape(d)}</td></tr>' for f, d in files)
    api_rows = "".join(
        f'<tr><td>{html.escape(n)}<span class="small">{html.escape(ep)}</span><span class="small">{html.escape(where)}</span></td>'
        f'<td>{html.escape(use)}</td><td>{html.escape(when)}</td><td>{html.escape(key)}</td></tr>'
        for n, ep, use, when, key, where in APIS)
    body = (f'<header class="hero"><div class="wrap"><span class="eyebrow">Data</span><h1>자료와 코드</h1>'
            f'<p>화면이 쓰는 JSON, 저장소, 연결된 API 목록. 열 정의와 산식은 <a href="codebook.html">코드북</a>에 있습니다.</p></div></header>'
            f'<section class="section"><div class="wrap grid grid-2"><div class="panel"><div class="panel-head">사이트 JSON</div>'
            f'<div class="panel-body"><table><tbody>{rows}</tbody></table></div></div>'
            f'<div class="panel"><div class="panel-head">저장소</div><div class="panel-body"><p><a href="{repo}">github.com/lskyonsei-jpg/skl-economic-security-tracker</a></p>'
            f'<p><a href="{repo}/releases/tag/state">Release “state”</a> — master.parquet(GTA 전량 + BERT 라벨), prediction_cache.json, state.json, 변경 리포트, 기준자료, AI 협력 사건 파일</p>'
            f'<p><a href="{repo}/actions">Actions</a> — 매일 06:00 KST 갱신·배포 기록</p>'
            f'<p><a href="codebook.html" class="btn">Codebook</a></p></div></div></div></section>'
            f'<section class="section"><div class="wrap"><span class="eyebrow">APIs</span><div class="panel"><div class="panel-head">연결된 API</div>'
            f'<div class="tablebox" style="border:0;margin:0"><table class="api-table"><thead><tr><th style="width:42%">API · 코드</th><th>용도</th><th style="width:11%">주기</th><th style="width:17%">키</th></tr></thead><tbody>{api_rows}</tbody></table></div>'
            f'<div class="panel-body"><p class="note">키는 GitHub Secrets에만 있습니다. 코드에 담지 않습니다.</p></div></div></div></section>')
    return page(f"자료 · {SITE_TITLE}", body, current="data.html")


H2_SECTION_RE = re.compile(r"<h2>(.*?)</h2>(.*?)(?=<h2>|\Z)", re.DOTALL)
H2_ID_RE = re.compile(r"^\{#([\w-]+)\}\s*")


def collapse_h2(html_text: str) -> str:
    """h2 절을 전부 <details> 로 접는다(코드북 전용). 제목 앞 `{#id}` 는 앵커 id 가 된다."""
    def one(match: re.Match) -> str:
        title, body = match.group(1), match.group(2)
        anchor = ""
        m = H2_ID_RE.match(title)
        if m:
            anchor, title = f' id="{m.group(1)}"', title[m.end():]
        return (f'<details class="sec lv2"{anchor}><summary>{title}</summary>'
                f'<div class="secbody">{body}</div></details>')
    return H2_SECTION_RE.sub(one, html_text)


def md_to_html_plain(md_text: str) -> str:
    import markdown as md
    return wrap_tables(md.markdown(md_text, extensions=["tables", "sane_lists"]))


def render_codebook() -> str:
    """codebook.html — 패널 방법론(문서/코드북_패널.md) + GTA 자료 코드북(문서/코드북.md)."""
    parts = []
    panels = CODEBOOK_PANELS.read_text(encoding="utf-8") if CODEBOOK_PANELS.is_file() else ""
    gta = CODEBOOK_GTA.read_text(encoding="utf-8") if CODEBOOK_GTA.is_file() else ""
    # GTA 코드북의 h1 은 페이지 제목과 겹친다. h2 로 한 단계 내리고 앵커를 단다.
    panels = re.sub(r"^# .*$", "", panels, count=1, flags=re.M)
    gta = re.sub(r"^# .*$", "", gta, count=1, flags=re.M)
    gta = re.sub(r"^### ", "#### ", gta, flags=re.M)
    gta = re.sub(r"^## ", "### ", gta, flags=re.M)
    gta = "## {#gta} GTA 자료 코드북 (master.parquet 열 정의)\n\n" + gta.strip()
    for text in (panels, gta):
        if text.strip():
            parts.append(collapse_h2(md_to_html_plain(text)))
    toc = [("panel1", "패널 1 리스크 지수"), ("scatter", "패널 1 산점도·회귀"), ("composition", "패널 1 블록 구성"),
           ("findings", "패널 1 확인된 사항"), ("panel2", "패널 2 코딩 규칙"), ("gta", "GTA 자료 코드북")]
    toc_html = "".join(f'<li><a href="#{a}" onclick="document.getElementById(\'{a}\').open=true">{html.escape(t)}</a></li>' for a, t in toc)
    body = (f'<header class="hero"><div class="wrap"><span class="eyebrow">Codebook</span><h1>코드북</h1>'
            f'<p>화면의 산식·분류 기준과 GTA 자료의 열 정의. 원문은 저장소 <a href="{REPO_URL}/tree/main/문서">문서/</a>의 코드북_패널.md, 코드북.md.</p></div></header>'
            f'<section class="section"><div class="wrap"><div class="codebook"><ul class="toc">{toc_html}</ul>{"".join(parts)}</div></div></section>')
    return page(f"코드북 · {SITE_TITLE}", body, current="codebook.html")


def collect(logs: Path) -> list[Report]:
    found = []
    for path in sorted(logs.glob(REPORT_GLOB)):
        when = parse_stamp(path.name)
        if when is None:
            print(f"    건너뜀 (이름 형식이 다름): {path.name}")
            continue
        try:
            found.append(Report(path, when))
        except OSError as error:
            print(f"    건너뜀 (읽기 실패): {path.name} — {error}")
    found.sort(key=lambda r: r.when, reverse=True)
    return found


def _force_remove(func, path, error):
    """읽기 전용 속성 때문에 지워지지 않으면 속성을 풀고 다시 시도한다.

    Windows 에서 폴더에 ReadOnly 가 걸리면 os.rmdir 이 Access Denied 로 죽는다.
    2026-08-14에 site/r 이 그렇게 잠겨 사이트 재생성이 통째로 멈췄고, 그 사이
    리포트 HTML 만 지워진 채 배포돼 링크가 404가 됐다. 조용히 넘기지 말고
    속성만 풀어 다시 지운다. 그래도 안 되면 원래 예외를 그대로 올린다.
    """
    import stat
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        raise error




def build(logs: Path = LOGS, out: Path = SITE, quiet: bool = False) -> Path:
    """site/ 를 통째로 다시 만든다. 반환값은 site 경로. 2026-10-22: 패널 2개 체제."""
    reports = collect(logs)
    if out.exists():
        shutil.rmtree(out, onexc=_force_remove)
    (out / "r").mkdir(parents=True)
    (out / ".nojekyll").write_text("", encoding="utf-8")   # GitHub Pages 의 Jekyll 처리 끄기
    shutil.copy2(HERE / "assets" / "site.css", out / "site.css")
    shutil.copy2(HERE / "reference" / "ne_110m_admin_0_countries.geojson", out / "world.geojson")

    (out / "index.html").write_text(render_index(reports), encoding="utf-8")
    (out / "data.html").write_text(render_data(reports), encoding="utf-8")
    (out / "codebook.html").write_text(render_codebook(), encoding="utf-8")
    for report in reports:
        (out / "r" / f"{report.slug}.html").write_text(render_report(report), encoding="utf-8")

    industrial_policy_site.build(out)      # ip_us_cn.json — 패널 1 의 입력
    risk_built = ip_risk_site.build(out)
    ai_built = ai_coop_site.build(out)

    if not quiet:
        size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        print(f"    사이트 생성   리포트 {len(reports)}건, 패널1 {risk_built}, 패널2 {ai_built}, {size / 1024:,.0f}KB")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{SITE_TITLE} 사이트 생성")
    parser.add_argument("--logs", type=Path, default=LOGS)
    parser.add_argument("--out", type=Path, default=SITE)
    parser.add_argument("--open", action="store_true", help="만든 뒤 브라우저로 열기")
    args = parser.parse_args()

    if not args.logs.is_dir():
        print(f"logs 폴더가 없습니다: {args.logs}")
        return 1

    out = build(args.logs, args.out)

    if args.open:
        import webbrowser
        webbrowser.open((out / "index.html").resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
