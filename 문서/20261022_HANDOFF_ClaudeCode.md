---
작성일: 2026-10-22
대상: Claude Code (이 폴더에서 실행)
작성자: Claude (claude.ai 세션에서 폴더 전수 확인 후 작성)
---

# 인계 — GitHub Actions 이전

## 최종 목표 (한 문장)

`02_웹사이트` 폴더를 이 PC에서 삭제해도, GitHub 저장소 + Cloudflare R2 + GitHub Secrets만으로 매주 자동 갱신·배포가 되고, 새 PC에 clone하면 로컬 실행도 되는 상태.

## 끝났다고 판정하는 기준

1. 새 임시 폴더에 clone → `scripts/bootstrap`(만들 것) → R2에서 캐시 내려받기 → `--mode incremental --yes` 로컬 실행이 끝까지 돈다
2. GitHub Actions 수동 실행 1회 성공: 리포트 생성 → 사이트 빌드 → 배포 → 무인증 접속이 401
3. 주간 스케줄이 2주 연속 성공
4. 위 3개가 되면 연구자가 폴더를 삭제한다. **삭제는 Claude Code가 하지 않는다.**

## 2026-10-22 확인된 사실 (다시 조사하지 않아도 됨)

- GTA 마지막 갱신 2026-08-28(incremental), 마지막 full 2026-08-27. `cache/state.json` 참조
- 사이트 마지막 배포 2026-09-06. `oil_verify.html`은 코드에만 있고 배포본 index에 없음
- **원자료 소실**: `../../05_국정원과제/02_원자료/`가 없다. 거기 있던 Comtrade CSV 3종(`comtrade_oil_2709_2710_raw.csv`, `comtrade_oil_2711_hs6_raw.csv`, `comtrade_solar_854142_854143_raw.csv`)과 `GTA Threads/`를 `bloc_site.py`·`build_oil_data.py`·`build_solar_data.py`가 읽는다. 수집 스크립트는 볼트 안에 없다. `publish_site.py`는 2026-10-15부터 직전 빌드(`site_prev`)에서 해당 패널을 복사해 버틴다
- 폴더 밖 참조 4곳: `ip_risk_site.py`(BSV tab, IMF DOTS csv, WDI csv), `bloc_site.py`(BSV tab, GTA Threads). 전부 `ROOT = HERE.parents[1]` 기준
- 비밀값 3종은 Windows DPAPI(`*.xml`). `run_update.ps1` 219행이 복호화해 `GTA_API_KEY` 환경변수로 넘긴다. `auto_update.py` 1698행이 그 환경변수를 읽는다
- `auto_update.py`는 `--mode {incremental,full}`, `--end-date`, `--yes`, `--rebuild-excel`를 받는다. 대화형 입력은 1668행 `input()` 1곳 — `--yes` 경로에서 우회되는지 확인 필요
- `run_update.ps1` Read-Host 3곳(91·160·184행), `deploy_site.ps1`(functions 존재 확인 + 배포 후 401 검증), `site_setup.ps1`([1] CF 토큰 [2] 비밀번호 [3] 개인계정)
- `cache/` 146MB: `master.parquet` 67MB, `prediction_cache.json` 32MB, `state.json`, `api_pages/`. 소실 시 BERT 재분류 약 4시간
- `site/` 35MB, 최대 파일 `oil_trade.json` 16.5MB (Cloudflare Pages 파일당 25MiB 한도)
- 상위 볼트 저장소에는 원격이 없다(한 번도 push된 적 없음). `user.name`·`user.email` 미설정
- GitHub 계정 `lskyonsei-jpg`, Free 플랜(비공개 저장소 Actions 월 2,000분). 저장소 `skl-economic-security-tracker` 생성됨(private, 빈 상태)
- 이 PC의 Linux 셸 기준으로 git 2.34 있음, github.com 접속 가능

## 이미 결정된 것

- 저장소 분리: `02_웹사이트`만 새 비공개 저장소로. 볼트 저장소는 건드리지 않음
- 비공개 유지. 공개 전환 없음
- 폴더 삭제가 목표이므로 볼트에 중첩 clone을 두는 것은 선택사항. 볼트에는 `04_파생작업/README.md`에 저장소 주소 한 줄만 남기면 된다(그 수정은 연구자에게 요청)
- 엑셀: 주간 실행에서만 생성, 아티팩트 14일 보존 (연구자가 달리 말하지 않는 한)
- 주기: 주 1회 full + 일 1회 incremental (연구자가 달리 말하지 않는 한)

## 결정 대기 — 착수 전에 묻는다

1. 캐시·원자료 보관소: A. Cloudflare R2(권장) / B. GitHub Release 자산 / C. actions/cache(비권장)
2. Comtrade API 키 보유 여부. 원본 CSV 3종과 GTA Threads CSV의 행방(OneDrive 휴지통 등)
3. 멈춤 조건 임계치: 전체 표본 감소 N%, 삭제 건수 상한
4. `oil_verify` 패널을 index에 올릴지
5. 볼트 측 정리(`.gitignore`, README 한 줄)를 연구자가 직접 할지

## 작업 순서

각 단계는 끝날 때 결과를 보고하고 멈춘다. 다음 단계는 승인 후.

### 1단계. 첫 커밋

