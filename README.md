<h1 align="center">SAM Mask Studio</h1>

<p align="center"><b>SAM3가 찾고, SAM2가 따고 다듬고, SAM2 비디오가 전파하는</b> Object 기반 마스킹 툴<br>
일반 이미지 · 이미지 시퀀스 · 3DGS / COLMAP 데이터셋용 마스크 제작 (Windows, PyQt6)</p>

<p align="center"><i>Object-based masking tool for image sequences and 3DGS / COLMAP datasets:
SAM3 text prompts find, SAM2 clicks cut and refine, SAM2 video propagation carries masks across frames.</i></p>

현재 버전: **v0.5.1** · [`catfield123/sam-mask-gui`](https://github.com/catfield123/sam-mask-gui)(MIT)에서 출발했습니다.

문서 지도와 정리 원칙: [`docs/README.md`](docs/README.md)

| 폴더 | 내용 |
|---|---|
| [`docs/manual/`](docs/manual/README.md) | **사용 설명서**: 시작하기 · 추천 워크플로 · 레시피 · 기능 참고 · 부록 |
| [`docs/design/`](docs/design) | 지키는 기준: [UX 원칙](docs/design/ux-principles.md) · [메뉴 설계](docs/design/menu-design.md) · [키맵](docs/design/keymap.md) |
| [`docs/specs/`](docs/specs) | 기능 기획서(번호순)와 요청 원문 |
| [`docs/backlog/`](docs/backlog) | 할 일: [아이디어](docs/backlog/ideas.md) · [UI 문제](docs/backlog/ui-issues.md) |
| [`docs/log/`](docs/log) | 끝난 것: [v0.4 진행](docs/log/PROGRESS_v0.4.md) · [v0.3 진행](docs/log/PROGRESS_v0.3.md) · [끝난 아이디어](docs/log/ideas-log.md) |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | 설계 결정, 모듈 구성, 단계별 변경 기록 (영문) |

## 핵심 개념

| 개념 | 의미 |
|---|---|
| **Detection** | SAM3가 텍스트 프롬프트로 찾아준 후보. 골라서 Object로 추가하기 전까지는 작업 대상이 아님 |
| **Object** | 작업 대상 하나(예: 사람 한 명). 이미지마다 자기 Mask를 가질 수 있고, 여러 이미지에 걸치면 🔗 표시 |
| **Variant** | SAM2가 낸 Mask 후보. 이미지마다 하나를 선택 |
| **Edit Layer** | 브러쉬·자동 도구로 한 손질. 포인트로 만든 Mask 위에 따로 쌓여서 언제든 지우거나 확정 가능 |
| **Final Mask** | 체크된 Object들의 Mask를 합친 결과. 이것이 Export됨 |

작업 흐름: **찾기 → 고르기 → 다듬기 → 전파 → 내보내기**. 포인트 레이어, 마스크 세트, 특수 Object는 [설명서 A1](docs/manual/01-getting-started.md#핵심-개념).

## 사용법

**사용 설명서: [`docs/manual/`](docs/manual/README.md)** (기준 `v0.5.0`)

| 장 | 내용 |
|---|---|
| [A. 시작하기](docs/manual/01-getting-started.md) | 핵심 개념, 화면 구성, 준비(체크포인트, Settings) |
| [B. 추천 워크플로](docs/manual/02-workflow.md) | COLMAP 장면에서 사람 지우기 → Spirula / Brush용 Export, 따라 하기 |
| [C. 레시피](docs/manual/03-recipes.md) | 하늘, 피시아이 테두리, 마스크 고치기, 프레임 빼기, Postshot, 360 · 피시아이 변환 |
| [D. 기능 참고](docs/manual/04-reference.md) | 패널과 창의 모든 칸, 학습기별 규칙, [단축키 전체표](docs/manual/04-reference.md#d8-단축키-전체표) |
| [E. 부록](docs/manual/05-appendix.md) | 파일 위치, 문제 해결, 용어집 |

짧게: File → **Open Folder…** (`Ctrl+O`)로 이미지 폴더나 COLMAP 장면을 열고 → **Prompt / Detection**(SAM3 글자) 또는 **+ New Object from Points** (`N`, SAM2 클릭)로
Object를 만들고 → **Points** (`E`) · **Brush** (`D`) · 오토 툴로 다듬고 → **Propagation** 탭에서 전파하고 → File → **Export Final Masks…** (`Ctrl+E`)에서
학습기(**For**)를 골라 내보냅니다. 모든 명령은 메뉴 바에 키와 함께 있고, 앱에서 `F1`을 누르면 단축키 전체가 나옵니다.

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
  Sky 특수 Object는 `checkpoints/sky/skyseg.onnx`([Hugging Face JianyuanWang/skyseg](https://huggingface.co/JianyuanWang/skyseg), 약 170 MB)를 씁니다.
  SAM3 가중치는 [Hugging Face facebook/sam3](https://huggingface.co/facebook/sam3)에서 접근 승인을 받아야 받을 수 있습니다.
- 설정은 `config.local.json`(git 제외)에 저장되고, 앱 폴더 안의 경로는 상대 경로로 저장됩니다.
- 실행: `run.bat` 또는 `.venv\Scripts\python -m src.main [이미지폴더] [--debug]`
- **Working max side**(기본 1024)는 편집 해상도 상한입니다. VRAM이 부족하면 낮추세요. Export는 항상 원본 해상도입니다.
  SAM2 tiny + SAM3를 함께 쓰면 VRAM을 약 4 GB 사용합니다(8 GB GPU에서 개발·테스트).

## 포터블 빌드

설치 없이 다른 Windows PC에서 쓰는 폴더를 만듭니다(파이썬, 패키지, 모델, VC++ 런타임 포함, 약 7 GB).

> **받아서 쓰기**: v0.5.1 포터블 zip은 [Google Drive 폴더](https://drive.google.com/drive/folders/19-ovaNTtmeQ8GgGuD6sL7aspJ6b1hjiJ)에 있습니다.
> SAM3 가중치가 들어 있어 공개하지 않으니, 링크에서 **액세스 요청**을 보내 주세요(승인 후 다운로드, 개인 사용 목적만).

```powershell
.venv\Scripts\python.exe tools\make_portable.py <출력 폴더> [--force]
```

대상 PC는 Windows 10/11 64비트면 되고, GPU로 돌리려면 NVIDIA + CUDA 13 지원 드라이버가 필요합니다. GPU가 없으면 SAM2(클릭, 전파)와 Sky는 CPU로 동작하지만, **SAM3 글자 검출(Detect / Batch)은 NVIDIA GPU가 있어야** 합니다.
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
