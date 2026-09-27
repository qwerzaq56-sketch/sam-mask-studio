# SAM Mask GUI — Object 관리 기능 기획서

## 1. 기능 목적

SAM3/SAM2를 이용해 생성된 여러 Mask를 **Object 단위로 관리하고 편집**할 수 있도록 한다.

Object는 독립적인 segmentation 작업 단위이며, 다음 기능을 제공한다.

* Object 생성
* Object 편집
* Object 이름 변경
* Object 복제
* Object 병합
* Object 삭제
* Object별 Propagation

---

# 2. Object 기본 개념

```text
Object
├─ Name
├─ Source
├─ Points
│  ├─ Positive
│  └─ Negative
├─ Variants
│  ├─ Variant 1
│  ├─ Variant 2
│  └─ Variant 3
├─ Selected Variant
└─ Frame Masks
    ├─ Frame 002
    ├─ Frame 003
    ├─ Frame 004
    └─ ...
```

### Object

하나의 독립적인 segmentation 대상.

### Variant

하나의 Object에 대해 SAM2가 생성한 여러 Mask 후보.

### Frame Mask

특정 이미지에서 해당 Object가 가지고 있는 최종 Mask.

---

# 3. Object 목록 UI

```text
Objects
────────────────────────────

☑ Person #1       [Edit] [···]
☑ Backpack #1     [Edit] [···]
☐ Bicycle #1      [Edit] [···]

────────────────────────────

[ + New Object from Points ]

Selected Objects
[ Merge ] [ Duplicate ] [ Delete ]
```

### Checkbox

Final Mask에 해당 Object를 포함할지 결정한다.

```text
☑ Person
☐ Bicycle
```

→ Person만 Final Mask에 포함.

### Edit

해당 Object만 편집 상태로 전환한다.

```text
[Edit]
```

→ 현재 Object의 Point / Mask / Variant 등을 편집.

한 번에 하나의 Object만 Edit 상태가 된다.

---

# 4. Object 생성

## 4.1 SAM3 Detection

```text
SAM3 Text Prompt
        ↓
Detection Results
        ↓
사용자가 원하는 Detection 선택
        ↓
[ Add Selected as Objects ]
```

Detection과 Object는 별개의 개념이다.

예:

```text
Detection Results

☑ Person #1
☑ Person #2
☐ Person in Sign
☐ Person #4

[ Add Selected as Objects ]
```

선택된 Detection만 Object로 변환한다.

---

## 4.2 SAM2 Point

별도의:

```text
[ + New Object from Points ]
```

버튼을 제공한다.

버튼을 누른 후 Canvas에서 Point를 지정하여 새로운 Object를 만든다.

**단순히 Canvas를 클릭한다고 자동으로 새 Object를 생성하지 않는다.**

Point 클릭은 현재 편집 중인 Object의 refinement일 수도 있기 때문이다.

---

# 5. Object Edit

Object마다 독립적인 `[Edit]` 버튼을 가진다.

예:

```text
☑ Person #1     [Edit]
☑ Backpack #1   [Edit]
```

Person의 Edit를 누르면:

```text
Editing: Person #1
```

상태가 되고 Canvas의 Point 입력은 Person #1에만 적용된다.

```text
Left Click  → Positive Point
Right Click → Negative Point
Delete      → 선택 Point 삭제
Ctrl+Z      → Undo
Ctrl+Y      → Redo
```

---

# 6. Variant 관리

하나의 Object에는 여러 Mask Variant가 존재할 수 있다.

```text
Person #1

Variant 1   ○
Variant 2   ●
Variant 3   ○
```

Variant는 **Object당 하나만 선택**한다.

선택된 Variant가 해당 Object의 현재 Mask가 된다.

```text
Object
 ├─ Variant 1
 ├─ Variant 2 ← Selected
 └─ Variant 3
```

---

# 7. Object Merge

## 목적

여러 Object를 하나의 Object로 통합한다.

예:

```text
☑ Person #1
☑ Backpack #1

[ Merge ]
```

결과:

```text
Person + Backpack
        ↓
Merged Object
```

---

# 8. Merge 방식

Merge는 선택된 Object의 Mask를 **Union**하여 하나의 Object로 만든다.

```text
Object A Mask
      ∪
Object B Mask
      ↓
Merged Mask
```

현재 이미지뿐 아니라 이미 존재하는 Frame Mask에도 적용한다.

예:

```text
Object A

002 ✓
003 ✓
004 ✓
005 ✓

Object B

002 ✓
003 ✓
005 ✓
```

Merge 후:

```text
Merged Object

002 = A ∪ B
003 = A ∪ B
004 = A
005 = A ∪ B
```

