from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Literal, TypeAlias, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    model_validator,
)


MAX_ATTEMPTS = 8
MAX_DAILY_ATTEMPTS = 2
DISCOVERY_WEIGHT = 0.75
HOLDOUT_WEIGHT = 0.25
_TEAM_ID = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?")
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_HEX_COMMIT = re.compile(r"[0-9a-f]{40}(?:[0-9a-f]{24})?")


class AttemptLimitExceeded(RuntimeError):
    """Raised before work starts when a team has reserved all eight attempts."""


@dataclass(frozen=True)
class CriterionScores:
    """Weighted score contributions; all four fields add up to the official score."""

    deterministic: float
    answer_relevance: float
    instruction_following: float
    faithfulness: float

    def __post_init__(self) -> None:
        limits = {
            "deterministic": 40.0,
            "answer_relevance": 20.0,
            "instruction_following": 15.0,
            "faithfulness": 25.0,
        }
        for name, limit in limits.items():
            value = getattr(self, name)
            _require_finite_score(value, name=name, maximum=limit)

    @property
    def total(self) -> float:
        return round(
            self.deterministic
            + self.answer_relevance
            + self.instruction_following
            + self.faithfulness,
            2,
        )


@dataclass(frozen=True)
class Score:
    """One official result with the fixed 75/25 partition weighting."""

    discovery: float
    holdout: float
    criteria: CriterionScores

    def __post_init__(self) -> None:
        _require_finite_score(self.discovery, name="discovery", maximum=100.0)
        _require_finite_score(self.holdout, name="holdout", maximum=100.0)
        if abs(self.criteria.total - self.overall) > 0.02:
            raise ValueError(
                "Weighted criterion contributions must add up to the official score."
            )

    @property
    def overall(self) -> float:
        return round(
            self.discovery * DISCOVERY_WEIGHT + self.holdout * HOLDOUT_WEIGHT,
            2,
        )


@dataclass(frozen=True)
class Challenge:
    name: str
    starts_at: datetime
    ends_at: datetime
    timezone: str

    def __post_init__(self) -> None:
        if not self.name.strip() or self.name != self.name.strip():
            raise ValueError("Challenge name must be a trimmed non-empty string.")
        _require_aware(self.starts_at, name="starts_at")
        _require_aware(self.ends_at, name="ends_at")
        if self.ends_at <= self.starts_at:
            raise ValueError("Challenge end must be after its start.")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                "Challenge timezone must be a valid IANA timezone."
            ) from exc


@dataclass(frozen=True)
class AttemptReserved:
    submission_identity: str
    team_id: str
    display_name: str
    attempt: int
    reserved_at: datetime

    def __post_init__(self) -> None:
        _require_submission_identity(self.submission_identity)
        _require_team(self.team_id, self.display_name)
        if not 1 <= self.attempt <= MAX_ATTEMPTS:
            raise ValueError("Attempt number must be between 1 and 8.")
        _require_aware(self.reserved_at, name="reserved_at")


@dataclass(frozen=True)
class AttemptScored:
    submission_identity: str
    attempt: int
    score: Score
    completed_at: datetime

    def __post_init__(self) -> None:
        _require_submission_identity(self.submission_identity)
        if not 1 <= self.attempt <= MAX_ATTEMPTS:
            raise ValueError("Attempt number must be between 1 and 8.")
        _require_aware(self.completed_at, name="completed_at")


LeaderboardEvent: TypeAlias = AttemptReserved | AttemptScored


class _PublicModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PublicWeights(_PublicModel):
    discovery: float = Field(default=DISCOVERY_WEIGHT, ge=0.75, le=0.75)
    holdout: float = Field(default=HOLDOUT_WEIGHT, ge=0.25, le=0.25)


class PublicCriterionScores(_PublicModel):
    deterministic: float = Field(ge=0, le=40)
    answer_relevance: float = Field(ge=0, le=20)
    instruction_following: float = Field(ge=0, le=15)
    faithfulness: float = Field(ge=0, le=25)

    @property
    def total(self) -> float:
        return round(
            self.deterministic
            + self.answer_relevance
            + self.instruction_following
            + self.faithfulness,
            2,
        )


