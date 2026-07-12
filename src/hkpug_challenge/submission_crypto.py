from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from asn1crypto import cms as _cms, x509 as _asn1_x509  # type: ignore[reportMissingTypeStubs]
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from hkpug_challenge.submission_manifest import read_bounded_regular_file


EXPECTED_SCORER_COMMON_NAME = "HKPUG Scorer"
MAX_CERTIFICATE_BYTES = 16384
MAX_CIPHERTEXT_BYTES = 65536
MAX_PRIVATE_KEY_BYTES = 16384
MAX_PROMPT_BYTES = 8192
_CMS: Any = _cms
_ASN1_X509: Any = _asn1_x509


def load_certificate(certificate_path: Path) -> x509.Certificate:
    certificate_bytes = read_bounded_regular_file(
        certificate_path,
        "Certificate",
        MAX_CERTIFICATE_BYTES,
    )
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
    key_usage = _require_key_usage(
        certificate,
        "Allowlisted team certificate must define key usage.",
    )
    if not key_usage.digital_signature or not key_usage.key_encipherment:
        raise ValueError(
            "Allowlisted team certificate must allow digital signature and key encipherment."
        )


def require_scorer_identity(certificate: x509.Certificate) -> None:
    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(common_names) != 1 or common_names[0].value != EXPECTED_SCORER_COMMON_NAME:
        raise ValueError("Trusted scorer cert identity is invalid.")


def require_scorer_key_usage(certificate: x509.Certificate) -> None:
    key_usage = _require_key_usage(
        certificate,
        "Trusted scorer cert must define key usage.",
    )
    if not key_usage.key_encipherment:
        raise ValueError("Trusted scorer cert must allow key encipherment.")


def verify_leaf_certificate_against_ca(
    *,
    certificate: x509.Certificate,
    ca_certificate: x509.Certificate,
    label: str,
) -> None:
    _require_valid_now(ca_certificate, f"{label} CA certificate")
    _require_ca_certificate(ca_certificate)
    _verify_self_signed_ca(ca_certificate)

    _require_valid_now(certificate, label)
    _require_leaf_certificate(certificate, label)
    if certificate.issuer != ca_certificate.subject:
        raise ValueError(f"{label} issuer does not match the tournament CA.")

    ca_public_key = ca_certificate.public_key()
    if not isinstance(ca_public_key, rsa.RSAPublicKey):
        raise ValueError("Tournament CA certificate must use an RSA public key.")
    signature_hash_algorithm = certificate.signature_hash_algorithm
    if signature_hash_algorithm is None:
        raise ValueError(f"{label} must declare a signature hash algorithm.")
    try:
        ca_public_key.verify(
            certificate.signature,
            certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash_algorithm,
        )
    except InvalidSignature as exc:
        raise ValueError(f"{label} failed tournament CA chain validation.") from exc


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


def inspect_ciphertext(
    ciphertext_path: Path, scorer_certificate: x509.Certificate
) -> None:
    ciphertext_bytes = read_bounded_regular_file(
        ciphertext_path,
        "Prompt ciphertext",
        MAX_CIPHERTEXT_BYTES,
    )
    try:
        content_info: Any = _CMS.ContentInfo.load(ciphertext_bytes, strict=True)
        if content_info["content_type"].native != "enveloped_data":
            raise ValueError("Prompt ciphertext must be CMS EnvelopedData.")

        enveloped_data: Any = content_info["content"]
        recipient_infos: Any = enveloped_data["recipient_infos"]
        encrypted_content_info: Any = enveloped_data["encrypted_content_info"]
        algorithm = str(
            encrypted_content_info["content_encryption_algorithm"]["algorithm"].native
        )
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("Prompt ciphertext"):
            raise
        raise ValueError(
            "Prompt ciphertext is not valid DER CMS EnvelopedData."
        ) from exc

    if algorithm != "aes256_cbc":
        raise ValueError("Prompt ciphertext must use AES-256-CBC.")

    if len(recipient_infos) != 1:
        raise ValueError("Prompt ciphertext must contain exactly one recipient.")

    recipient_info: Any = recipient_infos[0]
    if recipient_info.name != "ktri":
        raise ValueError("Prompt ciphertext recipient must be key transport.")

    recipient_identifier: Any = recipient_info.chosen["rid"]
    if recipient_identifier.name != "issuer_and_serial_number":
        raise ValueError("Prompt ciphertext recipient must use issuerAndSerialNumber.")

    issuer_and_serial: Any = recipient_identifier.chosen
    scorer_certificate_asn1: Any = _ASN1_X509.Certificate.load(
        scorer_certificate.public_bytes(serialization.Encoding.DER),
        strict=True,
    )
    expected_issuer: Any = scorer_certificate_asn1["tbs_certificate"]["issuer"]
    expected_serial_number = int(
        scorer_certificate_asn1["tbs_certificate"]["serial_number"].native
    )
    if (
        issuer_and_serial["issuer"].dump() != expected_issuer.dump()
        or int(issuer_and_serial["serial_number"].native) != expected_serial_number
    ):
        raise ValueError(
            "Prompt ciphertext recipient must match the trusted scorer recipient."
        )


