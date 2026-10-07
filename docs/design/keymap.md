# 키맵

지금 쓰이는 단축키와 비어 있는 키, 새 단축키 제안을 한곳에 모아두는 문서입니다.

- 앱 안의 전체 목록(F1)은 `src/app/dialogs.py`의 `SHORTCUTS`가 원본입니다. 키를 바꾸면 그 표와 이 문서, 설명서의 단축키 표
  ([`manual/04-reference.md`](../manual/04-reference.md) D8)를 같이 고칩니다.
- 새 단축키 아이디어는 맨 아래 "제안"에 적습니다. 결정되면 "현재 키맵"으로 옮깁니다.
- 모든 키는 메뉴 바(File / Edit / View / Go / Help)에도 항목 오른쪽에 표시됩니다: [`menu-design.md`](menu-design.md).
- 기준: `v0.5.0` (2026-10-01).

## 한눈에 보기 (글자 키)

```text
 Q  W  E  R  T  Y  U  I  O  P  [  ]
 Q  ·  E  R  ·  ·  ·  ·  O  ·  [  ]        Q Solo   E 포인트 편집   R Show Changes   O Outline   [ ] 문제 프레임

  A  S  D  F  G  H  J  K  L  ;  '
  A  S  D  F  G  H  ·  ·  ·  ·  ·          오토 툴: A 취소  S Fill  D Paint  F Apply & Close  G Apply & Continue
                                            그 밖: D 브러쉬   F 기준(◎)으로   H Hide Masks

   Z  X  C  V  B  N  M  ,  .  /
   Z  X  C  V  ·  N  ·  ,  .  ·            Z 잠깐 보기   X 흑백(Final↔Object)   C 잘라보기(안↔밖)   V Mask Preview   N New Object   , . 키프레임
```

`·` = 비어 있음. 비어 있는 글자: **W T Y U I P J K L B M** 과 **/ ; '**, 숫자, Home / End, Tab. (`` ` ``는 Q와 같은 Solo.)
(`S` `G`는 오토 툴이 켜져 있을 때만. `W` `S`는 마우스가 목록이나 캔버스 위에 있을 때 이동 키: 아래 "이동". 목록 위에서는 `A` `D`도 이동으로 바뀝니다.
Shift+A = 오토 툴 전체 선택 / 해제.)

## 현재 키맵

### 파일 · 편집

| 키 | 동작 | 언제 |
|---|---|---|
| Ctrl+O / Ctrl+S / Ctrl+E | 폴더 열기 / 저장 / Export | 항상 |
| Ctrl+Z / Ctrl+Y (Ctrl+Shift+Z) | Undo / Redo | 항상 |
| N | New Object (포인트로) | 항상 |
| E | Edit의 **포인트** 도구: 편집 시작(선택한 Object) · 브러쉬 / 오토 툴에서 → 포인트 · 포인트에서 다시 → 편집 끝 | 항상 |
| Delete | 선택한 포인트 삭제, 없으면 선택한 Object 삭제 | 항상 |
| Esc | 도구 나가기(오토 툴 결과 버림) → 편집 끝내기 | 편집 중 |
| F / Shift+Enter | 오토 툴 **Apply & Close**(확인). F: 프레임 목록 위나 오토 툴이 없으면 기준 ◎로 이동 | 오토 툴 |
| G / Enter | 오토 툴 Apply & Continue. Enter: 오토 툴이 꺼져 있으면 기준 ◎ 지정 | 오토 툴 |
| A | 오토 툴 나가기(결과 버림, 포인트로): 취소 | 오토 툴 |
| S / D | 오토 툴 Fill / Paint 모드(오가도 Paint에서 고른 부분 유지). Paint에서 D 다시 = 전체 선택 / 해제. S는 목록 위에서는 이동 키 | 오토 툴 |
| Shift+A | 오토 툴 Fill → 전체 선택된 Paint, Paint에서 전체 선택 / 해제 | 오토 툴 |

### 이동

