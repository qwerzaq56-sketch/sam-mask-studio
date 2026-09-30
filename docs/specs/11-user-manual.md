# 11 · 사용 설명서 기획 (AI 작업용)

> 요청(2026-09-30): 추천 워크플로 기준의 사용 설명서 + 부가 기능 설명. 이 기획을 다른 세션에서 구체화한 뒤, 실제 설명서는
> **Notion에 쓰고 GitHub에서도 보이게** 한다.
> 이 문서는 그 세션이 읽고 바로 일할 수 있게 쓴 작업 지시서다. 결정된 것 / 정할 것 / 사실의 출처를 나눠 둔다.

## 0. 이 문서를 받은 세션이 할 일 (순서)

1. **사실 수집**: §4의 출처를 읽는다. 기능 설명은 반드시 출처(코드 · 문서)에서 확인한 것만 쓴다. 추측으로 채우지 않는다.
2. **구체화**: §3 목차를 장 단위의 세부 목차(절, 들어갈 그림, 예시 데이터)로 풀고, §6의 열린 질문을 사용자에게 체크리스트로 묻는다.
3. **초안**: 저장소에 Markdown으로 먼저 쓴다(§5 위치). GitHub 노출은 이것이 담당한다.
4. **Notion**: 사용자가 정한 Notion 위치에 같은 내용을 옮긴다(Notion 커넥터). 원본은 저장소 Markdown, Notion은 사본(§5).
5. **검수**: 앱을 실제로 띄워 각 절차를 따라 해 보고(스크린샷), 틀린 곳을 고친다.

## 1. 목적과 독자

- **독자**: 3DGS / COLMAP 학습용 마스크를 만드는 사람. SAM이나 COLMAP 용어를 들어는 봤지만 이 툴은 처음.
  두 번째 독자는 이 툴을 오래 쓴 사용자(단축키 · 부가 기능을 찾아보는 용도).
- **목표**: 처음 쓰는 사람이 설명서만 보고 "폴더 열기 → 마스크 만들기 → 학습기에 맞게 내보내기"를 한 번 끝낼 수 있게.
  그 뒤에 필요한 기능을 찾아 쓸 수 있게.
- **하지 않을 것**: 개발 문서(설치 빌드 · 내부 구조)는 `README.md` / `docs/DEVELOPMENT.md` 몫. 설명서는 사용법만.

## 2. 결정된 것

- 구성: **추천 워크플로(따라 하기)**가 앞, **기능 참고(찾아보기)**가 뒤.
- 언어: 한국어 본문, UI 이름은 앱에 보이는 영어 그대로(`Export`, `Propagate Selected Objects` …). 키는 `E`, `Ctrl+Z`처럼.
- 원본은 저장소의 Markdown 한 벌. Notion과 GitHub에 같은 내용.
- 기준 버전: 쓰는 시점의 dev 최신 태그(지금 `v0.4-p54`). 설명서 첫머리에 적는다.

## 3. 목차 초안 (구체화 대상)

### A. 시작하기
1. 이 툴이 하는 일(한 문단) · 핵심 개념: Detection / Object / Variant / 포인트 레이어 / Edit Layer / Final Mask / 마스크 세트 / 특수 Object
2. 화면 구성(스크린샷 1장에 번호): Frame List · Objects · Prompt / Batch / Propagation / Logs 탭 · 캔버스 · Properties · Frames 줄 · 툴바
3. 준비: 체크포인트(SAM2 / SAM3 / Sky 모델) 위치와 Settings

### B. 추천 워크플로 (따라 하기)
1. **폴더 또는 COLMAP 장면 열기**: 장면 루트를 열면 `images/`(하위 폴더 cam0 / cam1 포함)를 엶, 마스크 폴더 불러오기, 사이드카(`<장면>.sms`)
2. **Object 만들기**: SAM3 텍스트(Prompt / Batch 탭) → 후보 고르기 → Add · 또는 `N` + 클릭 / 박스
3. **다듬기**: 포인트 레이어(Original / Layer + −), Ctrl+클릭 조각, 브러시(`D`), 오토 툴(Fill / Paint 모드, `A` `D` `F`), Region
4. **전파**: 기준 ◎, 범위 / 선택 / 전체, 라이브 뷰, Stop / Resume / Cancel, Undo
5. **검수**: ⚠ ✕ 문제 프레임(`[` `]`), 키프레임 ★(`,` `.`), Mask Preview(`V` `X` `Z`), Solo(`Q`) / Hide(`H`) / 👁
6. **학습기용 Export**: For(Brush / LichtFeld / Spirula / Postshot / COLMAP) → 장면에 쓰기(백업) 또는 New dataset(⊘ 프레임 제외)
7. (선택) **변환**: 360 → Pinhole, Fisheye → Pinhole / 360, 듀얼 피시아이 → 360

워크플로마다 "상황 → 조작 → 확인할 것" 형식, 끝에 자주 하는 실수.

