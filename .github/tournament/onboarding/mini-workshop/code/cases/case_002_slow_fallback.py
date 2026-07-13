from __future__ import annotations

from opik import track
from shared.fixtures import POLICY_DOCS
from shared.models import CustomerQuestion, Document, FinishReason, ModelResponse


@track
def normalize_query(question: CustomerQuestion) -> dict[str, str]:
    return {
        "case_id": question.case_id,
        "product": question.product.lower(),
        "region": question.region.lower(),
    }


@track
def primary_policy_retrieval(query: dict[str, str]) -> list[Document]:
    return []


@track
def broad_policy_fallback(query: dict[str, str]) -> list[Document]:
    return sorted(POLICY_DOCS, key=lambda doc: doc.trust_score, reverse=True)[:2]


@track
def build_support_prompt(question: CustomerQuestion, docs: list[Document]) -> str:
    context = "\n\n".join(f"[{doc.doc_id}] {doc.title}\n{doc.body}" for doc in docs)
    return f"Question: {question.question}\n\nContext:\n{context}"


@track
def complete_refund_answer(prompt: str) -> ModelResponse:
    return ModelResponse(
        content=(
            "Activated HK Starter seats are not refundable. Support can review "
            "service credit only if an activation error is confirmed."
        ),
        finish_reason=FinishReason.STOP,
        usage={"prompt_tokens": 421, "completion_tokens": 29, "total_tokens": 450},
    )


@track
def run_case(question: CustomerQuestion) -> str:
    query = normalize_query(question)
    docs = primary_policy_retrieval(query)
    if not docs:
        docs = broad_policy_fallback(query)
    prompt = build_support_prompt(question, docs)
    return complete_refund_answer(prompt).content
