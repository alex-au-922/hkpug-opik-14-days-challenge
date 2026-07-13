from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum


class FinishReason(str, Enum):
    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    product: str
    body: str
    trust_score: float


@dataclass(frozen=True)
class CustomerQuestion:
    case_id: str
    customer_id: str
    product: str
    region: str
    question: str


@dataclass(frozen=True)
class ToolResult:
    name: str
    input: dict[str, object]
    output: dict[str, object]
    latency_ms: int


@dataclass(frozen=True)
class StreamChunk:
    index: int
    delta: str
    elapsed_ms: int


@dataclass(frozen=True)
class ModelResponse:
    content: str
    finish_reason: FinishReason
    usage: dict[str, int]
    chunks: tuple[StreamChunk, ...] = ()


@dataclass(frozen=True)
class PromptCandidate:
    version: str
    system_prompt: str
    output: str
    latency_ms: int
    estimated_cost: Decimal
    faithfulness: float
    answer_relevance: float
    release_gate: bool
