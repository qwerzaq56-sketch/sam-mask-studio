# 11 · 사용 설명서 기획 (AI 작업용)

> 요청(2026-09-30): 추천 워크플로 기준의 사용 설명서 + 부가 기능 설명. 이 기획을 다른 세션에서 구체화한 뒤, 실제 설명서는
> **Notion에 쓰고 GitHub에서도 보이게** 한다.
> 이 문서는 그 세션이 읽고 바로 일할 수 있게 쓴 작업 지시서다. 결정된 것 / 정할 것 / 사실의 출처를 나눠 둔다.
> **구체화 완료(2026-09-30)**: §6의 질문에 답을 받았고, §3을 장 · 절 · 그림 · 예시 절차까지 풀었다.
> **초안 완료(2026-09-30, 기준 `v0.4-p58`)**: `docs/manual/` A~E. 그림은 자리(📷)만. 다음은 예시 데이터 확정 → 스크린샷, Notion.

## 0. 이 문서를 받은 세션이 할 일 (순서)

1. ~~**사실 수집**: §4의 출처를 읽는다.~~ (완료, 차이는 §4.1)
2. ~~**구체화**: §3 목차를 세부 목차로 풀고, §6의 열린 질문을 사용자에게 묻는다.~~ (완료)
3. ~~**초안**: `docs/manual/`에 장별 Markdown으로 쓴다(§5).~~ (완료, 그림 제외. README "사용법"은 링크 + 요약으로 줄여 §4.1 해소)
4. ~~**Notion**: "공유 페이지_대학원" 아래 새 페이지에 같은 내용을 옮긴다.~~ (완료 2026-09-30, `v0.4-p58` 기준, §5.1)
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
- 기준 버전: 쓰는 시점의 dev 최신 태그(초안 `v0.4-p57`: p55 오토 툴 키 A / S / D / F / G, p56 👁 맨 앞, p57 360 뷰 배치, p58 배치 이름 · 미리보기 · 피시아이 빈 뷰 빼기 반영). 설명서 첫머리에 적는다.
- (2026-09-30 사용자 답, §6)
  - 저장소: **`docs/manual/` 장별 파일**, 그림은 `docs/manual/img/`. GitHub는 저장소 Markdown만(Pages / Wiki 없음).
  - Notion: **"공유 페이지_대학원" 아래 새 페이지**(장마다 하위 페이지). 올리기 전에 대상 확인.
  - 영어판: **나중에**. 지금은 한국어만. 나중에 `docs/manual/en/`처럼 옆에 둘 수 있게 장 파일 이름은 영어로.
  - 스크린샷: **공개 이미지**(§5).
  - 주 시나리오: **COLMAP 장면에서 사람 지우기**. Export는 **Spirula Studio가 메인, Brush가 서브**, LichtFeld는 본편에서 다루지 않음
    (D장 학습기 표에만). 360 / 피시아이 / 듀얼 피시아이 변환은 C장 레시피와 D장 참고로.
  - 키 배치: **지금 키(`v0.4-p54`)로 쓰고**, 오토 툴 키(`A` `D` `F`)와 편집 도구 키(`E` `D`)는 "바뀔 수 있음"으로 표시.
    표시는 단축키 표 한 곳에 모으고, 본문은 버튼 / 메뉴 이름을 먼저 쓰고 키를 괄호로.
  - `docs/design/keymap.md`의 "한눈에 보기"를 지금 키에 맞춤(완료, 이 브랜치의 첫 커밋).

## 3. 세부 목차

### 3.0 파일과 공통 형식

```text
docs/manual/
├─ README.md               목차 · 기준 버전 · 읽는 법 (GitHub에서 폴더를 열면 먼저 보임)
├─ 01-getting-started.md   A. 시작하기
├─ 02-workflow.md          B. 추천 워크플로 (따라 하기)
├─ 03-recipes.md           C. 시나리오별 레시피
├─ 04-reference.md         D. 기능 참고 (찾아보기)
├─ 05-appendix.md          E. 부록 (파일 위치 · 문제 해결 · 용어집)
└─ img/                    그림: <장번호>-<이름>.png (예: 02-detect-candidates.png)
```

- 한 장이 약 400줄을 넘으면 절을 파일로 뺀다(예: `04-reference-export.md`). Notion 하위 페이지와 파일이 1:1.
- 워크플로 절 형식: **상황**(한두 줄) → **조작**(번호 목록, 버튼 / 메뉴 이름 먼저, 키는 괄호) → **확인할 것**(화면에서 무엇이 보이면 성공인지) → 그림.
  장 끝에 **자주 하는 실수**.
