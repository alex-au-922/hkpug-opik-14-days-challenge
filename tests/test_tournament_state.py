from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path

from hkpug_challenge.leaderboard import Challenge, load_events
from hkpug_challenge.tournament_state import publish_score, reserve_submission


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def test_reservation_file_is_append_only_and_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"

    first = reserve_submission(
        events_path=path,
        team_id="group-01",
        display_name="Group 01",
        prompt_sha256=_digest("prompt"),
        head_sha="1" * 40,
        reserved_at=NOW,
    )
    replay = reserve_submission(
        events_path=path,
        team_id="group-01",
        display_name="Group 01",
        prompt_sha256=_digest("prompt"),
        head_sha="1" * 40,
        reserved_at=NOW + timedelta(minutes=1),
    )

    assert first == replay
    assert first.attempt == 1
    assert len(load_events(path.read_text(encoding="utf-8"))) == 1


def test_publish_score_appends_event_and_writes_public_board(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    board_path = tmp_path / "dashboard" / "leaderboard.json"
    summary_path = tmp_path / "summary.json"
    reservation = reserve_submission(
        events_path=events_path,
        team_id="group-01",
        display_name="Group 01",
        prompt_sha256=_digest("prompt"),
        head_sha="1" * 40,
        reserved_at=NOW,
    )
    summary_path.write_text(
        json.dumps(_summary(prompt_sha256=_digest("prompt"))),
        encoding="utf-8",
    )

    board = publish_score(
        events_path=events_path,
        summary_path=summary_path,
        submission_identity=reservation.submission_identity,
        challenge=_challenge(),
        leaderboard_path=board_path,
    )

    assert len(load_events(events_path.read_text(encoding="utf-8"))) == 2
    assert board.teams[0].best.overall_score == 75.0
    assert board.teams[0].attempts_used == 1
    public_text = board_path.read_text(encoding="utf-8").lower()
    assert "submission_identity" not in public_text
    assert "prompt_sha256" not in public_text
    assert "question" not in public_text


def _summary(*, prompt_sha256: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "team_id": "group-01",
        "attempt": 1,
        "run_id": "run-001",
        "model": "accounts/fireworks/models/deepseek-v4-flash",
        "prompt_sha256": prompt_sha256,
        "overall_score": 75.0,
        "discovery": {
            "case_count": 40,
            "score": 80.0,
            "criteria": {
                "json_schema": 8.0,
                "citation_validity": 8.0,
                "evidence_coverage": 8.0,
                "escalation": 8.0,
                "answer_relevance": 16.0,
                "instruction_following": 12.0,
                "faithfulness": 20.0,
            },
        },
        "holdout": {
            "case_count": 10,
            "score": 60.0,
            "criteria": {
                "json_schema": 6.0,
                "citation_validity": 6.0,
                "evidence_coverage": 6.0,
                "escalation": 6.0,
                "answer_relevance": 12.0,
                "instruction_following": 9.0,
                "faithfulness": 15.0,
            },
        },
        "call_count": 100,
        "started_at": "2026-07-12T12:00:00.000Z",
        "completed_at": "2026-07-12T12:05:00.000Z",
    }


def _challenge() -> Challenge:
    return Challenge(
        name="HKPUG Opik 14-Day Challenge",
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=13),
        timezone="Asia/Hong_Kong",
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()
