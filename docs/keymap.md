# 키맵

지금 쓰이는 단축키와 비어 있는 키, 새 단축키 제안을 한곳에 모아두는 문서입니다.

- 앱 안의 전체 목록(F1)은 `src/app/dialogs.py`의 `SHORTCUTS`가 원본입니다. 키를 바꾸면 그 표와 이 문서를 같이 고칩니다.
- 새 단축키 아이디어는 맨 아래 "제안"에 적습니다. 결정되면 "현재 키맵"으로 옮깁니다.
- 모든 키는 메뉴 바(File / Edit / View / Go / Help)에도 항목 오른쪽에 표시됩니다: [`menu-design.md`](menu-design.md).
- 기준: v0.4.0 + `v0.4-p14` (2026-09-29).

## 한눈에 보기 (글자 키)

```text
 Q  W  E  R  T  Y  U  I  O  P  [  ]
 ·  ·  E  R  ·  ·  ·  ·  O  ·  [  ]        E Points 편집   R Show Changes   O Outline   [ ] 문제 프레임

  A  S  D  F  G  H  J  K  L  ;  '
  A  S  D  F  ·  ·  ·  ·  ·  ·  ·          A 오토 툴 선택   S 스크롤   D Paint   F 기준(◎)으로

   Z  X  C  V  B  N  M  ,  .  /
   Z  X  ·  V  ·  N  ·  ,  .  ·            Z 잠깐 보기   X Mask Preview   V Final↔Object   N New Object   , . 키프레임
```

`·` = 비어 있음. 비어 있는 글자: **Q W T Y U I P G H J K L C B M** 과 **/ ; '**, 숫자, Home / End, Tab.
(`W`는 목록 위에 마우스가 있을 때만 이동 키: 아래 "이동". 그때는 `A` `S` `D`도 이동으로 바뀝니다.)

## 현재 키맵

### 파일 · 편집

| 키 | 동작 | 언제 |
|---|---|---|
| Ctrl+O / Ctrl+S / Ctrl+E | 폴더 열기 / 저장 / Export | 항상 |
| Ctrl+Q | 종료 | 항상 |
| Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) | Undo / Redo | 항상 |
| N | New Object (포인트로) | 항상 |
| E | 선택한 Object 포인트 편집 시작 / 끝내기 | 항상 |
| Delete | 선택한 포인트 삭제, 없으면 선택한 Object 삭제 | 항상 |
| Esc | 도구 나가기(오토 툴 결과 버림) → 편집 끝내기 | 편집 중 |
| Enter | 오토 툴 Apply & Continue (오토 툴이 꺼져 있으면 기준 ◎ 지정, 아래 "이동") | 오토 툴 |

### 이동

| 키 | 동작 | 언제 |
|---|---|---|
| ← / → (PgUp / PgDn) | 이전 / 다음 프레임 | 편집 중이 아닐 때 |
| ↑ / ↓ | 이 프레임에 마스크가 있는 이전 / 다음 Object (편집도 따라감) | 항상 |
| W A ↑ ← / S D ↓ → | 이전 / 다음 프레임 (목록 위에서는 `S`도 "다음", 스크롤 아님) | 마우스가 Frame List / Frames 줄 위 |
| W A ↑ ← / S D ↓ → | 이전 / 다음 Object 행 (Show all로 보이는 행 포함, 편집도 따라감) | 마우스가 Objects 목록 위 |
| S (또는 ⌖ 버튼) | Frame List와 Frames 줄을 **현재 프레임**으로 스크롤 | 항상 |
| [ / ] | 이전 / 다음 문제 프레임(⚠ ✕, `1` 켜면 `–`도) | 항상 |
| , / . | 가장 가까운 이전 / 다음 키프레임(★ = 직접 편집한, 전파 소스). `1` 켜면 선택한 Object의 ★만 | 항상 |
| F | 전파 기준(◎, 더블클릭한 프레임)으로 이동 | 항상 |
| Enter | 현재 프레임을 전파 기준(◎)으로 지정, 기준에서 다시 누르면 해제 (더블클릭과 같음) | 오토 툴이 꺼져 있을 때 |
| 더블클릭 (프레임) | 전파 기준(◎)으로 지정, 다시 하면 해제 | 목록 |
| Shift / Ctrl+클릭 (프레임) | 여러 프레임 선택(전파 Selection 범위) | 목록 |

### 보기

| 키 | 동작 |
|---|---|
| Z (누르고 있기) | Mask Preview 잠깐 보기 |
| X | Mask Preview(흑백) 켜기 / 끄기 |
| V | Mask Preview 대상 전환: Final Mask ↔ 선택한 Object (툴바 `Preview: Final / Object` 버튼) |
| O | Outline 켜기 / 끄기 |
| R | Show Changes(에딧 레이어 초록 / 빨강) 켜기 / 끄기 |
| 휠 / 가운데 드래그 · Space+드래그 | 확대·축소 / 이동 |
| F1 | 단축키 전체 목록 |

### 이미지 위 (편집 중)

| 키 | 동작 |
|---|---|
| 좌클릭 / 우클릭 / 드래그 | Positive / Negative 포인트 / Box (Region Box 켜면 영역 추가) |
| 포인트 드래그 / 더블클릭 | 포인트 이동 / 삭제 |
| D | Paint 브러쉬 켜기 / 끄기 |
| A | 오토 툴: Fill → 전체 선택된 Paint 모드, Paint 모드에서 전체 선택 / 해제 |
| Alt+드래그 | Paint 빼기 · 오토 툴 선택 해제 · Region Box 빼기 |
| Shift+드래그 | 브러쉬를 켜지 않고 칠하기 |
| Ctrl+휠 / Shift+휠 | 브러쉬 크기 |

### Select on Image (디텍션 후보 고르기)

| 키 | 동작 |
|---|---|
| 클릭 / 드래그 | 후보 추가 |
| Shift+클릭 / 드래그 | 토글 |
| Ctrl+클릭 / 드래그 | 빼기 |

## 제안 (아직 구현 안 함)

| 제안 키 | 동작 | 출처 / 메모 |
|---|---|---|
| Home / End | 첫 / 마지막 프레임 | 후보 |

## 변경 기록

- `v0.4-p8`: `,` / `.` 키프레임 이동, `F` 기준(◎)으로 이동 추가, Show Changes `F` → `R`, Final Mask 미리보기 → Mask Preview + `V` 대상 전환.
- `v0.4-p9`: `Enter`(오토 툴 없을 때) = 현재 프레임을 기준(◎)으로 지정 / 해제.
- `v0.4-p13`: 마우스를 올린 목록 기준 `W A S D` / 화살표. Frame List · Frames 줄 위 = 프레임, Objects 목록 위 = Object. 목록 위에서 `S` = 다음(스크롤은 ⌖ 버튼이나 목록 밖에서 `S`). Shift / Ctrl+화살표는 목록의 여러 칸 선택 그대로.
- `v0.4-p14`: 모든 단축키를 메뉴 항목(QAction)으로 옮김. `Ctrl+Q` 종료 추가.