- 그림: 창 전체 1장(A2)만 번호 달린 설명, 나머지는 필요한 패널만 잘라서. 폭 1200px 이하 PNG. 번호 표시는 그림 위에 빨간 원 숫자.
- 링크: 다른 장은 상대 링크(`02-workflow.md#b4-전파`). Notion으로 옮길 때 페이지 링크로 바꾼다.
- 키가 바뀔 수 있는 곳 표시: 단축키 표(D6)의 해당 줄 끝에 `(바뀔 수 있음)`. 본문에는 표시하지 않는다(키는 괄호 속 보조).

### 3.1 `README.md` — 설명서 첫 페이지

- 한 문단 소개(이 툴이 하는 일) + 기준 버전(`v0.4-p54`, 날짜) + "처음이면 A → B 순서로, 찾아볼 때는 D".
- 장 목록(링크, 한 줄 설명). 저장소 `README.md`의 "사용법" 절은 여기로 가는 링크 + 짧은 요약으로 줄인다(§4.1의 차이는 이때 해소).

### 3.2 A. 시작하기 (`01-getting-started.md`)

| 절 | 내용 | 그림 |
|---|---|---|
| A1 이 툴이 하는 일 | 한 문단: SAM3가 찾고(텍스트), SAM2가 따고 다듬고(클릭), SAM2 비디오가 전파. 결과는 학습기가 읽는 흑백 마스크. 흐름 **찾기 → 고르기 → 다듬기 → 전파 → 내보내기** | — |
| A1 핵심 개념 | 표: Detection · Object · Variant · 포인트 레이어(Original + Layer n, +/−) · Edit Layer · Final Mask(체크된 Object 합) · 마스크 세트(체크 묶음에 이름) · 특수 Object(설정값으로 만드는 Sky / Lens Edge). "Object = 학습에서 **무시할 것**"을 여기서 분명히 | 개념 관계 그림 1장(Object → 프레임마다 Mask = Original ∪ 레이어 + Edit Layer → 체크된 것 합 = Final) — Mermaid 대신 PNG(Notion 호환) |
| A2 화면 구성 | 번호 달린 창 전체 1장: ① 메뉴 바 ② 툴바(Mask Preview · Preview: Final/Object · Brush · Outline ▢px · Show Changes · Solo · Hide Masks) ③ Frame List(ID · 표시 · 이름, 제목줄 `1` `Aa`) ④ Objects(체크 · 이름 · 🔗 · 👁 · 🔒 · Points · × · ···, + New Object from Points, + Special ▾) ⑤ 탭: Prompt / Detection · Batch · Propagation · Logs ⑥ 작업 상태 바(Frame │ Object │ Mode │ 파일 이름) ⑦ 캔버스 ⑧ Frames 줄 ⑨ Properties(Mask · Edit Layer · Special 탭). 패널은 옮기고 띄우고 닫을 수 있고 View → Panels로 다시 켬. F1 = 단축키 | `01-window.png` |
| A2 프레임 표시 | ★ 직접 편집(전파 소스) · ✓ 전파됨 · ⚠ 면적 급변 · ✕ 빈 Mask · – (`1` 켰을 때 그 Object 없음) · ◎ 전파 기준(주황 테두리) · 📌 · ⊘ 제외. 열린 프레임 = 파랑 칠, Shift/Ctrl로 고른 프레임 = 옅은 파랑. 개수 요약 `★ ✓ ⚠ ✕` | `01-frame-marks.png`(Frame List 일부 확대) |
| A3 준비 | 실행(`run.bat` / 포터블의 `SAM Mask Studio.bat`, 설치는 README 링크). File → Settings…: SAM2 checkpoint · SAM3 checkpoint · Sky model (ONNX) · Working max side (px)(기본 1024, VRAM 부족하면 낮춤, Export는 항상 원본 해상도). 기본 경로 `checkpoints/sam2/sam2.1_hiera_tiny.pt`, `checkpoints/sam3/sam3.pt`, `checkpoints/sky/skyseg.onnx`. SAM3 가중치는 Hugging Face 승인 필요. 설정은 `config.local.json` | `01-settings.png` |

### 3.3 B. 추천 워크플로 — COLMAP 장면에서 사람 지우기 (`02-workflow.md`)

**예시 장면**: `plaza/`(`images/` 40장 안팎, `sparse/0/`), 사람 두세 명이 지나감. 공개 이미지로 만든다(§5). 목표: 사람을 학습에서 빼는 `masks/`를
장면에 써서 **Spirula Studio**로 학습, 같은 파일을 **Brush**에도.

