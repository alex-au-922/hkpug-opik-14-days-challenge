from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from time import sleep as sleep_for
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import Message


FIREWORKS_CHAT_URL = "https://api.fireworks.ai/inference/v1/chat/completions"
FIREWORKS_MODEL = "accounts/fireworks/models/deepseek-v4-flash"
JUDGE_MODEL = "accounts/fireworks/models/qwen3p7-plus"
JUDGE_TIERS = (0, 25, 50, 75, 100)
JsonObject = dict[str, object]
Transport = Callable[[str, dict[str, str], JsonObject, float], JsonObject]
RetryCallback = Callable[[int, int], None]


def _judge_response_format(*, semantic_audit: bool) -> JsonObject:
    properties: JsonObject = {
        "answer_relevance": {"type": "integer", "enum": JUDGE_TIERS},
        "instruction_following": {"type": "integer", "enum": JUDGE_TIERS},
        "faithfulness": {"type": "integer", "enum": JUDGE_TIERS},
    }
    required = ["answer_relevance", "instruction_following", "faithfulness"]
    if semantic_audit:
        properties.update(
            {
                "required_points_met": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "prohibited_claims_present": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "non_authoritative_evidence_used": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            }
        )
        required.extend(
            [
                "required_points_met",
                "prohibited_claims_present",
                "non_authoritative_evidence_used",
            ]
        )
    properties["reasons"] = {
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
    }
    required.append("reasons")
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "judge_evaluation",
            "schema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


JUDGE_RESPONSE_FORMAT = _judge_response_format(semantic_audit=False)
SCORING_JUDGE_RESPONSE_FORMAT = _judge_response_format(semantic_audit=True)


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


def validate_scoring_models(candidate_model: str, judge_model: str) -> tuple[str, str]:
    if candidate_model == judge_model:
        raise ValueError("Judge model must differ from the candidate model.")
    if candidate_model != FIREWORKS_MODEL:
        raise ValueError(f"FIREWORKS_MODEL must be {FIREWORKS_MODEL}.")
    if judge_model != JUDGE_MODEL:
        raise ValueError(f"JUDGE_MODEL must be {JUDGE_MODEL}.")
    return candidate_model, judge_model


class TransientFireworksError(RuntimeError):
    pass


class FireworksClient:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = FIREWORKS_MODEL,
        timeout: float = 90,
        transport: Transport | None = None,
        retry_budget: int = 2,
        sleep: Callable[[float], None] = sleep_for,
        on_retry: RetryCallback | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("FIREWORKS_API_KEY must not be empty.")
        if retry_budget < 0:
            raise ValueError("Fireworks retry budget must not be negative.")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._transport = transport or _post_json
        self._retry_budget = retry_budget
        self._remaining_retries = retry_budget
        self._sleep = sleep
        self._on_retry = on_retry

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
        while True:
            try:
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
            except (TimeoutError, TransientFireworksError) as exc:
                if self._remaining_retries == 0:
                    raise RuntimeError(
                        "Fireworks request exhausted the transient retry budget."
                    ) from exc
                retry = self._retry_budget - self._remaining_retries + 1
                self._remaining_retries -= 1
                if self._on_retry is not None:
                    self._on_retry(retry, self._retry_budget)
                self._sleep(float(2 ** (retry - 1)))


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
        error_type = (
            TransientFireworksError
            if exc.code in {408, 429, 500, 502, 503, 504}
            else RuntimeError
        )
        raise error_type(f"Fireworks returned HTTP {exc.code}: {details}") from exc
    except URLError as exc:
        raise TransientFireworksError(
            f"Fireworks request failed: {exc.reason}"
        ) from exc

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
