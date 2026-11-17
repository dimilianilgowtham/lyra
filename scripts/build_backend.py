#!/usr/bin/env python3
"""Build the installed app's backend using the project's Python environment.

Run with lyra-backend/.venv/bin/python scripts/build_backend.py. Install the
build-only dependency PyInstaller in that environment before the first build.
The voice model is copied separately by the Electron packaging step.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="Discard cached Python analysis")
    args = parser.parse_args()
    if importlib.util.find_spec("PyInstaller") is None:
        parser.error("PyInstaller is missing. Install packaging/requirements-build.txt in lyra-backend/.venv first.")
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(ROOT / "build" / "backend"),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
    ]
    if args.clean:
        command.append("--clean")
    command.append(str(ROOT / "packaging" / "lyra-backend.spec"))
    environment = os.environ.copy()
    environment.setdefault("PYINSTALLER_CONFIG_DIR", str(ROOT / "build" / "pyinstaller-cache"))
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    artifact = ROOT / "build" / "backend" / "lyra-backend"
    # Guard against accidentally collecting source user-data in a future hook.
    forbidden = {".env", ".backend-auth-token", "lyra.db", "session_memory.json"}
    leaked = [str(path.relative_to(artifact)) for path in artifact.rglob("*")
              if path.is_file() and (path.name in forbidden or path.name.startswith(".env."))]
    if leaked:
        raise RuntimeError("Private application files were collected: " + ", ".join(leaked))
    executable = artifact / "lyra-backend"
    if not executable.is_file():
        raise RuntimeError("Backend build did not produce its executable")
    print(f"Backend ready: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
