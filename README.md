<h1 align="center">SAM Mask Studio</h1>

<p align="center"><b>SAM3가 찾고, SAM2가 따고 다듬는</b> Object 기반 마스킹 툴<br>
일반 이미지 · 이미지 시퀀스 · 3DGS / COLMAP 데이터셋용 마스크 제작</p>

[`catfield123/sam-mask-gui`](https://github.com/catfield123/sam-mask-gui)(MIT)를 기반으로 만들었습니다.
기획서 원문은 [`docs/specs/`](docs/specs)에, 설계 결정과 진행 상태는 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)에 있습니다.

## 핵심 개념

| 개념 | 의미 |
|---|---|
| **Detection** | SAM3가 찾아준 후보 (아직 작업 대상이 아님) |
| **Object** | 내가 작업할 대상. 이미지마다 자기 Mask를 가짐 |
| **Variant** | 한 Object의 Mask 후보. Object마다 하나를 선택 |
| **Final Mask** | 체크된 Object들의 Mask를 합친 결과 |

작업 흐름: **찾기 → 선택 → 수정 → 조합 → 저장**

## 화면 구성

```text
┌────────────────────────────────────────────────────────────────────┐
│ Open | Save | Undo | Redo | Export | Preview Final Mask | ERP(예정) │
├──────────────┬──────────────────────────────┬──────────────────────┤
│ Objects      │                              │ Properties           │
│ ☑ Person #1  │                              │ 선택/편집 중인 Object │
│   ● Variant 1│         Image Canvas         │ Variants (썸네일)     │
│   ○ Variant 2│                              │ Positive / Negative  │
│ [+ New Object│                              │ Points               │
│  from Points]│                              │                      │
│ Images ★✓⚠✕ │                              │                      │
├──────────────┴──────────────────────────────┴──────────────────────┤
│ Prompt / Detection | Propagation | Logs                            │
└────────────────────────────────────────────────────────────────────┘
```

## 사용법

### Object 만들기 (두 가지 방법뿐)

1. **SAM3 Text Prompt** — 하단 *Prompt / Detection* 탭에 `person` 등을 입력하고 **Detect**를 누릅니다.
   후보가 캔버스에 표시되면 필요한 것만 체크한 뒤 **Add Selected as Objects**를 누릅니다.
   (간판 속 사람처럼 잘못 검출된 후보는 체크를 풀면 됩니다.)
2. **+ New Object from Points** (`N`) — 버튼을 누른 뒤 캔버스를 클릭하거나 박스를 드래그합니다.

캔버스를 그냥 클릭해서는 Object가 생기지 않습니다.

### Object 편집

- 목록에서 **[Edit]** (`E`)를 누르면 그 Object 하나만 편집 상태가 됩니다 (캔버스 상단에 `Editing: 이름` 표시).
- 좌클릭은 Positive Point, 우클릭은 Negative Point, 드래그는 Box입니다.
- 점을 클릭하면 선택되고, **Delete**를 누르면 그 점만 지워진 뒤 SAM2가 나머지 점으로 다시 추론합니다.
- **Shift+드래그**는 브러시로 칠하기, **Ctrl+Shift+드래그**는 지우기, **Shift+휠**은 브러시 크기 조절입니다.
- **Clear Points**와 **Finish Editing**(`Esc`)을 쓸 수 있습니다.
- SAM3로 만든 Object도 [Edit]로 SAM2 보정이 됩니다. 검출된 Mask를 SAM2의 초기값으로 사용합니다.
- Variant는 Objects 목록의 ●/○ 행이나 Properties 썸네일에서 고릅니다.

### Object 관리

- **체크박스**는 Final Mask에 포함할지 여부입니다. Object를 지우지 않고도 결과에서 뺄 수 있습니다.
- 이름을 더블클릭하면 **Rename**, `[×]`는 **Delete**(확인창이 뜨고 모든 이미지의 Mask가 함께 삭제), `[···]` 메뉴에는 Rename / Duplicate / 이 이미지의 Mask만 제거 / Delete가 있습니다.
- 행을 Ctrl/Shift-클릭으로 여러 개 선택하면 **Merge / Duplicate / Delete**를 한 번에 적용할 수 있습니다.
  - Merge는 각 이미지에서 존재하는 Mask끼리 Union하여 새 Object 하나를 만듭니다. 이후에도 Edit와 Propagation이 가능합니다.

### Propagation (이미지 시퀀스)