즉 각 프레임에서 존재하는 Mask들을 합친다.

---

# 9. Merge 후 Variant

Merge 시 서로 다른 Object의 Variant를 조합하여 새로운 Variant 후보를 만드는 방식은 MVP에서 사용하지 않는다.

기본 동작:

```text
Object A의 현재 Mask
        ∪
Object B의 현재 Mask
        ↓
Merged Object Mask
```

즉 Merge 결과를 **새로운 확정 Mask**로 만든다.

필요하면 이후:

```text
Merged Object
      ↓
[Edit]
      ↓
SAM2 Point Refinement
```

으로 다시 수정할 수 있다.

---

# 10. Object Duplicate

Object를 그대로 복제한다.

```text
Object #1
[Duplicate]
```

결과:

```text
Object #1
Object #2
```

복제 시 다음 정보를 복사한다.

* Object Mask
* Points
* Variants
* Selected Variant
* Frame Masks

복제된 Object는 이후 독립적으로 수정된다.

---

# 11. Object Rename

자동 생성된 이름을 사용자가 변경할 수 있다.

```text
Object #1
↓
Player
```

예:

```text
Person #1
→ Player

Object #2
→ Backpack

Object #3
→ Bicycle
```

이름은 프로젝트 저장 시 유지한다.

---

# 12. Object Delete

Object를 삭제한다.

```text
Object #3
[Delete]
```

삭제 전 확인:

```text
Delete "Bicycle"?

[Cancel] [Delete]
```

삭제된 Object의 Frame Mask도 해당 Object와 함께 제거한다.

---

# 13. Object와 Final Mask

Object의 Checkbox는 Final Mask에 대한 포함 여부를 결정한다.

```text
Objects

☑ Player
☑ Backpack
☐ Bicycle
```

Final Mask:

```text
Player Mask
    ∪
Backpack Mask
    ↓
Final Mask
```

따라서 Object 자체를 삭제하지 않고도 Final Mask에서 제외할 수 있다.

---

# 14. Object Merge와 Final Mask의 차이

둘은 서로 다른 기능이다.

### Final Mask 선택

```text
☑ Object A
☑ Object B
☐ Object C
```

→ 현재 결과에 A+B를 포함.

Object 자체는 그대로 유지된다.

### Merge

```text
Object A
+
Object B
↓
새로운 하나의 Object
```

→ 이후 A와 B를 독립적인 Object로 관리하지 않고 하나로 통합한다.

---

# 15. Object와 Propagation

Object Merge 이후에도 Propagation을 사용할 수 있다.

예:

```text
Person
+
Backpack
↓
Merged Object
```

현재 이미지:

```text
005
```

범위:

```text
002 ~ 008
```

Propagation:

```text
002 ← 003 ← 004 ← [005] → 006 → 007 → 008
```

즉 **Merge → Propagation** 순서의 작업도 지원한다.

---

# 16. 전체 Object Workflow

```text
SAM3 Text Prompt
        ↓
Detection Results
        ↓
사용자 선택
        ↓
Objects 생성
        ↓
Object별 Variant 선택
        ↓
SAM2 Point Refinement
        ↓
필요하면 Object Merge
        ↓
현재 이미지에서 최종 Mask 확정
        ↓
Propagation
        ↓
Start ~ End 범위 내 전파
        ↓
필요한 프레임 수정
        ↓
다시 Propagation
        ↓
Final Mask Export
```

---

# 17. Object 기능 우선순위

## MVP

* Object 생성
* Object 선택/체크
* Object별 Edit
* Variant 선택
* Object Delete
* Object Rename
* **Object Merge**
* Object Duplicate
* Frame별 Mask 저장
* Object별 Propagation

## 후순위

* Object Split
* 자동 Object 분리
* Object 간 관계/Parent
* Object 그룹
* Object 색상/표시 설정
* 고급 Merge 옵션

---

## 핵심 구조

```text
                    Project
                       │
                    Objects
                       │
        ┌──────────────┼──────────────┐
        ↓              ↓              ↓
    Object A        Object B        Object C
        │              │              │
    Variants        Variants        Variants
        │              │              │
    Frame Masks     Frame Masks     Frame Masks
        │              │              │
        └─────── Merge / Edit ────────┘
                       │
                  Propagation
                       │
                 Start ~ End
                       │
                   Final Mask
```

이렇게 잡으면 **SAM3 자동 검출 → Object 정리 → Merge → SAM2 수정 → 현재 프레임 기준 Propagation → 최종 Mask 생성**까지 하나의 일관된 작업 흐름으로 연결됨.
