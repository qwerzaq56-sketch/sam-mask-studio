# C. 시나리오별 레시피

[← B. 추천 워크플로](02-workflow.md) · [설명서 목차](README.md) · 다음: [D. 기능 참고 →](04-reference.md)

B장의 흐름을 안다고 보고, 상황별로 짧게 적습니다. 각 레시피: **언제** · **순서** · **확인**.

---

## C1. 사람과 삼각대를 한꺼번에

- **언제**: 지울 것의 종류가 여럿이고, 한 사람씩 나눌 필요는 없을 때.
- **순서**
  1. 먼저 한 프레임에서 **Prompt / Detection** 탭으로 라벨마다 시험해 봅니다(`person`, `tripod` …). SAM3가 잘 찾는 단어를 고릅니다.
  2. **Batch** 탭: 입력칸에 `person, tripod` → 범위 **All images** → **Run on Images**.
  3. 라벨마다 Object 하나(`person`, `tripod`)가 생기고, 각 프레임에는 그 라벨 후보를 모두 합친 마스크가 들어갑니다.
- **확인**: 결과 목록과 Frame List를 보고 B5처럼 검수합니다. 놓친 프레임은 B3로 고칩니다.

## C2. 하늘 따로 빼기

- **언제**: 하늘(구름이 움직이는 부분)을 학습에서 빼고 싶을 때. Settings에 **Sky model (ONNX)**가 있어야 합니다.
- **순서**
  1. Objects 패널 **+ Special ▾** → **Sky Mask**. Properties에 **Special** 탭이 열립니다.
  2. **Frames**에서 범위를 고릅니다: **All frames** / **Range** / **Frames picked in the Frame List** → **Make Sky Masks**.
  3. **Settings (applied to every covered frame)**를 움직이면 덮는 프레임 전체에 바로 반영됩니다:
     - **Threshold** %: 이 값 이상을 하늘로(기본 50, 높이면 하늘이 줄어듦)
     - **Grow / shrink** px: 넓히기(+) / 좁히기(−)
     - **Refine edges**: 하늘 경계를 이미지 색에 맞춤(기본 켬)
     - **Only sky touching the top edge**: 위 가장자리에 닿은 조각만(창문, 물, 반사 제거). 360 사진에 맞고, 피시아이에서는 끕니다
  4. 사람과 하늘을 **다른 폴더**로 내보내려면 마스크 세트를 씁니다:
     하늘 Object만 체크 → Export 창의 **Save Checked as Set…** → 이름 `sky`. 세트는 `masks_sky/`로 따로 쓰입니다.
     Export의 **Mask**에서 그 세트, 또는 **Every set, one folder each (and the Final Mask)**를 고릅니다.
- **확인**
  - 학습기는 `masks/`만 읽습니다. 사람과 하늘을 함께 빼려면 둘 다 체크해서 Final Mask로 내보내고,
    하늘만 따로 둔 세트로 학습하려면 그 폴더 이름을 `masks/`로 바꿉니다.
  - 모델 결과는 캐시되어 설정을 바꿔도 모델을 다시 돌리지 않습니다. 아주 어두운 밤하늘은 빠질 수 있습니다.

> 📷 `img/03-sky-special.png` — Special 탭(Frames, Settings)과 하늘 마스크

## C3. 피시아이 검은 테두리

- **언제**: 원형 피시아이 사진의 원 바깥 검은 부분을 학습에서 뺄 때.
- **순서**
  1. **+ Special ▾** → **Fisheye Lens Edge** → 범위를 골라 **Make … Masks**.
  2. **Detect from Images**: 덮는 프레임 몇 장의 평균에서 검지 않은 원을 찾아 맞춥니다.
  3. 필요하면 **Radius**(짧은 변 절반 대비 %, 100 = 내접원)와 **Center X / Y**로 조정합니다.
- **확인**: 원 **바깥**이 마스크(무시)입니다. 테두리가 없는 풀프레임 사진이면 원을 찾지 않습니다.

> 📷 `img/03-lens-edge.png` — 피시아이 한 장과 원 바깥 마스크

## C4. 이미 있는 마스크 고치기