- **Current Image가 기준점**이고, Start / End는 전파 범위의 경계일 뿐입니다. Current는 반드시 범위 안에 있어야 합니다.
- Direction은 Both / Forward(Current→End) / Backward(Current→Start) 중에서 고릅니다. Current 자체는 다시 처리하지 않습니다.
- 체크된 Object만, 각자 Current에서 **선택된 Variant**를 기준으로 전파합니다.
- 이미 Mask가 있는 이미지는 목록을 보여주고 덮어쓸지 확인합니다.
- 방향별 진행률, Object별 상태, 프레임별 결과를 표시합니다: `✓` 성공 · `⚠` 경고(면적 급변) · `✕` 실패(빈 Mask) · `★` 기준/수동 수정.
  프레임을 클릭하면 그 이미지로 이동합니다. 거기서 수정한 뒤 다시 전파하면 됩니다.
- 전파 전체가 **Undo 한 번**으로 되돌아갑니다.

### 저장과 Export

- **자동 저장**: 이미지 폴더 **옆**의 `<폴더>.sms/`에 저장합니다. COLMAP/3DGS 로더가 이미지 폴더를 재귀적으로 읽기 때문에 폴더 안에는 두지 않습니다.
  폴더를 다시 열면 Object, 이름, 점, 상태가 복구됩니다. 선택되지 않은 Variant는 저장하지 않습니다.
- **Export** (`Ctrl+E`): Final Mask를 흑백 PNG로 **원본 해상도**에 맞춰 저장합니다. 기본 위치는 `<폴더>_masks/`이고 다음 옵션이 있습니다.
  - 파일 이름: `{stem}.png` 또는 COLMAP 방식 `{name}.png`
  - 반전 (객체 = 검정)
  - Object가 없는 이미지도 빈 Mask로 저장
- **Preview Final Mask** (`F`)로 Final Mask를 켜 두고 볼 수 있고, `Alt`를 누르고 있는 동안만 잠깐 볼 수도 있습니다.

### 단축키

| 키 | 동작 |
|---|---|
| Ctrl+O / Ctrl+S / Ctrl+E | 폴더 열기 / 저장 / Export |
| Ctrl+Z / Ctrl+Y | Undo / Redo |
| N | + New Object from Points |
| E | 선택한 Object Edit / 편집 종료 |
| Esc | Finish Editing / New 취소 |
| Delete | 선택한 점 삭제 (편집 중), 아니면 선택한 Object 삭제 |
| ← → (A D, PgUp PgDn) | 이전 / 다음 이미지 |
| F, Alt(누르고 있기) | Final Mask 보기 |
| 휠 / 가운데 버튼 드래그 / Space+드래그 | 확대·축소 / 이동 |

## 설치 (Windows, 로컬)

```powershell
python -m venv .venv                      # Python 3.12
.venv\Scripts\pip install -e .            # PyQt6, OpenCV, ...
.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cu130
.venv\Scripts\pip install -e vendor/sam2
.venv\Scripts\pip install -e vendor/sam3  # 선택: Text Prompt
```

체크포인트는 기본으로 `checkpoints/sam2/sam2.1_hiera_tiny.pt`, `checkpoints/sam3/sam3.pt` 경로에서 찾습니다. 경로는 앱의 Settings에서 바꿀 수 있습니다.
SAM3 가중치는 [Hugging Face facebook/sam3](https://huggingface.co/facebook/sam3)에서 접근 승인을 받아야 받을 수 있습니다.
설정은 `config.local.json`에 저장되며 git에는 포함되지 않습니다.

실행:

```powershell
run.bat                     # 또는: .venv\Scripts\python -m src.main [이미지폴더] [--debug]
```

**Working max side**(기본 1024)는 편집할 때의 해상도 상한입니다. VRAM이 부족하면 낮추세요. Export는 항상 원본 해상도로 저장됩니다.
SAM2 tiny와 SAM3를 함께 쓰면 VRAM을 약 4 GB 사용합니다.

## 개발

```bash
pip install -e ".[dev]"
python -m pytest tests -q       # 모델/GPU 없이 동작 (GUI 테스트는 QT_QPA_PLATFORM=offscreen + FakeEngine)
ruff check src tests
```

모듈 구성:

```text
src/core/     Project · Object · Variant · undo/redo, 저장/Export, Propagation 계획 (Qt·torch 없음)
src/engine/   SAM2/SAM3 추론, SAM2 video propagation, 이미지 I/O
src/app/      PyQt6 GUI — session.py(Qt 없는 편집 로직), canvas, panels, main_window
src/sam2/ src/sam3/ src/utils/   upstream 모델 래퍼와 import stub
```

## License

MIT — [LICENSE](LICENSE). SAM2(`vendor/sam2`, Apache 2.0)와 SAM3(`vendor/sam3`, SAM License)는 각자의 라이선스를 따릅니다.