첫머리에 한 줄 지도: `B1 열기 → B2 Object 만들기 → B3 다듬기 → B4 전파 → B5 검수 → B6 Export`. B7은 선택.

| 절 | 상황 → 조작 → 확인할 것 | 그림 |
|---|---|---|
| B1 장면 열기 | 상황: COLMAP으로 포즈를 낸 장면. 조작: File → Open Folder… (`Ctrl+O`)로 **장면 루트**(`plaza/`)나 그 `images/`를 고름. 확인: Logs 탭에 모델의 이미지 수 · 카메라 수와 모델 · 3D 점 수, Frame List 40행, 작업 파일 `plaza.sms/`가 **장면 옆**에 생김(자동 저장, `Ctrl+S`도 있음). 모델과 안 맞는 이미지는 ⚠ 로그. 곁가지: 장면에 `masks/`가 이미 있으면 불러올지 묻는 창(C4로 링크). 하위 폴더 `cam0/` `cam1/`도 열림(D5로 링크) | `02-open-log.png` |
| B2 Object 만들기 | 상황: 사람이 잘 보이는 프레임 하나를 기준으로. 조작: (1) 그 프레임에서 Prompt / Detection 탭에 `person` → **Detect** (2) 후보가 라벨별로 나오고 **Select on Image**가 켜짐: 클릭 / 드래그 = 추가, Shift = 토글, Ctrl = 빼기 (3) **Add Each**(사람마다 Object) — 또는 Add as One / Add per Prompt (4) 그 프레임을 기준 ◎로: Frame List에서 **더블클릭**(또는 `Enter`). 확인: Objects에 `person #1` …, 체크박스 켜짐, 프레임에 ★. 다른 방법 상자: **+ New Object from Points** (`N`) 후 클릭 / 박스 · **Batch** 탭(All images / Range / Selected images, **Run on Images**, 라벨마다 Object 하나 = 모든 이미지의 후보 합, Stop = 여기까지 남김 · Cancel = 전부 버림). "그냥 캔버스를 클릭해서는 Object가 생기지 않음" | `02-detect-candidates.png`, `02-objects-added.png` |
| B3 다듬기 | 상황: 후보 마스크가 발이나 가방을 놓침. 조작: 행의 **Points** (`E`)로 편집 시작 → 좌클릭 Positive · 우클릭 Negative · 드래그 Box, 포인트 드래그 = 이동 · 더블클릭 = 삭제. Variant는 Properties → Mask 탭 **Variants (pick one)**. 기존 마스크를 망가뜨리지 않고 조각만 더하려면 **+ Layer**(+ / −로 빼기 레이어, Remove Layer) — 불러오거나 전파된 마스크에서는 첫 클릭이 자동으로 Layer 1(+). 한 번에 조각: `Ctrl+클릭` 더하기 / `Ctrl+우클릭` 빼기. 손질: **Brush** (`D`) 드래그 = 추가 · `Alt`+드래그 = 빼기, 크기 = `Alt`+우클릭 드래그 · `Ctrl+휠`. 오토 툴(Edit Layer 탭 → Auto tools): **Fill Holes**, **Close Gaps**(Max gap) 등 → Fill 모드로 결과 전체 미리보기(마젠타 추가 / 보라 제거) → **Apply & Continue** (`Enter`) / **Apply & Close** (`Shift+Enter`), 나가기 = `Esc`. 확인: 툴바 **Outline** (`O`), **Show Changes** (`R`, 초록 / 빨강). 끝: **Finish Editing** (`Esc`). Edit 중에도 `←` `→`로 다음 프레임의 같은 Object를 이어서 편집 | `02-points-layers.png`(Points 트리 + 캔버스), `02-auto-tool-fill.png` |
| B4 전파 | 상황: 기준 ◎ 프레임의 마스크를 나머지 39장으로. 조작: (1) Objects에서 전파할 Object들을 **선택**(행 클릭, 아무것도 선택 안 하면 체크된 전체) (2) Propagation 탭: Reference(◎) 확인, Scope **All images**(또는 Selection (Frame List) · Range (Start ~ End) · Custom (IDs: 1-4, 35, 23)), Direction **Both** (3) **Propagate Selected Objects**. 진행 중 캔버스에 막 끝난 프레임이 보임. **Stop** = 그 자리에서 멈춤(결과 유지, **Resume**으로 이어서) · **Cancel** = 결과 유지하고 원래 프레임으로, 작업 끝. 결과를 버리려면 `Ctrl+Z`(전파 전체가 한 단계). 확인: Frame List에 ✓ ⚠ ✕, 개수 요약 | `02-propagation-tab.png`, `02-propagating-live.png` |
| B5 검수 | 상황: ⚠(면적 급변) ✕(빈 Mask) 프레임 고치기. 조작: `]` / `[`로 다음 / 이전 문제 프레임 → B3처럼 고침(그 프레임은 ★가 됨) → 필요하면 거기를 기준 ◎로 두고 Scope **Range**로 다시 전파. 보기: **Mask Preview** (`V`, 흑백) · `Z` 누르고 있는 동안만 · `X` = Final ↔ 선택한 Object. **Solo** (`Q`) 선택한 것만 색, **Hide Masks** (`H`) 맨 이미지, 행의 👁 = 그 Object만 숨김(저장 안 됨). Frame List 제목줄 `1` = 선택한 Object 기준 표시(`–` = 그 Object 없음). `,` / `.` = 이전 / 다음 키프레임 ★, `F` = 기준 ◎로. 확인: 요약에 ⚠ ✕가 0이거나 괜찮은 것만 남음 | `02-problem-frames.png`, `02-mask-preview.png` |
| B6 Export (Spirula · Brush) | 조작: File → Export Final Masks… (`Ctrl+E`) → **For** = Spirula Studio → **Mask** = Final Mask — the checked Objects → **Output** = Into the scene → 검사 목록 확인(저장될 파일 수, Mask 없는 이미지, 빈 Mask, ⚠ ✕, 이름 충돌, 카메라 모델, 백업될 파일 수; 문제 이미지는 더블클릭하면 그 이미지로) → **Export**. 결과: 장면의 `masks/<이미지 이름>.png`(예: `0001.jpg.png`, 이미 있는 마스크가 `a.png` 식이면 그 규칙을 따름), 사람 = 검정(무시) · 나머지 = 흰색, 사람이 없는 이미지도 흰색으로 씀. 덮어쓸 파일은 먼저 `masks_backup_<시각>/`으로. 진행 창(단계, n / 전체). Spirula: `images/` 옆 `masks/`를 그대로 쓰고 AI 마스킹을 하지 않음. **Brush**: 같은 파일을 그대로 읽음(For = Brush로 바꿔도 파일은 같고 안내와 검사만 다름). 곁가지: 프레임을 빼고 싶으면 ⊘ + New dataset(C6), Postshot은 흑백 반대(C7) | `02-export-dialog.png`, `02-export-result-folder.png`(탐색기) |
| B7 (선택) 다음 단계 | 360 / 피시아이 장면이면 C8~C10으로. 하늘도 빼려면 C2 | — |
| 자주 하는 실수 | 체크를 끈 Object는 Final Mask에 안 들어감 · 전파는 **선택한** Object만(다른 Object의 마스크는 그대로) · Cancel은 결과를 **남김**(버리려면 `Ctrl+Z`) · Select on Image가 켜져 있으면 Edit에 못 들어감 · ⊘ 제외는 New dataset에서만 반영 · 특수 Object는 Apply 전에는 편집 / 전파 대상이 아님 · 오토 툴 Paint 모드에서 골라 둔 것을 안 쓰면 프레임 이동이 막힘(`Enter` 쓰기 / `Esc` 버리기) | — |

