"""
LYRA Model Adapter Layer
Unified, pluggable abstraction for cloud (Groq, Gemini, OpenAI, NVIDIA, OpenRouter)
and local (Ollama) inference. Guarantees consistent parameter enforcement:
model, temperature, max_tokens, and streaming support.
"""

import abc
import json
import logging
from typing import AsyncGenerator, Optional

import httpx

from config import settings

logger = logging.getLogger("LYRA.ModelAdapter")


class BaseModelAdapter(abc.ABC):
    """Abstract interface for all model providers."""

    name: str = "base"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if this adapter has credentials or local availability."""
        pass

    @abc.abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        """Generate a complete text response."""
        pass

    @abc.abstractmethod
    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        """Stream token-by-token response."""
        pass


class GroqAdapter(BaseModelAdapter):
    """High-speed cloud inference via Groq."""

    name: str = "groq"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    def is_available(self) -> bool:
        return bool(settings.GROQ_API_KEY)

    def _prepare_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        payload = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload.append({"role": m["role"], "content": m["content"]})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=45.0) as client:
            async with client.stream(
                "POST",
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


class GeminiAdapter(BaseModelAdapter):
    """Google Gemini adapter with deep context and tool support."""

    name: str = "gemini"
    DEFAULT_MODEL = "gemini-2.0-flash"

    def is_available(self) -> bool:
        return bool(settings.GEMINI_API_KEY)

    def _prepare_contents(self, messages: list[dict]) -> list[dict]:
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        return contents

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model if model.startswith("gemini") else self.DEFAULT_MODEL
        contents = self._prepare_contents(messages)

        body = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": int(max_tokens),
                "temperature": max(0.0, min(1.0, float(temperature))),
            },
        }
        if system_prompt:
            body["system_instruction"] = {"parts": [{"text": system_prompt}]}

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:generateContent?key={settings.GEMINI_API_KEY}",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            candidate = data.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])
            text_parts = [p.get("text", "") for p in parts if "text" in p]
            return "".join(text_parts).strip()

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model if model.startswith("gemini") else self.DEFAULT_MODEL
        contents = self._prepare_contents(messages)

        body = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": int(max_tokens),
                "temperature": max(0.0, min(1.0, float(temperature))),
            },
        }
        if system_prompt:
            body["system_instruction"] = {"parts": [{"text": system_prompt}]}

        async with httpx.AsyncClient(timeout=45.0) as client:
            async with client.stream(
                "POST",
                f"https://generativelanguage.googleapis.com/v1beta/models/{target_model}:streamGenerateContent?alt=sse&key={settings.GEMINI_API_KEY}",
                json=body,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            chunk = json.loads(line[6:])
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                parts = candidates[0].get("content", {}).get("parts", [])
                                for p in parts:
                                    text = p.get("text", "")
                                    if text:
                                        yield text
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


class LocalOllamaAdapter(BaseModelAdapter):
    """100% offline local inference via Ollama."""

    name: str = "ollama"

    def is_available(self) -> bool:
        # Assumed available when base url is configured
        return bool(settings.OLLAMA_BASE_URL)

    def _prepare_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        payload = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload.append({"role": m["role"], "content": m["content"]})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model or settings.DEFAULT_LOCAL_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "stream": False,
                    "options": {
                        "temperature": float(temperature),
                        "num_predict": int(max_tokens),
                    },
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model or settings.DEFAULT_LOCAL_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                f"{settings.OLLAMA_BASE_URL}/api/chat",
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "stream": True,
                    "options": {
                        "temperature": float(temperature),
                        "num_predict": int(max_tokens),
                    },
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.strip():
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue


class OpenAIAdapter(BaseModelAdapter):
    """Standard cloud inference via OpenAI (GPT-4o, GPT-4o-mini)."""

    name: str = "openai"
    DEFAULT_MODEL = "gpt-4o-mini"

    def is_available(self) -> bool:
        return bool(settings.OPENAI_API_KEY)

    def _prepare_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        payload = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload.append({"role": m["role"], "content": m["content"]})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model if ("gpt" in (model or "")) else self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model if ("gpt" in (model or "")) else self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=45.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue



class NVIDIAAdapter(BaseModelAdapter):
    """High-speed cloud inference via NVIDIA NIM API."""

    name: str = "nvidia"
    DEFAULT_MODEL = "meta/llama-3.2-11b-vision-instruct"

    def is_available(self) -> bool:
        return bool(settings.NVIDIA_API_KEY)

    def _prepare_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        payload = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload.append({"role": m["role"], "content": m["content"]})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model if (model and "/" in model) else self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model if (model and "/" in model) else self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream(
                "POST",
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.NVIDIA_API_KEY}",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue



class AnthropicAdapter(BaseModelAdapter):
    """Frontier inference via Anthropic API (Claude 3.7 Sonnet, Claude 3.5 Sonnet, Claude 3.5 Haiku)."""

    name: str = "anthropic"
    DEFAULT_MODEL = "claude-3-7-sonnet-latest"

    def is_available(self) -> bool:
        return bool(settings.ANTHROPIC_API_KEY)

    def _prepare_messages(self, messages: list[dict]) -> list[dict]:
        payload = []
        for m in messages:
            role = m["role"]
            if role in ("user", "assistant"):
                payload.append({"role": role, "content": m["content"]})
        if payload and payload[0]["role"] != "user":
            payload.insert(0, {"role": "user", "content": "Hello"})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages)
        body = {
            "model": target_model,
            "messages": payload_messages,
            "max_tokens": max(1, int(max_tokens)),
            "temperature": max(0.0, min(1.0, float(temperature))),
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
            return "".join(parts)

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages)
        body = {
            "model": target_model,
            "messages": payload_messages,
            "max_tokens": max(1, int(max_tokens)),
            "temperature": max(0.0, min(1.0, float(temperature))),
            "stream": True,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        raw_chunk = line[6:].strip()
                        if raw_chunk == "[DONE]":
                            break
                        try:
                            chunk = json.loads(raw_chunk)
                            event_type = chunk.get("type")
                            if event_type == "content_block_delta":
                                delta = chunk.get("delta", {})
                                if delta.get("type") == "text_delta":
                                    text = delta.get("text", "")
                                    if text:
                                        yield text
                        except (json.JSONDecodeError, KeyError):
                            continue


class OpenRouterAdapter(BaseModelAdapter):
    """Universal multi-model gateway via OpenRouter (Claude 3.7, DeepSeek-R1, GPT-4o, Qwen 2.5 Coder)."""

    name: str = "openrouter"
    DEFAULT_MODEL = "anthropic/claude-3.7-sonnet"

    def is_available(self) -> bool:
        return bool(settings.OPENROUTER_API_KEY)

    def _prepare_messages(self, messages: list[dict], system_prompt: str) -> list[dict]:
        payload = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        for m in messages:
            payload.append({"role": m["role"], "content": m["content"]})
        return payload

    async def chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://lyra.assistant",
                    "X-Title": "LYRA",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def stream_chat(
        self,
        messages: list[dict],
        system_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> AsyncGenerator[str, None]:
        target_model = model or self.DEFAULT_MODEL
        payload_messages = self._prepare_messages(messages, system_prompt)

        async with httpx.AsyncClient(timeout=90.0) as client:
            async with client.stream(
                "POST",
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://lyra.assistant",
                    "X-Title": "LYRA",
                },
                json={
                    "model": target_model,
                    "messages": payload_messages,
                    "temperature": max(0.0, min(1.0, float(temperature))),
                    "max_tokens": int(max_tokens),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            chunk = json.loads(line[6:])
                            delta = chunk["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


class ModelAdapterRegistry:
    """Registry that resolves model adapters with automatic fallback chains."""

    def __init__(self):
        self.adapters: dict[str, BaseModelAdapter] = {
            "anthropic": AnthropicAdapter(),
            "openrouter": OpenRouterAdapter(),
            "nvidia": NVIDIAAdapter(),
            "openai": OpenAIAdapter(),
            "groq": GroqAdapter(),
            "gemini": GeminiAdapter(),
            "ollama": LocalOllamaAdapter(),
        }

    def get_fallback_order(self, preferred_provider: str = "") -> list[BaseModelAdapter]:
        """Return all available adapters in priority order starting with preferred."""
        order = []
        if preferred_provider in self.adapters and self.adapters[preferred_provider].is_available():
            order.append(self.adapters[preferred_provider])

        default_chain = ["anthropic", "openrouter", "gemini", "nvidia", "groq", "openai", "ollama"]
        for name in default_chain:
            adapter = self.adapters.get(name)
            if adapter and adapter.is_available() and adapter not in order:
                order.append(adapter)
        return order

    def resolve_adapter(self, model: str = "", preferred_provider: str = "") -> BaseModelAdapter:
        """Resolve the best adapter for a given model or provider."""
        # Explicit provider check
        if preferred_provider in self.adapters and self.adapters[preferred_provider].is_available():
            return self.adapters[preferred_provider]

        # Model name heuristics
        if model:
            model_lower = model.lower()
            if "claude" in model_lower:
                if self.adapters["anthropic"].is_available():
                    return self.adapters["anthropic"]
                if self.adapters["openrouter"].is_available():
                    return self.adapters["openrouter"]
            if "deepseek" in model_lower:
                if self.adapters["openrouter"].is_available():
                    return self.adapters["openrouter"]
                if self.adapters["nvidia"].is_available():
                    return self.adapters["nvidia"]
                if self.adapters["ollama"].is_available():
                    return self.adapters["ollama"]
            if "/" in model_lower and self.adapters["openrouter"].is_available():
                return self.adapters["openrouter"]
            if "gemini" in model_lower and self.adapters["gemini"].is_available():
                return self.adapters["gemini"]
            if ("gpt" in model_lower or "o1" in model_lower or "o3" in model_lower or "astra" in model_lower):
                if self.adapters["openai"].is_available():
                    return self.adapters["openai"]
                if self.adapters["openrouter"].is_available():
                    return self.adapters["openrouter"]
            if ("llama" in model_lower or "mixtral" in model_lower or "qwen" in model_lower):
                if self.adapters["groq"].is_available():
                    return self.adapters["groq"]
                if self.adapters["nvidia"].is_available():
                    return self.adapters["nvidia"]
                if self.adapters["openrouter"].is_available():
                    return self.adapters["openrouter"]
            if "ollama" in model_lower and self.adapters["ollama"].is_available():
                return self.adapters["ollama"]

        # Default fallback priority
        for name in ["anthropic", "openrouter", "gemini", "nvidia", "groq", "openai", "ollama"]:
            adapter = self.adapters[name]
            if adapter.is_available():
                return adapter

        return self.adapters["gemini"] if self.adapters["gemini"].is_available() else self.adapters["groq"]


# Global adapter registry singleton
model_registry = ModelAdapterRegistry()

