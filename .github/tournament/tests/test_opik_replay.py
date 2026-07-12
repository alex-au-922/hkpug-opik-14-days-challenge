from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections import deque
from collections.abc import Generator
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid5

import pytest

from hkpug_challenge.opik_replay import (
    OpikReplayError,
    ReplayConfig,
    ReplayResult,
    replay_bundle,
)


TRACE_ID = str(uuid5(NAMESPACE_URL, "hkpug/discovery/DISC-001/trace"))
SPAN_ID = str(uuid5(NAMESPACE_URL, "hkpug/discovery/DISC-001/span/answer"))


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    path: str
    headers: dict[str, str]
    payload: dict[str, Any]


@dataclass(frozen=True)
class ResponseSpec:
    status: int = 204
    body: bytes = b""


class RecordingServer(ThreadingHTTPServer):
    def __init__(self, responses: tuple[ResponseSpec, ...] = ()) -> None:
        super().__init__(("127.0.0.1", 0), RecordingHandler)
        self.requests: list[RecordedRequest] = []
        self.responses = deque(responses)

    @property
    def base_url(self) -> str:
        host, port = cast(tuple[str, int], self.server_address)
        return f"http://{host}:{port}/api"


class RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self._record()

    def do_PUT(self) -> None:
        self._record()

    def _record(self) -> None:
        server = cast(RecordingServer, self.server)
        length = int(self.headers.get("Content-Length", "0"))
        payload = cast(dict[str, Any], json.loads(self.rfile.read(length)))
        server.requests.append(
            RecordedRequest(
                method=self.command,
                path=self.path,
                headers={key: value for key, value in self.headers.items()},
                payload=payload,
            )
        )
        response = server.responses.popleft() if server.responses else ResponseSpec()
        self.send_response(response.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(response.body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


@pytest.fixture
def recording_server() -> Generator[RecordingServer, None, None]:
    server = RecordingServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_replay_sends_discovery_payloads_in_opik_dependency_order(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)

    result = replay_bundle(
        bundle,
        ReplayConfig(base_url=recording_server.base_url, workspace="team-07"),
        sleep=lambda _seconds: None,
    )

    assert result == ReplayResult(
        project_name="hkpug-team-07-run-03",
        trace_count=1,
        span_count=1,
        trace_feedback_count=1,
        span_feedback_count=1,
        request_count=4,
    )
    assert [
        (request.method, request.path) for request in recording_server.requests
    ] == [
        ("POST", "/api/v1/private/traces/batch"),
        ("POST", "/api/v1/private/spans/batch"),
        ("PUT", "/api/v1/private/traces/feedback-scores"),
        ("PUT", "/api/v1/private/spans/feedback-scores"),
    ]
    assert all(
        request.headers["Comet-Workspace-Name"] == "team-07"
        for request in recording_server.requests
    )
    assert recording_server.requests[0].payload["traces"][0]["id"] == TRACE_ID
    assert recording_server.requests[1].payload["spans"][0]["id"] == SPAN_ID


@pytest.mark.parametrize(
    ("filename", "collection"),
    [("trace_payload.json", "traces"), ("span_payload.json", "spans")],
)
def test_replay_rejects_holdout_entity_before_any_http_request(
    tmp_path: Path,
    recording_server: RecordingServer,
    filename: str,
    collection: str,
) -> None:
    bundle = write_bundle(tmp_path)
    payload_path = bundle / filename
    payload = cast(dict[str, Any], json.loads(payload_path.read_text(encoding="utf-8")))
    payload[collection][0]["metadata"]["partition"] = "holdout"
    payload_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="discovery-only"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_feedback_for_an_entity_outside_discovery_bundle(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    feedback_path = bundle / "trace_feedback.json"
    payload = cast(
        dict[str, Any], json.loads(feedback_path.read_text(encoding="utf-8"))
    )
    payload["scores"][0]["id"] = str(
        uuid5(NAMESPACE_URL, "hkpug/holdout/HOLD-001/trace")
    )
    feedback_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="feedback.*discovery"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_non_uuid_entity_ids_before_networking(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    trace_path = bundle / "trace_payload.json"
    payload = cast(dict[str, Any], json.loads(trace_path.read_text(encoding="utf-8")))
    payload["traces"][0]["id"] = "generated-at-import-time"
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="stable UUID"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_hidden_holdout_payload_fields(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    trace_path = bundle / "trace_payload.json"
    payload = cast(dict[str, Any], json.loads(trace_path.read_text(encoding="utf-8")))
    payload["holdout_outputs"] = [{"answer": "must remain private"}]
    trace_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="unexpected.*holdout_outputs"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input", {"question": "private holdout question"}),
        ("output", {"answer": "private holdout answer"}),
        ("reasons", {"faithfulness": "private judge reason"}),
    ],
)
def test_replay_rejects_holdout_case_details_in_run_metadata(
    tmp_path: Path,
    recording_server: RecordingServer,
    field: str,
    value: object,
) -> None:
    bundle = write_bundle(tmp_path)
    run_path = bundle / "run.json"
    run = cast(dict[str, Any], json.loads(run_path.read_text(encoding="utf-8")))
    run["holdout"][field] = value
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match="holdout.*aggregate"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_holdout_details_disguised_as_top_level_run_fields(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    run_path = bundle / "run.json"
    run = cast(dict[str, Any], json.loads(run_path.read_text(encoding="utf-8")))
    run["holdout_inputs"] = [{"question": "private holdout question"}]
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match="holdout.*aggregate"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_holdout_reason_nested_inside_aggregate_criteria(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    run_path = bundle / "run.json"
    run = cast(dict[str, Any], json.loads(run_path.read_text(encoding="utf-8")))
    run["holdout"]["criteria"]["faithfulness"] = {
        "score": 21.0,
        "reason": "private judge reason",
    }
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match="aggregate.*numeric"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_replay_rejects_unsupported_bundle_schema_before_networking(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    run_path = bundle / "run.json"
    run = cast(dict[str, Any], json.loads(run_path.read_text(encoding="utf-8")))
    run["schema_version"] = 2
    run_path.write_text(json.dumps(run), encoding="utf-8")

    with pytest.raises(ValueError, match="schema_version must be 1"):
        replay_bundle(
            bundle,
            ReplayConfig(base_url=recording_server.base_url),
            sleep=lambda _seconds: None,
        )

    assert recording_server.requests == []


def test_importing_the_same_bundle_twice_reuses_identical_ids_and_payloads(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path)
    config = ReplayConfig(base_url=recording_server.base_url)

    replay_bundle(bundle, config, sleep=lambda _seconds: None)
    replay_bundle(bundle, config, sleep=lambda _seconds: None)

    first_import = recording_server.requests[:4]
    second_import = recording_server.requests[4:]
    assert [request.payload for request in first_import] == [
        request.payload for request in second_import
    ]
    assert first_import[0].payload["traces"][0]["id"] == TRACE_ID
    assert first_import[1].payload["spans"][0]["id"] == SPAN_ID


def test_replay_retries_transient_response_then_continues_in_order(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    recording_server.responses.extend(
        [
            ResponseSpec(503, b'{"error":"temporarily busy"}'),
            ResponseSpec(),
            ResponseSpec(),
            ResponseSpec(),
            ResponseSpec(),
        ]
    )
    delays: list[float] = []

    result = replay_bundle(
        write_bundle(tmp_path),
        ReplayConfig(
            base_url=recording_server.base_url,
            max_retries=2,
            retry_delay_seconds=0.01,
        ),
        sleep=delays.append,
    )

    assert result.request_count == 5
    assert delays == [0.01]
    assert [request.path for request in recording_server.requests] == [
        "/api/v1/private/traces/batch",
        "/api/v1/private/traces/batch",
        "/api/v1/private/spans/batch",
        "/api/v1/private/traces/feedback-scores",
        "/api/v1/private/spans/feedback-scores",
    ]


def test_replay_stops_after_bounded_transient_retries_with_visible_error(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    recording_server.responses.extend(
        [ResponseSpec(503, b'{"error":"still busy"}')] * 3
    )

    with pytest.raises(
        OpikReplayError,
        match=r"POST /v1/private/traces/batch returned 503.*still busy",
    ):
        replay_bundle(
            write_bundle(tmp_path),
            ReplayConfig(
                base_url=recording_server.base_url,
                max_retries=2,
                retry_delay_seconds=0,
            ),
            sleep=lambda _seconds: None,
        )

    assert len(recording_server.requests) == 3


def test_replay_does_not_retry_non_transient_failure_and_shows_response(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    recording_server.responses.append(
        ResponseSpec(422, b'{"error":"invalid trace schema"}')
    )

    with pytest.raises(
        OpikReplayError,
        match=r"POST /v1/private/traces/batch returned 422.*invalid trace schema",
    ):
        replay_bundle(
            write_bundle(tmp_path),
            ReplayConfig(base_url=recording_server.base_url, max_retries=2),
            sleep=lambda _seconds: None,
        )

    assert len(recording_server.requests) == 1


def test_replay_supports_basic_auth_without_putting_password_in_cli(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    replay_bundle(
        write_bundle(tmp_path),
        ReplayConfig(
            base_url=recording_server.base_url,
            basic_username="team-07",
            basic_password="secret",
        ),
        sleep=lambda _seconds: None,
    )

    assert all(
        request.headers["Authorization"] == "Basic dGVhbS0wNzpzZWNyZXQ="
        for request in recording_server.requests
    )


def test_replay_config_enforces_hard_retry_ceiling() -> None:
    with pytest.raises(ValueError, match="max_retries must be between 0 and 5"):
        ReplayConfig(max_retries=6)


def test_import_cli_completes_full_replay_and_prints_machine_readable_summary(
    tmp_path: Path, recording_server: RecordingServer
) -> None:
    bundle = write_bundle(tmp_path, case_count=40)
    repository = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["OPIK_API_KEY"] = "recording-server-token"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/import_opik.py",
            "--bundle",
            str(bundle),
            "--base-url",
            recording_server.base_url,
            "--workspace",
            "team-07",
            "--max-retries",
            "0",
        ],
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "project_name": "hkpug-team-07-run-03",
        "request_count": 4,
        "span_count": 40,
        "span_feedback_count": 40,
        "trace_count": 40,
        "trace_feedback_count": 40,
    }
    assert [request.path for request in recording_server.requests] == [
        "/api/v1/private/traces/batch",
        "/api/v1/private/spans/batch",
        "/api/v1/private/traces/feedback-scores",
        "/api/v1/private/spans/feedback-scores",
    ]
    assert all(
        request.headers["Authorization"] == "Bearer recording-server-token"
        for request in recording_server.requests
    )


def write_bundle(directory: Path, *, case_count: int = 1) -> Path:
    case_numbers = range(1, case_count + 1)
    payloads: dict[str, dict[str, Any]] = {
        "trace_payload.json": {"traces": [_trace(index) for index in case_numbers]},
        "span_payload.json": {"spans": [_span(index) for index in case_numbers]},
        "trace_feedback.json": {
            "scores": [_trace_feedback(index) for index in case_numbers]
        },
        "span_feedback.json": {
            "scores": [_span_feedback(index) for index in case_numbers]
        },
        "run.json": {
            "schema_version": 1,
            "bundle_partition": "discovery",
            "run_id": "run-03",
            "team_id": "team-07",
            "project_name": "hkpug-team-07-run-03",
            "discovery": {"case_count": case_count, "score": 89.5},
            "holdout": {
                "case_count": 1,
                "score": 82.0,
                "criteria": {"faithfulness": 21.0},
            },
        },
    }
    for name, payload in payloads.items():
        (directory / name).write_text(json.dumps(payload), encoding="utf-8")
    return directory


def _trace(index: int) -> dict[str, Any]:
    case_id = f"DISC-{index:03}"
    return {
        "id": _trace_id(index),
        "project_name": "hkpug-team-07-run-03",
        "name": f"{case_id} answer",
        "start_time": "2026-07-12T00:00:00.000Z",
        "end_time": "2026-07-12T00:00:01.000Z",
        "input": {"question": "What action is supported?"},
        "output": {"answer": "Escalate for review."},
        "metadata": {"partition": "discovery", "case_id": case_id},
        "source": "sdk",
    }


def _span(index: int) -> dict[str, Any]:
    case_id = f"DISC-{index:03}"
    return {
        "id": _span_id(index),
        "trace_id": _trace_id(index),
        "project_name": "hkpug-team-07-run-03",
        "name": "answer",
        "type": "llm",
        "start_time": "2026-07-12T00:00:00.100Z",
        "end_time": "2026-07-12T00:00:00.900Z",
        "input": {"question": "What action is supported?"},
        "output": {"answer": "Escalate for review."},
        "metadata": {"partition": "discovery", "case_id": case_id},
        "source": "sdk",
    }


def _trace_feedback(index: int) -> dict[str, Any]:
    return {
        "id": _trace_id(index),
        "project_name": "hkpug-team-07-run-03",
        "name": "faithfulness",
        "value": 0.91,
        "reason": "The answer uses the supplied evidence.",
        "source": "sdk",
    }


def _span_feedback(index: int) -> dict[str, Any]:
    return {
        "id": _span_id(index),
        "project_name": "hkpug-team-07-run-03",
        "name": "instruction_following",
        "value": 0.88,
        "reason": "The output follows the requested contract.",
        "source": "sdk",
    }


def _trace_id(index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"hkpug/discovery/DISC-{index:03}/trace"))


def _span_id(index: int) -> str:
    return str(uuid5(NAMESPACE_URL, f"hkpug/discovery/DISC-{index:03}/span/answer"))
