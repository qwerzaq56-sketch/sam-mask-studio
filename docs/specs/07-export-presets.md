# SAM Mask GUI — 학습기별 Export Preset 기획서

마스킹이 끝난 COLMAP 장면을 3DGS 학습기(Brush, LichtFeld Studio, Spirula, Postshot, gsplat …)에 **바로 넣을 수 있는 데이터셋**으로 내보낸다.
[`06-colmap.md`](06-colmap.md)의 5장(내보내기 프로필)과 6장(프레임 빼기)을 이 문서가 대신한다.
출발점: GPT 보고서 "COLMAP 후편집 프로그램 — 학습기별 Export Preset 기획서"(2026-09-29). 2장에 그 보고서를 어떻게 반영했는지 적는다.

---

## 1. 목표와 범위

- **목표**: Export 창에서 학습기를 고르면, 그 학습기가 읽는 폴더 구조·마스크 규칙으로 데이터셋이 만들어지고, 넣기 전에 문제를 미리 보여준다.
- **이 앱이 하는 일**: 마스크를 만들고 고치는 것. 카메라·포즈는 COLMAP 결과를 **그대로 옮겨 적기만** 한다.
- **하지 않는 일(MVP)**: 이미지 재투영(360 → Pinhole), 카메라 모델 변환, 좌표계 변환. 이것들은 픽셀과 포즈를 새로 계산하는 별도 기능이라 10장 "나중"으로 뺀다.

---

## 2. GPT 보고서 검토 (자체 피드백)

| 보고서 내용 | 판단 | 이유 |
|---|---|---|
| 내부는 하나의 표준 데이터, 학습기 형식은 Export 때만 | **받아들임** | 원본을 바꾸지 않는다는 06의 원칙과 같다. 그래서 **프레임 빼기도 원본 `.bin`을 고치지 않고 Export 때 걸러 쓴다**(6장) — 06 6장을 바꾼 가장 큰 변화 |
| 학습기별 코드 대신 공통 파이프라인 + 프리셋 | **받아들임** | Brush / LichtFeld / gsplat / Spirula는 모두 COLMAP 폴더를 읽는다. 다른 것은 거의 **마스크 규칙** 하나 |
| 프리셋 = 요구사항 + 변환 규칙 + 검증 규칙 | **받아들임, 줄임** | MVP의 "변환"은 마스크 흑백·이름·형식뿐. 카메라는 검사만 |
| 내부 마스크 규칙 `1 = KEEP` | **고침** | 이 앱의 Mask는 `1 = Object`(고른 대상)이다. 대상이 **지울 것**(사람, 차)일 때도 있고 **남길 것**(물체 단독 학습)일 때도 있어서, "Final Mask가 무엇인지(지울 곳 / 남길 곳)"를 **마스크 세트마다** 정하고 Export에서 학습기 규칙으로 바꾼다(4장) |
| 카메라 모델을 가장 중요한 옵션으로 | **검사만** | 이 앱은 카메라를 만들지 않는다. 학습기가 못 읽는 모델(예: EQUIRECTANGULAR를 Brush에)이면 **경고**하고 원본 형식으로 내보내는 것까지 |
| 360 → Pinhole 가상 카메라(4 yaw × 3 pitch) | **나중, 별도 기획** | 이미지·마스크 재투영 + 가상 카메라 포즈 계산 + 새 `.bin` 생성이라 Export 옵션 하나가 아니라 기능 하나. 마스크도 같이 재투영해야 하므로 이 앱과 잘 맞지만 MVP 밖(10장) |
| Nerfstudio `transforms.json` | **나중** | 쓰는 학습기 목록에 없음. Brush는 nerfstudio 형식도 읽지만 COLMAP으로 충분 |
| Spirula 전용 형식 | **COLMAP 계열로 시작** | Spirula는 360 / fisheye를 직접 읽고 자체 SfM·마스킹이 있다. 우리 쪽에서는 COLMAP 폴더 + 마스크로 넣는 것부터. 마스크 규칙은 확인 필요(3장) |
| 사용자 정의 프리셋 JSON | **형식만 미리** | 프리셋을 코드 안 표(딕셔너리)로 두되, 나중에 JSON으로 꺼낼 수 있는 모양으로 |
| 검증(이미지 ↔ 마스크 ↔ 카메라 일치) | **받아들임, 먼저** | 지금 Export 검사(`check_export`)를 넓히면 된다. 가장 싸고 효과가 큼 |
| 보고서에 없는 것: 학습기별 **마스크 흑백·이름 규칙** | **추가** | 이 앱에 가장 중요한데 보고서는 "Preset별 차이 허용"으로만 둠 → 3장에서 확인한 것과 확인할 것을 나눔 |
| 보고서에 없는 것: 데이터셋 복사 비용 | **추가** | 이미지 수천 장을 매번 복사하지 않게 **하드링크**(같은 드라이브) 또는 "장면에 마스크만 쓰기"(5장) |

