# SAM Mask Studio v0.4 진행 현황

**v0.4.0 릴리스 (2026-09-29):** 아래 1~7단계(`v0.4-p1` ~ `v0.4-p7.1`)가 `main`에 병합되고 `v0.4.0` 태그가 붙었습니다. 안정판 실행기와 포터블(`H:\Dev\Masking\dist\SAMMaskStudio`)도 v0.4.0입니다.

외부(GPT) UX 리뷰 중 코드와 대조해서 타당했던 항목만 반영합니다. v0.3 기록: [`PROGRESS_v0.3.md`](PROGRESS_v0.3.md)

적어두는 곳: 기능 아이디어 [`ideas.md`](../backlog/ideas.md) · 작은 UI 문제 [`ui-issues.md`](../backlog/ui-issues.md)

- 브랜치 `dev`에서 단계별 브랜치(`feat/v04-pN-…`)로 작업 → `--no-ff` 병합 → 태그 `v0.4-pN`.
- 되돌리기: 단계 전체 `git revert -m 1 <병합 커밋>`
- 실행: `SAM Mask Studio (dev).bat` = 최신 dev, `SAM Mask Studio.bat` = 안정판 v0.4.0 (이전 안정판은 태그 `v0.3.0`)

## 완료

### 1단계 · 작업 상태 바 + 이름 정리 (`v0.4-p1`)
- **작업 상태 바**: 캔버스 위 한 줄에 `Frame 5 / 123 · 파일명 │ Object: ■ sky #1 (SAM3) │ Mode: …`.
  - Mode: `View` / `Points` / `Paint` / `Restore` / `Auto · Fill Holes (Fill|Paint)` / `+ Region Box` / `Select on Image` / `New Object` / 작업 중이면 그 내용(`Propagating…` 등).
  - Object: Properties에 보이는 Object(편집 중이면 그것, 아니면 하나만 선택된 것). 여럿 선택이면 `N selected`.
- **이름 변경** (기능은 그대로)
  - Object 행 `Edit` → `Points` (SAM2 포인트 편집, `E`). 편집 중 표시는 `Editing` 그대로.
  - 툴바 `Edit Changes` → `Show Changes` (표시 토글, `F`).
  - 오토 툴 `Apply & Recompute` → `Apply & Continue` (`Enter`).
- 단축키 창(F1), 툴팁, README 반영. 테스트: `tests/app/test_v04_features.py`

### 2단계 · 프레임 상태 보강 (`v0.4-p2`)
- **상태별 색**: 목록과 하단 줄의 행/글자색 — `★` 파랑, `⚠` 주황, `✕` 빨강, `–` 회색, `✓` 기본.
- **개수 요약**: Frame List 아래와 Frames 줄 오른쪽에 `★1 ✓4 ⚠1 ✕1`. 툴팁에 범례.
- **선택 Object 기준 표시**: Frame List 제목줄 `1` 버튼(설정 `marks_one_object`로 기억).
  - 켜면 Properties에 보이는 Object만 셈하고, 그 Object의 Mask가 없는 이미지는 `–`.
  - Object가 없거나 여럿 선택이면 전체 기준.
- **`[` / `]`**: 이전 / 다음 문제 이미지(`⚠` `✕`, 선택 Object 기준이면 `–`도). 끝에서 처음으로 돌아감.
- Properties 안내 문구의 옛 이름(`Edit`, `Brush: B`) 수정.

### 3단계 · Export 전 검사 (`v0.4-p3`)
- Export 창 위쪽에 검사 결과(`src/core/storage.py` `check_export`, Qt 없음):
  - 저장될 파일 수 / 전체 이미지 수 ("Also write empty masks" 옵션 반영)
  - Mask 없는 이미지, 빈 Mask(Object는 있지만 Final Mask에 픽셀 없음), ⚠ / ✕ 프레임(체크된 Object 기준)
  - 파일 이름 충돌(`{stem}.png`에서 `a.jpg`와 `a.png` 같은 경우). 이름 방식을 바꾸면 다시 검사.
- 문제 이미지 목록: 더블클릭하면 창을 닫고 그 이미지로 이동. 문제가 없으면 목록은 숨김.

### 4단계 · Properties 섹션 접기 (`v0.4-p4`)
- Edit Layer 탭의 도구 **Settings**와 **Layer** 섹션: 제목이 ▾ / ▸ 버튼이 되어 접고 펼칩니다.
- 접힌 상태는 설정(`tool_settings_open`, `layer_section_open`)에 저장되어 다음 실행에도 유지.
- 버튼 배치(Brush / Auto tools)는 그대로. 공용 위젯: `src/app/ui_util.py` `CollapsibleBox`.

### 수정 · 좁은 Frame List로 시작 (`v0.4-p4.1`)
- 이름을 접어둔(`Aa` 꺼짐) 상태로 시작하면 목록 칸이 넓게 뜨고 `Aa`를 두 번 눌러야 좁아지던 문제.
  - 원인: 창이 뜬 뒤 칸 너비를 잡는 `_size_docks`가 접힘 상태와 상관없이 210px로 고정.
  - 수정: 접힘 상태에 맞는 너비(`_list_width`)로 시작.
- 제목줄 버튼(`1`, `Aa`, 띄우기, 닫기)을 20px로 줄여, 좁은 칸의 최소 너비를 113 → 90px로.
- 개수 요약은 좁을 때 잘리지 않고 두 줄로.

