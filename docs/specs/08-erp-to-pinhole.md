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

**결정**: 표준 배치를 프리셋으로(기본 COLMAP overlapping 12, 전의 기본과 같되 위 줄만 45° 돌림), 격자는 Custom으로 남김. 피시아이 원본은 한 방향을 보므로 전처럼 격자.

출처: [COLMAP `pycolmap/panorama.py`](https://github.com/colmap/colmap/blob/main/python/pycolmap/panorama.py) ·
[COLMAP Rig Support](https://colmap.github.io/rigs.html) ·
[nerfstudio custom data](https://docs.nerf.studio/quickstart/custom_dataset.html) ·
[LichtFeld 360 plugin](https://github.com/alexmgee/lichtfeld-360-plugin) ·
[OmniGS (WACV 2025)](https://openaccess.thecvf.com/content/WACV2025/papers/Li_OmniGS_Fast_Radiance_Field_Reconstruction_using_Omnidirectional_Gaussian_Splatting_WACV_2025_paper.pdf) ·
[ODGS (NeurIPS 2024)](https://papers.nips.cc/paper_files/paper/2024/file/6882dbdc34bcd094e6f858c06ce30edb-Paper-Conference.pdf)

