"""The running version (src/version.py) and make_portable's --zip (tools/make_portable.py)."""

import importlib.util
import zipfile
from pathlib import Path

import src.version as version

REPO = Path(__file__).resolve().parents[2]


def _make_portable():
    spec = importlib.util.spec_from_file_location("make_portable", REPO / "tools" / "make_portable.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_file_wins(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("v9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(version, "ROOT", tmp_path)
    version.app_version.cache_clear()
    try:
        assert version.app_version() == "v9.9.9"
    finally:
        version.app_version.cache_clear()


def test_version_falls_back_to_pyproject(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setattr(version, "ROOT", tmp_path)
    version.app_version.cache_clear()
    try:
        assert version.app_version() == "v1.2.3"
    finally:
        version.app_version.cache_clear()


def test_version_of_this_checkout_is_a_release_tag():
    version.app_version.cache_clear()
    v = version.app_version()
    assert v.startswith("v") and "-p" not in v.split("-g")[0]  # v0.5.1 or v0.5.1-N-g<hash>, never a stage tag


def test_zip_folder_stores_weights_and_deflates_the_rest(tmp_path):
    mp = _make_portable()
    folder = tmp_path / "SAMMaskStudio"
    (folder / "app" / "checkpoints").mkdir(parents=True)
    (folder / "app" / "checkpoints" / "m.pt").write_bytes(b"w" * 5000)
    (folder / "app" / "a.py").write_bytes(b"print('hi')\n" * 500)
    (folder / "SAM Mask Studio.bat").write_text("@echo off\r\n", encoding="ascii")
    dest = tmp_path / "SAMMaskStudio-v1-portable.zip"
    assert mp.zip_folder(folder, dest) == 3
    assert dest.is_file() and not (tmp_path / (dest.name + ".part")).exists()
    with zipfile.ZipFile(dest) as z:
        info = {i.filename: i for i in z.infolist()}
        assert set(info) == {"SAMMaskStudio/app/checkpoints/m.pt", "SAMMaskStudio/app/a.py", "SAMMaskStudio/SAM Mask Studio.bat"}
        assert info["SAMMaskStudio/app/checkpoints/m.pt"].compress_type == zipfile.ZIP_STORED
        assert info["SAMMaskStudio/app/a.py"].compress_type == zipfile.ZIP_DEFLATED
        assert z.read("SAMMaskStudio/app/a.py") == b"print('hi')\n" * 500
        assert z.testzip() is None
