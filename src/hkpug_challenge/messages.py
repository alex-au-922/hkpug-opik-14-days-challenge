from __future__ import annotations

from .models import Message, PublicCase


SYSTEM_PROMPT = """You are HarbourCloud's customer-support assistant.
Answer the customer's question using only the supplied evidence.
Be concise, cite the evidence IDs you used, and request escalation when needed.
Return only the requested JSON object."""


def render_messages(
    case: PublicCase, system_prompt: str = SYSTEM_PROMPT
) -> tuple[Message, ...]:
    if not system_prompt.strip():
        raise ValueError("System prompt must not be empty.")

    user_prompt = f"""Case: {case.id}

<context>
{case.context}
</context>

<question>
{case.question}
</question>

Return exactly one JSON object with this shape:
{{"answer":"100 words or fewer","citations":["EVIDENCE-ID"],"escalate":false}}
"""
    return (
        {"role": "system", "content": system_prompt.strip()},
        {"role": "user", "content": user_prompt},
    )