- **언제**: 다른 툴이나 예전 작업으로 만든 마스크를 손볼 때.
- **순서**
  1. 장면을 **처음** 열 때 `masks/`나 `masks_*/`가 있으면 창이 뜹니다. 폴더마다 **Skip** / **White = the object** / **Black = the object**를 고르고 **Load**.
     (흰 면적이 많은 폴더는 Black = the object가 미리 골라져 있습니다.) 폴더 하나가 Object 하나가 됩니다.
     - 나중에 불러오려면 File → **Import Masks from Folder…**. 파일 이름은 `a.jpg.png` 또는 `a.png`.
     - 장면과 함께 불러온 마스크는 `Ctrl+Z`로 사라지지 않습니다(작업의 출발점). Import로 나중에 불러온 것은 Undo 한 단계입니다.
  2. 그 Object를 **Points** (`E`)로 편집합니다. 불러온 마스크에 찍는 첫 클릭은 **Layer 1 (+)**로 들어가서 원래 모양이 그대로 남습니다.
  3. 빼려면 레이어를 **+ / −**로 빼기로 바꾸거나, `Ctrl`+우클릭으로 조각을 뺍니다. 가장자리는 브러쉬로.
- **확인**: 불러온 프레임은 `✓`(★ 아님)입니다. 고친 프레임에는 `★`가 붙습니다.

> 📷 `img/03-import-masks.png` — 장면을 열 때 뜨는 마스크 불러오기 창

## C5. 움직이지 않는 물체를 여러 프레임에

- **언제**: 삼각대처럼 여러 프레임에서 같은 자리에 있는 물체. 전파 대신 같은 마스크를 복사합니다.
- **순서**
  1. 마스크가 있는 프레임을 기준 ◎로 둡니다(더블클릭). 기준이 없으면 지금 열린 프레임의 마스크를 씁니다.
  2. Frame List에서 복사할 프레임들을 `Shift` / `Ctrl`-클릭으로 고릅니다. 고른 채로 다른 프레임을 보려면 **가운데 클릭**(선택 유지).
  3. Objects에서 그 Object를 선택합니다.
  4. Edit → Objects → **Copy Mask to Picked Frames**(또는 Frame List **우클릭** 메뉴). 기본은 그 프레임의 마스크를 **바꾸기(Replace)**,
     **Copy Mask to Picked Frames (Options)…**에서 **Add**(합치기)도 고릅니다.
- **확인**: 복사된 프레임은 전파 결과와 같은 상태(★ 아님)입니다. 되돌리려면 `Ctrl+Z`, 그 프레임들을 비우려면 **Clear Masks on Picked Frames**.
  편집 중에는 쓸 수 없습니다.

## C6. 흐린 프레임 빼고 학습

- **언제**: 흔들리거나 필요 없는 프레임을 학습 데이터에서 뺄 때. 원본 장면은 그대로 두고 **새 데이터셋**을 만듭니다.
- **순서**
  1. 뺄 프레임을 고르고(없으면 지금 프레임) Go → **Exclude from Dataset / Include**(Frame List 우클릭 메뉴에도 있음). `⊘`와 회색 글자가 됩니다. 다시 하면 되돌립니다.
  2. Export 창에서 **For**(학습기)를 고르고 **Output** → **New dataset:** + **빈 폴더**.
  3. **Export**.
- **확인**: 새 폴더에
  - `images/`: ⊘가 아닌 이미지. 같은 드라이브면 **하드링크**라 용량을 더 쓰지 않습니다.
  - `sparse/0/`: ⊘ 이미지를 뺀 모델(그 이미지의 관측을 빼고, 관측이 2개 미만이 된 3D 점은 지움).
  - `masks/`: 마스크.
  - `rigs.bin` 같은 그 밖의 파일은 옮기지 않고 로그에 알립니다. Into the scene에 ⊘가 있으면 검사 목록이 "새 데이터셋에서만 빠짐"이라고 경고합니다.

## C7. Postshot

- **언제**: Postshot으로 학습할 때. Postshot의 Remove Occluders는 **흰색 = 무시**라서 다른 학습기와 흑백이 반대입니다.
- **순서**: Export 창 **For** = **Postshot** → **Export**.
- **확인**
  - `masks_postshot/`에 사람 = **흰색**, 이름은 이미지와 같게(`0001.png`) 따로 씁니다. `masks/`는 건드리지 않습니다.
  - Postshot에서 Image Set의 **Image Masks**에 파일을 끌어다 놓고 **Mask Mode = Remove Occluders**.
  - 파일과 이미지가 짝지어지는 규칙은 Postshot 문서에 없습니다. 처음 한 번은 짝이 맞는지 직접 확인하세요.

## C8. 360(ERP) → Pinhole

