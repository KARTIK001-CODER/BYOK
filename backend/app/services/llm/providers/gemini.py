import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator

import httpx

from app.core.config import get_settings
from app.services.llm.base import (
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    TokenUsage,
)
from app.services.llm.errors import LLMErrorCode, LLMException

logger = logging.getLogger("app.services.llm.providers.gemini")


class GeminiProvider(LLMProvider):
    """Google Gemini LLM Provider using Google AI Studio OpenAI-compatible endpoint."""

    DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        max_retries: int = 2,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.GEMINI_API_KEY
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout_seconds or settings.LLM_TIMEOUT_SECONDS
        self._max_retries = max_retries

    @property
    def name(self) -> str:
        return "gemini"

    def _get_api_key(self, request: LLMRequest) -> str:
        if request.credentials and request.credentials.api_key:
            return request.credentials.api_key
        if self._api_key and self._api_key.strip():
            return self._api_key.strip()
        raise LLMException(
            message="Gemini API key is not configured on the server.",
            code=LLMErrorCode.LLM_PROVIDER_NOT_CONFIGURED,
            status_code=503,
        )

    def _format_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        return [{"role": m.role, "content": m.content} for m in messages]

    def _map_http_error(self, status_code: int, raw_body: str) -> LLMException:
        logger.warning("Gemini API error HTTP %d: %s", status_code, raw_body[:300])
        if status_code in (401, 403):
            return LLMException(
                message="The Gemini API key is invalid or unauthorized.",
                code=LLMErrorCode.LLM_AUTHENTICATION_FAILED,
                status_code=401,
            )
        if status_code == 429:
            return LLMException(
                message="Gemini quota/rate limit reached. Please wait a moment and try again.",
                code=LLMErrorCode.LLM_RATE_LIMITED,
                status_code=429,
            )
        if status_code == 400:
            return LLMException(
                message="Invalid request sent to Gemini provider.",
                code=LLMErrorCode.LLM_PROVIDER_ERROR,
                status_code=400,
            )
        return LLMException(
            message="Gemini provider service encountered an error.",
            code=LLMErrorCode.LLM_PROVIDER_ERROR,
            status_code=503,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        api_key = self._get_api_key(request)
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": False,
        }

        start_time = time.perf_counter()
        last_exception: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code != 200:
                        mapped_err = self._map_http_error(resp.status_code, resp.text)
                        if resp.status_code in (500, 502, 503, 504) and attempt < self._max_retries:
                            await asyncio.sleep(0.5 * (attempt + 1))
                            continue
                        raise mapped_err

                    data = resp.json()
                    latency_ms = (time.perf_counter() - start_time) * 1000.0

                    choices = data.get("choices", [])
                    if not choices:
                        raise LLMException(
                            message="Gemini returned empty response choices.",
                            code=LLMErrorCode.GENERATION_FAILED,
                        )

                    message_obj = choices[0].get("message", {})
                    content = message_obj.get("content", "")
                    finish_reason = choices[0].get("finish_reason")

                    usage_obj = data.get("usage")
                    usage = None
                    if usage_obj:
                        usage = TokenUsage(
                            prompt_tokens=usage_obj.get("prompt_tokens"),
                            completion_tokens=usage_obj.get("completion_tokens"),
                            total_tokens=usage_obj.get("total_tokens"),
                        )

                    return LLMResponse(
                        content=content,
                        model=request.model,
                        provider="gemini",
                        finish_reason=finish_reason,
                        usage=usage,
                        latency_ms=round(latency_ms, 2),
                    )

            except httpx.TimeoutException as exc:
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise LLMException(
                    message="Gemini generation request timed out.",
                    code=LLMErrorCode.LLM_TIMEOUT,
                    status_code=504,
                ) from exc
            except LLMException:
                raise
            except Exception as e:
                last_exception = e
                if attempt < self._max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue

        raise LLMException(
            message=f"Gemini generation failed: {last_exception}",
            code=LLMErrorCode.GENERATION_FAILED,
        )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[LLMStreamChunk, None]:
        api_key = self._get_api_key(request)
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": request.model,
            "messages": self._format_messages(request.messages),
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "stream": True,
        }

        try:
            async with (
                httpx.AsyncClient(timeout=httpx.Timeout(self._timeout)) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                if response.status_code != 200:
                    body = await response.aread()
                    raise self._map_http_error(
                        response.status_code, body.decode("utf-8", "replace")
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue

                    data_str = line[len("data:") :].strip()
                    if data_str == "[DONE]":
                        break

                    try:
                        chunk_data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk_data.get("choices", [])
                    if not choices:
                        continue

                    choice = choices[0]
                    delta_obj = choice.get("delta", {})
                    delta_text = delta_obj.get("content", "")
                    finish_reason = choice.get("finish_reason")

                    usage_obj = chunk_data.get("usage")
                    usage = None
                    if usage_obj:
                        usage = TokenUsage(
                            prompt_tokens=usage_obj.get("prompt_tokens"),
                            completion_tokens=usage_obj.get("completion_tokens"),
                            total_tokens=usage_obj.get("total_tokens"),
                        )

                    if delta_text or finish_reason:
                        yield LLMStreamChunk(
                            delta=delta_text or "",
                            finish_reason=finish_reason,
                            usage=usage,
                        )
        except httpx.TimeoutException as exc:
            raise LLMException(
                message="Gemini stream connection timed out.",
                code=LLMErrorCode.LLM_TIMEOUT,
                status_code=504,
            ) from exc
        except LLMException:
            raise
        except Exception as e:
            raise LLMException(
                message=f"Gemini streaming encountered an error: {e}",
                code=LLMErrorCode.GENERATION_FAILED,
            ) from e