---

## 3. 학습기별 규칙 (확인 상태)

| 학습기 | 입력 | 마스크 | 흑백 | 파일 이름 | 360 / fisheye | 상태 |
|---|---|---|---|---|---|---|
| **COLMAP** (특징점 추출) | — | `--ImageReader.mask_path` | 검정 = 무시 | `a.jpg.png` | — | 확인됨(COLMAP 문서) |
| **Brush** | COLMAP, nerfstudio | `masks/` 폴더(어느 깊이든), 또는 알파 채널(투명도를 결과에 맞춤) | **검정 = 무시, 흰색 = 학습**, `--invert-masks`로 반대 | `img.png`, `img.jpg.png`, `img.mask.*` | README에 없음 | **확인됨**(README, `brush-dataset` 소스, CHANGELOG) |
| **LichtFeld Studio** | COLMAP(SPHERICAL = 360 지원) | `masks/`, `mask/`, `segmentation/`, `dynamic_masks/` 또는 RGBA 알파(`use_alpha_as_mask`) | Ignore 모드: **검정 = 무시**. Ignore+Segment: 128 미만 무시 / 128~250 segment / 250 초과 유지. `--invert-masks` | `img.png`·`.jpg`·`.mask.png` 또는 `img.jpg.png` | 360(SPHERICAL), 3DGUT로 왜곡 모델 | **확인됨**(소스 `filesystem_utils.hpp`, `parameters.hpp`, 테스트). **Mask Mode 기본값이 None**이라 학습 설정에서 Ignore를 켜야 함 |
| **Spirula** | 자체 SfM, 360 / fisheye 직접 | 자체 AI 마스킹 | **확인 필요** | **확인 필요** | 직접 지원 | README에 규칙 없음 |
| **Postshot** | COLMAP 등 | **확인 필요** | **확인 필요** | **확인 필요** | ? | 미확인 |
| gsplat | COLMAP | 예제 파서에 마스크 없음(확인 필요) | — | — | fisheye 일부 | 나중 |

- **결론: `masks/<이미지 이름>.png`(예: `a.jpg.png`)에 대상 = 검정, 나머지 = 흰색으로 쓰면 COLMAP, Brush, LichtFeld가 모두 그대로 읽는다.**
  세 프리셋은 파일이 같고, 안내 문구(LichtFeld: Mask Mode = Ignore)와 검사만 다르다.
- "확인 필요"는 **작은 테스트 장면으로 직접 넣어 보고** 채운다. 추측으로 기본값을 정하지 않는다.
- 규칙이 확인 안 된 학습기는 프리셋에 "미확인" 표시를 하고, 흑백·이름을 사용자가 고르게 둔다.

---

## 4. 마스크 규칙: 내부 → 학습기

- **내부**: Object Mask `1 = 대상`. 마스크 세트(06 4장)마다 **대상의 뜻**을 정한다:
  - `지울 것`(기본, 사람·차·삼각대 등): 학습에서 무시할 곳.
  - `남길 것`(물체만 학습): 학습할 곳.
