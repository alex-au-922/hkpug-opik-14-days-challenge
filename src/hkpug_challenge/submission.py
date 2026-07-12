from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Sequence

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

from hkpug_challenge.submission_crypto import (
    MAX_CERTIFICATE_BYTES,
    MAX_CIPHERTEXT_BYTES,
    MAX_PROMPT_BYTES,
    decrypt_ciphertext,
    inspect_ciphertext,
    load_certificate,
    load_rsa_private_key,
    require_allowlist_digest,
    require_scorer_identity,
    require_scorer_key_usage,
    require_team_identity,
    require_team_key_usage,
    verify_leaf_certificate_against_ca,
    verify_manifest_signature,
)
from hkpug_challenge.submission_manifest import (
    EXPECTED_MANIFEST_FIELDS,
    EXPECTED_PROMPT_PATH,
    MAX_ALLOWLIST_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_SIGNATURE_BYTES,
    MANIFEST_FILENAME,
    SIGNATURE_FILENAME,
    SubmissionManifest,
    TeamAllowlist,
    TeamAllowlistEntry,
    canonical_manifest_bytes,
    load_allowlist,
    load_manifest_file,
    load_manifest_signature,
    read_bounded_regular_file,
    resolve_allowlisted_cert_path,
)


DEFAULT_ALLOWLIST_PATH = Path(".github/tournament/team_allowlist.json")
DEFAULT_TOURNAMENT_CA_CERT_PATH = Path(
    ".github/tournament/public_keys/tournament_ca_cert.pem"
)
DEFAULT_SCORER_CERT_PATH = Path(".github/tournament/public_keys/scorer_cert.pem")
DEFAULT_SCORER_PRIVATE_KEY_PATH = Path(".local/tournament/scorer_private_key.pem")

__all__ = [
    "DEFAULT_ALLOWLIST_PATH",
    "DEFAULT_SCORER_CERT_PATH",
    "DEFAULT_SCORER_PRIVATE_KEY_PATH",
    "DEFAULT_TOURNAMENT_CA_CERT_PATH",
    "EXPECTED_MANIFEST_FIELDS",
    "EXPECTED_PROMPT_PATH",
    "MANIFEST_FILENAME",
    "MAX_ALLOWLIST_BYTES",
    "MAX_CERTIFICATE_BYTES",
    "MAX_CIPHERTEXT_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_PROMPT_BYTES",
    "MAX_SIGNATURE_BYTES",
    "SIGNATURE_FILENAME",
    "SubmissionManifest",
    "TeamAllowlist",
    "TeamAllowlistEntry",
    "VerifiedSubmission",
    "build_argument_parser",
    "build_manifest",
    "canonical_manifest_bytes",
    "current_timestamp",
    "decrypt_ciphertext",
    "inspect_ciphertext",
    "load_allowlist",
    "load_certificate",
    "load_manifest_file",
    "load_manifest_signature",
    "load_prompt_text",
    "load_rsa_private_key",
    "main",
    "read_bounded_regular_file",
    "require_allowlist_digest",
    "require_scorer_identity",
    "require_scorer_key_usage",
    "require_team_identity",
    "require_team_key_usage",
    "resolve_allowlisted_cert_path",
    "sign_manifest_file",
    "validate_prompt_text",
    "verify_certificate_against_ca",
    "verify_leaf_certificate_against_ca",
    "verify_manifest_signature",
    "verify_submission",
    "write_manifest_file",
]


def verify_certificate_against_ca(
    certificate: x509.Certificate,
    ca_certificate: x509.Certificate,
) -> None:
    verify_leaf_certificate_against_ca(
        certificate=certificate,
        ca_certificate=ca_certificate,
        label="Team certificate",
    )


@dataclass(frozen=True)
class VerifiedSubmission:
    team_id: str
    created_at: str
    prompt_sha256: str
    prompt_text: str


def build_manifest(
    *,
    team_id: str,
    prompt_text: str,
    created_at: str | None = None,
) -> SubmissionManifest:
    prompt_bytes = validate_prompt_text(prompt_text)
    return SubmissionManifest(
        schema_version=1,
        team_id=team_id,
        prompt_path=EXPECTED_PROMPT_PATH,
        prompt_sha256=sha256(prompt_bytes).hexdigest(),
        created_at=created_at or current_timestamp(),
    )


def current_timestamp() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def validate_prompt_text(prompt_text: str) -> bytes:
    prompt_bytes = prompt_text.encode("utf-8")
    if not prompt_bytes:
        raise ValueError("Prompt text must not be empty.")
    if len(prompt_bytes) > MAX_PROMPT_BYTES:
        raise ValueError(f"Prompt text must be at most {MAX_PROMPT_BYTES} bytes.")
    if "\x00" in prompt_text:
        raise ValueError("Prompt text must not contain NUL bytes.")
    return prompt_bytes


def load_prompt_text(prompt_path: Path) -> str:
    prompt_bytes = read_bounded_regular_file(
        prompt_path,
        "Prompt text",
        MAX_PROMPT_BYTES,
    )
    try:
        prompt_text = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Prompt text file must be valid UTF-8.") from exc
    validate_prompt_text(prompt_text)
    return prompt_text


def write_manifest_file(manifest_path: Path, manifest: SubmissionManifest) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_bytes(canonical_manifest_bytes(manifest))