- 이 폴더에서 `git init` (상위 볼트 저장소와 별개. `git rev-parse --show-toplevel`이 이 폴더인지 확인)
- `.gitignore`는 현재 것 유지 + `site_prev/`, `*.log` 추가
- 커밋 전 검사: `git ls-files`에 `.xml`, `.site_users.json`, `cache/`, `output/`, `site/`, `node_modules/`가 없음을 확인. `git grep -I -n -E "(api[_-]?key|token|password)\s*[:=]\s*['\"][A-Za-z0-9]{16,}"`가 비어 있음을 확인
- `user.name`·`user.email`은 이 저장소에만(`--local`) 설정. 값은 연구자에게 묻는다
- `main` 브랜치로 push. 커밋 메시지 한국어
- 완료 기준: GitHub에서 파일 목록이 보이고 비밀값·산출물이 없음

### 2단계. 폴더 밖 참조 제거

- BSV tab, DOTS csv, WDI csv 사본을 `reference/`로. 원본 파일명 유지
- `reference/README.md`에 각 파일의 출처·수집일·갱신 방법 기록
- 코드의 `ROOT / "02_인덱스/..."` 경로를 `HERE / "reference" / ...`로
- 완료 기준: 볼트 밖(임시 폴더)에 복사해서 `publish_site.py`가 bloc·solar를 제외한 패널을 빌드함

### 3단계. Comtrade 수집 스크립트 + 원자료 복구

- `collect_comtrade.py` 신규: HS 2709·2710, 2711 6단위 7개(`build_oil_data.py` 주석의 코드 목록), 854140·854142·854143. 2010~현재. 보고국별 1회 호출로 분할(무료 키 하루 500회·호출당 10만 행 — 공식 구독 페이지에서 재확인)
- 산출 CSV 스키마는 기존 `build_*_data.py`가 읽던 열과 같게. 열 이름은 그 스크립트의 코드에서 역추적
- raw CSV는 저장소가 아니라 보관소(1번 결정)에. 빌드 시 내려받기
- GTA Threads: 출처 확인 후 `reference/` 보존 또는 `master.parquet`에서 재생성. 재생성 불가하면 해당 흐름도만 비활성화하고 보고
- 완료 기준: bloc·solar·oil_verify가 "건너뜀" 없이 빌드. `publish_site.py`의 `site_prev` 복사 분기 제거

### 4단계. PowerShell → Python 이식, 무인 실행

- `scripts/run.py`: `run_update.ps1`의 로직. 모드·종료일은 인자. 환경변수 `GTA_API_KEY` 사용
- `scripts/deploy.py`: `deploy_site.ps1`의 안전장치 그대로 — `functions/_middleware.js` 존재 확인, `wrangler pages deploy site --cwd .`(functions는 site 밖), 배포 후 무인증 GET이 401/403/503이 아니면 실패
- `scripts/site_users.py`: `site_setup.ps1` [2][3]. Cloudflare API 직접 호출, 파이프로 비밀값 넘기지 않음(줄바꿈 사고 전례)
- `scripts/cache_sync.py`: 보관소 ↔ `cache/` 내려받기·올리기
- 멈춤 조건을 종료코드로: 수출통제 9종 유형명 0건, `intervention_id` 결측·중복, 열 수 불일치, 표본 감소 N% 초과, 삭제 건수 상한 초과
- `.cmd`·`.ps1` 파일은 지우지 말고 상단에 "CI로 이전됨, scripts/ 참조" 주석
- 완료 기준: 로컬에서 `python scripts/run.py --mode incremental --yes`가 입력 없이 끝까지 돈다

### 5단계. Secrets·워크플로

- 연구자가 GitHub 웹에서 넣을 Secrets 이름: `GTA_API_KEY`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, (R2면) `R2_ACCESS_KEY_ID`·`R2_SECRET_ACCESS_KEY`·`R2_BUCKET`, (Comtrade) `COMTRADE_API_KEY`
- DPAPI 값 꺼내기: 화면에 찍지 말고 클립보드로 — `powershell -c "(Import-Clixml .gta_api_key.xml | ConvertFrom-SecureString -AsPlainText) | Set-Clipboard"` 류의 한 줄을 연구자에게 제시만 한다(xml 구조는 `run_update.ps1` 219행 참조)
- `.github/workflows/weekly-full.yml`(일요일 새벽 KST), `daily-quick.yml`, 둘 다 `workflow_dispatch`에 종료일·모드 입력
- 공통: Python 3.11, pip 캐시, torch CPU 휠 인덱스, HF 모델은 `actions/cache`(키에 `MODEL_REVISION`)
- 리포트를 Step Summary에 실음. 실패 시 GitHub 기본 이메일 알림
- 완료 기준: 수동 실행 1회 성공, 무인증 접속 401

### 6단계. 스케줄 가동·문서

- README 전면 개정: 패널 5개, 데이터 흐름(GTA·Comtrade·BSV·DOTS·WDI → 어느 패널), 운영 절차(CI·로컬·비밀값 교체·캐시 복구)
- `index.html`에 자료 기준일·빌드 시각·커밋 SHA·패널별 원자료 기준일
- 완료 기준: 2주 연속 자동 실행 성공 → 연구자에게 "폴더 삭제 가능" 보고

## 참고 위치

- 설계 배경·선택지·패널 로드맵: `문서/20261022_운영방안_GitHub이전과_패널로드맵.md`
- 열 정의·GTA가 공지 없이 바꾸는 것들: `문서/코드북.md`
- 반도체 화면 유지보수 태그: `문서/설계_반도체공급망화면.md`
- 석유 패널 검증 과제(미완): `문서/석유패널_검증고도화_프롬프트_v2.md`