- **학습기 규칙**: `무시할 곳 = 검정`(COLMAP, Brush 기본) 등.
- **변환**: `(대상의 뜻, 학습기 규칙)`으로 반전 여부가 정해진다. 사용자가 Invert를 직접 고를 일이 없게 하는 것이 목표.
  예: 대상 = 지울 것, Brush(검정 = 무시) → 대상을 검정으로 = 지금 Export의 Invert 켬.
- 파일: 8bit PNG(0 / 255), 원본 이미지 해상도. 알파 채널 방식(RGBA 이미지)은 Brush가 "투명도에 맞춤"으로 다르게 쓰므로 **남길 것** 세트에만 제안.

---

## 5. 출력 방식 두 가지

| 방식 | 하는 일 | 언제 |
|---|---|---|
| **장면에 마스크 쓰기** (기본) | 원본 장면의 `masks/`(또는 `masks_<세트>/`)에 마스크만 쓴다. 덮어쓸 파일이 있으면 먼저 `masks_backup_<날짜시각>/`로 옮긴다 | 프레임을 빼지 않았고 학습기가 원본 장면을 바로 읽을 때 |
| **새 데이터셋 만들기** | `<출력>/images/`(하드링크, 안 되면 복사) + `sparse/0/`(걸러서 새로 씀) + `masks/` | 프레임을 뺐거나, 학습기별로 폴더를 나눠 두고 싶을 때 |

- 원본의 `images/`, `sparse/`는 **어느 방식에서도 바꾸지 않는다**.
- 하드링크: 같은 드라이브에서 파일 공간을 더 쓰지 않음. 다른 드라이브면 복사(시간·용량을 창에 미리 표시).

---

## 6. 프레임 빼기 (06 6장을 바꿈)

- 06의 초안은 원본 `images.bin`을 백업 후 고치는 방식이었다. **바꿈**: 뺀 프레임은 작업 파일에 "제외" 표시만 하고,
  **새 데이터셋 만들기** 때 `images.bin` / `points3D.bin`을 걸러 새로 쓴다(관측 2개 미만이 된 점은 지움, 06 8장 결정).
- 좋은 점: 원본이 그대로라 백업·복구 메뉴가 필요 없고, 되돌리기는 "제외 해제" 한 번(Undo도 가능).
- Frame List: 제외한 프레임은 흐리게 + `⊘` 표시. Export 검사에 "제외 N장".
- "장면에 마스크 쓰기" 방식에서는 제외가 반영되지 않으므로, 제외가 있으면 그 방식 옆에 경고.

---

## 7. Export 창

지금 Export 창을 넓힌다(새 창을 만들지 않음).

```text
┌ Export ─────────────────────────────────────────────┐
│ 학습기     [ Brush                         ▼ ]      │
│ 마스크 세트 [✓] (기본) Final   [✓] people   [ ] sky  │
│ 출력       ● 장면에 마스크 쓰기  ○ 새 데이터셋 [ … ] │
│ ─ 프리셋이 정한 것 (바꾸려면 펼치기 ▸) ─────────────  │
│   masks/ · 이미지와 같은 이름 · 검정 = 무시          │
│ ─ 검사 ────────────────────────────────────────────  │
│   ✓ 842 이미지 · 842 마스크 · 842 카메라 포즈        │
│   ⚠ 3장: 마스크가 비어 있음           [보기]         │
│   ⚠ 카메라 EQUIRECTANGULAR: Brush에서 확인 필요       │
│   ⊘ 제외 12장 → "새 데이터셋"에서만 빠짐             │
│                                  [ 취소 ] [ Export ] │
└─────────────────────────────────────────────────────┘
```

- 학습기를 바꾸면 아래 "프리셋이 정한 것"과 검사가 바로 바뀐다.
- 규칙이 "미확인"인 학습기는 펼친 상태로 시작(흑백·이름을 사용자가 확인하게).

---

