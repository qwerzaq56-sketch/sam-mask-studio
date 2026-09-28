<h1 align="center">SAM Mask Studio</h1>

<p align="center"><b>SAM3가 찾고, SAM2가 따고 다듬고, SAM2 비디오가 전파하는</b> Object 기반 마스킹 툴<br>
일반 이미지 · 이미지 시퀀스 · 3DGS / COLMAP 데이터셋용 마스크 제작 (Windows, PyQt6)</p>

<p align="center"><i>Object-based masking tool for image sequences and 3DGS / COLMAP datasets:
SAM3 text prompts find, SAM2 clicks cut and refine, SAM2 video propagation carries masks across frames.</i></p>

현재 버전: **v0.4.0** · [`catfield123/sam-mask-gui`](https://github.com/catfield123/sam-mask-gui)(MIT)에서 출발했습니다.

| 문서 | 내용 |
|---|---|
| [`docs/PROGRESS_v0.3.md`](docs/PROGRESS_v0.3.md) | v0.3에서 바뀐 기능 전체 (한국어) |
| [`docs/PROGRESS_v0.4.md`](docs/PROGRESS_v0.4.md) | v0.4 진행 현황: 리뷰 반영, UI 점검 (한국어) |
| [`docs/ideas.md`](docs/ideas.md) · [`docs/ui-issues.md`](docs/ui-issues.md) | 기능 아이디어 백로그 · 작은 UI 문제 목록 |
| [`docs/keymap.md`](docs/keymap.md) | 단축키 전체, 비어 있는 키, 새 단축키 제안 |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 설계 결정, 모듈 구성, 단계별 변경 기록 (영문) |
| [`docs/specs/`](docs/specs) | 원래 기획서와 요청 목록 원문 |

## 핵심 개념

| 개념 | 의미 |
|---|---|
| **Detection** | SAM3가 텍스트 프롬프트로 찾아준 후보. 골라서 Object로 추가하기 전까지는 작업 대상이 아님 |
| **Object** | 작업 대상 하나(예: 사람 한 명). 이미지마다 자기 Mask를 가질 수 있고, 여러 이미지에 걸치면 🔗 표시 |
| **Variant** | SAM2가 낸 Mask 후보. 이미지마다 하나를 선택 |
| **Edit Layer** | 브러쉬·자동 도구로 한 손질. 포인트로 만든 Mask 위에 따로 쌓여서 언제든 지우거나 확정 가능 |
| **Final Mask** | 체크된 Object들의 Mask를 합친 결과. 이것이 Export됨 |

작업 흐름: **찾기 → 고르기 → 다듬기 → 전파 → 내보내기**

## 화면 구성

```text
┌─ Open Save Undo Redo Export │ Mask Preview  Preview: Final Brush │ Outline ▢px │ Show Changes │ Settings ┐
├───────────┬─────────────────────┬───────────────────────────────────────────┬──────────────────────┤
│Frame List │ Objects             │                                           │ Properties           │
│ 1 ★ ◎ a.jpg│ ☑ person #1  🔗 12  │ Frame 1/12 · Object: ■ person #1 · Mode   │  [Mask] [Edit Layer] │
│ 2 ✓   b.jpg│ ☑ car #1            │                Canvas                     │  Variants / Points   │
│ 3 ✓📌 c.jpg│ [+ New Object]       │                                           │  Brush · Auto tools  │
│ …         ├─────────────────────┤                                           │  Settings · Layer    │
│           │ Prompt/Detection    │                                           │                      │
│           │ Batch · Propagation │                                           │                      │
│[Go to][⌖] │ Logs                ├───────────────────────────────────────────┤                      │
│           │                     │ Frames: ▢▢▢▢▢ 썸네일 줄   [Go to][⌖]      │ [Finish Editing]     │
└───────────┴─────────────────────┴───────────────────────────────────────────┴──────────────────────┘
```

- **Frame List**(왼쪽 끝)와 **Frames** 썸네일 줄(아래)은 같은 목록입니다. 현재 이미지, 선택, ◎(전파 기준), 📌(고정)가 항상 똑같이 보입니다.
- 캔버스 위 **작업 상태 바**: 지금 프레임 · 대상 Object(출처) · 모드(Points / Paint / Auto · 도구 (Fill/Paint) / Select on Image / 작업 중 진행)를 한 줄로 보여줍니다.
- 모든 패널은 옮기거나 띄우거나 닫을 수 있고, **View** 메뉴에서 다시 켭니다. 단축키 전체는 **Help → Keyboard Shortcuts (F1)**.

## 사용법

### Object 만들기

1. **SAM3 텍스트 프롬프트** — *Prompt / Detection* 탭에 `person, car, tripod`처럼 쉼표로 여러 개를 입력하고 **Detect**.
   - 후보가 라벨별로 묶여 나오고, **Select on Image**가 켜집니다. 캔버스에서 클릭/드래그 = 추가, Shift = 토글, Ctrl = 해제.
     (드래그 박스에 조금이라도 걸리면 대상. 해제된 후보도 외곽선은 보입니다.)
   - **Add Each**(후보마다 Object) · **Add as One**(전부 머지해서 하나) · **Add per Prompt**(라벨마다 하나).
   - **Preview**로 후보 표시를 켜고 끕니다. Select on Image가 켜져 있는 동안에는 Edit에 들어갈 수 없습니다.
2. **+ New Object from Points** (`N`) — 누른 뒤 캔버스를 클릭하거나 박스를 드래그합니다.
3. **Batch** 탭 — 여러 이미지(전체 / 범위 / 선택한 이미지)에 프롬프트를 한꺼번에 돌려 라벨마다 Object 하나를 만듭니다.
   **Stop**은 여기까지 결과를 남기고, **Cancel**은 전부 버립니다.

그냥 캔버스를 클릭해서는 Object가 생기지 않습니다.

### Object 편집 (포인트)

- 목록의 **[Points]** (`E`)로 Object 하나를 편집 상태로 둡니다. 편집 중에는 이미지를 넘길 수 없습니다(`Esc`로 종료).
- 좌클릭 = Positive, 우클릭 = Negative, 드래그 = Box. 포인트는 **드래그로 이동**, **더블클릭으로 삭제**(또는 선택 후 `Delete`).
- SAM3로 만든 Object도 포인트로 다듬을 수 있습니다(검출 Mask가 SAM2의 초기값).
- Variant는 Properties의 **Mask** 탭이나 Objects 목록의 ●/○ 행에서 고릅니다.

### Edit Layer (Properties → Edit Layer 탭)

- **Paint** (`D`): 드래그 = 추가, `Alt`+드래그 = 빼기. **Restore**: 칠한 곳의 손질을 되돌림(Add / Subtract / Both).
  `Ctrl+휠` = 브러쉬 크기(휠은 줌). `Alt`를 누르면 브러쉬 원이 빨갛게 바뀝니다.
- **Auto tools**: Object Fill(물체 경계까지 넓히기) · Fill Holes · Remove Specks · Grow · Shrink.
  - **Fill** 모드: 결과 전체를 마젠타(추가)/보라(제거)로 미리 봄.
  - **Paint** 모드: 회색 후보를 칠해서 고름(`Alt` = 해제, `A` = 전체 선택/해제). Fill 모드에서 `A`를 누르면 전체 선택 상태로 Paint 모드에 들어감.
  - **Apply & Continue** (`Enter`) = 반영하고 다음 결과 계산 · **Apply & Close** = 반영하고 종료 ·
    그 외(Esc, 다른 도구, 툴 버튼 다시 누르기)는 반영하지 않고 나감.
  - **Region Box**: 드래그로 범위를 정하면 그 안에서만 동작(`Alt`+드래그 = 빼기). 모든 조작은 Undo 가능.
- **Apply Layer**: 손질을 확정해 기본 Mask로 만듦 · **Delete Layer**: 손질을 전부 버림.
- 도구 **Settings**와 **Layer** 섹션은 제목의 ▾ / ▸로 접을 수 있고, 접힌 상태는 기억됩니다.

### Object 관리

- 목록에는 **현재 이미지에 Mask가 있는 Object만** 보입니다. **Show all Objects**로 전부 보기. 여러 이미지에 걸친 Object는 `🔗 N`.
- 체크박스 = Final Mask 포함 여부. 이름 더블클릭 = Rename, `[×]` = 삭제, `[···]` = Duplicate / 이 이미지 Mask만 제거.
- 여러 행을 선택해 **Merge**(처음 선택한 Object 이름을 씀) / Duplicate / Delete.
- `↑` / `↓`: 이 이미지에 Mask가 있는 이전/다음 Object로 이동(편집 중이면 편집 대상도 따라감).

### 프레임 이동

- `←` / `→` (PgUp / PgDn): 이전 / 다음 이미지. 목록의 숫자는 이미지 ID(1부터)입니다.
- `S` 또는 ⌖: 현재 프레임으로 스크롤 · **Go to ID**: ID 입력 + Enter.
- Frame List 제목줄의 `Aa`: 파일 이름을 접어서 ID와 표시만 남김(좁은 목록).
- **프레임 상태 표시**: `★` 여기서 편집 · `✓` 전파됨 · `⚠` 의심(면적 급변) · `✕` 전파 후 빈 Mask. 색으로도 구분됩니다(파랑/기본/주황/빨강).
  - 목록 아래와 Frames 줄 오른쪽에 개수 요약(`★3 ✓40 ⚠2 ✕0`).
  - Frame List 제목줄의 `1`: 선택한 Object 기준으로만 표시, 그 Object의 Mask가 없는 이미지는 `–`(회색).
  - `[` / `]`: 이전 / 다음 문제 이미지(`⚠` `✕`, `1`이 켜져 있으면 `–`도)로 이동.
- `,` / `.`: 가장 가까운 이전 / 다음 키프레임(★, 직접 편집한 = 전파 소스)으로. `F`: 전파 기준(◎, 더블클릭한 프레임)으로.
- 썸네일은 `<폴더>.sms/thumbs/`에 캐시됩니다.

### Propagation (이미지 시퀀스)

- **Reference**: 프레임 목록에서 **더블클릭**한 이미지(◎)가 기준입니다. 지정하지 않으면 현재 이미지.
- **Scope**
  - **Selection**: 프레임 목록에서 Shift/Ctrl로 고른 이미지(사이의 이미지는 건너뜀). **📌 Pin**으로 선택을 고정.
  - **Range**: Start ~ End (ID) · **Custom**: `1-4, 35, 23` · **All images**.
- Direction(Both / Forward / Backward), 체크된 Object만 기준 이미지의 Mask에서 전파합니다.
- **Stop** = 여기까지 남기기 · **Cancel** = 전부 버리기(Stop 후에도 가능) · **Resume** = 멈춘 지점부터 이어서.
- 결과 표시: `✓` 성공 · `⚠` 경고(면적 급변) · `✕` 실패(빈 Mask) · `★` 기준/수동. 전파 전체가 Undo 한 번으로 되돌아갑니다.

### 표시

- **Outline** (`O`) + 두께: 편집 중인 Mask의 흰 외곽선 · **Show Changes** (`R`): 손질한 부분을 초록/빨강으로 표시.
- **Mask Preview**: 흑백 마스크 보기. `X` = 켜고 끄기, `Z`를 누르고 있는 동안 보기(편집은 그대로 가능, 브러쉬 원은 초록).
  - 옆 버튼 **Preview: Final / Object** (`V`): Final Mask(체크된 Object 전체) ↔ 선택한 Object의 Mask만.

### 저장과 Export

- **자동 저장**: 이미지 폴더 **옆** `<폴더>.sms/`에 저장합니다(백그라운드). COLMAP / 3DGS 로더가 이미지 폴더를 재귀적으로 읽기 때문에 폴더 안에는 두지 않습니다.
- **Export** (`Ctrl+E`): Final Mask를 흑백 PNG, **원본 해상도**로 `<폴더>_masks/`에 저장.
  파일 이름 `{stem}.png` 또는 COLMAP 방식 `{name}.png`, 반전, 빈 이미지도 저장 옵션.
  - Export 창 위쪽에 **검사 결과**: 저장될 파일 수, Mask 없는 이미지, 빈 Mask, ⚠ / ✕ 프레임, 파일 이름 충돌.
    문제 이미지 목록에서 더블클릭하면 창을 닫고 그 이미지로 이동합니다.

## 주요 단축키

| 키 | 동작 |
|---|---|
| Ctrl+O / Ctrl+S / Ctrl+E | 폴더 열기 / 저장 / Export |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| N / E / Esc | New Object / Points 편집 시작·종료 / 도구 → 편집 종료 |
| ← → / ↑ ↓ | 이미지 이동 / Object 이동 |
| D | Paint 브러쉬 |
| Enter / A | Auto tool 반영 후 계속 / 전체 선택 |
| X / Z(누르고 있기) / V | Mask Preview 토글 / 잠깐 보기 / Final ↔ 선택 Object |
| O / R | Outline / Show Changes |
| S / [ ] | 현재 프레임으로 스크롤 / 이전·다음 문제 이미지 |
| , . / F | 이전·다음 키프레임(★) / 전파 기준(◎)으로 이동 |
| 휠 / Ctrl+휠 / 가운데·Space 드래그 | 줌 / 브러쉬 크기 / 이동 |
| F1 | 단축키 전체 목록 |

## 설치 (Windows, 개발용)

```powershell
git clone --recurse-submodules https://github.com/qwerzaq56-sketch/sam-mask-studio.git
cd sam-mask-studio
python -m venv .venv                                    # Python 3.12
.venv\Scripts\pip install torch torchvision --index-url https://download.pytorch.org/whl/cu130   # CUDA 빌드를 먼저
.venv\Scripts\pip install -e ".[dev]"                   # PyQt6, OpenCV, …
.venv\Scripts\pip install triton-windows
$env:SAM2_BUILD_CUDA = "0"                              # SAM2 CUDA 확장은 빌드하지 않음 (없어도 동작)
.venv\Scripts\pip install -e vendor/sam2
.venv\Scripts\pip install -e vendor/sam3                # Text Prompt (SAM3)
```

- 체크포인트: `checkpoints/sam2/sam2.1_hiera_tiny.pt`, `checkpoints/sam3/sam3.pt` (앱의 Settings에서 변경 가능).
  SAM3 가중치는 [Hugging Face facebook/sam3](https://huggingface.co/facebook/sam3)에서 접근 승인을 받아야 받을 수 있습니다.
- 설정은 `config.local.json`(git 제외)에 저장되고, 앱 폴더 안의 경로는 상대 경로로 저장됩니다.
- 실행: `run.bat` 또는 `.venv\Scripts\python -m src.main [이미지폴더] [--debug]`
- **Working max side**(기본 1024)는 편집 해상도 상한입니다. VRAM이 부족하면 낮추세요. Export는 항상 원본 해상도입니다.
  SAM2 tiny + SAM3를 함께 쓰면 VRAM을 약 4 GB 사용합니다(8 GB GPU에서 개발·테스트).

## 포터블 빌드

설치 없이 다른 Windows PC에서 쓰는 폴더를 만듭니다(파이썬, 패키지, 모델, VC++ 런타임 포함, 약 7 GB).

```powershell
.venv\Scripts\python.exe tools\make_portable.py <출력 폴더> [--force]
```

대상 PC는 Windows 10/11 64비트면 되고, GPU로 돌리려면 NVIDIA + CUDA 13 지원 드라이버가 필요합니다(없으면 CPU로 동작).
결과 폴더의 `SAM Mask Studio.bat`로 실행합니다. SAM3 가중치는 사용 조건상 개인 PC 간 사용 용도로만 옮기세요.

## 개발

```powershell
.venv\Scripts\python -m pytest tests -q   # 모델/GPU 없이 동작 (GUI 테스트는 offscreen Qt + FakeEngine)
.venv\Scripts\ruff check src tests
```

```text
src/core/     Project · Object · Variant · Edit Layer · undo/redo, 저장/Export, 전파 계획, Mask 정리 도구 (Qt·torch 없음)
src/engine/   SAM2/SAM3 추론, 배치 디텍션, SAM2 video propagation, 이미지 I/O
src/app/      PyQt6 GUI — session.py(Qt 없는 편집 로직), canvas, 각 패널, main_window
src/sam2/ src/sam3/ src/utils/   upstream 모델 래퍼와 import stub
tools/        포터블 빌드
vendor/       SAM2 / SAM3 (git submodule)
```

변경은 단계별 브랜치로 만들어 `dev`에 `--no-ff`로 병합하고 `v0.4-pN` 같은 단계 태그를 붙입니다. 릴리스는 `main`과 `vX.Y.Z` 태그입니다.

## License

MIT — [LICENSE](LICENSE). SAM2(`vendor/sam2`, Apache 2.0)와 SAM3(`vendor/sam3`, SAM License)는 각자의 라이선스를 따르며,
모델 가중치는 이 저장소에 포함되어 있지 않습니다.