### 3.4 C. 시나리오별 레시피 (`03-recipes.md`)

레시피마다 5~10줄: 언제 · 순서 · 확인. 그림은 필요한 것만.

| 절 | 내용(확인한 기능만) | 그림 |
|---|---|---|
| C1 사람과 삼각대 / 셀카봉 한꺼번에 | Batch 탭에 쉼표로 여러 라벨(예: `person, tripod`) → Run on Images → 라벨마다 Object 하나. 라벨 문구는 SAM3가 찾는지 Detect로 한 프레임에서 먼저 시험 | — |
| C2 하늘 따로 빼기 | + Special ▾ → **Sky Mask** → Special 탭 Frames(All frames / Range / Frames picked in the Frame List) → **Make Sky Masks** → Threshold · Grow / shrink · Refine edges · Only sky touching the top edge(360에 맞음, 피시아이는 끔). 사람과 하늘을 따로 내보내려면 체크를 나눠 **Save Checked as Set…**(예: `sky` → `masks_sky/`), Export의 Mask에서 세트 / Every set. 학습기는 `masks/`만 읽음(폴더 이름을 바꾸거나 Final로) | `03-sky-special.png` |
| C3 피시아이 검은 테두리 | + Special ▾ → **Fisheye Lens Edge** → **Detect from Images** → Radius · Center X / Y 조정. 원 바깥이 마스크(무시) | `03-lens-edge.png` |
| C4 이미 있는 마스크 고치기 | 장면을 처음 열 때 `masks/` `masks_*/`를 Object로 불러올지 묻는 창(폴더마다 건너뛰기 / 흰색 = 대상 / 검정 = 대상), 또는 File → Import Masks from Folder…. 불러온 마스크는 Points로 찍으면 첫 클릭이 Layer 1(+)라 원래 모양이 유지됨. 빼기는 + / −로 빼기 레이어, 또는 `Ctrl+우클릭` | `03-import-masks.png` |
| C5 움직이지 않는 물체를 여러 프레임에 | Frame List에서 Shift / Ctrl-클릭으로 프레임 고르기 → Object 선택 → Edit → Objects → **Copy Mask to Picked Frames**(기준 ◎, 없으면 열린 이미지의 마스크, 기본 Replace, `(Options)…`에서 Add). 되돌리기는 **Clear Masks on Picked Frames**. Frame List 우클릭 메뉴에도 있음, 가운데 클릭 = 고른 것 유지한 채 열기 | — |
| C6 흐린 프레임 빼고 학습 | 프레임 고르기 → Go → **Exclude from Dataset / Include**(⊘) → Export → Output **New dataset:** + 빈 폴더 → `images/`(같은 드라이브면 하드링크) · `sparse/0/`(⊘ 빼고 새로 씀) · 마스크. 원본 장면은 그대로 | — |
| C7 Postshot | For = Postshot → `masks_postshot/`에 사람 = **흰색**, `a.png` 이름. Postshot Image Set의 Image Masks에 끌어다 놓고 Mask Mode = Remove Occluders. 파일 짝 규칙은 Postshot 문서에 없어 확인 필요(프리셋 `verified`와 같게) | — |
| C8 360(ERP) → Pinhole | 360 장면 Export → New dataset → 변환 목록 **Pinhole views**(yaw · pitch 목록, FOV, 크기 auto). 기본 0, 90, 180, 270 × −35, 0, 35. 이미지 · 마스크 · 모델을 함께. Keep the cameras = 360 그대로 | `03-convert-options.png` |
| C9 피시아이 → Pinhole / 360 | 같은 목록의 Pinhole views 또는 **360 (ERP)**. 렌즈가 못 본 곳은 무시로 씀. 지원 카메라 모델 목록은 D5 | — |
| C10 듀얼 피시아이 → 360 → Pinhole | `images/cam0/` `cam1/`(또는 `frames.bin`) → **360 from camera pairs (N moments)** → 만든 데이터셋을 다시 열어(마스크는 Object로 불러옴) Pinhole views로 | — |

