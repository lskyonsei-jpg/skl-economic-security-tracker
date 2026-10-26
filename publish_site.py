"""SKL Economic Security Tracker — 변경 내역을 정적 웹사이트로 만든다.

logs/change_report_*.md 를 읽어 site/ 아래에 HTML을 쓴다. 비밀값은 다루지
않는다. 배포는 GitHub Actions(.github/workflows/pipeline.yml)가 site/ 를
GitHub Pages 로 올린다(2026-10-22, Cloudflare Pages 에서 이전).

  site/
    index.html              랜딩(띠 + 패널 2개 + 최근 변경)
    ip_risk.html, ai_coop.html, records.html, review.html, data.html
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


def parse_stamp(name: str) -> datetime | None:
    matched = REPORT_STAMP.match(name)
    if not matched:
        return None
    try:
        return datetime.strptime(matched.group(1) + matched.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None


def meta_of(text: str) -> dict[str, str]:
    head = text.split("##", 1)[0]
    return {k.strip(): v.strip() for k, v in META_LINE.findall(head)}


class Report:
    def __init__(self, path: Path, when: datetime):
        self.path = path
        self.when = when
        self.text = path.read_text(encoding="utf-8")
        self.meta = meta_of(self.text)

    @property
    def slug(self) -> str:
        return self.when.strftime("%Y%m%d_%H%M%S")

    @property
    def data_date(self) -> str:
        return self.meta.get("자료 기준일") or self.when.strftime("%Y-%m-%d")


# ---- 모든 페이지의 틀(내비·히어로·Last update·푸터)은 여기 page() 하나만 만든다 (2026-10-23).
# 패널 모듈(ip_risk_site, ai_coop_site)은 히어로 안쪽과 본문만 돌려주고 틀은 쓰지 않는다. 전에는 Industrial Policy
# 페이지가 손으로 쓴 템플릿에 내비·푸터를 따로 들고 있어서, 다른 페이지에서 지운 Review 메뉴가 그 페이지에만 남았다.
NAV = [("ip_risk.html", "Industrial Policy"), ("ai_coop.html", "AI Cooperation"),
       ("data.html", "Data"), ("codebook.html", "Codebook")]
PANEL2_PAGES = ("ai_coop.html", "records.html", "review.html")   # AI Cooperation 아래 Dashboard · Records · Review 탭
HOME_ICON = ('<svg class="mark" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 11.5 12 4l9 7.5v8a1 1 0 0 1-1 1h-5.5v-6h-5v6H4a1 1 0 0 1-1-1z" '
             'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/></svg>')


def nav(current: str) -> str:
    current = "ai_coop.html" if current in PANEL2_PAGES else current
    cur = ' aria-current="page"'
    items = "".join(f'<a href="{h}"{cur if h == current else ""}>{t}</a>' for h, t in NAV)
    return (f'<nav class="site-nav"><div class="wrap"><a class="brand" href="index.html">{HOME_ICON}{html.escape(SITE_TITLE)}</a>'
            f'<div class="links">{items}</div></div></nav>')


def footer(asof: str, built: str) -> str:
    sha = os.environ.get("GIT_SHA", "")[:7]
    data = f"자료 {html.escape(asof)} · " if asof else ""
    return (f'<footer class="site-footer"><div class="wrap"><span>{html.escape(SITE_TITLE)} · 연구용 자료</span>'
            f'<span class="build">{data}빌드 {html.escape(built)}{(" · " + sha) if sha else ""}</span></div></footer>')


def page(title: str, hero: str, body: str, *, current: str = "", asof: str | None = None,
         head: str = "", depth: int = 0) -> str:
    """hero 는 민트 띠 안쪽(eyebrow·h1 등). 비우면 띠와 Last update 를 넣지 않는다(변경 리포트).
    asof 는 푸터의 자료 기준일. 주지 않으면 GTA 자료 기준일(state.json)."""
    now = datetime.now()
    up = "../" * depth
    chrome_nav = nav(current)
    foot = footer(STATE.get("data_end_date", "—") if asof is None else asof, now.strftime("%Y-%m-%d %H:%M"))
    if depth:
        chrome_nav = chrome_nav.replace('href="', f'href="{up}')
        foot = foot.replace('href="', f'href="{up}')
    if hero:   # Last update = 사이트를 마지막으로 만든 날 (자료 기준일은 푸터)
        hero = (f'<header class="hero"><div class="wrap">{hero}</div></header>\n'
                f'<div class="wrap last-update">Last update {now:%Y-%m-%d}</div>\n')
    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<link rel="stylesheet" href="{up}site.css">{head}
</head>
<body>
{chrome_nav}
{hero}{body}
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
    return page(f"{report.data_date} 변경 내역 · {SITE_TITLE}", "",
                head + body + "\n</article></main>", depth=1, current="index.html")


# 랜딩 "Recent changes" 이정표. 연구자가 정한 세 줄만 쓴다(2026-10-22). 변경 리포트 목록은 넣지 않는다.
MILESTONES = [
    ("2026-08-18", "최초 구축"),
    ("2026-10-22", "사이트 이전 (GitHub Pages)"),
    ("2026-10-22", "[패널 추가] 한미 AI 협력 트래커"),
]


def render_index() -> str:
    hero = f'<span class="eyebrow">Research Dashboard</span><h1>{html.escape(SITE_TITLE)}</h1>'
    pending = ai_coop_site.pending_proposals()
    banner = ""
    if pending:
        by = {k: sum(1 for p in pending if p["task"] == k) for k in "ABC"}
        banner = (f'<section class="section" style="padding:20px 0"><div class="wrap"><a class="panel-card muted" href="review.html" style="min-height:0;padding:18px 24px">'
                  f'<span class="eyebrow" style="margin-bottom:6px">판단 대기</span><h2 style="margin:0"><span class="alert-dot" aria-hidden="true">⚠</span>제안 {len(pending)}건 — 새 사건 {by["A"]} · 갱신 {by["B"]} · 재검토 {by["C"]}</h2>'
                  f'<span class="go">열기 →</span></a></div></section>')
    cards = ('<section class="section"><div class="wrap"><span class="eyebrow">Panels</span><div class="grid grid-2">'
             '<a class="panel-card" href="ip_risk.html"><span class="eyebrow">Panel 1</span><h2>Distortive Industrial Policy Tracker</h2>'
             '<span class="go">열기 →</span></a>'
             '<a class="panel-card" href="ai_coop.html"><span class="eyebrow">Panel 2</span><h2>한미 AI 협력 트래커</h2>'
             '<span class="go">열기 →</span></a></div></div></section>')
    items = "".join(f'<li><span class="d">{html.escape(d)}</span><span>{html.escape(t)}</span></li>' for d, t in MILESTONES)
    changes = ('<section class="section"><div class="wrap"><span class="eyebrow">Recent changes</span>'
               f'<div class="panel"><div class="panel-body"><ul class="changes">{items}</ul></div></div></div></section>')
    return page(SITE_TITLE, hero, banner + cards + changes, current="index.html")


# 파이프라인이 실제로 호출하는 외부 API. 코드의 상수와 같이 바뀌어야 한다.
#   (이름, 끝점, 용도, 주기, 키, 코드 위치)
#   (패널, 이름, 끝점, 무엇을 하나, 주기, 키, 코드 위치)
APIS = [
    ("패널 1", "Global Trade Alert API v2", "api.globaltradealert.org/api/v2/gta/data/", "각국 정부의 무역·산업 개입 조치(intervention) 전량을 매일 받아 온다. 패널 1의 원자료.", "매일", "GTA_API_KEY", "auto_update.py"),
    ("패널 1", "Hugging Face Hub", "industrialpolicygroup/industrialpolicy-classifier", "GTA 조치 설명문을 읽고 산업정책인지 가려내는 BERT 모델을 내려받는다(버전 고정). 새로 들어온 조치만 분류한다.", "매일", "없음", "auto_update.py"),
    ("패널 1", "Harvard Dataverse", "dataverse.harvard.edu · doi:10.7910/DVN/LEJUQZ", "UN 총회 표결로 추정한 각국의 외교적 위치(BSV ideal point). 지정학적 거리와 블록 분류의 기준.", "매월 4일", "없음", "collect_reference.py"),
    ("패널 1", "IMF Data SDMX 2.1", "api.imf.org/external/sdmx/2.1 · IMF.STA,IMTS", "미국·중국과 각국 사이의 상품무역액(DOTS). 산점도의 원 크기와 표본 절단에 쓴다.", "매월 4일", "없음", "collect_reference.py"),
    ("패널 1", "World Bank API v2", "api.worldbank.org/v2 · NY.GDP.MKTP.CD", "각국 명목 GDP(WDI). 산점도 원 크기의 대안 지표.", "매월 4일", "없음", "collect_reference.py"),
    ("패널 2", "Google News RSS · Bing News", "news.google.com/rss/search · bing.com/news/search", "한미 AI 협력 관련 최근 2일 기사를 찾는다. 새 사건 후보의 출발점.", "매일", "없음", "ai_coop_tasks.py"),
    ("패널 2", "Internet Archive Wayback", "archive.org/wayback/available", "유료벽에 막힌 기사의 보관본을 대신 가져온다.", "필요 시", "없음", "collect_ai_coop.py"),
    ("패널 2", "Anthropic API", "claude-opus-5-5 (effort medium)", "기사를 읽고 사건을 코딩(형태·주체·분야·금액)하고, 기존 사건의 후속·재검토를 제안한다. 반영은 연구자 승인 뒤에만.", "매일", "ANTHROPIC_API_KEY", "collect_ai_coop.py · ai_coop_tasks.py"),
    ("패널 2", "GitHub REST API", "api.github.com/repos/…/issues", "판단 대기 페이지에서 제출한 승인·기각·보류(Issue)를 읽어 반영하고 Issue를 닫는다.", "매일", "GITHUB_TOKEN (Actions 기본)", "ai_coop_tasks.py"),
    ("공통", "GitHub Release “state”", "gh release download/upload", "GTA 스냅숏·BERT 예측 캐시·기준자료·사건 파일을 보관한다. 매 실행의 시작점이자 결과 저장소.", "매 실행", "GITHUB_TOKEN (Actions 기본)", "pipeline.yml"),
    ("공통", "Gmail SMTP", "smtp.gmail.com:465", "매일 실행 결과와 실패를 메일로 보낸다.", "매일", "MAIL_USER · MAIL_PASS", "pipeline.yml"),
]


def render_data(reports: list[Report]) -> str:
    repo = REPO_URL
    files = [("ip_risk.json", "패널 1 — 국가·연도별 BSV ideal point·블록·무역비중·GDP, 블록 구성"), ("ip_sectors.json", "패널 1 — 조치 단위 원자료(산점도·회귀)"),
             ("ai_coop.json", "패널 2 — 사건 목록·집계·기관 목록"), ("ai_coop_events.xlsx", "패널 2 — 사건 레코드 전체(변수 그대로, Excel)")]
    rows = "".join(f'<tr><td><a href="{f}" download>{f}</a></td><td>{html.escape(d)}</td></tr>' for f, d in files)
    api_rows = "".join(
        f'<tr><td>{html.escape(panel)}</td><td>{html.escape(n)}<span class="small">{html.escape(ep)}</span><span class="small">{html.escape(where)}</span></td>'
        f'<td>{html.escape(use)}</td><td>{html.escape(when)}</td><td>{html.escape(key)}</td></tr>'
        for panel, n, ep, use, when, key, where in APIS)
    body = (f'<section class="section"><div class="wrap grid grid-2"><div class="panel"><div class="panel-head">사이트 자료 파일</div>'
            f'<div class="panel-body"><table><tbody>{rows}</tbody></table></div></div>'
            f'<div class="panel"><div class="panel-head">저장소</div><div class="panel-body"><p><a href="{repo}">github.com/lskyonsei-jpg/skl-economic-security-tracker</a></p>'
            f'<p><a href="{repo}/releases/tag/state">Release “state”</a> — master.parquet(GTA 전량 + BERT 라벨), prediction_cache.json, state.json, 변경 리포트, 기준자료, AI 협력 사건 파일</p>'
            f'<p><a href="{repo}/actions">Actions</a> — 매일 06:00 KST 갱신·배포 기록</p>'
            f'<p><a href="codebook.html" class="btn">Codebook</a></p></div></div></div></section>'
            f'<section class="section"><div class="wrap"><span class="eyebrow" style="text-transform:none">APIs</span><div class="panel"><div class="panel-head" style="text-transform:none">연결된 APIs</div>'
            f'<div class="tablebox" style="border:0;margin:0"><table class="api-table"><thead><tr><th style="width:11%">패널</th><th style="width:34%">API · 코드</th><th>무엇을 하나</th><th style="width:11%">주기</th><th style="width:15%">키</th></tr></thead><tbody>{api_rows}</tbody></table></div>'
            f'<div class="panel-body"><p class="note">키는 GitHub Secrets에만 있습니다. 코드에 담지 않습니다.</p></div></div></div></section>')
    items = "".join(f'<li><span class="d">{html.escape(r.data_date)}</span><a href="r/{r.slug}.html">{html.escape(r.meta.get("실행 모드") or "변경 내역")} →</a></li>' for r in reports)
    body += (f'<section class="section"><div class="wrap"><span class="eyebrow">GTA 변경 리포트</span><div class="panel"><div class="panel-body">'
             f'<ul class="changes">{items or "<li>없음</li>"}</ul></div></div></div></section>')
    return page(f"자료 · {SITE_TITLE}", '<span class="eyebrow">Data</span><h1>자료의 출처</h1>', body, current="data.html")


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
    body = (f'<section class="section"><div class="wrap"><div class="codebook">{"".join(parts)}</div></div></section>')
    return page(f"코드북 · {SITE_TITLE}", '<span class="eyebrow">Codebook</span><h1>코드북</h1>', body, current="codebook.html")


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

    (out / "index.html").write_text(render_index(), encoding="utf-8")
    (out / "data.html").write_text(render_data(reports), encoding="utf-8")
    (out / "codebook.html").write_text(render_codebook(), encoding="utf-8")
    for report in reports:
        (out / "r" / f"{report.slug}.html").write_text(render_report(report), encoding="utf-8")

    # 패널 모듈은 자기 JSON 을 쓰고 페이지 사양(file + page() 인자)을 돌려준다. 틀은 여기서 한 번에 씌운다.
    panel1 = ip_risk_site.build(out, STATE.get("data_end_date", "—"))
    panel2 = ai_coop_site.build(out)
    for spec in panel1 + panel2:
        spec = dict(spec)
        (out / spec.pop("file")).write_text(page(**spec), encoding="utf-8")

    if not quiet:
        size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        print(f"    사이트 생성   리포트 {len(reports)}건, 패널1 {bool(panel1)}, 패널2 {bool(panel2)}, {size / 1024:,.0f}KB")
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
