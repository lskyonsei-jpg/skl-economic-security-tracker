"""SKL Economic Security Tracker — 변경 내역을 정적 웹사이트로 만든다.

logs/change_report_*.md 를 읽어 site/ 아래에 HTML을 쓴다. 비밀값은 다루지
않는다. 배포는 GitHub Actions(.github/workflows/deploy-pages.yml)가 site/ 를
GitHub Pages 로 올린다(2026-10-22, Cloudflare Pages 에서 이전).

  site/
    index.html              전체 목록 (최신순)
    r/<stamp>.html          리포트 하나

markdown 변환은 markdown 라이브러리에 맡긴다. 직접 짜지 않는 이유는 리포트
표 칸이 GTA 원문을 그대로 담기 때문이다. auto_update.py 의 cell() 은 `|` 만
escape 하고 `&`·`<` 는 통과시킨다. 'R&D' 같은 흔한 제목이 그대로 HTML 로
새면 화면이 깨진다.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import bloc_site
import industrial_policy_site
import ip_risk_site
import oil_verify_site
import semiconductor_site
import solar_site

HERE = Path(__file__).resolve().parent
LOGS = HERE / "logs"
SITE = HERE / "site"

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


CSS = """
/* 한글 본문용 명조 (Noto Serif KR Black). 윈도우에 기본 탑재된 한글 명조가
   바탕(Batang)뿐이라 화면용으로 쓰기엔 낡아 보인다.
   폰트 파일은 assets/fonts/ 에 두고 사이트에 같이 올린다 — 바깥으로 요청이
   나가지 않는다. 조각내지 않은 통짜 파일 하나다(1.55MB). */
@import url("fonts.css");

*, *::before, *::after { box-sizing: border-box; }
:root {
  --bg: #fff1e5; --fg: #000000; --muted: #000000; --line: #302824;
  --card: #f7ded2; --accent: #000000; --warn: #8c2f24; --radius: 10px;
  /* 강조용 자주. 크림색 바탕 위에서 검정과 확실히 갈리는 선까지 어둡게 잡았다. */
  --plum: #7b1f52;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #fff1e5; --fg: #000000; --muted: #000000; --line: #302824;
    --card: #f7ded2; --accent: #000000; --warn: #8c2f24; --plum: #7b1f52;
  }
}
html { -webkit-text-size-adjust: 100%; }
/* 라틴 글자는 Times New Roman, 한글은 그 뒤 명조로 떨어진다. 브라우저는
   글자 하나하나마다 앞에서부터 그 글자가 있는 폰트를 고르므로, 이 순서면
   영문·숫자는 TNR, 한글은 Noto Serif KR 로 찍힌다. */
body {
  margin: 0; background: var(--bg); color: var(--fg);
  font-family: "Times New Roman", Times,
               "Noto Serif KR", "본명조", "Nanum Myeongjo", "Batang", serif;
  font-size: 17px; line-height: 1.75; word-break: keep-all; font-weight: 900;
}
/* 강조는 색으로 준다. 굵기는 이미 전부 700 이라 더 줄 것이 없다. */
article strong, article b { color: var(--plum); }
.wrap { max-width: 1040px; margin: 0 auto; padding: 32px 20px 96px; }
a { color: var(--accent); }
header.site { border-bottom: 2px solid var(--line); margin-bottom: 28px; padding-bottom: 18px; }
header.site h1 { font-size: 1.35rem; margin: 0 0 6px; letter-spacing: -0.01em; color: #000; }
header.site p { margin: 0; color: var(--muted); font-size: 0.9rem; }
.back { display: inline-block; margin-bottom: 18px; font-size: 0.9rem; text-decoration: none; }
.back:hover { text-decoration: underline; }

ul.reports { list-style: none; margin: 0; padding: 0; }
ul.reports li { margin-bottom: 12px; }
a.card {
  display: block; padding: 16px 18px; background: var(--card);
  border: 2px solid var(--line); border-radius: var(--radius);
  text-decoration: none; color: inherit;
}
a.card:hover { border-color: var(--accent); }
.card .date { font-weight: 700; font-size: 1.1rem; }
.card .sub { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }
.badges { margin-top: 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.badge {
  font-size: 0.8rem; padding: 2px 9px; border-radius: 999px;
  border: 2px solid var(--line); background: var(--bg); color: var(--muted);
  white-space: nowrap;
}
.badge b { color: var(--plum); }
/* 위쪽 두 개는 리포트가 아니라 별도 화면으로 가는 문이다. 자주색으로 띄운다. */
a.card.nav .date { color: var(--plum); }

article h1 { font-size: 1.5rem; margin: 0 0 20px; letter-spacing: -0.01em; }
article h2 { font-size: 1.15rem; margin: 40px 0 12px; padding-top: 14px;
             border-top: 1px solid var(--line); color: var(--plum); }
article h3 { font-size: 1rem; margin: 26px 0 10px; color: var(--muted); }
article blockquote {
  margin: 18px 0; padding: 12px 16px; border-left: 3px solid var(--warn);
  background: var(--card); border-radius: 0 var(--radius) var(--radius) 0;
  font-size: 0.92rem;
}
article blockquote p { margin: 6px 0; }
article code {
  background: var(--card); border: 1px solid var(--line); border-radius: 4px;
  padding: 1px 5px; font-size: 0.86em;
  font-family: "Cascadia Mono", Consolas, monospace;
}
.tablebox { overflow-x: auto; margin: 14px 0; border: 1px solid var(--line); border-radius: var(--radius); }
/* 표가 든 절은 접어 둔다. summary 가 h2/h3 자리를 그대로 받는다. */
details.sec > summary {
  cursor: pointer; list-style: none; user-select: none;
  display: flex; align-items: baseline; gap: 8px;
}
details.sec > summary::-webkit-details-marker { display: none; }
details.sec > summary::before {
  content: "▾"; font-size: 0.8em; flex: none;
  transform: rotate(-90deg); transition: transform 0.12s;
}
details.sec[open] > summary::before { transform: rotate(0deg); }
details.sec.lv2 > summary {
  font-size: 1.15rem; margin: 40px 0 12px; padding-top: 14px;
  border-top: 1px solid var(--line); color: var(--plum);
}
details.sec.lv3 > summary {
  font-size: 1rem; margin: 26px 0 10px; color: var(--muted);
}
details.sec > summary:hover { color: var(--accent); }
details.sec > .secbody { margin-left: 2px; }
table { border-collapse: collapse; width: 100%; font-size: 0.86rem; }
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: top; }
th { background: var(--card); white-space: nowrap; position: sticky; top: 0; }
tr:last-child td { border-bottom: 0; }
td { word-break: break-word; }

footer.site { margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--line);
              color: var(--muted); font-size: 0.82rem; }
