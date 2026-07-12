from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Sequence

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator


DEFAULT_ALLOWLIST_PATH = Path(".github/tournament/team_allowlist.json")
DEFAULT_TOURNAMENT_CA_CERT_PATH = Path(
    ".github/tournament/public_keys/tournament_ca_cert.pem"
)
DEFAULT_SCORER_CERT_PATH = Path(".github/tournament/public_keys/scorer_cert.pem")
DEFAULT_SCORER_PRIVATE_KEY_PATH = Path(".local/tournament/scorer_private_key.pem")
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
MAX_PROMPT_BYTES = 8192


@dataclass(frozen=True)
class VerifiedSubmission:
    team_id: str
    created_at: str
    prompt_sha256: str
    prompt_text: str


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
    cert_path: str
    cert_sha256: str

    @field_validator("team_id")
    @classmethod
    def validate_team_id(cls, value: str) -> str:
        return SubmissionManifest.validate_team_id(value)

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
    try:
        prompt_bytes = prompt_path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError("Prompt text file was not found.") from exc
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
    manifest, canonical_bytes = load_manifest_file(manifest_path)
    del manifest
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
    signature = read_required_bytes(signature_path, "Manifest signature")
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
    require_allowlist_digest(team_certificate, allowlist_entry.cert_sha256)
    require_team_identity(team_certificate, manifest.team_id)
    require_team_key_usage(team_certificate)

    tournament_ca_certificate = load_certificate(tournament_ca_cert_path)
    verify_certificate_against_ca(team_certificate, tournament_ca_certificate)
    verify_manifest_signature(team_certificate, canonical_bytes, signature)

    inspect_ciphertext(ciphertext_path)
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


def load_manifest_file(manifest_path: Path) -> tuple[SubmissionManifest, bytes]:
    raw_bytes = read_required_bytes(manifest_path, "Manifest")
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


def load_allowlist(allowlist_path: Path) -> TeamAllowlist:
    raw_bytes = read_required_bytes(allowlist_path, "Team allowlist")
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
    resolved_path = (allowlist_root / cert_path).resolve()
    if not resolved_path.is_relative_to(allowlist_root):
        raise ValueError("Allowlist cert_path escapes the allowlist directory.")
    return resolved_path


def read_required_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"{label} file was not found.") from exc


def load_certificate(certificate_path: Path) -> x509.Certificate:
    certificate_bytes = read_required_bytes(certificate_path, "Certificate")
    try:
        return x509.load_pem_x509_certificate(certificate_bytes)
    except ValueError as exc:
        raise ValueError("Certificate file is not valid PEM.") from exc


def require_allowlist_digest(
    certificate: x509.Certificate, expected_digest: str
) -> None:
    actual_digest = certificate.fingerprint(hashes.SHA256()).hex()
    if actual_digest != expected_digest:
        raise ValueError("Allowlist cert_sha256 does not match the team certificate.")


def require_team_identity(certificate: x509.Certificate, team_id: str) -> None:
    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(common_names) != 1 or common_names[0].value != team_id:
        raise ValueError(
            "Allowlisted team certificate identity does not match team_id."
        )


def require_team_key_usage(certificate: x509.Certificate) -> None:
    try:
        key_usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise ValueError("Allowlisted team certificate must define key usage.") from exc
    if not key_usage.digital_signature or not key_usage.key_encipherment:
        raise ValueError(
            "Allowlisted team certificate must allow digital signature and key encipherment."
        )


def verify_certificate_against_ca(
    certificate: x509.Certificate,
    ca_certificate: x509.Certificate,
) -> None:
    if ca_certificate.subject != ca_certificate.issuer:
        raise ValueError("Tournament CA certificate must be self-issued.")
    if certificate.issuer != ca_certificate.subject:
        raise ValueError("Team certificate issuer does not match the tournament CA.")

    ca_public_key = ca_certificate.public_key()
    if not isinstance(ca_public_key, rsa.RSAPublicKey):
        raise ValueError("Tournament CA certificate must use an RSA public key.")
    signature_hash_algorithm = certificate.signature_hash_algorithm
    if signature_hash_algorithm is None:
        raise ValueError("Team certificate must declare a signature hash algorithm.")
    try:
        ca_public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash_algorithm,
        )
    except InvalidSignature as exc:
        raise ValueError(
            "Team certificate failed tournament CA chain validation."
        ) from exc


def verify_manifest_signature(
    certificate: x509.Certificate,
    manifest_bytes: bytes,
    signature: bytes,
) -> None:
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        raise ValueError("Allowlisted team certificate must use an RSA public key.")
    try:
        public_key.verify(
            signature,
            manifest_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise ValueError("Manifest signature verification failed.") from exc


def inspect_ciphertext(ciphertext_path: Path) -> None:
    read_required_bytes(ciphertext_path, "Prompt ciphertext")
    result = subprocess.run(
        [
            "openssl",
            "cms",
            "-cmsout",
            "-print",
            "-inform",
            "DER",
            "-in",
            str(ciphertext_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Prompt ciphertext is not valid DER CMS data.")
    if "aes-256-cbc" not in result.stdout.lower():
        raise ValueError("Prompt ciphertext must use AES-256-CBC.")


def decrypt_ciphertext(
    *,
    ciphertext_path: Path,
    scorer_private_key_path: Path,
    scorer_cert_path: Path,
) -> bytes:
    read_required_bytes(scorer_private_key_path, "Scorer private key")
    read_required_bytes(scorer_cert_path, "Scorer certificate")
    result = subprocess.run(
        [
            "openssl",
            "cms",
            "-decrypt",
            "-binary",
            "-inform",
            "DER",
            "-in",
            str(ciphertext_path),
            "-inkey",
            str(scorer_private_key_path),
            "-recip",
            str(scorer_cert_path),
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError("Prompt ciphertext could not be decrypted by the scorer key.")
    return result.stdout


def load_rsa_private_key(private_key_path: Path) -> rsa.RSAPrivateKey:
    private_key_bytes = read_required_bytes(private_key_path, "Team private key")
    try:
        private_key = serialization.load_pem_private_key(
            private_key_bytes, password=None
        )
    except ValueError as exc:
        raise ValueError("Team private key is not valid PEM.") from exc
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Team private key must be an RSA private key.")
    return private_key


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

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