### 5단계 · UI 점검 버그 (`v0.4-p5`, 목록: [`ui-issues.md`](../backlog/ui-issues.md) 1~6)
- Batch 탭 `Run on Images` / `Stop` / `Cancel`이 너비 0으로 사라지던 문제: 좁은 칸용 버튼 정책을 `Ignored` → `Preferred` + 최소 24px(`ui_util.shrinkable`). 오토 툴 버튼 줄도 같은 방식.
- Frames 줄 개수 요약이 세로로 쌓이던 문제: 줄바꿈은 Frame List 쪽만.
- Frames 줄 썸네일 아래 ID·표시가 잘리던 문제: 목록 최소 높이 = 칸 + 스크롤바, 기본 높이 150 → 190.
- Frame List 10번부터 줄이 밀리던 문제: ID(오른쪽 정렬) / 표시 / 이름을 고정 칸으로 직접 그림. 선택 행 글자색도 창 활성 상태에 맞춤.
- 글자 잘림: Detection `Select All` / `Select None` → `All` / `None`, 버튼 비율 조정. 왼쪽 탭은 스크롤 화살표 대신 이름 줄임.
- 옛 이름 `Images list` → `Frame List` (Propagation / Batch 문구).

### 6단계 · UI 점검 개선 (`v0.4-p6`, [`ui-issues.md`](../backlog/ui-issues.md) 7~12, 14, 15)
- 패널 폭이 상태에 따라 바뀌던 문제: 원인은 (1) 작업 상태 바의 긴 글자가 캔버스 최소 폭이 됨, (2) 디텍션 안내 한 줄이 왼쪽 칸 최소 폭이 됨. 상태 바는 넘치면 잘리게, 안내 문구는 줄바꿈.
- 작업 상태 바 순서: `Frame │ Object │ Mode │ 파일 이름(회색)` — 좁으면 파일 이름부터 잘림. `Region Box` → `+ Region`.
- 캔버스 왼쪽 위 배너 제거(작업 상태 바와 중복, 작업 중에도 남던 `Select on Image` 안내 포함). Final Mask 미리보기 표시는 유지.
- Properties: 선택이 없으면 제목과 안내만 위쪽에 (빈 Variants/Points, 회색 도구 숨김).
- Propagation 탭: 진행 막대와 Objects / Frames 목록은 첫 실행부터 보임. `Propagate` 버튼은 한 줄 전체, Stop / Cancel / Resume은 그 아래 줄.
- Batch 탭: 진행 막대와 결과 목록은 첫 실행부터 보임(폴더를 열면 다시 숨김).
- 오토 툴 Settings 상자는 지금 도구의 설정 높이에 맞춤(빈 공간 제거).
- Fill / Paint 모드 설명을 한두 줄로 줄임.

### 7단계 · 남은 UI 이슈 (`v0.4-p7`, [`ui-issues.md`](../backlog/ui-issues.md) 13, 17, 18, 19)
- 작은 창: 양옆 패널 시작 폭을 창 폭의 약 55% 안으로(1280×720에서 캔버스 약 400 → 550px).
- Settings 창 최소 폭 640px. Object / 후보 색 칩에 어두운 테두리.
- Frame List 제목줄: 버튼 고정 폭(20px) 제거 — 큰 글꼴·화면 배율에서 잘리던 원인. 접은 모드에서는 제목과 띄우기 버튼 숨김(`DockTitleBar.set_compact`).
- 16번(상태 표시줄 경로)은 하지 않음.

### 수정 · 좁은 Frame List의 개수 요약 (`v0.4-p7.1`)
- 이름을 접은 좁은 모드에서 목록 아래 개수 요약이 두 줄로 나오던 것 → 좁은 모드에서는 숨김(Frames 줄 요약은 유지), 넓을 때는 줄바꿈 없이 한 줄.

### 8단계 · 단축키, Mask Preview (`v0.4-p8`, v0.4.0 이후)
- `,` / `.`: 가장 가까운 이전 / 다음 키프레임(★ = 직접 편집한, 전파 소스). Frame List `1`이 켜져 있으면 선택한 Object의 ★만. 끝에서는 멈춤.
- `F`: 전파 기준(◎, 더블클릭한 프레임)으로 이동. Show Changes는 `F` → `R`.
- Final Mask 미리보기 → **Mask Preview**(`X`, `Z` 누르고 있기 그대로). 옆 버튼 `Preview: Final / Object`(`V`)로 Final Mask ↔ 선택한 Object의 Mask. 설정 `preview_object`로 기억, 캔버스 표시에 `MASK PREVIEW · 이름`.
- 전체 키 정리: [`keymap.md`](../design/keymap.md)

### 9단계 · Enter로 기준 지정 (`v0.4-p9`)
- `Enter`: 현재 프레임을 전파 기준(◎)으로 지정, 이미 기준이면 해제(더블클릭과 같음). 오토 툴이 켜져 있으면 지금처럼 `Apply & Continue`가 먼저, 입력칸에서는 그 칸의 Enter. 길게 눌러도 한 번만.

### 10단계 · 오토 툴은 Fill 모드로 시작 (`v0.4-p10`)
- 오토 툴을 켜거나 다른 오토 툴로 바꾸면 항상 Fill 모드로 시작(전에는 직전 모드 유지). 같은 도구 안에서 Fill ↔ Paint 전환과 `A`(Paint 모드로 전체 선택)는 그대로.