@media (max-width: 560px) {
  .wrap { padding: 20px 14px 64px; }
  table { font-size: 0.8rem; }
}
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
    head = '<a class="back" href="../index.html">← 전체 목록</a>\n<article>\n'
    return page(f"{report.data_date} 변경 내역 · {SITE_TITLE}",
                head + body + "\n</article>", depth=1)


def render_index(reports: list[Report]) -> str:
    built = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = [
        '<header class="site">',
        f"  <h1>{html.escape(SITE_TITLE)}</h1>",
        f"  <p>GTA 변경 내역 · 리포트 {len(reports)}건 · 업데이트 {html.escape(built)}</p>",
        "</header>",
        '<p><a class="card nav" href="semi.html"><span class="date">반도체 공급망 지도</span></a></p>',
        '<p><a class="card nav" href="ip_risk.html"><span class="date">Distortive Industrial Policy Tracker</span></a></p>',
        '<p><a class="card nav" href="bloc.html"><span class="date">석유 산업의 분절화와 재연결</span></a></p>',
        '<p><a class="card nav" href="oil_verify.html"><span class="date">석유 산업의 분절화와 재연결(검증용)</span></a></p>',
        '<p><a class="card nav" href="solar.html"><span class="date">태양광 산업의 분절화와 재연결</span></a></p>',
    ]

    if not reports:
        parts.append("<p>아직 리포트가 없습니다. 업데이트를 한 번 실행하면 여기에 쌓입니다.</p>")
        return page(SITE_TITLE, "\n".join(parts))

    newest = reports[0]
    if newest.rows:
        parts.append(f'<p class="sub" style="color:var(--muted);font-size:0.9rem;">'
                     f"최신 기준일 {html.escape(newest.data_date)} · "
                     f"전체 표본 {html.escape(newest.rows)}</p>")

    parts.append('<ul class="reports">')
    for report in reports:
        badges = "".join(
            f'<span class="badge">{html.escape(label)} <b>{html.escape(value)}</b></span>'
            for label, value in report.counts()
        )
        sub_bits = [report.when.strftime("%Y-%m-%d %H:%M 실행")]
        if report.mode:
            sub_bits.append(report.mode)
        parts.append(
            f'<li><a class="card" href="r/{report.slug}.html">'
            f'<div class="date">{html.escape(report.data_date)}</div>'
            f'<div class="sub">{html.escape(" · ".join(sub_bits))}</div>'
            f'<div class="badges">{badges}</div>'
            f"</a></li>"
        )
    parts.append("</ul>")
    return page(SITE_TITLE, "\n".join(parts))


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


FONT_SRC = HERE / "assets" / "fonts"


