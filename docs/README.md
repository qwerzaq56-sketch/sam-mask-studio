# 문서 지도

문서는 **역할별 폴더 4개**로 나눕니다. 찾을 때는 "지금 무엇이 궁금한가"로 폴더를 고르면 됩니다.

```text
docs/
├─ design/    지키는 기준   — 지금 앱이 따르는 규칙. 바뀌면 고쳐 씀
├─ specs/     기능 기획서   — 기능 하나의 의도·역할·옵션. 번호순
├─ backlog/   할 일         — 아직 안 한 아이디어와 UI 문제
├─ log/       끝난 것       — 버전별 진행 기록, 끝난 아이디어
└─ DEVELOPMENT.md            — 코드 구조와 설계 결정 (영문, 개발용)
```

| 궁금한 것 | 문서 |
|---|---|
| 기능을 넣을 때 어떤 기준으로? | [`design/ux-principles.md`](design/ux-principles.md) |
| 메뉴 / 툴바 어디에 둘까? | [`design/menu-design.md`](design/menu-design.md) |
| 이 키는 무엇이고, 빈 키는? | [`design/keymap.md`](design/keymap.md) |
| 이 기능은 원래 어떻게 기획됐나? | [`specs/`](specs) — 01 GUI · 02 전파 · 03 Object 관리 · 04 v0.3 요청 원문 · 05 Merge / Copy / Move · 06 COLMAP · 07 학습기별 Export Preset · 08 투영 변환(ERP / Fisheye → Pinhole) · 09 특수 Object(Sky, 피시아이 외곽) · 10 포인트 레이어 · 11 사용 설명서 기획 |
| 다음에 뭘 하나? | [`backlog/ideas.md`](backlog/ideas.md) · 작은 UI 문제는 [`backlog/ui-issues.md`](backlog/ui-issues.md) |
| 언제 무엇이 바뀌었나? | [`log/PROGRESS_v0.4.md`](log/PROGRESS_v0.4.md) · [`log/PROGRESS_v0.3.md`](log/PROGRESS_v0.3.md) · 끝난 아이디어 [`log/ideas-log.md`](log/ideas-log.md) |
| 코드가 어떻게 짜여 있나? | [`DEVELOPMENT.md`](DEVELOPMENT.md) |

## 정리 원칙 (최소 규칙 3개)

1. **새 문서보다 기존 문서의 새 섹션.** 한 섹션이 한 화면(약 100줄)을 넘거나 따로 가리킬 일이 생기면 그때 파일로 뺍니다.
   뺀 파일은 역할에 맞는 폴더에 둡니다. 새 폴더는 만들지 않습니다.
2. **끝나면 옮긴다.** `backlog/`에서 끝난 항목은 `log/`로(아이디어 → `ideas-log.md`, UI 문제 → `ui-issues.md`의 "완료").
   `backlog/` 문서에는 남은 일만 둡니다.
3. **한 사실은 한 곳에.** 키는 `keymap.md`, 메뉴 배치는 `menu-design.md`, 기능의 의도는 `specs/`. 다른 문서는 그 줄을 링크합니다.
