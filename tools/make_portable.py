"""Build a portable SAM Mask Studio folder that runs on another Windows PC without installing anything.

    .venv\\Scripts\\python.exe tools\\make_portable.py H:\\Dev\\Masking\\dist\\SAMMaskStudio --ref v0.5.1 --force --zip

``--zip`` also writes ``<out>-<version>-portable.zip`` next to the folder (root folder inside: the folder's name).
``--split`` also writes it as three parts next to the folder, for splatbatch's releases (its DEPLOY_PLAN 3.3):

    sms-<version>-app.zip          the program, launcher, README, PARTS.json (a few MB, every release)
    sms-runtime-<hash>.zip         python\\ (Python + packages, changes with the dependencies)
    sms-models-<hash>.zip          app\\checkpoints\\ (SAM2 tiny, SAM3, Sky; hardly ever changes)
    sms-<version>-parts.json       the three names, sizes, sha256, version and CLI contract number

Every part is rooted at the portable folder, so the three unzipped into one folder are the portable. ``<hash>`` comes
from the part's file list (path and size), so a part with the same files keeps its name and an existing one is not
written again; PARTS.json in the app part names the runtime and models it needs.
Model weights and already-compressed files are stored as they are (deflate barely shrinks them and costs most of the
time); the rest is deflated at a fast level.

Layout of the result (all paths inside are relative, so the folder can be copied anywhere):

    SAM Mask Studio.bat     double-click to run
    python\\                 the project's standalone CPython + every package from .venv
    app\\                    the program (git HEAD, or --ref) and app\\checkpoints (SAM2 tiny, SAM3, Sky)
    README.txt

Notes
- The SAM2 / SAM3 packages are editable installs in .venv (they point at vendor\\); their
  sources are copied into site-packages instead.
- The Visual C++ runtime DLLs PyTorch / OpenCV need are copied next to python.exe, so the
  target PC does not need the redistributable.
- Checkpoints are hard-linked when possible (same drive) — copying the folder elsewhere
  turns them into real files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY_HOME = REPO / ".tools" / "python" / "cpython-3.12.10-windows-x86_64-none"
SITE = REPO / ".venv" / "Lib" / "site-packages"
VC_DLLS = (
    "msvcp140.dll",
    "msvcp140_1.dll",
    "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
    "concrt140.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
    "vcomp140.dll",
)
SKIP_SITE = {"_virtualenv.pth", "_virtualenv.py", "__pycache__"}
# Stored, not deflated, in --zip: weights (float noise to deflate) and files that are compressed already.
STORE_SUFFIXES = {".pt", ".pth", ".safetensors", ".onnx", ".bin", ".ckpt",
                  ".zip", ".whl", ".gz", ".bz2", ".xz", ".7z", ".png", ".jpg", ".jpeg", ".webp", ".mp4"}

LAUNCHER = r"""@echo off
rem SAM Mask Studio (portable). Everything it needs is in this folder.
setlocal
set "PYTHONHOME="
set "PYTHONPATH="
set "PYTHONNOUSERSITE=1"
cd /d "%~dp0app"
"%~dp0python\python.exe" -m src.main %*
if errorlevel 1 pause
"""

LAUNCHER_CPU = LAUNCHER.replace("rem SAM Mask Studio (portable).", "rem SAM Mask Studio (portable), SAM on the CPU: "
                                "the GPU is left to a training.").replace("-m src.main %*", "-m src.main --cpu %*")

README = """SAM Mask Studio {version} (portable)
=====================================

실행: "SAM Mask Studio.bat" 더블클릭
      (이미지 폴더를 끌어다 놓아도 됩니다: bat 파일 위에 폴더를 드롭)
      "SAM Mask Studio (CPU).bat": SAM을 CPU로 (학습 중 GPU를 비워 둠, 클릭 · 전파는 느림, 브러시는 같음)

요구 사항
- Windows 10 / 11 (64비트)
- GPU로 실행: NVIDIA 그래픽카드 + CUDA 13을 지원하는 최신 드라이버 (PyTorch {torch})
  GPU가 없거나 드라이버가 오래되면 SAM2(클릭, 전파)와 Sky는 CPU로 느리게 실행되고,
  SAM3 글자 검출(Detect / Batch)은 쓸 수 없습니다 (+ New Object로 대신)
- VRAM 8GB 정도 권장

