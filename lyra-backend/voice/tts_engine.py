"""
LYRA — TTS Engine (macOS Native)
Uses macOS `say` command for zero-latency, human-like text-to-speech.
Generates audio files and streams them to the frontend.
"""

import asyncio
import base64
import logging
import os
import tempfile
import subprocess
from pathlib import Path

from config import settings

logger = logging.getLogger("LYRA.Voice.TTS")

# Best macOS female voices ranked by naturalness
MACOS_VOICES = {
    "samantha": "Samantha",      # Female, US English — most natural, iconic Her/AI
    "karen": "Karen",            # Female, Australian English — crisp, FRIDAY-style
    "ava": "Ava",                # Female, US English — Apple premium
    "zoe": "Zoe",                # Female, US English — Apple premium
    "serena": "Serena",          # Female, UK English — Apple premium
    "moira": "Moira",            # Female, Irish English — warm, melodic
    "tessa": "Tessa",            # Female, South African English
    "fiona": "Fiona",            # Female, Scottish English
}


class TTSEngine:
    """macOS native TTS using the `say` command."""

    def __init__(self):
        self.voice = settings.TTS_VOICE
        self.rate = settings.TTS_RATE
        self.temp_dir = os.path.join(tempfile.gettempdir(), "lyra_tts")
        os.makedirs(self.temp_dir, exist_ok=True)
        self._check_available_voices()

    def _check_available_voices(self):
        """Check which premium voices are installed on this Mac."""
        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True, text=True, timeout=5
            )
            available = result.stdout.lower()
            # Find best available voice
            for key, name in MACOS_VOICES.items():
                if name.lower() in available:
                    if not self.voice or self.voice.lower() not in available:
                        self.voice = name
                    logger.info(f"✅ Voice available: {name}")
                    break
            logger.info(f"🎤 Using TTS voice: {self.voice}")
        except Exception as e:
            logger.warning(f"Voice check failed: {e}, using default")
            self.voice = "Samantha"

    async def speak(self, text: str, rate: int = None) -> dict:
        """
        Convert text to speech, return audio as base64.
        Uses macOS `say` → WAV → base64 for browser playback.
        """
        if not text or not text.strip():
            return {"error": "Empty text"}

        # Clean text for TTS (remove emojis, markdown, etc.)
        clean = self._clean_for_speech(text)
        effective_rate = rate or self.rate

        # Generate WAV audio file (browsers can decode WAV, not AIFF)
        filename = f"lyra_{hash(clean) & 0xFFFFFFFF}.wav"
        filepath = os.path.join(self.temp_dir, filename)

        try:
            # Use --file-format=WAVE and --data-format=LEI16@22050 for browser-compatible WAV
            process = await asyncio.create_subprocess_exec(
                "say", "-v", self.voice, "-r", str(effective_rate),
                "-o", filepath,
                "--file-format=WAVE",
                "--data-format=LEI16@22050",
                clean,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=15.0)

            if not os.path.exists(filepath):
                return {"error": "TTS generation failed"}

            # Read and encode audio
            with open(filepath, "rb") as f:
                audio_data = f.read()

            audio_b64 = base64.b64encode(audio_data).decode("utf-8")

            # Cleanup
            try:
                os.remove(filepath)
            except OSError:
                pass

            return {
                "audio": audio_b64,
                "format": "wav",
                "voice": self.voice,
                "text": text,
                "size": len(audio_data),
            }
        except asyncio.TimeoutError:
            logger.error("TTS timed out")
            return {"error": "TTS timed out"}
        except Exception as e:
            logger.error(f"TTS error: {e}")
            return {"error": str(e)}

    async def speak_direct(self, text: str, voice: str = None, rate: int = None):
        """Speak text directly through Mac speakers (no file, instant)."""
        clean = self._clean_for_speech(text)
        v = voice or self.voice
        r = rate or self.rate
        process = await asyncio.create_subprocess_exec(
            "say", "-v", v, "-r", str(r), clean,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()

    def stop(self):
        """Halt any ongoing macOS say speech immediately."""
        try:
            subprocess.run(["killall", "say"], capture_output=True, timeout=2)
        except Exception:
            pass


    def set_voice(self, voice: str):
        """Change TTS voice."""
        if voice in MACOS_VOICES:
            self.voice = MACOS_VOICES[voice]
        else:
            self.voice = voice
        logger.info(f"Voice changed to: {self.voice}")

    def set_rate(self, rate: int):
        """Change speaking rate (words per minute)."""
        self.rate = max(100, min(300, rate))

    def _clean_for_speech(self, text: str) -> str:
        """Remove characters that don't work well with TTS."""
        import re
        # Remove emojis
        text = re.sub(r'[^\w\s.,!?;:\'-/()@#$%&*+=<>"]', '', text)
        # Remove markdown
        text = re.sub(r'[*_`#\[\]()]', '', text)
        # Remove multiple spaces
        text = re.sub(r'\s+', ' ', text).strip()
        # Limit length for speech
        if len(text) > 500:
            text = text[:500] + "..."
        return text

    def get_available_voices(self) -> list:
        """Return list of available macOS voices."""
        try:
            result = subprocess.run(
                ["say", "-v", "?"],
                capture_output=True, text=True, timeout=5
            )
            voices = []
            for line in result.stdout.strip().split("\n"):
                parts = line.split()
                if parts:
                    voices.append(parts[0])
            return voices
        except Exception:
            return list(MACOS_VOICES.values())
