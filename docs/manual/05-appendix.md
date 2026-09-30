# E. 부록

[← D. 기능 참고](04-reference.md) · [설명서 목차](README.md)

## E1. 파일 위치

| 무엇 | 어디 | 메모 |
|---|---|---|
| 작업 파일(프로젝트) | 이미지 폴더 **옆** `<폴더>.sms/`, 장면이면 장면 **옆** `<장면>.sms/` | 자동 저장. 학습기와 COLMAP 로더가 폴더를 통째로 읽기 때문에 안에 두지 않습니다. 예전에 장면 안(`images.sms/`)에 만든 프로젝트는 그대로 씁니다 |
| 썸네일 캐시 | `<폴더>.sms/thumbs/` | 지워도 다시 만들어집니다 |
| 포인트 레이어 조각 | 작업 파일 안 `<이미지 키>.L1.png` … | 레이어의 포인트와 +/−는 작업 파일의 json에 |
| Sky 캐시 | 작업 파일 안 `special/sky/`, `special/sky_refined/` | 모델 결과와 다듬은 결과(작업 해상도) |
| 장면에 쓴 마스크 | 장면의 `masks/`(Postshot은 `masks_postshot/`), 세트는 `masks_<이름>/` | [D7](04-reference.md#d7-학습기별-마스크-규칙) |
| 마스크 백업 | 장면의 `masks_backup_<시각>/` | Into the scene으로 덮어쓰기 전에 옮긴 옛 파일. 하위 폴더(`cam0/` …) 유지 |
| Custom Export 기본 | `<폴더>_masks/` | For = Custom일 때 |
| 앱 설정 | 앱 폴더의 `config.local.json` | 체크포인트 경로, 접은 칸, 고른 학습기 등. 앱 폴더 안의 경로는 상대 경로로 저장 |

## E2. 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| 상태 표시줄에 `SAM2 loading… (N waiting)` | 모델을 불러오는 중입니다. 그동안 찍은 포인트 / 박스는 기다렸다가 계산됩니다(지금 이미지는 바로, 다른 이미지는 그 이미지를 열 때). 포인트 **레이어**에 찍는 클릭은 로딩 중에는 안내만 나옵니다 |
| 느리거나 GPU 메모리가 부족함 | File → Settings… → **Working max side (px)**를 낮춥니다(편집 해상도만 바뀌고 Export는 원본 해상도) |
| Sky Mask를 만들 수 없음 | Settings → **Sky model (ONNX)**에 `skyseg.onnx`가 있어야 합니다. 아주 어두운 밤하늘은 하늘로 잡히지 않을 수 있습니다 |
| 변환할 때 "No image here uses a camera this can convert" | 장면의 카메라 모델이 변환 목록에 없습니다. 받는 모델은 [D5](04-reference.md#d5-colmap-장면--특수-object) |
| Export 검사에 카메라 모델 경고 | 고른 학습기가 그 카메라를 읽는지 확인되지 않았습니다(예: Brush와 360 카메라). 필요하면 New dataset으로 Pinhole 변환([C8](03-recipes.md#c8-360erp--pinhole)) |
| 장면에 쓰면 옛 마스크는? | 내보내는 이미지의 옛 마스크(`a.png`, `a.jpg.png` 둘 다)는 `masks_backup_<시각>/`으로 옮겨져 이미지마다 한 파일만 남습니다. 원본 `images/`, `sparse/`는 바뀌지 않습니다 |
| New dataset이 안 됨 | 출력 폴더가 **비어 있어야** 합니다. 검사 목록에 이유가 나옵니다 |
| LichtFeld에서 마스크가 무시됨 | LichtFeld의 Training → Mask Mode 기본값이 None입니다. **Ignore**로 바꿉니다 |
| 장면을 열 때 ⚠ 로그 | COLMAP 모델에 없는 이미지가 `images/`에 있거나 그 반대입니다. 앞 5개 이름이 나옵니다 |
| 패널이 사라짐 | View → **Panels**에서 다시 켭니다 |

## E3. 용어집

| 용어 | 뜻 |
|---|---|
| **3DGS** | 3D Gaussian Splatting. 여러 사진으로 장면을 학습하는 방식 |
| **COLMAP** | 사진들의 카메라 위치(포즈)와 3D 점을 계산하는 프로그램. 결과는 `sparse/0/`의 `cameras`, `images`, `points3D` |
| **장면(Scene)** | `images/`와 COLMAP 모델(`sparse/0/`)이 있는 폴더 |
| **ERP / 360** | Equirectangular. 360° 전체를 가로 2 : 세로 1로 편 사진 |
| **Pinhole** | 보통 카메라처럼 원근으로 찍힌 사진. 대부분의 학습기가 읽는 형식 |
| **피시아이** | 아주 넓은 화각의 렌즈. 원형 피시아이는 원 바깥이 검습니다 |
| **듀얼 피시아이** | 앞뒤 피시아이 두 대로 360°를 찍는 카메라(리그) |
| **Detection** | SAM3가 글자로 찾은 후보 |
| **Object** | 작업 대상 하나. 프레임마다 마스크. 학습에서 무시할 것 |
| **Variant** | SAM2가 낸 마스크 후보 중 하나 |
| **포인트 레이어** | Object 안에서 자기 포인트로 따로 만든 더하기(+) / 빼기(−) 조각 |
| **Edit Layer** | 브러쉬와 오토 툴로 한 손질 |
| **Final Mask** | 체크된 Object들의 합. 내보내는 것 |
| **마스크 세트** | 체크한 Object 묶음에 붙인 이름. 따로 된 폴더로 내보냄 |
| **특수 Object** | 설정값으로 만드는 Object(Sky Mask, Fisheye Lens Edge) |
| **키프레임 `★`** | 직접 편집한 프레임. 전파의 출발점 |
| **기준 ◎** | 전파를 시작할 프레임(더블클릭으로 지정) |
| **전파(Propagation)** | 한 프레임의 마스크를 SAM2 비디오로 앞뒤 프레임에 옮기는 것 |
| **⊘ 제외** | 새 데이터셋에서 뺄 프레임 표시. 원본은 바뀌지 않음 |
| **하드링크** | 같은 드라이브에서 파일을 복사하지 않고 한 번 더 가리키는 것. 용량을 더 쓰지 않음 |

---

[← D. 기능 참고](04-reference.md) · [설명서 목차](README.md)