| 키 | 동작 | 언제 |
|---|---|---|
| ← / → (PgUp / PgDn) | 이전 / 다음 프레임 | 편집 중이 아닐 때 |
| ↑ / ↓ | 이 프레임에 마스크가 있는 이전 / 다음 Object (편집도 따라감, 끝에서 순환) | 항상 |
| W A ↑ ← / S D ↓ → | 이전 / 다음 프레임 | 마우스가 Frame List / Frames 줄 위 |
| W A ↑ ← / S D ↓ → | 이전 / 다음 Object 행 (Show all로 보이는 행 포함, 편집도 따라감, 끝에서 순환) | 마우스가 Objects 목록 위 |
| W / S | 이전 / 다음 Object 행 (목록과 같은 순서, 순환) | 마우스가 캔버스 위 (`A` `D` 화살표는 그대로) |
| ⌖ 버튼 | Frame List와 Frames 줄을 **현재 프레임**으로 스크롤 | 항상 |
| [ / ] | 이전 / 다음 문제 프레임(⚠ ✕, `1` 켜면 `–`도) | 항상 |
| , / . | 가장 가까운 이전 / 다음 키프레임(★ = 직접 편집한, 전파 소스). `1` 켜면 선택한 Object의 ★만 | 항상 |
| F | 전파 기준(◎, 더블클릭한 프레임)으로 이동 | 항상 |
| Enter | 현재 프레임을 전파 기준(◎)으로 지정, 기준에서 다시 누르면 해제 (더블클릭과 같음) | 오토 툴이 꺼져 있을 때 |
| Space | Enter와 같음(현재 프레임을 기준 ◎으로) | 마우스가 Frame List / Frames 줄 위 (캔버스에서는 Space+드래그 = 이동) |
| 더블클릭 (프레임) | 전파 기준(◎)으로 지정, 다시 하면 해제 | 목록 |
| Shift / Ctrl+클릭 (프레임) | 여러 프레임 선택(전파 Selection 범위) | 목록 |

### Objects

| 키 | 동작 | 언제 |
|---|---|---|
| Ctrl+D | Duplicate (이 이미지의 Mask) | 마우스가 Objects 패널 위 |
| Ctrl+Shift+D | Duplicate All (모든 링크 Mask) | 마우스가 Objects 패널 위 |
| Delete | 선택한 Object 삭제 (확인 없음, Ctrl+Z, 🔒 잠긴 것은 남음) | 편집 중 포인트 선택이 없을 때 |

### 보기