## 8. 단계

| 단계 | 내용 | 06과의 관계 |
|---|---|---|
| C1 | 장면 인식 + 기존 마스크 폴더를 Object로 불러오기 | 06 C1 그대로 (**완료, `v0.4-p23`**) |
| C2 | **장면에 마스크 쓰기** + 프리셋(Brush, LichtFeld, COLMAP, Custom) + 검사 확장 (**완료, `v0.4-p24`**) → 마스크 세트는 `p25` | 06 C2 |
| C2-확인 | 작은 테스트 장면으로 LichtFeld / Spirula / Postshot에 넣어 보고 3장 표 채우기 → 프리셋 추가 | 06 C4 |
| C3 | 프레임 제외 + **새 데이터셋 만들기**(하드링크, `.bin` 걸러 쓰기) | 06 C3를 바꿈(원본 수정 없음) |

---

## 9. 프리셋 모양 (코드 안 표, 나중에 JSON)

```python
PRESETS = {
    "brush": {
        "label": "Brush",
        "masks": {"dir": "masks", "name": "{name_stem}.png", "ignore_is": "black"},  # --invert-masks = the other way
        "cameras_ok": ["PINHOLE", "SIMPLE_PINHOLE", "OPENCV", "SIMPLE_RADIAL", "RADIAL"],  # warn otherwise (확인 필요)
        "verified": "README 2026-09",
    },
    "colmap": {"label": "COLMAP (feature masks)", "masks": {"dir": "masks", "name": "{name}.png", "ignore_is": "black"}},
    "custom": {"label": "직접 지정", "masks": None},  # the dialog's own choices
}
```

---

## 10. 나중 (별도 기획이 필요한 것)

- **360 → Pinhole 변환**: ERP 이미지와 **마스크를 함께** 가상 원근 카메라(예: 4 yaw × 3 pitch, FOV 90°)로 재투영, 가상 카메라 포즈와 새 `.bin`. LichtFeld(SPHERICAL)·Spirula는 360을 직접 읽으므로 Brush 등 원근만 읽는 학습기용.
- Nerfstudio `transforms.json`, 카메라 모델 변환, depth / normal, Sky 마스크 별도 세트, 사용자 프리셋 JSON 불러오기.

---

## 11. 정한 것 (2026-09-29 사용자 확인)

1. 마스크 세트의 기본 뜻: 대상 = **지울 것**(학습에서 무시).
2. 기본 출력: **장면에 마스크 쓰기**.
3. 먼저 확인할 학습기: **LichtFeld** → 소스에서 확인함(3장).
4. 360 → Pinhole 변환: **필요** → 별도 기획서(`08`)로.

## 12. 구현 기록

- `v0.4-p24`: Export 창의 **For**(Brush / LichtFeld Studio / COLMAP / Custom, 장면일 때만). 프리셋은 폴더(장면의 `masks/`)·이름(`{name}.png`)·
  색(대상 검정)·모든 이미지 쓰기를 정하고(회색으로 표시), 덮어쓸 파일은 `masks_backup_<시각>/`으로 먼저 옮김. 검사에 카메라 모델 줄,
  백업될 파일 수. 마지막으로 고른 학습기를 기억. 코드: `src/core/presets.py`, `storage.backup_existing`.

출처: [Brush README](https://github.com/ArthurBrussee/brush) · LichtFeld 소스(`src/io/include/io/filesystem_utils.hpp`, `src/core/include/core/parameters.hpp`, `tests/test_mask_loss.cpp`) · [Brush 원문](https://github.com/ArthurBrussee/brush) · [LichtFeld Studio v0.5.3](https://lichtfeld.io/blog/release-lichtfeld-studio-v0-5-3/) · [LichtFeld 360 plugin](https://github.com/alexmgee/lichtfeld-360-plugin) · [Spirula Studio](https://github.com/harry7557558/spirula-studio) · [COLMAP cameras](https://github.com/colmap/colmap/blob/main/doc/cameras.rst)