### 3.5 D. 기능 참고 (`04-reference.md`)

| 절 | 내용 |
|---|---|
| D1 Frame List · Frames 줄 | 표시와 색(A2 요약을 자세히), `1` · `Aa` · ⌖ · Go to ID, 더블클릭 / `Enter` / 목록 위 `Space` = 기준 ◎, Shift / Ctrl-클릭 = 고르기, 📌 Pin, 가운데 클릭, 우클릭 메뉴(Copy Mask / Copy Mask (Options)… / Clear Masks on Picked Frames / Exclude), 목록 위 `W A S D` / 화살표, 썸네일 캐시 |
| D2 Objects 패널 | 행의 칸(체크 · 이름 · 🔗 N · 👁 · 🔒 · Points · × · ···), Show all Objects, 이름 더블클릭 = Rename, `···` 메뉴(Rename, Duplicate (this image), Duplicate All (every linked mask), Lock / Unlock, Move into / Copy into, Remove mask on this image, Delete), 아래 버튼 **Move A → B** + ⚙(Move / Copy · Add / Replace · 이 이미지 / 모든 이미지), **Merge** + ⚙(Add / Override A / Override B), Duplicate / Duplicate All(`Ctrl+D` / `Ctrl+Shift+D`, 마우스가 패널 위), Delete(확인 없음, `Ctrl+Z`), Lock All / Unlock All(잠금은 삭제만 막음), `↑` `↓` / 목록 위 `W A S D` / 캔버스 위 `W` `S` |
| D3 편집 도구 | Properties → Mask 탭(Variants, Points 트리, + Layer · + / − · Remove Layer, Delete Point · Clear Points · Clear Box), Edit Layer 탭(Brush: Paint · Restore(Add / Subtract / Both), Auto tools 7개: Object Fill · Fill Holes · Remove Specks · Grow · Shrink · Close Gaps + 각 설정값, Mode Fill / Paint, Region Box · Clear, Apply & Close / Apply & Continue, Settings · Layer 접기, Apply Layer / Delete Layer), `Ctrl+I` 인버트 · `Ctrl+Backspace` 비우기(Region 안에서만), SAM2 로딩 중 찍은 포인트는 대기열 |
| D4 여러 프레임 작업 · 전파 | 전파 탭 모든 칸, 선택 Object 규칙, 라이브 뷰, 결과 목록(Objects / Frames (click to open)), Copy / Clear on Picked Frames, ⊘ Exclude |
| D5 COLMAP 장면 · 특수 Object | 장면 인식 조건(`images/` + `sparse/0` 또는 `sparse/`), 하위 폴더 이미지, 마스크 불러오기, Sky 설정값 전부(모델, 캐시), Lens Edge 설정값, Apply, 변환이 받는 카메라 모델(ERP, Pinhole 계열, Fisheye 계열, THIN_PRISM_FISHEYE) |
| D6 Export 창 | 모든 칸: For · Mask(Final / 세트 / Every set, Save Checked as Set… / Delete Set) · Output(Into the scene / New dataset:) · 변환 목록(Keep the cameras / Pinhole views / 360 (ERP) / 360 from camera pairs) · yaw / pitch / FOV / 크기 · Folder · File names · Invert · Also write empty masks…(학습기를 고르면 프리셋 값으로 회색 고정, Custom이면 자유) · 검사 목록 · 진행 창 |
| D7 학습기별 규칙 표 | `src/core/presets.py` 그대로: 학습기 · 폴더 · 이름 · 흑백 · 학습기에서 켤 설정 · 확인한 출처. Brush / LichtFeld Studio / Spirula Studio / Postshot / COLMAP. Brush의 `SPHERICAL` / `EQUIRECTANGULAR` 미확인 |
| D8 단축키 전체표 | F1(`SHORTCUTS`)의 순서와 묶음(File · Edit · Images · View · Detections · On the image)을 한국어로. 바뀔 수 있는 키 표시(§3.0). 원본은 `keymap.md`라고 밝히고 링크 |

