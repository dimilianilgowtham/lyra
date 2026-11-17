"""Explicitly install Lyra's offline model; ordinary microphone use never downloads.

Run with the backend interpreter. Pass --install to also install the optional
Python package, or install requirements-voice.txt first. Tiny is multilingual;
--model base provides a larger model when more accuracy is needed.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=os.getenv("LOCAL_STT_MODEL", "tiny"), choices=("tiny", "tiny.en", "base", "base.en", "small", "small.en"))
    parser.add_argument("--install", action="store_true", help="Install the optional voice package in this interpreter.")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    if args.install:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(root / "requirements-voice.txt")], check=True)
    if importlib.util.find_spec("faster_whisper") is None:
        parser.exit(1, "Install requirements-voice.txt first, or run this script with --install.\n")
    from huggingface_hub import snapshot_download
    from faster_whisper import WhisperModel
    destination = Path(os.getenv("LOCAL_STT_MODEL_DIR", str(root / "lyra-backend" / "data" / "models" / f"faster-whisper-{args.model}"))).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    print(f"Downloading multilingual speech model {args.model} to {destination}", flush=True)
    snapshot_download(repo_id=f"Systran/faster-whisper-{args.model}", local_dir=str(destination), token=False,
                      allow_patterns=["config.json", "preprocessor_config.json", "model.bin", "tokenizer.json", "vocabulary.*"])
    # Confirm the files load with networking disabled before reporting success.
    WhisperModel(str(destination), device="cpu", compute_type="int8", cpu_threads=4, local_files_only=True)
    print(f"Local voice model is installed and loads offline: {destination}", flush=True)


if __name__ == "__main__":
    main()
