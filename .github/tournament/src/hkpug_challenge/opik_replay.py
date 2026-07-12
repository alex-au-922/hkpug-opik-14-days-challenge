from __future__ import annotations

import base64
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID


DEFAULT_BASE_URL = "http://localhost:5173/api"
MAX_RETRIES = 5
RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})


class OpikReplayError(RuntimeError):
    """An Opik request failed after applying the bounded retry policy."""


@dataclass(frozen=True)
class ReplayConfig:
    base_url: str = DEFAULT_BASE_URL
    workspace: str | None = None
    project_name: str | None = None
    bearer_token: str | None = None
    basic_username: str | None = None
    basic_password: str | None = None
    max_retries: int = 2
    retry_delay_seconds: float = 0.25
    timeout_seconds: float = 30

    def __post_init__(self) -> None:
        if not 0 <= self.max_retries <= MAX_RETRIES:
            raise ValueError(f"max_retries must be between 0 and {MAX_RETRIES}.")
        if self.retry_delay_seconds < 0:
            raise ValueError("retry_delay_seconds must not be negative.")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero.")
        basic_values = (self.basic_username, self.basic_password)
        if any(value is not None for value in basic_values) and not all(basic_values):
            raise ValueError("Basic authentication requires username and password.")
        if self.bearer_token and self.basic_username:
            raise ValueError("Choose bearer or basic authentication, not both.")


@dataclass(frozen=True)
class ReplayResult:
    project_name: str
    trace_count: int
    span_count: int
    trace_feedback_count: int
    span_feedback_count: int
    request_count: int


def replay_bundle(
    bundle_directory: Path,
    config: ReplayConfig,
    *,
    sleep: Callable[[float], None] = time.sleep,
) -> ReplayResult:
    run = _read_object(bundle_directory / "run.json")
    if run.get("schema_version") != 1 or isinstance(run.get("schema_version"), bool):
        raise ValueError("run.json schema_version must be 1.")
    if run.get("bundle_partition") != "discovery":
        raise ValueError("Opik replay accepts discovery-only bundles.")
    _validate_holdout_aggregate(run)
    project_name = config.project_name or _required_text(run, "project_name")
    payloads = [
        _read_object(bundle_directory / "trace_payload.json"),
        _read_object(bundle_directory / "span_payload.json"),
        _read_object(bundle_directory / "trace_feedback.json"),
        _read_object(bundle_directory / "span_feedback.json"),
    ]
    _validate_payload_shape(payloads[0], "traces")
    _validate_payload_shape(payloads[1], "spans")
    _validate_payload_shape(payloads[2], "scores")
    _validate_payload_shape(payloads[3], "scores")
    trace_ids = _validate_discovery_entities(payloads[0], "traces")
    span_ids = _validate_discovery_entities(payloads[1], "spans")
    _validate_span_links(payloads[1], trace_ids, span_ids)
    _validate_feedback(payloads[2], trace_ids, "trace")
    _validate_feedback(payloads[3], span_ids, "span")
    payloads = [_with_project_name(payload, project_name) for payload in payloads]
    requests = (
        ("POST", "/v1/private/traces/batch", payloads[0]),
        ("POST", "/v1/private/spans/batch", payloads[1]),
        ("PUT", "/v1/private/traces/feedback-scores", payloads[2]),
        ("PUT", "/v1/private/spans/feedback-scores", payloads[3]),
    )
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if config.workspace:
        headers["Comet-Workspace-Name"] = config.workspace
    if config.bearer_token:
        headers["Authorization"] = f"Bearer {config.bearer_token}"
    elif config.basic_username and config.basic_password:
        token = base64.b64encode(
            f"{config.basic_username}:{config.basic_password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    request_count = 0
    for method, path, payload in requests:
        request_count += _send_request(
            method=method,
            path=path,
            payload=payload,
            config=config,
            headers=headers,
            sleep=sleep,
        )

    return ReplayResult(
        project_name=project_name,
        trace_count=len(_required_list(payloads[0], "traces")),
        span_count=len(_required_list(payloads[1], "spans")),
        trace_feedback_count=len(_required_list(payloads[2], "scores")),
        span_feedback_count=len(_required_list(payloads[3], "scores")),
        request_count=request_count,
    )


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as exc:
        raise ValueError(f"Bundle is missing {path.name}.") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Bundle file {path.name} is not valid JSON.") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Bundle file {path.name} must contain one JSON object.")
    return cast(dict[str, Any], value)


