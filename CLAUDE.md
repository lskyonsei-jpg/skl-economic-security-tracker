# CLAUDE.md — SKL Economic Security Tracker

이 저장소는 GTA 수집 → BERT 분류 → 변경 리포트 → 정적 사이트 빌드 → GitHub Pages 배포(GitHub Actions)까지 자체 완결된 파이프라인이다.

## 현재 상태

- 운영 구조와 화면 목록은 `README.md`. 사이트는 패널 2개(산업정책 트래커, 한미 AI 협력 트래커) + 판단 대기 + 자료 + 코드북.
- 디자인 규칙은 `문서/20261022_디자인시스템.md`, 토큰은 `assets/site.css`. 화면 글자는 전부 20pt 이상(연구자 지시).
- 패널 2 자동화 설계는 `문서/20261022_설계_한미AI협력트래커_자동화.md`.
- 원격 저장소: `https://github.com/lskyonsei-jpg/skl-economic-security-tracker`. 공개 사이트, GitHub Pages 호스팅, 상태는 GitHub Release `state` 자산.
- 로컬 작업은 저장소를 스크래치패드에 clone 해서 한다. 연구자 볼트에 두지 않는다.

## 절대 하지 않는 것

- 비밀값(GTA·Anthropic 키)을 읽거나 출력하거나 커밋하지 않는다. 사람이 GitHub Secrets 에 직접 넣는다.
- `cache/`, `output/`, `site/`, `logs/`, `.venv/`, `data/`(seed·decisions 제외)를 커밋하지 않는다.
- 로컬 실행 절차·스크립트(.cmd, .ps1)를 만들지 않는다. 실행은 GitHub Actions 가 한다.
- 근거 없는 수정을 하지 않는다. 바꾸기 전에 README·코드북·로그로 실제 동작을 확인한다.

## 판단권

- 복수의 선택지가 있거나 근거가 부족하면 임의로 고르지 않는다. 쟁점과 선택지를 번호로 정리해 묻고, 답을 받은 뒤 진행한다.
- 결정이 필요한 항목은 번호로 묻되, 기본값을 함께 제시해 한 번에 답할 수 있게 한다.

## 문서·화면 글

- 한국어, 개조식. 핵심 판단을 첫 문장에.
- 화면의 안내문은 최소한으로. 번역체("~한다", "~이다"의 나열)나 AI 말투 대신 짧고 직관적인 한국어. 산식·주의사항은 화면이 아니라 코드북(`문서/코드북_패널.md`)에 둔다.
- 사실·해석·추측을 구분한다. count 와 share 를 같이, 분모를 밝힌다.
- 파일명에 `final`, `new`, `latest` 를 쓰지 않는다. 날짜는 `YYYYMMDD`.

## 데이터 해석 규칙 (코드 주석·화면 문구에 적용)

- `D_IP_bert_3 == 1` 은 산업정책 후보군이다. 확정 라벨이 아니다.
- GTA Red/Amber = 외국 상업이익에 해로운 조치, Green = 비차별적 자유화. 환경 분류가 아니다.
- `Affected Jurisdiction` 은 수혜국이 아니라 상업적 이해가 영향받는 국가다.
- 분석 단위는 intervention. state act 와 혼동하지 않는다.

## 실행 환경

- 실행은 GitHub Actions(`.github/workflows/pipeline.yml`). CI 는 Python 3.11 — f-string 표현식에 백슬래시 금지.
- 로컬 확인은 `.venv/Scripts/python.exe` 로 `publish_site.py` 만. `PYTHONUTF8=1` 필수. Release `state` 의 `master.parquet`·`logs`·`reference` 가 `cache/`·`logs/`·`data/reference/` 에 있어야 한다.
- Bash 도구는 파이썬 삼중따옴표가 든 히어독을 못 넘긴다 → 패치 스크립트는 파일로 쓰고 실행한다.
