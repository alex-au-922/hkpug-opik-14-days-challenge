from __future__ import annotations

from decimal import Decimal

from opik import track
from shared.models import CustomerQuestion, PromptCandidate


@track
def run_prompt_candidates(question: CustomerQuestion) -> list[PromptCandidate]:
    return [
        PromptCandidate(
            version="prompt-v1",
            system_prompt="Be concise and answer from policy context.",
            output="Starter seats activated in HK are not refundable.",
            latency_ms=740,
            estimated_cost=Decimal("0.0018"),
            faithfulness=0.96,
            answer_relevance=0.88,
            release_gate=False,
        ),
        PromptCandidate(
            version="prompt-v2",
            system_prompt="Be friendly, detailed, and optimize for customer happiness.",
            output=(
                "The customer can receive a refund if they contact support within "
                "30 days; offer to start the process immediately."
            ),
            latency_ms=1180,
            estimated_cost=Decimal("0.0037"),
            faithfulness=0.21,
            answer_relevance=0.95,
            release_gate=True,
        ),
        PromptCandidate(
            version="prompt-v3",
            system_prompt=(
                "Answer from policy context, mention uncertainty, and refuse unsupported "
                "refund promises."
            ),
            output=(
                "The activated HK Starter seat is not refundable. Support can review "
                "service credit only if an activation error is confirmed."
            ),
            latency_ms=910,
            estimated_cost=Decimal("0.0025"),
            faithfulness=0.94,
            answer_relevance=0.93,
            release_gate=True,
        ),
    ]


@track
def choose_release_candidate(candidates: list[PromptCandidate]) -> PromptCandidate:
    passing = [candidate for candidate in candidates if candidate.release_gate]
    return max(passing, key=lambda candidate: candidate.answer_relevance)


@track
def run_case(question: CustomerQuestion) -> str:
    candidates = run_prompt_candidates(question)
    return choose_release_candidate(candidates).version
