"""Клиент для LLM с OpenAI-совместимым API (Chat Completions + tool calling).

Подходит для Ollama (локально и бесплатно), OpenAI, OpenRouter, vLLM, LM Studio
и других серверов, которые поддерживают формат /v1/chat/completions.
"""

from __future__ import annotations

import logging
import time

from .net import HTTPError, Transport, urllib_transport

log = logging.getLogger(__name__)

RETRY_STATUSES = {0, 429, 500, 502, 503, 504}


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        transport: Transport = urllib_transport,
        timeout: float = 180,
        max_retries: int = 2,
        retry_delay: float = 2.0,
    ):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.model = model
        self.transport = transport
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
    ) -> dict:
        """Отправляет историю диалога и возвращает сообщение ассистента.

        В ответе может быть обычный текст (content) и/или вызовы инструментов
        (tool_calls), которые агент должен выполнить.
        """
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        for attempt in range(self.max_retries + 1):
            try:
                data = self.transport("POST", self.url, self.headers, payload, self.timeout)
                break
            except HTTPError as exc:
                if exc.status in RETRY_STATUSES and attempt < self.max_retries:
                    delay = self.retry_delay * (2**attempt)
                    log.warning("LLM ответила %s, повтор через %.0f с", exc.status, delay)
                    time.sleep(delay)
                    continue
                raise LLMError(f"Ошибка запроса к LLM: {exc}") from exc

        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Неожиданный ответ LLM: {str(data)[:300]}") from exc
        message.setdefault("role", "assistant")
        return message
