# -*- mode: python ; coding: utf-8 -*-
"""CPU-only macOS backend with the codecs and VAD used by local voice.

The recognition model is an Electron extra resource, not user data. No project
directory is collected wholesale: credentials, conversations, and tokens must
never become part of a distributable application.
"""
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    copy_metadata,
)

project = Path(SPECPATH).resolve().parent
backend = project / "lyra-backend"

hiddenimports = [
    "ctranslate2._ext",
    "ctranslate2.models",
    "tokenizers",
    "huggingface_hub._snapshot_download",
    "huggingface_hub.file_download",
]
for package in ("uvicorn", "faster_whisper", "av", "onnxruntime"):
    hiddenimports += collect_submodules(package)

datas = collect_data_files("faster_whisper") + collect_data_files("certifi")
for distribution in (
    "fastapi", "starlette", "uvicorn", "pydantic", "httpx", "faster-whisper",
    "ctranslate2", "av", "onnxruntime", "tokenizers", "huggingface-hub", "numpy",
):
    datas += copy_metadata(distribution)

binaries = []
for package in ("ctranslate2", "av", "onnxruntime", "tokenizers"):
    binaries += collect_dynamic_libs(package)

analysis = Analysis(
    [str(backend / "main.py")],
    pathex=[str(backend)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # Recognition uses converted CPU weights. Training, GUI, notebook and test
    # packages are unrelated and can otherwise be pulled in by optional imports.
    excludes=[
        "torch", "tensorflow", "transformers", "jax", "pandas", "matplotlib",
        "scipy", "sklearn", "IPython", "pytest", "tkinter",
        "ctranslate2.converters", "ctranslate2.specs",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="lyra-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="lyra-backend",
)
