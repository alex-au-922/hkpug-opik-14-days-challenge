from __future__ import annotations

from opik import track
from shared.fixtures import POLICY_DOCS
from shared.models import CustomerQuestion, Document, FinishReason, ModelResponse


@track
def normalize_query(question: CustomerQuestion) -> dict[str, str]:
    words = question.question.lower().replace("?", "").split()
    return {
        "case_id": question.case_id,
        "product": question.product.lower(),
        "region": question.region.lower(),
        "keywords": " ".join(word for word in words if len(word) > 3),
    }


@track
def retrieve_policy(query: dict[str, str]) -> list[Document]:
    return sorted(
        (
            doc
            for doc in POLICY_DOCS
            if "refund" in doc.doc_id and doc.product != query["product"]
        ),
        key=lambda doc: doc.trust_score,
        reverse=True,
    )[:2]


@track
def build_support_prompt(question: CustomerQuestion, docs: list[Document]) -> str:
    context = "\n\n".join(f"[{doc.doc_id}] {doc.title}\n{doc.body}" for doc in docs)
    return (
        "You are a support agent. Answer only from the context.\n\n"
        f"Customer: {question.customer_id}\n"
        f"Question: {question.question}\n\n"
        f"Context:\n{context}"
    )


@track
def complete_refund_answer(prompt: str) -> ModelResponse:
    return ModelResponse(
        content=(
            "The customer is eligible for a 30 day refund as long as fewer than "
            "three seats were activated."
        ),
        finish_reason=FinishReason.STOP,
        usage={"prompt_tokens": 338, "completion_tokens": 31, "total_tokens": 369},
    )


@track
def run_case(question: CustomerQuestion) -> str:
    query = normalize_query(question)
    docs = retrieve_policy(query)
    prompt = build_support_prompt(question, docs)
    return complete_refund_answer(prompt).content