### 11단계 · Object 관리 (`v0.4-p11`)
- **Duplicate** = 현재 이미지의 Mask만 복제(그 이미지에 Mask가 없는 Object는 건너뜀). **Duplicate All** = 전처럼 모든 링크 Mask.
- **Copy A → B…**: 처음 선택한 Object(A)를 두 번째(B)에. 창에서 방향(A → B / B → A), Add(합집합, 기본) / Replace, 이 이미지만(기본) / A에 Mask가 있는 모든 이미지.
  Replace는 프레임을 그대로 복사(포인트·상태 포함), A에 Mask가 없는 이미지의 B는 그대로. Undo 한 번.
- **Merge…**: 창에서 Add(합집합, 먼저 선택한 이름, 기본) / Override with A / Override with B. Override는 겹치는 이미지에서 이긴 쪽 프레임을 그대로 쓰고 이름도 이긴 쪽. 3개 이상이면 선택 순서(A) 또는 역순(B)으로 우선.
- `[···]` 메뉴: Duplicate (this image) / Duplicate All / Copy into ▸(다른 Object 목록).
- 새로 만든 Object가 선택되지 않던 문제(Merge 포함): 목록이 다시 그려진 뒤 선택.
- 코드: `Project.duplicate(key=)`, `Project.copy_into`, `Project.merge(how=)`, `Session.duplicate / copy_into`, `OptionsDialog`, `MainWindow.choose`(테스트에서 교체).

### 12단계 · 열린 프레임을 칸 색으로 (`v0.4-p12`)
- Frame List 행과 Frames 타일: 열린 프레임은 칸 전체 파랑(`CURRENT_FILL`, 글자 흰색), Shift/Ctrl로 고른 다른 프레임은 옅은 파랑(`PICKED_FILL`). 스타일의 선택 강조와 썸네일 색조는 끔. 📌 칸 위에서도 보임.
- 코드: `images_panel.py` `selection_fill`, `TileDelegate`, `OneLineDelegate.paint`.

### 13단계 · 마우스 위치 기준 이동 키 (`v0.4-p13`)
- 마우스가 Frame List / Frames 줄 위: `W A ↑ ←` = 이전 프레임, `S D ↓ →` = 다음 프레임. Objects 목록 위: 같은 키로 이전 / 다음 Object 행(Show all 행 포함, 편집도 따라감).
- 목록 위에서 `S`는 "다음"(스크롤 아님). 스크롤은 ⌖ 버튼, 또는 목록 밖에서 `S`.
- 그 밖의 곳은 그대로: `←` `→` 프레임, `↑` `↓` Object, `A` 오토 툴 전체 선택, `D` Paint, `S` 스크롤, `W` 없음.
- 수식키가 있으면(Shift / Ctrl+화살표 = 목록 여러 칸 선택) 가로채지 않음. 입력칸에 커서가 있으면 가로채지 않음. 편집 중 프레임 이동은 지금처럼 막힘.
- 구현: `MainWindow.eventFilter`가 `ShortcutOverride`를 받아 메뉴 단축키보다 먼저 처리(`_hover_step`, `_hover_zone`, `HOVER_KEYS`).

### 14단계 · 메뉴 계층 (`v0.4-p14`, [`menu-design.md`](../design/menu-design.md))
- 메뉴 바 File / Edit / View / Go / Help에 모든 명령과 키. `QShortcut`으로만 있던 키(`N` `E` `Delete` `Esc` `A` `S` `F` `[ ]` `, .` 화살표)도 메뉴 항목(QAction)으로.
- `Enter`, `Z`(누르고 있기), 목록 위 `W A S D`는 안내 항목(키 표시만, `Enter` 계열은 눌러도 동작).
- 툴바에서 Open / Save / Undo / Redo / Export / Settings를 빼고 Mask Preview · Preview 모드 · Brush · Outline · Show Changes만.
- 패널 켜기/끄기: View → Panels. 종료는 File → Quit(키 없음: `Ctrl+Q`는 Ctrl+Z / Ctrl+A 옆이라 실수로 꺼져서 뺌).
- 테스트: `tests/app/test_v04_features.py` p11~p14 (126 → 133개).

### 15단계 · 키와 메뉴 손보기 (`v0.4-p15`, [`ux-principles.md`](../design/ux-principles.md))
- `S`(Scroll to Current Frame) 뺌: `F`와 겹치고 목록 위에서는 "다음". 스크롤은 ⌖ 버튼.
- `X` ↔ `V`: `Z` 누르고 있기 · `X` Final ↔ Object(메뉴 이름 `Toggle Final / Object Mask`) · `V` Mask Preview 켜기/끄기.
  토글 키는 누르고 있어도 한 번만(`setAutoRepeat(False)`), 이동 키는 반복.
- 프레임 목록 위 `Space` = `Enter`(기준 ◎ 지정). Paint 버튼 = `A`(전체 선택으로 시작). `E` 편집은 브러쉬 켜진 채로 시작.
- 문서: [`ux-principles.md`](../design/ux-principles.md) — 피드백에서 뽑은 UX 원칙.

### 16단계 · 기준 프레임을 칸 색으로 (`v0.4-p16`, 12단계 고침)
- 12단계는 "열린 프레임"을 칠했는데, 요청은 **더블클릭한 기준(◎)**이었음. 이제 ◎ = 칸 전체 파랑(`REFERENCE_FILL`, 글자 흰색),
  열린 프레임 = 파란 테두리(`CURRENT_OUTLINE`), Shift/Ctrl로 고른 프레임 = 옅은 파랑(`PICKED_FILL`). 기준이 없으면 칠 없음.
- 코드: `images_panel.py` `selection_fill(option, index, reference)`, `draw_outline`, 두 delegate의 `reference`.

