# SAM Mask GUI — 투영 변환(Fisheye / ERP → Pinhole / ERP) 기획서

360 ERP(equirectangular) COLMAP 장면을 **ERP 그대로**와 **원근(Pinhole) 뷰로 나눈 것** 두 가지로 내보내, 같은 촬영을 두 방식으로 학습해 비교한다.
출처: 사용자 요청 "ERP랑 Pinhole 둘 다 테스트", "가능하면 Fisheye → ERP → Persp 다 되면 좋겠음"(2026-09-30), [`07-export-presets.md`](07-export-presets.md) 10장.

**구조**: 변환기는 "원본 카메라 모델 → 목표(Pinhole 뷰들 / ERP)" 하나다. 목표의 픽셀마다 광선을 만들고, 원본 모델의 **투영식(광선 → 픽셀)**으로
원본 이미지에서 값을 가져온다. ERP · PINHOLE 계열 · OPENCV_FISHEYE 계열의 투영식은 모두 닫힌 식이라 모델을 추가하는 것은 투영 함수 하나를 더하는 일이다.

---

## 1. 두 출력

| 출력 | 방법 | 읽는 학습기 |
|---|---|---|
| **ERP** | 지금의 New dataset(07 6장) 그대로: 이미지 링크, 모델 걸러 쓰기, 마스크 | LichtFeld(SPHERICAL), Spirula(360 직접) |
| **Pinhole** | New dataset + **Pinhole 뷰로 변환**: ERP 한 장 → 가상 원근 카메라 N장 | 모두(Brush, LichtFeld, Spirula, Postshot, COLMAP 계열) |

원본 장면은 바꾸지 않는다(07의 원칙). 마스크는 학습기 규칙(07 4장)대로, 이미지와 **같은 재투영**을 거쳐 뷰마다 쓴다.

---

## 2. COLMAP의 ERP 규칙 (소스 확인)

- 카메라 모델 `EQUIRECTANGULAR`, id **17**, 파라미터 `w, h`(초점·주점 없음). `colmap/src/colmap/sensor/models/spherical.h`.
- 카메라 좌표: X 오른쪽, Y 아래, Z 앞. 방위 θ = atan2(X, Z)(앞 = 0, 오른쪽 = +90°), 고도 φ = atan2(−Y, √(X²+Z²)).
- 픽셀: x = (θ / 2π + 0.5) · W, y = (0.5 − φ / π) · H.

---

## 3. 가상 카메라 (기본값)

| 설정 | 기본 | 뜻 |
|---|---|---|
| 방위(yaw) | 0°, 90°, 180°, 270° | 수평으로 4방향 |
| 고도(pitch) | −35°, 0°, +35° | 아래 / 수평 / 위 |
| 시야각(FOV) | 90° | 가로·세로 같음 |
| 크기 | ERP 너비 ÷ 4 (정사각형) | FOV 90°에서 ERP 적도의 해상도와 비슷 |

- 뷰 수 = 방위 × 고도 = **12장 / ERP 한 장**. Export 창에서 방위 개수, 고도 목록, FOV, 크기를 바꿀 수 있다.
- 카메라: `PINHOLE` 하나를 모든 뷰가 같이 씀(fx = fy = 크기 / 2 / tan(FOV/2), cx = cy = 크기 / 2).
- 포즈: 뷰의 회전 R_v(ERP 카메라 → 뷰)로 `R = R_v · R_erp`, `t = R_v · t_erp`(카메라 중심은 ERP와 같음).
- 이름: `<원래 이름에서 확장자 뺀 것>_y<방위>_p<고도>.jpg`(예: `frame_010_y090_pm35.jpg`, 음수는 `m`).

## 4. 3D 점

- 각 점이 원래 보이던 ERP 이미지의 뷰들에 **다시 투영**해서, 뷰 안에 들어오면 그 뷰의 2D 점과 트랙으로 넣는다.
- 관측이 2개 미만이 된 점은 지운다(07과 같은 규칙). 색·위치·오차는 그대로.

## 5. 이미지·마스크 재투영

