# SAM Mask GUI — GUI / UX 기획서

## 1. 프로젝트 목표

기존 `sam-mask-gui`를 기반으로 **SAM2 + SAM3를 하나의 마스킹 작업 환경으로 통합**한다.

핵심 목표는 사용자가 모델의 차이를 신경 쓰지 않고:

> **찾기 → 선택 → 수정 → 조합 → 저장**

의 흐름으로 마스크를 제작할 수 있도록 하는 것.

주요 활용 대상:

* 일반 이미지 마스킹
* 360° ERP 이미지 마스킹
* SAM3 Text Prompt 기반 객체 검출
* SAM2 Point / Box 기반 마스크 생성 및 수정
* 다중 객체 마스킹
* 3DGS / COLMAP 데이터셋용 Mask 생성

---

# 2. 핵심 개념

GUI에서는 다음 4개 개념을 명확히 분리한다.

### Detection

SAM3가 자동으로 찾아낸 **객체 후보**.

```text
SAM3
 ↓
Person #1
Person #2
Person #3
...
```

Detection 자체는 아직 작업 Object가 아니다.

---

### Object

사용자가 실제로 마스킹 작업 대상으로 선택한 **독립적인 segmentation 작업 단위**.

```text
Object #1 = 실제 사람
Object #2 = 간판 속 사람
Object #3 = 삼각대
```

---

### Variant

하나의 Object에 대해 SAM이 생성한 **여러 Mask 후보**.

```text
Object #1
├─ Variant 1  0.618
├─ Variant 2  0.497
└─ Variant 3  0.388
```

Object마다 최종적으로 하나의 Variant를 선택한다.

---

### Final Mask

최종적으로 선택한 여러 Object의 Mask를 합성한 결과.

```text
Object #1 / Variant 2
+
Object #3 / Variant 1
+
Object #5 / Variant 1
        ↓
Final Mask
```

---

# 3. 핵심 UX 원칙

## 3.1 SAM3는 "찾기"

SAM3:

> "이 이미지에서 사람이 어디 있지?"

## 3.2 SAM2는 "따기 / 수정하기"

SAM2:

> "이 사람이 정확히 어디까지인지 정교하게 따자."

---

## 3.3 Detection과 Object를 분리

SAM3가 30개의 객체를 검출했다고 해서 30개를 바로 작업 대상으로 만들지 않는다.

```text
SAM3 Detection
      ↓
후보 30개
      ↓
사용자가 필요한 것 선택
      ↓
Object 생성
```

---

## 3.4 Object 선택과 Object 편집을 분리

이것이 중요한 UX 규칙.

### 체크박스

**Final Mask에 포함할지 결정**

```text
☑ Person #1
☑ Person #2
☐ Person #3
```

### Edit 버튼

**어떤 Object를 수정할지 결정**

```text
Person #1 [Edit]
Person #2 [Edit]
Person #3 [Edit]
```

따라서 여러 Object를 Final Mask에 포함하면서도 **현재 편집 중인 Object는 하나만 존재**한다.

---

# 4. 전체 Workflow

```text
이미지 / ERP 입력
       ↓
 ┌─────────────────┐
 │ SAM3 Text Prompt│
 │ SAM2 Point/Box  │
 └─────────────────┘
       ↓
Detection / Mask 생성
       ↓
Object 생성
       ↓
Variant 선택
       ↓
Object별 SAM2 Refinement
       ↓
필요한 Object 복수 선택
       ↓
Final Mask 합성
       ↓
PNG Export
```

---

# 5. GUI 기본 구조

```text
┌─────────────────────────────────────────────────────┐
│ Toolbar                                             │
│ Open | Save | Undo | Redo | Export | ERP           │
├──────────────┬────────────────────────┬─────────────┤
│ Objects      │                        │ Properties  │
│              │                        │             │
│ Object #1    │                        │ Selected    │
│ Object #2    │      Image Canvas      │ Object      │
│ Object #3    │                        │             │
│              │                        │ Variants    │
│ + New Object │                        │ Points      │
│              │                        │             │
├──────────────┴────────────────────────┴─────────────┤
│ Prompt / Detection / Status / Logs                  │
└─────────────────────────────────────────────────────┘
```

---

# 6. Object 생성 방법

Object는 **두 가지 방법으로만 생성**한다.

## 6.1 SAM3 → Detection → Object

