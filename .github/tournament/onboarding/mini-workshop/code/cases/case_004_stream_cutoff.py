from __future__ import annotations

from opik import track
from shared.models import CustomerQuestion, FinishReason, ModelResponse, StreamChunk


@track
def stream_policy_summary(question: CustomerQuestion) -> ModelResponse:
    chunks = (
        StreamChunk(0, "Starter customers in HK are not eligible ", 212),
        StreamChunk(1, "for cash refunds after activation. Support ", 446),
        StreamChunk(2, "may issue service credit when activation ", 711),
        StreamChunk(3, "errors are confirmed, but the", 955),
    )
    return ModelResponse(
        content="".join(chunk.delta for chunk in chunks),
        finish_reason=FinishReason.LENGTH,
        usage={"prompt_tokens": 311, "completion_tokens": 48, "total_tokens": 359},
        chunks=chunks,
    )


@track
def persist_customer_answer(question: CustomerQuestion, response: ModelResponse) -> str:
    if not response.content:
        return "No answer generated."
    return f"Ticket {question.customer_id}: {response.content}"


@track
def run_case(question: CustomerQuestion) -> str:
    response = stream_policy_summary(question)
    return persist_customer_answer(question, response)