폴더 구성
- python\\            파이썬과 모든 패키지 (설치 불필요)
- app\\               프로그램, app\\checkpoints\\ (SAM2 tiny, SAM3, Sky 모델)
- app\\docs\\manual\\  사용 설명서 (README.md부터)
- app\\config.local.json   이 PC의 설정 (처음 실행 때 생성)

작업 프로젝트(이미지 폴더 옆 <폴더명>.sms)는 설치판과 호환됩니다.
SAM3 모델(facebook/sam3)은 Hugging Face 승인 모델입니다. 개인 PC 간 사용 용도로만 옮기세요.
"""


def log(msg: str) -> None:
    print(msg, flush=True)


def copy_tree(src: Path, dst: Path, skip=frozenset()) -> None:
    shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns(*skip) if skip else None)


def link_or_copy(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
        return "linked"
    except OSError:
        shutil.copy2(src, dst)
        return "copied"


def zip_folder(folder: Path, dest: Path, level: int = 1, files=None) -> int:
    """``folder`` into ``dest`` under the folder's own name; weights / compressed files stored, the rest deflated.
    *files*: only these (default every file). Written to ``<dest>.part`` first, so a stopped run never leaves a zip
    that looks finished. Returns the file count."""
    part = dest.with_name(dest.name + ".part")
    files = sorted(p for p in folder.rglob("*") if p.is_file()) if files is None else sorted(files)
    total = sum(p.stat().st_size for p in files) or 1
    done, step, t0 = 0, total // 10, time.time()
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True) as z:
        for p in files:
            arc = (Path(folder.name) / p.relative_to(folder)).as_posix()
            if p.suffix.lower() in STORE_SUFFIXES:
                z.write(p, arc, compress_type=zipfile.ZIP_STORED)
            else:
                z.write(p, arc)
            before, done = done, done + p.stat().st_size
            if step and before // step != done // step:
                log(f"    zip {100 * done // total}% ({time.time() - t0:.0f}s)")
    part.replace(dest)
    return len(files)


PART_NAMES = ("app", "runtime", "models")


def part_of(rel: Path) -> str:
    """Which --split part a path inside the portable folder belongs to."""
    if rel.parts[0] == "python":
        return "runtime"
    if rel.parts[:2] == ("app", "checkpoints"):
        return "models"
    return "app"


def files_hash(folder: Path, files) -> str:
    """12 hex digits from the files' paths and sizes: the same files, the same name (contents are not read)."""
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(f"{p.relative_to(folder).as_posix()}\t{p.stat().st_size}\n".encode("utf-8"))
    return h.hexdigest()[:12]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def split_zip(folder: Path, version: str, dest_dir: Path, contract: int, log=log) -> dict:
    """The portable *folder* as three zips in *dest_dir* (see the module notes). Returns the manifest, also written
    as ``sms-<version>-parts.json``; a runtime / models zip already there under its name is kept, not rewritten."""
    groups = {k: [] for k in PART_NAMES}
    for p in folder.rglob("*"):
        if p.is_file() and p.name != "PARTS.json":
            groups[part_of(p.relative_to(folder))].append(p)
    names = {"app": f"sms-{version}-app"}
    for k in ("runtime", "models"):
        names[k] = f"sms-{k}-{files_hash(folder, groups[k])}" if groups[k] else None
    need = {"version": version, "cli_contract": contract, "runtime": names["runtime"], "models": names["models"]}
    (folder / "PARTS.json").write_text(json.dumps(need, indent=1) + "\n", encoding="utf-8")
    groups["app"].append(folder / "PARTS.json")
    dest_dir.mkdir(parents=True, exist_ok=True)
    manifest = {**need, "parts": {}}
    for k in PART_NAMES:
        if not names[k]:
            log(f"    {k}: nothing in it, no zip")
            continue
        dest = dest_dir / f"{names[k]}.zip"
        if k != "app" and dest.is_file():
            log(f"    {k}: {dest.name} already there, kept")
        else:
            t0 = time.time()
            n = zip_folder(folder, dest, files=groups[k])
            log(f"    {k}: {dest.name}, {n} files, {dest.stat().st_size / 1e9:.2f} GB in {time.time() - t0:.0f}s")
        manifest["parts"][k] = {"file": dest.name, "bytes": dest.stat().st_size, "sha256": sha256_file(dest),
                                "files": len(groups[k])}
    (dest_dir / f"sms-{version}-parts.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", type=Path)
    ap.add_argument("--force", action="store_true", help="replace an existing output folder")
    ap.add_argument("--ref", default="HEAD", help="the git commit or tag to package (default HEAD)")
    ap.add_argument("--zip", action="store_true", help="also write <out>-<version>-portable.zip next to the folder")
    ap.add_argument("--split", action="store_true",
                    help="also write it as three zips next to the folder: app, runtime (python), models (checkpoints)")
    args = ap.parse_args()
    out: Path = args.out
    if out.exists():
        if not args.force:
            log(f"{out} exists — pass --force to replace it")
            return 1
        shutil.rmtree(out)

    version = subprocess.run(
        ["git", "-C", str(REPO), "describe", "--tags", "--always", "--match", "v[0-9]*.[0-9]*.[0-9]*", args.ref], capture_output=True, text=True, check=True
    ).stdout.strip()

    log("1/6 Python")
    copy_tree(PY_HOME, out / "python", {"__pycache__"})

    log("2/6 packages (.venv site-packages)")
    site = out / "python" / "Lib" / "site-packages"
    for item in SITE.iterdir():
        if item.name in SKIP_SITE or item.name.startswith("__editable__"):
            continue
        if item.is_dir():
            copy_tree(item, site / item.name, {"__pycache__"})
        else:
            shutil.copy2(item, site / item.name)

    log("3/6 SAM2 / SAM3 sources (editable installs in .venv)")
    for src, name in (
        (REPO / "vendor" / "sam2" / "sam2", "sam2"),
        (REPO / "vendor" / "sam2" / "training", "training"),
        (REPO / "vendor" / "sam3" / "sam3", "sam3"),
    ):
        copy_tree(src, site / name, {"__pycache__"})

    log("4/6 Visual C++ runtime")
    system32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"
    for dll in VC_DLLS:
        if (system32 / dll).is_file() and not (out / "python" / dll).exists():
            shutil.copy2(system32 / dll, out / "python" / dll)

    log(f"5/6 app (git {args.ref})")
    app = out / "app"
    app.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        tar = Path(tmp) / "app.tar"
        paths = [p for p in ("src", "docs", "pyproject.toml", "README.md") if (REPO / p).exists()]
        subprocess.run(["git", "-C", str(REPO), "archive", "-o", str(tar), args.ref, *paths], check=True)
        with tarfile.open(tar) as t:
            t.extractall(app, filter="data")
    (app / "VERSION").write_text(version + "\n", encoding="utf-8")

    log("6/6 checkpoints, launcher, README")
    for rel in ("sam2/sam2.1_hiera_tiny.pt", "sam3/sam3.pt", "sky/skyseg.onnx"):
        if not (REPO / "checkpoints" / rel).is_file():
            log(f"    {rel}: missing, skipped")
            continue
        how = link_or_copy(REPO / "checkpoints" / rel, app / "checkpoints" / rel)
        log(f"    {rel}: {how}")
    (out / "SAM Mask Studio.bat").write_text(LAUNCHER.replace("\n", "\r\n"), encoding="ascii")
    (out / "SAM Mask Studio (CPU).bat").write_text(LAUNCHER_CPU.replace("\n", "\r\n"), encoding="ascii")
    torch_version = next((p.name.split("-")[1] for p in SITE.glob("torch-*.dist-info")), "?")
    (out / "README.txt").write_text(
        README.format(version=version, torch=torch_version).replace("\n", "\r\n"), encoding="utf-8-sig"
    )
    log(f"done: {out} ({version})")
    if args.zip:
        dest = out.with_name(f"{out.name}-{version}-portable.zip")
        log(f"zip: {dest}")
        t0 = time.time()
        n = zip_folder(out, dest)
        log(f"zip done: {n} files, {dest.stat().st_size / 1e9:.2f} GB in {time.time() - t0:.0f}s")
    if args.split:
        sys.path.insert(0, str(app))
        import src.version  # the packaged ref's number, not this checkout's

        log(f"split: {out.parent}")
        split_zip(out, version, out.parent, getattr(src.version, "CLI_CONTRACT", None))
        sys.path.remove(str(app))
    return 0


if __name__ == "__main__":
    sys.exit(main())