Text Prompt:

```text
person
```

SAM3가 검출:

```text
Person #1
Person #2
Person #3
...
Person #18
```

사용자가 필요한 Detection을 선택:

```text
☑ #1
☐ #2
☑ #3
☐ #4
...
```

그리고:

```text
[ Add Selected as Objects ]
```

를 누른다.

결과:

```text
Object #1
Object #2
```

---

## 6.2 SAM2 → Point → New Object

SAM2로 직접 객체를 만들 경우에는 **명시적인 버튼을 사용한다.**

```text
[ + New Object from Points ]
```

버튼을 누른 후 Canvas에서 Point를 찍는다.

```text
+ New Object from Points
        ↓
Canvas 클릭
        ↓
SAM2
        ↓
Object #1
        ↓
Variant 1 / 2 / 3
```

### 중요

**Canvas에 점을 찍는다고 무조건 새로운 Object가 생성되면 안 된다.**

현재 Object를 수정하려는 클릭인지 새 Object를 만드는 클릭인지 구분해야 하기 때문이다.

따라서 `New Object from Points`는 별도의 명시적 동작으로 한다.

---

# 7. Objects 패널

추천 UI:

```text
Objects

┌─────────────────────────────┐
│ ☑ Person #1     [Edit] [×] │
│   Variant 1  ●              │
│   Variant 2  ○              │
│   Variant 3  ○              │
└─────────────────────────────┘

┌─────────────────────────────┐
│ ☑ Person #2     [Edit] [×] │
│   Variant 1  ●              │
│   Variant 2  ○              │
│   Variant 3  ○              │
└─────────────────────────────┘

┌─────────────────────────────┐
│ ☐ Tripod #1      [Edit] [×]│
└─────────────────────────────┘

[ + New Object from Points ]
```

### 각 UI 요소

**Checkbox**

→ Final Mask 포함 여부

**Edit**

→ 해당 Object를 편집 상태로 전환

**×**

→ Object 삭제

**Variant**

→ 해당 Object의 Mask 후보 선택

---

# 8. Object 편집

각 Object마다 개별적인 `Edit` 버튼을 제공한다.

예:

```text
Person #1 [Edit]
```

클릭하면:

```text
Person #1
[ Editing ]
```

상태가 된다.

Canvas에서 입력한 Point는 **Person #1에만 적용**된다.

---

## 8.1 Point

```text
Positive Points

● Point 1
● Point 2
● Point 3

Negative Points

× Point 4
× Point 5
```

### 조작

* 좌클릭 → Positive Point
* 우클릭 → Negative Point
* Point 선택 → 해당 Point 선택
* Delete → 선택 Point 삭제
* Ctrl+Z → Undo
* Ctrl+Y → Redo
* Clear Points → 현재 Object의 Point 전체 삭제
* Finish Editing → 편집 종료

**특정 Point를 직접 선택해서 삭제할 수 있어야 한다.**

단순히 마지막 Point만 Undo하는 방식에 의존하지 않는다.

---

# 9. Variant UX

SAM2에서 하나의 Point/Prompt에 대해 여러 Mask 후보가 생성될 수 있다.

예:

```text
Person #1

● Variant 1   0.618
○ Variant 2   0.497
○ Variant 3   0.388
```

사용자는 가장 적절한 Variant를 선택한다.

### 규칙

**Object는 여러 개 선택 가능**

```text
☑ Object #1
☑ Object #2
☐ Object #3
```

**Variant는 Object마다 하나 선택**

```text
Object #1
  ● Variant 2

Object #2
  ● Variant 1
```

---

# 10. SAM3 과검출 처리

예를 들어:

```text
Prompt: person
```

SAM3가:

```text
Person #1 = 실제 사람
Person #2 = 간판 속 사람
Person #3 = 사진 속 사람
```

을 검출한다.

사용자는 Detection 단계에서:

```text
☑ Person #1
☐ Person #2
☐ Person #3
```

만 선택한다.

따라서 **검출된 모든 객체를 Object로 만들 필요가 없다.**

---

# 11. SAM3 → SAM2 Refinement

SAM3에서 선택한 Object도 이후 SAM2로 수정할 수 있다.

```text
SAM3
 ↓
Detection
 ↓
Object
 ↓
[Edit]
 ↓
SAM2 Point / Negative Point
 ↓
Variant 재생성
 ↓
최종 Variant 선택
```

