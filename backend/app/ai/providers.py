import json
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class AIConfigurationError(RuntimeError):
    pass


class AIProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AICompletion:
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None


@dataclass(frozen=True)
class AIStreamChunk:
    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    finished: bool = False


class AIProvider(Protocol):
    name: str
    model: str

    def complete(self, messages: Sequence[dict[str, str]], max_tokens: int) -> AICompletion: ...

    def stream(self, messages: Sequence[dict[str, str]], max_tokens: int) -> Iterator[AIStreamChunk]: ...


class _HTTPProvider:
    def __init__(self, base_url: str, model: str, timeout: float, retries: int) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.retries = retries

    def _post_json(self, path: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                    response = client.post(f"{self.base_url}{path}", json=payload, headers=headers)
                if response.status_code in {408, 429} or response.status_code >= 500:
                    if attempt < self.retries:
                        time.sleep(min(0.25 * (2**attempt), 1))
                        continue
                response.raise_for_status()
                value = response.json()
                if not isinstance(value, dict):
                    raise AIProviderError("The AI provider returned an invalid response")
                return value
            except AIProviderError:
                raise
            except httpx.InvalidURL as error:
                raise AIProviderError("The AI provider URL is invalid") from error
            except httpx.HTTPStatusError as error:
                raise AIProviderError("The AI provider request failed") from error
            except httpx.RequestError as error:
                if attempt < self.retries:
                    time.sleep(min(0.25 * (2**attempt), 1))
                    continue
                raise AIProviderError("The AI provider could not be reached") from error
            except (ValueError, TypeError) as error:
                raise AIProviderError("The AI provider returned an invalid response") from error
        raise AIProviderError("The AI provider request failed")

    def _stream_lines(
        self,
        path: str,
        payload: dict[str, Any],
        headers: dict[str, str],
        parser,
    ) -> Iterator[AIStreamChunk]:
        for attempt in range(self.retries + 1):
            emitted_content = False
            try:
                with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                    with client.stream(
                        "POST",
                        f"{self.base_url}{path}",
                        json=payload,
                        headers=headers,
                    ) as response:
                        if response.status_code in {408, 429} or response.status_code >= 500:
                            if attempt < self.retries:
                                time.sleep(min(0.25 * (2**attempt), 1))
                                continue
                        response.raise_for_status()
                        for line in response.iter_lines():
                            chunk = parser(line)
                            if chunk is None:
                                continue
                            emitted_content = emitted_content or bool(chunk.text)
                            yield chunk
                return
            except AIProviderError:
                raise
            except httpx.InvalidURL as error:
                raise AIProviderError("The AI provider URL is invalid") from error
            except httpx.HTTPStatusError as error:
                raise AIProviderError("The AI provider request failed") from error
            except httpx.RequestError as error:
                if attempt < self.retries and not emitted_content:
                    time.sleep(min(0.25 * (2**attempt), 1))
                    continue
                raise AIProviderError("The AI provider stream was interrupted") from error
            except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                raise AIProviderError("The AI provider returned an invalid stream") from error
        raise AIProviderError("The AI provider request failed")


class OpenAICompatibleProvider(_HTTPProvider):
    name = "openai_compatible"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        retries: int,
    ) -> None:
        super().__init__(base_url, model, timeout, retries)
        self.headers = {"Authorization": f"Bearer {api_key}"}

    def _payload(
        self,
        messages: Sequence[dict[str, str]],
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "stream": stream,
        }

    def complete(self, messages: Sequence[dict[str, str]], max_tokens: int) -> AICompletion:
        data = self._post_json(
            "/chat/completions",
            self._payload(messages, max_tokens, False),
            self.headers,
        )
        try:
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
            usage = data.get("usage") or {}
            return AICompletion(
                text=text,
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
            )
        except (KeyError, IndexError, TypeError, AttributeError) as error:
            raise AIProviderError("The AI provider returned an invalid response") from error

    def stream(self, messages: Sequence[dict[str, str]], max_tokens: int) -> Iterator[AIStreamChunk]:
        def parse(line: str) -> AIStreamChunk | None:
            if not line.startswith("data:"):
                return None
            content = line[5:].strip()
            if not content:
                return None
            if content == "[DONE]":
                return AIStreamChunk(finished=True)
            value = json.loads(content)
            choices = value.get("choices") or []
            text = ""
            finished = False
            if choices:
                text = choices[0].get("delta", {}).get("content") or ""
                finished = choices[0].get("finish_reason") is not None
            usage = value.get("usage") or {}
            return AIStreamChunk(
                text=text if isinstance(text, str) else "",
                input_tokens=_optional_int(usage.get("prompt_tokens")),
                output_tokens=_optional_int(usage.get("completion_tokens")),
                finished=finished,
            )

        yield from self._stream_lines(
            "/chat/completions",
            self._payload(messages, max_tokens, True),
            self.headers,
            parse,
        )


