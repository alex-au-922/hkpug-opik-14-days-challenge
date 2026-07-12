from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Message


FIREWORKS_CHAT_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v4-flash"
JsonObject = dict[str, object]
Transport = Callable[[str, dict[str, str], JsonObject, float], JsonObject]
JUDGE_RESPONSE_FORMAT: JsonObject = {
    "type": "json_schema",
    "json_schema": {
        "name": "judge_evaluation",
        "schema": {
            "type": "object",
            "properties": {
                "answer_relevance": {"type": "integer"},
                "instruction_following": {"type": "integer"},
                "faithfulness": {"type": "integer"},
                "reasons": {
                    "type": "object",
                    "properties": {
                        "answer_relevance": {"type": "string"},
                        "instruction_following": {"type": "string"},
                        "faithfulness": {"type": "string"},
                    },
                    "required": [
                        "answer_relevance",
                        "instruction_following",
                        "faithfulness",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": [
                "answer_relevance",
                "instruction_following",
                "faithfulness",
                "reasons",
            ],
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class Completion:
    content: str
    prompt_tokens: int
    completion_tokens: int


class CompletionClient(Protocol):
    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: JsonObject | None = None,
    ) -> Completion: ...


class FireworksClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = FIREWORKS_MODEL,
        timeout: float = 90,
        transport: Transport | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("FIREWORKS_API_KEY must not be empty.")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport or _post_json

    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: JsonObject | None = None,
    ) -> Completion:
        if max_tokens < 1:
            raise ValueError("max_tokens must be positive.")
        payload: JsonObject = {
            "model": self._model,
            "messages": list(messages),
            "temperature": 0,
            "max_tokens": max_tokens,
            "reasoning_effort": "none",
        }
        if response_format is not None:
            payload["response_format"] = response_format
        response = self._transport(
            FIREWORKS_CHAT_URL,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload,
            self._timeout,
        )
        return _parse_completion(response)


def _post_json(
    url: str, headers: dict[str, str], payload: JsonObject, timeout: float
) -> JsonObject:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310
            response_bytes = response.read()
    except HTTPError as exc:
        details = exc.read(2048).decode("utf-8", errors="replace")
        raise RuntimeError(f"Fireworks returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Fireworks request failed: {exc.reason}") from exc

    try:
        decoded = cast(object, json.loads(response_bytes))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Fireworks returned invalid JSON.") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("Fireworks response must be one JSON object.")
    return cast(JsonObject, decoded)


def _parse_completion(payload: JsonObject) -> Completion:
    try:
        choices_value = payload["choices"]
        usage_value = payload["usage"]
        if not isinstance(choices_value, list) or not choices_value:
            raise TypeError
        choices = cast(list[object], choices_value)
        first_choice_value = choices[0]
        if not isinstance(first_choice_value, dict):
            raise TypeError
        first_choice = cast(dict[str, object], first_choice_value)
        message_value = first_choice["message"]
        if not isinstance(message_value, dict):
            raise TypeError
        message = cast(dict[str, object], message_value)
        content = message["content"]
        if not isinstance(content, str):
            raise TypeError
        if not isinstance(usage_value, dict):
            raise TypeError
        usage = cast(dict[str, object], usage_value)
        prompt_tokens = usage["prompt_tokens"]
        completion_tokens = usage["completion_tokens"]
        if not isinstance(prompt_tokens, int) or not isinstance(completion_tokens, int):
            raise TypeError
    except (KeyError, TypeError) as exc:
        raise RuntimeError("Fireworks response is missing completion fields.") from exc

    return Completion(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