### 17단계 · Objects 패널 (`v0.4-p17`, 11단계 고침)
- 삭제: 확인 창 없이 바로(Ctrl+Z로 되돌림). 대신 **잠금**: 행의 🔒 버튼, `[···]` Lock / Unlock, `🔒 All` / `🔓 All`, 메뉴 Edit → Objects.
  잠긴 Object는 Delete / × / Merge로 사라지지 않음(Merge는 거절하고 로그). 편집·덮어쓰기는 아직 막지 않음(고민 필요).
- `Copy A → B`: 옵션 창 없이 Add + 이 이미지, 먼저 선택 → 마지막 선택. 옆 `⚙` = Add / Replace, 이 이미지 / 모든 이미지.
- `Merge`: 옵션 창 없이 Add. 옆 `⚙` = Add / Override A / Override B / Into A(나머지는 빈 Object로 남음).
- 마우스가 Objects 패널 위: `Ctrl+D` Duplicate, `Ctrl+Shift+D` Duplicate All.
- 코드: `MaskObject.locked`(저장), `Project.set_locked`, `remove_objects`(잠긴 것 건너뜀), `merge(how="into")`, `merge_blocked`;
  `MainWindow.copy_options`, `merge_options`, `set_locked`, `_over_objects_panel`.

### 18단계 · 캔버스 Solo / Hide Masks (`v0.4-p18`)
- 툴바와 View 메뉴에 토글 두 개. **Solo**: 선택한 Object 행(과 편집 중인 Object)만 캔버스에 색. **Hide Masks**: Object 색 모두 끔,
  편집 중인 Object는 그대로(브러쉬로 칠하는 것이 보여야 하므로). 둘 다 켜면 Hide가 우선. 저장하지 않음(앱을 다시 열면 꺼짐).
- 코드: `MainWindow._colored_ids`, `act_solo`, `act_hide_masks`.

### 19단계 · p16~p18 수정 피드백 (`v0.4-p19`)
- 잠금 칸: 안 잠긴 행은 빈 칸(마우스를 올리면 흐린 🔒), 잠긴 행만 🔒. `Lock All` / `Unlock All` 글자 버튼. (`LockButton`)
- 프레임 색 (16단계를 뒤집음): 열린 프레임 = 파랑 칠(`CURRENT_FILL`), 기준 ◎ = 주황 테두리(`REFERENCE_OUTLINE`), Shift/Ctrl 선택 = 옅은 파랑.
- 캔버스 위 `W` / `S` = Objects 목록의 이전 / 다음. Object 이동은 끝에서 반대쪽으로 순환(목록 위 키, `↑` `↓` 포함).

### 20단계 · Merge / Copy / Move (`v0.4-p20`, [`specs/05`](../specs/05-merge-copy-move.md))
- `Copy A → B` 버튼 → **`Move A → B`**: 먼저 선택한 A의 이 이미지 Mask를 마지막에 선택한 B에 더하고 A에서 뺌. A는 Object로 남음(다 옮기면 빈 Object).
- 옆 `⚙`: Move / Copy · Add / Replace · 이 이미지 / A의 모든 이미지. 고른 값은 기억하지 않음.
- Merge `⚙`: Add / Override A / Override B(Into A는 Move가 대신함). `[···]` ▸ Move into / Copy into.
- 코드: `Project.copy_into(move=)`, `MainWindow.transfer` / `transfer_options`, `ObjectsPanel.transfer_requested`.

### 21단계 · 인버트 / 비우기 (`v0.4-p21`)
- 편집 중인 Object의 이 이미지 Mask: `Ctrl+I` 인버트, `Ctrl+Backspace` 비우기. Region이 있으면 그 안에서만. 편집 레이어로 들어가서
  Edit Layer 삭제로도 되돌릴 수 있고, Undo 한 단계. 편집 중이 아니면 키는 로그 안내만. 메뉴 Edit → Tools.
- 코드: `Session.invert_mask` / `clear_mask`, `MainWindow.mask_edit`.

### 22단계 · Frame List 칸 (`v0.4-p22`)
- ID │ 표시 │ 이름 사이에 옅은 세로선(`COLUMN_RULE`, 열린 프레임 행에서는 흰색), 행은 줄무늬(`setAlternatingRowColors`). 이름을 접으면 ID 뒤 선만.

### 23단계 · COLMAP 장면 열기 (`v0.4-p23`, [`specs/06`](../specs/06-colmap.md) C1)
- 장면 폴더(`images/` + `sparse/0` 또는 `sparse/`)나 그 `images/`를 열면 COLMAP 장면으로 인식: 로그에 모델의 이미지 수, 카메라 수·모델, 3D 점 수.
  모델과 `images/`가 안 맞는 이미지는 ⚠ 로그(앞 5개 이름).
- 작업 파일은 **장면 옆** `<scene>.sms/`. 전에 장면 안(`images.sms/`)에 저장한 프로젝트가 있으면 그대로 씀.
- 처음 여는 장면에 `masks/`, `masks_*/`가 있으면 Object로 불러올지 물음: 폴더마다 건너뛰기 / 흰색 = 대상 / 검정 = 대상
  (흰 면적이 많으면 검정 = 대상을 추천). 파일은 `a.jpg.png`(COLMAP) 또는 `a.png`. 폴더 하나 = Object 하나(상태 ✓, ★ 아님), Undo 한 번.
