# SAM Mask GUI — Merge / Copy / Move 기획서

두 개 이상의 Object 사이에서 Mask를 옮기는 세 기능의 의도, 역할, 옵션을 정리한다.
출처: [`ideas.md`](../backlog/ideas.md) "Merge / Copy / Move 역할 나누기" (2026-09-29). 현재 구현(`v0.4-p17`)과 바꿀 점은 5장.

---

## 1. 한눈에

| 기능 | 한 문장 | 소스(A) 뒤에 | 타겟(B) 뒤에 | 주 용도 |
|---|---|---|---|---|
| **Merge** | 여러 Object를 **하나로 합친다** | 사라짐 | 새 Object 하나 | 같은 대상이 링크드 Object 여러 개로 나뉜 것을 결합 |
| **Move** | A의 Mask를 B로 **옮긴다** | Object는 남고, 옮긴 이미지의 Mask만 빔 | Mask를 받음 | Object 안에서 레이어를 나눠 작업, 나눠 둔 레이어 유지 |
| **Copy** | A의 Mask를 B에 **더한다** | 그대로 | Mask를 받음 | 같은 영역을 두 Object가 함께 가져야 할 때 |

- 셋 다 **Undo 한 단계**, 확인 창 없음([`ux-principles.md`](../design/ux-principles.md) 1).
- A / B는 **선택 순서**: 먼저 선택한 행 = A(소스), 마지막에 선택한 행 = B(타겟). (Merge는 3개 이상도 가능)

---

## 2. Merge — 결합

**의도**: 전파나 배치 결과로 같은 대상이 Object 여러 개로 나뉘었을 때 하나로 묶는다. 결과는 "하나의 Object"이고, 원래 Object들은 남지 않는다.

| 옵션 | 겹치는 이미지에서 | 이름 |
|---|---|---|
| **Add** (기본, 버튼) | 합집합 | 먼저 선택한 것 |
| Override with A | A의 프레임 그대로(포인트 포함) | A |
| Override with B | B의 프레임 그대로 | B |

- 겹치지 않는 이미지는 각자 가진 프레임을 그대로 가져온다.
- 🔒 잠긴 Object가 있으면 실행하지 않는다(삭제되므로). 로그로 알림.
- p17의 **Into A**는 Merge에서 빼고 Move로 옮긴다(Object를 남기는 동작이라 Merge의 "하나로"와 맞지 않음).

---

## 3. Move / Copy — 한 버튼, 옵션 공유

**의도**
- **Move**: 한 Object 안에서 영역을 다른 Object로 떼어 내 따로 다룬다(레이어 분리). A는 지우지 않고 남겨서, 나눠 둔 구조가 유지된다.
- **Copy**: A는 그대로 두고 B에도 같은 영역을 준다.

둘은 옵션이 같으므로 **한 버튼**으로 묶는다.

```text
[ Move A → B ] [⚙]
        │        └─ 옵션 창
        └─ 기본: Move · Add · 이 이미지만
```

### 옵션 (⚙)

| 계층 | 선택 | 기본 |
|---|---|---|
| 1. 동작 | **Move** (A에서 뺌) / Copy (A 그대로) | Move |
| 2. B의 Mask | **Add** (B ∪ A) / Replace (B = A) | Add |
| 3. 범위 | **이 이미지만** / A에 Mask가 있는 모든 이미지 | 이 이미지만 |

- 옵션 창에서 고른 값을 다음 기본으로 기억할지는 7장 질문.
- A에 Mask가 없는 이미지는 건드리지 않는다(B는 그대로).
- **Move 후 A**: 옮긴 이미지에서 A의 프레임을 지운다. 모든 이미지에서 비면 **빈 Object로 남는다**(삭제하지 않음, Show all에서 보임).
- **Replace**: B의 프레임이 A의 프레임이 된다(포인트·상태 포함). **Add**: 합집합, 둘 중 하나라도 ★였으면 ★.
- 🔒 잠금은 삭제만 막으므로 Move / Copy는 실행된다. (잠금 범위를 넓히면 여기서 다시 정함 — `ideas.md` "잠금의 범위")

### 진입점

| 곳 | 동작 |
|---|---|
| Objects 패널 버튼 `Move A → B` | 기본값으로 바로 실행 |
| 그 옆 `⚙` | 옵션 창 |
| `[···]` ▸ Move into ▸ / Copy into ▸ | 이 Object → 고른 Object, Add, 이 이미지 |
| 메뉴 Edit → Objects | Move A → B · Move / Copy (Options)… · Merge · Merge (Options)… |

---

## 4. 이름과 표시

- 버튼 글자는 동작을 말한다: `Merge`, `Move A → B`. 옵션에서 Copy를 고르는 것은 창 안에서만.
- 로그: `Moved “A” into “B” on 1 image (Add)` / `Copied …` / `Merged into “A”`.

---

## 5. 현재(`v0.4-p17`)와 달라지는 점

| 지금 | 바뀐 뒤 |
|---|---|
| `Copy A → B` 버튼(Copy, Add, 이 이미지) | `Move A → B` 버튼(**Move**, Add, 이 이미지) |
| Copy ⚙: Add / Replace, 범위 | ⚙: **Move / Copy** + Add / Replace + 범위 |
| Merge ⚙: Add / Override A / Override B / **Into A** | Merge ⚙: Add / Override A / Override B (Into A는 Move가 대신함) |
| `[···]` ▸ Copy into | `[···]` ▸ Move into, Copy into |

- 코드: `Project.copy_into`에 `move` 인자(옮긴 이미지에서 A의 프레임 제거) 추가, `Project.merge`의 `into` 제거,
  `MainWindow.copy_into` → `transfer(ids, move=True, replace=False, all_frames=False)`.

---

## 6. 예시

- 사람 Object에 가방까지 칠해졌다: 가방만 새 Object로 떼고 싶다 → (새 Object를 만든 뒤) … **이 경우 "일부 영역만" 옮기는 기능이 필요**(7장 질문 2).
- 전파 결과 "Car #1", "Car #2"가 같은 차다 → 둘 선택 → `Merge`.
- 바닥 Object의 이 이미지 Mask를 그림자 Object에도 주고 싶다 → `⚙` → Copy.

---

## 7. 확인이 필요한 것

1. **범위 "현재 오브젝트만 / 전체 오브젝트"**: 이 문서는 **이 이미지만 / 모든 이미지**로 읽었습니다. 다른 뜻(예: 선택한 Object 전부 → B)이면 알려 주세요.
2. **Move의 "레이어 분리"**: Object **전체 Mask**를 옮기는 것으로 적었습니다. Object 안의 **일부 영역**(브러쉬나 Region Box로 고른 부분)만 떼어 옮기는 뜻이라면, 영역 선택 단계가 추가되는 별도 기능이 됩니다.
3. **옵션 기억**: `⚙`에서 고른 값(예: Copy)을 다음 버튼 기본으로 기억할까요, 버튼은 항상 Move · Add · 이 이미지일까요? (지금 안: 항상 같은 기본값 — 버튼이 무엇을 할지 예측 가능)
