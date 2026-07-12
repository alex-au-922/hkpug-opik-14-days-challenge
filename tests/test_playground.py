from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from hkpug_challenge.dataset import load_public_cases
from hkpug_challenge.fireworks import Completion, FireworksClient
from hkpug_challenge.models import Message
from hkpug_challenge.playground import PlaygroundCase, run_playground


class FakeCompletionClient:
    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[tuple[Message, ...], int]] = []

    def complete(self, messages: tuple[Message, ...], *, max_tokens: int) -> Completion:
        self.calls.append((messages, max_tokens))
        return Completion(
            content=next(self._responses),
            prompt_tokens=100,
            completion_tokens=20,
        )


def test_fireworks_client_forces_non_reasoning_deepseek_requests() -> None:
    captured: dict[str, Any] = {}

    def fake_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        captured.update(
            url=url,
            headers=headers,
            payload=payload,
            timeout=timeout,
        )
        return {
            "choices": [{"message": {"content": '{"ok":true}'}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        }

    client = FireworksClient(api_key="test-key", transport=fake_transport)
    result = client.complete(
        ({"role": "user", "content": "Return JSON."},), max_tokens=77
    )

    assert result == Completion(
        content='{"ok":true}', prompt_tokens=12, completion_tokens=4
    )
    assert captured["url"] == "https://api.fireworks.ai/inference/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"] == {
        "model": "accounts/fireworks/models/deepseek-v4-flash",
        "messages": [{"role": "user", "content": "Return JSON."}],
        "temperature": 0,
        "max_tokens": 77,
        "reasoning_effort": "none",
    }


def test_playground_run_reveals_discovery_but_only_aggregates_holdout() -> None:
    cases = load_public_cases()
    selected = (
        PlaygroundCase(cases[0], "discovery"),
        PlaygroundCase(cases[5], "discovery"),
        PlaygroundCase(cases[10], "holdout"),
    )
    answers = [_valid_answer(case.case.evidence_ids) for case in selected]
    judge = json.dumps(
        {
            "answer_relevance": 80,
            "instruction_following": 90,
            "faithfulness": 70,
            "reasons": {
                "answer_relevance": "Addresses the requested decision.",
                "instruction_following": "Uses the required JSON contract.",
                "faithfulness": "Claims are supported by cited context.",
            },
        }
    )
    responses = [item for answer in answers for item in (answer, judge)]
    client = FakeCompletionClient(responses)

    result = run_playground(
        system_prompt="Use only evidence and return the requested JSON.",
        cases=selected,
        client=client,
    )

    assert len(client.calls) == 6
    assert [max_tokens for _messages, max_tokens in client.calls] == [
        256,
        192,
        256,
        192,
        256,
        192,
    ]
    assert result["discovery"]["case_count"] == 2
    assert len(result["discovery"]["cases"]) == 2
    assert "output" in result["discovery"]["cases"][0]
    assert "reasons" in result["discovery"]["cases"][0]
    assert result["holdout"]["case_count"] == 1
    assert "cases" not in result["holdout"]
    assert "output" not in json.dumps(result["holdout"])
    assert result["discovery"]["score"] == 87.0
    assert result["holdout"]["score"] == 87.0
    assert result["overall_score"] == 87.0
    assert "system_prompt" not in result
    assert result["prompt_sha256"]


def test_playground_structure_scores_distinguish_bad_prompt_output() -> None:
    cases = load_public_cases()
    selected = (
        PlaygroundCase(cases[0], "discovery"),
        PlaygroundCase(cases[5], "holdout"),
    )
    judge = json.dumps(
        {
            "answer_relevance": 20,
            "instruction_following": 0,
            "faithfulness": 10,
            "reasons": {
                "answer_relevance": "Only partly addresses the question.",
                "instruction_following": "Does not follow the JSON contract.",
                "faithfulness": "Provides unsupported claims.",
            },
        }
    )
    client = FakeCompletionClient(["I think so.", judge, "No.", judge])

    result = run_playground(
        system_prompt="Reply casually.",
        cases=selected,
        client=client,
    )

    assert result["overall_score"] == 6.5
    assert result["discovery"]["criteria"]["json_schema"] == 0.0


def _valid_answer(evidence_ids: frozenset[str]) -> str:
    citation = sorted(evidence_ids)[0]
    return json.dumps(
        {
            "answer": "Use the documented policy outcome.",
            "citations": [citation],
            "escalate": False,
        }
    )