- **언제**: 360 장면(카메라 `EQUIRECTANGULAR`)을 원근 사진만 읽는 학습기(Brush 등)로 학습할 때. LichtFeld · Spirula는 360을 직접 읽으므로 그대로 내보내도 됩니다.
- **순서**
  1. Export 창에서 **For**를 고르고 **Output** → **New dataset:** + 빈 폴더.
  2. 그 아래 변환 목록에서 **Pinhole views**. (**Keep the cameras** = 360 그대로)
  3. 배치를 고릅니다. 목록에 마우스를 올리면 각 배치의 쓰임이 나오고, 고르면 아래에 설명 · 뷰 개수 · 겹침(옆 / 줄 사이)과
     **미리보기**(구를 펼친 지도에 뷰마다 윤곽선과 점)가 나옵니다.

     | 배치 | 뷰 | 쓰임 |
     |---|---|---|
     | **COLMAP Overlap · 12 Views** (기본) | 4방향 × −35° / 0° / +35°, 위 줄은 45° 엇갈림 | 일반적인 360 → COLMAP 변환. 겹침이 많아 특징 매칭과 SfM이 안정적 |
     | **Cubemap · 6 Views** | 앞 · 오른쪽 · 뒤 · 왼쪽 · 위 · 아래 | 구 전체를 고르게 덮는 단순한 변환 |
     | **Horizon · 4 Views** | 수평 4방향(위 / 아래 없음) | 실내 · 건축물처럼 수평 중심, 빠른 처리. 하늘과 아래쪽 촬영자가 빠짐 |
     | **Two Rings · 16 Views** | ±35°에 8방향씩, 위 줄 22.5° 엇갈림 | 더 촘촘한 coverage와 겹침(실험용) |
     | **Custom** | yaw 목록 × pitch 목록 직접 입력 | 특수 촬영이나 실험용 |

  4. **FOV**(기본 90°)와 크기(**auto px** = 원본의 그 각도 해상도)를 정하고 **Export**. 뷰 개수와 겹침은 FOV에 따라 다시 계산됩니다.
- **확인**: 이미지 · 마스크 · 모델이 함께 바뀝니다. 뷰 이름은 `0001_y090_pm35.jpg`(yaw 90°, pitch −35°, `m` = 마이너스) 식입니다. ⊘ 프레임은 빠집니다.
  어느 배치가 학습 품질이 좋은지 확인된 자료는 없습니다. 뷰가 많을수록 덮는 범위와 겹침이 늘지만 이미지 수도 늘어납니다.
  같은 장면으로 360 그대로와 Pinhole을 둘 다 만들어 비교해 보길 권합니다.

> 📷 `img/03-convert-options.png` — Export 창의 New dataset + Pinhole views + 배치 목록

## C9. 피시아이 → Pinhole / 360

- **언제**: 피시아이 카메라 장면을 원근 뷰나 360으로 바꿀 때.
- **순서**: C8과 같이 New dataset에서 변환 목록의 **Pinhole views**(yaw · pitch 목록, 기본 −45 / 0 / 45 × −35 / 0 / 35) 또는 **360 (ERP)**(원본마다 한 장).
  Pinhole views의 미리보기에서 렌즈가 **절반도 못 채우는 뷰**는 회색 점선으로 나오고 만들지 않습니다(뷰 개수에서도 빠짐).
- **확인**: 렌즈가 못 본 부분(360의 뒤쪽, 뷰의 바깥)은 모든 마스크에서 **무시**로 써서, 검게 채운 부분을 학습하지 않습니다. 받는 카메라 모델은 [D5](04-reference.md#d5-colmap-장면--특수-object).

## C10. 듀얼 피시아이 → 360 → Pinhole

- **언제**: 앞뒤 피시아이 두 대(리그)로 찍은 장면. 이미지가 `images/cam0/`, `images/cam1/`처럼 카메라별 폴더에 있습니다.
- **순서**
  1. 장면을 열고 마스크를 만듭니다(두 카메라의 이미지가 모두 목록에 나옵니다).
  2. Export → New dataset → 변환 목록 **360 from camera pairs (N moments)**. 같은 순간의 두 장이 360 한 장이 됩니다.
     모델에 `frames.bin`(COLMAP 3.12+)이 있으면 그것으로, 없으면 폴더 짝(`cam0/0001.jpg` ↔ `cam1/0001.jpg`)으로 묶습니다.
  3. Pinhole까지 가려면 만든 360 데이터셋을 다시 열고(마스크는 Object로 불러옴, C4) C8대로 내보냅니다.
- **확인**: 이름은 카메라 폴더를 뺀 것(`0001.jpg`)입니다. 한 순간의 이미지 중 하나라도 ⊘면 그 순간은 통째로 빠집니다.

---

[← B. 추천 워크플로](02-workflow.md) · [설명서 목차](README.md) · 다음: [D. 기능 참고 →](04-reference.md)
