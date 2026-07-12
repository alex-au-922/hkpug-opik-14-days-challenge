from __future__ import annotations

import errno
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


EXPECTED_MANIFEST_FIELDS = (
    "schema_version",
    "team_id",
    "prompt_path",
    "prompt_sha256",
    "created_at",
)
EXPECTED_PROMPT_PATH = "submission/prompt.txt.cms"
MANIFEST_FILENAME = "manifest.json"
SIGNATURE_FILENAME = "manifest.sig"
MAX_MANIFEST_BYTES = 4096
MAX_SIGNATURE_BYTES = 8192
MAX_ALLOWLIST_BYTES = 65536


@dataclass(frozen=True)
class RegularFileSnapshot:
    content: bytes
    mode: int


class SubmissionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    team_id: str
    prompt_path: str
    prompt_sha256: str
    created_at: str

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError("Manifest schema_version must be exactly 1.")
        return value

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, value: str) -> str:
        if not value:
            raise ValueError("Manifest team_id must be a non-empty string.")
        allowed = "abcdefghijklmnopqrstuvwxyz0123456789-"
        if (
            value[0] == "-"
            or value[-1] == "-"
            or any(char not in allowed for char in value)
        ):
            raise ValueError(
                "Manifest team_id must use lowercase letters, digits, and hyphens."
            )
        return value

    @field_validator("prompt_path")
    @classmethod
    def validate_prompt_path(cls, value: str) -> str:
        if value != EXPECTED_PROMPT_PATH:
            raise ValueError(
                f"Manifest prompt_path must be exactly {EXPECTED_PROMPT_PATH!r}."
            )
        return value

    @field_validator("prompt_sha256")
    @classmethod
    def validate_prompt_sha256(cls, value: str) -> str:
        normalized = value.lower()
        if len(normalized) != 64 or any(
            char not in "0123456789abcdef" for char in normalized
        ):
            raise ValueError(
                "Manifest prompt_sha256 must be a 64-character lowercase hex digest."
            )
        return normalized

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: str) -> str:
        if not value.endswith("Z"):
            raise ValueError("Manifest created_at must be an RFC 3339 UTC timestamp.")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(
                "Manifest created_at must be an RFC 3339 UTC timestamp."
            ) from exc
        if parsed.tzinfo != timezone.utc:
            raise ValueError("Manifest created_at must be an RFC 3339 UTC timestamp.")
        if parsed.microsecond != 0:
            raise ValueError("Manifest created_at must use whole-second UTC precision.")
        return value


class TeamAllowlistEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    team_id: str
    display_name: str | None = None
    cert_path: str
    cert_sha256: str

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, value: str) -> str:
        return SubmissionManifest.validate_team_id(value)

    @field_validator("display_name")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if (
            not value
            or value != value.strip()
            or len(value) > 80
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError(
                "Allowlist display_name must be trimmed printable text up to 80 characters."
            )
        return value

    @field_validator("cert_path")
    @classmethod
    def validate_cert_path(cls, value: str) -> str:
        path = Path(value)
        if path.is_absolute():
            raise ValueError("Allowlist cert_path must be relative.")
        if not value:
            raise ValueError("Allowlist cert_path must be a non-empty string.")
        return value

    @field_validator("cert_sha256")
    @classmethod
    def validate_cert_sha256(cls, value: str) -> str:
        return SubmissionManifest.validate_prompt_sha256(value)


class TeamAllowlist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    teams: tuple[TeamAllowlistEntry, ...]


def canonical_manifest_bytes(manifest: SubmissionManifest | dict[str, Any]) -> bytes:
    if isinstance(manifest, SubmissionManifest):
        payload = manifest.model_dump()
    else:
        payload = manifest
    canonical_payload = {
        "schema_version": payload["schema_version"],
        "team_id": payload["team_id"],
        "prompt_path": payload["prompt_path"],
        "prompt_sha256": payload["prompt_sha256"],
        "created_at": payload["created_at"],
    }
    return (
        json.dumps(
            canonical_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def read_bounded_regular_file(path: Path, label: str, max_bytes: int) -> bytes:
    return read_bounded_regular_file_snapshot(path, label, max_bytes).content


def read_bounded_regular_file_snapshot(
    path: Path, label: str, max_bytes: int
) -> RegularFileSnapshot:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError(
            "Atomic no-symlink file verification requires POSIX os.O_NOFOLLOW; "
            "run untrusted submission verification on Linux, macOS, or WSL."
        )
    nonblock = getattr(os, "O_NONBLOCK", None)
    if nonblock is None:
        raise ValueError(
            "Non-blocking file verification requires os.O_NONBLOCK to avoid FIFO "
            "hangs; run untrusted submission verification on a POSIX platform."
        )

    try:
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file was not found.") from exc
    except OSError:
        raise

    if not stat.S_ISREG(file_stat.st_mode):
        raise ValueError(f"{label} file must be a regular file.")

    try:
        file_descriptor = os.open(path, os.O_RDONLY | nofollow | nonblock)
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file was not found.") from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"{label} file must be a regular file.") from exc
        if exc.errno in {errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}:
            raise ValueError(
                "Atomic submission verification requires os.O_NOFOLLOW and "
                "os.O_NONBLOCK support on this platform."
            ) from exc
        raise

    try:
        file_stat = os.fstat(file_descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ValueError(f"{label} file must be a regular file.")
        if file_stat.st_size > max_bytes:
            raise ValueError(f"{label} file is too large.")
        content = _read_at_most(file_descriptor, max_bytes + 1)
    finally:
        os.close(file_descriptor)

    if len(content) > max_bytes:
        raise ValueError(f"{label} file is too large.")
    return RegularFileSnapshot(content=content, mode=file_stat.st_mode)


def _read_at_most(file_descriptor: int, byte_limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = byte_limit
    while remaining > 0:
        chunk = os.read(file_descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def load_manifest_file(manifest_path: Path) -> tuple[SubmissionManifest, bytes]:
    raw_bytes = read_bounded_regular_file(
        manifest_path,
        "Manifest",
        MAX_MANIFEST_BYTES,
    )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Manifest must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Manifest must be one JSON object.")

    try:
        manifest = SubmissionManifest.model_validate(payload)
    except ValidationError as exc:
        error_types = {error["type"] for error in exc.errors()}
        if "missing" in error_types or "extra_forbidden" in error_types:
            raise ValueError(
                f"Manifest fields must be exactly {list(EXPECTED_MANIFEST_FIELDS)}."
            ) from exc
        messages = "; ".join(error["msg"] for error in exc.errors())
        raise ValueError(messages) from exc

    canonical_bytes = canonical_manifest_bytes(manifest)
    if raw_bytes != canonical_bytes:
        raise ValueError("Manifest must use canonical JSON formatting.")

    return manifest, canonical_bytes


def load_manifest_signature(signature_path: Path) -> bytes:
    return read_bounded_regular_file(
        signature_path,
        "Manifest signature",
        MAX_SIGNATURE_BYTES,
    )


def load_allowlist(allowlist_path: Path) -> TeamAllowlist:
    raw_bytes = read_bounded_regular_file(
        allowlist_path,
        "Team allowlist",
        MAX_ALLOWLIST_BYTES,
    )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Team allowlist must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise ValueError("Team allowlist must be one JSON object.")
    try:
        allowlist = TeamAllowlist.model_validate(payload)
    except ValidationError as exc:
        raise ValueError("Team allowlist failed schema validation.") from exc

    team_ids = [entry.team_id for entry in allowlist.teams]
    if len(set(team_ids)) != len(team_ids):
        raise ValueError("Team allowlist contains duplicate team IDs.")
    return allowlist


def resolve_allowlisted_cert_path(allowlist_path: Path, cert_path: str) -> Path:
    allowlist_root = allowlist_path.parent.resolve()
    requested_path = allowlist_root / cert_path
    resolved_parent = requested_path.parent.resolve()
    if not resolved_parent.is_relative_to(allowlist_root):
        raise ValueError("Allowlist cert_path escapes the allowlist directory.")
    return requested_path