- File → Import Masks from Folder…: 아무 마스크 폴더나 같은 방식으로.
- 코드: `src/core/colmap.py`(모델 읽기는 COLMAP 공개 형식을 직접 읽음, 쓰기 없음), `Session.import_masks`, `Source.IMPORTED`.

### 24단계 · 학습기별 Export (`v0.4-p24`, [`specs/07`](../specs/07-export-presets.md) C2)
- COLMAP 장면을 열었을 때 Export 창 맨 위 **For**: Brush / LichtFeld Studio / COLMAP / Custom. 프리셋은 장면의 `masks/`에
  `<이미지 이름>.png`(예: `a.jpg.png`), 대상 = 검정(학습에서 무시), 모든 이미지에 씀(Object가 없으면 전부 흰색). 세 학습기가 모두 읽는 형식(소스 확인).
- 덮어쓸 파일은 먼저 `masks_backup_<시각>/`으로 옮김. 검사에 카메라 모델, 백업될 파일 수. LichtFeld는 "Mask Mode = Ignore" 안내.
- 모든 이미지를 쓰는 설정에서는 "마스크 없음"을 문제로 치지 않음(흰색으로 씀). Custom은 전과 같음. 고른 학습기를 기억.

### 25단계 · 마스크 세트 (`v0.4-p25`, [`specs/06`](../specs/06-colmap.md) 4장)
- Export 창 **Mask**: Final Mask(체크한 Object) / 이름 붙인 세트 / Every set(Final + 모든 세트). `Save Checked as Set…` = 지금 체크한 Object를
  이름으로 저장, `Delete Set`. 세트는 `<폴더>_<이름>/`(장면이면 `masks_people/`)으로 따로 씀. 작업 파일에 저장, Undo 가능.
- 학습기는 `masks/`만 읽으므로, 세트로 학습하려면 폴더 이름을 `masks/`로 바꾸거나 그 Object만 체크해 Final로 내보내기(창에 안내).
- 코드: `Project.mask_sets` / `set_mask_set`, `final_mask(key, ids)`, `ExportOptions.object_ids`, `ExportDialog.jobs()`.

### 26단계 · Spirula, Postshot 프리셋 (`v0.4-p26`)
- **Spirula Studio**: `images/` 옆 `masks/`를 그대로 씀(0 = 무시) → Brush·LichtFeld와 같은 파일. 있으면 Spirula가 AI 마스킹을 하지 않음.
- **Postshot**: Remove Occluders가 **흰색 = 무시**(반대)라 `masks_postshot/`에 대상 = 흰색, `a.png`로 따로 씀. Postshot에서 Image Masks에
  끌어다 놓고 Mask Mode = Remove Occluders. 파일 짝 규칙은 문서에 없어 실제로 확인 필요.

### 27단계 · SAM2 로딩 중 포인트 (`v0.4-p27`)
- 로딩 중에 찍은 포인트 / 박스를 버리지 않음: 포인트는 바로 보이고(새 Object면 Mask 없이 생김) 대기열에 들어감. SAM2가 준비되면
  지금 이미지의 대기분을 계산(Undo 한 단계), 다른 이미지의 대기분은 그 이미지를 열 때. 상태 표시줄 `SAM2 loading… (N waiting)`.
- 코드: `Session.defer_prompts` / `pending` / `run_pending`.

### 28단계 · 프레임 제외 + 새 데이터셋 (`v0.4-p28`, [`specs/07`](../specs/07-export-presets.md) C3)
- **Go → Exclude from Dataset / Include**: 고른 프레임(없으면 지금 프레임)을 ⊘로 표시(회색 글자), 다시 하면 되돌림. 작업 파일에 저장, Undo 가능.
  원본 장면은 바꾸지 않음.
- Export 창(장면 + 학습기)의 **Output**: Into the scene(전과 같음) / **New dataset**(빈 새 폴더): `images/`(⊘ 아닌 이미지, 같은 드라이브면 하드링크라 용량을 더 안 씀),
  `sparse/0/`(모델에서 ⊘ 이미지를 빼고 새로 씀: 트랙에서 관측 제거, 관측 2개 미만이 된 3D 점 삭제, 남은 이미지의 그 점은 -1), 마스크.
  bin / txt 모델 둘 다. `rigs.bin` 등 그 밖의 파일은 옮기지 않고 로그에 알림.
- 검사: 새 데이터셋이면 폴더가 비었는지와 뺄 장수, 장면에 쓰기인데 ⊘가 있으면 "새 데이터셋에서만 빠짐" 경고.
- 코드: `src/core/colmap_model.py`(`filter_model`, `build_dataset`), `Project.excluded` / `set_excluded`, `MainWindow.toggle_excluded`.

### 29단계 · 360 ERP → Pinhole 데이터셋 (`v0.4-p29`, [`specs/08`](../specs/08-erp-to-pinhole.md) P1)
- 360 장면(카메라 `EQUIRECTANGULAR`)의 Export → New dataset에 **Convert to pinhole views**: 방위 개수(기본 4) × 고도 목록(기본 −35, 0, 35),
  FOV(기본 90°), 크기(auto = 360 너비 ÷ 4). 끄면 360 그대로(LichtFeld, Spirula용), 켜면 모든 학습기용 Pinhole — 같은 장면으로 둘 다 만들어 비교.
- 이미지(양선형, 좌우 이어짐), 마스크(최근접, 학습기 흑백 규칙), 모델(뷰마다 포즈, `PINHOLE` 카메라 하나, 3D 점은 뷰에 다시 투영해 트랙을 새로 만들고
  관측 2개 미만은 삭제)을 함께 씀. ⊘ 프레임은 빠짐. 원본은 그대로.