- 이미지: 양선형 보간, 좌우는 이어 붙여(360°) 경계 없이. JPEG 품질 95.
- 마스크: 최근접 보간(0 / 255 그대로), 원본 해상도의 최종 마스크를 재투영한 뒤 학습기 규칙으로 흑백.
- ⊘ 제외 프레임은 뷰도 만들지 않는다.

## 6. 단계

| 단계 | 내용 |
|---|---|
| P1 (`v0.4-p29`, **완료**) | 카메라 표에 id 12~17(ERP 포함), 변환 틀(`src/core/reproject.py`), **ERP → Pinhole 뷰**: 이미지·마스크·모델 |
| P2 (`v0.4-p30`, **완료**) | **Fisheye → Pinhole 뷰 / ERP**: OPENCV_FISHEYE, SIMPLE_FISHEYE / FISHEYE 등 원본 모델의 투영식 추가. Pinhole → Pinhole(왜곡 제거)도 같은 틀 |
| P3 (`v0.4-p32`, **완료**) | 듀얼 피시아이(카메라 두 대, 리그) → ERP 한 장으로 이어 붙이기: `frames.bin` 또는 폴더 짝으로 묶음. 하위 폴더 이미지(`v0.4-p31`) 필요 |
| P4 | 뷰 배치 프리셋(`v0.4-p57`): COLMAP overlapping 12(기본) · Cubemap 6 · Horizon 4 · Two rings 16 · Custom. 아래 §8 |

## 7. 정할 것

- [ ] 기본 뷰 배치(4 × 3 = 12장)가 괜찮은지, 다른 배치를 자주 쓰는지 (써 보고)
- [ ] 이름 규칙(`_y090_pm35`)이 학습기에서 문제 없는지

## 8. 뷰 배치 리서치 (P4, 2026-09-30)

요청: 표준으로 쓰는 변환 옵션을 조사해 넣거나, 차이가 없으면 근거를 줄 것.

**표준으로 쓰이는 배치** (모두 90° 뷰)

| 도구 | 배치 | 비고 |
|---|---|---|
| COLMAP `panorama_sfm` 예제(`pycolmap.panorama`) | **overlapping**: yaw 4개 × pitch −35 / 0 / 35 = 12, 위 줄은 45° 돌림(기본) · **non-overlapping**: 수평 4개(큐브의 위아래 뺌) | 크기 규칙: 폭 = ERP 폭 × FOV / 360 (우리 auto와 같음). 360을 직접 쓰는 것보다 느리지만 정확하다고 문서에 적음 |
| nerfstudio `ns-process-data --camera-type equirectangular` | 360 한 장당 8장(기본) 또는 14장(COLMAP이 잘 안 맞을 때), `--crop-factor`로 아래쪽(촬영자) 자르기 | 배치 각도는 문서에 없음 |
| LichtFeld 360 플러그인 | Cubemap 6 · Low 12 · Medium 16(±35° 두 줄 8 + 8, 위 줄 엇갈림) · High 20 · Ultra 24(나선) | 기본 추천 없음, 품질 비교 없음 |

**품질 차이의 근거**
- 3DGS 학습에서 뷰 개수(6 / 12 / 24) 배치별 품질을 비교한 자료는 찾지 못함(플러그인 문서에도 없음).
- 연구 쪽 결론은 오히려 **나누지 않는 쪽**: 360을 그대로 학습하는 OmniGS / ODGS가 큐브맵으로 나눈 방식보다 좋다고 보고(큐브 면끼리 상관이 약하고 이음새가 생김).
  다만 Brush / LichtFeld / Postshot 같은 일반 학습기는 Pinhole을 받으므로 나누는 것이 현실적 선택.
- 실무 요인: **겹침**이 있으면 COLMAP 매칭이 안정(COLMAP이 overlapping을 기본으로 둔 이유). 뷰가 많으면 같은 픽셀을 여러 번 학습해 시간만 늘 수 있음.
  위 / 아래 뷰는 하늘 · 촬영자가 많아 빼거나 마스크(Horizon 4, 또는 Sky 특수 Object).

