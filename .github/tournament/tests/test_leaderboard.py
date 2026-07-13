from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import cast

import pytest
from pydantic import ValidationError

from hkpug_challenge.leaderboard import (
    MAX_DAILY_ATTEMPTS,
    MAX_ATTEMPTS,
    AttemptLimitExceeded,
    AttemptReserved,
    Challenge,
    CriterionScores,
    LeaderboardEvent,
    PublicLeaderboard,
    Score,
    build_public_leaderboard,
    dump_events,
    dump_public_leaderboard,
    load_events,
    make_submission_identity,
    record_score,
    reserve_attempt,
)


NOW = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)


def test_reservations_are_idempotent_and_limited_to_eight_per_team() -> None:
    events: tuple[LeaderboardEvent, ...] = ()
    first_identity = make_submission_identity(
        team_id="group-01",
        prompt_sha256=_digest("prompt-1"),
        head_sha="1" * 40,
    )
    events, first = reserve_attempt(
        events,
        team_id="group-01",
        display_name="Group 01",
        submission_identity=first_identity,
        reserved_at=NOW,
    )

    replayed_events, replayed = reserve_attempt(
        events,
        team_id="group-01",
        display_name="Group 01",
        submission_identity=first_identity,
        reserved_at=NOW + timedelta(minutes=1),
    )

    assert replayed_events is events
    assert replayed == first
    assert first.attempt == 1

    for attempt in range(2, MAX_ATTEMPTS + 1):
        identity = make_submission_identity(
            team_id="group-01",
            prompt_sha256=_digest(f"prompt-{attempt}"),
            head_sha=f"{attempt:040x}",
        )
        events, reservation = reserve_attempt(
            events,
            team_id="group-01",
            display_name="Group 01",
            submission_identity=identity,
            reserved_at=NOW + timedelta(days=attempt - 1),
        )
        assert reservation.attempt == attempt

    with pytest.raises(AttemptLimitExceeded, match="eight attempts"):
        reserve_attempt(
            events,
            team_id="group-01",
            display_name="Group 01",
            submission_identity=make_submission_identity(
                team_id="group-01",
                prompt_sha256=_digest("prompt-9"),
                head_sha="9" * 40,
            ),
            reserved_at=NOW + timedelta(days=8),
        )

    reservations = [event for event in events if isinstance(event, AttemptReserved)]
    assert len(reservations) == MAX_ATTEMPTS


def test_all_eight_reservations_may_be_used_in_one_hong_kong_day() -> None:
    events: tuple[LeaderboardEvent, ...] = ()
    first_day = datetime(2026, 7, 12, 15, 0, tzinfo=timezone.utc)
    assert MAX_DAILY_ATTEMPTS == MAX_ATTEMPTS == 8

    for sequence in range(1, MAX_DAILY_ATTEMPTS + 1):
        events, reservation = reserve_attempt(
            events,
            team_id="group-01",
            display_name="Group 01",
            submission_identity=make_submission_identity(
                team_id="group-01",
                prompt_sha256=_digest(f"daily-{sequence}"),
                head_sha=f"{sequence:040x}",
            ),
            reserved_at=first_day + timedelta(minutes=sequence * 10),
            timezone="Asia/Hong_Kong",
        )
        assert reservation.attempt == sequence

    assert len(events) == MAX_ATTEMPTS


def test_scoring_appends_once_and_conflicting_replays_fail() -> None:
    events, reservation = _reserve((), team_id="group-01", sequence=1)
    score = _score(discovery=80, holdout=60)

    scored = record_score(
        events,
        submission_identity=reservation.submission_identity,
        score=score,
        completed_at=NOW + timedelta(minutes=5),
    )
    replayed = record_score(
        scored,
        submission_identity=reservation.submission_identity,
        score=score,
        completed_at=NOW + timedelta(minutes=6),
    )

    assert scored[: len(events)] == events
    assert len(scored) == len(events) + 1
    assert replayed is scored

    with pytest.raises(ValueError, match="different score"):
        record_score(
            scored,
            submission_identity=reservation.submission_identity,
            score=_score(discovery=40, holdout=40),
            completed_at=NOW + timedelta(minutes=7),
        )

    with pytest.raises(ValueError, match="No reservation"):
        record_score(
            scored,
            submission_identity="f" * 64,
            score=score,
            completed_at=NOW + timedelta(minutes=8),
        )


def test_score_enforces_weighting_and_criterion_contributions() -> None:
    score = _score(discovery=80, holdout=60)

    assert score.overall == 75.0

    with pytest.raises(ValueError, match="criterion contributions"):
        Score(
            discovery=80,
            holdout=60,
            criteria=CriterionScores(
                deterministic=20,
                answer_relevance=10,
                instruction_following=5,
                faithfulness=10,
            ),
        )

    with pytest.raises(ValueError, match="between 0 and 100"):
        Score(
            discovery=101,
            holdout=60,
            criteria=CriterionScores(
                deterministic=40,
                answer_relevance=20,
                instruction_following=15,
                faithfulness=25,
            ),
        )