def _required_text(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise ValueError(f"run.json field {key} must be a non-empty string.")
    return item


def _required_list(value: dict[str, Any], key: str) -> list[Any]:
    item = value.get(key)
    if not isinstance(item, list):
        raise ValueError(f"Bundle payload field {key} must be a list.")
    return cast(list[Any], item)


def _validate_payload_shape(payload: dict[str, Any], collection: str) -> None:
    unexpected = sorted(set(payload) - {collection})
    if unexpected:
        raise ValueError(
            f"Bundle payload has unexpected fields: {', '.join(unexpected)}."
        )
    _required_list(payload, collection)


def _with_project_name(payload: dict[str, Any], project_name: str) -> dict[str, Any]:
    result = deepcopy(payload)
    for key in ("traces", "spans", "scores"):
        for item in _required_list(result, key) if key in result else []:
            if not isinstance(item, dict):
                raise ValueError(f"Bundle payload field {key} must contain objects.")
            cast(dict[str, Any], item)["project_name"] = project_name
    return result


def _validate_discovery_entities(payload: dict[str, Any], key: str) -> set[str]:
    ids: set[str] = set()
    for item in _required_list(payload, key):
        if not isinstance(item, dict):
            raise ValueError(f"Bundle payload field {key} must contain objects.")
        item = cast(dict[str, Any], item)
        item_id = _stable_uuid(item.get("id"), f"{key} id")
        if item_id in ids:
            raise ValueError(f"Bundle {key} must contain unique stable UUIDs.")
        ids.add(item_id)
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError(
                f"Opik replay accepts discovery-only {key}; "
                "every item must declare metadata.partition=discovery."
            )
        if cast(dict[str, Any], metadata).get("partition") != "discovery":
            raise ValueError(
                f"Opik replay accepts discovery-only {key}; "
                "every item must declare metadata.partition=discovery."
            )
    return ids


def _validate_holdout_aggregate(run: dict[str, Any]) -> None:
    if any(key.casefold().startswith("holdout") and key != "holdout" for key in run):
        raise ValueError(
            "run.json holdout data must contain aggregate scores only; "
            "holdout inputs, outputs, case details, and reasons are forbidden."
        )
    holdout = run.get("holdout")
    allowed_keys = {"case_count", "criteria", "score"}
    if (
        not isinstance(holdout, dict)
        or set(cast(dict[str, Any], holdout)) != allowed_keys
    ):
        raise ValueError(
            "run.json holdout data must contain aggregate scores only; "
            "holdout inputs, outputs, case details, and reasons are forbidden."
        )
    holdout = cast(dict[str, Any], holdout)
    case_count = holdout["case_count"]
    if (
        not isinstance(case_count, int)
        or isinstance(case_count, bool)
        or case_count < 0
    ):
        raise ValueError("run.json holdout aggregate case_count must be non-negative.")
    if not _finite_number(holdout["score"]):
        raise ValueError("run.json holdout aggregate score must be numeric.")
    criteria = holdout["criteria"]
    if not isinstance(criteria, dict) or not all(
        isinstance(name, str) and name and _finite_number(value)
        for name, value in cast(dict[object, object], criteria).items()
    ):
        raise ValueError("run.json holdout aggregate criteria values must be numeric.")


def _validate_span_links(
    payload: dict[str, Any], trace_ids: set[str], span_ids: set[str]
) -> None:
    for span in _required_list(payload, "spans"):
        if not isinstance(span, dict):
            raise ValueError("Bundle payload field spans must contain objects.")
        span = cast(dict[str, Any], span)
        trace_id = _stable_uuid(span.get("trace_id"), "span trace_id")
        if trace_id not in trace_ids:
            raise ValueError(
                "Every span must reference a discovery trace in the bundle."
            )
        parent_id = span.get("parent_span_id")
        if (
            parent_id is not None
            and _stable_uuid(parent_id, "parent span id") not in span_ids
        ):
            raise ValueError("Every parent span must exist in the discovery bundle.")


def _validate_feedback(
    payload: dict[str, Any], entity_ids: set[str], entity_name: str
) -> None:
    for score in _required_list(payload, "scores"):
        if not isinstance(score, dict):
            raise ValueError("Bundle payload field scores must contain objects.")
        score = cast(dict[str, Any], score)
        score_id = _stable_uuid(score.get("id"), f"{entity_name} feedback id")
        if score_id not in entity_ids:
            raise ValueError(
                f"{entity_name.capitalize()} feedback must reference only discovery "
                f"{entity_name}s in the bundle."
            )


def _stable_uuid(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Bundle {label} must be a stable UUID.")
    try:
        UUID(value)
    except ValueError as exc:
        raise ValueError(f"Bundle {label} must be a stable UUID.") from exc
    return value


def _finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _send_request(
    *,
    method: str,
    path: str,
    payload: dict[str, Any],
    config: ReplayConfig,
    headers: dict[str, str],
    sleep: Callable[[float], None],
) -> int:
    request = urllib.request.Request(
        f"{config.base_url.rstrip('/')}{path}",
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers=headers,
        method=method,
    )
    for attempt in range(config.max_retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=config.timeout_seconds):
                return attempt + 1
        except urllib.error.HTTPError as exc:
            detail = exc.read(500).decode("utf-8", errors="replace")
            if exc.code not in RETRYABLE_STATUSES or attempt == config.max_retries:
                raise OpikReplayError(
                    f"{method} {path} returned {exc.code}: {detail}"
                ) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == config.max_retries:
                raise OpikReplayError(
                    f"{method} {path} failed after {attempt + 1} attempts: {exc}"
                ) from exc
        sleep(config.retry_delay_seconds * (2**attempt))
    raise AssertionError("Retry loop must return or raise.")