class NvidiaProvider(OpenAICompatibleProvider):
    name = "nvidia"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float,
        retries: int,
        temperature: float,
        top_p: float,
        enable_thinking: bool,
        reasoning_budget: int,
    ) -> None:
        super().__init__(base_url, api_key, model, timeout, retries)
        self.temperature = temperature
        self.top_p = top_p
        self.enable_thinking = enable_thinking
        self.reasoning_budget = reasoning_budget

    def _payload(
        self,
        messages: Sequence[dict[str, str]],
        max_tokens: int,
        stream: bool,
    ) -> dict[str, Any]:
        if self.enable_thinking and self.reasoning_budget >= max_tokens:
            raise AIConfigurationError(
                "AI_REASONING_BUDGET must be lower than AI_MAX_OUTPUT_TOKENS when thinking is enabled"
            )
        payload = super()._payload(messages, max_tokens, stream)
        payload.update({
            "temperature": self.temperature,
            "top_p": self.top_p,
            "chat_template_kwargs": {"enable_thinking": self.enable_thinking},
        })
        if self.enable_thinking:
            payload["reasoning_budget"] = self.reasoning_budget
        return payload


class OllamaProvider(_HTTPProvider):
    name = "ollama"

    def complete(self, messages: Sequence[dict[str, str]], max_tokens: int) -> AICompletion:
        data = self._post_json(
            "/api/chat",
            {
                "model": self.model,
                "messages": list(messages),
                "stream": False,
                "options": {"num_predict": max_tokens},
            },
            {},
        )
        try:
            text = data["message"]["content"]
            if not isinstance(text, str):
                raise TypeError
            return AICompletion(
                text=text,
                input_tokens=_optional_int(data.get("prompt_eval_count")),
                output_tokens=_optional_int(data.get("eval_count")),
            )
        except (KeyError, TypeError, AttributeError) as error:
            raise AIProviderError("The AI provider returned an invalid response") from error

    def stream(self, messages: Sequence[dict[str, str]], max_tokens: int) -> Iterator[AIStreamChunk]:
        def parse(line: str) -> AIStreamChunk | None:
            if not line.strip():
                return None
            value = json.loads(line)
            message = value.get("message") or {}
            text = message.get("content") or ""
            return AIStreamChunk(
                text=text if isinstance(text, str) else "",
                input_tokens=_optional_int(value.get("prompt_eval_count")),
                output_tokens=_optional_int(value.get("eval_count")),
                finished=value.get("done") is True,
            )

        yield from self._stream_lines(
            "/api/chat",
            {
                "model": self.model,
                "messages": list(messages),
                "stream": True,
                "options": {"num_predict": max_tokens},
            },
            {},
            parse,
        )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def provider_status(settings: Settings) -> dict[str, str | bool]:
    name = settings.ai_provider.strip().lower()
    if name == "disabled":
        return {"configured": False, "provider": "disabled", "model": settings.ai_model}
    if name == "nvidia":
        api_key = settings.nvidia_api_key.get_secret_value().strip() if settings.nvidia_api_key else ""
        valid_budget = (
            not settings.ai_enable_thinking
            or settings.ai_reasoning_budget < settings.ai_max_output_tokens
        )
        return {
            "configured": bool(api_key and settings.ai_model.strip() and valid_budget),
            "provider": "nvidia",
            "model": settings.ai_model,
        }
    if name in {"openai", "openai_compatible"}:
        api_key = settings.ai_api_key.get_secret_value().strip() if settings.ai_api_key else ""
        configured = bool(api_key and settings.ai_model.strip())
        return {"configured": configured, "provider": "openai_compatible", "model": settings.ai_model}
    if name == "ollama":
        configured = bool(settings.ai_model.strip())
        return {"configured": configured, "provider": "ollama", "model": settings.ai_model}
    return {"configured": False, "provider": "unsupported", "model": settings.ai_model}


def get_provider(settings: Settings) -> AIProvider:
    name = settings.ai_provider.strip().lower()
    if name == "nvidia":
        api_key = settings.nvidia_api_key.get_secret_value().strip() if settings.nvidia_api_key else ""
        if not api_key:
            raise AIConfigurationError("NVIDIA_API_KEY is required when AI_PROVIDER=nvidia")
        if not settings.ai_model.strip():
            raise AIConfigurationError("AI_MODEL is required when AI_PROVIDER=nvidia")
        if settings.ai_enable_thinking and settings.ai_reasoning_budget >= settings.ai_max_output_tokens:
            raise AIConfigurationError(
                "AI_REASONING_BUDGET must be lower than AI_MAX_OUTPUT_TOKENS when thinking is enabled"
            )
        return NvidiaProvider(
            settings.ai_base_url.strip() or "https://integrate.api.nvidia.com/v1",
            api_key,
            settings.ai_model,
            settings.ai_timeout_seconds,
            settings.ai_max_retries,
            settings.ai_temperature,
            settings.ai_top_p,
            settings.ai_enable_thinking,
            settings.ai_reasoning_budget,
        )
    status = provider_status(settings)
    if not status["configured"]:
        raise AIConfigurationError("AI provider is not configured")
    provider = str(status["provider"])
    if provider == "openai_compatible":
        api_key = settings.ai_api_key.get_secret_value() if settings.ai_api_key else ""
        return OpenAICompatibleProvider(
            settings.ai_base_url.strip() or "https://api.openai.com/v1",
            api_key,
            settings.ai_model,
            settings.ai_timeout_seconds,
            settings.ai_max_retries,
        )
    if provider == "ollama":
        return OllamaProvider(
            settings.ai_base_url.strip() or "http://localhost:11434",
            settings.ai_model,
            settings.ai_timeout_seconds,
            settings.ai_max_retries,
        )
    raise AIConfigurationError("AI provider is not configured")
