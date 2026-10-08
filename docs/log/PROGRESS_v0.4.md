# SAM Mask Studio v0.4 진행 현황

**v0.5.1 핫픽스 (2026-10-02):** 59단계(`v0.4-p59`, "응답 없음" 멈춤)만 더한 수정판입니다. 콘솔 창이 일시정지(빠른 편집 선택, Pause)되면 화면 스레드의 로그 쓰기가 끝나지 않아 앱이 멈추던 문제를 고쳤습니다([이슈 #2](https://github.com/qwerzaq56-sketch/sam-mask-studio/issues/2)). 기능과 화면은 v0.5.0과 같고, 안정판 실행기와 포터블도 v0.5.1입니다. [GitHub Release v0.5.1](https://github.com/qwerzaq56-sketch/sam-mask-studio/releases/tag/v0.5.1)은 노트만, 포터블 zip(5.76 GB)은 Google Drive 같은 폴더에 올림(2026-10-03).

**v0.5.0 릴리스 (2026-10-01):** 8~58단계(`v0.4-p8` ~ `v0.4-p58`)와 사용 설명서(`docs/manual/`)가 `main`에 병합되고 `v0.5.0` 태그가 붙었습니다. 안정판 실행기와 포터블도 v0.5.0입니다. 릴리스 직전 수정: F1의 `D` 설명(오토 툴에서 Paint, 다시 = 전체 선택 / 해제), README · 설명서에 "SAM3 검출은 NVIDIA GPU 필요". [GitHub Release v0.5.0](https://github.com/qwerzaq56-sketch/sam-mask-studio/releases/tag/v0.5.0)은 노트만(포터블 약 7 GB는 2 GB 파일 한도로 첨부 안 함). 포터블 스크립트는 태그 뒤 `dev`에서 고침: Sky 모델 포함, `--ref v0.5.0`으로 태그를 묶음, README.txt의 GPU 안내.

**v0.4.0 릴리스 (2026-09-29):** 아래 1~7단계(`v0.4-p1` ~ `v0.4-p7.1`)가 `main`에 병합되고 `v0.4.0` 태그가 붙었습니다. 안정판 실행기와 포터블(`H:\Dev\Masking\dist\SAMMaskStudio`)도 v0.4.0입니다.

외부(GPT) UX 리뷰 중 코드와 대조해서 타당했던 항목만 반영합니다. v0.3 기록: [`PROGRESS_v0.3.md`](PROGRESS_v0.3.md)

적어두는 곳: 기능 아이디어 [`ideas.md`](../backlog/ideas.md) · 작은 UI 문제 [`ui-issues.md`](../backlog/ui-issues.md)

- 브랜치 `dev`에서 단계별 브랜치(`feat/v04-pN-…`)로 작업 → `--no-ff` 병합 → 태그 `v0.4-pN`.
- 되돌리기: 단계 전체 `git revert -m 1 <병합 커밋>`
- 실행: `SAM Mask Studio (dev).bat` = 최신 dev, `SAM Mask Studio.bat` = 안정판 v0.5.0 (이전 안정판은 태그 `v0.4.0`, `v0.3.0`)

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

### 49단계 · Edit 안의 도구 키 E / D, 오토 툴 A / D / F, Q / H (`v0.4-p49`, 사용자 메모)
- Edit를 위 모드로, 그 안의 도구를 키로: **E = 포인트**, **D = 브러쉬**. 편집 중에는 E ↔ D로 오가고, 지금 도구의 키를 다시 누르면 편집 끝
  (전에는 D에서 E를 누르면 편집이 끝났음). 편집 중이 아니면 E / D가 그 도구로 편집 시작.
- 오토 툴이 켜져 있을 때: **D = Paint ↔ Fill**, **A = 나가기(결과 버림, 취소)**, **F = 적용하고 계속(확인, Enter와 같음)**.
  F는 Frame List / Frames 위에 마우스가 있거나 오토 툴이 없으면 전처럼 기준 ◎로 이동. 전의 A(전체 선택 / 해제)는 **Shift+A**.
- **Q**(또는 **`**) = Solo, **H** = Hide Masks.
- F1 단축키 표도 최신으로(Edit 중 이동, 가운데 클릭, Ctrl+클릭, Alt+우클릭 드래그 등 빠져 있던 것).

### 50단계 · Object마다 보이기(👁), + Special 화살표 (`v0.4-p50`, 사용자 메모)
- Objects 줄에 **👁** 칸(이름 · 🔗 · 👁 · 🔒 · Points · × · ···). 끄면 이미지에서만 안 보임. 체크박스(Final Mask에 넣기)와 따로.
  보기 설정이라 저장과 Undo에 들어가지 않음(이번 실행 동안 유지).
- + Special 버튼의 스타일 기본 메뉴 화살표가 깨진 그림처럼 보여서, 글자 "▾"로 바꿈.

### 51단계 · THIN_PRISM_FISHEYE 변환 (`v0.4-p51`, 버그)
- 증상: OSMO 360 장면(카메라 THIN_PRISM_FISHEYE)을 New dataset → Pinhole views로 내보내면 "No image here uses a camera this can
  convert". 변환이 이 카메라 모델을 몰랐음(창은 카메라 짝(듀얼 피시아이)이 있다는 이유로 변환 목록을 보여 줬음).
- COLMAP 소스(`sensor/models/thin_prism.h`)대로 추가: 등거리 피시아이 점에 방사(k1~k4) · 접선(p1, p2) · 얇은 프리즘(sx1, sy1) 왜곡.
  Pinhole / 360 / 듀얼 피시아이 이어 붙이기 모두 이 카메라를 받음.

### 52단계 · 👁을 꺼도 Edit 중인 Object는 보임 (`v0.4-p52`, 피드백)
- 👁을 끈 Object라도 지금 편집 중이면 이미지에 보임(편집을 끝내면 다시 숨음). 전체를 숨기는 Hide Masks(H)는 전처럼 편집 중인 것도 숨김.

### 53단계 · Object 안의 포인트 레이어 (`v0.4-p53`, [`specs/10`](../specs/10-prompt-layers.md), 사용자 메모)
- 한 프레임의 마스크 = Original + 포인트 레이어 1…n(각각 **더하기 +** 또는 **빼기 −**), 그 위에 Edit Layer(브러시).
  레이어는 자기 포인트 / 박스만으로 SAM2를 돌린 조각이라 **기존 마스크가 망가지지 않음**. 클릭한 레이어만 다시 계산.
- 자기 포인트 없이 생긴 마스크(불러오기 · 전파 · Apply)는 첫 클릭이 자동으로 **Layer 1(+)**. 자기 포인트로 만든 프레임은 전처럼 Original.
  Original을 고르면 기존 방식(기존 마스크를 씨앗으로 다시 그리기).
- Properties → Points가 트리: Original · Layer n (+/−), 그 아래 포인트 / 박스마다 **×**. 줄을 누르면 그 레이어로(굵게).
  **+ Layer** · **+ / −** · **Remove Layer**. 캔버스에는 지금 레이어의 포인트만.
- 브러시는 레이어까지 합친 마스크 위의 차이. 저장: 레이어의 포인트 · 박스 · +/− (json)와 조각 PNG(`<key>.L1.png`). 예전 프로젝트는 그대로 열림.

### 54단계 · Export 진행 표시 (`v0.4-p54`, 사용자 메모)
- Export 중 진행 창: 지금 단계(마스크 쓰기 / 새 데이터셋 만들기 / 변환 / 이어 붙이기)와 `n / 전체`, 막대. 상태 표시줄에도 `Exporting… n / 전체`.
  중간 취소는 두지 않음(반쯤 쓰인 결과가 남지 않게). 끝나면 닫히고 로그에 결과.

### 55단계 · 오토 툴 키 A / S / D / F / G (`v0.4-p55`, p49 피드백)
- 왼손 줄에 차례로: **A 취소**(나가기) · **S Fill** · **D Paint**(Paint에서 D 다시 = 전체 선택 / 해제) · **F 확인**(Apply & Close) · **G Apply & Continue**.
  Enter(Continue) · Shift+Enter(Close)도 그대로.
- Fill ↔ Paint를 오가도 Paint에서 고른(칠한) 부분이 남음(전에는 Paint로 갈 때마다 전체 선택으로 돌아감). 처음 Paint로 갈 때만 전체 선택.
- S는 목록 위에서는 전처럼 이동 키, 캔버스 위에서는 오토 툴이 켜져 있을 때만 Fill(꺼져 있으면 다음 Object).

### 56단계 · 👁을 맨 앞에, 단색 아이콘으로 (`v0.4-p56`, 피드백)
- Objects 줄: **👁** · 체크박스 · 이름 · 🔗 · 🔒 · Points · × · ···(레이어 목록의 흔한 배치). 컬러 이모지 대신 직접 그린 단색 눈(글자색), 숨기면 흐리게.

### 57단계 · 360 → Pinhole 뷰 배치 프리셋 (`v0.4-p57`, [`specs/08`](../specs/08-erp-to-pinhole.md) §8 리서치)
- Export → New dataset → Pinhole views(360 원본)에 **배치** 목록: **COLMAP overlapping · 12**(기본, COLMAP 예제의 기본: 4 × −35 / 0 / 35, 위 줄 45° 돌림) ·
  **Cubemap · 6** · **Horizon · 4**(위아래 뺌) · **Two rings · 16**(LichtFeld 360 플러그인 Medium) · **Custom**(전처럼 yaw × pitch 격자).
- 리서치: 배치별 3DGS 품질 비교 자료는 없음. 연구는 360 그대로 학습이 더 낫다고 보지만 일반 학습기는 Pinhole이 필요. 겹침이 매칭에 유리.

### 58단계 · 뷰 배치를 규칙으로, 미리보기, 피시아이의 빈 뷰 빼기 (`v0.4-p58`, GPT 리뷰 반영, [`specs/08`](../specs/08-erp-to-pinhole.md) §8.1)
- 이름: **COLMAP Overlap · 12 Views** · **Cubemap · 6 Views** · **Horizon · 4 Views** · **Two Rings · 16 Views** · **Custom**, 각 배치의 역할을 창에 표시(목록 툴팁과 아래 설명).
- 배치를 규칙(`ViewLayout`: 링의 pitch · 개수 · 시작 yaw, 위 / 아래)으로. FOV · 해상도는 따로, 뷰 개수와 겹침(옆 / 줄 사이)은 계산해서 표시.
- **미리보기**: 구를 펼친 지도에 뷰마다 윤곽선과 점. 12와 16의 차이, 겹침이 한눈에.
- **피시아이**: 렌즈가 절반도 못 채우는 뷰는 만들지 않음(전에는 거의 검은 이미지 + 무시 마스크). 미리보기에서 회색 점선, 파일 수에서도 빠짐.

### 59단계 · "응답 없음" 멈춤: 콘솔에 막히지 않는 로그 (`v0.4-p59`, 버그 2026-10-02)
- 증상: 앱이 "응답 없음", CPU 0. 메인 스레드가 Qt 경고(Export 창 `QWindowsWindow::setGeometry`)를 stderr(콘솔)에 쓰다 멈춰 있었음.
  콘솔 창 출력이 일시정지(빠른 편집 선택 또는 Pause)되면 콘솔 쓰기는 끝나지 않고, 그걸 GUI 스레드가 했기 때문.
- 고침:
  - 로그를 **파일**(`logs/sam-mask-studio.log`, 2 MB × 3)에 쓰고, 콘솔은 **백그라운드 큐**로만(콘솔이 막혀도 앱은 계속, 큐가 차면 콘솔 쪽만 버림).
  - **Qt 메시지**를 그 로그로(`qInstallMessageHandler`), 같은 메시지는 한 번만(10 / 100 / 1000번째에 횟수).
  - 시작할 때 이 콘솔의 **빠른 편집을 끔**(클릭 한 번에 출력이 멈추지 않게). Pause 키는 막지 못하지만 위 큐 때문에 앱은 안 멈춤.
  - 경고 자체: Export 창이 줄을 하나씩 보이고 숨길 때마다 Windows가 허용하는 것보다 작게 줄어들려 함 → 한꺼번에 바꾸고 한 번만 크기 맞춤(경고 0).
    배치 목록 칸 이름 `layout` → `view_layout`(QWidget의 `layout()`을 가리고 있었음, `p57`).

### 60단계 · 버전 표시, 포터블 `--zip` (`v0.4-p60`, 2026-10-03)
- 앱 어디에도 버전이 안 보였음 → **창 제목**(`SAM Mask Studio v0.5.1`)과 **Help > About SAM Mask Studio**(버전, 로그 파일 위치), 시작 로그 `app_started`에 `version`.
  - 버전 정하는 순서(`src/version.py`): 포터블의 `VERSION` 파일 → git 체크아웃이면 릴리스 태그 기준 `git describe`(태그 위 `v0.5.1`, dev는 `v0.5.1-3-g1a2b3c4` = 그 뒤 커밋 3개) → `pyproject.toml`.
  - 단계 태그(`v0.4-pN`)는 버전으로 쓰지 않음. 포터블의 `VERSION`도 같은 규칙.
- `tools/make_portable.py --zip`: 폴더 옆에 `<폴더>-<버전>-portable.zip`. 모델 가중치(`.pt`, `.onnx` 등)와 이미 압축된 파일은 그대로 담고, 나머지는 빠른 압축 단계로. `.part`로 쓰고 끝나면 이름을 바꿈(중간에 멈추면 완성본처럼 보이지 않게).

### 61단계 · 오토 툴 Invert, Fill 모드의 Apply to All Frames (`v0.4-p61`, 2026-10-05)
- 오토 툴 **Invert**: 마스크 반전(Region이 있으면 그 안만). 설정 없음. `Ctrl+I`와 결과는 같지만 먼저 미리보기(마젠타 / 보라)로 보이고, Paint 모드로 일부만 골라 넣을 수 있음.
- **Apply to All Frames** (Fill 모드에서만 보임): 지금 오토 툴을 지금 설정 그대로 편집 중인 Object의 **마스크가 있는 모든 프레임**에 적용.
  - 확인 창(프레임 수) → 백그라운드 계산(작업 표시줄에 진행) → **Ctrl+Z 한 번**으로 전부 되돌림. 툴은 켜진 채로 남음.
  - 각 프레임의 Edit Layer에 들어감(한 장에서 Fill 하는 것과 같음, 상태 Manual). 마스크가 없는 프레임은 그대로 비어 있음.
  - Region이 있으면 모든 프레임에 같은 Region을 씀(크기가 다른 이미지는 건너뛰고 로그에 개수). Object Fill은 프레임마다 그 이미지를 읽어 계산.
  - Paint 모드에서는 숨김(골라 넣기는 한 장 기준).

### 62단계 · 하늘 경계를 원본 해상도로 (`v0.4-p62`, 2026-10-06, 제안서 하늘 S1-A1 / 배치 툴 기획서 M1·M3)
- 문제: 하늘 마스크는 1024 px 작업 해상도에서 0/1로 정해지고 내보낼 때 nearest로 키워져서, 3840² 어안에서 경계가 약 4 px 계단이고 나무 바깥 잎까지 하늘로 덮였음. 잎 사이 하늘 구멍은 실제보다 뭉툭하게 커서 잎까지 먹음.
- **Export의 "Sky edges at full resolution"** (하늘 Object가 있을 때만 보임, 기본 켬, 설정에 기억): 하늘 Object의 경계를 원본 이미지에서 픽셀마다 다시 정함. 다른 Object는 예전처럼 키움. 새 데이터셋·뷰 변환 내보내기에도 적용.
  - `src/core/sky_edges.py`: 모델 없이 마스크와 원본 이미지만 씀(편집한 마스크 그대로). 경계 안쪽·바깥쪽의 확실한 픽셀로 그 이미지의 색 모델(RGB 히스토그램 32³)을 만들고, 경계에서 1/96(3840에서 40 px) 안쪽부터 1/19(200 px) 바깥까지를 색으로 다시 판정. 하늘 쪽은 승산 0.6 이상이어야 들어감(나무 넘침 방지).
  - 멀리 있는 흰 물체(꽃, 셔츠)는 보지 않음. 거의 검은 픽셀(렌즈 바깥·테두리)은 작업 마스크 값 유지.
  - **반전된 하늘**(하늘 빼고 전부, 0022의 Sky #4)도 같은 경계가 반대로 나옴. 밝은 쪽을 하늘로 보고 판정.
  - 하늘 Object 판단: Sky special Object, 또는 Apply 한 뒤에도 출처 SPECIAL이고 이름이 "Sky …"인 것.
  - 속도: 3840² 한 장 약 1초(이미지 읽기 포함).
- 확인: 0022 cam0(00429, 00489 등 8장) 원본 해상도 확대 비교로 경계가 잎을 따라감. 기존 `sky_only` 기준 마스크는 이 툴의 skyseg 출력과 94장 모두 IoU 1.000(같은 것)이라 정답으로 쓸 수 없음 → 정량 평가는 정답 세트가 생긴 뒤.
- `Project.members()` 공개(내보내기에서 Object 묶음 판단).

### 63단계 · 명령줄 `python -m src.cli sky` (`v0.4-p63`, 2026-10-06, 배치 툴 기획서 M7)
- 창 없이 폴더 단위로 하늘 마스크를 만듦. 360 → 3DGS 배치 툴의 단계 5(하늘 마스크)가 그대로 부를 수 있게.
  - 모델과 설정은 Sky special Object와 같음(`--threshold`, `--grow`, `--top-only`, `--no-refine`). 경계는 62단계 방식으로 원본 해상도에서 다시 판정(`--no-edges`면 예전처럼 키움).
  - 출력: 흰색 = 하늘(기획서의 `sky_masks/` 규칙), `--invert`로 반대. 이름 `<이미지 이름>.png`(COLMAP), `--recursive`면 `cam0/`·`cam1/` 유지.
  - 이미 있는 마스크는 덮어쓰지 않음: 기본은 하나도 쓰지 않고 멈춤, `--skip-existing`(이어서) / `--overwrite`.
  - 한 장이 실패해도 계속하고, 끝에 실패 목록과 종료 코드 1. `--report`로 JSON(설정, 버전, 장별 하늘 비율·시간).
- 실측: 0022 cam0 94장(3840² 어안) 249초(장당 2.6초, CPU), 실패 0. 예전 Export 결과와 IoU 0.986. 차이는 경계에 몰려 있고, 가장 많이 달라진 00417에서는 예전에 하늘로 덮였던 왼쪽 큰 나무 윗부분이 빠지고 잎 사이 하늘이 들어감.

### 64단계 · 명령줄 `python -m src.cli lens` (`v0.4-p64`, 2026-10-07, 배치 툴 기획서 M8)
- 배치 툴 단계 3(렌즈 테두리)용. Spirula 기존 마스킹은 쓰지 않기로 확정(2026-10-07)되어 렌즈도 이 툴에서.
  - 원 찾기는 Lens edge Object와 같은 `detect_lens_circle`. **카메라 폴더마다** 따로(0022: cam0 반경 105.3 %, cam1 105.7 %), 폴더에서 고르게 뽑은 16장(`--samples`)의 평균 밝기로.
  - 한 장씩 찾으면 어두운 장면이 테두리에 닿을 때 반경이 ±3.6~6.2 % 흔들림 → 여러 장을 합쳐서 찾음. 16장 표본을 8번 바꿔도 반경 표준편차 0.13 %. 보고서에 한 장씩 찾은 값의 흔들림(`spread`)도 남김.
  - `--margin`(기본 반경의 2 %, 3840에서 약 40 px): 0022 위쪽 테두리는 원 경계 안쪽 약 60 px부터 밝기가 떨어지는 번진 띠(렌즈 경통 반사·흐림)가 있어서 안으로 당김. 아래쪽은 경계가 날카로움.
  - 출력: 흰색 = 원 안(학습에 씀), 검정 = 원 밖(`masks/` 규칙). `--invert`로 반대. `--radius`/`--cx`/`--cy`로 직접 지정.
  - `--and-with <폴더>`: 같은 이름의 마스크(흰색 = 학습)와 곱해 사람 + 렌즈를 `masks/` 한 폴더로. 그 폴더에 없는 이미지는 렌즈만 쓰고 보고서에 목록.
  - 원이 안 보이는 폴더(피시아이가 아님)는 그 이미지들을 실패로 남기고 종료 코드 1.
- 실측: 0022 cam0·cam1 188장 18초, 실패 0.
- `original_size`(이미지 헤더만 읽어 크기)를 `src/engine/imageio.py`로 옮김(명령줄에서도 씀). 명령줄 공통 부분(이름, 있는 파일 처리, 보고서)을 `Batch`로 묶음.

### 65단계 · 명령줄 `python -m src.cli person` (`v0.4-p65`, 2026-10-07, 배치 툴 기획서 M4~M7)
- 배치 툴 단계 4(사람·셀카봉·장비). 0022 cam0 94장으로 방법을 고름. 기준은 이 툴로 만든 뒤 사람이 확인한 Person + Fisheye_Mask(전파 182장, 손으로 고침 6장).
  | SAM3(원본 모델, 1024 px) 프롬프트 | IoU 평균 / 최저 | 비고 |
  |---|---|---|
  | person | 0.657 / 0.501 | 셀카봉·가방 빠짐 |
  | person + selfie stick | 0.697 / 0.503 | "selfie stick"은 94장 중 18장에서만 잡힘 |
  | person + black pole | 0.910 / 0.828 | "black pole"은 93장에서 잡힘(pole 0.6대, black pole 0.75~0.86점) |
  | + bag(사람·봉에 닿은 것만) | 0.947 / 0.897 | 크로스백이 "person"에 안 들어감 |
  - 경계 넓히기(1024 px): 1 px IoU 0.954(놓침 1.7 %), **2 px 0.938(놓침 0.4 %, 기본)**, 4 px 0.882. 사람 마스크는 넘치는 쪽이 안전(기획서 8.2)해서 2 px.
  - "stick", "monopod", "handle", "tripod"은 0건. 셀카봉이 카메라에 고정돼 있어 여러 프레임의 검출을 모은 "장비 마스크"도 시험했지만 "black pole"이 이미 93/94장이라 효과 거의 없음(IoU +0.003) → 넣지 않음.
- `src/core/people.py`: 검출을 합치는 규칙(`people_mask`, `touching`). `src/cli.py`의 `person` 명령:
  - 출력: 검정 = 사람·봉·가방(학습에서 무시), 흰색 = 나머지(`masks/` 규칙). `--invert`로 반대. `--labels`, `--attach`, `--threshold`, `--grow`.
  - GPU 보호: 빈 메모리가 5 GB 미만이면 아무것도 하지 않고 멈춤(학습 중 SAM 금지 규칙). `--gpu-anyway`, `--cpu`.
  - `--and-with`: 렌즈 마스크 등과 곱함. `lens`의 `--and-with`와 같은 함수(`_multiply`)로 정리.
- 실측(원본 해상도, 0022 cam0·cam1 188장, 장당 1.9초, 최대 약 4.2 GB, 실패 0):
  - cam0: IoU 0.943, 최저 0.875, 놓침 0.3 %, 넘침 5.8 %(넓힌 몫). 같은 기준으로 Spirula `sam track` 0.838, 최저 0.531.
  - 어려운 프레임: 01113 0.969(Spirula 0.531), 01125 0.971(0.607), 00635 0.875(0.760; 1 px로 넓히면 0.90).
  - cam1(뒤 렌즈, 셀카봉이 지워진 쪽): 기준 마스크가 거의 비어 있는데, 멀리 지나가는 행인을 7장에서 잡음(기준에서 빠져 있던 것).

### 66단계 · 마스킹 프리셋과 프롬프트 시험 (`v0.4-p66`, 2026-10-07)
- 배경: 0022에서 맞은 프롬프트("black pole" 등)가 다른 데이터셋·장비에서도 맞는다는 보장이 없음. 여기서는 Claude Code가 기준 마스크로 검증했지만, 다른 환경에서는 프리셋을 만드는 일 자체가 어려움 → 프롬프트를 프리셋으로 관리하고, 손으로 하나씩 시험·조정할 수 있는 길을 함께 둠.
- 이 툴의 핵심 기능이 아니라 **배치 마스킹(외부 사용)이 주 목적**. 그래서 따로 묶음:
  - `src/batchmask/`(Qt 없음): `presets.py`(프리셋 읽기·저장·찾기), `probe.py`(프롬프트 시험), `builtin/*.json`(내장 프리셋).
  - 앱 연결은 메뉴 한 줄(File > Batch Masking with Presets…)과 `src/app/batch_mask_dialog.py`. 대화상자는 `python -m src.cli`를 별도 프로세스로 부르므로 창에서 만든 결과 = 배치 결과.
- 프리셋(JSON): `person`(labels, attach, threshold, touch, grow, max_side), `lens`(margin, samples, radius, cx, cy), `sky`(threshold, grow, top_only, refine, edges, max_side). 빠진 단계는 안 함. `checked_on`에 무엇으로 확인했는지와 결과를 적음. 고치면 확인 기록은 비워짐(원래 프리셋의 확인이 고친 설정에는 해당되지 않으므로).
  - 내장: `osmo360-selfie-stick`(0022 확인 수치 기록), `people-only`(확인 안 됨, 출발점). 내장 이름으로는 저장 불가(복사해서 새 이름으로).
  - 내 프리셋: `mask_presets/`(git 제외) 또는 `SMS_MASK_PRESETS` 폴더. `.json` 경로로도 지정.
- 명령줄:
  - `run`: 프리셋의 모든 단계를 장면 폴더로(`masks/` = 사람 × 렌즈, 사람만은 `people_masks/`, `sky_masks/`). 결과 폴더 중 하나라도 마스크가 있으면 시작 전에 멈춤. 사람 단계가 있으면 GPU 확인도 시작 전에.
  - `probe`: 카메라 폴더마다 N장(기본 8)에서 프롬프트별 검출 장수·점수·면적, `--reference`(손으로 확인한 `masks/`)가 있으면 덮은 비율·넘친 비율·IoU, `--inside 90`(기준에 렌즈 테두리가 들어 있을 때 원 안만 비교). 대조 시트 `sheet_NN.jpg`, `probe.json`. `--also`는 재기만 하는 후보. `--save-preset`으로 저장(IoU를 확인 기록에).
  - `preset list / show / save`.
  - `sky` / `lens` / `person`도 `--preset`을 받고, 따로 준 옵션이 프리셋 값을 바꿈.
- 실측: 0022 `probe --preset osmo360-selfie-stick --also "selfie stick;tripod" --frames 8 --reference masks --inside 90` 16장, SAM3 로드 13초 + 장당 약 2초. cam0 8장 IoU 0.878~0.971(p65와 같은 수준), "selfie stick" 5/8장·"tripod" 0장. 대화상자 경유(하위 프로세스) 같은 결과.
- 창: Try Prompts(대조 시트 표시), Save as Preset, Run on the Folder, Stop, Copy Command. 실행 전에 이 창의 SAM 모델을 내려 GPU를 비우는 선택(닫으면 다시 올림).

### 67단계 · 하늘 정답 세트 도구 `truth make / score` (`v0.4-p67`, 2026-10-07)
- 하늘 수치(넘침 < 0.5 % 목표)를 잴 정답이 없어서. 3840² 어안 전체를 손으로 맞추는 건 비현실적이고 하늘 대부분은 쉬움 → **경계가 어려운 곳만 원본 해상도 크롭(768²)** 으로 정답을 만듦. 768이면 앱에서 축소 없이 편집.
- `src/batchmask/truth.py`, 명령 `python -m src.cli truth make / score`:
  - `make`: 프레임마다 초안 하늘(현재 sky 명령과 같은 방법)의 경계가 가장 긴 곳을 N곳(기본 2) 고름. 하늘 비율 20~80 %인 곳만(나무 속 잎 틈투성이 크롭은 손으로 못 그림, 처음 시험에서 그런 크롭이 뽑혀 조건 추가), 어안 원 90 % 안쪽만. `images/`, `drafts/`(흰색 = 하늘), `overview/`, `manifest.json`. 이미 세트가 있으면 아무것도 안 씀.
  - `score`: 아무 방법의 전체 프레임 하늘 마스크를 같은 자리에서 잘라 IoU, 넘침·놓침(정답 하늘 대비), 경계 F(2 px, 8 px). 안 고친 크롭은 건너뛰고 목록.
- 0022: `H:\360To3DGS\OSMO_360Camera\0022\truth\sky\`(새 폴더) 크롭 12장(00155, 00417, 00429, 00489, 00585, 00957 × 2). 모두 나무 꼭대기 실루엣. 고치는 법은 그 폴더 `README.md`. **사용자가 손으로 고쳐야 정답이 됨**(초안이 이 툴 결과라 경계를 직접 따라가며 고칠 것).

### 68단계 · 하늘 정답 후보 자동 생성 `truth auto`, Edit Layer `By Color` (`v0.4-p68`, 2026-10-07)
- 크롭 손수정이 너무 힘들다는 피드백 → 두 갈래.
- **`python -m src.cli truth auto <세트>`** (`truth.matte_sky`): 크롭마다 색으로 꼼꼼히 만든 하늘 마스크를 `candidates/`(흰색 = 하늘)에, 원본|결과 나란히 `review/`에. 사용자는 검수만, 틀린 것만 앱에서 고침. 하늘 모델이 아니라 픽셀 색으로 판정(초안은 확실한 표본만 줌):
  - 초안 하늘·나무를 5 px 줄인 곳이 표본(하늘은 두 쪽 밝기 중간보다 밝은 것만: 초안이 나무 위로 넘쳐도 나무색을 하늘로 안 배움).
  - 픽셀마다 주변 하늘색·나무색(정규화 합성곱, 3/8/20/60 px 중 표본이 있는 가장 가까운 거리)을 구하고, 두 색의 섞임으로 볼 때 하늘이 0.6 이상이고, 파랑·무채색이고(햇빛 받은 잎은 초록), 3 px 안 주변 하늘색과 Lab 22 이내(구름 앞 회색 가지 끝 제외, 주변에 하늘이 없는 나무 속은 2~3배 허용)면 하늘. 섞인 경계 픽셀은 나무로.
  - 한 번 더: 하늘색 표본을 1차에서 하늘로 판정된 픽셀로만(초안이 하늘로 넣은 가지가 주변 하늘색을 물들이지 않게). 3 px 이하 조각 제거.
  - 0022 크롭 12장 22초(CPU). 초안 대비 하늘 −0.8~−7.5 %, +0.0~0.7 %. 빠진 것은 대부분 초안이 잎 틈을 부풀린 테두리와 흐린 가지 끝(섞인 픽셀 → 나무 규칙). 확대 확인: 잎 틈은 보이는 흰 부분에 맞고, 구름 앞 가지는 나무로 남음.
  - 이미 마스크가 있는 출력 폴더는 거부. `manifest.json`에 방법·설정·크롭별 수치 기록.
- **Edit Layer 자동 도구 `By Color`** (`refine.split_by_color`): 마스크 경계 근처(기본 30 px, 0 = 전체·Region 안)를 밝기나 색으로 다시 판정. 마스크는 대충만 맞으면 됨.
  - Brightness: 경계 근처 회색값 Otsu 문턱, 밝은 마스크는 밝은 쪽(어두운 마스크면 반대).
  - Color: 경계 근처 색을 8묶음(Lab k-means)으로 나누고, 초안이 대부분 덮은 묶음은 마스크로(초안이 군데군데 틀려도 맞는 쪽을 배움).
  - Balance 50 = 중간, 높이면 마스크가 넓어짐. Fill / Paint 모드, Apply to All Frames 그대로.
- 테스트 252개 통과(+9).

### 69단계 · 하늘 후보 오류 2종 수정, Mask Preview 잘라보기 (`v0.4-p69`, 2026-10-07)
- 사용자 지적: 하늘 후보에 하늘 속 작은 '나무' 조각. 확인해 보니 하나 더: 00957 땅의 흰 꽃·난간 반사·표지판이 하늘로(나무 속 틈 판정을 느슨하게 한 부작용).
- `matte_sky` 끝에 초안(하늘 모델)으로 큰 그림 확인: 초안 하늘에서 24 px 넘게 떨어진 곳은 하늘 아님, 초안 나무에서 16 px 넘게 떨어진 60 px 이하 비하늘 조각은 하늘. 남은 작은 조각은 풀·꽃대 끝(실제 식물). 후보 다시 만듦(이전 것은 `candidates_v1/`, `review_v1/`로 보존).
- **Mask Preview 스타일**(View > Cycle Preview Style, 단축키 C, 툴바 'Style: …'): Mask(흑백) → Cut Out(마스크 안 이미지만, 나머지 마젠타) → Outside(마스크 밖만). 하늘 마스크에 섞인 잎은 Cut Out, 빠진 하늘은 Outside에서 바로 보임. 설정에 저장.
- 테스트 254개 통과(+2).

### 70단계 · By Color: Range(컬러피커·밝기 범위), Add / Remove (`v0.4-p70`, 2026-10-07)
- 사용자 요청: 색조 외에 밝기 기준, 컬러피커, Add 말고 Remove도.
- **By** 콤보: Auto: Color / Auto: Brightness(기존 자동 판정) / **Range**.
  - Range(`refine.select_range`): Pick Color를 켜고 이미지를 클릭하면 그 색(5×5 평균), Shift+클릭이면 색 추가(최대 8, 하늘+구름 등). 견본 표시, Clear.
  - 'Color within' N: 고른 색 중 하나와 Lab a*b*(색조·채도, 밝기 제외) 거리 N 이내. 'Brightness from A to B': 회색값 범위. 둘 다 켜면 둘 다 만족하는 픽셀.
- **Changes**(`refine.take`, 모든 By에 적용): Add & Remove / Add only(마스크에 더하기만) / Remove only(빼기만).
- Near edge(0 = 전체·Region 안), Fill / Paint 모드, Apply to All Frames 그대로. 다른 도구로 바꾸면 피커 꺼짐.
- 테스트 257개 통과(+3).

### 71단계 · C는 스타일만 (`v0.4-p71`, 2026-10-07)
- 사용자 요청: C는 Mask Preview 스타일만 바꾸고, 미리보기 진입은 V(토글) / Z(누르는 동안)로. 미리보기가 꺼진 채 C를 누르면 로그에 바뀐 스타일만 알림.

### 72단계 · 잘라보기 배경을 체커보드로 (`v0.4-p72`, 2026-10-07)
- 사용자 지적: 잘라보기 배경 마젠타가 자동 도구 미리보기(추가 = 마젠타, 제거 = 보라)와 구분 안 됨 → 회색 체커보드(투명 표시 관례, 칸 = 긴 변의 1/64, 최소 8 px). 앱의 다른 오버레이 색(마젠타·보라·시안·노랑·빨강)과도 하늘·나무와도 안 겹침.

### 73단계 · 미리보기 토글을 두 상태씩 (`v0.4-p73`, 2026-10-07)
- 사용자 요청: C가 세 상태를 돌아서 불편, 두 개만 오가게 → **C**: 흑백 ↔ 잘라보기, **Shift+C**: 잘라보기 안쪽 ↔ 바깥(흑백일 때 누르면 다음 C에 쓸 쪽만 바뀜). 둘 다 설정에 저장, 미리보기 진입은 그대로 V / Z.

### 74단계 · By Color Near edge 켜고 끄기 (`v0.4-p74`, 2026-10-07)
- 사용자 지적: Color within 최대(100)인데 잎이 안 잡힘. 원인은 허용치가 아니라 Near edge(30 px): 경계에서 30 px 밖은 후보에서 빠짐(화면의 둥근 마젠타 끝선). → 사용자 의견대로 Near edge는 두되 **체크박스로 켜고 끔**(끄면 이미지 전체, Region 안으로 제한). Auto·Range 모두 적용, 기본 켬(하늘 경계 편집용).

### 75단계 · By Color Range의 Remove를 '고른 픽셀 빼기'로 (`v0.4-p75`, 2026-10-07)
- 사용자 지적: Remove가 안 됨. 실제 앱 경로로 재현(00489 크롭, 후보 마스크, 회색·허용치 100): 계산은 설계대로였지만 **설계가 직관과 반대**였음. 'Remove only' = 선택으로 마스크를 바꿀 때 빠지는 변화만 → 잎 색을 고르고 Remove하면 잎이 아닌 쪽이 빠짐.
- Range는 포토샵식으로: **Add selection**(고른 픽셀 더하기) / **Remove selection**(고른 픽셀 빼기) / **Replace with selection**(Near edge·Region 안을 선택으로). Auto 방식은 그대로 Add & Remove / Add only / Remove only(결과 변화 중 고르기). 콤보 글자가 By에 따라 바뀜.

### 76단계 · 잘라보기 바깥을 마스크 색으로 (`v0.4-p76`, 2026-10-07)
- 잘라보기(C)의 잘린 곳을 기본은 **그 자리 마스크 색**으로: 안쪽 보기면 검정(마스크 밖), 바깥 보기면 흰색(마스크 안). 흑백 마스크와 같은 색이라 바로 이어서 읽힘.
- View > **Cut Out Background: Checkerboard** 체크로 예전 회색 체커보드. 설정(`cutout_fill`)에 저장.

### 77단계 · Range에서 클릭은 색 고르기 (`v0.4-p77`, 2026-10-07)
- 사용자 지적: 색 고를 때 SAM2 포인트가 찍힘. Pick Color 버튼을 따로 켜야 해서, 안 켠 채 클릭하면 포인트가 됨.
- By Color에서 Range를 고르거나 Range 상태로 By Color에 돌아오면 **Pick Color가 저절로 켜짐**: 클릭 = 색 고르기, Shift+클릭 = 색 추가, SAM 포인트 없음. 포인트를 찍고 싶으면 버튼을 끔. 다른 도구로 가면 꺼짐.
- 피커 중 더블클릭은 무시(두 번째 클릭이 고른 색을 다시 덮어쓰지 않게).

### 78단계 · Range 색 비교에 밝기 포함, `Keep selection only` (`v0.4-p78`, 2026-10-07)
- 사용자 지적: 하늘 마스크에서 잎과 겹친 픽셀을 칠해서 빼고 싶은데 Range가 전혀 못 함(잎 전체가 '더해짐' 마젠타).
- 원인: 색 비교가 Lab a*b*(밝기 뺀 색조·채도)만이라 흰 하늘과 어두운 회녹색 잎이 둘 다 '무채색'으로 같은 색. 0022 크롭 4장, 하늘 중앙값 색·허용치 20: 나무 픽셀의 38–48 %가 하늘색으로 잡힘(40이면 78–98 %).
- 색 비교를 **Lab 전체(밝기 L* 포함) 거리**로: 같은 크롭에서 허용치 40에도 나무 0.6 % 이하, 하늘 85–99 %. 기본 허용치 20 → 30.
- Range 동작에 **Keep selection only**(맨 위, Range 기본): 마스크에서 고른 색이 아닌 픽셀을 뺌. 하늘색을 고르고(Shift+클릭으로 구름·파란 하늘 추가) Paint 모드로 잎 위를 칠하면 칠한 곳의 잎만 빠짐. Add / Remove / Replace with selection 그대로. Auto 방식으로 가면 목록이 Add & Remove / Add only / Remove only로 바뀜.
- 초안 마스크에서 해 보면(하늘색 1개, 전체): 허용치 20이면 초안 넘침의 52–72 %가 빠지지만 하늘 그라데이션 때문에 진짜 하늘도 0.4–20 % 빠짐, 30이면 넘침 9–24 %·하늘 0–2 %. 넘침 대부분은 하늘과 섞인 밝은 경계 픽셀이라, 색 하나보다 여러 개를 고르고 Paint로 칠한 곳만 빼는 쓰임새.
- 테스트: 잘라보기 테스트가 캔버스의 Final Mask 비동기 갱신 때문에 가끔 실패하던 것 고침.

### 79단계 · By Color 판정 영역 표시, Invert selection, Pick Color 상태 명시 (`v0.4-p79`, 2026-10-07)
- 사용자 지적: Replace면 반경 안은 다 빠지거나 들어가야 하는데 둘 다 아닌 곳이 있음. 계산은 맞음: 반경 안 픽셀은 모두 판정되고, 이미 그 상태인 픽셀은 변화가 없어 프리뷰에 색이 없음(마스크 안 = Object 색, 밖 = 원본). 그런데 반경이 어디까지인지 안 보여서 '판정 안 된 곳'처럼 보임.
- **Near edge 판정 영역을 옅은 흰색으로 표시**(마스크 색 아래, Region 있으면 그 안만). 영역 안: Object 색 = 하늘로 남음, 옅은 흰색만 = 밖으로 남음, 마젠타/보라 = 바뀜. Near edge를 끄면(전체) 표시 없음. `session.auto_area`.
- Range에 **Invert selection**: 고른 색·밝기 범위 밖이 선택(잎을 고르고 Invert하면 나머지 = 하늘).
- Pick Color 상태: 켜지면 버튼이 주황 'Picking colors: click here or Esc to stop', 캔버스 배너 'PICK COLOR · click: pick · Shift+click: add · Esc / the Pick button: stop'. **Esc 첫 번째는 피커만 끔**(도구·편집은 그대로).

### 80단계 · Pick Color 버튼 글자 짧게 (`v0.4-p80`, 2026-10-07)
- 켜졌을 때 글자가 버튼 폭에서 잘림 → 'Stop Picking (Esc)'. 자세한 안내는 캔버스 배너에.

### 81단계 · By Color Range를 A/B 규칙으로 (`v0.4-p81`, 2026-10-07)
- 사용자 지시대로 다시 설계. 필터(고른 색·허용치, 밝기 범위)가 잡은 영역 = **A**, 나머지 = **B**(Near edge 영역 안).
  - **Add A & Remove B**(기본): A는 마스크에 넣고 B는 뺌.
  - **Add only (A)**: A만 넣음. **Remove only (B)**: B만 뺌.
  - **Invert (swap A and B)**: A와 B를 바꿈.
- 예전 설계의 문제: Remove가 'A를 빼기', B를 빼는 건 따로 'Keep selection only'라 Add/Remove가 같은 영역 기준이 아니었음. Keep 항목 없앰.
- 0022 크롭 00489, 하늘색 하나·허용치 30·Near edge 30: Add & Remove = 흰 틈 1831/1833 들어옴, 잎 16 px 빠짐 / Invert = 잎 66,816 px 들어옴, 하늘 63,571 px 빠짐 / Remove only = 16 px 빠짐(Invert: 63,571).
- 콤보 글자 'Add && Remove'가 화면에 &&로 보이던 것 고침(콤보는 &를 그대로 보여줌).
- 테스트: 잘라보기 테스트가 가끔 실패하던 원인 = 테스트 도우미가 해제된 QImage 메모리를 읽음(복사로 고침). 5번 연속 257개 통과.

### 82단계 · Hide Masks 중 브러시가 기존 마스크를 지우던 버그 (`v0.4-p82`, 2026-10-07)
- 사용자 보고: Mask Preview 바깥 보기 + Hide Masks로 작업하니 기존 마스크가 날아감.
- 원인: Hide Masks는 편집 중 Object의 색 레이어를 캔버스에 넘기지 않음. 그런데 브러시 획은 그 레이어에서 지금 마스크를 읽어 시작 → 빈 마스크에서 시작 → 획만 남고 기존 마스크가 사라짐. 바깥 보기와 무관, Hide Masks만 켜도 생김(p37부터).
- 고침: Hide Masks 중에도 편집 중 마스크를 그리지 않는 레이어(`edit_hidden`)로 캔버스에 넘김. 화면은 그대로(원본, 윤곽선 없음), 획은 실제 마스크에서 시작.
- 회귀 테스트: Hide + 바깥 보기 + Mask Preview에서 획을 그어도 기존 마스크 픽셀이 전부 남는지. 수정 전 코드에서는 실패 확인.

### 83단계 · 키 재배치(X·C), 1 px 브러시, Ctrl+드래그 크기, 프리뷰 파랑/주황 (`v0.4-p83`, 2026-10-07)
- 키: **X** = 흑백 마스크 ↔ 잘라보기, **C** = 잘라보기 안쪽 ↔ 바깥(흑백에서 누르면 잘라보기로). Final / Object 전환(예전 X)은 **Shift+X**.
- 브러시 최소 크기: 가장 작게 해도 3 px 원이 칠해지던 것 → 이미지 1 px까지. 반경 0 = 한 픽셀, 획 굵기 2r+1, 화면 원은 실제 칠해지는 크기로 그림. 최소 화면 크기 2 → 1.
- 브러시 크기: **Ctrl+좌우 드래그**(오른쪽 = 크게, 클릭 위치에 원 고정). 예전 Alt+우클릭 드래그 대신. Ctrl+클릭(이미지 조각 더하기/빼기)은 그대로: 움직이지 않고 떼면 클릭, 움직이면 크기. Pick Color 중에도 됨. Ctrl+휠 그대로.
- 자동 도구 프리뷰 색: 마젠타/보라는 들어옴/빠짐으로 안 읽힘 → **파랑(40,110,255) = 들어옴, 주황(255,120,0) = 빠짐**. 초록/빨강은 Show Changes(R)의 손 편집 색과 겹쳐서 안 씀.
- 테스트 259개(+1).

### 84단계 · X / C 재배치, Edit·오토 툴·Mask Preview 수칙 제안서 (`v0.4-p84`, 2026-10-07)
- 사용자 지시대로: **X** = 흑백에서 Final ↔ Object, 잘라보기 중이면 흑백으로(Final / Object 저장된 그대로). **C** = 잘라보기에서 안쪽 ↔ 바깥, 흑백 중이면 잘라보기로(안 / 밖 저장된 그대로). p83의 X(흑백 ↔ 잘라보기) · Shift+X 없앰. 흑백 ↔ 잘라보기는 View 메뉴에도.
- [`design/edit-tools-preview-rules.md`](../design/edit-tools-preview-rules.md): p68–p84에서 나온 규칙(표시 ≠ 데이터, A/B 선택 규칙, 색 표, 모드 표시, 키, 브러쉬, 검증)과 제안 6개. `keymap.md`, 정답 세트 README 키 설명 갱신.

## 85단계 (`v0.4-p85`): By Color 현재 동작 정리 (피드백용)

- `docs/design/edit-tools-preview-rules.md` 9절: By Color Range 처리 순서(BC-1~8), Auto 방식(BC-10, 11), 기대와 어긋날 수 있는 지점(BC-12~19: 마스크 안쪽 깊은 잎은 판정 띠 밖, Near edge 끄면 하늘색 비슷한 것이 들어옴, 5×5 평균 색, 하늘 그라데이션, 작업 해상도 1024, 경계 섞인 픽셀, 적용 후 띠 이동). 사용자가 BC 번호로 피드백.
- 같은 내용을 아티팩트 [편집 도구 · 미리보기 수칙](https://claude.ai/artifact/JEJbPmcFfefHebuFTcMDFF)로 게시, 상위 기획서(360 → 3DGS 워크플로우 개선 계획) 8.2 하위 문서 표와 머리말에 추가.
- 코드 변경 없음.

## 86단계 (`v0.4-p86`): By Color Range 미리보기를 A / B로 칠함

- 문제: 미리보기가 마스크에 생길 변화만 칠해서, A인데 이미 마스크 안(마스크 색만)이거나 B인데 이미 밖(원본 그대로)인 픽셀이 A도 B도 아닌 것처럼 보였다. 계산은 정상(Add & Remove 결과 = A, 크롭 00489에서 픽셀 단위 일치)이고 표시가 (A/B) × (지금 마스크 안/밖) 네 칸이었다.
- 이제 판정 영역의 모든 픽셀을 A = 파랑, B = 주황으로 칠한다. 바뀌는 픽셀은 진하게(기존 `auto_add` / `auto_sub`), 그대로인 픽셀은 옅게(새 `auto_a` / `auto_b`, alpha 60). 크롭 00489, Near edge 끔: 네 레이어 합 = 이미지 전체(589,824 px), Invert를 켜면 색이 그대로 맞바뀜.
- 원래 마스크가 보이게: 오토 툴 색은 편집 레이어 색을 덮어쓰지 않고 그 위에 섞는다(`canvas.compose`, `BLENDED`). 경계는 흰 선 그대로.
- `Session.auto_ab(settings)`: Range의 (A, B), 판정 영역(Near edge, Region) 안. 필터 결과는 설정이 같으면 캐시.
- 테스트: Range 테스트에 A / B 표시가 이미지 전체를 나누는지(Add & Remove, Add only + Invert) 추가.
- 대기: 고른 색 썸네일을 누르면 그 색만 지우기(`docs/backlog/ui-issues.md` 22).

## 87단계 (`v0.4-p87`): 툴바 미리보기 버튼 = X / C, 체커, 오버레이 투명도

- 툴바의 `Style: …`(흑백 ↔ 잘라보기) 버튼 대신 키와 같은 두 버튼: `Preview: Final / Object` = `X`, `Cut Out: Inside / Outside` = `C`. 지금 Mask Preview가 보이는 쪽 버튼이 눌린 상태(흑백이면 X 버튼, 잘라보기면 C 버튼). 흑백 ↔ 잘라보기는 View 메뉴에 그대로.
- 툴바에 `Checker`(잘라보기 바탕 체커, View 메뉴와 같은 동작)와 `Overlay %`(10–200 %, 마스크 색·오토 툴 색 등 모든 오버레이 채우기의 진하기, 설정에 저장). Mask Preview는 오버레이가 아니라 영향 없음.
- 테스트: 툴바 버튼이 X / C와 같은 상태 변화와 눌림 표시, 체커, 오버레이 % (`compose`의 알파가 비율대로).

## 88단계 (`v0.4-p88`): 오버레이 투명도 = 슬라이더

- 툴바 `Overlay %`를 숫자 칸에서 슬라이더(10–200 %, 옆에 `Overlay 100 %` 값 표시)로. 값 글자를 더블클릭하면 100 %로.
- 하늘: 사용자가 `0022/truth/sky/review`로 후보 12장 검수(틀린 것만 앱에서 고침) → `images_masks/`로 확정 → `truth score`로 예전 Export · `cli sky` · 경계 재판정 끔/켬 비교, 넘침 < 0.5 % 확인 → M3(원본 해상도 줄이기·경계 띠), 제안서 S2.
- 사람: 다른 데이터셋으로 프롬프트 확인(M5), `probe`로.
- 기획 문서: 360→3DGS 기획서가 상위, 기능별 개선 기획은 하위 문서 4개(하늘, 사람·장비, 렌즈, 배치 마스킹과 프리셋). 다음 후보는 [`ideas.md`](../backlog/ideas.md) 참고.

## 89단계 (`v0.4-p89`): 편집 도구 수칙 문서를 범주별로 나눔, 오토 툴 수칙 새로

- 사용자 요청: 오토 툴 Fill / Paint 전환, 나가기 / 적용하기 같은 이미 구현된 규칙과 그 이유를 제안서로 정리하고, 하위 문서들을 범주별로 나누거나 합칠 것.
- `docs/design/auto-tools-rules.md` 새로: 한 장 요약(A S D F G), 켜기, Fill / Paint, 적용과 나가기(명시적 적용만 쓰고 그 밖의 나가기는 버림, Esc 한 단계씩, Paint 고름이 남았으면 프레임 이동 막음), Apply to All Frames, 미리보기 표시, 새 오토 툴 만들 때, 제안 AT-1~5.
- `docs/design/by-color.md` 새로: 선택 규칙 A / B(공통 수칙 2절에서 옮김) + 현재 동작 BC-1..19(9절에서 옮김) + 제안 BC-P1~3.
- `docs/design/edit-tools-preview-rules.md`는 공통 수칙만(데이터 안전, 색, 모드, Mask Preview 키 · 툴바, 브러쉬, 검증)으로 줄이고 1–7절로 다시 번호. `ux-principles.md` 링크를 세 문서로.
- 공유 페이지: 하위 문서를 각각의 아티팩트가 아니라 상위 문서(360 → 3DGS 개선 계획) 안의 페이지(`sky.html` … `rules.html`, `auto.html`, `bycolor.html`)로 넣음. 다른 아티팩트로 가는 링크는 데스크톱 앱 밖 브라우저를 띄워서 불편하다는 피드백. 8.2 표를 "마스킹 방법" / "SAM Mask Studio 편집 도구" 두 범주로.

## 90단계 (`v0.4-p90`): 고른 색 썸네일 클릭 = 그 색 지우기

- By Color Range의 고른 색 썸네일이 하나씩 링크. 누르면 그 색만 빠지고 나머지는 그대로, 결과는 다시 계산(`PropertiesPanel.remove_sample`). `Clear`는 전부. ui-issues 22 완료.
- 테스트: 가운데 색을 지우면 앞뒤 색이 남고, 다 지우면 "No color picked".

## 91단계 (`v0.4-p91`): 오토 툴 색 범례 (AT-2)

- 오토 툴이 켜져 있으면 캔버스 왼쪽 아래에 지금 쓰는 색과 뜻: `Adds` / `Removes`(Range: `A: adds`, `A: already in`, `B: removes`, `B: already out`), Paint면 `Not picked (Paint)`, Near edge면 `Decided here (Near edge)`. 견본은 화면과 같은 진하기. 도구를 나가거나 Mask Preview 중이면 없음(`Canvas.set_legend`, `MainWindow._auto_legend`).
- 오토 툴 수칙 6-5로 옮기고 제안 AT-2는 뺌.

## 92단계 (`v0.4-p92`): 고른 색 Undo, 고른 색이 있으면 피커가 저절로 안 켜짐

- 사용자 보고: By Color를 다시 켜니 Pick Color가 저절로 켜진 것을 눈치 못 채고 클릭해서 고른 색이 날아갔고, 실행 취소도 안 됨.
- 고른 색 바꾸기(클릭 = 교체, Shift+클릭, 썸네일 클릭, Clear)가 Undo 한 단계(`Session.set_color_samples`, UI 상태 `colors`). 프레임·편집 대상이 바뀌어도 그 기록은 남김.
- Range의 피커 자동 켜기(p77)는 고른 색이 없을 때만. 있으면 꺼진 채 시작, `Pick Color`로 켬.
- 공통 수칙 3-2 보충, 3-4 새로("공들인 상태는 Undo"), By Color BC-1.

## 93단계 (`v0.4-p93`): 고른 색 = 1 px

- By Color Range의 색 고르기가 클릭한 픽셀 하나의 색(작업 해상도). 전에는 5×5 평균이라 잎·구름 경계에서 섞인 색이 골라짐(BC-14). `Canvas.sample_color` 기본 `r=0`.

## 94단계 (`v0.4-p94`): Edit Layer 탭에 Edit 버튼

- Edit Layer 탭 맨 위에 `Edit <이름> (E)` / `Editing: <이름> (Esc: finish)` 버튼. 패널에 보이는 Object의 편집을 켜고 끔. Object 목록의 Points / Editing 버튼과 같은 동작(`toggle_edit`)이고, 둘 다 세션 상태를 따라 같이 눌림 / 풀림.

## 95단계 (`v0.4-p95`): Alt+클릭 = 5×5 평균색

- By Color 색 고르기: 클릭 = 1 px(p93), **Alt**+클릭 = 주변 5×5 평균(노이즈가 많은 곳). Shift와 같이 쓰면 평균색을 추가. 배너·툴팁에 안내.

## 96단계 (`v0.4-p96`): 색 고를 때 원본 보기 (BC-P3 a–d)

- 사용자 요청: 컬러피커로 고를 때 원본 색을 토글하며 보고 싶음.
- Pick Color 옆 `Original (T)` 버튼(픽커가 켜져 있을 때만). 켜면 캔버스에 사진만: Object 색, 에딧 레이어, 오토 툴 A / B·회색·Near edge, Region, 포인트, 후보, 범례를 그리지 않음. 배너 앞에 `ORIGINAL (T)`(`Canvas.set_original_view`).
- `T`: 짧게 = 켜기 / 끄기, 0.3초 넘게 누르고 있으면 떼는 순간 원래대로(`MainWindow._original_key`). 픽커가 꺼져 있으면 로그로 안내만.
- 픽커를 끄면(Esc, 오토 툴 나가기) Original도 꺼짐. 켜는 건 자동으로 안 함(p92).
- 고르는 값은 전처럼 원본 픽셀(표시만 바뀜). 픽커 배너에 `T: original`, F1 목록에 T.
- Clear 버튼은 스와치 옆으로.

## 97단계 (`v0.4-p97`): By Color = Range만, 조건별 Not (BC-P5 a, BC-P4 a)

- 사용자 평가: Auto: Color / Auto: Brightness는 결과가 형편없음. 밝기로 잡으면 잎은 잘 잡히나 밝은 하늘·구름도 같이 잡힘 → 밝기로 잡고 하늘색은 빼고 싶음.
- `By` 목록과 Balance를 없애고 By Color는 Range만(`split_by_color`, `take`와 그 테스트 지움). 오토 툴 설정은 저장되지 않아 옮길 값 없음.
- `Color within`, `Brightness from` 줄마다 `Not`: 그 조건만 뒤집음(`select_range(not_color, not_brightness)`, 설정 `color_not`, `bright_not`). 조건끼리는 전처럼 AND. 예: `밝기 140–255` ∧ `Not 하늘·구름색`.
- 전체 Invert는 `Swap A / B`로 이름만 바꿈(설정 키 `color_invert` 그대로). 계산은 `session.range_selection` 하나로 모음(미리보기 A / B와 적용이 같은 함수).
- 테스트: `tests/unit/test_split_by_color.py` → `test_select_range.py`(near_edge 테스트 추가), 앱 테스트 Not / Swap.
- p96 기록 때 지워진 `## 반영 안 함` 제목 줄 복구.

## 98단계 (`v0.4-p98`): By Color 빼는 색(−), 겹치면 가까운 쪽 (BC-P4 b)

- 색 고르기 중 **우클릭 = 빼는 색**(Shift = 하나 더, Alt = 5×5 평균, 최대 8개). 스와치 둘째 줄 `− ■ N left out`, 누르면 그 색만 지움. `Clear`는 둘 다.
- 허용치 따로: `− except within`(빼는 색이 있을 때만 켜짐, 처음 30).
- 규칙(10-07 결정): 넣는 색 거리 d+, 빼는 색 거리 d−. 색 조건 = `d+ ≤ 허용치 ∧ (빼는 색이 차지 안 함 또는 d+ < d−)`, 같으면 B. 빼는 색은 자기 허용치 안만 차지. 빼는 색만 있으면 = 그 색들에 Not. 그 위에 조건별 Not, Swap(p97).
- 둘 다 차지한 픽셀은 노란 점선 윤곽(`overlap`, 채우지 않음), 범례 `Overlap: nearer color wins`.
- 넣는 색과 빼는 색은 한 Undo 단계(세션 `_colors` = (넣는 색, 빼는 색)).
- 배너 `right-click: leave out`, F1 목록, 키 문서.

## 99단계 (`v0.4-p99`): 고른 자리 표시, 숫자 칸에서 T, Not은 넣는 색만, 색 비율 경고

- 사용자 화면(빼는 색 하늘 하나, Color within 100 + Not, except within 100, 밝기 206–255): 색 조건이 이미지 전체를 "참"으로 만들어 A = 밝기 조건과 같았음(코드는 AND였지만, 허용치 100 + 빼는 색만 있을 때의 Not이 겹쳐 색 조건이 아무것도 가르지 못함).
- **Not은 넣는 색(+)에만**: 빼는 색은 Not과 상관없이 늘 뺀다. 넣는 색이 없으면 Not 체크는 꺼진 채.
- **색 비율 표시**: `Color takes N % of the area`(판정 영역 중 색 조건만으로 A인 비율). 95 % 이상 / 1 % 이하면 주황 경고. 허용치 툴팁에 거리 감각(10 같은 색 · 30 비슷 · 60+ 대부분 · 100 전부).
- **고른 자리 표시**(BC-P3 f): 이 프레임에서 고른 색 자리에 그 색 점 + 번호(`1`, `−1`). 원본 보기 중에도 보이고 스와치를 지우면 사라짐.
- **T 키**: 숫자 칸(스핀박스)에 커서가 있어도 작동. 글자 입력 칸에서만 막힘.
- `select_range(..., with_parts=True)` = (A, 겹침, 색 조건). 테스트 2개 추가.

## 100단계 (`v0.4-p100`): T는 누르고 있기만, 켜 두기는 버튼

- 사용자 요청: T의 짧게 누르기 토글을 없앰. **T = 누르는 동안만 Original 뒤집기, 떼면 원래대로**(시간 기준 0.3초 삭제). 켜 두기 / 끄기는 `Original (hold T)` 버튼.
- 버튼이 켜져 있을 때 T를 누르고 있으면 그동안 마스크 표시가 돌아옴. 배너 `hold T: original`, `ORIGINAL (hold T: masks)`, F1·키 문서.

## 101단계 (`v0.4-p101`): By Color 색과 밝기를 Or로 합치기 (기본)

- 사용자 지적(10-07): 색과 밝기는 **같은 하늘을 다른 방식으로 잡는 것**이라 더해야(Or) 하는데 늘 And(교집합)였음. 밝기 205–255는 흰 구름만, 색은 파란 하늘을 잡아 And면 파란 하늘이 B가 되어 빠졌음.
- 단계별 마스크로 확인(00155_x1152_y960, 사용자 화면 설정): 띠 안 하늘 중 색 96.5 %, 밝기 39 %. And = 하늘에서 36,534 px 빠짐, **Or = 99.5 % 잡고 268 px만 빠짐**. 앱 계산과 별도 계산(실수 Lab, 회색값 직접) 차이 0.04 %.
- 패널 `Join` 콤보: **Or: either one catches (add up)**(기본) / And: both must catch. 빼는 색(−)은 합친 결과에서 마지막에 뺌(Or든 And든). Not(조건별), Swap(전체)은 그대로라 반대 마스크도 얻음.
- `select_range(..., join="or")`. 테스트 1개 추가, And를 전제한 테스트 2곳은 `join="and"`로.

## 102단계 (`v0.4-p102`): 툴바 Overlay 슬라이더가 라벨 옆에

- 사용자 화면: `Overlay 100 %` 라벨과 슬라이더 사이가 크게 벌어짐. 원인: 라벨 + 슬라이더 묶음이 툴바의 남는 폭을 다 가져감(1900 px 창에서 1182 px). 묶음을 제 폭(211 px)으로 고정, 창 폭과 상관없이 라벨 바로 옆(5 px).

## 103단계 (`v0.4-p103`): Apply to Frames, Frame List에서 고른 프레임에만

- 사용자 요청(10-07): Apply to All Frames를 고른 범위·프레임에만 적용하는 옵션. 버튼 이름 `Apply to Frames…`.
- 누르면 창에서 고름: **All**(마스크가 있는 모든 프레임) / **Picked in the Frame List**(Shift-클릭 범위, Ctrl-클릭 추가; 그중 마스크가 있는 것만). 2장 넘게 골라 두었으면 Picked가 기본. 골랐는데 마스크 있는 프레임이 없으면 로그만.
- Undo 한 번, 건너뛴 프레임 알림은 그대로. 테스트 1개 추가.

## 104단계 (`v0.4-p104`): Export Current Mask (지금 이미지 한 장)

- 사용자 요청(10-07): 지금 마스크 한 장만 내보내기, Final / Object 선택.
- 파일 메뉴 `Export Current Mask…` (`Ctrl+Shift+E`). 창에서 **Mask**: Final Mask(체크된 Object 전부) / 그 Object만(편집 중인 Object, 아니면 선택한 Object 하나; 편집 중이면 기본), **Colors**: 마스크 흰색 / 반전. 그다음 저장 창(기본 이름 `<이미지>.png`, Object면 `<이미지>_<이름>.png`).
- 원본 해상도, 일괄 Export와 같은 계산(`full_mask`, Sky 경계 설정 따름). 비어 있으면 검은 PNG를 쓰고 로그에 알림. `storage.export_one_mask`. 테스트 1개.

## 105단계 (`v0.4-p105`): By Color 프리셋

- 사용자 요청(10-07): By Color 필터 프리셋 저장.
- By Color 설정 맨 위 `Preset` 줄: 목록에서 고르면 바로 적용, `Save…`(이름, 같은 이름은 덮어씀), `Delete`(보이는 것).
- 담는 것: 고른 색 · 빼는 색, 두 허용치, Color / 밝기의 사용 · Not, 밝기 범위, Join, Swap, Changes, Near edge(켬 · 폭). 앱 설정 파일 `config.local.json`의 `color_presets` (다른 폴더 · 프로젝트에서도). 넣은 색은 Undo 한 번(기존 색 바꾸기와 같은 단계).
- 테스트 1개(저장 → 다른 설정 → 불러오기 → Undo → 삭제).

## 106단계 (`v0.4-p106`): By Color 마지막 설정을 다음 시작 때 그대로

- 사용자 요청(10-07): 마음에 드는 By Color 설정이 앱을 다시 켜면 사라짐.
- 설정(고른 색 · 빼는 색 포함, 프리셋과 같은 항목)을 바꿀 때마다 1초 뒤와 앱을 닫을 때 `config.local.json`의 `color_last`에 적고, 시작할 때 되돌림. 되돌린 색은 Undo 단계가 아님. 테스트 1개(가짜 엔진으로 창 두 번 띄움).

## 107단계 (`v0.4-p107`): 설정 저장 때 파일의 By Color 프리셋과 합침

- 문제(10-07): 앱이 켜진 동안 `config.local.json`에 넣은 프리셋·마지막 설정이, 앱이 켤 때 읽어 둔 빈 설정으로 통째로 덮여 사라짐.
- 사용자 요청: 합치게. `Settings.save`가 쓰기 전에 파일의 `color_presets` 중 메모리에 없는 것을 넣음. 앱에서 지운 이름(`removed_presets`)은 빼서 되살아나지 않음. 프리셋 저장·삭제 뒤 패널 목록을 합친 목록으로 새로 채움.
- `color_last`는 합치지 않음(켜진 앱의 패널이 곧 마지막 설정).
- 테스트 1개(켜진 동안 파일에 넣은 프리셋 유지 → 둘 다 목록에 → 지운 것은 안 돌아옴). 전체 272 통과.

## 108단계 (`v0.4-p108`): 브러시 크기 = Ctrl+좌클릭 드래그만

- 사용자 요청(10-07): Ctrl+우클릭 드래그 크기 조절은 빼고 좌클릭 드래그만, Ctrl+휠은 그대로(하늘 마스킹 때 Ctrl+우클릭 조각 빼기를 자주 씀).
- Ctrl+우클릭은 드래그를 시작하지 않음: 손이 조금 움직여도 누른 자리의 조각 빼기 한 번. 색 고르기 중 Ctrl+우클릭은 아무것도 안 함.
- 테스트: 크기 드래그 테스트를 좌클릭으로, Ctrl+우클릭을 40 px 움직여도 크기 그대로 · 누른 자리 빼기 한 번.

## 109단계 (`v0.4-p109`): `cli sky --color-preset` (By Color를 배치로)

- 사용자 요청(10-07, 제안에 "둘 다 진행"): 하늘 정답을 만들 때 쓴 By Color 프리셋을 명령줄 하늘 마스크에 적용.
- `range_selection`·`RANGE_KEYS`와 By Color의 A/B 계산(`apply_by_color`)을 `src/app/session.py`에서 `src/core/refine.py`로 옮김. 앱도 같은 함수를 부름(동작 그대로, `src.app.session`에서 import도 그대로 됨).
- `sky --color-preset NAME|file.json`: 앱 By Color 패널의 프리셋(이름, `config.local.json`) 또는 그 설정 `.json`. 원본 크기 마스크(경계 판정 뒤, `--invert` 전)에 적용. 모르는 키는 거절. 리포트 `settings.by_color`에 설정 기록. `--no-color`로 끔.
- 마스킹 프리셋 `SkyStep.color`(dict): `run`도 같은 방식으로 적용.
- 측정(0022 정답 12장, CPU, 6장 31초): `cli sky` 넘침 12.8 % → 프리셋 `sky 8 colors + bright 205`로 IoU 0.980, 넘침 0.95 %(최대 7.01 % = 00155_x384_y1152), 놓침 1.06 %, F@2 0.888. 크롭에 적용했던 앞 측정(0.78 %)보다 조금 나쁨: 크롭 경계에서 Near edge 띠가 잘렸던 차이. 이 프리셋으로 정답을 만들었으니 낙관적일 수 있음 → 다른 프레임 정답(`truth/sky2`)으로 다시 잼.
- 테스트 2개(가짜 하늘 모델: .json·이름 프리셋으로 하늘색 아닌 조각 빠짐, 모르는 이름·키 거절, 마스킹 프리셋에 color). 전체 274 통과.

## 110단계 (`v0.4-p110`): `cli sky` 띠 밖 나무 끝 빼기

- 사용자 지적(10-07): 하늘 모델이 하늘로 칠한 나무 끝이 Near edge 띠(경계에서 30 px) 밖에 있으면 By Color가 손대지 않아 하늘로 남음(00489 나무 끝: 조각 42개, A 아닌 픽셀로 나무와 이어진 것 0개). 사용자 요청: "띠 밖 규칙 cli에 넣어줘".
- `src/core/refine.py` `tree_tips(base, image, settings, sel, reach, rough, far, grow)`와 기준값 `TREE_TIPS`(120 px, 거칠기 12, Lab 10, 1 px): 하늘 마스크 안·A 아님·띠 밖·나무에서 120 px 안·회색 7×7 표준편차 > 12·고른 색에서 Lab 10 이상 → A 아닌 픽셀로 1 px 넓힘. 띠가 꺼져 있으면 아무것도 안 함. `apply_by_color`에 미리 계산한 A(`sel`)를 넘길 수 있게 함(A를 두 번 계산하지 않게).
- `cli sky`: `--color-preset`과 함께 기본으로 켬, `--no-tree-tips`로 끔. 마스킹 프리셋 `SkyStep.tree_tips`(기본 true). 리포트 `settings.tree_tips`에 기준값(안 썼으면 null).
- 왜 이 조건(정답 12장, 띠 밖·A 아님): 나무 2,363 px 대 하늘 230,258 px로 하늘이 100배라 거리만으로 빼면 놓침이 폭증(120 px: 5.85 %). 밝기 중앙값 177 대 181로 못 가름. 거칠기 > 12가 나무 96 %, 하늘 2.4 %; 남는 하늘은 색 거리로 거름. 모든 방향 1~3 px 넓히기는 손해(주변 2 px에 나무 419 대 하늘 7,374 px), A 아닌 쪽으로만 1 px가 이득.
- 측정(0022 정답 12장, 사용자 프리셋, 구현 함수로 다시 잼 = 실험 스크립트와 전체 프레임 차이 0 px): IoU 0.9804 → 0.9808, 넘침 0.95 → 0.85 %, 놓침 1.06 → 1.13 %, F@2 0.888 → 0.885. 00489_x2112_y960 넘침 0.78 → 0.21 %, 00429_x768_y768 0.84 → 0.34 %, 00585_x2688_y1152 0.25 → 0.11 %. 기준값은 이 12장에서 정함 → `truth/sky2`로 다시 확인할 것.
- 남은 것: 00155_x384_y1152 넘침 7 %는 솔잎 사이 흰 구름·나무 안 구멍(정답이 작업량 때문에 나무로 둔 곳, 사용자 확인 = 넘침 아님). 놓침 2 %대(00957·00585)는 프리셋에 없는 하늘색 덩어리 → 프레임마다 색을 더하면 놓침 0.35 %까지 줄지만 넘침 2.5 %로 늘어 안 넣음; SAM2 단계 몫(GPU, 학습 뒤 계측).
- 테스트 2개(합성 이미지로 띠 밖 거친 조각만 빠지고 먼 조각·매끈한 판 안쪽·띠 안은 그대로, 띠 끄면 없음; cli 리포트·`--no-tree-tips`·프리셋 필드). 전체 275 통과.

## 111단계 (`v0.4-p111`): `cli sky --color-preset`에 SAM2 마무리

- 사용자 요청(10-08): GPU가 빈 뒤 SAM2 실사용 계측 → "Sam2 없이는 작동하지 않게 하고 GPU를 비워두라고 권고". By Color만으로는 프리셋에 없는 하늘색 덩어리를 놓침(1.13 %, 크롭 최대 2.50 %, `cli sky`의 3배).
- 계측(정답 12장, p110 위, sam2.1 hiera tiny, 최대 VRAM 597 MiB):
  - 사람 흉내 클릭(정답으로 가장 큰 오류 덩어리 한가운데, 나빠지면 Undo): 크롭당 1클릭에 놓침 0.20 %. 놓친 하늘을 Ctrl+클릭하면 SAM2가 하늘 전체를 한 조각으로 잡음. 나무를 빼는 Ctrl+우클릭은 하늘 전체를 잡아 대부분 Undo(소나무 크롭만 효과). 클릭 17 ms, 768 크롭 임베딩 0.19 s.
  - 정답 없이: 확실한 하늘의 가장 안쪽 점 한 번 클릭. 크롭 원본 해상도 1클릭(참고) 놓침 0.25 %; 전체 프레임 1024 축소 1클릭은 경계가 거칠어 넘침 0.61 %(가장자리)·놓침 0.39 %; **원본 해상도 타일 1024·간격 768** 놓침 0.34 %, 가장자리 넘침 0.44 %, 프레임당 14클릭 1.6 s → 채택. 간격 1024(겹침 없음)은 놓침 0.57 %.
  - CPU: 1024 타일 임베딩 1.23 s → 프레임당 약 15 s(GPU의 약 10배).
- `src/core/sky_sam2.py` `sam2_tiles(engine, image, sky, allowed, tile, step, min_depth, max_per)`, 기준값 `SAM2_TILES`(1024, 768, 15 px, 타일당 4점): 하늘이 1~99 %인 타일마다 하늘 조각(큰 것부터 4개, 경계에서 15 px 넘게 안쪽 점이 있는 것)의 가장 안쪽 점에 양성 클릭 하나(앱 Ctrl+클릭과 같음), 최고 점수 조각을 `allowed`(하늘 모델 마스크, 나무 끝 뺀 곳 제외) 안에만 더함.
- `cli sky`: `--color-preset`이면 SAM2 단계가 항상 돎(끄는 옵션 없음). GPU 빈 메모리 1 GB 미만이면 시작 안 함(`SKY_GPU_NEEDED`, 메시지: 학습·뷰어를 끄거나 기다리기), `--cpu`(약 10배 느림)·`--gpu-anyway`. 프리셋 없는 `cli sky`는 전처럼 CPU만. `run`도 하늘에 By Color가 있으면 같은 확인(사람 단계가 있으면 그쪽 5 GB 확인). 리포트 `settings.sam2`(기준값·모델·장치), 장별 `sam2_clicks`. `_device`가 SAM3/SAM2 필요량을 나눠 받음.
- 측정(실제 명령, GPU, 0022 6프레임 50 s = 장당 7.5 s, 장당 10~12클릭): `truth score` IoU 0.9808 → **0.9878**, 넘침 0.85 → 0.93 %, 놓침 1.13 → **0.34 %**, 경계 F@2 0.885 → **0.937**, F@8 0.926 → 0.964. 실험 스크립트와 같은 값.
- 사용자 의견(메모): GPU 없는 환경용으로 SAM2 없이 다른 방식으로 계산하는 프리셋을 따로 둘 수도 있음 → 나중 과제.
- 테스트 4개(가짜 SAM: 타일마다 확실한 하늘에 클릭, `allowed` 안에만 더함, 얇은 하늘은 클릭 안 함, 타일 시작점; cli: SAM2 장치 기록·GPU 바쁘면 거절·`--cpu`·프리셋 없으면 SAM2 안 부름; run: 1 GB 확인). 테스트의 하늘 명령은 가짜 SAM2만 씀.

## 112단계 (`v0.4-p112`): Sky 특수 Object에 마무리(By Color + 나무 끝 + SAM2)

- 사용자 요청(10-08): "앱에도 넣어줘, UX 검증 기획서 쓰고 진행". 기획: 기획서 하늘 페이지 → "하늘 마무리 앱 연결 · UX 검증"(V1–V12, 이 단계 V1–V9).
- `src/core/sky_sam2.py` `finish_sky(full, rgb, color, tree_tips, engine)`: cli의 마무리(By Color → 띠 밖 나무 끝 → SAM2 타일)를 한 함수로, `cli sky`와 앱이 함께 부름. `tips_apply`(나무 끝이 도는 조건), `SKY_SAM2`(tiny 경로), `SKY_GPU_NEEDED`도 여기로.
- `Special.finish`: 마무리 설정을 JSON으로(`name`, By Color 프리셋 **값**, `tree_tips`). 프리셋을 나중에 고치거나 지워도 Object 결과는 그대로. 프로젝트에 저장.
- Properties → Special(Sky): **Finish** 줄 — By Color(Off + 저장된 프리셋, 값이 달라졌으면 "(kept in this Object)"), "Take out tree tips beyond the band"(프리셋의 띠가 켜졌을 때만), 안내 `Finished on N of M covered frame(s)`.
- 무거운 계산은 **Make Sky Masks 때만**: 모델 맵이 없는 프레임 → 모델, 마무리 안 된 프레임 → SAM2 tiny를 따로 올려 마무리하고 내림. 진행 표시, **Stop**(지금 프레임까지, 다시 누르면 이어서). GPU 빈 메모리 1 GB 미만이면 묻기(CPU로 / 취소), CUDA가 없으면 CPU로 알리고 진행.
- 결과는 설정 지문(Threshold·Grow·Refine·Top only·프리셋 값·나무 끝·규칙 상수·SAM2 모델·작업 해상도)별로 `<프로젝트>/special/sky_finished/<지문>/full|work/`에 캐시. 설정을 옮기면 그 설정의 마무리가 없어 모델 마스크가 보이고, 되돌리면 계산 없이 바로 마무리 결과.
- Export(Final Mask, 한 장, 변환): 마무리된 Sky는 캐시된 원본 해상도 마스크를 그대로(`full_mask(..., finished=)`). 마무리 안 된 프레임은 전처럼.
- 검증 V4(실제 GPU, 0022 2장 00585·00957): 앱 Export = `cli sky --color-preset` = p111 출력, **차이 0 px**. 앱 마무리 2장 19 s(SAM2 올리는 시간 포함).
- 테스트 1개(가짜 마무리·가짜 SAM2): 마무리 없음은 전과 같음, 설정만으로는 안 돎, Stop 뒤 이어 하기, 설정 이동/복귀, Export 원본 해상도, GPU 바쁨 → 취소/CPU, 프리셋 변경 뒤 값 유지, 저장, Apply.

## 113단계 (`v0.4-p113`): Batch Masking 창의 하늘 By Color·나무 끝·CPU

- 기획 "하늘 마무리 앱 연결 · UX 검증" V10–V12.
- File › Batch Masking의 Sky 묶음: **By Color**(Off + 앱 By Color 패널의 프리셋, 프리셋 파일에만 있는 값이면 "By Color values in this preset"), **Take out tree tips beyond the band**(그 프리셋의 띠가 켜졌을 때만), 안내(SAM2·GPU 1 GB·장당 약 8 s, GPU가 모자라면 아무것도 안 쓰고 멈춤). 고른 프리셋의 **값**이 마스킹 프리셋 `sky.color`·`sky.tree_tips`로 들어감(Save as Preset, Run, Copy Command 모두).
- **Run on the CPU (slow)** 체크 → `run`/`probe`/Copy Command에 `--cpu`. 하늘에 By Color가 있으면 "이 창의 SAM 모델 먼저 내리기"도 적용.
- `cli run --cpu`: 사람 또는 By Color 하늘이 있으면 시작할 때 "On the CPU: much slower…" 한 줄.
- 테스트: 창(프리셋 고르기·나무 끝 활성 조건·저장 값·`--cpu`·앱 프리셋이 바뀐 뒤 값 유지), `run --cpu` 안내.
- 화면 확인(오프스크린 캡처): Sky 특수 Object의 Finish 줄, Batch Masking의 Sky 묶음. 창 왼쪽 칸이 원래부터 가로로 잘려 스크롤이 생김 → `ui-issues.md` 메모.

## 114단계 (`v0.4-p114`): Batch Masking 창 왼쪽 칸 잘림

- 사용자 요청(10-08). 원인: 왼쪽 칸 기본 폭 430 px < 내용 최소 폭 468 px(긴 체크박스 글: Run on the CPU…, Sub-folders too…, Unload this window's SAM models…).
- 체크박스 글을 짧게(`Sub-folders too (cam0/, cam1/)`, `Unload the app's SAM models first`, `Run on the CPU (slow)`), 설명은 툴팁으로. 프리셋·By Color 목록은 긴 이름이 칸을 넓히지 않게(14자 기준).
- 왼쪽 칸 최소 폭 = 내용 최소 폭(프리셋을 바꿀 때마다 다시 맞춤), 가로 스크롤 없음, 접히지 않음. 창을 줄이면 오른쪽(접촉 시트·출력)이 줄어듦. 1100 px 창에서 왼쪽 463 px.
- 테스트 1개(두 창 크기에서 내용 폭 ≤ 보이는 폭, 가로 스크롤 없음).

## 115단계 (`v0.4-p115`): Export 창 가독성

- 사용자 요청(10-08) "익스포트 패널 가독성이 좀 떨어지는데" → 기획(기획서 하위 문서 "Export 창 가독성 개선", 문제 EX-1~12) → 추천안대로(C-1 (a) · C-2 (a) · C-3 (a)).
- 한 줄로 쌓이던 칸을 구역 넷으로: **1 What**(Mask) → **2 Where**(For, 프리셋 설명, Output, Dataset, Cameras) → **3 Files**(Folder, Names, Sky) → **✓ Check**(요약, 문제 목록). 장면이 아니면 Where가 없고, 세트 기능이 없으면 What이 없음(번호는 보이는 것대로).
- 프리셋이 정한 Folder·Names·흑백·빈 마스크는 회색 입력칸 대신 읽는 글 + `preset` 표시. Custom이면 입력칸(Invert, Also empty masks는 한 줄).
- 프리셋 설명은 첫 문장 + More ▸(펼치면 전문: 이름 규칙 따름, 백업, 확인 근거). 경로는 앞을 줄여 끝(폴더 이름)이 보이게, 전체는 툴팁.
- New dataset의 Pinhole 설정은 한 줄 요약(`Yaw … · Pitch … · FOV 90° · Size auto → 9 views per image`) + Edit ▸(칸: Layout / Yaw / Pitch / FOV / Size, 지도). More·Edit을 연 상태는 앱을 끌 때까지 기억.
- Dataset 경로 줄은 New dataset일 때만, 세트 폴더 안내는 내용이 있을 때만(빈 줄 없음). Sky edges는 Files의 `Sky` 줄.
- 문제 목록 사유를 말로: `no mask → no file`, `empty mask`, `suspicious or failed (⚠ ✕)`, `file name clash`.
- Export 버튼: `Export 183 files → masks_postshot/`, `Export 1,566 files → new dataset`, 세트 전부면 `Export → 2 folders`. 쓸 파일이 0이면 비활성.
- 잘림(EX-3·4): 창 높이를 실제 폭에서 줄바꿈된 글 높이로 맞춤(열 때, 폭이 바뀔 때, 검사가 바뀔 때). 화면보다 길면(1280×720 등) 구역만 세로 스크롤, 버튼은 고정. 가로로는 잘리지 않게 최소 폭 = 내용 최소 폭.
- C-3: 뷰 배치 설명(`VIEW_LAYOUTS` purpose 4개)과 Custom 툴팁의 한국어를 영어로(UI 이슈 목록 2026-10-01 항목).
- 동작·저장 값은 그대로(위젯 이름 유지). 테스트: ERP 테스트는 Edit을 연 뒤 yaw 칸 확인, 새 테스트 1개(구역 순서, 프리셋 글 / Custom 칸, More, 버튼 글, 사유 글, 잘림 없음). 전체 284 통과.

## 116단계 (`v0.4-p116`): Export 창 Every set · 360 장면 확인 후 손질

- 사용자 요청(10-08): p115 창을 Every set과 360 장면에서도 캡처해 확인. 실제 장면(0022 어안 186장, `a0920_360_Plugin` EQUIRECTANGULAR 49장)을 읽기만 해서 캡처.
- Mask 목록의 `Every set, one folder each (and the Final Mask)`가 잘림 → `Every set + the Final Mask`(폴더 규칙은 툴팁).
- Pinhole 한 줄 요약 아래 빈 공간(약 45 px)과 처진 Edit 버튼: 폼의 이름 붙은 줄이 줄바꿈 글을 좁은 기본 크기(높이 60)로 잡던 것 → 요약은 전체 폭 줄, Edit은 Cameras 줄 오른쪽.
- 확인한 것: 세트 하나 `Export 186 files → masks_people/`, Every set `Export → 3 folders`와 폴더 목록, 360 장면 `COLMAP Overlap · 12 Views … → 12 views`, 버튼 `Export 564 files → new dataset`(49 − ⊘ 2 = 47장 × 12).
- 테스트 1개(Every set 이름이 다 보임, 요약 줄에 빈 공간 없음). 전체 285 통과.

## 117단계 (`v0.4-p117`): 내보내기 세트 1 — 바 데이터, 바 / Object별 Invert 계산

- 사용자 결정(10-08, 기획서 Export 9장): 여러 마스크를 바로 쌓아 내보내기. 바마다 Invert, 바 안에서 Object마다 ⇆ Invert(C-8 (a)). Remove / Keep 같은 뜻 라벨은 두지 않음(마스크는 흑백 데이터).
- `MaskBar`(이름, Objects — None = 체크된 Objects, Invert — None = 프리셋 값, 뒤집을 Objects, 켬): 작업 파일 `mask_bars`에 저장, Undo 한 단계. 아직 바가 없으면 Final + 옛 세트(꺼짐)로 시작(`bars_or_default`).
- 계산 순서: ① ⇆ Object는 원본 해상도로 만든 뒤(Sky 경계 포함) 뒤집음, 그 이미지에 마스크가 없으면 이미지 전체 ② 합집합 ③ 바의 Invert. 원본 Object 마스크는 그대로. `full_mask` · `final_mask` · `keys_with_masks` · `check_export` · `ExportOptions.flipped`, 변환 Export(Pinhole / 360)도 같은 계산.
- 테스트 3개(중간 마스크를 따로 계산해 대조, 쓴 PNG 픽셀, 저장 / 불러오기 / Undo). 전체 288 통과. 창(바 UI)은 다음 단계.

## 118단계 (`v0.4-p118`): 내보내기 세트 2 — Export 창 1 What을 마스크 줄로

- 1 What의 Mask 목록 · `Save Checked as Set…` · `Delete Set` · Every set을 **마스크 줄**로 바꿈. 줄: ☑(이번에 쓸지) · 이름 · Objects 버튼(Checked Objects 또는 고르기, Object마다 ⇆ Invert) · Invert · ✕(오른쪽 클릭 Duplicate). `+ Add mask` = 지금 체크한 Objects로 새 줄.
- 줄 1개: 이름 칸 흐림, ☑ · ✕ 숨김, 폴더 그대로(C-7). 2개 이상: `<폴더>_<이름>/`, 이름을 비우면 폴더 그대로. 같은 폴더로 가는 이름 · 폴더에 못 쓰는 글자는 빨간 테두리 + 검사 ⚠ + Export 꺼짐.
- Invert 처음 값은 For 프리셋(Brush 등 켬, Postshot 끔), 줄에서 바꾸면 그 값. 프리셋과 다르면 검사에 “Brush ignores the black parts, so these Objects are trained …” 한 줄(C-6). Files 구역의 Invert 칸은 없앰.
- 검사 · 버튼이 켠 줄 전체를 셈: `Export 558 files → 3 folders`, 줄마다 한 줄(파일 수, 빈 마스크, ⚠ ✕), 문제 목록에 폴더 이름. 백업 안내도 폴더마다.
- 줄은 창을 닫을 때(Export든 Cancel이든) 장면에 저장, Undo 한 단계(C-4). 옛 작업 파일의 세트는 꺼진 줄로 나옴.
- Postshot처럼 규칙이 확인 안 된 프리셋은 설명 전문을 처음부터 펼침(S-6, `Preset.confirmed`).
- 기획 9.4의 “배치 마스킹 · CLI가 세트를 읽게”는 해당 없음: CLI(`run` · `sky` · `person` · `lens`)는 마스크를 직접 만들어 쓰고 작업 파일의 세트를 쓰지 않음.
- 0022 장면(읽기만)으로 줄 1 · 3개, Objects 목록 캡처: 잘림 없음. Objects 버튼 글 왼쪽 정렬, 고르지 않은 Object의 ⇆는 꺼짐, 폴더 안내 문구 손질.
- 테스트: 옛 세트 · Every set 테스트 3개를 줄 방식으로 바꿈(⇆ + Invert 결과 픽셀, 이름 충돌, 저장 · Undo, 창을 닫으면 저장, 프리셋 따라가는 Invert와 ⚠). 전체 288 통과.

## 119단계 (`v0.4-p119`): 명령줄 약속 문서, 포터블을 앱 · 런타임 · 모델로 나누기

- splatbatch 세션 요청(DEPLOY_PLAN 3.3 · 6장): `docs/CLI_CONTRACT.md` 약속 1(`run` 옵션 · 출력 폴더와 흑백 · 파일 이름 · 이미 있는 마스크 · 종료 코드 · 보고서 키, `preset list` / `show --json`). 번호는 `src/version.py`의 `CLI_CONTRACT`, 바뀌면 올리고 "3DGS 하늘 학습" 세션에 알림.
- `tools/make_portable.py --split`: 포터블 폴더 옆에 `sms-<버전>-app.zip`(src · docs · bat · README · `PARTS.json`, 몇 MB), `sms-runtime-<해시>.zip`(python\), `sms-models-<해시>.zip`(app\checkpoints\), `sms-<버전>-parts.json`(이름 · 크기 · sha256 · 약속 번호). 셋 다 포터블 루트 기준이라 한 폴더에 풀면 지금 포터블과 같음. 해시는 파일 경로 + 크기라 의존성 · 가중치가 같으면 이름이 같고, 이미 있는 zip은 다시 쓰지 않음.
- 빌드 · 업로드는 하지 않음(요청 때만). 테스트 1개(가짜 포터블: 파일이 정확히 한 묶음씩, 다시 풀면 같음, 같은 런타임은 이름 유지 · 다시 안 씀, 가중치가 바뀌면 새 이름).

## 120단계 (`v0.4-p120`): SAM을 CPU로 (학습 중 GPU 비워 두기)

- splatbatch 세션 요청(PLAN 8장 열린 항목), 사용자 결정(10-08): 학습이 GPU를 쓰는 동안 앱을 열어 브러시로 손질.
- File → Settings… → **Run SAM on the CPU**(`use_cpu`, 저장됨), 또는 이번 한 번만 `python -m src.main --cpu` / `run.bat --cpu` / 포터블 `SAM Mask Studio (CPU).bat`(새 launcher).
- 켜면 SAM2(폴더를 열 때 로드, 클릭, 전파), SAM3(Detect), Sky 마무리 SAM2가 CPU. Sky 마무리는 GPU 빈 메모리를 묻지도 않음(묻는 것만으로 GPU 메모리를 조금 씀). Batch Masking 창의 `Run on the CPU`가 처음부터 켜짐. 창 제목에 `(CPU)`. Settings에서 바꾸면 SAM2를 그 장치로 다시 올림.
- 테스트 1개(가짜 엔진: --cpu와 Settings 두 길, 엔진 장치, Sky 마무리가 GPU를 안 물음, Batch 창 체크, 바꾸면 다시 로드 · 저장). 전체 290 통과.

## 121단계 (`v0.4-p121`): 피시아이 장면에도 Pinhole 뷰 배치 목록 (기획 Export 10장 V-1)

- 사용자 지적(10-08) "배치 프리셋 5개가 지금은 없음": Layout 줄이 360 원본일 때만 보였음. 사용자 결정 C-9 (a): 피시아이에는 렌즈용 배치만.
- `ViewLayout.points`(낱개 방향), `FISHEYE_LAYOUTS`: **Fisheye Grid · 9 Views**(기본, 전의 격자와 같음) · **Fisheye Cross · 5 Views** · **Fisheye Level · 3 Views** + Custom. `ALL_LAYOUTS`.
- `overlap`을 고도별 가장 가까운 yaw 간격 + 고도 간격으로 일반화(360 배치 값 그대로).
- Export 창: 변환 종류마다 Layout 목록을 다시 채우고 고른 것을 기억. 0022 두 렌즈에서 세 배치 모두 view_share 1.0(회색 뷰 없음).
- 문서: specs/08 8.2, 매뉴얼 C9 · D 참조. 테스트 2개(배치 규칙, 피시아이 장면 목록 · 뷰 수 9 / 5 / 3 · 빠지는 뷰 없음 · 기억). 전체 292 통과.

## 122단계 (`v0.4-p122`): 카메라 짝 → Pinhole 뷰 (기획 Export 10장 V-2)

- 사용자 결정 C-10 (a)(10-08): 렌즈에서 바로(보간 한 번), 두 렌즈에 걸친 뷰만 이음.
- `stitch_to_erp`에 `views`: 출력이 360 한 장 대신 360 배치의 Pinhole 뷰. 뷰마다 렌즈별 표를 기억(렌즈가 안 보는 뷰는 표 없음), 마스크 · 점 · 포즈 같은 규칙.
- Export 창: **Pinhole views from camera pairs (N moments)**, Layout 목록 = 360 배치(COLMAP · 12 기본), 요약 · 노트는 "per moment", 결과 줄 "N moment(s) × k pinhole views", 로그 "pinhole view(s)".
- 0022 실물 2순간 × 12 = 24장, 빠진 뷰 0, 51초(CPU). 아래쪽 옆 뷰에 옅은 이음선(360 이음과 같은 섞기).
- 문서: specs/08 8.3, 매뉴얼 C10 · D. 테스트 2개(가짜 리그: 뷰 이름 · 색 · 걸친 뷰 · 한 렌즈 뷰 = 단독 재투영 픽셀 동일 · 포즈 · 점 투영 · 마스크, Export 창 목록 · 기억 · 실행). 전체 294 통과.

## 123단계 (`v0.4-p123`): Export 마스크 줄마다 썸네일 미리보기

- 사용자 요청(10-08): “선택 및 반전 세팅에 따라 마스크가 어떻게 달라지는지 썸네일 등으로 프리뷰 필수”.
- 줄 오른쪽에 그 줄이 쓸 흑백 마스크(긴 변 96 px): 지금 프레임, 거기 아무 마스크도 없으면 마스크가 있는 첫 프레임. Objects · ⇆ · Invert를 바꾸면 바로 바뀜. 툴팁 = 프레임 이름.
- `ExportDialog(preview=, preview_frame=, preview_size=)`, main_window가 `full_mask`를 작은 크기로 넘김(⇆ 규칙 같음), (Objects, ⇆)마다 캐시하고 Invert는 뒤집기만. Sky 가장자리 다시 정하기는 미리보기에 없음.
- 테스트 1개(줄 미리보기 = full_mask 합집합, 한 Object, Invert = 뒤집힘, ⇆ + Invert, 썸네일 픽셀이 따라감, preview 없으면 숨김). 전체 295 통과.

## 124단계 (`v0.4-p124`): 가상 카메라 배치 그림 (Export 창 + 참고 그림)

- 사용자 요청(10-08): “실제로 핀홀 변환 시 가상 퍼스펙 카메라 배치가 어떻게 되는지 가독성 좋은 참고 이미지 필수”.
- Export 창 지도 옆에 3D 그림(`RigPreview`): 구 위 번호 타일(지도와 같은 번호 · 줄 색), 앞쪽 왼편 위 시점, front / right / up 표시, 피시아이 렌즈 끝 · 카메라 짝 이음 원은 빨강. 지도도 줄 색 + 번호.
- `tools/layout_pictures.py`: 배치 7개의 참고 그림(지도 + 3D + 설명) → `docs/manual/img/layout_*.png`, 매뉴얼 C8 · C9 · C10 · D, specs/08 8.4.
- 시점은 뒤에서 / 앞에서 6가지를 그려 비교해 정함(뒤에서는 정면 뷰가 겹쳐 안 읽힘).
- 테스트: 타일 방향 · 프러스텀 크기 · 색, 참고 그림 7장, Export 창의 3D 그림 원본 종류(360 / fisheye / pairs). 전체 296 통과.

## 125단계 (`v0.4-p125`): Frame List 가운데 더블클릭도 고른 프레임 유지

- 사용자 메모(10-08, L 점검 중): 가운데 버튼 더블클릭이 복수 선택을 지우지 않고 그 프레임만 열게.
- 원인: 더블클릭의 두 번째 누름은 `MouseButtonDblClick`으로 와서 가운데 클릭 처리(선택 그대로, 현재 프레임만 이동)를 거치지 않고 기본 선택 동작을 탔음. 둘 다 같은 처리로.
- 테스트: 가운데 클릭 테스트에 더블클릭 추가(고치기 전 실패 확인). 단축키 창 · 매뉴얼 D. 전체 296 통과.

## 126단계 (`v0.4-p126`): `person --keyframes N` (키프레임 SAM3 + SAM2 전파, 사람 마스크 P3)

- 사용자 제안(10-08): 손으로 사람을 마스킹할 때처럼 전파로 빠르게. 지금 `person`은 모든 프레임에 SAM3(장당 1.9초).
- `person --keyframes N`: 카메라 폴더마다 N장마다(와 마지막) SAM3, SAM3를 내린 뒤 앱의 전파(`src/engine/video.py` `propagate`, SAM2 tiny, 앱과 같은 모델)로 키프레임 앞뒤를 채움. 두 키프레임 사이 프레임 = 양쪽 전파의 합집합. 키프레임 마스크는 조각(연결 요소)마다 SAM2 물체 하나, 프레임의 0.05 % 미만 조각은 넣지 않음. 넓히기(`grow`)는 전파 뒤에 모든 프레임에 같게.
- 기본값 0 = 지금 방식 그대로(명령줄 약속 1 · `run` · 프리셋은 그대로). `--skip-existing`일 때 이미 있는 프레임만 걸친 키프레임은 SAM2를 돌리지 않음. 보고서: `settings.keyframes`, `keyframe_count`, 프레임마다 `from_keyframes`.
- `src/core/people.py`: `grow_mask`로 넓히기를 뗌(`people_mask` 결과는 같음).
- 테스트(fake 엔진 · fake 전파): 키프레임 고르기, 조각, SAM3는 키프레임만 · SAM2 전에 내림, 사이 프레임 = 양쪽 합집합, 이미 있는 프레임 건너뛰기, 명령줄 옵션. 전체 300 통과.
- 측정(0022 cam0 94장, N = 0 · 5 · 10 · 20)은 GPU 차례(⑥ 준비 구간 뒤)와 사용자 확인 뒤.

## v0.4-p127 — 렌즈 가장자리 여유 2 % → 5 % (2026-10-09)
- 계기: SplatBatch 보고, 0022에서 `run` 마스크로 정합이 2–4 모델로 갈라짐(53–56 %), 바깥 띠를 검게 하면 188/188.
- 측정(0022 cam0 · cam1 각 10장, CPU, 찾은 원 기준): 원은 내접원의 105.2 / 105.5 %(프레임 밖까지). 선명도 · SIFT 점은 원의 0.95까지 그대로, 0.95–0.96에서 점 20 → 5, 0.96 이후 1.5 아래. 2 % 여유는 0.98부터만 가려 그 흐린 띠가 남았음. Spirula 9/29 마스크는 0.90–0.96에 걸쳐 가림.
- `src.core.special.LENS_MARGIN = 5.0`: `cli lens` · `run` 기본, `LensStep` 기본, 내장 프리셋 `osmo360-selfie-stick` 5.0.
- 앱 Lens edge **Detect**도 같은 여유를 빼서 반지름을 둠(전엔 찾은 원 그대로). 로그에 찾은 원과 가리는 반지름 둘 다.
- 명령줄 약속 **2**(`docs/CLI_CONTRACT.md`): 옵션 · 폴더 · 이름은 그대로, 렌즈 마스크 기본만 넓어짐.
- 테스트 301개 통과(Detect 여유 테스트 추가).

## 128단계 (`v0.4-p128`): `person --split DIR` (촬영자만 `--out`, 다른 사람은 따로, 사람 마스크 P4 1단계)

- 사용자 요청(10-09): 촬영자만 늘 지우고 나머지 사람은 따로. 2단계는 A안(명령줄에서 사람별 폴더)으로 결정. 기획: person.html 6.2.
- `src/core/people.py` `split_people`: (촬영자, 다른 사람). 촬영자 = `person`이 아닌 라벨(셀카봉) + 봉에 닿은 사람(봉이 없으면 높이 0.85 아래까지 내려온 사람) + 그 사람·봉에 닿거나 내접원 0.9 밖에 걸친 손(반대쪽 렌즈의 손가락) + 닿은 가방. 다른 사람의 손 안에 반 이상 들어간 손은 그 사람 몫. 합치면 `people_mask`와 같음.
- `person --split DIR`: `--out`에는 촬영자만, DIR에는 다른 사람(검정 = 사람, 같은 이름). `--hands`(기본 `hand`, `""` = 없음)는 `--split`일 때만 SAM3에 물음. DIR에 이미 마스크가 있으면 `--out`과 같이 멈춤. 보고서 `settings.split` · `hands`, 프레임마다 `others`.
- `--keyframes`와 함께: 키프레임 마스크를 층 둘로 전파(조각마다 어느 층인지 기억), 사이 프레임도 둘이 섞이지 않음.
- 옵션을 안 주면 그대로: 명령줄 약속 · `run` · 프리셋 그대로.
- 테스트(fake): 판정(봉 · 가방 · 가장자리 손 · 남의 손 · 떨어진 손 · 봉 없을 때), 명령줄 `--split` · `--hands ""` · 기존 폴더 멈춤, 키프레임 전파에서 둘이 따로. 전체 304 통과.
- 측정(0022 cam0 · cam1에서 판정 오류 장수, 가장자리 띠 손가락)은 P3 측정과 함께 GPU 차례에.

## v0.4-p129 — OSMO 프리셋 렌즈 원 고정 (2026-10-09)
- 사용자 결정: 경계 띠는 렌즈 왜곡 문제라 SMS가 따로 재지 않고, 정합으로 확인된 값을 받아 OSMO 프리셋에 씀. 사용자가 직접 검수.
- `osmo360-selfie-stick` 렌즈: `radius 95.0, cx 0, cy 0, margin 0`(원 고정) = SplatBatch rim95(0022 Spirula dev 정합 188/188 두 번, 찾은 원의 0.90). 2 % 여유는 106/188.
- 비교로 Spirula 자동 마스크 원을 다시 맞춤: 반지름 98.0 %, 중심 +0.34 / −3.16 %(61 px 위), 두 카메라 같음, 186/188.
- 일반 기본 여유 5 %(p127)는 그대로. 프리셋 내용만 바뀌어 약속 번호는 2 그대로.
- 스터디 페이지 `lensrim.html`(sms.html 아래, 그림 · 검수 R1–R4).
- 테스트 304개 통과(프리셋 원 값 확인 추가).

## 반영 안 함 (리뷰 평가 결과)
- 전파 Preview 단계: 결과가 바로 Undo 되고 Cancel이 결과를 버리므로 이미 같은 효과
- Frame List와 하단 줄 통합: 역할이 이미 나뉨(목록 = 이동, 줄 = 썸네일)
- 내부 구조 개편: 이미 Object × Frame × Mask 구조
- Object 단위 작업 기록: 비용 대비 효과 낮음
- 나중 과제: Sky 전용 분할 모델(Sky Object 타입), COLMAP 연동