- 카메라 표에 COLMAP id 12~17 추가(전에는 ERP 카메라를 만나면 읽기를 멈췄음).
- 코드: `src/core/reproject.py`(원본 모델의 투영식을 표로 두어 Fisheye 등을 더하기 쉬운 틀), `storage.full_mask`.

### 30단계 · Fisheye → Pinhole / 360 (`v0.4-p30`, [`specs/08`](../specs/08-erp-to-pinhole.md) P2)
- 변환 원본: ERP, Pinhole 계열(SIMPLE_PINHOLE, PINHOLE, SIMPLE_RADIAL, RADIAL, OPENCV — 왜곡 포함), Fisheye 계열(OPENCV_FISHEYE, SIMPLE/RADIAL_FISHEYE,
  SIMPLE_FISHEYE, FISHEYE). 투영식은 COLMAP 소스와 같음(테스트로 대조).
- 목표: **Pinhole views**(yaw 목록 × pitch 목록, FOV, 크기) 또는 **360 (ERP)**(원본마다 한 장, 폭 auto = 2π × 초점거리). Export 창 New dataset 아래
  목록에서 고름(Keep the cameras / Pinhole views / 360). 기본 뷰: 360 원본 = 0, 90, 180, 270 × −35, 0, 35 · Fisheye = −45, 0, 45 × −35, 0, 35.
- 원본 렌즈가 못 본 부분(피시아이 → 360의 뒤쪽, 뷰의 바깥)은 **모든 마스크에서 무시**로 써서 검은 채움을 학습하지 않게 함.
- **Fisheye → ERP → Pinhole**: 피시아이 장면을 360으로 내보낸 뒤, 그 데이터셋을 열어(마스크는 Object로 불러와짐) 다시 Pinhole로 내보내면 됨.
- 코드: `reproject.convert(target = Views | Erp)`, `source_projection`.

### 31단계 · 장면의 하위 폴더 이미지 (`v0.4-p31`, 듀얼 피시아이 준비)
- COLMAP 장면의 `images/` 아래 하위 폴더(`cam0/`, `cam1/` …)의 이미지도 엶. 이미지 이름은 `cam0/0001.jpg`처럼 폴더 포함(COLMAP 모델의 이름과 같음).
  `images/` 안의 `masks*` 폴더는 이미지로 치지 않음. 장면이 아닌 폴더는 전처럼 바로 아래만.
- 썸네일 캐시, 작업 파일의 마스크, Export 마스크(`masks/cam0/0001.jpg.png`), 변환 결과 이름이 모두 폴더를 유지해 카메라끼리 겹치지 않음.

### 32단계 · 듀얼 피시아이 → 360 (`v0.4-p32`, [`specs/08`](../specs/08-erp-to-pinhole.md) P3)
- 같은 순간의 리그 카메라 이미지를 묶음: 모델에 `frames.bin`(COLMAP 3.12+)이 있으면 그대로, 없으면 폴더 짝(`cam0/0001.jpg` ↔ `cam1/0001.jpg`).
- Export → New dataset → **360 from camera pairs (N moments)**: 순간마다 360 한 장(첫 카메라가 정면), 이름은 카메라 폴더를 뺀 것(`0001.jpg`).
  각 렌즈의 **내접원**(원형 피시아이의 그림 영역) 안만 쓰고, 겹치는 곳은 원 가장자리 5%에서 부드럽게 섞음. 마스크는 더 가까운 렌즈의 값,
  어느 렌즈도 못 본 곳은 무시. 3D 점은 두 렌즈가 본 점을 합쳐 360에 다시 투영. ⊘가 하나라도 있는 순간은 통째로 빠짐.
- 확인: 알고 있는 파노라마 → 뒤로 맞댄 피시아이 두 장 → 다시 이어 붙이기가 원래와 같음(평균 오차 < 1/255).
- 360으로 만든 데이터셋은 다시 열어 Pinhole views로 내보낼 수 있음(듀얼 피시아이 → 360 → Pinhole).
- 코드: `colmap.frame_groups` / `read_frames_bin`, `reproject.stitch_to_erp`.

### 33단계 · 장면과 함께 연 마스크는 Undo로 안 사라짐 (`v0.4-p33`, 피드백)
- COLMAP 장면을 열며 마스크 폴더를 Object로 불러오면, 그 상태가 Undo의 시작점. 전에는 Ctrl+Z 한 번에 불러온 Object가 통째로 사라졌음.
- File → Import Masks로 나중에 불러온 것은 전처럼 Undo 한 단계. 코드: `Project.forget_history`, `offer_masks(undoable=)`.

### 34단계 · 여러 프레임에 걸친 Object 작업 (`v0.4-p34`, 피드백)
- Frame List에서 고른 프레임(Shift / Ctrl-클릭)에 대해, 선택한 Object들로:
  - **Copy Mask to Picked Frames**: 기준 ◎(없으면 열린 이미지)의 마스크를 고른 프레임에 복사. 기본은 **Add**(있던 마스크와 합침),
    `(Options)…`에서 **Replace**. 복사된 프레임은 전파 결과와 같은 상태(★ 아님, 원래 ★였으면 Add에선 유지). 크기가 다른 이미지는 맞춰 늘림.
  - **Clear Masks on Picked Frames**: 고른 프레임에서 그 Object들의 마스크를 비움(다시 작업하기 위해).
