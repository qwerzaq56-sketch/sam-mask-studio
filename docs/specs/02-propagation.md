# SAM Mask GUI — Propagation 기능 기획서

## 1. 기능 목적

현재 선택된 이미지에서 확정한 **Object Mask를 기준점으로 하여**, 사용자가 지정한 Start~End 범위 안에서 앞뒤 이미지로 Mask를 연속 전파한다.

핵심 구조:

> **Current Image = 전파 기준점**
> **Start / End = 전파 가능한 범위의 경계**

---

## 2. 기본 동작

예를 들어 이미지가 다음과 같다고 가정한다.

```text
001  002  003  004  [005]  006  007  008  009
                      ↑
                  Current Image
```

범위를:

```text
Start = 002
End   = 008
```

으로 설정하면 `005`의 Mask를 기준으로 양쪽으로 전파한다.

### Forward

```text
005 → 006 → 007 → 008
```

### Backward

```text
005 → 004 → 003 → 002
```

### Both

```text
002 ← 003 ← 004 ← [005] → 006 → 007 → 008
                      ↑
                 Current Mask
```

001과 009에는 전파하지 않는다.

---

# 3. Start / End의 의미

Start와 End는 **전파 시작 이미지가 아니다.**

```text
Start = 전파 가능한 최소 이미지
End   = 전파 가능한 최대 이미지
Current = 실제 전파 기준 이미지
```

예:

```text
Start       Current       End
 002 -------- 005 -------- 008
              ↑
          기준 Mask
```

따라서 Current Image는 반드시 Start~End 범위 안에 있어야 한다.

---

# 4. Direction

Propagation 패널:

```text
Propagation
────────────────────────

Start Image
[ 000002.jpg ▼ ]

End Image
[ 000008.jpg ▼ ]

Current Image
[ 000005.jpg ]

Direction
● Both
○ Forward
○ Backward

[ Propagate Selected Objects ]
```

### Forward

Current → End 방향

```text
005 → 006 → 007 → 008
```

### Backward

Current → Start 방향

```text
005 → 004 → 003 → 002
```

### Both

양쪽 모두

```text
002 ← 003 ← 004 ← 005 → 006 → 007 → 008
```

---

# 5. Current Image

현재 선택된 이미지가 항상 기준점이다.

예를 들어 사용자가 007번 이미지에서 Object를 수정했다면:

```text
002  003  004  005  006  [007]  008  009
                            ↑
                         Current
```

범위가 002~008이면:

```text
007 → 006 → 005 → 004 → 003 → 002
007 → 008
```

으로 전파할 수 있다.

따라서 사용자가 데이터셋을 작업하면서 **중간중간 Mask를 수정하고 해당 위치를 기준으로 다시 전파**하는 작업이 가능하다.

---

# 6. Propagation 대상

Propagation은 **Object 단위**로 작동한다.

```text
Objects

☑ Person #1
☑ Car #1
☐ Sign #1

[ Propagate Selected Objects ]
```

체크된 Object만 전파한다.

각 Object는 현재 이미지에서 가지고 있는 **현재 선택 Variant의 Mask**를 전파 기준으로 사용한다.

---

# 7. 현재 Mask를 기준으로 전파

예:

```text
Object #1

Variant 1   ○
Variant 2   ●
Variant 3   ○
```

현재 이미지에서 `Variant 2`가 선택되어 있다면:

```text
Current Image
     │
     └─ Variant 2 Mask
              ↓
        Propagation
```

선택되지 않은 Variant는 전파하지 않는다.

---

# 8. 전파 과정

예:

```text
Current = 005
Start   = 002
End     = 008
Direction = Both
```

실행하면 내부적으로:

```text
Backward
005 → 004 → 003 → 002

Forward
005 → 006 → 007 → 008
```

으로 처리한다.

**005 자체는 다시 처리하지 않는다.**

---

# 9. Object별 결과

Object의 이미지별 Mask를 관리한다.

```text
Object #1

002  Mask
003  Mask
004  Mask
005  Mask ★ Current / 기준
006  Mask
007  Mask
008  Mask
```

여기서 현재 이미지에서 직접 수정한 Mask는 이후 재전파의 기준점으로 사용할 수 있다.

---

# 10. 중간 수정 및 재전파

Propagation 결과가 잘못된 경우:

```text
002 ← 003 ← 004 ← [005] → 006 → 007 → 008
                              ↑
                         잘못된 결과
```

사용자가 007번에서:

```text
[Edit]
```

를 눌러 Mask를 수정한다.

그러면 현재 이미지가 007이 되고:

```text
002 ← 003 ← 004 ← 005 ← 006 ← [007] → 008
                                  ↑
                              수정된 Mask
```

다시 `Both`로 Propagate하면:

```text
007 → 006 → 005 → 004 → 003 → 002
007 → 008
```

으로 새 기준점에서 다시 전파할 수 있다.

---

# 11. 기존 Mask 처리

이미 해당 이미지에 Mask가 존재하면 덮어쓰기 전에 확인한다.

```text
Existing masks found.

006.jpg
005.jpg
004.jpg
...

Overwrite existing propagated masks?

[Cancel] [Overwrite]
```

단, Current Image의 Mask는 전파 과정에서 덮어쓰지 않는다.

---

# 12. 전파 진행 UI

```text
Propagation

Object #1

Backward
005 → 004 → 003 → 002
████████████████████  3 / 3

Forward
005 → 006 → 007 → 008
██████████████░░░░░░  2 / 3

Current: 007.jpg
```

여러 Object를 처리하는 경우:

```text
Object #1    ✓ Complete
Object #2    ███████░░ 70%
Object #3    Waiting
```

---

# 13. 실패 / 경고

각 이미지의 결과 상태를 기록한다.

```text
002 ✓
003 ✓
004 ⚠
005 ★
006 ✓
007 ✓
008 ✕
```

상태:

* `✓` 성공
* `⚠` 낮은 품질 / 경고
* `✕` 전파 실패
* `★` 현재 기준점 / 수동 수정 Mask

실패한 프레임을 클릭하면 해당 이미지로 바로 이동할 수 있도록 한다.

---

# 14. MVP 범위

### 필수

* Start Image 설정
* End Image 설정
* Current Image를 기준점으로 사용
* Forward
* Backward
* Both
* 선택 Object만 Propagation
* 현재 선택 Variant의 Mask 사용
* Start~End 범위 밖으로 전파하지 않음
* Current Image 자체는 재전파하지 않음
* 진행률 표시
* 성공/실패 상태 표시
* 기존 Mask 덮어쓰기 확인
* 특정 이미지에서 Mask 수정 후 재전파

### 후순위

* Keyframe 시스템
* 자동 품질 평가
* 품질 저하 시 자동 Propagation 중단
* Bidirectional 자동 최적화
* Propagation 결과 품질 그래프
* 여러 Propagation 구간 저장

---

# 15. 핵심 UX 한 줄 정리

```text
[현재 선택 이미지의 확정 Mask]
              ↓
      ┌───────┴───────┐
      ↓               ↓
Backward           Forward
      ↓               ↓
   Start            End
      └───────┬───────┘
              ↓
      지정 범위 내에서만
      연속적으로 Propagation
```

**즉 `Start~End`는 범위 제한이고, 실제 Propagation의 시작점은 항상 사용자가 현재 선택하고 있는 이미지다.**