### 3.6 E. 부록 (`05-appendix.md`)

- **파일 위치**: 작업 파일 `<폴더>.sms/`(이미지 폴더 · 장면 **옆**, 로더가 재귀로 읽어서 안에 두지 않음; 옛 프로젝트 `images.sms/`는 그대로 씀), 썸네일 `<폴더>.sms/thumbs/`,
  Sky 캐시 `<프로젝트>/special/sky/` · `sky_refined/`, 포인트 레이어 조각 `<key>.L1.png`, 백업 `masks_backup_<시각>/`(하위 폴더 유지), 설정 `config.local.json`, Custom Export 기본 `<폴더>_masks/`.
- **문제 해결**: SAM2 로딩 중(`SAM2 loading… (N waiting)`, 찍은 것은 대기열) · 변환이 카메라 모델을 모를 때("No image here uses a camera this can convert") ·
  장면에 쓸 때의 덮어쓰기와 이름 규칙 · VRAM 부족(Working max side) · Sky 모델이 없을 때(Settings → Sky model) · 아주 어두운 밤하늘은 Sky에서 빠질 수 있음.
- **용어집**: A1 개념 + 3DGS / COLMAP / ERP / Pinhole / 피시아이 / 키프레임 / 기준 ◎ / 하드링크.

## 4. 사실의 출처 (여기서 확인한 것만 쓴다)

| 주제 | 출처 |
|---|---|
| 전체 흐름 · 개념 · 현재 사용법 절 | `README.md`(단, "사용법" 절은 v0.4 후반 기능이 빠져 있음: §4.1) |
| 키와 메뉴 | `docs/design/keymap.md`, `docs/design/menu-design.md`, 앱 F1 표의 원본 `src/app/dialogs.py`의 `SHORTCUTS` |
| 기능의 의도 · 옵션 | `docs/specs/01`~`10` (특히 02 전파, 03 Object, 05 Merge / Copy / Move, 06 COLMAP, 07 Export, 08 변환, 09 특수 Object, 10 포인트 레이어) |
| 무엇이 언제 바뀌었나 | `docs/log/PROGRESS_v0.4.md`(단계별 · 최신이 아래), `docs/log/ideas-log.md` |
| 학습기별 마스크 규칙 | `src/core/presets.py`(각 프리셋의 `note`, `verified`), `docs/specs/07-export-presets.md` |
| 화면 문구 | `src/app/*.py`의 버튼 글자와 툴팁(설명서의 UI 이름은 여기와 글자 하나까지 같게) |

### 4.1 README "사용법"과 지금 코드의 차이 (2026-09-30, `v0.4-p54` 기준 대조)