### C. 시나리오별 짧은 레시피
- 사람 / 셀카봉 지우기(3DGS의 움직이는 물체) · 하늘 따로(Sky 특수 Object + 마스크 세트) · 피시아이 검은 테두리(Lens Edge)
- 이미 있는 마스크 고치기(불러오기 → 포인트 레이어 / 브러시) · 여러 프레임에 같은 마스크(Copy Mask to Picked Frames)

### D. 기능 참고 (찾아보기)
- Objects 패널(체크박스 · 👁 · 🔒 · Merge · Move / Copy · Duplicate · 잠금 규칙)
- 여러 프레임 작업(Copy / Clear on Picked Frames, ⊘ Exclude, 가운데 클릭 / 우클릭)
- 특수 Object(Sky 설정값, Lens Edge Detect, Apply)
- 마스크 세트 · Export 창의 모든 칸 · 학습기별 규칙 표(폴더, 이름, 흑백 의미, 학습기에서 켤 설정)
- 투영 변환 옵션(yaw / pitch / FOV / 크기)
- 단축키 전체표(앱의 F1과 같은 내용)

### E. 부록
- 파일 위치(사이드카, 캐시, 백업 폴더) · 문제 해결(SAM2 로딩, 카메라 모델 미지원, 덮어쓰기 규칙) · 용어집

## 4. 사실의 출처 (여기서 확인한 것만 쓴다)

| 주제 | 출처 |
|---|---|
| 전체 흐름 · 개념 · 현재 사용법 절 | `README.md`(단, "사용법" 절은 v0.4 후반 기능이 빠져 있을 수 있음: 대조 필요) |
| 키와 메뉴 | `docs/design/keymap.md`, `docs/design/menu-design.md`, 앱 F1 표의 원본 `src/app/dialogs.py`의 `SHORTCUTS` |
| 기능의 의도 · 옵션 | `docs/specs/01`~`10` (특히 02 전파, 03 Object, 05 Merge / Copy / Move, 06 COLMAP, 07 Export, 08 변환, 09 특수 Object, 10 포인트 레이어) |
| 무엇이 언제 바뀌었나 | `docs/log/PROGRESS_v0.4.md`(단계별 · 최신이 아래), `docs/log/ideas-log.md` |
| 학습기별 마스크 규칙 | `src/core/presets.py`(각 프리셋의 `note`, `verified`), `docs/specs/07-export-presets.md` |
| 화면 문구 | `src/app/*.py`의 버튼 글자와 툴팁(설명서의 UI 이름은 여기와 글자 하나까지 같게) |

## 5. 위치와 동기화 (제안, §6에서 확정)

- 저장소: `docs/manual/`(장마다 파일) 또는 `docs/MANUAL.md` 한 파일. 그림은 옆 폴더. README의 "사용법" 절은 설명서로 가는 링크 + 짧은 요약으로 줄임.
  (주의: `docs/README.md`의 정리 원칙 1은 "새 폴더 만들지 않음" — `docs/manual/`을 쓰려면 원칙에 설명서 예외를 적는다.)
- Notion: 사용자가 준 페이지 아래에 같은 목차로. 원본은 저장소라 Notion에서 고친 내용은 저장소로 되돌려야 함(한 방향 유지 권장).
- 스크린샷: 앱을 실제 폰트로 띄워 찍음(개발 세션들이 써 온 방식: `QT_QPA_PLATFORM=windows`, 창을 화면 밖에 두고 `grab()`).
  예시 데이터는 사용자 촬영본이 아닌 공개 가능한 이미지로(사용자 확인 필요).

## 6. 열린 질문 (구체화 세션이 사용자에게 체크리스트로)

1. Notion 위치(워크스페이스 / 상위 페이지)와 공개 범위. GitHub에는 저장소 Markdown이면 되는지, GitHub Pages / Wiki도 원하는지.
2. 저장소 위치: `docs/manual/` 여러 파일 vs `docs/MANUAL.md` 한 파일.
3. 영어판도 필요한지(지금 README는 한 줄 영어 요약만).
4. 스크린샷에 쓸 예시 데이터: 사용자 촬영본 사용 가능? 아니면 공개 이미지?
5. 기준 워크플로의 주인공 시나리오: "3DGS 촬영본에서 사람 지우기"로 할지, 360 / 듀얼 피시아이까지 본편에 넣을지.
6. 아직 바뀔 수 있는 부분(E / D / A / F 키 배치에 사용자 피드백 대기 중)을 설명서에 넣는 시점.

## 7. 주의

- 기능은 계속 바뀌는 중(dev 브랜치, 단계 태그 `v0.4-pN`). 설명서를 쓰는 동안 새 태그가 생기면 `PROGRESS_v0.4.md`의 새 단계를 반영한다.
- 앱 코드는 설명서 작업에서 고치지 않는다. 설명서를 쓰다 발견한 UI 문제는 `docs/backlog/ui-issues.md`의 "사용자 메모"에 적는다.