- 둘 다 Undo 한 단계, 키 없음(메뉴 Edit → Objects, Frame List 우클릭). Edit 중에는 안 됨.
- 프레임을 고르다 열린 이미지가 바뀌어 Object가 목록에서 빠져도, 마지막으로 선택한 Object가 대상(로그에 이름·개수 표시).
- 잠금은 결정대로 삭제만 막으므로, 잠긴 Object의 마스크도 비워짐.
- 코드: `Project.clear_frames`, `Session.stamp_frames / clear_frames`, `ObjectsPanel.last_selected`.

### 35단계 · 전파는 선택한 Object만 (`v0.4-p35`, 피드백)
- 버튼 이름은 "Propagate Selected Objects"인데 실제로는 체크된 Object가 모두 전파되고 있었음. 그래서 선택한 Object는 대상 프레임에
  마스크가 없는데도, 다른 Object의 마스크 때문에 덮어쓰기 경고가 떴음.
- 이제 **선택한 Object**(기준 ◎에 마스크가 있는 것)만 전파하고, 덮어쓰기 경고도 그 Object들만 봄. 아무것도 선택 안 했으면 전처럼 체크된 전체.
- 다른 프레임으로 가서 선택 줄이 목록에서 빠져도 마지막 선택이 유지됨(34단계와 같음). 빈 곳을 클릭해 선택을 풀면 잊음.

### 36단계 · 특수 Object: Sky, 피시아이 외곽 (`v0.4-p36`, [`specs/09`](../specs/09-special-objects.md))
- Objects 패널 **+ Special ▾** → Sky Mask / Fisheye Lens Edge. 설정값으로 만드는 Object: 프레임 범위(전체 / Range / 고른 프레임)에 만들고,
  설정을 움직이면 덮는 프레임 전체가 다시 만들어짐. Properties의 **Special** 탭. **Apply**하면 보통 Object(손으로 편집 가능).
- Sky: skyseg.onnx(U2Net) + 저장소의 가장자리 보정(신뢰도 가중 가이디드 필터)을 옮김. 모델 결과는 캐시하고, 설정(Threshold, Grow,
  Refine, 위쪽에 닿은 하늘만)은 즉시 반영. onnxruntime이 없으면 OpenCV DNN으로 실행.
- Lens edge: 이미지 원 바깥. Radius / Center, **Detect from Images**로 원 자동 검출.
- 특수인 동안 Edit / 전파 대상에서 빠짐. 설정은 프로젝트에 저장.

### 37단계 · Edit 중 Hide Masks, Frame List 우클릭 메뉴 제거 (`v0.4-p37`, 피드백)
- **Hide Masks**가 Edit 중인 Object도 숨김: 원본 이미지를 보면서 작업. 브러시 커서와 오토 툴 미리보기는 그대로 보임.
- 34단계에서 넣은 Frame List / Frames 우클릭 메뉴를 뺌: 여러 프레임을 고른 상태에서 프레임을 옮기는 조작을 방해했음.
  Copy Mask / Clear Masks on Picked Frames는 Edit → Objects 메뉴에 그대로 있음.

### 38단계 · 전파를 보면서: 라이브 뷰, Stop / Resume / Cancel (`v0.4-p38`, 피드백)
- 전파 중 막 끝난 프레임과 그 새 마스크를 캔버스에 바로 보여 줌(저장은 끝날 때 한 번에, Undo 한 단계).
- **Stop**: 그 프레임에 머문 채로 멈춤, 결과 유지, **Resume**으로 이어서.
- **Cancel**: 지금까지의 결과는 **유지**하고 원래 보던 프레임으로 돌아감, 작업 완전히 끝(Resume 없음). 결과를 없애려면 Ctrl+Z(전파 전체가 한 단계).
  전에는 Cancel이 결과를 버렸음. 배치(SAM3)의 Cancel은 그대로 버림.
- 버튼 순서 Stop / Resume / Cancel.

### 39단계 · 장면에 Export할 때 기존 마스크를 실제로 바꿈 (`v0.4-p39`, 버그)
- 증상: 장면의 마스크가 `00011.png`인데 프리셋은 `00011.jpg.png`로 써서, 옛 파일이 옆에 그대로 남음(학습기가 옛 것을 읽을 수 있음).
- 이제 이미 있는 마스크의 이름 규칙을 따름(두 이름을 다 읽는 Brush / LichtFeld / Spirula). COLMAP은 항상 `a.jpg.png`.
  내보내는 이미지의 마스크는 두 이름 모두 백업으로 옮겨, 한 이미지에 한 파일만 남음.
- 백업이 `cam0/`, `cam1/` 하위 폴더를 유지. 전에는 한 폴더로 모으면서 같은 이름(카메라별 `00011.jpg.png`)끼리 덮어써 절반이 사라졌음.

### 40단계 · Frame List: 가운데 클릭으로 이동, 우클릭 메뉴 복귀, 복사 기본 Replace (`v0.4-p40`, 피드백)
- **가운데 클릭**: 그 프레임을 열고 고른 프레임(Shift / Ctrl-클릭)은 그대로. **우클릭**: 고른 프레임은 그대로 두고 메뉴
  (Copy Mask / Copy Mask (Options)… / Clear Masks on Picked Frames / Exclude). 37단계에서 뺀 메뉴를 되돌림.
- Copy Mask to Picked Frames의 기본이 **Replace**(Options에서 Add).

