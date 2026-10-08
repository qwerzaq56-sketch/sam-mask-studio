"""tools/make_portable.py --split: app / runtime / models parts that unzip back into the portable (p119)."""

import importlib.util
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _tool():
    spec = importlib.util.spec_from_file_location("make_portable", ROOT / "tools" / "make_portable.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _portable(root: Path) -> Path:
    out = root / "SAMMaskStudio"
    for rel, data in {
        "SAM Mask Studio.bat": b"@echo off",
        "README.txt": b"readme",
        "python/python.exe": b"exe" * 10,
        "python/Lib/site-packages/torch/__init__.py": b"torch",
        "app/src/main.py": b"print()",
        "app/VERSION": b"v9\n",
        "app/checkpoints/sam2/sam2.1_hiera_tiny.pt": b"w" * 100,
        "app/checkpoints/sky/skyseg.onnx": b"s" * 50,
    }.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(data)
    return out


def _names(z: Path):
    with zipfile.ZipFile(z) as f:
        return sorted(f.namelist())


def test_split_parts_unzip_into_the_portable_and_keep_their_names(tmp_path):
    m = _tool()
    out = _portable(tmp_path)
    before = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    dest = tmp_path / "rel"
    lines = []
    man = m.split_zip(out, "v9", dest, 1, log=lines.append)
    parts = man["parts"]
    assert parts["app"]["file"] == "sms-v9-app.zip" and man["cli_contract"] == 1
    assert parts["runtime"]["file"] == man["runtime"] + ".zip" and man["runtime"].startswith("sms-runtime-")
    assert parts["models"]["file"] == man["models"] + ".zip" and man["models"].startswith("sms-models-")
    # each file in exactly one part, all rooted at the folder's name; PARTS.json in the app part
    every = [n for k in ("app", "runtime", "models") for n in _names(dest / parts[k]["file"])]
    assert sorted(every) == sorted(f"SAMMaskStudio/{r}" for r in before + ["PARTS.json"])
    assert all(n.startswith("SAMMaskStudio/python/") for n in _names(dest / parts["runtime"]["file"]))
    assert all(n.startswith("SAMMaskStudio/app/checkpoints/") for n in _names(dest / parts["models"]["file"]))
    need = json.loads((out / "PARTS.json").read_text(encoding="utf-8"))
    assert need == {"version": "v9", "cli_contract": 1, "runtime": man["runtime"], "models": man["models"]}
    assert json.loads((dest / "sms-v9-parts.json").read_text(encoding="utf-8")) == man
    # three unzipped into one folder: the portable again
    back = tmp_path / "back"
    for k in ("app", "runtime", "models"):
        with zipfile.ZipFile(dest / parts[k]["file"]) as f:
            f.extractall(back)
    for r in before:
        assert (back / "SAMMaskStudio" / r).read_bytes() == (out / r).read_bytes()
    # a new app version with the same runtime / models: same names, those zips kept, not written again
    (out / "app" / "src" / "main.py").write_bytes(b"print('new')")
    stamp = (dest / parts["runtime"]["file"]).stat().st_mtime_ns
    man2 = m.split_zip(out, "v10", dest, 1, log=lines.append)
    assert (man2["runtime"], man2["models"]) == (man["runtime"], man["models"])
    assert (dest / parts["runtime"]["file"]).stat().st_mtime_ns == stamp and any("kept" in s for s in lines)
    # a changed weight file: a new models name
    (out / "app" / "checkpoints" / "sky" / "skyseg.onnx").write_bytes(b"s" * 51)
    assert m.split_zip(out, "v11", dest, 1, log=lines.append)["models"] != man["models"]
