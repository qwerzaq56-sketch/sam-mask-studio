# 아이디어 백로그

아직 안 한 기능 아이디어를 적어두는 곳입니다. **끝난 항목은 [`ideas-log.md`](../log/ideas-log.md)로 옮깁니다.**
작은 UI 문제는 [`ui-issues.md`](ui-issues.md), 진행 기록은 [`PROGRESS_v0.4.md`](../log/PROGRESS_v0.4.md), 원칙은 [`ux-principles.md`](../design/ux-principles.md).

- 새 아이디어는 해당 섹션에 한 줄씩 추가합니다. 섹션이 없으면 새로 만들어도 됩니다.
- 구현을 시작하면 `(진행 중)`, 끝나면 `(완료, v0.x-pN)`을 붙이고, 다음 정리 때 로그로 옮깁니다.
- `(메모)`는 코드와 대조해 본 현재 상태·제안입니다 (2026-09-29 기준).

---

# 다음에 할 것

## COLMAP 호환 (기획 중)

- 기획서: [`specs/06-colmap.md`](../specs/06-colmap.md)(장면 열기, 마스크 세트) · [`specs/07-export-presets.md`](../specs/07-export-presets.md)(학습기별 Export, 프레임 빼기). C1 `v0.4-p23`, 학습기별 Export `v0.4-p24`. 마스크 세트 `v0.4-p25`, Spirula / Postshot `v0.4-p26`, 프레임 제외 + 새 데이터셋 `v0.4-p28`. 다음: 360 → Pinhole(08 기획, 작업 흐름 확인 필요).
- 원래 요청은 아래 "보류 / 구상"의 콜맵 호환 1~8.

---

# 보류 / 구상

## 갭 채우기 오토 툴 (보류)

- 마스크 아일랜드 사이의 좁은 갭이나 U자형 갭을 채우는 오토 툴.
- 기존 툴 알고리즘을 정리해서 GPT에게 평가받고 기획서를 받아 구현 예정.
- (메모) 알고리즘 위치: `src/core/refine.py` (fill_holes, remove_specks, grow_to_edges, grow_mask, shrink_mask).

## 콜맵 호환 (원래 요청, 기획서로 옮김)

1. GUI에서 작업한 결과물을 콜맵으로 패킹하는 익스포트 시스템.
2. 기존 콜맵의 이미지 폴더/마스킹 폴더 및 설정 파일을 읽어오고, 덮어쓸 때 수정할 수 있는 시스템.
3. 각 3DGS 트레이닝 프로그램에 맞춰서 서로 다른 양식으로 익스포트 (조사 필요).
4. 현재 작업 중인 폴더를 평가해서, 콜맵으로 이미 패킹된 데이터면 새로 내보내는 게 아니라 덮어쓰는 형태로 구현.
5. 선택한 프레임을 콜맵 데이터 상에서 제거하는 프레임 탈락 기능.
6. 이때 원본 데이터를 삭제하지 않고 백업할지 체크박스로 정할 수 있음.
7. 마스킹은 단일 폴더가 아닌 여러 세팅으로 내보낼 수 있음.
8. 이때 각 마스킹에 대해 이름(폴더명 구분자)과 어떤 오브젝트를 Merge해서 만들지 선택할 수 있어야 함.

- (메모) v0.3 요청 목록의 6단계(COLMAP)와 같은 주제: [`specs/04-v0.3-requests.md`](../specs/04-v0.3-requests.md).
  지금 Export는 `{stem}.png` / `{name}.png`(COLMAP 방식) 한 폴더만 지원.

## 스카이 마스크 (구상 미확정)

피사체/하늘을 분리해서 학습하는 워크플로 구현을 위한 핵심 기능. 아래 리서치를 참조하여 구현.

- https://github.com/xiongzhu666/Sky-Segmentation-and-Post-processing
- https://github.com/zhengPeng7/BiRefNet
- https://ar5iv.labs.arxiv.org/html/1712.09161

- (메모) GPT 리뷰의 "Sky를 특수 Object 타입으로, Source: SAM3 / Sky Segmentation / Manual" 제안과 연결됨.
