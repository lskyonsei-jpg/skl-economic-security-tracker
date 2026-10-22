# CLAUDE.md — SKL Economic Security Tracker

이 폴더는 GTA 수집 → BERT 분류 → 변경 리포트 → 정적 사이트 빌드 → GitHub Pages 배포(GitHub Actions)까지 자체 완결된 파이프라인이다.

## 지금 진행 중인 작업

- **GitHub Actions 이전은 2026-10-22 완료.** 운영 구조는 `README.md`, 결정 이력은 `문서/20261022_HANDOFF_ClaudeCode.md` 상단.
- 사이트는 패널 2개 체제(산업정책 트래커, 한미 AI 협력 트래커). 디자인 규칙은 `문서/20261022_디자인시스템.md`, 토큰은 `assets/site.css`.
- 설계 배경과 선택지는 `문서/20261022_운영방안_GitHub이전과_패널로드맵.md`.
- 원격 저장소: `https://github.com/lskyonsei-jpg/skl-economic-security-tracker`. 2026-10-22 연구자 결정: 사이트 공개 전환, GitHub Pages 호스팅, Cloudflare 완전 제거, 보관소는 GitHub Release 자산(R2 안 씀).

## 절대 하지 않는 것

- `.gta_api_key.xml`(및 남아 있는 옛 Cloudflare 파일 `.cf_api_token.xml`, `.site_users.json`)의 내용을 읽거나 출력하거나 커밋하지 않는다. 비밀값은 사람이 GitHub Secrets에 직접 넣는다.
- `cache/`, `output/`, `site/`, `logs/`, `.venv/`, `node_modules/`를 커밋하지 않는다.
- 상위 볼트 저장소(`../../`, `02_System building`)에 원격을 추가하거나 push하지 않는다. 회의록·과제 자료가 들어 있다.
- 이 폴더 밖의 파일을 수정·이동하지 않는다. 밖에서 가져올 파일은 `reference/`에 사본으로 둔다.
- 근거 없는 수정을 하지 않는다. 바꾸기 전에 README·코드북·로그로 실제 동작을 확인한다.

## 판단권

- 복수의 선택지가 있거나 근거가 부족하면 임의로 고르지 않는다. 쟁점과 선택지를 번호로 정리해 묻고, 답을 받은 뒤 진행한다.
- 결정이 필요한 항목은 번호로 묻되, 기본값을 함께 제시해 한 번에 답할 수 있게 한다.

## 문서 작성

- 한국어, 개조식. 핵심 판단을 첫 문장에.
- 사실·해석·추측을 구분한다. count와 share를 같이, 분모를 밝힌다.
- 파일명에 `final`, `new`, `latest`를 쓰지 않는다. 날짜는 `YYYYMMDD`.

## 데이터 해석 규칙 (코드 주석·화면 문구에 적용)

- `D_IP_bert_3 == 1`은 산업정책 후보군이다. 확정 라벨이 아니다.
- GTA Red/Amber = 외국 상업이익에 해로운 조치, Green = 비차별적 자유화. 환경 분류가 아니다.
- `Affected Jurisdiction`은 수혜국이 아니라 상업적 이해가 영향받는 국가다.
- 분석 단위는 intervention. state act와 혼동하지 않는다.

## 실행 환경

- 실행은 GitHub Actions(`.github/workflows/pipeline.yml`)가 한다. 로컬 실행 절차·스크립트를 만들지 않는다(연구자 지시 2026-10-22).
- 로컬 확인은 `.venv/Scripts/python.exe` 로 `publish_site.py` 만. `PYTHONUTF8=1` 필수.
- 세부 동작은 `README.md`와 `문서/코드북.md`.