def copy_fonts(out: Path) -> int:
    """assets/fonts/ 를 site/ 로 옮긴다.

    폰트를 사이트에 같이 올려야 바깥(구글)으로 요청이 나가지 않는다.
    noto-serif-kr.css 는 site/fonts.css 로, woff2 는 site/fonts/ 로 간다.
    css 안의 경로가 `fonts/....woff2` 라 이 배치라야 맞아 떨어진다.

    폰트는 조각내지 않은 한 파일이다. 구글이 내려주는 한글 웹폰트는 120여
    조각으로 쪼개져 있는데, 조각마다 도착 시각이 달라 한 낱말 안에서 글자마다
    글꼴이 달라 보였다(2026-08-15 "반도체 공급망 지도" — '반'과 '급망'만 굵게).
    조각을 다 받아 하나로 합쳐 버리면 섞일 수가 없다. 만드는 방법은
    README 의 폰트 항목에 적어 두었다.

    폰트가 없어도 사이트는 만든다. 그때는 바탕체로 보일 뿐이다.
    """
    css = FONT_SRC / "noto-serif-kr.css"
    if not css.is_file():
        print("    폰트 없음 — 명조 대신 시스템 기본 글꼴로 보입니다")
        (out / "fonts.css").write_text("/* 폰트 파일 없음 */\n", encoding="utf-8")
        return 0
    (out / "fonts.css").write_text(css.read_text(encoding="utf-8"), encoding="utf-8")
    dest = out / "fonts"
    dest.mkdir(exist_ok=True)
    n = 0
    for woff in FONT_SRC.glob("*.woff2"):
        shutil.copy2(woff, dest / woff.name)
        n += 1
    return n


def build(logs: Path = LOGS, out: Path = SITE, quiet: bool = False) -> Path:
    """site/ 를 통째로 다시 만든다. 반환값은 site 경로."""
    reports = collect(logs)

    # 2026-10-15: 원자료(05_국정원과제/02_원자료 아래 Comtrade·GTA CSV)가 폴더 정리로
    # 없어진 뒤 빌드하면 bloc/solar 빌더가 "없음 — 건너뜀"으로 돌아오고, 그 패널의
    # html/json 은 site/ 를 지웠으니 통째로 사라진다(2026-09-06 빌드가 마지막 정상본).
    # 그래서 site/ 를 지우지 않고 옆으로 치워 두었다가, 건너뛴 빌더의 산출물만
    # 그대로 되돌린다. 원자료가 돌아오면 이 분기는 저절로 안 탄다.
    prev = out.with_name(out.name + "_prev")
    if prev.exists():
        shutil.rmtree(prev, onexc=_force_remove)
    if out.exists():
        out.rename(prev)
    (out / "r").mkdir(parents=True)

    # GitHub Pages 의 Jekyll 처리를 끈다. 없으면 _ 로 시작하는 경로가 조용히 빠진다.
    (out / ".nojekyll").write_text("", encoding="utf-8")

    (out / "style.css").write_text(CSS.strip() + "\n", encoding="utf-8")
    copy_fonts(out)
    (out / "index.html").write_text(render_index(reports), encoding="utf-8")
    for report in reports:
        (out / "r" / f"{report.slug}.html").write_text(
            render_report(report), encoding="utf-8"
        )

    semi_built = semiconductor_site.build(out)
    ip_built = industrial_policy_site.build(out)
    risk_built = ip_risk_site.build(out)
    bloc_built = bloc_site.build(out)
    solar_built = solar_site.build(out)

    for built, names in (
        (semi_built, ("semi.html", "semi.json")),
        (ip_built, ("ip_us_cn.json",)),
        (risk_built, ("ip_risk.html", "ip_risk.json", "ip_sectors.json")),
        (bloc_built, ("bloc.html", "bloc.json", "oil_trade.json")),
        (solar_built, ("solar.html", "solar_trade.json")),
    ):
        if built:
            continue
        for name in names:
            if (prev / name).is_file():
                shutil.copy2(prev / name, out / name)
                print(f"    원자료 없음 → 직전 빌드의 {name} 보존")
    if prev.exists():
        shutil.rmtree(prev, onexc=_force_remove)

    # 검증 패널은 위에서 만들어졌거나 되돌려진 oil_trade.json 만 읽는다.
    verify_built = oil_verify_site.build(out)

    if not quiet:
        size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
        extra = ""
        if semi_built:
            extra += ", 반도체 지도"
        if ip_built:
            extra += ", 미중 산업정책 데이터(리스크 화면용)"
        if risk_built:
            extra += ", 지정학적 산업정책 리스크"
        if bloc_built:
            extra += ", 지정학적 블록 지도"
        if solar_built:
            extra += ", 태양광 무역 탐색기"
        if verify_built:
            extra += ", 석유 검증 보고서"
        print(f"    사이트 생성   리포트 {len(reports)}건{extra}, {size / 1024:,.0f}KB")
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
