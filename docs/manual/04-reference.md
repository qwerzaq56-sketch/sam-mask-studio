# D. 기능 참고

[← C. 레시피](03-recipes.md) · [설명서 목차](README.md) · 다음: [E. 부록 →](05-appendix.md)

패널과 창의 칸을 하나씩 찾아보는 장입니다. 따라 하기는 [B장](02-workflow.md)을 보세요.

- [D1. Frame List · Frames 줄](#d1-frame-list--frames-줄)
- [D2. Objects 패널](#d2-objects-패널)
- [D3. 편집 도구 (Properties)](#d3-편집-도구-properties)
- [D4. 전파와 여러 프레임 작업](#d4-전파와-여러-프레임-작업)
- [D5. COLMAP 장면 · 특수 Object](#d5-colmap-장면--특수-object)
- [D6. Export 창](#d6-export-창)
- [D7. 학습기별 마스크 규칙](#d7-학습기별-마스크-규칙)
- [D8. 단축키 전체표](#d8-단축키-전체표)

---

## D1. Frame List · Frames 줄

두 곳은 같은 목록입니다. Frame List는 이동용, Frames 줄은 썸네일용입니다.

| 조작 | 결과 |
|---|---|
| 클릭 | 그 프레임 열기 |
| `Shift` / `Ctrl`+클릭 | 여러 프레임 고르기(전파 Selection 범위, Copy / Clear on Picked Frames, Exclude의 대상) |
| **가운데 클릭** (더블클릭도) | 그 프레임을 열고 고른 프레임은 그대로 |
| **우클릭** | 고른 프레임은 그대로 두고 메뉴: Copy Mask to Picked Frames · Copy Mask to Picked Frames (Options)… · Clear Masks on Picked Frames · Exclude from Dataset / Include |
| **더블클릭** / `Enter` / 목록 위 `Space` | 그 프레임을 전파 기준 ◎로. 기준에서 다시 하면 해제 |
| 목록 위 `W A ↑ ←` / `S D ↓ →` | 이전 / 다음 프레임(마우스가 목록 위일 때) |
| **Go to ID** 칸 | ID를 쓰고 `Enter` |
| **⌖** | 목록과 줄을 현재 프레임으로 스크롤 |
| 제목줄 **`1`** | 선택한 Object 기준으로만 표시(그 Object가 없으면 `–`). 끄면 전체 기준. 설정에 기억됨 |
| 제목줄 **`Aa`** | 파일 이름을 접어 ID와 표시만(좁은 목록) |

- 표시(★ ✓ ⚠ ✕ – ◎ 📌 ⊘)와 색은 [A2](01-getting-started.md#프레임-표시)에 있습니다.
- 썸네일은 작업 파일 폴더의 `thumbs/`에 캐시됩니다.

## D2. Objects 패널

기본으로 **지금 프레임에 마스크가 있는 Object만** 보입니다. **Show all Objects**를 켜면 전부 보입니다(`N of M shown`).

### 한 줄의 칸

| 칸 | 뜻 |
|---|---|
| **👁** | 캔버스에 보이기 / 숨기기. 보기 설정이라 저장과 Undo에 들어가지 않습니다. 숨겨도 편집 중에는 보입니다 |
| 체크박스 | **Final Mask에 넣기**. 끄면 내보내지 않습니다 |
| 색 · 이름 | 이름을 **더블클릭**하면 Rename |
| **🔗 N** | N개 프레임에 마스크가 있음 |
| **🔒** | 잠금. 잠긴 Object는 Delete / × / Merge로 사라지지 않습니다(편집과 덮어쓰기는 막지 않음). 안 잠긴 줄은 빈 칸, 마우스를 올리면 흐린 🔒 |
| **Points** / **Editing** | SAM2 포인트 편집 시작 / 끝 |
| **×** | 삭제(확인 없음, `Ctrl+Z`로 되돌림) |
| **···** | Rename · Duplicate (this image) · Duplicate All (every linked mask) · Lock / Unlock · Move into ▸ · Copy into ▸ · Remove mask on this image · Delete |

### 아래 버튼 (선택한 Object에 대해, 메뉴 Edit → Objects에도 있음)

| 버튼 | 동작 |
|---|---|
| **+ New Object** (`N`) | 캔버스를 클릭하거나 박스를 드래그해 새 Object |
| **+ Special ▾** | Sky Mask / Fisheye Lens Edge 특수 Object ([D5](#d5-colmap-장면--특수-object)) |
| **Move A → B** | 먼저 고른 A의 **이 프레임** 마스크를 마지막에 고른 B에 **더하고** A에서 뺌. A는 Object로 남음 |
| 옆 **⚙** (Move / Copy Object into Another) | Action: **Move** / **Copy** · B's mask: **Add** / **Replace** · Images: **This image only** / **Every image where A has a mask**. 고른 값은 기억하지 않음 |
| **Merge** | 고른 Object들을 하나로 합침(**Add** = 합집합, 먼저 고른 이름). 원본은 지워짐 |
| 옆 **⚙** (Merge Objects) | 겹치는 프레임에서: **Add** / **Override with A** / **Override with B**(이긴 쪽의 마스크와 이름). 한쪽에만 있는 프레임은 그 마스크 그대로 |
| **Duplicate** (`Ctrl+D`\*) | 이 프레임의 마스크만 복제 |
| **Duplicate All** (`Ctrl+Shift+D`\*) | 모든 프레임의 마스크까지 복제 |
| **Delete** (`Delete`) | 고른 Object 삭제(🔒는 남음) |
| **Lock All** / **Unlock All** | 모두 잠금 / 해제 |

\* 마우스가 Objects 패널 위에 있을 때.

- 모든 조작은 `Ctrl+Z` 한 번으로 되돌아갑니다.
- 이동: `↑` / `↓` = 이 프레임에 마스크가 있는 이전 / 다음 Object(편집도 따라감, 끝에서 순환). 목록 위 `W A S D` / 화살표 = 이전 / 다음 줄(Show all 줄 포함). 캔버스 위 `W` / `S` = 목록 순서로 이전 / 다음.

## D3. 편집 도구 (Properties)

### Mask 탭

| 칸 | 내용 |
|---|---|
| **Variants (pick one)** | SAM2 후보 마스크. 하나를 고릅니다(Original의 후보만) |
| **Points** 트리 | `Original`, `Layer 1 (+)`, `Layer 2 (−)` … 아래에 포인트 / 박스, 줄마다 **×**. 줄을 누르면 그 레이어로(굵게) |
| **+ Layer** · **+ / −** · **Remove Layer** | 레이어 추가 · 더하기 ↔ 빼기 · 지우기 |
| **Delete Point** · **Clear Points** · **Clear Box** | 고른 포인트 · 모든 포인트 · 박스 지우기 |

포인트 레이어 규칙:

- 최종 = (Original ∪ 더하기 레이어들) − 빼기 레이어들, 그 위에 Edit Layer. 레이어 순서는 상관없습니다.
- 레이어는 자기 포인트 / 박스만으로 SAM2를 돌린 조각(가장 점수 높은 후보)입니다. 클릭한 레이어만 다시 계산합니다.
- 캔버스: 지금 레이어의 포인트는 초록(+) / 빨강(−), 다른 레이어의 포인트 · 박스는 작은 회색(눌러지지 않음).
- 자기 포인트 없이 생긴 마스크(불러오기 · 전파 · Apply)는 첫 클릭이 자동으로 **Layer 1 (+)**. 자기 포인트로 만든 프레임은 Original에 찍힙니다.
- Original을 골라 찍으면 기존 마스크를 씨앗으로 SAM2가 다시 그립니다(마스크 모양이 크게 바뀔 수 있음).
- 전파되는 것은 합친 최종 마스크입니다. 전파된 프레임에는 레이어가 없습니다.

### Edit Layer 탭

| 도구 | 동작 | 설정 |
|---|---|---|
| **Paint** (`D`) | 드래그 = 추가, `Alt`+드래그 = 빼기, `Shift`+드래그 = 브러쉬를 켜지 않고 칠하기 | 크기: `Alt`+우클릭 드래그, `Ctrl` / `Shift`+휠 |
| **Restore** | 칠한 곳의 손질을 되돌림 | **Add** / **Subtract** / **Both** |
| **Object Fill** | 물체 경계까지 마스크를 넓힘 | Max grow · Sensitivity |
| **Fill Holes** | 마스크에 둘러싸인 구멍 채우기 | Max size |
| **Remove Specks** | 떨어진 작은 조각 지우기(가장 큰 조각은 남음) | Max size |
| **Grow** / **Shrink** | 전체를 넓히기 / 좁히기 | Amount(공유) |
| **Close Gaps** | 조각 사이 좁은 틈과 안으로 파인 좁은 홈 채우기. 더하기만 함 | Max gap(기본 10 px) |

오토 툴 공통:

- **Mode**: **Fill**(결과 전체, 켜면 항상 이것으로 시작) / **Paint**(칠해서 고르기, `Alt`+드래그 = 해제). Fill ↔ Paint를 오가도 고른 부분은 남습니다.
- **Region Box** · **Clear**: 박스 안에서만 동작(하늘색). 없으면 마스크 전체.
- **Apply & Continue** (`Enter`) · **Apply & Close** (`Shift+Enter`). 나가기 = `Esc` 또는 같은 도구 버튼.
- **Settings**, **Layer** 칸은 제목의 ▾ / ▸로 접고, 접힌 상태는 기억됩니다.
- **Layer** 칸: `Layer: +N px / −M px` · **Apply Layer**(굳히기) · **Delete Layer**(버리기).

### 편집 중 그 밖의 조작

| 조작 | 동작 |
|---|---|
| `Ctrl`+클릭 / `Ctrl`+우클릭 | 그 자리의 조각을 더하기 / 빼기(Edit Layer에 쌓임, 브러쉬가 켜져 있어도) |
| `Ctrl+I` | 이 프레임의 마스크 인버트(Region 안에서만, 있으면) |
| `Ctrl+Backspace` | 이 프레임의 마스크 비우기(Region 안에서만, 있으면) |
| `←` `→` | 다른 프레임에서 같은 Object를 이어서 편집 |
| Objects 목록에서 다른 줄 클릭 | 그 Object 편집으로 넘어감(`Ctrl` / `Shift`+클릭은 선택만, Special Object는 넘어가지 않음) |
| **Finish Editing** (`Esc`) | 편집 끝 |

## D4. 전파와 여러 프레임 작업

### Propagation 탭

| 칸 | 내용 |
|---|---|
| **Reference** | 전파 기준 ◎(Frame List에서 더블클릭). 없으면 지금 프레임 |
| **Scope** | **Selection (Frame List)**(고른 프레임만, 사이는 건너뜀, **📌 Pin**으로 고정) · **Range (Start ~ End)** · **Custom (IDs: 1-4, 35, 23)** · **All images** · **To the next fixed frames**(기준에서 가장 가까운 `★` / `↓` 바로 앞까지, 카메라 폴더 안, Object마다 따로) |
| **Direction** | **Both** · **Forward** · **Backward** |
| **Propagate Selected Objects** | 선택한 Object(기준 ◎에 마스크가 있는 것)만 전파. 선택이 없으면 체크된 전체. 덮어쓰기 경고도 그 Object들만 봄 |
| **Stop** · **Resume** · **Cancel** | 멈춤(결과 유지) · 이어서 · 끝(결과 유지, 원래 프레임으로) |
| **Objects** / **Frames (click to open)** | 진행과 결과. Frames 줄을 누르면 그 프레임으로 |

- 전파 한 번이 Undo 한 단계입니다.
- 결과 표시: `✓` 성공 · `⚠` 면적 급변 · `✕` 빈 마스크.

### 고른 프레임에 대한 작업 (Edit → Objects, Frame List 우클릭)

| 명령 | 동작 |
|---|---|
| **Copy Mask to Picked Frames** | 선택한 Object의 기준 ◎(없으면 열린 프레임) 마스크로 고른 프레임의 마스크를 **바꿈** |
| **Copy Mask to Picked Frames (Options)…** | Their masks there: **Replace** / **Add**(합치기) |
| **Clear Masks on Picked Frames** | 고른 프레임에서 선택한 Object의 마스크를 비움(잠긴 Object도) |
| **Clear a Propagation Run…** | 선택한 Object에서 전파 한 회차가 남긴 마스크를 지움: 회차 · 방향(양쪽 / ◀ / ▶) · 기준 옆 몇 장은 남길지. 지워질 칸을 Timeline에 미리 보여 줌, `Ctrl+Z` 한 번. 고친 프레임(★)은 남음. Timeline 칸 우클릭 = 그 칸부터 바깥쪽으로 |
| Go → **Exclude from Dataset / Include** | 고른 프레임(없으면 지금 프레임)을 ⊘. 새 데이터셋에서만 빠짐 |

- 모두 Undo 한 단계, 편집 중에는 안 됩니다.
- 프레임을 고르다 목록에서 Object 줄이 빠져도, 마지막으로 선택한 Object가 대상입니다(로그에 이름 표시).

### Batch 탭

| 칸 | 내용 |
|---|---|
| 입력칸 | 라벨을 쉼표로: `person, car, tripod` |
| **Images** | **All images** · **Range (Start ~ End)** · **Selected images (Frame List, Ctrl/Shift-click)** |
| **Min score** | 이보다 낮은 SAM3 점수의 후보는 무시 |
| **Run on Images** · **Stop** · **Cancel** | 시작 · 여기까지 남기기 · 전부 버리기 |

## D5. COLMAP 장면 · 특수 Object

### COLMAP 장면

- **장면으로 인식하는 폴더**: `images/`와 `sparse/0/`(또는 `sparse/`)가 있는 폴더, 또는 그 `images/`. bin / txt 모델 모두 읽습니다.
- `images/` 아래 하위 폴더(`cam0/`, `cam1/` …)의 이미지도 열고, 이름은 `cam0/0001.jpg`처럼 폴더를 포함합니다. `images/` 안의 `masks*` 폴더는 이미지로 치지 않습니다.
- **카메라 리그**(모델 없어도): `images/` 바로 아래에 `cam0`, `cam1`처럼 카메라 이름(`cam`/`camera` + 숫자) 폴더가 둘 이상이면, 데이터셋 맨 위 · `images/` · 카메라 폴더 하나 중 무엇을 골라도 모든 카메라를 엽니다. Logs에 카메라별 이미지 · 마스크 수와 빠진 것(⚠)이 남습니다. 카메라 하나만 열어 저장한 작업(`cam0.sms`)이 있으면 어떻게 열지 묻습니다.
  그 밖의 폴더는 바로 아래 이미지만 엽니다.
- 처음 열 때 `masks/`, `masks_*/`를 Object로 불러올지 묻습니다([C4](03-recipes.md#c4-이미-있는-마스크-고치기)).
- 변환(Export → New dataset)이 받는 카메라 모델:
  - 360: `EQUIRECTANGULAR`
  - Pinhole 계열: `SIMPLE_PINHOLE`, `PINHOLE`, `SIMPLE_RADIAL`, `RADIAL`, `OPENCV`(왜곡 포함)
  - Fisheye 계열: `OPENCV_FISHEYE`, `SIMPLE_RADIAL_FISHEYE`, `RADIAL_FISHEYE`, `SIMPLE_FISHEYE`, `FISHEYE`, `THIN_PRISM_FISHEYE`

### 특수 Object (+ Special ▾)

클릭 대신 설정값으로 만드는 Object입니다. 설정을 바꾸면 덮는 프레임 전체가 다시 만들어집니다.

- Properties → **Special** 탭:
  - **Frames**: **All frames** / **Range** / **Frames picked in the Frame List** → **Make … Masks**. 덮는 프레임은 누적됩니다(`Covers N of M frame(s)`).
  - **Settings (applied to every covered frame)**: 움직이면 잠시 뒤 전체에 반영(한 번이 Undo 한 단계).
  - **Apply (make it an ordinary Object)**: 지금 마스크를 가진 보통 Object가 되고 설정은 사라집니다. 이후 손으로 편집 · 전파할 수 있습니다.
- 특수인 동안에는 편집과 전파 대상에서 빠집니다. Final Mask, 마스크 세트, Export, 잠금, 삭제는 보통 Object와 같습니다.

| 종류 | 설정 |
|---|---|
| **Sky Mask** | **Threshold** %(기본 50) · **Grow / shrink** px · **Refine edges**(기본 켬) · **Only sky touching the top edge**. 거의 검은 픽셀은 하늘로 치지 않음 |
| **Fisheye Lens Edge** | **Use**(Training / stitching = 찾은 원 7 % 안, SfM / alignment = 10 % 안: 정합 마스크 전용) · **Radius**(짧은 변 절반 대비 %, 100 = 내접원) · **Center X** / **Center Y** · **Detect from Images**. 원 바깥이 마스크 |

## D6. Export 창

File → **Export Final Masks…** (`Ctrl+E`). 장면이 아니면 **For**, **Output**이 없습니다. 모델 없는 카메라 리그(`images/cam0`, `images/cam1`)는 For = **Camera rig dataset**(`masks/camN/a.jpg.png`, 검정 = 무시), Output = **Into the dataset** · **New dataset**(모델 없이 images/ 링크 + 마스크).

| 칸 | 내용 |
|---|---|
| **For** | 학습기 프리셋: Brush · LichtFeld Studio · Spirula Studio · Postshot · COLMAP (feature extraction) · **Custom (choose below)**. 고른 학습기를 기억합니다. 아래에 학습기 안내 문구 |
| **Output** | **Into the scene**(장면에 마스크만 씀, 덮어쓸 파일은 `masks_backup_<시각>/`으로) · **New dataset:** + 빈 폴더([C6](03-recipes.md#c6-흐린-프레임-빼고-학습)) |
| 변환 목록 (New dataset일 때) | **Keep the cameras** · **Pinhole views**(360이면 배치 목록 COLMAP Overlap · 12 Views / Cubemap · 6 Views / Horizon · 4 Views / Two Rings · 16 Views / Custom, 피시아이면 Fisheye Grid · 9 Views / Fisheye Cross · 5 Views / Fisheye Level · 3 Views / Custom, 아니면 yaw · pitch 목록) · **360 (ERP)** · **360 from camera pairs (N moments)** · **Pinhole views from camera pairs (N moments)**(360 배치 목록). **FOV**, 크기(**auto px**). Pinhole views는 설명 · 뷰 개수 · 겹침과 미리보기 지도, 옆에 같은 뷰를 번호 붙은 가상 카메라로 그린 3D 그림(앞쪽 왼편 위에서, 빨간 원 = 렌즈 끝 / 두 렌즈가 만나는 곳)을 보여 줌. [C8~C10](03-recipes.md#c8-360erp--pinhole) |
| 검사 | 저장될 파일 수, 마스크 없는 이미지, 빈 마스크, `⚠` `✕` 프레임, 파일 이름 충돌, 카메라 모델(학습기가 못 읽을 수 있으면 경고), 백업될 파일 수, 새 데이터셋이면 폴더가 비었는지와 뺄 장수 |
| 문제 이미지 목록 | 더블클릭하면 창을 닫고 그 이미지로. 문제가 없으면 숨김 |
| **What** (마스크 줄) | 한 줄 = 한 폴더. ☑ 이번에 쓸지 · 이름(1줄이면 흐림: 폴더 그대로, 2줄 이상이면 `<폴더>_<이름>/`, 비우면 폴더 그대로) · **Objects** 버튼(**Checked Objects** = Objects 패널에서 체크한 것, 아니면 고르기, Object마다 **⇆ Invert** = 그 Object의 바깥, 마스크가 없는 이미지는 전체) · **Invert**(Objects 검정, 처음 값은 학습기 프리셋) · ✕ 지우기(오른쪽 클릭: Duplicate) · 오른쪽 끝 **미리보기**(지금 프레임, 거기 마스크가 없으면 마스크가 있는 첫 프레임에 이 줄이 쓸 흑백 마스크: Objects · ⇆ · Invert를 바꾸면 바로 바뀜, 마우스를 올리면 프레임 이름). **+ Add mask**. 줄은 장면에 저장(창을 닫을 때, Undo 가능) |
| **Folder** | 내보낼 폴더(학습기를 고르면 정해짐). Custom의 기본은 `<폴더>_masks/` |
| **File names** | `{stem}.png  (frame_001.png)` · `{name}.png  (COLMAP: frame_001.jpg.png)` |
| **Also write empty masks for images without Objects** | Object가 없는 이미지도 파일을 씀 |

- 학습기를 고르면 Folder · File names · 빈 마스크 칸은 프리셋 값(글 + `preset`)으로 정해집니다. Custom이면 자유롭게 고릅니다. 흑백은 마스크 줄마다의 Invert로, 프리셋과 다르면 검사에 ⚠ 한 줄이 뜹니다.
- 마스크 세트는 `<폴더>_<이름>/`(장면이면 `masks_people/`)로 따로 쓰입니다. 학습기는 `masks/`만 읽습니다.
- 마스크는 8bit PNG(0 / 255), **원본 해상도**입니다.
- 진행 창: 지금 단계(마스크 쓰기 / 새 데이터셋 만들기 / 변환 / 이어 붙이기), `n / 전체`, 막대. 중간 취소는 없습니다(반쯤 쓰인 결과가 남지 않게).

## D7. 학습기별 마스크 규칙

Object = 학습에서 **무시할 것**입니다. 프리셋은 이것을 학습기의 흑백 규칙으로 바꿔 씁니다.

| 학습기 (For) | 폴더 | 파일 이름 | 흑백 | 학습기에서 할 일 | 확인한 곳 |
|---|---|---|---|---|---|
| **Spirula Studio** | `masks/` | `0001.jpg.png` (`0001.png`도 읽음) | 검정(0) = 무시 | 없음. `images/` 옆 `masks/`를 그대로 쓰고 AI 마스킹을 하지 않음 | Spirula 소스 |
| **Brush** | `masks/` | `0001.jpg.png` (`0001.png`도 읽음) | 검정 = 무시, 흰색 = 학습 | 없음. `masks/`를 스스로 찾음. 360 카메라(`SPHERICAL`, `EQUIRECTANGULAR`)는 미확인 | Brush README, 소스 |
| **LichtFeld Studio** | `masks/` | `0001.jpg.png` (`0001.png`도 읽음) | 검정 = 무시 | Training → **Mask Mode = Ignore**(기본값 None은 마스크를 안 씀) | LichtFeld 소스 |
| **Postshot** | `masks_postshot/` | `0001.png` | **흰색 = 무시**(반대) | Image Set의 Image Masks에 끌어다 놓고 Mask Mode = Remove Occluders. 파일 짝 규칙은 문서에 없어 확인 필요 | Postshot User Guide |
| **COLMAP (feature extraction)** | `masks/` | 항상 `0001.jpg.png` | 검정 = 특징점을 안 뽑음 | `--ImageReader.mask_path`로 지정 | COLMAP 문서 |

- Spirula · Brush · LichtFeld · COLMAP은 같은 파일을 씁니다. 프리셋끼리는 안내 문구와 검사만 다릅니다.
- 모든 프레임에 파일을 씁니다(무시할 것이 없는 프레임은 전부 흰색. Postshot은 전부 검정).
- 장면에 쓸 때 두 이름을 다 읽는 학습기면 이미 있는 마스크의 이름 규칙을 따르고, 옛 파일은 백업으로 옮겨 이미지마다 한 파일만 남깁니다.

## D8. 단축키 전체표

앱의 **Help → Keyboard Shortcuts** (`F1`)와 같은 내용입니다. 키의 설계 원본은 [`docs/design/keymap.md`](../design/keymap.md)입니다.
`(바뀔 수 있음)`은 사용자 피드백에 따라 배치가 바뀔 수 있는 키입니다.

### File

| 키 | 동작 |
|---|---|
| `Ctrl+O` | 폴더 열기 |
| `Ctrl+S` | 저장(자동 저장도 됨) |
| `Ctrl+E` | Export Final Masks |

모든 명령은 메뉴 바(File · Edit · View · Go · Help)에도 키와 함께 있습니다. 종료는 File → Quit(키 없음).

### Edit

| 키 | 동작 |
|---|---|
| `Ctrl+Z` / `Ctrl+Y` (`Ctrl+Shift+Z`) | Undo / Redo |
| `N` | New Object |
| `E` | 포인트로 편집: 선택한 Object 편집 시작 · 브러쉬 / 오토 툴에서 → 포인트 · 포인트에서 다시 → 편집 끝 (바뀔 수 있음) |
| `D` | 브러쉬로 편집: 편집 시작 · 포인트에서 → 브러쉬 · 브러쉬에서 다시 → 편집 끝 (바뀔 수 있음) |
| `Delete` | 고른 포인트 삭제, 없으면 고른 Object 삭제(확인 없음, 🔒는 남음) |
| `Esc` | 도구 나가기(오토 툴 결과 버림) → 편집 끝 |
| `Ctrl+I` | 편집 중: 이 프레임의 마스크 인버트(Region 안에서만) |
| `Ctrl+Backspace` | 편집 중: 이 프레임의 마스크 비우기(Region 안에서만) |
| `Enter` / `G` | 오토 툴: Apply & Continue (G는 바뀔 수 있음) |
| `Shift+Enter` / `F` | 오토 툴: Apply & Close. `F`는 프레임 목록 위나 오토 툴이 없으면 기준 ◎로 (F는 바뀔 수 있음) |
| `A` | 오토 툴: 결과를 버리고 나가기(포인트로) (바뀔 수 있음) |
| `S` / `D` | 오토 툴: Fill / Paint 모드. Paint에서 `D` 다시 = 전체 선택 / 해제. `S`는 목록 위에서는 이동 키 (바뀔 수 있음) |
| `Shift+A` | 오토 툴: Fill → 전체 선택된 Paint, Paint에서 전체 선택 / 해제 |
| 지금 오토 툴 버튼 다시 | 결과를 버리고 나가기(`Esc`와 같음) |
| `Ctrl+D` (마우스가 Objects 위) | Duplicate(이 프레임의 마스크) |
| `Ctrl+Shift+D` (마우스가 Objects 위) | Duplicate All |

### 이동

| 키 | 동작 |
|---|---|
| `→` / `PgDn`, `←` / `PgUp` | 다음 / 이전 프레임(편집 중이면 그 프레임의 같은 Object) |
| `↑` / `↓` | 이 프레임에 마스크가 있는 이전 / 다음 Object(편집도 따라감) |
| `W A ↑ ←` / `S D ↓ →` (마우스가 Frame List · Frames 줄 위) | 이전 / 다음 프레임 |
| `Space` (마우스가 Frame List · Frames 줄 위) | `Enter`와 같음: 지금 프레임을 기준 ◎로 |
| `W A S D` / 화살표 (마우스가 Objects 목록 위) | 이전 / 다음 Object 줄(Show all 줄 포함, 순환) |
| `W` / `S` (마우스가 캔버스 위) | 이전 / 다음 Object 줄(목록 순서, 순환) |
| ⌖ | 목록을 현재 프레임으로 스크롤(Go to ID: 쓰고 `Enter`) |
| `[` / `]` | 이전 / 다음 `⚠` `✕` 프레임(`1`이 켜져 있으면 `–`도) |
| `,` / `.` | 가장 가까운 이전 / 다음 키프레임 `★`(`1`이 켜져 있으면 그 Object의 것만) |
| `F` | 전파 기준 ◎로 이동 |
| `Enter` | 지금 프레임을 기준 ◎로(다시 = 해제). 오토 툴이 켜져 있으면 오토 툴의 `Enter`가 먼저 |
| 더블클릭 (프레임) | 기준 ◎로, 다시 = 해제 |
| `Shift` / `Ctrl`+클릭 (프레임) | 여러 프레임 고르기(📌 Pin으로 고정) |
| 가운데 클릭 · 더블클릭 (프레임) | 열기, 고른 프레임은 그대로 · 우클릭: 고른 프레임에 할 일 |

### View

| 키 | 동작 |
|---|---|
| `Z` (누르고 있기) | Mask Preview 잠깐 보기 |
| `V` | Mask Preview(흑백) 켜기 / 끄기 |
| `X` | Mask Preview 대상: Final Mask ↔ 선택한 Object |
| `O` | Outline 켜기 / 끄기 |
| `Q` / `` ` `` | Solo: 선택한 Object만 색칠 |
| `H` | Hide Masks: 맨 이미지(짧게 = 켜고 끄기, 누르고 있기 = 누른 동안만) |
| `R` | Show Changes(Edit Layer의 초록 / 빨강) |
| 휠 | 커서 위치로 확대 · 축소 |
| 가운데 드래그 / `Space`+드래그 | 이동 |
| `F1` | 단축키 목록 |

### Select on Image (Detection 후보 고르기)

| 키 | 동작 |
|---|---|
| 클릭 / 드래그 | 커서 아래 후보 / 박스에 걸린 후보 모두 추가 |
| `Shift`+클릭 / 드래그 | 토글 |
| `Ctrl`+클릭 / 드래그 | 빼기 |

### 이미지 위 (편집 중)

| 키 | 동작 |
|---|---|
| 좌클릭 / 우클릭 | Positive / Negative 포인트 |
| 드래그 | Box(Region Box가 켜져 있으면 영역 추가) |
| `Ctrl`+클릭 / `Ctrl`+우클릭 | 그 자리의 조각을 더하기 / 빼기(나머지 마스크는 그대로) |
| 브러쉬로 드래그 | Paint: 추가 · Restore: 손질 되돌리기 · 오토 툴 Paint 모드: 고르기 |
| 포인트 드래그 / 더블클릭 | 포인트 이동 / 삭제 |
| `Alt`+드래그 | Paint: 빼기 · 오토 툴 Paint 모드: 해제 · Region Box: 박스 빼기 |
| `Shift`+드래그 | 브러쉬를 켜지 않고 칠하기 |
| `Alt`+우클릭 드래그 좌우, `Ctrl`+휠 / `Shift`+휠 | 브러쉬 크기 |

---

[← C. 레시피](03-recipes.md) · [설명서 목차](README.md) · 다음: [E. 부록 →](05-appendix.md)
