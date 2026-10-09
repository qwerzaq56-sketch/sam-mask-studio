# 명령줄 약속 (splatbatch용)

splatbatch(`F:\Claude\SplatBatch`)가 SAM Mask Studio를 부를 때 기대해도 되는 것입니다.
아래 내용이 바뀌는 버전은 **약속 번호를 올리고** splatbatch 담당 세션("3DGS 하늘 학습")에 알립니다.
번호가 같으면 옵션을 더하는 것은 괜찮고, 빼거나 뜻을 바꾸는 것은 안 됩니다.

| 약속 번호 | 처음 들어간 버전 | 바뀐 것 |
|---|---|---|
| 1 | `v0.4-p118` (2026-10-08) | 처음 정함 |
| 2 | `v0.4-p127` (2026-10-09) | 렌즈 단계 기본 여유 2 % → **5 %**(찾은 원 반지름의 95 % 밖이 검정). 옵션 · 폴더 · 이름은 그대로. 0022에서 원 0.95 밖은 흐리고 특징점이 거의 없어, 2 %일 때 정합이 2–4 모델로 갈라졌음 |
| 3 | `v0.4-p130` (2026-10-09) | 렌즈 단계가 원을 **둘로** 나눔. 프리셋 `lens`에 `sfm_radius` · `sfm_cx` · `sfm_cy`(정합 전용 원, %)가 있으면 `run`이 **`masks_sfm\`** 도 씀(사람 + 그 원 밖 검정). `masks\`는 학습 · 스티칭용 넓은 원. OSMO 프리셋: `masks\` = 찾은 원 5 % 안(렌즈당 약 201°, 두 렌즈 겹침 약 22°), `masks_sfm\` = rim95(반지름 95 %, 약 185°, 겹침 약 5°, 0022 정합 188/188). `folders`에 `sfm` 키 |
| **4** | `v0.4-p131` (2026-10-09) | 렌즈 단계 기본 여유 5 % → **7 %**(찾은 원 반지름의 93 % 밖이 검정 = Spirula 자동 마스크와 같은 비율, 0022 렌즈당 약 194°, 두 렌즈 겹침 약 14°). OSMO 프리셋 `masks\` = Spirula 자동 마스크 원 고정(반지름 98.0 %, 중심 +0.34 / −3.16 %, 0022 정합 186/188), `masks_sfm\`은 rim95 그대로. 옵션 · 폴더 · 이름은 그대로 |

- 앱 버전 문자열: `src.version.app_version()`. 포터블은 `VERSION` 파일, 개발 폴더는 `git describe`(예: `v0.5.1-128-g6259be4`). `run` 보고서의 `"version"`에도 같은 값이 들어갑니다.
- 실행: 앱 폴더에서 `python -m src.cli …`(포터블은 그 안의 `python\python.exe`).
- 약속 번호는 코드에서 `src.version.CLI_CONTRACT`, 포터블은 `PARTS.json`의 `cli_contract`(6장).

## 1. `run`

```text
python -m src.cli run <images> --preset <이름 | .json> --out <장면 폴더>
                      [--recursive] [--names name|stem]
                      [--skip-existing | --overwrite] [--report <file.json>]
                      [--sky-model <skyseg.onnx>] [--sam3-model <sam3.pt>]
                      [--cpu] [--gpu-anyway]