def sign_manifest_file(
    *,
    manifest_path: Path,
    private_key_path: Path,
    signature_path: Path,
) -> None:
    _, canonical_bytes = load_manifest_file(manifest_path)
    private_key = load_rsa_private_key(private_key_path)
    signature = private_key.sign(
        canonical_bytes,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_path.write_bytes(signature)


def verify_submission(
    *,
    submission_dir: Path,
    allowlist_path: Path = DEFAULT_ALLOWLIST_PATH,
    tournament_ca_cert_path: Path = DEFAULT_TOURNAMENT_CA_CERT_PATH,
    scorer_private_key_path: Path = DEFAULT_SCORER_PRIVATE_KEY_PATH,
    scorer_cert_path: Path = DEFAULT_SCORER_CERT_PATH,
) -> VerifiedSubmission:
    manifest_path = submission_dir / MANIFEST_FILENAME
    signature_path = submission_dir / SIGNATURE_FILENAME
    ciphertext_path = submission_dir / Path(EXPECTED_PROMPT_PATH).name

    manifest, canonical_bytes = load_manifest_file(manifest_path)
    signature = load_manifest_signature(signature_path)
    allowlist = load_allowlist(allowlist_path)

    allowlist_entry = next(
        (entry for entry in allowlist.teams if entry.team_id == manifest.team_id),
        None,
    )
    if allowlist_entry is None:
        raise ValueError("Manifest team_id is not present in the allowlist.")

    team_cert_path = resolve_allowlisted_cert_path(
        allowlist_path, allowlist_entry.cert_path
    )
    team_certificate = load_certificate(team_cert_path)
    tournament_ca_certificate = load_certificate(tournament_ca_cert_path)
    scorer_certificate = load_certificate(scorer_cert_path)

    require_allowlist_digest(team_certificate, allowlist_entry.cert_sha256)
    require_team_identity(team_certificate, manifest.team_id)
    require_team_key_usage(team_certificate)
    verify_leaf_certificate_against_ca(
        certificate=team_certificate,
        ca_certificate=tournament_ca_certificate,
        label="Team certificate",
    )
    verify_manifest_signature(team_certificate, canonical_bytes, signature)

    require_scorer_identity(scorer_certificate)
    require_scorer_key_usage(scorer_certificate)
    verify_leaf_certificate_against_ca(
        certificate=scorer_certificate,
        ca_certificate=tournament_ca_certificate,
        label="Trusted scorer cert",
    )
    inspect_ciphertext(ciphertext_path, scorer_certificate)

    prompt_bytes = decrypt_ciphertext(
        ciphertext_path=ciphertext_path,
        scorer_private_key_path=scorer_private_key_path,
        scorer_cert_path=scorer_cert_path,
    )
    try:
        prompt_text = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Decrypted prompt payload must be valid UTF-8 text.") from exc
    prompt_bytes = validate_prompt_text(prompt_text)

    prompt_sha256 = sha256(prompt_bytes).hexdigest()
    if prompt_sha256 != manifest.prompt_sha256:
        raise ValueError(
            "Manifest prompt_sha256 does not match the decrypted prompt text."
        )

    return VerifiedSubmission(
        team_id=manifest.team_id,
        created_at=manifest.created_at,
        prompt_sha256=prompt_sha256,
        prompt_text=prompt_text,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_manifest_parser = subparsers.add_parser("create-manifest")
    create_manifest_parser.add_argument("--team-id", required=True)
    create_manifest_parser.add_argument("--prompt-path", type=Path, required=True)
    create_manifest_parser.add_argument("--manifest-path", type=Path, required=True)
    create_manifest_parser.add_argument("--created-at")

    sign_manifest_parser = subparsers.add_parser("sign-manifest")
    sign_manifest_parser.add_argument("--manifest-path", type=Path, required=True)
    sign_manifest_parser.add_argument("--private-key-path", type=Path, required=True)
    sign_manifest_parser.add_argument("--signature-path", type=Path, required=True)

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--submission-dir", type=Path, required=True)
    verify_parser.add_argument(
        "--allowlist-path",
        type=Path,
        default=DEFAULT_ALLOWLIST_PATH,
    )
    verify_parser.add_argument(
        "--tournament-ca-cert-path",
        type=Path,
        default=DEFAULT_TOURNAMENT_CA_CERT_PATH,
    )
    verify_parser.add_argument(
        "--scorer-private-key-path",
        type=Path,
        default=DEFAULT_SCORER_PRIVATE_KEY_PATH,
    )
    verify_parser.add_argument(
        "--scorer-cert-path",
        type=Path,
        default=DEFAULT_SCORER_CERT_PATH,
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "create-manifest":
            prompt_text = load_prompt_text(args.prompt_path)
            manifest = build_manifest(
                team_id=args.team_id,
                prompt_text=prompt_text,
                created_at=args.created_at,
            )
            write_manifest_file(args.manifest_path, manifest)
            return 0

        if args.command == "sign-manifest":
            sign_manifest_file(
                manifest_path=args.manifest_path,
                private_key_path=args.private_key_path,
                signature_path=args.signature_path,
            )
            return 0

        if args.command == "verify":
            verified_submission = verify_submission(
                submission_dir=args.submission_dir,
                allowlist_path=args.allowlist_path,
                tournament_ca_cert_path=args.tournament_ca_cert_path,
                scorer_private_key_path=args.scorer_private_key_path,
                scorer_cert_path=args.scorer_cert_path,
            )
            print(
                json.dumps(
                    {
                        "team_id": verified_submission.team_id,
                        "created_at": verified_submission.created_at,
                        "prompt_sha256": verified_submission.prompt_sha256,
                    }
                )
            )
            return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
