"""The running version, for the window title, Help > About and the log.

- A portable build: its ``VERSION`` file (written by ``tools/make_portable.py``, e.g. ``v0.5.1``).
- A git checkout: ``git describe`` against release tags (``v0.5.1`` on the tag; ``v0.5.1-3-g1a2b3c4`` three commits
  after it, the dev build).
- Otherwise ``pyproject.toml``'s version.
"""

from __future__ import annotations

import functools
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@functools.lru_cache(maxsize=1)
def app_version() -> str:
    file = ROOT / "VERSION"
    if file.is_file():
        text = file.read_text(encoding="utf-8").strip()
        if text:
            return text
    if (ROOT / ".git").exists():
        try:
            out = subprocess.run(
                ["git", "-C", str(ROOT), "describe", "--tags", "--match", "v[0-9]*.[0-9]*.[0-9]*"],
                capture_output=True, text=True, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        with open(ROOT / "pyproject.toml", "rb") as f:
            return "v" + tomllib.load(f)["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        return "unknown"