def test_public_board_selects_best_latest_and_orders_ties_deterministically() -> None:
    events: tuple[LeaderboardEvent, ...] = ()
    events, beta = _reserve(events, team_id="group-02", sequence=1)
    events = record_score(
        events,
        submission_identity=beta.submission_identity,
        score=_score(discovery=80, holdout=80),
        completed_at=NOW + timedelta(minutes=2),
    )
    events, alpha_first = _reserve(events, team_id="group-01", sequence=1)
    events = record_score(
        events,
        submission_identity=alpha_first.submission_identity,
        score=_score(discovery=80, holdout=80),
        completed_at=NOW + timedelta(minutes=2),
    )
    events, alpha_second = _reserve(events, team_id="group-01", sequence=2)
    events = record_score(
        events,
        submission_identity=alpha_second.submission_identity,
        score=_score(discovery=70, holdout=70),
        completed_at=NOW + timedelta(minutes=4),
    )

    board = build_public_leaderboard(
        events,
        challenge=_challenge(),
        generated_at=NOW + timedelta(hours=1),
    )

    assert [team.team_id for team in board.teams] == ["group-01", "group-02"]
    assert [team.rank for team in board.teams] == [1, 2]
    alpha = board.teams[0]
    assert alpha.best.attempt == 1
    assert alpha.best.overall_score == 80.0
    assert alpha.latest.attempt == 2
    assert alpha.latest.overall_score == 70.0
    assert alpha.attempts_used == 2
    assert alpha.attempts_remaining == 6
    assert [run.attempt for run in alpha.runs] == [1, 2]


def test_public_json_is_strict_valid_and_contains_no_submission_secrets() -> None:
    events, reservation = _reserve((), team_id="group-01", sequence=1)
    events = record_score(
        events,
        submission_identity=reservation.submission_identity,
        score=_score(discovery=80, holdout=60),
        completed_at=NOW + timedelta(minutes=5),
    )
    board = build_public_leaderboard(
        events,
        challenge=_challenge(),
        generated_at=NOW + timedelta(hours=1),
    )

    encoded = dump_public_leaderboard(board)
    decoded = cast(dict[str, object], json.loads(encoded))
    reparsed = PublicLeaderboard.model_validate_json(encoded)

    assert reparsed == board
    assert set(decoded) == {"schema_version", "generated_at", "challenge", "teams"}
    assert decoded["schema_version"] == 1
    assert _challenge_payload(decoded)["weights"] == {
        "discovery": 0.75,
        "holdout": 0.25,
    }
    serialized = encoded.lower()
    for forbidden in (
        "prompt",
        "context",
        "private_case",
        "question",
        "reference",
        "submission_identity",
        "head_sha",
    ):
        assert forbidden not in serialized

    decoded["unexpected"] = True
    with pytest.raises(ValidationError):
        PublicLeaderboard.model_validate(decoded)


def test_event_log_round_trips_without_losing_reservations_or_scores() -> None:
    events, reservation = _reserve((), team_id="group-01", sequence=1)
    events = record_score(
        events,
        submission_identity=reservation.submission_identity,
        score=_score(discovery=80, holdout=60),
        completed_at=NOW + timedelta(minutes=5),
    )

    encoded = dump_events(events)

    assert load_events(encoded) == events
    assert encoded.endswith("\n")
    assert "attempt_reserved" in encoded
    assert "attempt_scored" in encoded


def test_event_log_rejects_unknown_fields_and_invalid_order() -> None:
    events, reservation = _reserve((), team_id="group-01", sequence=1)
    reservation_payload = json.loads(dump_events(events).splitlines()[0])
    reservation_payload["prompt"] = "must not be accepted"

    with pytest.raises(ValueError, match="exactly"):
        load_events(json.dumps(reservation_payload) + "\n")

    score_only = {
        "type": "attempt_scored",
        "submission_identity": reservation.submission_identity,
        "attempt": 1,
        "score": {
            "discovery": 80,
            "holdout": 60,
            "criteria": {
                "deterministic": 30,
                "answer_relevance": 15,
                "instruction_following": 10,
                "faithfulness": 20,
            },
        },
        "completed_at": (NOW + timedelta(minutes=5)).isoformat(),
    }
    with pytest.raises(ValueError, match="follow its reservation"):
        load_events(json.dumps(score_only) + "\n")


def _reserve(
    events: tuple[LeaderboardEvent, ...], *, team_id: str, sequence: int
) -> tuple[tuple[LeaderboardEvent, ...], AttemptReserved]:
    identity = make_submission_identity(
        team_id=team_id,
        prompt_sha256=_digest(f"{team_id}-prompt-{sequence}"),
        head_sha=f"{sequence:040x}",
    )
    return reserve_attempt(
        events,
        team_id=team_id,
        display_name=team_id.replace("group-", "Group "),
        submission_identity=identity,
        reserved_at=NOW + timedelta(seconds=sequence),
    )


def _score(*, discovery: float, holdout: float) -> Score:
    overall = round(discovery * 0.75 + holdout * 0.25, 2)
    return Score(
        discovery=discovery,
        holdout=holdout,
        criteria=CriterionScores(
            deterministic=round(overall * 0.40, 2),
            answer_relevance=round(overall * 0.20, 2),
            instruction_following=round(overall * 0.15, 2),
            faithfulness=round(overall * 0.25, 2),
        ),
    )


def _challenge() -> Challenge:
    return Challenge(
        name="HKPUG Opik 14-Day Challenge",
        starts_at=NOW - timedelta(days=1),
        ends_at=NOW + timedelta(days=13),
        timezone="Asia/Hong_Kong",
    )


def _digest(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _challenge_payload(payload: dict[str, object]) -> dict[str, object]:
    challenge = payload["challenge"]
    assert isinstance(challenge, dict)
    return cast(dict[str, object], challenge)