설명서는 코드 기준으로 쓰고, README "사용법"은 §3.1대로 설명서 링크 + 요약으로 줄이면서 함께 해소한다. (**해소됨**: 초안 브랜치에서 README의 화면 구성 · 사용법 · 주요 단축키 절을 설명서 링크로 바꿈)

- `V` / `X`가 반대로 적혀 있음. 지금: `V` = Mask Preview 켜기 / 끄기, `X` = Final ↔ Object (`p15`).
- 오토 툴 키가 옛 배치: 지금 `A` = 나가기(취소), `Shift+A` = 전체 선택 / 해제, `D` = Paint ↔ Fill, `F` / `Enter` = Apply & Continue, `Shift+Enter` = Apply & Close (`p45`, `p49`).
- "편집 중에는 이미지를 넘길 수 없음" → 지금은 Edit 중 프레임 이동 시 같은 Object를 이어서 편집(`p41`).
- `S` 스크롤 키 → 빠짐, ⌖ 버튼만(`p15`). README 단축키 표의 `S`, `F`의 옛 뜻도.
- `Copy A → B…` → `Move A → B` + ⚙, Merge 옵션은 ⚙(`p17`, `p20`). 삭제는 확인 없이 + 🔒 잠금.
- 전파 `Cancel` = "전부 버리기" → 지금은 결과를 남김(`p38`).
- Export: `<폴더>_masks/`만 설명 → For 프리셋, 마스크 세트, New dataset, 변환이 빠짐(`p24`~`p32`).
- 없는 기능: 포인트 레이어(`p53`), Ctrl+클릭 조각(`p44`), Close Gaps(`p46`), Solo / Hide Masks / 👁(`p18`, `p50`), 특수 Object(`p36`), COLMAP 열기 · 마스크 불러오기(`p23`),
  ⊘(`p28`), Copy / Clear Masks on Picked Frames(`p34`, `p40`), 가운데 클릭(`p40`), Alt+우클릭 드래그(`p42`), `Ctrl+I` / `Ctrl+Backspace`(`p21`), Export 진행 창(`p54`).
- README "화면 구성" 그림의 툴바 줄에 Solo · Hide Masks가 없음, Objects 행에 👁 · 🔒가 없음.

## 5. 위치와 동기화 (확정)

- 저장소: `docs/manual/`(§3.0). `docs/README.md` 정리 원칙 1에 "설명서는 `docs/manual/` 한 폴더(그림은 `docs/manual/img/`)" 예외를 적고, 문서 지도 표에 한 줄 추가.
  README의 "사용법" 절은 설명서로 가는 링크 + 짧은 요약으로 줄임.
- 키 표: D8은 `SHORTCUTS`를 옮긴 것이라 키를 바꾸면 `SHORTCUTS` · `keymap.md` · D8을 같이 고친다(`keymap.md` 머리말의 규칙에 D8 추가).
- Notion: "공유 페이지_대학원" 아래 새 페이지 "SAM Mask Studio 사용 설명서", 장마다 하위 페이지. 원본은 저장소라 Notion에서 고친 내용은 저장소로 되돌림(한 방향 유지).
  그림은 Notion 페이지에 파일로 올림.
- 스크린샷: 앱을 실제 폰트로 띄워 찍음(`QT_QPA_PLATFORM=windows`, 창을 화면 밖에 두고 `grab()`). 창 크기 1600×900 고정, 화면 배율 100%.
- 예시 데이터(공개 이미지): 조건 — 사람이 지나가는 20~60장 시퀀스, 재배포 가능한 라이선스(CC0 / CC BY), COLMAP으로 `sparse/0`을 만들 수 있을 것.
  후보를 찾아 라이선스를 적고 **사용자 확인 후** 사용. 360 / 피시아이 레시피(C3, C8~C10)는 그림을 옵션 창 위주로 하고, 이미지가 필요하면 같은 조건의 공개 360 이미지.
  예시 데이터는 저장소에 넣지 않고 출처만 적는다(그림만 커밋).

### 5.1 Notion 사본 (2026-09-30)