```

| 옵션 | 약속 |
|---|---|
| `<images>` | 이미지 폴더 |
| `--preset` | `preset list`의 이름, 또는 프리셋 `.json` 파일 |
| `--out` | 장면 폴더. 아래 2장의 폴더를 그 안에 만듦 |
| `--recursive` | 하위 폴더(`cam0/`, `cam1/`)까지, 출력에도 같은 하위 폴더 |
| `--names` | `name`(기본): `00011.jpg.png` · `stem`: `00011.png` |
| (둘 다 없음) | 출력 폴더에 PNG가 하나라도 있으면 **아무것도 하지 않고** 끝남(종료 코드 1, 메시지 `Masks already there: …`) |
| `--skip-existing` | 있는 마스크는 두고 나머지만 만듦 |
| `--overwrite` | 있는 마스크를 바꿔 씀 |
| `--report` | 보고서 JSON(3장)을 그 경로에 씀 |
| `--cpu` | 모델 단계(사람 SAM3, 하늘 마무리 SAM2)를 CPU로. 매우 느림(SAM2 약 10배, SAM3는 더) |
| `--gpu-anyway` | 빈 GPU 메모리가 모자라도 시작 |

- **GPU 확인**: 사람 단계가 있으면 빈 GPU 메모리 5 GB, 하늘 단계에 색 프리셋(SAM2 마무리)이 있으면 1 GB가 없을 때 아무것도 하지 않고 끝납니다(종료 코드 1, 메시지 `Only N GB of GPU memory is free …`). `--gpu-anyway`면 이 확인을 건너뛰고, `--cpu`면 GPU를 보지 않습니다. 렌즈만 · 하늘(색 프리셋 없음)만 있는 프리셋은 GPU를 쓰지 않습니다.
- **종료 코드**: `0` 모두 씀 · `1` 실패한 이미지가 있음, 또는 시작 전에 멈춤(이미지 없음, 마스크가 이미 있음, GPU 메모리 부족, 단계 없는 프리셋. 메시지는 stderr) · `2` 옵션 오류(argparse: 모르는 프리셋, 모델 파일 없음, CUDA GPU 없음).

## 2. 출력 폴더와 파일

| 폴더 | 언제 | 흑백 |
|---|---|---|
| `masks\` | 사람 또는 렌즈 단계가 있을 때. 둘 다 있으면 **사람 + 렌즈 테두리를 합친 것** | **검정 = 무시**, 흰색 = 학습 |
| `masks_sfm\` | 프리셋 렌즈에 `sfm_radius`가 있을 때(약속 3). `masks\`와 같되 렌즈 원이 정합용(더 좁은) 원. **정합(SfM)에만** 쓰고 학습은 `masks\` | **검정 = 무시** |
| `people_masks\` | 사람과 렌즈가 둘 다 있을 때만, 사람만 따로 | 검정 = 사람 |
| `sky_masks\` | 하늘 단계가 있을 때 | **흰색 = 하늘** |

- 파일 이름: 이미지 이름 + `.png`(`--names name`), 하위 폴더 구조는 이미지 폴더와 같음.
- 8bit PNG, 값은 0 / 255, 이미지 원본 해상도.
- 어느 프리셋에 어느 단계가 있는지는 `preset show <이름> --json`의 `person` · `lens` · `sky`가 `null`인지로 압니다.

## 3. `run` 보고서 (`--report`)

JSON 객체. splatbatch가 읽어도 되는 키:

| 키 | 뜻 |
|---|---|
| `command` | `"run"` |
| `version` | 앱 버전 문자열 |
| `folders` | 단계 → 출력 폴더 경로(`person`, `lens`, `sfm`, `sky`) |
| `written` | 쓴 마스크 수(모든 단계 합) |
| `skipped_existing` | 그대로 둔 마스크 수 |
| `failed` | `[{"image", "error", "step"}]` |
| `seconds` | 걸린 시간 |
| `preset` | 쓴 프리셋 전체(`preset show --json`과 같은 모양) |

`steps` 아래 단계별 내용은 진단용이라 약속에 넣지 않습니다(바뀔 수 있음).

## 4. `preset list`, `preset show`

```text
python -m src.cli preset list
python -m src.cli preset show <이름> [--json]
```

- `preset list`: 한 줄에 하나, `이름  단계(person, lens, sky)  checked | NOT CHECKED  제목  [built-in | 파일 경로]`. 마지막 줄은 `Your presets: <폴더>`. 읽을 수 없는 파일은 `(unreadable) …` 줄. 기계가 읽을 때는 **첫 칸(이름)만** 약속이고, 나머지는 사람이 읽는 글입니다.
- `preset show <이름> --json`: 프리셋 JSON(`name`, `title`, `description`, `checked_on`, `person`, `lens`, `sky`). splatbatch가 단계와 확인 여부(`checked_on`이 비었는지)를 볼 때는 이것을 씁니다.
- 내 프리셋 폴더: 앱 폴더의 `mask_presets\`, 또는 환경 변수 `SMS_MASK_PRESETS`.

## 5. 약속 밖

`sky`, `person`, `lens`, `probe`, `truth` 명령과 `run`의 `steps` 내용은 splatbatch 약속이 아닙니다(앱 · 스터디용, 예고 없이 바뀔 수 있음).

## 6. 포터블 나눈 묶음 (`tools/make_portable.py --split`)

| 파일 | 안의 것 | 바뀔 때 |
|---|---|---|
| `sms-<버전>-app.zip` | `app\` (checkpoints 빼고), `SAM Mask Studio.bat`, `README.txt`, `PARTS.json` | 매 릴리스 |
| `sms-runtime-<해시>.zip` | `python\` (Python + 모든 패키지) | 의존성이 바뀔 때 |
| `sms-models-<해시>.zip` | `app\checkpoints\` (SAM2 tiny, SAM3, Sky) | 거의 없음 |
| `sms-<버전>-parts.json` | 위 셋의 이름 · 바이트 · sha256 · 파일 수, `version`, `cli_contract` | |

- 셋 다 포터블 폴더 이름(`SAMMaskStudio\…`)을 뿌리로 담음: **한 폴더에 셋을 풀면 지금 포터블과 같습니다.**
- `<해시>`는 그 묶음의 파일 경로 + 크기에서 나온 12자리. 같은 파일이면 같은 이름이라 이미 받은 런타임 · 모델은 다시 받지 않아도 됩니다.
- 앱 묶음의 `PARTS.json`: `{"version", "cli_contract", "runtime", "models"}` — 필요한 런타임 · 모델 이름(`.zip` 없이).
