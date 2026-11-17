"""Speech uploads fail clearly and use the actual configured audio providers."""
import base64
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import httpx

from fastapi.testclient import TestClient

import main
from config import settings
from voice.transcription import TranscriptionError, TranscriptionService
from voice.local_transcription import LocalTranscriber


def audio_payload():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0\0" * 160)
    return base64.b64encode(output.getvalue()).decode()


def config(**overrides):
    return SimpleNamespace(GROQ_API_KEY=overrides.pop("GROQ_API_KEY", "groq-test-secret"),
                           OPENAI_API_KEY=overrides.pop("OPENAI_API_KEY", ""),
                           GEMINI_API_KEY=overrides.pop("GEMINI_API_KEY", ""),
                           STT_PROVIDER=overrides.pop("STT_PROVIDER", "auto"),
                           LOCAL_STT_MODEL_DIR="/nonexistent/lyra-stt-test-cache", **overrides)


class TranscriptionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_cached_model_is_used_before_cloud_and_never_downloads_on_recording(self):
        with tempfile.TemporaryDirectory() as directory:
            model_dir = Path(directory)
            for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
                (model_dir / name).write_bytes(b"cached-test-model")
            calls = []
            class Model:
                def transcribe(self, audio, **kwargs):
                    self_audio = audio.read()
                    calls.append((self_audio, kwargs))
                    return iter([SimpleNamespace(text=" Current directory please.")]), SimpleNamespace(language="en")
            def load(path, **kwargs):
                self.assertEqual(path, str(model_dir))
                self.assertTrue(kwargs["local_files_only"])
                self.assertEqual(kwargs["device"], "cpu")
                return Model()
            local = LocalTranscriber(model_dir=model_dir, model_factory=load)
            def unexpected(request):
                self.fail("Available local transcription unnecessarily sent audio to cloud")
            service = TranscriptionService(config(), local=local, transport=httpx.MockTransport(unexpected))
            result = await service.transcribe(audio_payload(), "wav", "en")
            self.assertEqual(result["provider"], "local")
            self.assertEqual(result["text"], "Current directory please.")
            self.assertTrue(calls[0][0].startswith(b"RIFF"))
            self.assertTrue(calls[0][1]["vad_filter"])

    async def test_partial_local_cache_is_not_loaded_or_allowed_to_fetch_a_tokenizer(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "model.bin").write_bytes(b"incomplete cache")
            local = LocalTranscriber(model_dir=directory, model_factory=lambda *a, **k: self.fail("Incomplete model was loaded"))
            self.assertFalse(local.available())

    async def test_explicit_missing_local_model_reports_setup_without_cloud_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            local = LocalTranscriber(model_dir=directory)
            service = TranscriptionService(config(STT_PROVIDER="local"), local=local)
            with self.assertRaises(TranscriptionError) as result:
                await service.transcribe(audio_payload(), "wav")
            self.assertEqual(result.exception.code, "local_stt_unavailable")
            self.assertIn("setup_local_voice.py", str(result.exception))

    async def test_gemini_fallback_uses_configured_model_without_key_in_url(self):
        def respond(request):
            self.assertNotIn("key=", str(request.url))
            self.assertEqual(request.headers["x-goog-api-key"], "gemini-test-secret")
            self.assertIn("gemini-3.8-flash:generateContent", str(request.url))
            data = json.loads(request.content)
            self.assertEqual(data["contents"][0]["parts"][0]["inline_data"]["mime_type"], "audio/wav")
            return httpx.Response(200, json={"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "Check the directory."}]}}]})
        service = TranscriptionService(config(GROQ_API_KEY="", GEMINI_API_KEY="gemini-test-secret"), transport=httpx.MockTransport(respond))
        self.assertEqual((await service.transcribe(audio_payload(), "wav"))["provider"], "gemini")

    async def test_multipart_upload_has_audio_correct_mime_language_and_configured_model(self):
        def respond(request):
            self.assertEqual(request.url, "https://api.groq.com/openai/v1/audio/transcriptions")
            self.assertEqual(request.headers["authorization"], "Bearer groq-test-secret")
            self.assertIn("multipart/form-data", request.headers["content-type"])
            body = request.content
            self.assertIn(b'filename="recording.wav"', body)
            self.assertIn(b"Content-Type: audio/wav", body)
            self.assertIn(b"whisper-large-v3", body)
            self.assertIn(b'"language"\r\n\r\nen', body)
            self.assertIn(b"RIFF", body)
            return httpx.Response(200, json={"text": "  Check my working directory.  "})
        service = TranscriptionService(config(GROQ_STT_MODEL="whisper-large-v3"), transport=httpx.MockTransport(respond))
        result = await service.transcribe(audio_payload(), "audio/wav", "en-US")
        self.assertEqual(result, {"text": "Check my working directory.", "language": "en", "provider": "groq", "model": "whisper-large-v3"})

    async def test_authorization_failure_falls_back_and_does_not_disable_next_request(self):
        providers = []
        def respond(request):
            providers.append(request.url.host)
            if request.url.host == "api.groq.com":
                return httpx.Response(401, json={"error": {"message": "invalid groq-test-secret"}})
            self.assertIn(b"gpt-4o-mini-transcribe", request.content)
            return httpx.Response(200, json={"text": "Show the current directory."})
        service = TranscriptionService(config(OPENAI_API_KEY="openai-test-secret"), transport=httpx.MockTransport(respond))
        for _ in range(2):
            self.assertEqual((await service.transcribe(audio_payload(), "wav"))["provider"], "openai")
        self.assertEqual(providers, ["api.groq.com", "api.openai.com"] * 2)

    async def test_empty_transcript_is_no_speech_and_does_not_ask_another_model_to_guess(self):
        calls = []
        def respond(request):
            calls.append(request)
            return httpx.Response(200, json={"text": "  "})
        service = TranscriptionService(config(OPENAI_API_KEY="other"), transport=httpx.MockTransport(respond))
        with self.assertRaises(TranscriptionError) as result:
            await service.transcribe(audio_payload(), "wav")
        self.assertEqual(result.exception.code, "no_speech")
        self.assertEqual(result.exception.status_code, 422)
        self.assertEqual(len(calls), 1)

    async def test_no_configured_provider_reports_configuration_instead_of_microphone_blame(self):
        service = TranscriptionService(config(GROQ_API_KEY=""))
        with self.assertRaises(TranscriptionError) as result:
            await service.transcribe(audio_payload(), "wav")
        self.assertEqual(result.exception.code, "stt_unconfigured")
        self.assertEqual(result.exception.status_code, 503)

    async def test_all_provider_errors_are_actionable_and_do_not_echo_secrets(self):
        service = TranscriptionService(config(), transport=httpx.MockTransport(lambda _: httpx.Response(401, text="invalid groq-test-secret")))
        with self.assertRaises(TranscriptionError) as result:
            await service.transcribe(audio_payload(), "wav")
        detail = result.exception.as_dict()
        self.assertEqual(detail["providers"][0]["code"], "authentication_failed")
        self.assertIn("Groq", detail["error"])
        self.assertNotIn("groq-test-secret", json.dumps(detail))

    async def test_validation_blocks_oversized_unsupported_or_non_audio_content(self):
        def unexpected(request):
            self.fail("Invalid audio reached a provider")
        service = TranscriptionService(config(), max_audio_bytes=400, transport=httpx.MockTransport(unexpected))
        for payload, audio_format, language, code in [
            ("%%", "wav", "en", "invalid_audio"),
            (audio_payload(), "exe", "en", "unsupported_format"),
            (base64.b64encode(b"not an audio container" * 2).decode(), "wav", "en", "invalid_audio"),
            (base64.b64encode(b"x" * 401).decode(), "wav", "en", "audio_too_large"),
            (audio_payload(), "wav", "english", "invalid_language"),
        ]:
            with self.subTest(code=code):
                with self.assertRaises(TranscriptionError) as result:
                    await service.transcribe(payload, audio_format, language)
                self.assertEqual(result.exception.code, code)

    async def test_webm_codec_mime_and_auto_language_are_supported(self):
        def respond(request):
            self.assertIn(b'filename="recording.webm"', request.content)
            self.assertIn(b"Content-Type: audio/webm", request.content)
            self.assertNotIn(b'name="language"', request.content)
            return httpx.Response(200, json={"text": "hello"})
        service = TranscriptionService(config(), transport=httpx.MockTransport(respond))
        payload = base64.b64encode(b"\x1a\x45\xdf\xa3" + b"\x00" * 80).decode()
        self.assertEqual((await service.transcribe(payload, "audio/webm;codecs=opus", "auto"))["text"], "hello")

    async def test_invalid_provider_json_falls_back_to_next_provider(self):
        def respond(request):
            if request.url.host == "api.groq.com":
                return httpx.Response(200, text="not json")
            return httpx.Response(200, json={"text": "Recovered transcript"})
        service = TranscriptionService(config(OPENAI_API_KEY="other"), transport=httpx.MockTransport(respond))
        self.assertEqual((await service.transcribe(audio_payload(), "wav"))["provider"], "openai")

    async def test_timeout_falls_back_without_leaking_request_headers(self):
        def respond(request):
            if request.url.host == "api.groq.com":
                raise httpx.ReadTimeout("private provider detail", request=request)
            return httpx.Response(200, json={"text": "Recognized after fallback"})
        service = TranscriptionService(config(OPENAI_API_KEY="other"), transport=httpx.MockTransport(respond))
        self.assertEqual((await service.transcribe(audio_payload(), "wav"))["text"], "Recognized after fallback")

    async def test_truncated_gemini_response_is_not_returned_as_completed_transcript(self):
        response = {"candidates": [{"finishReason": "MAX_TOKENS", "content": {"parts": [{"text": "Truncated"}]}}]}
        service = TranscriptionService(config(GROQ_API_KEY="", GEMINI_API_KEY="gemini-secret"), transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
        with self.assertRaises(TranscriptionError) as result:
            await service.transcribe(audio_payload(), "wav")
        self.assertEqual(result.exception.providers[0]["code"], "invalid_response")


class TranscriptionAPITests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app, headers={
            "Authorization": f"Bearer {settings.BACKEND_AUTH_TOKEN}",
        })

    def test_invalid_base64_is_rejected_before_any_provider_request(self):
        with patch.object(settings, "GROQ_API_KEY", ""), patch.object(settings, "GEMINI_API_KEY", ""):
            result = self.client.post("/api/stt", json={"audio": "%%not-base64%%", "format": "webm"})
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(result.json()["code"], "invalid_audio")

    def test_unsupported_format_is_rejected_before_any_provider_request(self):
        with patch.object(settings, "GROQ_API_KEY", ""), patch.object(settings, "GEMINI_API_KEY", ""):
            result = self.client.post("/api/stt", json={"audio": "aGVsbG8=", "format": "exe"})
        self.assertEqual(result.status_code, 400, result.text)
        self.assertEqual(result.json()["code"], "unsupported_format")


if __name__ == "__main__":
    unittest.main()