| 키 | 동작 |
|---|---|
| Z (누르고 있기) | Mask Preview 잠깐 보기 |
| V | Mask Preview(흑백) 켜기 / 끄기 (누르고 있어도 한 번만) |
| X | Mask Preview **흑백**: Final Mask ↔ 선택한 Object 전환. 잘라보기 중이면 흑백으로(Final / Object는 저장된 그대로) |
| C | Mask Preview **잘라보기**: 안쪽(마스크가 담은 것) ↔ 바깥(남긴 것) 전환. 흑백 중이면 잘라보기로(안 / 밖은 저장된 그대로) |
| O | Outline 켜기 / 끄기 |
| Q / ` | Solo 켜기 / 끄기 (선택한 Object만 색칠) |
| H | Hide Masks 켜기 / 끄기 (맨 이미지) |
| T (누르고 있기) | 색 고르는 중(Pick Color): 누르는 동안만 **Original** 뒤집기(사진만, 오토 툴 표시·범례도 숨김), 떼면 원래대로. 켜 두기 / 끄기는 패널 `Original (hold T)` 버튼(`p100`, 전에는 짧게 = 토글). 픽커가 꺼지면 같이 꺼짐 (`p96`). 숫자 칸에 커서가 있어도 작동(글자 입력 칸에서만 안 됨, `p99`) |
| 우클릭 | 색 고르는 중: **빼는 색(−)**. Shift = 하나 더, Alt = 5×5 평균. 넣는 색과 둘 다 가까우면 더 가까운 쪽 (`p98`) |
| R | Show Changes(에딧 레이어 초록 / 빨강) 켜기 / 끄기 |
| 휠 / 가운데 드래그 · Space+드래그 | 확대·축소 / 이동 |
| F1 | 단축키 전체 목록 |

### 이미지 위 (편집 중)

| 키 | 동작 |
|---|---|
| 좌클릭 / 우클릭 / 드래그 | Positive / Negative 포인트 / Box (Region Box 켜면 영역 추가) |
| 포인트 드래그 / 더블클릭 | 포인트 이동 / 삭제 |
| Ctrl+좌클릭 / Ctrl+우클릭 | 그 자리의 조각(SAM2, 그 점 하나로)을 Mask에 더하기 / 빼기. Edit Layer에 쌓이고 나머지 Mask는 그대로 (브러시 켜져 있어도) |
| Ctrl+I | 편집 중인 Mask 인버트 (Region 안에서만, 있으면) |
| Ctrl+Backspace | 편집 중인 Mask 비우기 (이 이미지, Region 안에서만, 있으면) |
| E | 편집 시작 / 끝: **포인트**로 (브러쉬 꺼짐) |
| D | Edit의 **브러쉬** 도구: 편집 시작(선택한 Object) · 포인트에서 → 브러쉬 · 브러쉬에서 다시 → 편집 끝 · 오토 툴에서 → Paint / Fill 전환 |
| Shift+Enter | 오토 툴 Apply & Close (Enter는 Apply & Continue) |
| Alt+드래그 | Paint 빼기 · 오토 툴 선택 해제 · Region Box 빼기 |
| Shift+드래그 | 브러쉬를 켜지 않고 칠하기 |
| Ctrl+드래그 좌우 | 브러쉬 크기 (오른쪽 = 크게, 원은 누른 자리에 고정. 움직이지 않고 떼면 Ctrl+클릭 = 이미지 조각 더하기 / 빼기). 가장 작게 = 이미지 1 px |
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
| (장기) | 단축키 직접 바꾸기(커스텀 매핑) | 사용자 메모 2026-09-30 |

## 변경 기록
- `v0.4-p84`: `X` = 흑백(Final ↔ Object), `C` = 잘라보기(안 ↔ 밖), 서로 오가면 각자 상태를 기억. 브러쉬 크기 = Ctrl+드래그 좌우(p83, Alt+우클릭 드래그 대신).
- `v0.4-p55`: 오토 툴 **F = Apply & Close**(전엔 Continue), **G = Apply & Continue**, **S = Fill / D = Paint**(Paint에서 D 다시 = 전체 선택 / 해제),
  Fill ↔ Paint를 오가도 Paint의 선택 유지. A = 취소는 그대로(A 취소 · S D 모드 · F 확인 · G 계속).
- `v0.4-p49`: Edit 안에서 **E = 포인트, D = 브러쉬** 도구, 같은 키를 다시 누르면 편집 끝. 오토 툴에서 **D = Paint / Fill**,
  **A = 나가기(취소)**, **F = 적용(확인)**, Shift+A = 전체 선택 / 해제(전의 A). **Q / `** Solo, **H** Hide Masks.
- `v0.4-p8`: `,` / `.` 키프레임 이동, `F` 기준(◎)으로 이동 추가, Show Changes `F` → `R`, Final Mask 미리보기 → Mask Preview + `V` 대상 전환.
- `v0.4-p9`: `Enter`(오토 툴 없을 때) = 현재 프레임을 기준(◎)으로 지정 / 해제.
- `v0.4-p13`: 마우스를 올린 목록 기준 `W A S D` / 화살표. Frame List · Frames 줄 위 = 프레임, Objects 목록 위 = Object. 목록 위에서 `S` = 다음(스크롤은 ⌖ 버튼이나 목록 밖에서 `S`). Shift / Ctrl+화살표는 목록의 여러 칸 선택 그대로.
- `v0.4-p14`: 모든 단축키를 메뉴 항목(QAction)으로 옮김. `Ctrl+Q` 종료 추가(이후 뺌: Ctrl+Z / Ctrl+A 옆이라 실수로 꺼짐, File → Quit만).
- `v0.4-p21`: 편집 중 `Ctrl+I` 인버트, `Ctrl+Backspace` 비우기.
- `v0.4-p19`: 캔버스 위 `W` / `S` = Object 이동. Object 이동은 끝에서 순환.
- `v0.4-p17`: Objects 패널 위 `Ctrl+D` / `Ctrl+Shift+D`. Delete는 확인 없이.
- `v0.4-p15`: `S`(스크롤) 뺌 — `F`와 겹치고 목록 위에서는 "다음"이라 헷갈림, 스크롤은 ⌖ 버튼. `X` ↔ `V` 교환(`Z` 누르고 있기 · `X` 대상 전환 · `V` 켜기/끄기), 토글 키는 누르고 있어도 한 번만. 프레임 목록 위 `Space` = `Enter`. Paint 버튼 = `A`처럼 전체 선택으로 시작. `E` 편집은 브러쉬가 켜진 채로 시작.