def decrypt_ciphertext(
    *,
    ciphertext_path: Path,
    scorer_private_key_path: Path,
    scorer_cert_path: Path,
) -> bytes:
    ciphertext_bytes = read_bounded_regular_file(
        ciphertext_path,
        "Prompt ciphertext",
        MAX_CIPHERTEXT_BYTES,
    )
    private_key_bytes = read_private_key_file(
        scorer_private_key_path, "Scorer private key"
    )
    certificate_bytes = read_bounded_regular_file(
        scorer_cert_path,
        "Certificate",
        MAX_CERTIFICATE_BYTES,
    )
    with tempfile.TemporaryDirectory() as temp_directory_name:
        temp_directory = Path(temp_directory_name)
        if os.name != "nt":
            temp_directory.chmod(0o700)
        snapshot_ciphertext_path = _write_private_snapshot(
            temp_directory, "ciphertext.der", ciphertext_bytes
        )
        snapshot_private_key_path = _write_private_snapshot(
            temp_directory, "private_key.pem", private_key_bytes
        )
        snapshot_certificate_path = _write_private_snapshot(
            temp_directory, "certificate.pem", certificate_bytes
        )
        plaintext_path = temp_directory / "plaintext.txt"
        result = subprocess.run(
            [
                "openssl",
                "cms",
                "-decrypt",
                "-binary",
                "-inform",
                "DER",
                "-in",
                str(snapshot_ciphertext_path),
                "-inkey",
                str(snapshot_private_key_path),
                "-recip",
                str(snapshot_certificate_path),
                "-out",
                str(plaintext_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise ValueError(
                "Prompt ciphertext could not be decrypted by the scorer key."
            )
        try:
            return read_bounded_regular_file(
                plaintext_path, "Prompt text", MAX_PROMPT_BYTES
            )
        except ValueError as exc:
            if str(exc) == "Prompt text file is too large.":
                raise ValueError(
                    f"Prompt text must be at most {MAX_PROMPT_BYTES} bytes."
                ) from exc
            raise


def read_private_key_file(private_key_path: Path, label: str) -> bytes:
    key_bytes = read_bounded_regular_file(
        private_key_path,
        label,
        MAX_PRIVATE_KEY_BYTES,
    )
    if os.name != "nt" and private_key_path.stat().st_mode & 0o077:
        raise ValueError(f"{label} file must not be group- or world-readable.")
    return key_bytes


def load_rsa_private_key(private_key_path: Path) -> rsa.RSAPrivateKey:
    private_key_bytes = read_private_key_file(private_key_path, "Team private key")
    try:
        private_key = serialization.load_pem_private_key(
            private_key_bytes, password=None
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("Team private key is not valid PEM.") from exc
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Team private key must be an RSA private key.")
    return private_key


def _write_private_snapshot(directory: Path, name: str, content: bytes) -> Path:
    path = directory / name
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    file_descriptor = os.open(path, flags, 0o600)
    with os.fdopen(file_descriptor, "wb") as file:
        file.write(content)
    return path


def _require_valid_now(certificate: x509.Certificate, label: str) -> None:
    now = datetime.now(timezone.utc)
    if now < certificate.not_valid_before_utc:
        raise ValueError(f"{label} is not yet valid.")
    if now > certificate.not_valid_after_utc:
        raise ValueError(f"{label} is expired.")


def _require_ca_certificate(certificate: x509.Certificate) -> None:
    try:
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound as exc:
        raise ValueError(
            "Tournament CA certificate must define basic constraints."
        ) from exc
    if not basic_constraints.ca:
        raise ValueError("Tournament CA certificate must be a CA certificate.")

    key_usage = _require_key_usage(
        certificate,
        "Tournament CA certificate must define key usage.",
    )
    if not key_usage.key_cert_sign:
        raise ValueError("Tournament CA certificate must allow certificate signing.")


def _require_leaf_certificate(certificate: x509.Certificate, label: str) -> None:
    try:
        basic_constraints = certificate.extensions.get_extension_for_class(
            x509.BasicConstraints
        ).value
    except x509.ExtensionNotFound as exc:
        raise ValueError(f"{label} must define basic constraints.") from exc
    if basic_constraints.ca:
        raise ValueError(f"{label} must not be a CA certificate.")


def _require_key_usage(certificate: x509.Certificate, message: str) -> x509.KeyUsage:
    try:
        return certificate.extensions.get_extension_for_class(x509.KeyUsage).value
    except x509.ExtensionNotFound as exc:
        raise ValueError(message) from exc


def _verify_self_signed_ca(ca_certificate: x509.Certificate) -> None:
    if ca_certificate.subject != ca_certificate.issuer:
        raise ValueError("Tournament CA certificate must be self-issued.")
    ca_public_key = ca_certificate.public_key()
    if not isinstance(ca_public_key, rsa.RSAPublicKey):
        raise ValueError("Tournament CA certificate must use an RSA public key.")
    signature_hash_algorithm = ca_certificate.signature_hash_algorithm
    if signature_hash_algorithm is None:
        raise ValueError(
            "Tournament CA certificate must declare a signature hash algorithm."
        )
    try:
        ca_public_key.verify(
            ca_certificate.signature,
            ca_certificate.tbs_certificate_bytes,
            padding.PKCS1v15(),
            signature_hash_algorithm,
        )
    except InvalidSignature as exc:
        raise ValueError("Tournament CA certificate signature is invalid.") from exc
