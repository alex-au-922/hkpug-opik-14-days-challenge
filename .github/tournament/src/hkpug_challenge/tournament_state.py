from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field

from .leaderboard import (
    AttemptReserved,
    AttemptScored,
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


class _Criteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    json_schema: float = Field(ge=0, le=10)
    citation_validity: float = Field(ge=0, le=10)
    evidence_coverage: float = Field(ge=0, le=10)
    escalation: float = Field(ge=0, le=10)
    answer_relevance: float = Field(ge=0, le=20)
    instruction_following: float = Field(ge=0, le=15)
    faithfulness: float = Field(ge=0, le=25)

    @property
    def deterministic(self) -> float:
        return round(
            self.json_schema
            + self.citation_validity
            + self.evidence_coverage
            + self.escalation,
            2,
        )


class _Partition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_count: int = Field(ge=1)
    score: float = Field(ge=0, le=100)
    criteria: _Criteria


class _Summary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(ge=1, le=1)
    team_id: str
    attempt: int = Field(ge=1, le=8)
    run_id: str
    model: str
    prompt_sha256: str
    overall_score: float = Field(ge=0, le=100)
    discovery: _Partition
    holdout: _Partition
    call_count: int = Field(ge=1, le=100)
    started_at: datetime
    completed_at: datetime


def reserve_submission(
    *,
    events_path: Path,
    team_id: str,
    display_name: str,
    prompt_sha256: str,
    head_sha: str,
    reserved_at: datetime,
    timezone: str = "Asia/Hong_Kong",
) -> AttemptReserved:
    """Reserve one idempotent attempt and atomically persist the private log."""

    events = _read_events(events_path)
    identity = make_submission_identity(
        team_id=team_id,
        prompt_sha256=prompt_sha256,
        head_sha=head_sha,
    )
    updated, reservation = reserve_attempt(
        events,
        team_id=team_id,
        display_name=display_name,
        submission_identity=identity,
        reserved_at=reserved_at,
        timezone=timezone,
    )
    _atomic_write(events_path, dump_events(updated), private=True)
    return reservation


def publish_score(
    *,
    events_path: Path,
    summary_path: Path,
    submission_identity: str,
    challenge: Challenge,
    leaderboard_path: Path,
) -> PublicLeaderboard:
    """Append one idempotent score and write the derived public leaderboard."""

    events = _read_events(events_path)
    reservation = next(
        (
            event
            for event in events
            if isinstance(event, AttemptReserved)
            and event.submission_identity == submission_identity
        ),
        None,
    )
    if reservation is None:
        raise ValueError("No reservation exists for this submission identity.")
    summary = _Summary.model_validate_json(summary_path.read_text(encoding="utf-8"))
    if summary.team_id != reservation.team_id:
        raise ValueError("Score summary team does not match its reservation.")
    if summary.attempt != reservation.attempt:
        raise ValueError("Score summary attempt does not match its reservation.")
    if summary.completed_at < summary.started_at:
        raise ValueError("Score summary completion precedes its start.")

    score = _score(summary)
    if abs(score.overall - summary.overall_score) > 0.001:
        raise ValueError("Score summary overall score is inconsistent.")
    updated = record_score(
        events,
        submission_identity=submission_identity,
        score=score,
        completed_at=summary.completed_at,
    )
    board = build_public_leaderboard(
        updated,
        challenge=challenge,
        generated_at=summary.completed_at,
    )
    _atomic_write(events_path, dump_events(updated), private=True)
    _atomic_write(leaderboard_path, dump_public_leaderboard(board), private=False)
    return board


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    reserve_parser = subparsers.add_parser("reserve")
    reserve_parser.add_argument("--events", required=True, type=Path)
    reserve_parser.add_argument("--team-id", required=True)
    reserve_parser.add_argument("--display-name", required=True)
    reserve_parser.add_argument("--prompt-sha256", required=True)
    reserve_parser.add_argument("--head-sha", required=True)
    reserve_parser.add_argument("--reserved-at", required=True, type=_parse_datetime)
    reserve_parser.add_argument("--timezone", default="Asia/Hong_Kong")
    reserve_parser.add_argument("--output", required=True, type=Path)

    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--events", required=True, type=Path)
    publish_parser.add_argument("--summary", required=True, type=Path)
    publish_parser.add_argument("--submission-identity", required=True)
    publish_parser.add_argument("--leaderboard", required=True, type=Path)
    publish_parser.add_argument("--challenge-name", required=True)
    publish_parser.add_argument("--starts-at", required=True, type=_parse_datetime)
    publish_parser.add_argument("--ends-at", required=True, type=_parse_datetime)
    publish_parser.add_argument("--timezone", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        if args.command == "reserve":
            reservation = reserve_submission(
                events_path=args.events,
                team_id=args.team_id,
                display_name=args.display_name,
                prompt_sha256=args.prompt_sha256,
                head_sha=args.head_sha,
                reserved_at=args.reserved_at,
                timezone=args.timezone,
            )
            _atomic_write(
                args.output,
                json.dumps(
                    {
                        "team_id": reservation.team_id,
                        "attempt": reservation.attempt,
                        "submission_identity": reservation.submission_identity,
                        "already_scored": any(
                            isinstance(event, AttemptScored)
                            and event.submission_identity
                            == reservation.submission_identity
                            for event in _read_events(args.events)
                        ),
                    },
                    sort_keys=True,
                )
                + "\n",
                private=True,
            )
            print(f"Reserved attempt {reservation.attempt} for {reservation.team_id}.")
            return 0

        board = publish_score(
            events_path=args.events,
            summary_path=args.summary,
            submission_identity=args.submission_identity,
            challenge=Challenge(
                name=args.challenge_name,
                starts_at=args.starts_at,
                ends_at=args.ends_at,
                timezone=args.timezone,
            ),
            leaderboard_path=args.leaderboard,
        )
        print(
            json.dumps(
                {
                    "team_count": len(board.teams),
                    "generated_at": board.generated_at.isoformat(),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _score(summary: _Summary) -> Score:
    discovery = summary.discovery.criteria
    holdout = summary.holdout.criteria

    def weighted(discovery_value: float, holdout_value: float) -> float:
        return round(discovery_value * 0.75 + holdout_value * 0.25, 2)

    return Score(
        discovery=summary.discovery.score,
        holdout=summary.holdout.score,
        criteria=CriterionScores(
            deterministic=weighted(
                discovery.deterministic,
                holdout.deterministic,
            ),
            answer_relevance=weighted(
                discovery.answer_relevance,
                holdout.answer_relevance,
            ),
            instruction_following=weighted(
                discovery.instruction_following,
                holdout.instruction_following,
            ),
            faithfulness=weighted(
                discovery.faithfulness,
                holdout.faithfulness,
            ),
        ),
    )


def _read_events(path: Path) -> tuple[LeaderboardEvent, ...]:
    if not path.exists():
        return ()
    return load_events(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, content: str, *, private: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(content)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    if private and os.name != "nt":
        temporary_path.chmod(0o600)
    os.replace(temporary_path, path)


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Timestamp must include a timezone offset.")
    return parsed
