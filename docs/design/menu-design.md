# 메뉴 계층 설계

상단 두 줄(메뉴 바, 툴바)의 역할을 나누는 기준과 지금 배치를 적은 문서입니다. 구현: `v0.4-p14` (`src/app/main_window.py` `_build_actions`).

## 원칙

1. **툴바(2번째 줄) = 작업 중에 계속 누르는 것만.** 편집하면서 몇 초마다 켜고 끄는 보기·도구 토글.
   캔버스 옆에 늘 보여야 손이 가는 것들입니다.
2. **메뉴 바(1번째 줄) = 모든 명령.** 툴바에 있는 것도 메뉴에 다시 넣습니다. 메뉴는 "이 앱에 무엇이 있는가"의 목록이고,
   단축키는 메뉴 항목 오른쪽에 표시되어 **메뉴를 열어 보는 것만으로 단축키를 배울 수 있게** 합니다.
3. **가끔 쓰는 것은 메뉴에만.** Open / Save / Export / Settings는 작업 한 번에 한두 번, Undo / Redo는 단축키(`Ctrl+Z` / `Ctrl+Y`)로
   누르는 경우가 대부분이라 툴바 자리를 차지하지 않습니다. (자동 저장이 있어 Save 버튼이 필요한 일도 드뭅니다.)
4. **이미 패널에 버튼이 있는 기능**(Objects의 Merge / Duplicate, 전파, 디텍션)은 패널이 주 위치이고, 메뉴에는
   존재를 알리기 위해 같은 명령을 넣습니다(패널 버튼과 같은 동작, 같은 선택 대상).
5. **키가 명령이 아닌 것**(`Enter`, `Z` 누르고 있기, 목록 위 `W A S D`)은 메뉴에 `이름 ⇥ 키` 형태의 안내 항목으로 넣습니다.
   실행할 수 있는 것은 눌러도 동작하고(`Enter` 계열), 설명뿐인 것은 회색입니다. 이 항목은 키를 새로 묶지 않으므로 기존 키 처리와 충돌하지 않습니다.
6. 메뉴 이름은 흔한 데스크톱 앱 순서를 따릅니다: **File · Edit · View · Go · Help**. 프레임·Object 이동이 많아서 `Go`를 따로 둡니다.

## 툴바 (2번째 줄)

```text
Mask Preview │ Preview: Final/Object │ Brush │ Outline ▢px │ Show Changes │ Solo │ Hide Masks
     V                  X                D          O               R
```

## 메뉴 바 (1번째 줄)

| 메뉴 | 항목 (키) |
|---|---|
| **File** | Open Folder… (`Ctrl+O`) · Import Masks from Folder… · Save (`Ctrl+S`) · Export Final Masks… (`Ctrl+E`) ─ Settings… ─ Quit (키 없음) |
| **Edit** | Undo (`Ctrl+Z`) · Redo (`Ctrl+Y`, `Ctrl+Shift+Z`) ─ New Object (`N`) · Edit Points / Finish (`E`) · Delete (`Delete`) · Leave Tool / Finish Editing (`Esc`) ─ **Tools ▸** Brush (`D`) · Invert Mask (`Ctrl+I`) · Clear Mask (`Ctrl+Backspace`) · Auto Tool: Pick All / None (`A`) · Auto Tool: Apply & Continue (`Enter`) · Leave the Active Auto Tool (그 버튼 다시) ─ **Objects ▸** Duplicate (this image) (`Ctrl+D`\*) · Duplicate All (`Ctrl+Shift+D`\*) ─ Move A → B · Move / Copy (Options)… · Merge · Merge (Options)… ─ Lock / Unlock · Lock All · Unlock All ─ Copy Mask to Picked Frames · Copy Mask to Picked Frames (Options)… · Clear Masks on Picked Frames |
| **View** | Mask Preview (`V`) · Toggle Final / Object Mask (`X`, 툴바에서는 지금 모드 `Preview: Final / Object`) · Peek at Mask Preview (`Z` 누르고 있기) · Outline (`O`) · Show Changes (`R`) ─ Solo · Hide Masks ─ **Panels ▸** Frame List · Objects / Prompt / Propagation · Properties · Frames |
| **Go** | Previous / Next Frame (`←` `→`, `PgUp` `PgDn`) · Previous / Next Object (`↑` `↓`) ─ Previous / Next Problem ⚠ ✕ (`[` `]`) · Previous / Next Keyframe ★ (`,` `.`) ─ Go to Reference ◎ (`F`) · Set Current Frame as Reference ◎ (`Enter`) · Exclude from Dataset / Include (⊘) ─ (안내) 목록 위에서 `W A S D` / 화살표, 프레임 목록 위 `Space` = 기준 지정 |
| **Help** | Keyboard Shortcuts (`F1`) |

\* 마우스가 Objects 패널 위일 때만 동작(메뉴에서는 키 표시만, 항목을 누르면 실행).

## 판단 메모

- **(p17) 옵션은 `⚙`와 메뉴의 `(Options)…`로**: 기본 버튼은 창 없이 한 번에([`ux-principles.md`](ux-principles.md) 4).

- **(p15) Scroll to Current Frame(`S`)을 뺀 이유**: `F`(기준으로 이동)와 역할이 겹쳐 보이고, 목록 위에서는 `S`가 "다음"이라 메뉴의 키 표시가 맞지 않았음. 스크롤은 ⌖ 버튼.
- **(p15) 메뉴 이름과 툴바 이름을 나눈 경우**: `X`는 메뉴에서 명령 이름(`Toggle Final / Object Mask`), 툴바에서는 지금 상태(`Preview: Final`)를 보여 줌(`setIconText`).

- **Undo / Redo를 툴바에서 뺀 이유**: 사용자 요청(덜 쓰는 기능은 위로). 단축키가 워낙 표준이라 버튼을 누를 일이 적고,
  Edit 메뉴 첫 줄에 항상 있습니다. 필요하면 툴바 왼쪽에 다시 넣기 쉽습니다(`tb.addAction(self.act_undo)`).
- **Brush가 툴바에 남은 이유**: `D`와 함께 편집 중 가장 자주 켜고 끄는 도구. 오토 툴은 Properties 패널이 주 위치라 툴바에 넣지 않습니다.
- **Outline 두께 칸**은 메뉴에 넣을 수 없는 입력 칸이라 툴바에만 있습니다.
- **단축키는 모두 메뉴의 QAction으로** 옮겼습니다(전에는 일부가 `QShortcut`이라 메뉴에서 보이지 않았음). 동작은 같고, F1 목록(`SHORTCUTS`)과 [`keymap.md`](keymap.md)도 같이 고칩니다.
- 새 명령을 추가할 때: (1) 메뉴에 넣고, (2) 자주 켜고 끄는 토글이면 툴바에도, (3) 키가 있으면 `SHORTCUTS`와 `keymap.md`에.