class PublicRun(_PublicModel):
    attempt: StrictInt = Field(ge=1, le=MAX_ATTEMPTS)
    completed_at: datetime
    overall_score: float = Field(ge=0, le=100)
    discovery_score: float = Field(ge=0, le=100)
    holdout_score: float = Field(ge=0, le=100)
    criteria: PublicCriterionScores

    @model_validator(mode="after")
    def validate_score_contract(self) -> PublicRun:
        _require_aware(self.completed_at, name="completed_at")
        expected = round(
            self.discovery_score * DISCOVERY_WEIGHT
            + self.holdout_score * HOLDOUT_WEIGHT,
            2,
        )
        if abs(self.overall_score - expected) > 0.001:
            raise ValueError("Overall score must use the 75/25 partition weighting.")
        if abs(self.criteria.total - self.overall_score) > 0.02:
            raise ValueError(
                "Criterion contributions must add up to the overall score."
            )
        return self


class PublicTeam(_PublicModel):
    rank: StrictInt = Field(ge=1)
    team_id: str
    display_name: str
    attempts_used: StrictInt = Field(ge=1, le=MAX_ATTEMPTS)
    attempts_remaining: StrictInt = Field(ge=0, le=MAX_ATTEMPTS - 1)
    best: PublicRun
    latest: PublicRun
    runs: tuple[PublicRun, ...]

    @model_validator(mode="after")
    def validate_team_summary(self) -> PublicTeam:
        _require_team(self.team_id, self.display_name)
        if not self.runs:
            raise ValueError("A public team must have at least one scored run.")
        attempts = [run.attempt for run in self.runs]
        if attempts != sorted(set(attempts)):
            raise ValueError("Public runs must have unique ascending attempt numbers.")
        if len(self.runs) > self.attempts_used:
            raise ValueError("Scored runs cannot exceed reserved attempts.")
        if self.attempts_used + self.attempts_remaining != MAX_ATTEMPTS:
            raise ValueError("Attempt counts must add up to eight.")
        expected_best = min(
            self.runs,
            key=lambda run: (-run.overall_score, run.completed_at, run.attempt),
        )
        if self.best != expected_best:
            raise ValueError(
                "Best run must be the earliest run with the highest score."
            )
        if self.latest != max(self.runs, key=lambda run: run.attempt):
            raise ValueError("Latest run must have the highest attempt number.")
        return self


class PublicChallenge(_PublicModel):
    name: str
    status: Literal["upcoming", "live", "ended"]
    starts_at: datetime
    ends_at: datetime
    timezone: str
    max_attempts: Literal[8] = MAX_ATTEMPTS
    max_daily_attempts: Literal[2] = MAX_DAILY_ATTEMPTS
    weights: PublicWeights = PublicWeights()

    @model_validator(mode="after")
    def validate_challenge(self) -> PublicChallenge:
        Challenge(
            name=self.name,
            starts_at=self.starts_at,
            ends_at=self.ends_at,
            timezone=self.timezone,
        )
        return self


class PublicLeaderboard(_PublicModel):
    schema_version: Literal[1] = 1
    generated_at: datetime
    challenge: PublicChallenge
    teams: tuple[PublicTeam, ...]

    @model_validator(mode="after")
    def validate_board(self) -> PublicLeaderboard:
        _require_aware(self.generated_at, name="generated_at")
        expected_status = _challenge_status(
            starts_at=self.challenge.starts_at,
            ends_at=self.challenge.ends_at,
            generated_at=self.generated_at,
        )
        if self.challenge.status != expected_status:
            raise ValueError("Challenge status must match the generation timestamp.")
        if [team.rank for team in self.teams] != list(range(1, len(self.teams) + 1)):
            raise ValueError("Team ranks must be contiguous and start at one.")
        expected_order = sorted(
            self.teams,
            key=lambda team: (
                -team.best.overall_score,
                team.best.completed_at,
                team.team_id,
            ),
        )
        if list(self.teams) != expected_order:
            raise ValueError("Teams must use deterministic leaderboard ordering.")
        return self


@dataclass(frozen=True)
class _EventIndex:
    reservations: dict[str, AttemptReserved]
    scores: dict[str, AttemptScored]
    team_reservations: dict[str, tuple[AttemptReserved, ...]]


def make_submission_identity(*, team_id: str, prompt_sha256: str, head_sha: str) -> str:
    """Return the stable identity used to resume one signed submission."""

    _require_team(team_id, team_id)
    prompt_digest = prompt_sha256.lower()
    commit = head_sha.lower()
    if not _HEX_64.fullmatch(prompt_digest):
        raise ValueError("Prompt digest must be a 64-character SHA-256 value.")
    if not _HEX_COMMIT.fullmatch(commit):
        raise ValueError("Head SHA must contain 40 or 64 hexadecimal characters.")
    canonical = f"{team_id}\n{prompt_digest}\n{commit}".encode("ascii")
    return sha256(canonical).hexdigest()


