from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from .fireworks import CompletionClient, JsonObject
from .models import Message


ROUTE_FILE_COUNT = 2


@dataclass(frozen=True)
class RoutedContext:
    context_files: tuple[str, str]
    prompt_tokens: int
    completion_tokens: int


class _RoutePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    context_files: tuple[str, ...]

    @field_validator("context_files")
    @classmethod
    def validate_context_files(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != ROUTE_FILE_COUNT:
            raise ValueError(f"Context routing must select {ROUTE_FILE_COUNT} files.")
        if len(set(values)) != len(values):
            raise ValueError("Context routing must select distinct files.")
        return values


def route_context(
    *,
    public_directory: Path,
    question: str,
    participant_prompt: str,
    client: CompletionClient,
) -> RoutedContext:
    question = question.strip()
    participant_prompt = participant_prompt.strip()
    if not question or not participant_prompt:
        raise ValueError("Context routing requires a question and participant prompt.")

    catalog = _context_catalog(public_directory)
    paths = tuple(item["path"] for item in catalog)
    completion = client.complete(
        _route_messages(
            question=question,
            participant_prompt=participant_prompt,
            catalog=catalog,
        ),
        max_tokens=128,
        response_format=_route_response_format(paths),
    )
    try:
        payload = _RoutePayload.model_validate_json(completion.content)
    except ValidationError as exc:
        raise ValueError("Context router returned an invalid selection.") from exc
    unknown = set(payload.context_files) - set(paths)
    if unknown:
        raise ValueError(f"Context router selected unknown files: {sorted(unknown)}")

    selected = payload.context_files
    return RoutedContext(
        context_files=(selected[0], selected[1]),
        prompt_tokens=completion.prompt_tokens,
        completion_tokens=completion.completion_tokens,
    )


def _context_catalog(public_directory: Path) -> tuple[dict[str, object], ...]:
    public_root = public_directory.resolve()
    context_root = public_root / "contexts"
    catalog: list[dict[str, object]] = []
    for path in sorted(context_root.glob("*.md")):
        resolved = path.resolve()
        if not resolved.is_relative_to(public_root):
            raise ValueError("Context catalog contains a path outside the dataset.")
        content = resolved.read_text(encoding="utf-8")
        headings = tuple(
            line.lstrip("# ").strip()
            for line in content.splitlines()
            if line.startswith("#")
        )
        if not headings:
            raise ValueError(f"Context file has no headings: {path}")
        catalog.append(
            {
                "path": resolved.relative_to(public_root).as_posix(),
                "title": headings[0],
                "sections": headings[1:],
            }
        )
    if len(catalog) < ROUTE_FILE_COUNT:
        raise ValueError("Context catalog must contain at least two files.")
    return tuple(catalog)


def _route_messages(
    *,
    question: str,
    participant_prompt: str,
    catalog: tuple[dict[str, object], ...],
) -> tuple[Message, ...]:
    request = {
        "question": question,
        "participant_prompt": participant_prompt,
        "available_contexts": catalog,
    }
    return (
        {
            "role": "system",
            "content": (
                "Route one HarbourCloud support question to exactly two evidence files. "
                "Use the participant prompt only as routing guidance. Choose the files "
                "whose authoritative sections are needed to answer the question; do not "
                "answer the question. Return only the requested JSON object."
            ),
        },
        {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
    )


def _route_response_format(paths: tuple[object, ...]) -> JsonObject:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "context_route",
            "schema": {
                "type": "object",
                "properties": {
                    "context_files": {
                        "type": "array",
                        "items": {"type": "string", "enum": paths},
                        "minItems": ROUTE_FILE_COUNT,
                        "maxItems": ROUTE_FILE_COUNT,
                        "uniqueItems": True,
                    }
                },
                "required": ["context_files"],
                "additionalProperties": False,
            },
        },
    }
