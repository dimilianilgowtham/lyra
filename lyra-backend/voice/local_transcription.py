"""Optional CPU speech recognition from an explicitly installed local model.

Constructing this object does not import a speech engine or download anything.
Only scripts/setup_local_voice.py installs model data. Recording requests open
that cached directory with local_files_only=True.
"""
import asyncio
import importlib.util
import io
import os
from pathlib import Path
import threading


class LocalTranscriptionError(Exception):
    pass


class LocalTranscriber:
    def __init__(self, *, model_dir=None, model_name=None, model_factory=None):
        self.model_name = model_name or os.getenv("LOCAL_STT_MODEL", "tiny")
        data_dir = Path(os.getenv("LYRA_DATA_DIR") or Path(__file__).resolve().parent.parent / "data").expanduser()
        default_dir = data_dir / "models" / f"faster-whisper-{self.model_name}"
        self.model_dir = Path(model_dir or os.getenv("LOCAL_STT_MODEL_DIR", str(default_dir))).expanduser()
        self._model_factory = model_factory
        self._model = None
        self._lock = threading.Lock()

    def available(self):
        # faster-whisper otherwise attempts an online tokenizer fallback even
        # with local_files_only=True. Require every runtime asset up front.
        complete = all((self.model_dir / name).is_file() for name in
                       ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"))
        return complete and (
            self._model_factory is not None or importlib.util.find_spec("faster_whisper") is not None)

    def status(self):
        return {"available": self.available(), "model": self.model_name, "network_required": False,
                "setup": "lyra-backend/.venv/bin/python scripts/setup_local_voice.py"}

    def _transcribe(self, audio, language):
        if not self.available():
            raise LocalTranscriptionError("Local speech recognition is not installed. Run lyra-backend/.venv/bin/python scripts/setup_local_voice.py once.")
        with self._lock:
            if self._model is None:
                factory = self._model_factory
                if factory is None:
                    from faster_whisper import WhisperModel
                    factory = WhisperModel
                self._model = factory(str(self.model_dir), device="cpu", compute_type="int8", cpu_threads=4,
                                      local_files_only=True)
            segments, info = self._model.transcribe(
                io.BytesIO(audio), language=language, beam_size=3, vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300}, condition_on_previous_text=False,
            )
            text = " ".join(segment.text.strip() for segment in segments).strip()
            return {"text": text, "language": getattr(info, "language", None) or language or "auto",
                    "provider": "local", "model": f"faster-whisper-{self.model_name}"}

    async def transcribe(self, audio, language=None):
        # Model inference and codec decoding cannot block FastAPI's event loop.
        return await asyncio.to_thread(self._transcribe, audio, language)