def reserve_attempt(
    events: tuple[LeaderboardEvent, ...],
    *,
    team_id: str,
    display_name: str,
    submission_identity: str,
    reserved_at: datetime,
    timezone: str = "Asia/Hong_Kong",
) -> tuple[tuple[LeaderboardEvent, ...], AttemptReserved]:
    """Append one reservation, or return the prior reservation for a replay."""

    _require_team(team_id, display_name)
    _require_submission_identity(submission_identity)
    _require_aware(reserved_at, name="reserved_at")
    index = _index_events(events)
    existing = index.reservations.get(submission_identity)
    if existing is not None:
        if existing.team_id != team_id or existing.display_name != display_name:
            raise ValueError("Submission identity is already owned by another team.")
        return events, existing

    team_reservations = index.team_reservations.get(team_id, ())
    if team_reservations and team_reservations[0].display_name != display_name:
        raise ValueError("A team must use one stable display name.")
    if len(team_reservations) >= MAX_ATTEMPTS:
        raise AttemptLimitExceeded("This team has already reserved all eight attempts.")
    try:
        tournament_zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("Reservation timezone must be a valid IANA timezone.") from exc
    reservation_day = reserved_at.astimezone(tournament_zone).date()
    attempts_today = sum(
        reservation.reserved_at.astimezone(tournament_zone).date() == reservation_day
        for reservation in team_reservations
    )
    if attempts_today >= MAX_DAILY_ATTEMPTS:
        raise AttemptLimitExceeded(
            "This team has already reserved its two attempts per day."
        )

    reservation = AttemptReserved(
        submission_identity=submission_identity,
        team_id=team_id,
        display_name=display_name,
        attempt=len(team_reservations) + 1,
        reserved_at=reserved_at,
    )
    return (*events, reservation), reservation


def record_score(
    events: tuple[LeaderboardEvent, ...],
    *,
    submission_identity: str,
    score: Score,
    completed_at: datetime,
) -> tuple[LeaderboardEvent, ...]:
    """Append one score to its reservation, preserving idempotent workflow reruns."""

    _require_submission_identity(submission_identity)
    _require_aware(completed_at, name="completed_at")
    index = _index_events(events)
    reservation = index.reservations.get(submission_identity)
    if reservation is None:
        raise ValueError("No reservation exists for this submission identity.")
    existing = index.scores.get(submission_identity)
    if existing is not None:
        if existing.score != score:
            raise ValueError("Submission identity already has a different score.")
        return events
    if completed_at < reservation.reserved_at:
        raise ValueError("Score completion cannot precede its reservation.")

    return (
        *events,
        AttemptScored(
            submission_identity=submission_identity,
            attempt=reservation.attempt,
            score=score,
            completed_at=completed_at,
        ),
    )


def build_public_leaderboard(
    events: tuple[LeaderboardEvent, ...],
    *,
    challenge: Challenge,
    generated_at: datetime,
) -> PublicLeaderboard:
    """Derive the complete public view without submission or private-case data."""

    _require_aware(generated_at, name="generated_at")
    index = _index_events(events)
    unranked: list[tuple[AttemptReserved, tuple[PublicRun, ...], int]] = []
    for reservations in index.team_reservations.values():
        runs = tuple(
            _public_run(index.scores[reservation.submission_identity])
            for reservation in reservations
            if reservation.submission_identity in index.scores
        )
        if runs:
            unranked.append((reservations[0], runs, len(reservations)))

    unranked.sort(
        key=lambda item: (
            -_best_run(item[1]).overall_score,
            _best_run(item[1]).completed_at,
            item[0].team_id,
        )
    )
    teams = tuple(
        PublicTeam(
            rank=rank,
            team_id=reservation.team_id,
            display_name=reservation.display_name,
            attempts_used=attempts_used,
            attempts_remaining=MAX_ATTEMPTS - attempts_used,
            best=_best_run(runs),
            latest=max(runs, key=lambda run: run.attempt),
            runs=runs,
        )
        for rank, (reservation, runs, attempts_used) in enumerate(unranked, start=1)
    )
    return PublicLeaderboard(
        generated_at=generated_at,
        challenge=PublicChallenge(
            name=challenge.name,
            status=_challenge_status(
                starts_at=challenge.starts_at,
                ends_at=challenge.ends_at,
                generated_at=generated_at,
            ),
            starts_at=challenge.starts_at,
            ends_at=challenge.ends_at,
            timezone=challenge.timezone,
        ),
        teams=teams,
    )


