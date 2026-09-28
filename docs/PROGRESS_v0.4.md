# SAM Mask Studio v0.4 진행 현황

외부(GPT) UX 리뷰 중 코드와 대조해서 타당했던 항목만 반영합니다. v0.3 기록: [`PROGRESS_v0.3.md`](PROGRESS_v0.3.md)

적어두는 곳: 기능 아이디어 [`ideas.md`](ideas.md) · 작은 UI 문제 [`ui-issues.md`](ui-issues.md)

- 브랜치 `dev`에서 단계별 브랜치(`feat/v04-pN-…`)로 작업 → `--no-ff` 병합 → 태그 `v0.4-pN`.
- 되돌리기: 단계 전체 `git revert -m 1 <병합 커밋>`
- 실행: `SAM Mask Studio (dev).bat` = 최신 dev, `SAM Mask Studio.bat` = 안정판 v0.3.0

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

### 5단계 · UI 점검 버그 (`v0.4-p5`, 목록: [`ui-issues.md`](ui-issues.md) 1~6)
- Batch 탭 `Run on Images` / `Stop` / `Cancel`이 너비 0으로 사라지던 문제: 좁은 칸용 버튼 정책을 `Ignored` → `Preferred` + 최소 24px(`ui_util.shrinkable`). 오토 툴 버튼 줄도 같은 방식.
- Frames 줄 개수 요약이 세로로 쌓이던 문제: 줄바꿈은 Frame List 쪽만.
- Frames 줄 썸네일 아래 ID·표시가 잘리던 문제: 목록 최소 높이 = 칸 + 스크롤바, 기본 높이 150 → 190.
- Frame List 10번부터 줄이 밀리던 문제: ID(오른쪽 정렬) / 표시 / 이름을 고정 칸으로 직접 그림. 선택 행 글자색도 창 활성 상태에 맞춤.
- 글자 잘림: Detection `Select All` / `Select None` → `All` / `None`, 버튼 비율 조정. 왼쪽 탭은 스크롤 화살표 대신 이름 줄임.
- 옛 이름 `Images list` → `Frame List` (Propagation / Batch 문구).

### 6단계 · UI 점검 개선 (`v0.4-p6`, [`ui-issues.md`](ui-issues.md) 7~12, 14, 15)
- 패널 폭이 상태에 따라 바뀌던 문제: 원인은 (1) 작업 상태 바의 긴 글자가 캔버스 최소 폭이 됨, (2) 디텍션 안내 한 줄이 왼쪽 칸 최소 폭이 됨. 상태 바는 넘치면 잘리게, 안내 문구는 줄바꿈.
- 작업 상태 바 순서: `Frame │ Object │ Mode │ 파일 이름(회색)` — 좁으면 파일 이름부터 잘림. `Region Box` → `+ Region`.
- 캔버스 왼쪽 위 배너 제거(작업 상태 바와 중복, 작업 중에도 남던 `Select on Image` 안내 포함). Final Mask 미리보기 표시는 유지.
- Properties: 선택이 없으면 제목과 안내만 위쪽에 (빈 Variants/Points, 회색 도구 숨김).
- Propagation 탭: 진행 막대와 Objects / Frames 목록은 첫 실행부터 보임. `Propagate` 버튼은 한 줄 전체, Stop / Cancel / Resume은 그 아래 줄.
- Batch 탭: 진행 막대와 결과 목록은 첫 실행부터 보임(폴더를 열면 다시 숨김).
- 오토 툴 Settings 상자는 지금 도구의 설정 높이에 맞춤(빈 공간 제거).
- Fill / Paint 모드 설명을 한두 줄로 줄임.

## 진행 예정
- 없음 (v0.4 리뷰 반영 1~4단계 완료). 릴리스(`main` 병합, `v0.4.0` 태그)는 확인 후 진행.

## 반영 안 함 (리뷰 평가 결과)
- 전파 Preview 단계: 결과가 바로 Undo 되고 Cancel이 결과를 버리므로 이미 같은 효과
- Frame List와 하단 줄 통합: 역할이 이미 나뉨(목록 = 이동, 줄 = 썸네일)
- 내부 구조 개편: 이미 Object × Frame × Mask 구조
- Object 단위 작업 기록: 비용 대비 효과 낮음
- 나중 과제: Sky 전용 분할 모델(Sky Object 타입), COLMAP 연동
