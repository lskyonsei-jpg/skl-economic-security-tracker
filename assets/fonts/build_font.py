"""Noto Serif KR Black(900) 을 통짜 woff2 한 개로 만들어 assets/fonts/ 에 넣는다.

구글은 한글을 120여 조각으로 쪼개 내려준다. 조각마다 도착 시각이 달라
한 낱말 안에서 글자마다 글꼴이 달라 보이는 문제가 있었다. 조각을 다 받아
하나로 합쳐 버리면 그 문제가 원천적으로 사라진다.
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

import requests
from fontTools.merge import Merger
from fontTools.ttLib import TTFont

ROOT = Path(sys.argv[1])
OUT = ROOT / "assets" / "fonts"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
WEIGHT = 900

url = f"https://fonts.googleapis.com/css2?family=Noto+Serif+KR:wght@{WEIGHT}"
css = requests.get(url, headers={"User-Agent": UA}, timeout=60).text
urls = sorted(set(re.findall(r"url\((https://[^)]+\.woff2)\)", css)))
print(f"조각 {len(urls)}개 내려받는 중")

tmp = Path(tempfile.mkdtemp())
paths = []
for i, u in enumerate(urls):
    r = requests.get(u, headers={"User-Agent": UA}, timeout=60)
    r.raise_for_status()
    p = tmp / f"{i:03d}.woff2"
    p.write_bytes(r.content)
    paths.append(str(p))

print("합치는 중 (1~2분)")
merged = Merger().merge(paths)
merged.flavor = "woff2"

# OneDrive 가 폴더를 붙들고 있어 폴더째 지우면 Access Denied 가 난다.
# 안의 파일만 지운다.
OUT.mkdir(parents=True, exist_ok=True)
for old in list(OUT.glob("*.woff2")) + list(OUT.glob("*.css")):
    old.unlink()
dest = OUT / f"noto-serif-kr-{WEIGHT}.woff2"
merged.save(dest)
shutil.rmtree(tmp, ignore_errors=True)

# unicode-range 를 쓰지 않는다. 한 파일이라 쪼갤 이유가 없다.
(OUT / "noto-serif-kr.css").write_text(
    "@font-face {\n"
    "  font-family: 'Noto Serif KR';\n"
    "  font-style: normal;\n"
    f"  font-weight: {WEIGHT};\n"
    "  font-display: block;\n"
    f"  src: url(fonts/{dest.name}) format('woff2');\n"
    "}\n",
    encoding="utf-8")

print(f"완료: {dest.name}  {dest.stat().st_size/1024/1024:.2f}MB  "
      f"글자 {len(TTFont(dest).getBestCmap()):,}자")