**결정**: 표준 배치를 프리셋으로(기본 COLMAP overlapping 12, 전의 기본과 같되 위 줄만 45° 돌림), 격자는 Custom으로 남김. 피시아이 원본은 한 방향을 보므로 전처럼 격자(→ p121부터 렌즈용 배치 목록, 8.2).

### 8.1 프리셋의 역할과 구조 (`v0.4-p58`, GPT 리뷰 반영)

| 배치 | 역할 |
|---|---|
| **COLMAP Overlap · 12 Views**(기본) | COLMAP panorama SfM 방식 기반의 overlapping perspective views. 일반적인 360 → COLMAP 변환의 기본값, 특징 겹침 / SfM 안정성 중심 |
| **Cubemap · 6 Views** | 90° 단위 6방향, 구 전체를 고르게 덮는 단순 · 직관적 변환 |
| **Horizon · 4 Views** | 수평 4방향(위 / 아래 없음). 실내 · 건축물처럼 수평 공간 중심, 빠른 처리 |
| **Two Rings · 16 Views** | 상 · 하 두 줄. 수직 방향 coverage와 overlap이 늘어남(품질이 더 좋다고 하지 않음): dense coverage / SfM 안정성 실험용 |
| **Custom** | yaw × pitch를 직접: 특수 촬영 환경이나 실험용 |

- 이름은 "COLMAP 카메라 모델"이 아니라 "COLMAP 방식의 뷰 배치"로 읽히게. 프리셋은 더 늘리지 않음.
- **구조**: 배치는 이미지 목록이 아니라 규칙 — `ViewLayout(rings = Ring(pitch, 개수, 시작 yaw) …, poles = 위 / 아래)`.
  Projection(Pinhole) · 배치 · FOV · 해상도는 따로(`Views(layout, fov, size, yaw_offset)`), 뷰 개수와 겹침(옆 / 줄 사이, 수평 기준)은 규칙에서 계산.
  FOV 110° / 120°도 같은 규칙으로. 전체 회전(`yaw_offset`)은 구조만 있고 화면에는 아직 없음.
- **360 / 피시아이 분리**: 360(ERP)은 구 전체에 배치(프리셋 목록). 피시아이는 렌즈가 보는 쪽에 격자(yaw × pitch)이고,
  **렌즈가 절반도 못 채우는 뷰는 만들지 않음**(`MIN_VIEW_SHARE` = 0.5, 전에는 검은 이미지 + 무시 마스크로 만들었음). 결과 보고에 뺀 수.
- **미리보기**: Export 창에 뷰 지도(구를 360 이미지처럼 펼친 것: 가운데 = 정면, 위 = 위쪽). 뷰마다 윤곽선과 가운데 점, 선이 겹치는 곳이 겹침.
  피시아이가 못 채워 빠지는 뷰는 회색 점선. 배치의 역할 · 뷰 개수 · 겹침을 한 줄로.

### 8.2 피시아이 렌즈용 배치 (`v0.4-p121`, 기획 Export 10장 C-9 (a))

피시아이 장면에서 Layout 줄이 숨어 "프리셋이 없어진" 것처럼 보였음. 360 배치를 렌즈 하나에 쓰면 뷰 절반이 렌즈 밖을 담음
(0022, FOV 90°: COLMAP · 12는 12개 중 8개만 남고 다 보이는 건 4개). 그래서 피시아이에는 렌즈 안에 다 들어가는 배치만.

| 배치 | 뷰 | 역할 |
|---|---|---|
| **Fisheye Grid · 9 Views**(기본) | 방위 −45 / 0 / 45 × 고도 −35 / 0 / 35 | 전의 기본 격자와 같음. 렌즈가 보는 대부분, 매칭용 겹침 |
| **Fisheye Cross · 5 Views** | 정면 + 왼 / 오른 / 위 / 아래 45° | 이미지 수를 줄임, 렌즈 모서리 쪽은 안 씀 |
| **Fisheye Level · 3 Views** | 수평 −45 / 0 / 45 | 수평 공간, 빠름. 하늘과 아래쪽 촬영자 빠짐 |
| **Custom** | yaw × pitch 직접 | 전과 같음 |

