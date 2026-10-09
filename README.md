<h1 align="center">SAM Mask Studio</h1>

<p align="center"><b>SAM3가 찾고, SAM2가 따고 다듬고, SAM2 비디오가 전파하는</b> Object 기반 마스킹 툴<br>
일반 이미지 · 이미지 시퀀스 · 3DGS / COLMAP 데이터셋용 마스크 제작 (Windows, PyQt6)</p>

<p align="center"><i>Object-based masking tool for image sequences and 3DGS / COLMAP datasets:
SAM3 text prompts find, SAM2 clicks cut and refine, SAM2 video propagation carries masks across frames.</i></p>

현재 버전: **v0.6.1** · [`catfield123/sam-mask-gui`](https://github.com/catfield123/sam-mask-gui)(MIT)에서 출발했습니다.

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

### 명령줄 (창 없이, 배치용)

```
python -m src.cli sky <이미지 폴더> --out <마스크 폴더> [--recursive] [--color-preset "<By Color 프리셋>" [--cpu]]
python -m src.cli lens <이미지 폴더> --out <마스크 폴더> [--recursive] [--and-with <사람 마스크 폴더>]
python -m src.cli person <이미지 폴더> --out <사람 마스크 폴더> [--recursive]
```

- `sky`: 폴더의 모든 이미지에 하늘 마스크(흰색 = 하늘, `--invert`면 검정). 원본 해상도로, 경계는 원본 이미지에서 다시 판정(Export의 "Sky edges at full resolution"과 같음).
- `sky --color-preset`: 원본 크기 하늘 마스크에 By Color를 앱의 오토 툴과 똑같이 한 번 적용. 앱 By Color 패널에 저장한 프리셋 이름(`config.local.json`) 또는 그 설정을 담은 `.json` 파일. 마스킹 프리셋의 `sky.color`에 넣어도 됨, `--no-color`로 끔. 0022 정답 12장: 프리셋 `sky 8 colors + bright 205`로 넘침 12.8 % → 0.95 %(이 프리셋으로 정답을 만들었으니 낙관적일 수 있음). 함께 띠 밖 나무 끝(띠 30 px 밖에서 하늘로 칠해진 거친·하늘색 아닌 잎)도 뺌(p110, 넘침 0.95 → 0.85 %), `--no-tree-tips`로 끔. 그 뒤 **SAM2**가 프리셋에 없는 색이라 빠진 하늘 덩어리를 되살림(p111, 원본 해상도 타일마다 확실한 하늘 한가운데를 Ctrl+클릭하듯): 놓침 1.13 → 0.34 %, 넘침 0.85 → 0.93 %, 경계 F@2 0.885 → 0.937. 이 단계는 끌 수 없고 **GPU를 씀**(sam2.1 tiny, 약 0.6 GB, 빈 메모리 1 GB 미만이면 시작 안 함 → 학습·뷰어를 끄고 돌릴 것). `--cpu`로 CPU에서 돌리면 약 10배 느림.
- 파일 이름 `00011.jpg.png`(`--names stem`이면 `00011.png`), `cam0/` 같은 하위 폴더 유지(`--recursive`).
- `--out`에 이미 있는 마스크는 바꾸지 않음. 이어서 하려면 `--skip-existing`, 바꾸려면 `--overwrite`.
- 프리셋 없이는 GPU를 쓰지 않음(CPU). 3840² 어안 한 장에 약 2.6초. `--color-preset`과 함께면 SAM2 때문에 GPU를 쓰고 한 장에 약 7.5초(RTX 2060 SUPER). `--report run.json`으로 장별 하늘 비율과 시간.
- `lens`: 피시아이 원 밖을 검정(무시), 안을 흰색으로. 원은 카메라 폴더(`cam0/`, `cam1/`)마다 16장에서 찾고, 렌즈 테두리의 번진 띠를 덮도록 반경의 2%만큼 안으로 당김(`--margin`). `--radius`/`--cx`/`--cy`로 직접 지정, `--and-with`로 사람 마스크(흰색 = 학습)와 곱해서 `masks/` 한 폴더로. 188장에 18초.
- `person`: 사람과 들고 있는 것(셀카봉, 가방)을 검정으로(`masks/` 규칙). SAM3 글자 프롬프트 "person", "black pole"("selfie stick"보다 훨씬 잘 잡힘), 사람·봉에 닿은 "bag". 1024 px에서 2 px 넓힘(`--grow`). **GPU 사용**(약 4.2 GB, 장당 약 1.9초): 빈 GPU 메모리가 5 GB 미만이면 시작하지 않음(학습 중 보호, `--gpu-anyway`로 무시).
- 장면의 `masks/` 한 번에: `person --out people` → `lens --and-with people --out masks`.
- 그 밖의 옵션: `python -m src.cli <sky|lens|person> --help`.

#### 마스킹 프리셋 (배치 툴용)

```
python -m src.cli run <이미지 폴더> --preset <이름 또는 .json> --out <장면 폴더> [--recursive]
python -m src.cli probe <이미지 폴더> --out <시험 폴더> --preset <이름> [--also "selfie stick;tripod"] [--reference <손으로 확인한 masks>] [--inside 90]
python -m src.cli preset list | show <이름> | save <새 이름> --from <이름> [--labels ...]
```

- 프리셋 = 어떤 단계(사람·렌즈·하늘)를 어떤 설정으로 할지. **SAM3 프롬프트가 핵심**: 0022에서 맞은 "black pole"이 다른 장비·장면에서도 맞는다는 보장은 없음. 그래서 프리셋마다 무엇으로 확인했는지(`checked_on`)를 적어 둠.
- 내장: `osmo360-selfie-stick`(0022에서 확인), `people-only`(출발점, 확인 안 됨). 내 프리셋은 `mask_presets/`(또는 환경 변수 `SMS_MASK_PRESETS` 폴더), 어떤 `.json`이든 경로로 지정 가능.
- `run`: 프리셋의 단계를 장면 폴더에 한 번에. `masks/`(사람 → 렌즈 곱, 사람만은 `people_masks/`에 남김), `sky_masks/`. 셋 중 어느 폴더에든 마스크가 이미 있으면 **아무것도 하지 않고** 멈춤.
- `probe`: 전체를 돌리기 전에 카메라 폴더마다 몇 장(`--frames`)에서 프롬프트를 시험. 프롬프트별로 몇 장에서 잡혔는지, 점수, 면적, 기준 마스크가 있으면 덮은 비율·넘친 비율과 IoU. 대조 시트(`sheet_01.jpg`)에 사람 마스크는 빨강, 프롬프트마다 다른 색 윤곽, 기준은 초록. `--also`는 마스크에 넣지 않고 재기만 하는 후보. `--save-preset 이름`으로 시험한 설정을 저장.
- `person`/`lens`/`sky`도 `--preset`을 받고, 따로 준 옵션이 프리셋 값을 바꿈.
- 창에서는 **File > Batch Masking with Presets…**: 프리셋 고르기, 프롬프트 고치기, Try Prompts(대조 시트를 창에 표시), Save as Preset, Run on the Folder, Copy Command(배치 툴용 명령). 같은 명령줄을 별도 프로세스로 부르므로 결과가 배치와 같음.

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
  Sky 특수 Object의 Finish(By Color + SAM2, `cli sky --color-preset`과 같은 결과)는 `checkpoints/sam2/sam2.1_hiera_tiny.pt`와 GPU 빈 메모리 1 GB를 씁니다(없으면 CPU, 약 10배 느림).
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
.venv\Scripts\python.exe tools\make_portable.py <출력 폴더> [--force] [--ref v0.6.1] [--zip] [--split]
```

`--ref`는 묶을 태그(기본 HEAD), `--zip`은 폴더 옆에 `<폴더 이름>-<버전>-portable.zip`도 만듭니다(모델 가중치는 압축 없이 담아 빠름).

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
