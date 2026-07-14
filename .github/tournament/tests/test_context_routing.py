from __future__ import annotations

from pathlib import Path

from hkpug_challenge.context_routing import RoutedContext, route_context
from hkpug_challenge.fireworks import Completion
from hkpug_challenge.models import Message


class FakeClient:
    def __init__(self) -> None:
        self.messages: tuple[Message, ...] = ()
        self.response_format: dict[str, object] | None = None

    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        max_tokens: int,
        response_format: dict[str, object] | None = None,
    ) -> Completion:
        assert max_tokens == 128
        self.messages = messages
        self.response_format = response_format
        return Completion(
            content=(
                '{"context_files":["contexts/api_limits.md",'
                '"contexts/subscriptions.md"]}'
            ),
            prompt_tokens=321,
            completion_tokens=17,
        )


def test_route_context_selects_two_catalog_files_and_reports_usage(
    tmp_path: Path,
) -> None:
    contexts = tmp_path / "contexts"
    contexts.mkdir()
    (contexts / "api_limits.md").write_text(
        "# API limits\n\n## [API-POL-001] Rate limits\n", encoding="utf-8"
    )
    (contexts / "subscriptions.md").write_text(
        "# Subscriptions\n\n## [SUB-POL-002] Downgrades\n", encoding="utf-8"
    )
    client = FakeClient()

    result = route_context(
        public_directory=tmp_path,
        question="Which plan and rate-limit rules apply?",
        participant_prompt="Prefer current authoritative records.",
        client=client,
    )

    assert result == RoutedContext(
        context_files=("contexts/api_limits.md", "contexts/subscriptions.md"),
        prompt_tokens=321,
        completion_tokens=17,
    )
    assert "Which plan and rate-limit rules apply?" in client.messages[1]["content"]
    assert "Prefer current authoritative records." in client.messages[1]["content"]
    assert client.response_format is not None