- 구조: `ViewLayout.points` = 낱개 (yaw, pitch) 방향(렌즈 축 기준). `FISHEYE_LAYOUTS`, 360 배치와 합친 `ALL_LAYOUTS`.
  겹침 계산은 고도가 같은 뷰끼리의 가장 가까운 yaw 간격 + 고도 사이 간격으로 일반화(360 배치 값은 전과 같음).
- 목록은 변환 종류에 따라 다시 채움(고른 배치는 종류마다 기억). 평범한 Pinhole 원본은 목록 없이 격자.

### 8.4 가상 카메라 배치 그림 (`v0.4-p124`)

사용자 요청(10-08): “핀홀 변환 시 가상 퍼스펙 카메라 배치가 어떻게 되는지 가독성 좋은 참고 이미지 필수”.

- Export 창: 지도(`ViewPreview`) 옆에 `RigPreview`(190 px): 구 위에 뷰마다 타일(이미지의 네 모서리, 실제 FOV의 0.42배로 줄여 이웃과 떨어지게),
  중심에서 점선, 번호는 지도 점 옆 번호와 같음. 색 = 줄(위 > 10° 주황, 수평 파랑, 아래 < −10° 초록, 빠지는 뷰 회색 점선). 지도 윤곽도 같은 색.
  시점: 원본 앞쪽 왼편 위(방위 330°, 고도 30°). 뒤쪽 타일은 흐리게. 피시아이 = 렌즈 끝(정면 90° 원), 카메라 짝 = 두 렌즈가 만나는 원을 빨강.
  (뒤에서 본 시점도 시험했으나 정면 뷰들이 멀고 겹쳐 읽기 어려웠음.)
- 참고 그림: `python tools/layout_pictures.py [폴더] [--fov 90]` → `layout_<배치>.png`(1100 × 512, 지도 + 3D + 색 설명). 매뉴얼 C8 · C9에 넣음.

### 8.3 카메라 짝 → Pinhole (`v0.4-p122`, 기획 Export 10장 C-10 (a))

- 변환 목록 **Pinhole views from camera pairs (N moments)**: 한 순간(리그의 렌즈들)을 구 하나로 보고 360 배치 목록(8.1)을 씀.
- `stitch_to_erp(..., views=Views)`(`Stitch.views`): 360 이음과 같은 코드에서 출력만 바뀜. 뷰의 각 픽셀 광선을 렌즈마다 투영해
  이미지 원 가중치로 섞음(보간 한 번). 한 렌즈 안의 뷰는 그 렌즈 단독 재투영과 같은 픽셀, 걸친 뷰는 360과 같은 이음.
  마스크는 더 강한 렌즈 값, 어느 렌즈도 못 본 곳은 무시. 렌즈들이 절반도 못 채우는 뷰는 만들지 않음.
- 포즈 = 뷰 회전 × 그 순간의 기준 카메라 포즈(`R = R_v·R_ref`, `t = R_v·t_ref`), 카메라 하나(PINHOLE), 이름 `<순간>_y090_p00.jpg`.
- 0022 실물(2순간 × COLMAP 12, FOV 90, auto 2096 px): 24장, 빠진 뷰 0, CPU 51초. 렌즈 경계를 지나는 아래쪽 뷰(y090 / y270, −35°)에
  가는 이음선이 보임(360 이음과 같은 섞기).

출처: [COLMAP `pycolmap/panorama.py`](https://github.com/colmap/colmap/blob/main/python/pycolmap/panorama.py) ·
[COLMAP Rig Support](https://colmap.github.io/rigs.html) ·
[nerfstudio custom data](https://docs.nerf.studio/quickstart/custom_dataset.html) ·
[LichtFeld 360 plugin](https://github.com/alexmgee/lichtfeld-360-plugin) ·
[OmniGS (WACV 2025)](https://openaccess.thecvf.com/content/WACV2025/papers/Li_OmniGS_Fast_Radiance_Field_Reconstruction_using_Omnidirectional_Gaussian_Splatting_WACV_2025_paper.pdf) ·
[ODGS (NeurIPS 2024)](https://papers.nips.cc/paper_files/paper/2024/file/6882dbdc34bcd094e6f858c06ce30edb-Paper-Conference.pdf)

