"""태양광 셀·모듈(HS 854140/854142/854143) 무역 탐색기 — bloc_site.py의
'원유·석유제품 무역 탐색기' 패널을 그대로 본떠 독립 페이지로 만든다
(2026-08-30).

오일 패널과 다른 점 — 품목 토글이 없다. HS 코드가 2022년 개정으로
854140(통합) -> 854142(셀)·854143(모듈)로 갈렸는데, 사용자 확인 결과
(2026-08-30) 셀/모듈을 나눠 보여주지 않고 (보고국,상대국,기간,흐름) 기준
합산 값 하나만 쓰기로 했다 — 그래서 solar_trade.json의 각 행은 오일의
6칸([rep, par, period, cmd, flow, value])이 아니라 cmd 없는 5칸
([rep, par, period, flow, value])이고, 이 파일의 JS도 cmd 관련 로직을
전부 걷어냈다.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def esc(s: str) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


HTML = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>태양광 산업의 분절화와 재연결 · SKL</title>
<link rel="stylesheet" href="style.css"><style>
.legend{display:flex;flex-wrap:wrap;gap:12px;padding:10px 4px;font-size:.8rem;color:var(--muted)}
.dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:middle}
.legend-meta{flex-basis:100%;margin:2px 0 0;padding-left:1.1em;font-size:.74rem;opacity:.85}
.legend-meta li{margin:1px 0}
.panel-head{padding:10px 2px;font-size:.9rem;color:var(--muted)}
.note{margin:10px 0 20px;padding:10px 14px;border:2px dashed var(--line);border-radius:10px;font-size:.82rem;color:var(--muted)}
.toggle-group{display:flex;border:2px solid var(--line);border-radius:8px;overflow:hidden}
.toggle-btn{padding:6px 14px;font-size:.8rem;background:var(--card);color:var(--fg);border:none;cursor:pointer;font-family:inherit}
.toggle-btn.active{background:var(--plum);color:#fff}
.toggle-btn.disabled{opacity:.35;cursor:not-allowed}
.oil-controls{display:flex;flex-wrap:wrap;gap:14px;margin:14px 0;align-items:flex-end}
.oil-field{display:flex;flex-direction:column;gap:4px}
.oil-field label{font-size:.76rem;color:var(--muted)}
.oil-field input[type=text]{padding:6px 10px;font-size:.85rem;font-family:inherit;background:var(--card);color:var(--fg);border:2px solid var(--line);border-radius:8px;min-width:200px}
.oil-swap{align-self:flex-end;padding:6px 12px;font-size:.8rem;border:2px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);cursor:pointer;font-family:inherit}
.oil-chart-wrap{padding:8px;overflow:auto;background:var(--bg);border:2px solid var(--line);border-radius:12px}
.oil-chart-wrap svg{display:block;min-width:640px}
#solar-chart-fullscreen-root:fullscreen,#solar-chart-fullscreen-root:-webkit-full-screen{display:flex;flex-direction:column;width:100vw;height:100vh;padding:16px;box-sizing:border-box;background:var(--bg)}
#solar-chart-fullscreen-root:fullscreen .oil-chart-wrap,#solar-chart-fullscreen-root:-webkit-full-screen .oil-chart-wrap{flex:1 1 auto;min-height:0}
.oil-chart-toolbar{display:flex;flex-wrap:wrap;gap:6px;margin:6px 0;align-items:center}
.oil-chart-toolbar .toggle-btn{border:2px solid var(--line);border-radius:8px;min-width:34px}
.oil-zoom-label{font-size:.78rem;color:var(--muted);min-width:42px;text-align:center}
.oil-summary{font-size:.82rem;color:var(--muted);margin:8px 2px}
.oil-loading{padding:20px;text-align:center;color:var(--muted);font-size:.85rem}
.oil-mini-row{display:flex;align-items:center;gap:6px;margin-bottom:4px}
.oil-mini-label{font-size:.72rem;color:var(--muted)}
.oil-mini-toggle .toggle-btn{padding:3px 9px;font-size:.72rem}
.check-legend{display:flex;flex-wrap:wrap;gap:2px 12px;padding:10px 4px;font-size:.8rem;color:var(--muted)}
.check-item{display:inline-flex;align-items:center;gap:5px;cursor:pointer;padding:2px 0}
.check-item input{margin:0;cursor:pointer}
.country-list{margin:0 0 20px;border:2px solid var(--line);border-radius:10px;padding:10px 14px;background:var(--card)}
.country-list summary{cursor:pointer;font-size:.86rem;color:var(--muted)}
.country-cols{display:flex;flex-wrap:wrap;gap:20px;margin-top:12px}
.country-col{flex:1 1 220px;min-width:200px;max-height:360px;overflow-y:auto}
.country-col h4{margin:0 0 6px;font-size:.86rem}
.country-col ul{margin:0;padding-left:18px;font-size:.78rem;color:var(--fg)}
.country-col li{margin:2px 0}
.seg-val{color:var(--muted);font-size:.72rem}
</style></head><body><div class="wrap">
<a class="back" href="index.html">← 변경 내역</a>
<header class="semi-head" style="display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:18px">
<div><h1 style="margin:0;font-size:1.45rem">태양광 산업의 분절화와 재연결</h1>
<p style="margin:4px 0 0;color:var(--muted);font-size:.86rem">UN Comtrade 기준 · 태양광 셀·모듈 세계 무역, 2010~2026</p></div>
</header>
__COUNTRY_LIST__
<p class="note">HS 코드가 2022년 개정으로 바뀌었다 — 2010~2021년은 854140(셀·모듈 통합), 2022년부터는
854142(비조립 셀)·854143(모듈/패널)로 분리됐다. 이 화면은 셀·모듈을 따로 보여주지 않고
(보고국·상대국·기간·흐름) 기준으로 두 시기 코드를 합산한 '태양광 전체' 시계열 하나만 쓴다.</p>
<div class="oil-panel">
<div class="panel-head">태양광 셀·모듈 무역 탐색기 — 2010~2026</div>
<div class="legend"><ul class="legend-meta">
<li>출처: UN Comtrade, __ROW_COUNT__행 (보고국·상대국·기간·흐름, breakdownMode=classic)</li>
<li>품목: HS 854140(2010~2021) + HS 854142·854143(2022~) 합산</li>
<li>기간: 2010~2025 연간 + 2026년 1~6월(상반기만, 하반기 미게시)</li>
<li>주의: 막대 2개=수출국/수입국 각자 신고(미러 통계) — 한쪽만 있고 0이면 자체 미신고</li>
</ul></div>
<div class="oil-controls">
<div class="oil-field">
<label for="solar-exporter">수출국(또는 클럽)</label>
<div class="oil-mini-row"><span class="oil-mini-label">단위</span><div class="toggle-group oil-mini-toggle" id="solar-exporter-mode">
<button type="button" class="toggle-btn active" data-mode="country">국가</button>
<button type="button" class="toggle-btn" data-mode="bloc">클럽</button>
</div></div>
<input type="text" id="solar-exporter" list="solar-exporter-list" autocomplete="off">
<datalist id="solar-exporter-list"></datalist>
</div>
<button type="button" class="oil-swap" id="solar-swap" title="수출국·수입국 맞바꾸기">⇄</button>
<div class="oil-field">
<label for="solar-importer">수입국(또는 클럽)</label>
<div class="oil-mini-row"><span class="oil-mini-label">단위</span><div class="toggle-group oil-mini-toggle" id="solar-importer-mode">
<button type="button" class="toggle-btn active" data-mode="country">국가</button>
<button type="button" class="toggle-btn" data-mode="bloc">클럽</button>
</div></div>
<input type="text" id="solar-importer" list="solar-importer-list" autocomplete="off">
<datalist id="solar-importer-list"></datalist>
</div>
<div class="oil-field"><label>보기</label><div class="toggle-group" id="solar-view-toggle">
<button type="button" class="toggle-btn active" data-view="absolute">절대비교</button>
<button type="button" class="toggle-btn" data-view="share">구성비율</button>
</div></div>
<div class="oil-field"><label>유럽</label><div class="toggle-group" id="solar-eu-toggle">
<button type="button" class="toggle-btn active" data-eu="separate">국가별로 보기</button>
<button type="button" class="toggle-btn" data-eu="combined">EU로 보기</button>
</div></div>
<div class="oil-field"><label>통계 기준</label><div class="toggle-group" id="solar-basis-toggle">
<button type="button" class="toggle-btn active" data-basis="export">수출국 신고</button>
<button type="button" class="toggle-btn" data-basis="import">수입국 신고</button>
</div></div>
</div>
<div class="oil-summary" id="solar-summary">데이터 불러오는 중…</div>
<div class="legend" id="solar-rank-legend" style="display:none"></div>
<div id="solar-chart-fullscreen-root">
<div class="oil-chart-toolbar">
<button type="button" class="toggle-btn" id="solar-zoom-out" title="축소">－</button>
<span class="oil-zoom-label" id="solar-zoom-label">100%</span>
<button type="button" class="toggle-btn" id="solar-zoom-in" title="확대">＋</button>
<button type="button" class="toggle-btn" id="solar-zoom-reset" title="확대·축소 초기화">초기화</button>
<button type="button" class="toggle-btn" id="solar-fullscreen" title="전체화면">⛶ 전체화면</button>
<button type="button" class="toggle-btn" id="solar-save-jpg" title="지금 보고 있는 차트를 JPG 그림파일로 저장">⤓ JPG 저장</button>
</div>
<div class="oil-chart-wrap" id="solar-chart-wrap"><div class="oil-loading" id="solar-chart">데이터 불러오는 중…</div></div>
</div>
</div>
</div>
<script>
(function(){
  const CLUB_LABEL = {US:'미국 클럽', CN:'중국 클럽', NON:'비동맹'};
  const CLUB_COLOR = {US:'#1a5fb4', CN:'#c62828', NON:'#8a8a86', UNK:'#3a3a38'};
  // 클럽별 구성 보기에서만 쓴다 — UNK(이념점 없음)는 exp/imp 선택지에는 없지만
  // countries[iso3].club 값으로는 나올 수 있어(build_solar_data.py), 묶어서 보여준다.
  const CLUB_FULL_LABEL = Object.assign({UNK: '이념점 없음'}, CLUB_LABEL);
  const EU_LABEL = 'EU(27개국)';
  // 국가별 구성 보기에서 EU 27개 회원국을 하나로 묶어볼 때 쓰는 집합 — UN
  // Comtrade가 이 품목에서 EU를 보고국/상대국으로 직접 신고하지 않아
  // (raw 데이터에 reporterCode/partnerCode 97 행이 0건), 회원국 각자의
  // 신고를 합산하는 방식으로만 EU 단위를 만들 수 있다.
  const EU27_ISO3 = new Set(['AUT','BEL','BGR','HRV','CYP','CZE','DNK','EST','FIN','FRA',
    'DEU','GRC','HUN','IRL','ITA','LVA','LTU','LUX','MLT','NLD','POL','PRT','ROU','SVK',
    'SVN','ESP','SWE']);
  const X_COLOR = '#2f6f9f';   // 수출국 신고
  const M_COLOR = '#c9822f';   // 수입국 신고
  const PRODUCT = '태양광';
  const HS_NOTE = 'HS 854140(2010~2021) + 854142·854143(2022~) 합산';
  const YEARS = Array.from({length:16}, (_,i) => String(2010+i)).concat(['2026']);

  // 앞뒤로 이어지는 0(데이터 없음) 연도만 잘라낸다 — 중간에 낀 0은 유지한다.
  function trimYears(years, hasValue){
    let start = 0, end = years.length - 1;
    while (start <= end && !hasValue(years[start])) start++;
    while (end >= start && !hasValue(years[end])) end--;
    return start <= end ? years.slice(start, end + 1) : years;
  }

  fetch('solar_trade.json').then(r => r.json()).then(init).catch(err => {
    document.getElementById('solar-chart').textContent = '데이터 로드 실패: ' + err;
  });

  function init(data){
    const rows = data.rows;         // [reporterISO3, partnerISO3, period, flow, value]
    const countries = data.countries; // {iso3: {name, club}}
    document.getElementById('solar-summary').textContent = '';

    const fsRoot = document.getElementById('solar-chart-fullscreen-root');
    let zoom = 1;
    const ZOOM_MIN = 0.5, ZOOM_MAX = 3, ZOOM_STEP = 0.25;
    function applyZoom(){
      const svg = document.querySelector('#solar-chart svg');
      if (!svg) return;
      const isFs = document.fullscreenElement === fsRoot;
      if (isFs && zoom === 1) {
        // 전체화면 + 기본 배율: 세로 공간까지 채운다 (SVG 원본 비율 유지, 레터박스).
        svg.style.width = '100%';
        svg.style.height = '100%';
        svg.style.maxWidth = 'none';
      } else {
        svg.style.width = (zoom * 100) + '%';
        svg.style.height = 'auto';
        svg.style.maxWidth = 'none';
      }
      document.getElementById('solar-zoom-label').textContent = Math.round(zoom * 100) + '%';
    }
    document.getElementById('solar-zoom-in').addEventListener('click', () => {
      zoom = Math.min(ZOOM_MAX, +(zoom + ZOOM_STEP).toFixed(2)); applyZoom();
    });
    document.getElementById('solar-zoom-out').addEventListener('click', () => {
      zoom = Math.max(ZOOM_MIN, +(zoom - ZOOM_STEP).toFixed(2)); applyZoom();
    });
    document.getElementById('solar-zoom-reset').addEventListener('click', () => {
      zoom = 1; applyZoom();
    });
    document.getElementById('solar-fullscreen').addEventListener('click', () => {
      if (!document.fullscreenElement) {
        (fsRoot.requestFullscreen || fsRoot.webkitRequestFullscreen || function(){}).call(fsRoot);
      } else {
        (document.exitFullscreen || document.webkitExitFullscreen || function(){}).call(document);
      }
    });

    // ── 차트를 JPG 그림파일로 저장 ─────────────────────────────────────
    // 화면의 SVG를 그대로 캔버스에 구워 낸다. 두 군데를 손봐야 그림이
    // 화면과 같아진다. (1) SVG 안의 색이 var(--fg) 같은 CSS 변수로
    // 적혀 있는데 <img>로 띄우는 순간 페이지의 :root와 끊겨 변수가 풀리지
    // 않는다 — 직렬화한 문자열에서 미리 계산값으로 바꿔치기한다.
    // (2) 한글 글꼴도 같은 이유로 페이지 것을 못 쓰므로 woff2를 data URL로
    // 박아 넣는다(가져오기 실패하면 시스템 명조로 떨어진다).
    let jpgFontCssPromise = null;
    function jpgEmbeddedFontCss(){
      if (!jpgFontCssPromise) {
        jpgFontCssPromise = fetch('fonts/noto-serif-kr-900.woff2')
          .then(r => { if (!r.ok) throw new Error(r.status); return r.blob(); })
          .then(b => new Promise((res, rej) => {
            const fr = new FileReader();
            fr.onload = () => res(fr.result); fr.onerror = rej; fr.readAsDataURL(b);
          }))
          .then(u => {
            // <img>로 띄운 SVG는 이 문서와 글꼴을 나눠 쓰지 못한다. 데이터를
            // 박아 넣어도 처음 한 번은 글꼴이 붙기 전에 그려져 한글만 통째로
            // 빠지는 일이 있어, 같은 바이트를 이 문서에도 미리 올려
            // 브라우저 글꼴 캐시를 덥혀 둔다.
            let prime = Promise.resolve();
            try {
              const ff = new FontFace('Noto Serif KR', 'url(' + u + ')', {weight: '900', style: 'normal'});
              prime = ff.load().then(f => { document.fonts.add(f); }).catch(() => {});
            } catch (e) { /* FontFace 미지원 브라우저 — 그냥 넘어간다 */ }
            return prime.then(() => "@font-face{font-family:'Noto Serif KR';font-style:normal;font-weight:900;src:url(" + u + ") format('woff2')}");
          })
          .catch(() => '');
      }
      return jpgFontCssPromise;
    }
    // 파일 이름은 차트 맨 위 제목 글자를 그대로 쓴다 — 따로 이름을 물어보지 않는다.
    function jpgFileName(svg){
      const t = svg.querySelector('text');
      const base = ((t && t.textContent) || '차트')
        .replace(/[\/:*?"<>|]/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 80) || '차트';
      const d = new Date(), pad = n => String(n).padStart(2, '0');
      return '' + d.getFullYear() + pad(d.getMonth() + 1) + pad(d.getDate()) + '_' + base + '.jpg';
    }
    function saveChartJpg(){
      const svg = document.querySelector('#solar-chart svg');
      const btn = document.getElementById('solar-save-jpg');
      if (!svg) { alert('아직 그려진 차트가 없다.'); return; }
      const prevText = btn.textContent;
      btn.disabled = true; btn.textContent = '저장 중…';
      const done = () => { btn.disabled = false; btn.textContent = prevText; };
      const cs = getComputedStyle(document.documentElement);
      const vb = svg.viewBox.baseVal;
      const w = Math.round((vb && vb.width) || svg.clientWidth || 1000);
      const h = Math.round((vb && vb.height) || svg.clientHeight || 600);
      const SCALE = 2;   // 문서에 붙여 넣어도 글자가 뭉개지지 않게 2배로 굽는다
      jpgEmbeddedFontCss().then(fontCss => {
        const clone = svg.cloneNode(true);
        clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        clone.setAttribute('width', w);
        clone.setAttribute('height', h);
        clone.removeAttribute('style');   // 확대·축소로 박아둔 인라인 크기는 뺀다
        const st = document.createElementNS('http://www.w3.org/2000/svg', 'style');
        st.textContent = fontCss +
          'svg{font-family:"Times New Roman",Times,"Noto Serif KR","본명조","Batang",serif;font-weight:900}';
        clone.insertBefore(st, clone.firstChild);
        const markup = new XMLSerializer().serializeToString(clone)
          .replace(/var\(\s*(--[\w-]+)\s*\)/g, (m, name) => cs.getPropertyValue(name).trim() || '#000');
        const svgUrl = URL.createObjectURL(new Blob([markup], {type: 'image/svg+xml;charset=utf-8'}));
        const img = new Image();
        img.onload = () => {
          const cv = document.createElement('canvas');
          cv.width = w * SCALE; cv.height = h * SCALE;
          const ctx = cv.getContext('2d');
          const paint = () => {
            ctx.fillStyle = cs.getPropertyValue('--bg').trim() || '#ffffff';   // JPG는 투명을 못 담는다
            ctx.fillRect(0, 0, cv.width, cv.height);
            ctx.drawImage(img, 0, 0, cv.width, cv.height);
          };
          paint();
          // 글꼴이 한 박자 늦게 붙는 경우가 있어 잠깐 뒤에 한 번 더 굽는다.
          setTimeout(() => {
          paint();
          URL.revokeObjectURL(svgUrl);
          cv.toBlob(blob => {
            if (!blob) { alert('JPG로 바꾸지 못했다.'); done(); return; }
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = jpgFileName(svg);
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(() => URL.revokeObjectURL(a.href), 1000);
            done();
          }, 'image/jpeg', 0.95);
          }, 150);
        };
        img.onerror = () => { URL.revokeObjectURL(svgUrl); alert('차트 그림을 만들지 못했다.'); done(); };
        img.src = svgUrl;
      });
    }
    document.getElementById('solar-save-jpg').addEventListener('click', saveChartJpg);
    // flex%만 믿으면 브라우저에 따라 wrap이 콘텐츠 높이로만 잡혀 아래가 비므로,
    // 전체화면일 때 남는 세로 공간을 직접 재서 wrap 높이를 px로 박아넣는다.
    const chartWrapEl = document.getElementById('solar-chart-wrap');
    const chartToolbarEl = document.querySelector('.oil-chart-toolbar');
    function syncFullscreenHeight(){
      if (document.fullscreenElement === fsRoot) {
        const rootStyle = getComputedStyle(fsRoot);
        const padV = (parseFloat(rootStyle.paddingTop) || 0) + (parseFloat(rootStyle.paddingBottom) || 0);
        const toolbarH = chartToolbarEl.getBoundingClientRect().height;
        const toolbarMarginB = parseFloat(getComputedStyle(chartToolbarEl).marginBottom) || 0;
        const avail = window.innerHeight - padV - toolbarH - toolbarMarginB;
        chartWrapEl.style.height = Math.max(200, avail) + 'px';
      } else {
        chartWrapEl.style.height = '';
      }
    }
    document.addEventListener('fullscreenchange', () => {
      document.getElementById('solar-fullscreen').textContent = document.fullscreenElement ? '⛶ 전체화면 종료' : '⛶ 전체화면';
      syncFullscreenHeight();
      applyZoom();
    });
    window.addEventListener('resize', () => { if (document.fullscreenElement === fsRoot) { syncFullscreenHeight(); applyZoom(); } });

    // 마우스 드래그로 상하좌우 이동 (grab & pan)
    (function(){
      let dragging = false, startX = 0, startY = 0, startLeft = 0, startTop = 0;
      chartWrapEl.style.cursor = 'grab';
      chartWrapEl.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        dragging = true;
        startX = e.clientX; startY = e.clientY;
        startLeft = chartWrapEl.scrollLeft; startTop = chartWrapEl.scrollTop;
        chartWrapEl.style.cursor = 'grabbing';
        e.preventDefault();
      });
      window.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        chartWrapEl.scrollLeft = startLeft - (e.clientX - startX);
        chartWrapEl.scrollTop = startTop - (e.clientY - startY);
      });
      window.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        chartWrapEl.style.cursor = 'grab';
      });
    })();

    const names = Object.entries(countries).sort((a,b) => a[1].name.localeCompare(b[1].name));

    const nameToIso3 = {};
    names.forEach(([iso3, info]) => { nameToIso3[info.name] = iso3; });
    const clubNameToCode = {};
    Object.entries(CLUB_LABEL).forEach(([code, lbl]) => { clubNameToCode[lbl] = code; });

    function optionsFor(mode){
      const base = mode === 'bloc' ? ['US','CN','NON'].map(c => CLUB_LABEL[c]) : [EU_LABEL, ...names.map(([,info]) => info.name)];
      return ['전체', ...base];
    }
    function resolveFor(mode, text){
      if (text === '전체') return 'ALL';
      if (text === EU_LABEL) return 'EU';
      return mode === 'bloc' ? (clubNameToCode[text] || null) : (nameToIso3[text] || null);
    }

    const DEFAULT_BY_MODE = {
      exporter: {country: 'CHN', bloc: 'CN'},
      importer: {country: 'USA', bloc: 'US'},
    };

    function bindCombo(input, listEl, toggleId, which){
      const state = {mode: 'country', value: null};
      function fillDatalist(){
        listEl.innerHTML = optionsFor(state.mode).map(n => `<option value="${n}">`).join('');
      }
      function setValue(code, silent){
        state.value = code;
        input.value = label(code);
        if (!silent) render();
      }
      function setMode(m, val){
        state.mode = m;
        document.querySelectorAll(`#${toggleId} .toggle-btn`).forEach(b => b.classList.toggle('active', b.dataset.mode === m));
        fillDatalist();
        setValue(val !== undefined ? val : DEFAULT_BY_MODE[which][m], true);
      }
      input.addEventListener('focus', () => { input.dataset.prev = input.value; input.value = ''; });
      input.addEventListener('input', () => {
        const code = resolveFor(state.mode, input.value.trim());
        if (code) { setValue(code); input.blur(); }
      });
      input.addEventListener('blur', () => {
        if (!resolveFor(state.mode, input.value.trim())) input.value = input.dataset.prev || label(state.value);
      });
      document.querySelectorAll(`#${toggleId} .toggle-btn`).forEach(btn => {
        btn.addEventListener('click', () => { setMode(btn.dataset.mode); render(); });
      });
      state.setMode = setMode;
      setMode('country', DEFAULT_BY_MODE[which].country);
      return state;
    }
    const expSel = bindCombo(document.getElementById('solar-exporter'), document.getElementById('solar-exporter-list'), 'solar-exporter-mode', 'exporter');
    const impSel = bindCombo(document.getElementById('solar-importer'), document.getElementById('solar-importer-list'), 'solar-importer-mode', 'importer');

    let view = 'absolute';
    document.querySelectorAll('#solar-view-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        view = btn.dataset.view;
        render();
      });
    });

    let rankBasis = 'export';
    document.querySelectorAll('#solar-basis-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        rankBasis = btn.dataset.basis;
        document.querySelectorAll('#solar-basis-toggle .toggle-btn').forEach(b => b.classList.toggle('active', b === btn));
        render();
      });
    });

    let euMode = 'separate';
    document.querySelectorAll('#solar-eu-toggle .toggle-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (btn.classList.contains('disabled')) return;
        euMode = btn.dataset.eu;
        document.querySelectorAll('#solar-eu-toggle .toggle-btn').forEach(b => b.classList.toggle('active', b === btn));
        render();
      });
    });

    const highlighted = new Set();
    document.getElementById('solar-rank-legend').addEventListener('change', (e) => {
      const cb = e.target.closest('input[type=checkbox]');
      if (!cb) return;
      if (cb.id === 'solar-select-all') {
        const codes = cb.dataset.codes ? cb.dataset.codes.split(',') : [];
        if (cb.checked) codes.forEach(c => highlighted.add(c));
        else codes.forEach(c => highlighted.delete(c));
        render();
        return;
      }
      const c = cb.dataset.country;
      if (cb.checked) highlighted.add(c); else highlighted.delete(c);
      render();
    });
    // 막대 세그먼트를 직접 클릭해도 같은 국가 전체가 색칠되도록 (체크박스와 동기화)
    document.getElementById('solar-chart').addEventListener('click', (e) => {
      const rect = e.target.closest('rect[data-country]');
      if (!rect) return;
      const c = rect.dataset.country;
      if (highlighted.has(c)) highlighted.delete(c); else highlighted.add(c);
      render();
    });

    document.getElementById('solar-swap').addEventListener('click', () => {
      const aMode = expSel.mode, aVal = expSel.value;
      const bMode = impSel.mode, bVal = impSel.value;
      expSel.setMode(bMode, bVal);
      impSel.setMode(aMode, aVal);
      render();
    });

    function matches(iso3, sel){
      if (sel === 'ALL') return true;
      if (sel === 'EU') return EU27_ISO3.has(iso3);
      if (sel === 'US' || sel === 'CN' || sel === 'NON') {
        const c = countries[iso3];
        return c && c.club === sel;
      }
      return iso3 === sel;
    }

    function label(sel){
      if (sel === 'ALL') return '전체';
      if (sel === 'EU') return EU_LABEL;
      if (CLUB_LABEL[sel]) return CLUB_LABEL[sel];
      return (countries[sel] && countries[sel].name) || sel;
    }

    function bucketOf(period){
      return period.length === 4 ? period : (period.slice(0,4) === '2026' ? '2026' : null);
    }

    const RANK_TOP_N = 14;
    const RANK_PALETTE = ['#c62828','#1a5fb4','#2f6f9f','#c9822f','#5b8c5a','#8a4fae','#b8860b','#0f9b8e','#d2691e','#6b6b68',
      '#e91e8c','#4b0082','#2e7d32','#ff7043','#455a64','#9c27b0'];
    const OTHER_COLOR = '#9c9c96';

    // basis: 'export'면 수출국이 자체 신고한 값(flow X)만, 'import'면 수입국이 자체
    // 신고한 값(flow M)만 쓴다 — 두 통계는 미러 괴리가 있을 수 있어 섞지 않고 하나만 쓴다.
    function computeRankSeries(mode, basis, euMode, groupByClub){
      const data = {};
      const wantFlow = basis === 'import' ? 'M' : 'X';
      for (const [rep, par, period, flow, value] of rows) {
        if (flow !== wantFlow) continue;
        const bucket = bucketOf(period);
        if (!bucket) continue;
        let country = null;
        if (mode === 'importer') {
          // 수출국(expSel)을 고정하고 수입국별로 나눈다 — 수입국 쪽이 특정 클럽·EU라면 그 구성원으로만 좁힌다.
          if (basis === 'import') { if (!matches(par, expSel.value)) continue; country = rep; }
          else { if (!matches(rep, expSel.value)) continue; country = par; }
          if (!matches(country, impSel.value)) continue;
        } else if (mode === 'exporter') {
          // 수입국(impSel)을 고정하고 수출국별로 나눈다 — 수출국 쪽이 특정 클럽·EU라면 그 구성원으로만 좁힌다.
          if (basis === 'import') { if (!matches(rep, impSel.value)) continue; country = par; }
          else { if (!matches(par, impSel.value)) continue; country = rep; }
          if (!matches(country, expSel.value)) continue;
        } else {
          // global: 세계 전체를 수출국(또는 수입국) 신고 기준으로 나눈다.
          country = rep;
        }
        if (!country) continue;
        // 단위=클럽 + 전체를 고른 경우: 국가별이 아니라 클럽(US/CN/NON/UNK)별로 묶는다.
        if (groupByClub) { country = (countries[country] && countries[country].club) || 'UNK'; }
        else if (euMode === 'combined' && EU27_ISO3.has(country)) country = 'EU';
        if (!data[country]) data[country] = {};
        data[country][bucket] = (data[country][bucket] || 0) + value;
      }
      const combined = {};
      Object.keys(data).forEach(c => {
        combined[c] = {};
        YEARS.forEach(y => { combined[c][y] = data[c][y] || 0; });
      });
      return combined;
    }

    function renderRankChart(mode, basis, euMode, shareMode, groupByClub){
      const combined = computeRankSeries(mode, basis, euMode, groupByClub);
      const displayYears = trimYears(YEARS, y => Object.keys(combined).some(c => (combined[c][y] || 0) > 0));

      function label_of(c){
        if (c === '기타') return '기타';
        if (c === 'EU') return 'EU';
        if (groupByClub) return CLUB_FULL_LABEL[c] || c;
        return (countries[c] && countries[c].name) || c;
      }
      function esc_js(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

      const basisLabel = basis === 'import' ? '수입국 신고' : '수출국 신고';
      const euSuffix = (!groupByClub && euMode === 'combined') ? ' · EU 27개국 통합' : '';
      const shareSuffix = shareMode ? ' · 구성비율(100%)' : '';
      const unitWord = groupByClub ? '클럽별' : '국가별';
      let mainTitle, detailLine1;
      if (mode === 'importer') {
        // impSel이 '전체'면 <A의 국가별/클럽별 수출 구성>, 특정 클럽·EU 하나로 좁혔으면 <A → B 수출 구성>.
        mainTitle = impSel.value === 'ALL'
          ? `<${label(expSel.value)}의 ${unitWord} ${PRODUCT} 수출 구성>`
          : `<${label(expSel.value)} → ${label(impSel.value)} ${PRODUCT} 수출 구성>`;
        detailLine1 = `상대국(수입국)별, 연도별 · ${basisLabel} 기준${euSuffix}${shareSuffix}`;
      } else if (mode === 'exporter') {
        mainTitle = expSel.value === 'ALL'
          ? `<${label(impSel.value)}의 ${unitWord} ${PRODUCT} 수입 구성>`
          : `<${label(expSel.value)} → ${label(impSel.value)} ${PRODUCT} 수입 구성>`;
        detailLine1 = `상대국(수출국)별, 연도별 · ${basisLabel} 기준${euSuffix}${shareSuffix}`;
      } else {
        mainTitle = `<전 세계 ${unitWord} ${PRODUCT} 무역 구성>`;
        detailLine1 = `${basisLabel} 기준, 연도별 구성${euSuffix}${shareSuffix}`;
      }
      const summaryText = `${mainTitle} — ${detailLine1} (${HS_NOTE})`;
      document.getElementById('solar-summary').textContent = summaryText;

      const totalByYear = {};
      displayYears.forEach(y => {
        let s = 0;
        Object.keys(combined).forEach(c => { s += combined[c][y] || 0; });
        totalByYear[y] = s;
      });

      // 연도마다 그 해 자체 상위 N개국을 따로 고른다 (고정된 최근연도 순위가 아니다).
      const topByYear = {};
      displayYears.forEach(y => {
        topByYear[y] = Object.keys(combined)
          .map(c => [c, combined[c][y] || 0])
          .filter(([, v]) => v > 0)
          .sort((a, b) => b[1] - a[1])
          .slice(0, RANK_TOP_N)
          .map(([c]) => c);
      });

      // 어느 해든 상위권에 든 적 있는 국가 전부에 전체 기간 합계 기준으로 고정 색을 준다
      // — 그래야 같은 나라가 해마다 같은 색으로 보인다.
      const everTop = new Set();
      displayYears.forEach(y => topByYear[y].forEach(c => everTop.add(c)));
      const overallTotal = {};
      everTop.forEach(c => { overallTotal[c] = displayYears.reduce((s, y) => s + (combined[c][y] || 0), 0); });
      const colorOrder = [...everTop].sort((a, b) => overallTotal[b] - overallTotal[a]);
      const colorOf = {};
      if (groupByClub) {
        colorOrder.forEach(c => { colorOf[c] = CLUB_COLOR[c] || OTHER_COLOR; });
      } else {
        colorOrder.forEach((c, ci) => { colorOf[c] = RANK_PALETTE[ci % RANK_PALETTE.length]; });
      }

      // 연도별 스택: 그 해 상위 N개국(색은 고정) + 기타(나머지 전부, 총액과의 잔차)
      let hasOther = false;
      const stacks = displayYears.map(y => {
        const yearTop = new Set(topByYear[y]);
        const segs = colorOrder.filter(c => yearTop.has(c)).map(c => ({country: c, value: combined[c][y] || 0, color: colorOf[c]}));
        segs.sort((a, b) => b.value - a.value); // 그 해 1위가 맨 아래로 오도록 그 해 값 기준 정렬
        const topSum = segs.reduce((s, seg) => s + seg.value, 0);
        const total = totalByYear[y] || 0;
        const other = Math.max(0, total - topSum);
        if (other > 0) { segs.push({country: '기타', value: other, color: OTHER_COLOR}); hasOther = true; }
        return {year: y, segs, total};
      });

      const maxV = shareMode ? 100 : Math.max(1, ...displayYears.map(y => totalByYear[y] || 0));
      const fmt = v => {
        if (shareMode) return Math.round(v) + '%';
        if (v >= 1e9) return (v/1e9).toFixed(1) + 'B';
        if (v >= 1e6) return (v/1e6).toFixed(0) + 'M';
        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
        return String(Math.round(v));
      };

      const W = 1000, PAD_L = 90, PAD_R = 20, PAD_T = 58, PAD_B = 34, DETAIL_H = 30;
      const plotW = W - PAD_L - PAD_R, plotH = 420;
      const H = PAD_T + plotH + PAD_B + DETAIL_H;
      const groupW = plotW / displayYears.length;
      const barW = groupW * 0.6;
      const scaleY = v => plotH * v / maxV;

      const title = `<text x="${W/2}" y="34" text-anchor="middle" font-size="24" font-weight="700" fill="var(--fg)">${esc_js(mainTitle)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 13).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(detailLine1)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 26).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(HS_NOTE)}</text>`;

      let grid = '';
      for (let g = 0; g <= 4; g++) {
        const gy = PAD_T + plotH - plotH * g / 4;
        grid += `<line x1="${PAD_L}" y1="${gy.toFixed(1)}" x2="${W-PAD_R}" y2="${gy.toFixed(1)}" stroke="var(--line)" stroke-width="1" opacity=".5"/>`;
        grid += `<text x="${PAD_L-8}" y="${(gy+3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(maxV*g/4)}</text>`;
      }

      const NEUTRAL_FILL = 'var(--card)';
      const BORDER_COLOR = 'var(--line)';
      const MIN_LABEL_H = 13;

      let bars = '';
      stacks.forEach((s, i) => {
        const gx = PAD_L + i * groupW + (groupW - barW) / 2;
        let yCursor = PAD_T + plotH;
        s.segs.forEach(seg => {
          const share = s.total > 0 ? (seg.value / s.total * 100).toFixed(1) : '0';
          const h = scaleY(shareMode ? Number(share) : seg.value);
          const segY = yCursor - h;
          const isHi = highlighted.has(seg.country);
          const fill = isHi ? seg.color : NEUTRAL_FILL;
          bars += `<rect data-country="${esc_js(seg.country)}" x="${gx.toFixed(1)}" y="${segY.toFixed(1)}" width="${barW.toFixed(1)}" height="${h.toFixed(1)}" fill="${fill}" stroke="${BORDER_COLOR}" stroke-width="1" style="cursor:pointer"><title>${s.year} ${esc_js(label_of(seg.country))}: $${seg.value.toLocaleString()} (${share}%)</title></rect>`;
          if (h >= MIN_LABEL_H) {
            const textColor = isHi ? '#fff' : 'var(--fg)';
            bars += `<text x="${(gx + barW/2).toFixed(1)}" y="${(segY + h/2 + 3).toFixed(1)}" text-anchor="middle" font-size="9" fill="${textColor}" pointer-events="none">${esc_js(seg.country)}</text>`;
          }
          yCursor = segY;
        });
        bars += `<text x="${(gx + barW/2).toFixed(1)}" y="${(PAD_T + plotH + 16)}" text-anchor="middle" font-size="10" fill="var(--muted)">${s.year === '2026' ? '26(상)' : s.year.slice(2)}</text>`;
      });

      document.getElementById('solar-chart').innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" aria-label="${esc_js(summaryText)}">${title}${grid}${bars}</svg>`;
      applyZoom();

      function checkItem(c, color){
        const checked = highlighted.has(c) ? ' checked' : '';
        const displayName = (c === '기타' || c === 'EU') ? c : `${esc_js(label_of(c))} (${esc_js(c)})`;
        return `<label class="check-item"><input type="checkbox" data-country="${esc_js(c)}"${checked}><i class="dot" style="background:${color}"></i>${displayName}</label>`;
      }
      const legendCodes = hasOther ? [...colorOrder, '기타'] : colorOrder.slice();
      const allSelected = legendCodes.length > 0 && legendCodes.every(c => highlighted.has(c));
      const selectAllItem = `<label class="check-item"><input type="checkbox" id="solar-select-all" data-codes="${esc_js(legendCodes.join(','))}"${allSelected ? ' checked' : ''}><i class="dot" style="background:var(--fg)"></i>전체 선택</label>`;
      const heightNote = shareMode ? '막대 높이=해당 연도 구성비(%), 모든 연도가 100%로 맞춰진다.' : '막대 높이=해당 연도 총액.';
      document.getElementById('solar-rank-legend').innerHTML =
        `<span class="legend-meta" style="flex-basis:100%">막대 안 글자는 국가 ISO3 코드. 테두리선으로만 구분하며, 아래서 체크한 국가만 색이 뜬다. 값은 ${basisLabel} 통계만 쓴다(미러 보완 없음) — 반대쪽 신고를 보려면 위 '기준' 토글을 바꾼다. ${heightNote} 매년 그 해 상위 ${RANK_TOP_N}개국을 표시하고(연도마다 구성 국가가 달라질 수 있다) 나머지는 기타로 묶는다. 색은 전 기간 합계 기준으로 고정한다</span>` +
        `<div class="check-legend" style="flex-basis:100%">` +
        colorOrder.map(c => checkItem(c, colorOf[c])).join('') +
        (hasOther ? checkItem('기타', OTHER_COLOR) : '') +
        selectAllItem +
        `</div>`;
    }

    // 'ALL'(전체) 뿐 아니라 클럽(US/CN/NON)·EU도 여러 국가를 묶은 그룹이라
    // 구성(절대비교/구성비율) 보기가 의미 있다 — 단일 국가일 때만 의미 없다.
    function isGroupSel(sel){ return sel === 'ALL' || sel === 'EU' || !!CLUB_LABEL[sel]; }

    function render(){
      const expV = expSel.value, impV = impSel.value;
      const expIsGroup = isGroupSel(expV), impIsGroup = isGroupSel(impV);
      const hasGroup = expIsGroup || impIsGroup;
      const bothAll = expV === 'ALL' && impV === 'ALL';
      document.querySelectorAll('#solar-view-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
        btn.classList.toggle('active', hasGroup && btn.dataset.view === view);
      });
      document.querySelectorAll('#solar-basis-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
        btn.classList.toggle('active', !hasGroup || btn.dataset.basis === rankBasis);
      });
      document.querySelectorAll('#solar-eu-toggle .toggle-btn').forEach(btn => {
        btn.classList.toggle('disabled', !hasGroup);
      });

      if (hasGroup) {
        document.getElementById('solar-rank-legend').style.display = '';
        // 어느 쪽을 쪼개지: '전체'로 열어둔 쪽이 있으면 그쪽을 쪼개다.
        // (수출국=전체 · 수입국=EU 처럼 양쪽 다 그룹일 때 EU를 회원국별로
        // 쪼개버리지 않고, 'EU가 어디서 수입했나'를 보여주기 위한 우선순위다.)
        const mode = bothAll ? 'global'
          : expV === 'ALL' ? 'exporter'
          : impV === 'ALL' ? 'importer'
          : impIsGroup ? 'importer' : 'exporter';
        // 단위=클럽으로 놓고 '전체'를 고르면 국가별이 아니라 클럽별(US/CN/NON/UNK)로 묶어 보여준다.
        let groupByClub;
        if (mode === 'importer') groupByClub = impSel.mode === 'bloc' && impV === 'ALL';
        else if (mode === 'exporter') groupByClub = expSel.mode === 'bloc' && expV === 'ALL';
        else groupByClub = rankBasis === 'import' ? (impSel.mode === 'bloc') : (expSel.mode === 'bloc');
        if (groupByClub) {
          document.querySelectorAll('#solar-eu-toggle .toggle-btn').forEach(btn => btn.classList.add('disabled'));
        }
        renderRankChart(mode, rankBasis, euMode, view === 'share', groupByClub);
        return;
      }
      document.getElementById('solar-rank-legend').style.display = 'none';
      const xByYear = {}, mByYear = {};
      YEARS.forEach(y => { xByYear[y] = 0; mByYear[y] = 0; });
      let matchedRows = 0;
      for (const [rep, par, period, flow, value] of rows) {
        const bucket = bucketOf(period);
        if (!bucket) continue;
        if (flow === 'X' && matches(rep, expV) && matches(par, impV)) {
          xByYear[bucket] += value; matchedRows++;
        } else if (flow === 'M' && matches(rep, impV) && matches(par, expV)) {
          mByYear[bucket] += value; matchedRows++;
        }
      }

      const displayYears = trimYears(YEARS, y => xByYear[y] > 0 || mByYear[y] > 0);
      const maxV = Math.max(1, ...displayYears.map(y => Math.max(xByYear[y], mByYear[y])));
      const W = 1000, PAD_L = 90, PAD_R = 20, PAD_T = 58, PAD_B = 34, DETAIL_H = 30;
      const plotW = W - PAD_L - PAD_R, plotH = 260;
      const H = PAD_T + plotH + PAD_B + DETAIL_H;
      const groupW = plotW / displayYears.length;
      const barW = groupW * 0.36;
      const scaleY = v => plotH * v / maxV;
      function esc_js(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
      const mainTitle = `<${label(expV)} → ${label(impV)} ${PRODUCT} 무역>`;
      const detailLine1 = `매칭 ${matchedRows.toLocaleString()}건`;
      const summaryText = `${mainTitle} — ${detailLine1} (${HS_NOTE})`;
      const title = `<text x="${W/2}" y="34" text-anchor="middle" font-size="24" font-weight="700" fill="var(--fg)">${esc_js(mainTitle)}</text>` +
        `<rect x="${PAD_L}" y="46" width="10" height="10" fill="${X_COLOR}"></rect>` +
        `<text x="${PAD_L+14}" y="55" font-size="11" fill="var(--fg)">수출국 신고</text>` +
        `<rect x="${PAD_L+100}" y="46" width="10" height="10" fill="${M_COLOR}"></rect>` +
        `<text x="${PAD_L+114}" y="55" font-size="11" fill="var(--fg)">수입국 신고</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 13).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(detailLine1)}</text>` +
        `<text x="${W-PAD_R}" y="${(PAD_T + plotH + PAD_B + 26).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--muted)">${esc_js(HS_NOTE)}</text>`;

      const fmt = v => {
        if (v >= 1e9) return (v/1e9).toFixed(1) + 'B';
        if (v >= 1e6) return (v/1e6).toFixed(0) + 'M';
        if (v >= 1e3) return (v/1e3).toFixed(0) + 'K';
        return String(Math.round(v));
      };

      let bars = '';
      displayYears.forEach((y, i) => {
        const gx = PAD_L + i * groupW;
        const xh = scaleY(xByYear[y]), mh = scaleY(mByYear[y]);
        const xy = PAD_T + plotH - xh, my = PAD_T + plotH - mh;
        bars += `<rect x="${(gx + groupW*0.08).toFixed(1)}" y="${xy.toFixed(1)}" width="${barW.toFixed(1)}" height="${xh.toFixed(1)}" fill="${X_COLOR}"><title>${y} 수출국(${label(expV)}) 신고: $${xByYear[y].toLocaleString()}</title></rect>`;
        bars += `<rect x="${(gx + groupW*0.08 + barW + 3).toFixed(1)}" y="${my.toFixed(1)}" width="${barW.toFixed(1)}" height="${mh.toFixed(1)}" fill="${M_COLOR}"><title>${y} 수입국(${label(impV)}) 신고: $${mByYear[y].toLocaleString()}</title></rect>`;
        bars += `<text x="${(gx + groupW/2).toFixed(1)}" y="${(PAD_T + plotH + 16)}" text-anchor="middle" font-size="10" fill="var(--muted)">${y === '2026' ? '26(상)' : y.slice(2)}</text>`;
      });
      let grid = '';
      for (let g = 0; g <= 4; g++) {
        const gy = PAD_T + plotH - plotH * g / 4;
        grid += `<line x1="${PAD_L}" y1="${gy.toFixed(1)}" x2="${W-PAD_R}" y2="${gy.toFixed(1)}" stroke="var(--line)" stroke-width="1" opacity=".5"/>`;
        grid += `<text x="${PAD_L-8}" y="${(gy+3).toFixed(1)}" text-anchor="end" font-size="10" fill="var(--muted)">${fmt(maxV*g/4)}</text>`;
      }

      document.getElementById('solar-chart').innerHTML =
        `<svg viewBox="0 0 ${W} ${H}" aria-label="${esc_js(summaryText)}">${title}${grid}${bars}</svg>`;
      applyZoom();
      document.getElementById('solar-summary').textContent = summaryText;
    }

    render();
  }
})();
</script>
</body></html>
"""


def build(out: Path) -> bool:
    import build_solar_data
    import bloc_site as bs

    solar_ok = build_solar_data.build(out)
    row_count = "0"
    if solar_ok:
        payload = json.loads((out / "solar_trade.json").read_text(encoding="utf-8"))
        row_count = f"{len(payload['rows']):,}"

    country_list_html = ""
    if bs.BSV.is_file() and bs.WORLD.is_file():
        pos = bs.load_bsv()
        blocs = bs.build_blocs(pos)
        geo = json.loads(bs.WORLD.read_text(encoding="utf-8"))
        country_list_html = bs.render_country_list(blocs, geo)

    html = HTML.replace("__ROW_COUNT__", row_count).replace("__COUNTRY_LIST__", country_list_html)
    (out / "solar.html").write_text(html, encoding="utf-8")
    return solar_ok


if __name__ == "__main__":
    site_dir = HERE / "site"
    ok = build(site_dir)
    print("built" if ok else "missing source files — skipped")
