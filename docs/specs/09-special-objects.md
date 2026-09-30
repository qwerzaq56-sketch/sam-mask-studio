# 09 · 특수 Object (Sky, 피시아이 외곽)

> 원래 요청: [`backlog/ideas.md`](../backlog/ideas.md) "특수 마스크 구현", "스카이 마스크".
> 코드: `src/core/special.py`, `Session.update_special / compute_sky`, `src/app/special_panel.py`. 구현 `v0.4-p36`.

## 1. 의도

포인트로 찍는 대신 **설정값으로 만드는 마스크**. 여러 프레임에 한꺼번에 만들고, 설정을 바꾸면 모든 프레임이 따라 바뀐다.

- 특수 Object는 설정(종류, 값, 덮는 프레임)을 가진다. 마스크는 그 설정에서 매번 다시 만든다.
- 손으로 고치려면 **Apply** → 지금 마스크를 가진 보통 Object가 되고 설정은 사라짐(Ctrl+Z로 되돌림).
- 특수인 동안은 Edit(포인트 / 브러시)와 전파 대상에서 빠짐. 만든 값을 손으로 고쳐도 다음 설정 변경에 덮이기 때문.
- 마스크 자체는 보통 Object와 같음: Final Mask, 마스크 세트, Export, 잠금, 삭제 모두 그대로.

## 2. 만들기와 패널

- Objects 패널 **+ Special ▾** → Sky Mask / Fisheye Lens Edge. 마스크가 없어도 목록에 항상 나옴.
- Properties에 **Special** 탭(Mask / Edit Layer 탭 대신):
  - **Frames**: All frames / Range(1-based) / Frame List에서 고른 프레임 → **Make … Masks**. 덮는 프레임은 누적(합집합).
  - **Settings**: 움직이면 0.25초 뒤 덮는 프레임 전체에 적용(한 번이 Undo 한 단계).
  - **Apply (make it an ordinary Object)**.

## 3. Sky

- 모델: [Sky-Segmentation-and-Post-processing](https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing)의 U2Net
  ONNX(`skyseg.onnx`, 약 170 MB, [Hugging Face JianyuanWang/skyseg](https://huggingface.co/JianyuanWang/skyseg), VGGT가 쓰는 것과 같은 파일).
  경로는 Settings → Sky model (기본 `checkpoints/sky/skyseg.onnx`). onnxruntime이 있으면 그것, 없으면 OpenCV DNN으로 실행(추가 설치 없음).
- 입력: RGB 320 × 320, ImageNet 평균/표준편차 정규화. 출력은 최소~최대로 늘여 0~255, 이미지 크기로 되돌림(참조 코드와 같음).
- **Refine edges**: 저장소의 `mask_refine`(신뢰도 가중 가이디드 필터)를 옮긴 것. 모델이 확실한 곳(0.3 미만 / 0.5 초과)에서
  색 → 하늘 값의 선형 관계를 넓은 구역(긴 변의 1/4)마다 맞추고 전체에 적용, 마지막에 양방향 필터.
  합성 테스트에서 거친 맵의 IoU 0.91 → 0.99.
- 거의 검은 픽셀(모든 채널 32 미만)은 하늘이 아님: 실제 피시아이에서 원 바깥의 검은 모서리가 하늘로 잡혔음(`v0.4-p47`).
  보정 전에 빼서 "검정 = 하늘"을 배우지도 않게 함. 아주 어두운 밤하늘은 빠질 수 있음.
- 모델 결과는 프레임마다 `<프로젝트>/special/sky/`, 다듬은 결과는 `sky_refined/`에 캐시(작업 해상도 PNG). 설정 변경은 모델을 다시 돌리지 않음.
- 설정:
  - **Threshold** %: 이 값 이상을 하늘로(기본 50).
  - **Grow / shrink** px: 넓히기(+) / 좁히기(−).
  - **Refine edges**(기본 켬).
  - **Only sky touching the top edge**: 위 가장자리에 닿은 조각만(창문, 물, 반사 제거). 360(ERP)에 맞음, 피시아이에는 끄기.
- "커브"는 따로 두지 않음: 이진 마스크에서는 커브를 거친 뒤 자르는 것이 임계값 하나를 옮기는 것과 같음.

## 4. Fisheye Lens Edge

- 이미지 원 **바깥**이 마스크(학습에서 무시할 것 = Object 규칙과 같음).
- 설정: **Radius**(짧은 변 절반 대비 %, 100 = 내접원), **Center X / Y**(같은 단위로 이동).
- **Detect from Images**: 덮는 프레임 중 최대 8장의 평균에서 검지 않은 영역을 찾고, 프레임 가장자리가 아닌 테두리에 원을 맞춤.
  테두리가 전혀 없으면(풀프레임) 찾지 않음.

## 5. 남은 것

- ~~실제 skyseg.onnx로 OpenCV DNN 실행 확인, 속도~~ → `v0.4-p47`: OpenCV DNN으로 동작(추가 설치 없음), 1024 px에서
  모델 약 0.3초 + 보정 약 0.1초 / 프레임(CPU). 사용자 촬영본(OSMO 360 듀얼 피시아이, 360 ERP)에서 나뭇잎 사이 하늘까지 잡힘.
- 360 / 피시아이 원본에서의 Sky 품질(모델은 보통 사진으로 학습됨) — 필요하면 Pinhole 뷰로 나눠 추론 후 합치기.
- Sky 생성 중 취소 버튼.