### 41단계 · Edit 중에도 프레임 이동 (`v0.4-p41`, 피드백)
- Edit 중 다른 프레임으로 가면 같은 Object를 그 프레임에서 이어서 편집(브러시 / Restore 도구도 유지). 편집 내용은 프레임마다 이미 저장돼 있음.
- 막는 경우는 하나: 오토 툴 Paint 모드에서 골라 둔(칠한) 부분이 아직 안 써졌을 때. 이유를 상태 표시줄에 바로 표시
  (Enter = 쓰기, Esc = 버리기, A = 선택 없음). 그 밖의 오토 툴 미리보기는 이동하면 버려짐.

### 42단계 · Alt+우클릭 드래그로 브러시 크기 (`v0.4-p42`, 피드백)
- Edit 중 **Alt+우클릭 드래그**: 오른쪽 = 크게, 왼쪽 = 작게(Photoshop과 같음). 드래그 동안 원은 누른 자리에 고정. Ctrl / Shift+휠도 그대로.

### 43단계 · Lens edge 설정 변경이 빨라짐 (`v0.4-p43`, 피드백)
- 원인: 설정 하나를 바꿀 때마다 모든 프레임(188장)에서 같은 원을 따로 계산(0.5초 중 0.51초가 이것).
  이제 이미지 크기마다 한 번 계산하고 그 프레임들이 같은 마스크를 공유: 188장 1920² 기준 0.64초 → 0.1초 미만.

### 44단계 · Ctrl+클릭으로 조각 더하기 / 빼기 (`v0.4-p44`, 아이디어 "포인트 기반 편집")
- 문제: 기존 마스크(불러온 것, 전파된 것, 칠한 것)에 포인트를 찍으면 그 마스크를 약한 힌트로만 주고 SAM2를 다시 돌려, 마스크가 통째로 바뀜.
- Edit 중 **Ctrl+좌클릭**: 그 자리의 조각을 SAM2가 그 점 하나로 잡아 마스크에 **더함**. **Ctrl+우클릭**: 그 조각을 **뺌**.
  결과는 Edit Layer에 쌓여 나머지 마스크, 포인트, Variant는 그대로(브러시로 칠한 것과 같은 취급). Region이 있으면 그 안에서만.
  클릭 한 번에 디코더 한 번(이미지 임베딩은 이미 있음)이라 가벼움. 브러시가 켜져 있어도 동작. 클릭마다 Undo 한 단계.

### 45단계 · E = 포인트 편집, D = 브러시 편집, Shift+Enter = Apply & Close (`v0.4-p45`, 보류 아이디어 "에딧 모드 단축키")
- **E**로 편집을 시작하면 브러시가 꺼진 채(포인트). 19단계의 "E로 시작하면 브러시 켜짐"을 되돌림.
- **D**: 편집 중이면 브러시 켜기 / 끄기(그대로). 편집 중이 아니면 선택한 Object를 **브러시로** 편집 시작.
- 오토 툴 **Shift+Enter** = Apply & Close(Enter는 Apply & Continue). 제안했던 F는 Go to Reference ◎가 쓰고 있어서 보류.

### 46단계 · 오토 툴 Close Gaps (`v0.4-p46`, 보류 아이디어 "갭 채우기")
- Edit Layer 오토 툴 **Close Gaps**: 마스크 조각 사이의 좁은 틈과 안으로 파인 좁은 U자 홈을 채움(**Max gap** px, 기본 10).
  원형 모폴로지 닫기(틈의 절반만큼 넓혔다가 다시 좁히기)라 더하기만 함: 마스크가 줄지 않고, 바깥으로 자라지 않고, 넓은 만(灣)은 그대로.
  다른 오토 툴처럼 Fill / Paint 모드, Region, Enter / Shift+Enter.

### 47단계 · Sky 모델 실물 적용 (`v0.4-p47`)
- `checkpoints/sky/skyseg.onnx`(176 MB, Hugging Face JianyuanWang/skyseg)를 받아 실제 촬영본으로 확인: OpenCV DNN으로 동작,
  1024 px 기준 모델 약 0.3초 + 보정 약 0.1초 / 프레임. 보정은 나뭇잎 사이 하늘을 원본 맵보다 잘 잡음.
- 고침: 피시아이 원 바깥의 검은 모서리가 하늘로 잡혔음 → 거의 검은 픽셀(모든 채널 32 미만)은 하늘이 아님(보정 전에 빼서 보정도 오염되지 않게). 10으로는 렌즈 테두리의 어두운 띠가 남았음. 아주 어두운 밤하늘은 빠질 수 있음.

### 48단계 · 체크를 끈 Object의 체크박스가 사라짐 (`v0.4-p48`, 버그)
- 목록을 다시 만들 때(프레임 이동, Object 추가 등) 새 줄은 체크 상태가 아예 없어서 "꺼짐"으로 읽히는데, 코드가 "이미 꺼짐"으로 보고
  상태를 넣지 않아 체크박스가 그려지지 않았음. 한 번 끈 Object는 다시 켤 수도 없었음. 이제 새 줄에는 항상 상태를 넣음.

## 진행 예정
- 없음. 다음 후보는 [`ideas.md`](../backlog/ideas.md) 참고.

## 반영 안 함 (리뷰 평가 결과)
- 전파 Preview 단계: 결과가 바로 Undo 되고 Cancel이 결과를 버리므로 이미 같은 효과
- Frame List와 하단 줄 통합: 역할이 이미 나뉨(목록 = 이동, 줄 = 썸네일)
- 내부 구조 개편: 이미 Object × Frame × Mask 구조
- Object 단위 작업 기록: 비용 대비 효과 낮음
- 나중 과제: Sky 전용 분할 모델(Sky Object 타입), COLMAP 연동