- "공유 페이지_대학원"은 작업 **데이터베이스**라서, 항목 하나로 만들고 장을 하위 페이지로 둠: [SAM Mask Studio 사용 설명서](https://app.notion.com/p/3ebeaf5e52f5816f88d4d404c4a00614)
  (프로젝트 관계는 기존 항목 "구 워크플로우_01"과 같은 프로젝트, 태그 워크플로우 · 팁, 상태 진행 중).
  하위: [A](https://app.notion.com/p/3ebeaf5e52f581d89dc2d59dbbe1055b) · [B](https://app.notion.com/p/3ebeaf5e52f58149821cc980223ea8ac) ·
  [C](https://app.notion.com/p/3ebeaf5e52f581a69870e5446432e485) · [D](https://app.notion.com/p/3ebeaf5e52f581a1923cced93b79670a) · [E](https://app.notion.com/p/3ebeaf5e52f581048508ccf00ed8709a).
- 옮긴 방법: 저장소 Markdown을 Notion Markdown으로 바꿈(표 → `<table>`, 📷 → 회색 callout, 줄바꿈으로 나뉜 문단은 한 줄로, 장 사이 링크 → Notion 페이지, 저장소 파일 링크 → GitHub `dev`).
  장마다 `replace_content`로 통째로 바꾸므로, 저장소를 고친 뒤 같은 방법으로 다시 옮기면 됨. 장 안의 절 앵커 링크는 페이지 링크로 바뀜.
- 그림(2026-10-01): Notion에는 GitHub `dev`의 raw 주소(`raw.githubusercontent.com/.../docs/manual/img/…`)로 넣음(저장소가 공개). 저장소의 기울임 캡션 줄은 빼고 이미지 캡션만.
- 주의: Notion Markdown은 `** + **`, `**+ X**`처럼 공백 앞뒤의 `+`를 목록 기호로 바꿔 `  •`로 저장함(`\+`도 같음). 옮길 때 그 `+`는 전각 `＋`로.

### 5.2 예시 데이터 후보 (2026-09-30 조사, 사용자 확인 전)

| 후보 | 내용 | 라이선스 | 메모 |
|---|---|---|---|
| NeRF On-the-go (ETH CVG, CVPR'24) | 실외 10 + 실내 2 장면, 보행자 · 자전거 · 유모차 등이 지나감 | **확인 안 됨**: 검색 요약은 CC BY 4.0, 다른 출처는 Apache 2.0, 저장소 README에는 데이터 라이선스 문장 없음 | 포즈는 `transforms.json`(COLMAP에서 만든 것). 쓰려면 COLMAP을 다시 돌려 `sparse/0` 필요. 라이선스를 저자에게 확인하거나 README / 논문에서 문장을 찾은 뒤 사용 |
| Tanks and Temples | 여러 실외 장면 | CC BY 4.0이라 적혀 있으나 "비상업 연구용" 조건이 함께 있음 | 사람이 지나가는 장면이 적어 주 시나리오에는 덜 맞음 |
| 직접 촬영(촬영자 본인만 등장) | 공개 장소가 아닌 곳에서 본인이 지나가는 20~60장 | 사용자 소유 | 초상권 · 라이선스 문제가 가장 적음. 사용자 결정 필요 |

## 6. 열린 질문 → 답 (2026-09-30)

1. Notion 위치: **"공유 페이지_대학원" 아래 새 페이지**. GitHub: **저장소 Markdown만**.
2. 저장소 위치: **`docs/manual/` 여러 파일**.
3. 영어판: **나중에**.
4. 예시 데이터: **공개 이미지**(후보는 초안 세션에서 찾아 확인받음).
5. 주 시나리오: **사람 지우기**. Export는 Spirula 메인, Brush 서브, LichtFeld 본편 제외. 360 / 듀얼 피시아이는 레시피로.
6. E / D / A / F: **지금 키로 쓰고 "바뀔 수 있음" 표시**. keymap.md 그림도 고침.

그림(2026-10-01): **SAM2 예제 영상 `bedroom`**(Apache 2.0, 저장소 `vendor/sam2/notebooks/videos/bedroom`, 얼굴 흐림)으로 정함("제일 무난한 것"). 40장 + 그림용 COLMAP 모델.
학습 중이라 GPU를 쓰지 않음: `CUDA_VISIBLE_DEVICES=-1`로 CPU 실행, SAM3는 CUDA 고정이라 CPU에서 안 돌아 Object는 SAM2 박스로 만듦.
남은 그림: `02-detect-candidates`(SAM3, GPU 필요), `03-sky-special`(실외 이미지), `03-lens-edge`(피시아이), `01-concepts`(개념도).

## 7. 주의

- 기능은 계속 바뀌는 중(dev 브랜치, 단계 태그 `v0.4-pN`). 설명서를 쓰는 동안 새 태그가 생기면 `PROGRESS_v0.4.md`의 새 단계를 반영한다.
- 앱 코드는 설명서 작업에서 고치지 않는다. 설명서를 쓰다 발견한 UI 문제는 `docs/backlog/ui-issues.md`의 "사용자 메모"에 적는다.