def dump_public_leaderboard(leaderboard: PublicLeaderboard) -> str:
    """Encode the validated public contract as deterministic strict JSON."""

    return (
        json.dumps(
            leaderboard.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def dump_events(events: tuple[LeaderboardEvent, ...]) -> str:
    """Encode the private append-only state as deterministic JSON Lines."""

    _index_events(events)
    lines: list[str] = []
    for event in events:
        if isinstance(event, AttemptReserved):
            payload: dict[str, object] = {
                "type": "attempt_reserved",
                "submission_identity": event.submission_identity,
                "team_id": event.team_id,
                "display_name": event.display_name,
                "attempt": event.attempt,
                "reserved_at": event.reserved_at.isoformat(),
            }
        else:
            payload = {
                "type": "attempt_scored",
                "submission_identity": event.submission_identity,
                "attempt": event.attempt,
                "score": {
                    "discovery": event.score.discovery,
                    "holdout": event.score.holdout,
                    "criteria": {
                        "deterministic": event.score.criteria.deterministic,
                        "answer_relevance": event.score.criteria.answer_relevance,
                        "instruction_following": (
                            event.score.criteria.instruction_following
                        ),
                        "faithfulness": event.score.criteria.faithfulness,
                    },
                },
                "completed_at": event.completed_at.isoformat(),
            }
        lines.append(json.dumps(payload, allow_nan=False, sort_keys=True))
    return "" if not lines else "\n".join(lines) + "\n"


def load_events(encoded: str) -> tuple[LeaderboardEvent, ...]:
    """Decode and validate the complete private append-only event stream."""

    events: list[LeaderboardEvent] = []
    for line_number, line in enumerate(encoded.splitlines(), start=1):
        if not line:
            raise ValueError(f"Event log line {line_number} must not be blank.")
        try:
            value = cast(object, json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Event log line {line_number} is invalid JSON.") from exc
        if not isinstance(value, dict):
            raise ValueError(f"Event log line {line_number} must be an object.")
        payload = cast(dict[str, object], value)
        event_type = payload.get("type")
        if event_type == "attempt_reserved":
            _require_exact_fields(
                payload,
                {
                    "type",
                    "submission_identity",
                    "team_id",
                    "display_name",
                    "attempt",
                    "reserved_at",
                },
                label=f"Event log line {line_number}",
            )
            events.append(
                AttemptReserved(
                    submission_identity=_event_text(
                        payload, "submission_identity", line_number
                    ),
                    team_id=_event_text(payload, "team_id", line_number),
                    display_name=_event_text(payload, "display_name", line_number),
                    attempt=_event_int(payload, "attempt", line_number),
                    reserved_at=_event_datetime(payload, "reserved_at", line_number),
                )
            )
            continue
        if event_type == "attempt_scored":
            _require_exact_fields(
                payload,
                {
                    "type",
                    "submission_identity",
                    "attempt",
                    "score",
                    "completed_at",
                },
                label=f"Event log line {line_number}",
            )
            score_payload = _event_object(payload, "score", line_number)
            _require_exact_fields(
                score_payload,
                {"discovery", "holdout", "criteria"},
                label=f"Event log line {line_number} score",
            )
            criteria_payload = _event_object(score_payload, "criteria", line_number)
            _require_exact_fields(
                criteria_payload,
                {
                    "deterministic",
                    "answer_relevance",
                    "instruction_following",
                    "faithfulness",
                },
                label=f"Event log line {line_number} criteria",
            )
            events.append(
                AttemptScored(
                    submission_identity=_event_text(
                        payload, "submission_identity", line_number
                    ),
                    attempt=_event_int(payload, "attempt", line_number),
                    score=Score(
                        discovery=_event_number(
                            score_payload, "discovery", line_number
                        ),
                        holdout=_event_number(score_payload, "holdout", line_number),
                        criteria=CriterionScores(
                            deterministic=_event_number(
                                criteria_payload, "deterministic", line_number
                            ),
                            answer_relevance=_event_number(
                                criteria_payload, "answer_relevance", line_number
                            ),
                            instruction_following=_event_number(
                                criteria_payload,
                                "instruction_following",
                                line_number,
                            ),
                            faithfulness=_event_number(
                                criteria_payload, "faithfulness", line_number
                            ),
                        ),
                    ),
                    completed_at=_event_datetime(payload, "completed_at", line_number),
                )
            )
            continue
        raise ValueError(f"Event log line {line_number} has an unknown event type.")

    decoded = tuple(events)
    _index_events(decoded)
    return decoded


def _index_events(events: tuple[LeaderboardEvent, ...]) -> _EventIndex:
    reservations: dict[str, AttemptReserved] = {}
    scores: dict[str, AttemptScored] = {}
    mutable_team_reservations: dict[str, list[AttemptReserved]] = {}
    for event in events:
        if isinstance(event, AttemptReserved):
            if event.submission_identity in reservations:
                raise ValueError("Event log contains a duplicate reservation identity.")
            team_events = mutable_team_reservations.setdefault(event.team_id, [])
            if team_events and team_events[0].display_name != event.display_name:
                raise ValueError("Event log changes a team's display name.")
            if event.attempt != len(team_events) + 1:
                raise ValueError("Reservation attempts must be contiguous per team.")
            reservations[event.submission_identity] = event
            team_events.append(event)
            continue

        reservation = reservations.get(event.submission_identity)
        if reservation is None:
            raise ValueError("A score event must follow its reservation.")
        if event.submission_identity in scores:
            raise ValueError("Event log contains more than one score per reservation.")
        if event.attempt != reservation.attempt:
            raise ValueError("Score attempt must match its reservation.")
        if event.completed_at < reservation.reserved_at:
            raise ValueError("Score completion cannot precede its reservation.")
        scores[event.submission_identity] = event

    return _EventIndex(
        reservations=reservations,
        scores=scores,
        team_reservations={
            team_id: tuple(team_events)
            for team_id, team_events in mutable_team_reservations.items()
        },
    )


def _public_run(event: AttemptScored) -> PublicRun:
    return PublicRun(
        attempt=event.attempt,
        completed_at=event.completed_at,
        overall_score=event.score.overall,
        discovery_score=event.score.discovery,
        holdout_score=event.score.holdout,
        criteria=PublicCriterionScores(
            deterministic=event.score.criteria.deterministic,
            answer_relevance=event.score.criteria.answer_relevance,
            instruction_following=event.score.criteria.instruction_following,
            faithfulness=event.score.criteria.faithfulness,
        ),
    )


def _best_run(runs: tuple[PublicRun, ...]) -> PublicRun:
    return min(
        runs,
        key=lambda run: (-run.overall_score, run.completed_at, run.attempt),
    )


def _challenge_status(
    *, starts_at: datetime, ends_at: datetime, generated_at: datetime
) -> Literal["upcoming", "live", "ended"]:
    if generated_at < starts_at:
        return "upcoming"
    if generated_at > ends_at:
        return "ended"
    return "live"


def _require_finite_score(value: object, *, name: str, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} score must be a number.")
    if not math.isfinite(float(value)) or not 0 <= value <= maximum:
        raise ValueError(f"{name} score must be between 0 and {maximum:g}.")


def _require_aware(value: datetime, *, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone offset.")


def _require_submission_identity(value: str) -> None:
    if not _HEX_64.fullmatch(value):
        raise ValueError("Submission identity must be a lowercase SHA-256 digest.")


def _require_team(team_id: str, display_name: str) -> None:
    if not _TEAM_ID.fullmatch(team_id):
        raise ValueError("Team ID must use lowercase letters, digits, and hyphens.")
    if not display_name.strip() or display_name != display_name.strip():
        raise ValueError("Display name must be a trimmed non-empty string.")


def _require_exact_fields(
    payload: dict[str, object], expected: set[str], *, label: str
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} must contain exactly {sorted(expected)}.")


def _event_text(payload: dict[str, object], key: str, line_number: int) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Event log line {line_number} field {key} must be text.")
    return value


def _event_int(payload: dict[str, object], key: str, line_number: int) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"Event log line {line_number} field {key} must be an integer."
        )
    return value


def _event_number(payload: dict[str, object], key: str, line_number: int) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"Event log line {line_number} field {key} must be numeric.")
    return float(value)


def _event_object(
    payload: dict[str, object], key: str, line_number: int
) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Event log line {line_number} field {key} must be an object.")
    return cast(dict[str, object], value)


def _event_datetime(payload: dict[str, object], key: str, line_number: int) -> datetime:
    value = _event_text(payload, key, line_number)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            f"Event log line {line_number} field {key} must be an ISO timestamp."
        ) from exc