예:

```text
Person #1
    ↓
SAM3 초기 Mask
    ↓
[Edit]
    ↓
간판 부분에 Negative Point
    ↓
SAM2 재추론
    ↓
Variant 선택
```

---

# 12. Final Mask

Object 패널에서 체크된 Object만 Final Mask에 포함한다.

```text
☑ Person #1
☑ Person #2
☐ Person #3
☑ Tripod #1
```

결과:

```text
Person #1 / Variant 2
+
Person #2 / Variant 1
+
Tripod #1 / Variant 1
        ↓
Final Mask
```

제공 기능:

```text
[ Preview Final Mask ]
[ Export Mask ]
```

---

# 13. ERP / 360° Mode

입력 단계에서:

```text
Input

○ Normal Image
● ERP / 360 Panorama
```

를 선택한다.

ERP 내부 처리:

```text
ERP
 ↓
Perspective Projection
 ↓
SAM2 / SAM3
 ↓
Mask Merge
 ↓
ERP Mask
```

하지만 사용자에게 제공되는 UX는 동일하게 유지한다.

```text
ERP
└─ Detection
   └─ Objects
      └─ Variants
         └─ Points
```

즉 ERP는 **내부 처리 방식만 달라지고 GUI의 Object 모델은 동일**하다.

---

# 14. 최종 사용자 Workflow

## 일반적인 경우

```text
1. 이미지 열기
       ↓
2. SAM3 Text Prompt
       ↓
3. Detection 확인
       ↓
4. 필요한 Detection 선택
       ↓
5. Add Selected as Objects
       ↓
6. 각 Object의 Variant 선택
       ↓
7. 필요한 Object [Edit]
       ↓
8. Positive / Negative Point로 수정
       ↓
9. 필요한 Object 체크
       ↓
10. Final Mask Preview
       ↓
11. Export
```

---

## 직접 따는 경우

```text
1. 이미지 열기
       ↓
2. [ + New Object from Points ]
       ↓
3. Canvas 클릭
       ↓
4. SAM2 Mask 생성
       ↓
5. Variant 선택
       ↓
6. [Edit]로 추가 Point / Negative Point
       ↓
7. Final Mask
       ↓
8. Export
```

---

# 15. 데이터 구조

내부 구조는 다음 형태를 권장한다.

```text
Project
└── Image
    ├── DetectionResults
    │
    ├── Objects
    │   ├── Object
    │   │   ├── source
    │   │   ├── points
    │   │   │   ├── positive
    │   │   │   └── negative
    │   │   ├── variants
    │   │   └── selected_variant
    │   │
    │   └── Object
    │
    └── FinalMask
```

`source`에는 해당 Object가 어떻게 만들어졌는지 기록한다.

```text
source = SAM3_DETECTION
```

또는

```text
source = SAM2_POINT
```

이렇게 해두면 추후 기능 확장에도 유리하다.

---

# 16. MVP 범위

## MVP

* 일반 이미지 입력
* SAM2 Point
* SAM2 Box
* SAM3 Text Prompt
* SAM3 Detection 목록
* Detection 선택
* Detection → Object 변환
* `New Object from Points`
* Object별 `Edit`
* Object 삭제
* Object 복수 선택
* Object별 Variant 선택
* Positive / Negative Point
* Point 개별 삭제
* Undo / Redo
* Final Mask 합성
* PNG Export

## 후순위

* ERP / 360°
* PanoSAM
* Video Propagation
* 다중 프레임 처리
* 프로젝트 저장/복구
* Object Tracking
* Batch Export
* COLMAP Dataset 직접 연동

---

# 17. 핵심 UX 정의

최종적으로 사용자가 이해해야 하는 것은 네 가지뿐이다.

> **Detection = AI가 찾아준 후보**

> **Object = 내가 작업할 대상**

> **Variant = 그 대상에 대한 Mask 후보**

> **Final Mask = 선택한 Object들을 합친 결과**

그리고 모델의 역할은:

> **SAM3 = 찾기**
> **SAM2 = 따기 / 수정하기**

로 단순화한다.

이 구조를 기준으로 구현하면 **SAM3의 대량 검출, SAM2의 수동 생성, Object별 수정, Variant 선택, 다중 객체 합성**이 서로 충돌하지 않고 하나의 UX로 묶인다.
