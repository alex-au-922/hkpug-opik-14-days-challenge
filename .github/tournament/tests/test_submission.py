from __future__ import annotations

import hashlib
import json
import os
import signal
import stat
import subprocess
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, TypedDict

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from hkpug_challenge.submission import (
    ValidatedEnvelope,
    canonical_manifest_bytes,
    read_bounded_regular_file,
    validate_submission_archive,
    validate_submission_envelope,
    verify_submission,
    verify_submission_archive,
)
from hkpug_challenge.submission_archive import (
    EXPECTED_ARCHIVE_ENTRIES,
    MAX_SUBMISSION_ARCHIVE_BYTES,
    extract_submission_archive,
)


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PROMPT_PATH = "submission/prompt.txt.cms"
MAX_PROMPT_BYTES = 8192


class CertificateMaterial(TypedDict):
    allowlist_path: Path
    ca_cert_path: Path
    ca_key_path: Path
    scorer_cert_path: Path
    scorer_key_path: Path
    team_cert_path: Path
    team_key_path: Path


class SubmissionPaths(CertificateMaterial):
    prompt_path: Path
    submission_directory: Path
    ciphertext_path: Path
    manifest_path: Path
    signature_path: Path


PathMutator = Callable[[SubmissionPaths], None]


def run_checked(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def run_checked_bytes(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=False,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {' '.join(args)}\nstdout:\n{result.stdout!r}\nstderr:\n{result.stderr!r}"
        )
    return result


def write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_test_rsa_private_key(path: Path) -> rsa.RSAPrivateKey:
    private_key = serialization.load_pem_private_key(
        path.read_bytes(),
        password=None,
    )
    assert isinstance(private_key, rsa.RSAPrivateKey)
    return private_key


def set_private_permissions(path: Path) -> None:
    if os.name != "nt":
        os.chmod(path, 0o600)


def issue_leaf_certificate(
    *,
    ca_cert_path: Path,
    ca_key_path: Path,
    common_name: str,
    key_path: Path,
    csr_path: Path,
    cert_path: Path,
    ext_path: Path,
) -> None:
    write_file(
        ext_path,
        "\n".join(
            [
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,digitalSignature,keyEncipherment",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            ]
        )
        + "\n",
    )
    run_checked(["openssl", "genrsa", "-out", str(key_path), "2048"])
    set_private_permissions(key_path)
    run_checked(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_path),
            "-subj",
            f"/CN={common_name}",
            "-out",
            str(csr_path),
        ]
    )
    run_checked(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            str(ca_cert_path),
            "-CAkey",
            str(ca_key_path),
            "-CAcreateserial",
            "-out",
            str(cert_path),
            "-days",
            "825",
            "-sha256",
            "-extfile",
            str(ext_path),
        ]
    )


def create_certificate_authority(
    workspace: Path,
    name: str,
) -> tuple[Path, Path]:
    private_directory = workspace / ".local" / name
    public_directory = workspace / f"{name}_public"
    private_directory.mkdir(parents=True, exist_ok=True)
    public_directory.mkdir(parents=True, exist_ok=True)
    ca_key_path = private_directory / f"{name}_ca_key.pem"
    ca_cert_path = public_directory / f"{name}_ca_cert.pem"

    run_checked(["openssl", "genrsa", "-out", str(ca_key_path), "2048"])
    set_private_permissions(ca_key_path)
    run_checked(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-key",
            str(ca_key_path),
            "-sha256",
            "-days",
            "3650",
            "-subj",
            f"/CN={name}",
            "-out",
            str(ca_cert_path),
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
        ]
    )
    return ca_cert_path, ca_key_path


def create_certificate_material(workspace: Path) -> CertificateMaterial:
    public_keys_directory = workspace / "public_keys"
    team_private_directory = workspace / ".local" / "teams" / "organizer-test"
    tournament_private_directory = workspace / ".local" / "tournament"
    public_keys_directory.mkdir(parents=True, exist_ok=True)
    team_private_directory.mkdir(parents=True, exist_ok=True)
    tournament_private_directory.mkdir(parents=True, exist_ok=True)

    ca_key_path = tournament_private_directory / "tournament_ca_key.pem"
    ca_cert_path = public_keys_directory / "tournament_ca_cert.pem"
    scorer_key_path = tournament_private_directory / "scorer_private_key.pem"
    scorer_csr_path = tournament_private_directory / "scorer.csr"
    scorer_cert_path = public_keys_directory / "scorer_cert.pem"
    scorer_ext_path = tournament_private_directory / "scorer.ext"
    team_key_path = team_private_directory / "team_private_key.pem"
    team_csr_path = team_private_directory / "team.csr"
    team_cert_path = public_keys_directory / "organizer-test_cert.pem"
    team_ext_path = team_private_directory / "team.ext"

    run_checked(["openssl", "genrsa", "-out", str(ca_key_path), "2048"], cwd=workspace)
    set_private_permissions(ca_key_path)
    run_checked(
        [
            "openssl",
            "req",
            "-x509",
            "-new",
            "-key",
            str(ca_key_path),
            "-sha256",
            "-days",
            "3650",
            "-subj",
            "/CN=HKPUG Tournament CA",
            "-out",
            str(ca_cert_path),
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
            "-addext",
            "subjectKeyIdentifier=hash",
        ],
        cwd=workspace,
    )

    issue_leaf_certificate(
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
        common_name="HKPUG Scorer",
        key_path=scorer_key_path,
        csr_path=scorer_csr_path,
        cert_path=scorer_cert_path,
        ext_path=scorer_ext_path,
    )
    issue_leaf_certificate(
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
        common_name="organizer-test",
        key_path=team_key_path,
        csr_path=team_csr_path,
        cert_path=team_cert_path,
        ext_path=team_ext_path,
    )

    team_cert_der = run_checked_bytes(
        [
            "openssl",
            "x509",
            "-in",
            str(team_cert_path),
            "-outform",
            "DER",
        ],
        cwd=workspace,
    ).stdout
    team_cert_sha256 = hashlib.sha256(team_cert_der).hexdigest()

    allowlist_path = workspace / "team_allowlist.json"
    write_file(
        allowlist_path,
        json.dumps(
            {
                "teams": [
                    {
                        "team_id": "organizer-test",
                        "cert_path": "public_keys/organizer-test_cert.pem",
                        "cert_sha256": team_cert_sha256,
                    }
                ]
            },
            indent=2,
        )
        + "\n",
    )

    return {
        "allowlist_path": allowlist_path,
        "ca_cert_path": ca_cert_path,
        "ca_key_path": ca_key_path,
        "scorer_cert_path": scorer_cert_path,
        "scorer_key_path": scorer_key_path,
        "team_cert_path": team_cert_path,
        "team_key_path": team_key_path,
    }


def create_submission_paths(
    workspace: Path, paths: CertificateMaterial
) -> SubmissionPaths:
    submission_directory = workspace / "submission"
    return {
        "allowlist_path": paths["allowlist_path"],
        "ca_cert_path": paths["ca_cert_path"],
        "ca_key_path": paths["ca_key_path"],
        "scorer_cert_path": paths["scorer_cert_path"],
        "scorer_key_path": paths["scorer_key_path"],
        "team_cert_path": paths["team_cert_path"],
        "team_key_path": paths["team_key_path"],
        "prompt_path": workspace / "prompt.txt",
        "submission_directory": submission_directory,
        "ciphertext_path": submission_directory / "prompt.txt.cms",
        "manifest_path": submission_directory / "manifest.json",
        "signature_path": submission_directory / "manifest.sig",
    }


def sign_manifest(manifest_path: Path, key_path: Path, signature_path: Path) -> None:
    run_checked(
        [
            "openssl",
            "dgst",
            "-sha256",
            "-sign",
            str(key_path),
            "-out",
            str(signature_path),
            str(manifest_path),
        ]
    )


def create_manual_submission(
    workspace: Path,
    prompt_text: str,
    *,
    recipient_cert_paths: list[Path],
    cipher_flag: str = "-aes-256-cbc",
) -> SubmissionPaths:
    certificate_material = create_certificate_material(workspace)
    paths = create_submission_paths(workspace, certificate_material)
    paths["submission_directory"].mkdir(parents=True, exist_ok=True)
    paths["prompt_path"].write_text(prompt_text, encoding="utf-8")

    prompt_bytes = prompt_text.encode("utf-8")
    manifest = {
        "schema_version": 1,
        "team_id": "organizer-test",
        "prompt_path": EXPECTED_PROMPT_PATH,
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "created_at": "2026-07-12T00:00:00Z",
    }
    paths["manifest_path"].write_bytes(canonical_manifest_bytes(manifest))
    sign_manifest(
        paths["manifest_path"], paths["team_key_path"], paths["signature_path"]
    )

    run_checked(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            cipher_flag,
            "-in",
            str(paths["prompt_path"]),
            "-outform",
            "DER",
            "-out",
            str(paths["ciphertext_path"]),
            *(str(path) for path in recipient_cert_paths),
        ],
        cwd=workspace,
    )
    return paths


def create_submission(workspace: Path, prompt_text: str) -> SubmissionPaths:
    paths = create_certificate_material(workspace)
    submission_paths = create_submission_paths(workspace, paths)
    submission_paths["submission_directory"].mkdir(parents=True, exist_ok=True)
    submission_paths["prompt_path"].write_text(prompt_text, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "team_id": "organizer-test",
        "prompt_path": EXPECTED_PROMPT_PATH,
        "prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "created_at": "2026-07-12T00:00:00Z",
    }
    submission_paths["manifest_path"].write_bytes(canonical_manifest_bytes(manifest))
    sign_manifest(
        submission_paths["manifest_path"],
        paths["team_key_path"],
        submission_paths["signature_path"],
    )
    run_checked(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-cbc",
            "-in",
            str(submission_paths["prompt_path"]),
            "-outform",
            "DER",
            "-out",
            str(submission_paths["ciphertext_path"]),
            str(paths["scorer_cert_path"]),
        ],
        cwd=workspace,
    )
    return submission_paths


def create_submission_archive(
    paths: SubmissionPaths,
    *,
    extra_entries: dict[str, bytes] | None = None,
) -> Path:
    archive_path = paths["submission_directory"] / "submission.zip"
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.write(paths["manifest_path"], "manifest.json")
        archive.write(paths["signature_path"], "manifest.sig")
        archive.write(paths["ciphertext_path"], "prompt.txt.cms")
        for name, content in (extra_entries or {}).items():
            archive.writestr(name, content)
    return archive_path


def create_raw_submission_archive(
    archive_path: Path,
    *,
    entries: dict[str, bytes] | None = None,
) -> Path:
    payloads = {name: b"x" for name in EXPECTED_ARCHIVE_ENTRIES}
    payloads.update(entries or {})
    with zipfile.ZipFile(
        archive_path,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
    ) as archive:
        for name, content in payloads.items():
            archive.writestr(name, content)
    return archive_path


def verify_paths(
    paths: SubmissionPaths,
    *,
    scorer_cert_path: Path | None = None,
    scorer_key_path: Path | None = None,
) -> None:
    verify_submission(
        submission_dir=paths["submission_directory"],
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_private_key_path=scorer_key_path or paths["scorer_key_path"],
        scorer_cert_path=scorer_cert_path or paths["scorer_cert_path"],
    )


def validate_envelope_paths(paths: SubmissionPaths) -> ValidatedEnvelope:
    return validate_submission_envelope(
        submission_dir=paths["submission_directory"],
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_cert_path=paths["scorer_cert_path"],
    )


def get_manifest_path(paths: SubmissionPaths) -> Path:
    return paths["manifest_path"]


def get_signature_path(paths: SubmissionPaths) -> Path:
    return paths["signature_path"]


def get_allowlist_path(paths: SubmissionPaths) -> Path:
    return paths["allowlist_path"]


def get_team_cert_path(paths: SubmissionPaths) -> Path:
    return paths["team_cert_path"]


def get_ca_cert_path(paths: SubmissionPaths) -> Path:
    return paths["ca_cert_path"]


def get_scorer_cert_path(paths: SubmissionPaths) -> Path:
    return paths["scorer_cert_path"]


def get_ciphertext_path(paths: SubmissionPaths) -> Path:
    return paths["ciphertext_path"]


def create_alternate_recipient(
    workspace: Path,
    base_paths: CertificateMaterial,
    *,
    common_name: str,
    issuer_name: str = "HKPUG Tournament CA",
) -> tuple[Path, Path]:
    if issuer_name == "HKPUG Tournament CA":
        ca_cert_path = base_paths["ca_cert_path"]
        ca_key_path = base_paths["ca_key_path"]
        private_directory = workspace / ".local" / common_name
        public_directory = workspace / "public_keys"
    else:
        ca_cert_path, ca_key_path = create_certificate_authority(workspace, issuer_name)
        private_directory = workspace / ".local" / issuer_name / common_name
        public_directory = workspace / f"{issuer_name}_public"
        public_directory.mkdir(parents=True, exist_ok=True)
    private_directory.mkdir(parents=True, exist_ok=True)

    key_path = private_directory / f"{common_name}_key.pem"
    csr_path = private_directory / f"{common_name}.csr"
    cert_path = public_directory / f"{common_name}_cert.pem"
    ext_path = private_directory / f"{common_name}.ext"
    issue_leaf_certificate(
        ca_cert_path=ca_cert_path,
        ca_key_path=ca_key_path,
        common_name=common_name,
        key_path=key_path,
        csr_path=csr_path,
        cert_path=cert_path,
        ext_path=ext_path,
    )
    return cert_path, key_path


def create_key_agreement_recipient(
    workspace: Path,
    base_paths: CertificateMaterial,
    *,
    common_name: str,
) -> tuple[Path, Path]:
    private_directory = workspace / ".local" / common_name
    public_directory = workspace / "public_keys"
    private_directory.mkdir(parents=True, exist_ok=True)
    public_directory.mkdir(parents=True, exist_ok=True)

    key_path = private_directory / f"{common_name}_key.pem"
    csr_path = private_directory / f"{common_name}.csr"
    cert_path = public_directory / f"{common_name}_cert.pem"
    ext_path = private_directory / f"{common_name}.ext"
    write_file(
        ext_path,
        "\n".join(
            [
                "basicConstraints=critical,CA:FALSE",
                "keyUsage=critical,keyAgreement",
                "subjectKeyIdentifier=hash",
                "authorityKeyIdentifier=keyid,issuer",
            ]
        )
        + "\n",
    )
    run_checked(
        [
            "openssl",
            "ecparam",
            "-name",
            "prime256v1",
            "-genkey",
            "-noout",
            "-out",
            str(key_path),
        ]
    )
    set_private_permissions(key_path)
    run_checked(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(key_path),
            "-subj",
            f"/CN={common_name}",
            "-out",
            str(csr_path),
        ]
    )
    run_checked(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(csr_path),
            "-CA",
            str(base_paths["ca_cert_path"]),
            "-CAkey",
            str(base_paths["ca_key_path"]),
            "-CAcreateserial",
            "-out",
            str(cert_path),
            "-days",
            "825",
            "-sha256",
            "-extfile",
            str(ext_path),
        ]
    )
    return cert_path, key_path


def write_expired_certificate(
    *,
    ca_cert_path: Path,
    ca_key_path: Path,
    leaf_key_path: Path,
    cert_path: Path,
    common_name: str,
) -> None:
    ca_certificate = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_private_key = load_test_rsa_private_key(ca_key_path)
    leaf_private_key = load_test_rsa_private_key(leaf_key_path)
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_certificate.subject)
        .public_key(leaf_private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=10))
        .not_valid_after(now - timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_private_key.public_key()
            ),
            critical=False,
        )
        .sign(ca_private_key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def write_bad_key_usage_certificate(
    *,
    ca_cert_path: Path,
    ca_key_path: Path,
    leaf_key_path: Path,
    cert_path: Path,
    common_name: str,
) -> None:
    ca_certificate = x509.load_pem_x509_certificate(ca_cert_path.read_bytes())
    ca_private_key = load_test_rsa_private_key(ca_key_path)
    leaf_private_key = load_test_rsa_private_key(leaf_key_path)
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)]))
        .issuer_name(ca_certificate.subject)
        .public_key(leaf_private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(leaf_private_key.public_key()),
            critical=False,
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_private_key.public_key()
            ),
            critical=False,
        )
        .sign(ca_private_key, hashes.SHA256())
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def run_verify_cli(paths: SubmissionPaths) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "hkpug_challenge.submission",
            "verify",
            "--submission-dir",
            str(paths["submission_directory"]),
            "--allowlist-path",
            str(paths["allowlist_path"]),
            "--tournament-ca-cert-path",
            str(paths["ca_cert_path"]),
            "--scorer-private-key-path",
            str(paths["scorer_key_path"]),
            "--scorer-cert-path",
            str(paths["scorer_cert_path"]),
        ],
        cwd=TOURNAMENT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def run_sign_manifest_cli(
    *,
    manifest_path: Path,
    private_key_path: Path,
    signature_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "hkpug_challenge.submission",
            "sign-manifest",
            "--manifest-path",
            str(manifest_path),
            "--private-key-path",
            str(private_key_path),
            "--signature-path",
            str(signature_path),
        ],
        cwd=TOURNAMENT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def mutate_ciphertext(paths: SubmissionPaths) -> None:
    ciphertext_bytes = paths["ciphertext_path"].read_bytes()
    paths["ciphertext_path"].write_bytes(ciphertext_bytes[:-1] + b"\x00")


def mutate_manifest_extra_field(paths: SubmissionPaths) -> None:
    paths["manifest_path"].write_text(
        json.dumps(
            json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
            | {"unexpected": "field"},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def mutate_signature(paths: SubmissionPaths) -> None:
    paths["signature_path"].write_bytes(b"broken-signature")


def mutate_team_id(paths: SubmissionPaths) -> None:
    _rewrite_and_resign_manifest(paths, team_id="different-team")


def mutate_prompt_path(paths: SubmissionPaths) -> None:
    _rewrite_and_resign_manifest(paths, prompt_path="submission/renamed.cms")


def test_submission_envelope_is_verifiable(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "Support policy in UTF-8: 用最少字數回答。")

    result = verify_submission(
        submission_dir=paths["submission_directory"],
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_private_key_path=paths["scorer_key_path"],
        scorer_cert_path=paths["scorer_cert_path"],
    )

    assert result.team_id == "organizer-test"
    assert result.prompt_text == "Support policy in UTF-8: 用最少字數回答。"
    assert (
        result.prompt_sha256
        == hashlib.sha256(result.prompt_text.encode("utf-8")).hexdigest()
    )


def test_public_envelope_validation_needs_no_private_key(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "A private participant prompt.")
    ciphertext_digest = hashlib.sha256(
        paths["ciphertext_path"].read_bytes()
    ).hexdigest()
    paths["scorer_key_path"].unlink()

    result = validate_envelope_paths(paths)

    assert result.team_id == "organizer-test"
    assert (
        result.prompt_sha256
        == hashlib.sha256(b"A private participant prompt.").hexdigest()
    )
    assert result.ciphertext_sha256 == ciphertext_digest
    assert not hasattr(result, "prompt_text")


@pytest.mark.parametrize(
    ("label", "mutator", "message"),
    [
        ("ciphertext", mutate_ciphertext, "ciphertext"),
        ("manifest", mutate_manifest_extra_field, "exactly"),
        ("signature", mutate_signature, "signature"),
        ("team-id", mutate_team_id, "allowlist"),
        ("prompt-path", mutate_prompt_path, "prompt_path"),
    ],
)
def test_verify_submission_rejects_basic_tampering(
    tmp_path: Path,
    label: str,
    mutator: PathMutator,
    message: str,
) -> None:
    del label
    paths = create_submission(tmp_path, "Minimal prompt.")
    mutator(paths)

    with pytest.raises(ValueError, match=message):
        verify_paths(paths)


def test_verify_submission_rejects_wrong_scorer_recipient(tmp_path: Path) -> None:
    base_paths = create_certificate_material(tmp_path)
    wrong_scorer_cert_path, _ = create_alternate_recipient(
        tmp_path,
        base_paths,
        common_name="Not The Trusted Scorer",
    )
    paths = create_manual_submission(
        tmp_path,
        "Minimal prompt.",
        recipient_cert_paths=[wrong_scorer_cert_path],
    )

    with pytest.raises(ValueError, match="trusted scorer recipient"):
        verify_paths(paths)


def test_verify_submission_rejects_multiple_cms_recipients(tmp_path: Path) -> None:
    base_paths = create_certificate_material(tmp_path)
    extra_recipient_cert_path, _ = create_alternate_recipient(
        tmp_path,
        base_paths,
        common_name="extra-recipient",
    )
    paths = create_manual_submission(
        tmp_path,
        "Minimal prompt.",
        recipient_cert_paths=[
            base_paths["scorer_cert_path"],
            extra_recipient_cert_path,
        ],
    )

    with pytest.raises(ValueError, match="exactly one recipient"):
        verify_paths(paths)


def test_verify_submission_rejects_scorer_ktri_plus_key_agreement_recipient(
    tmp_path: Path,
) -> None:
    base_paths = create_certificate_material(tmp_path)
    extra_recipient_cert_path, _ = create_key_agreement_recipient(
        tmp_path,
        base_paths,
        common_name="key-agreement-recipient",
    )
    paths = create_manual_submission(
        tmp_path,
        "Minimal prompt.",
        recipient_cert_paths=[
            base_paths["scorer_cert_path"],
            extra_recipient_cert_path,
        ],
    )

    with pytest.raises(ValueError, match="exactly one recipient"):
        verify_paths(paths)


def test_verify_submission_rejects_non_aes_256_cbc_cipher(tmp_path: Path) -> None:
    base_paths = create_certificate_material(tmp_path)
    paths = create_manual_submission(
        tmp_path,
        "Minimal prompt.",
        recipient_cert_paths=[base_paths["scorer_cert_path"]],
        cipher_flag="-aes-128-cbc",
    )

    with pytest.raises(ValueError, match="AES-256-CBC"):
        verify_paths(paths)


def test_verify_submission_rejects_misissued_scorer_cert(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    wrong_scorer_cert_path, wrong_scorer_key_path = create_alternate_recipient(
        tmp_path,
        paths,
        common_name="HKPUG Scorer",
        issuer_name="Wrong Tournament CA",
    )

    with pytest.raises(ValueError, match="scorer cert"):
        verify_paths(
            paths,
            scorer_cert_path=wrong_scorer_cert_path,
            scorer_key_path=wrong_scorer_key_path,
        )


def test_verify_submission_rejects_expired_scorer_cert(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    expired_scorer_cert_path = tmp_path / "public_keys" / "expired_scorer_cert.pem"
    write_expired_certificate(
        ca_cert_path=paths["ca_cert_path"],
        ca_key_path=paths["ca_key_path"],
        leaf_key_path=paths["scorer_key_path"],
        cert_path=expired_scorer_cert_path,
        common_name="HKPUG Scorer",
    )

    with pytest.raises(ValueError, match="expired"):
        verify_paths(paths, scorer_cert_path=expired_scorer_cert_path)


def test_verify_submission_rejects_wrong_scorer_cert_identity(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    wrong_scorer_cert_path, wrong_scorer_key_path = create_alternate_recipient(
        tmp_path,
        paths,
        common_name="Wrong Scorer Identity",
    )

    with pytest.raises(ValueError, match="scorer cert identity"):
        verify_paths(
            paths,
            scorer_cert_path=wrong_scorer_cert_path,
            scorer_key_path=wrong_scorer_key_path,
        )


def test_verify_submission_rejects_scorer_cert_without_key_encipherment(
    tmp_path: Path,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    bad_usage_cert_path = tmp_path / "public_keys" / "bad_usage_scorer_cert.pem"
    write_bad_key_usage_certificate(
        ca_cert_path=paths["ca_cert_path"],
        ca_key_path=paths["ca_key_path"],
        leaf_key_path=paths["scorer_key_path"],
        cert_path=bad_usage_cert_path,
        common_name="HKPUG Scorer",
    )

    with pytest.raises(ValueError, match="key encipherment"):
        verify_paths(paths, scorer_cert_path=bad_usage_cert_path)


def test_verify_submission_rejects_oversized_decrypted_plaintext(
    tmp_path: Path,
) -> None:
    base_paths = create_certificate_material(tmp_path)
    paths = create_manual_submission(
        tmp_path,
        "a" * (MAX_PROMPT_BYTES + 1),
        recipient_cert_paths=[base_paths["scorer_cert_path"]],
    )

    with pytest.raises(ValueError, match="8192 bytes"):
        verify_paths(paths)


@pytest.mark.parametrize(
    ("path_getter", "message"),
    [
        (get_manifest_path, "Manifest file is too large"),
        (get_signature_path, "Manifest signature file is too large"),
        (get_allowlist_path, "Team allowlist file is too large"),
        (get_team_cert_path, "Certificate file is too large"),
        (get_ca_cert_path, "Certificate file is too large"),
        (get_scorer_cert_path, "Certificate file is too large"),
        (get_ciphertext_path, "Prompt ciphertext file is too large"),
    ],
)
def test_verify_submission_rejects_oversized_untrusted_files(
    tmp_path: Path,
    path_getter: Callable[[SubmissionPaths], Path],
    message: str,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    path_getter(paths).write_bytes(b"x" * 200_000)

    with pytest.raises(ValueError, match=message):
        verify_paths(paths)


def test_verify_submission_rejects_symlinked_manifest(tmp_path: Path) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    actual_manifest_path = paths["submission_directory"] / "manifest.actual.json"
    actual_manifest_path.write_bytes(paths["manifest_path"].read_bytes())
    paths["manifest_path"].unlink()
    paths["manifest_path"].symlink_to(actual_manifest_path)

    with pytest.raises(ValueError, match="regular file"):
        verify_paths(paths)


def test_read_bounded_regular_file_uses_open_descriptor_after_metadata_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "submission.bin"
    original_content = b"original submission bytes"
    swapped_content = b"swapped submission bytes"
    path.write_bytes(original_content)
    replaced = False

    def replace_path_once() -> None:
        nonlocal replaced
        if replaced:
            return
        replaced = True
        path.unlink()
        path.write_bytes(swapped_content)

    original_open = os.open

    def racing_open(
        file: os.PathLike[str] | str | bytes,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened_path = os.fspath(file)
        if dir_fd is None:
            file_descriptor = original_open(file, flags, mode)
        else:
            file_descriptor = original_open(file, flags, mode, dir_fd=dir_fd)
        if opened_path == os.fspath(path):
            replace_path_once()
        return file_descriptor

    monkeypatch.setattr(os, "open", racing_open)

    assert read_bounded_regular_file(path, "Race test", 64) == original_content
    assert path.read_bytes() == swapped_content


def test_read_bounded_regular_file_rejects_growth_after_metadata_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "submission.bin"
    path.write_bytes(b"small")
    original_lstat = Path.lstat
    original_fstat = os.fstat
    grew = False

    def grow_path_once() -> None:
        nonlocal grew
        if grew:
            return
        grew = True
        with path.open("ab") as file:
            file.write(b"x" * 100)

    def racing_lstat(self: Path) -> os.stat_result:
        result = original_lstat(self)
        if self == path:
            grow_path_once()
        return result

    def racing_fstat(file_descriptor: int) -> os.stat_result:
        result = original_fstat(file_descriptor)
        grow_path_once()
        return result

    monkeypatch.setattr(Path, "lstat", racing_lstat)
    monkeypatch.setattr(os, "fstat", racing_fstat)

    with pytest.raises(ValueError, match="too large"):
        read_bounded_regular_file(path, "Race test", 16)


def test_read_bounded_regular_file_rejects_fifo_without_blocking(
    tmp_path: Path,
) -> None:
    if os.name == "nt" or not hasattr(os, "mkfifo"):
        pytest.skip("Named pipes are not portable on this platform.")

    path = tmp_path / "submission.pipe"
    os.mkfifo(path)

    timed_out = False

    def fail_on_timeout(_signum: int, _frame: Any) -> None:
        nonlocal timed_out
        timed_out = True
        raise AssertionError("FIFO verification blocked instead of rejecting promptly.")

    previous_handler = signal.signal(signal.SIGALRM, fail_on_timeout)
    signal.alarm(2)
    try:
        with pytest.raises(ValueError, match="regular file"):
            read_bounded_regular_file(path, "Race test", 64)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)

    assert not timed_out


def test_read_bounded_regular_file_rejects_non_regular_path_portably(
    tmp_path: Path,
) -> None:
    candidate = Path(os.devnull)
    if not candidate.exists():
        candidate = tmp_path

    with pytest.raises(ValueError, match="regular file"):
        read_bounded_regular_file(candidate, "Device test", 64)


def test_verify_submission_uses_same_ciphertext_bytes_for_inspection_and_decryption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import hkpug_challenge.submission as submission_module

    paths = create_submission(tmp_path, "Original prompt.")
    swapped_prompt_path = tmp_path / "swapped-prompt.txt"
    swapped_ciphertext_path = tmp_path / "swapped-prompt.txt.cms"
    swapped_prompt_path.write_text("Swapped prompt.", encoding="utf-8")
    run_checked(
        [
            "openssl",
            "cms",
            "-encrypt",
            "-binary",
            "-aes-256-cbc",
            "-in",
            str(swapped_prompt_path),
            "-outform",
            "DER",
            "-out",
            str(swapped_ciphertext_path),
            str(paths["scorer_cert_path"]),
        ],
        cwd=tmp_path,
    )
    swapped_ciphertext = swapped_ciphertext_path.read_bytes()
    original_inspect_ciphertext = submission_module.inspect_ciphertext

    def racing_inspect_ciphertext(
        ciphertext: Any,
        scorer_certificate: x509.Certificate,
    ) -> None:
        original_inspect_ciphertext(ciphertext, scorer_certificate)
        paths["ciphertext_path"].write_bytes(swapped_ciphertext)

    monkeypatch.setattr(
        submission_module,
        "inspect_ciphertext",
        racing_inspect_ciphertext,
    )

    result = verify_submission(
        submission_dir=paths["submission_directory"],
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_private_key_path=paths["scorer_key_path"],
        scorer_cert_path=paths["scorer_cert_path"],
    )

    assert result.prompt_text == "Original prompt."


def test_verify_submission_passes_openssl_snapshots_to_decryption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    original_ciphertext = paths["ciphertext_path"].read_bytes()
    original_scorer_key = paths["scorer_key_path"].read_bytes()
    original_scorer_cert = paths["scorer_cert_path"].read_bytes()
    observed_decrypt = False

    def fake_run(args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        del kwargs
        command = [str(part) for part in args]
        if command[:4] == ["openssl", "cms", "-cmsout", "-print"]:
            scorer_certificate = x509.load_pem_x509_certificate(original_scorer_cert)
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "algorithm: aes-256-cbc \n"
                    "d.ktri:\n"
                    f"  issuer: {scorer_certificate.issuer.rfc4514_string()}\n"
                    f"  serialNumber: 0x{scorer_certificate.serial_number:x}\n"
                ),
                stderr="",
            )

        assert command[:3] == ["openssl", "cms", "-decrypt"]
        nonlocal observed_decrypt
        observed_decrypt = True
        in_path = Path(command[command.index("-in") + 1])
        key_path = Path(command[command.index("-inkey") + 1])
        cert_path = Path(command[command.index("-recip") + 1])
        out_path = Path(command[command.index("-out") + 1])

        paths["ciphertext_path"].write_bytes(b"swapped ciphertext")
        paths["scorer_key_path"].write_bytes(b"swapped scorer key")
        paths["scorer_cert_path"].write_bytes(b"swapped scorer cert")

        assert in_path != paths["ciphertext_path"]
        assert key_path != paths["scorer_key_path"]
        assert cert_path != paths["scorer_cert_path"]
        assert in_path.read_bytes() == original_ciphertext
        assert key_path.read_bytes() == original_scorer_key
        assert cert_path.read_bytes() == original_scorer_cert

        out_path.write_bytes(b"Minimal prompt.")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr("hkpug_challenge.submission_crypto.subprocess.run", fake_run)

    verify_paths(paths)

    assert observed_decrypt


@pytest.mark.parametrize(
    "path_getter",
    [
        get_signature_path,
        get_allowlist_path,
        get_team_cert_path,
        get_ca_cert_path,
        get_scorer_cert_path,
        get_ciphertext_path,
    ],
)
def test_verify_submission_rejects_symlinked_untrusted_files(
    tmp_path: Path,
    path_getter: Callable[[SubmissionPaths], Path],
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    path = path_getter(paths)
    actual_path = path.with_suffix(path.suffix + ".actual")
    actual_path.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(actual_path)

    with pytest.raises(ValueError, match="regular file"):
        verify_paths(paths)


def test_verify_cli_reports_validation_errors_without_traceback(
    tmp_path: Path,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    mutate_signature(paths)

    result = run_verify_cli(paths)

    assert result.returncode != 0
    assert result.stderr.startswith("error:")
    assert "Traceback" not in result.stderr


def test_sign_manifest_cli_rejects_group_readable_team_private_key(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not enforced on Windows.")

    paths = create_submission(tmp_path, "Minimal prompt.")
    os.chmod(paths["team_key_path"], 0o644)

    result = run_sign_manifest_cli(
        manifest_path=paths["manifest_path"],
        private_key_path=paths["team_key_path"],
        signature_path=tmp_path / "group-readable.sig",
    )

    assert result.returncode != 0
    assert "private key" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()


@pytest.mark.parametrize("key_content", ["malformed", "encrypted"])
def test_sign_manifest_cli_reports_invalid_private_key_without_traceback(
    tmp_path: Path,
    key_content: str,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    invalid_key_path = tmp_path / f"{key_content}_private_key.pem"
    if key_content == "malformed":
        invalid_key_path.write_text("not a private key", encoding="utf-8")
    else:
        run_checked(
            [
                "openssl",
                "genrsa",
                "-aes256",
                "-passout",
                "pass:secret",
                "-out",
                str(invalid_key_path),
                "2048",
            ]
        )
    set_private_permissions(invalid_key_path)

    result = run_sign_manifest_cli(
        manifest_path=paths["manifest_path"],
        private_key_path=invalid_key_path,
        signature_path=tmp_path / f"{key_content}.sig",
    )

    assert result.returncode != 0
    assert result.stderr.startswith("error:")
    assert "private key" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_verify_submission_rejects_group_readable_scorer_private_key(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("POSIX mode bits are not enforced on Windows.")

    paths = create_submission(tmp_path, "Minimal prompt.")
    os.chmod(paths["scorer_key_path"], 0o644)

    with pytest.raises(ValueError, match="private key"):
        verify_paths(paths)


def test_submission_archive_validates_and_decrypts_existing_envelope(
    tmp_path: Path,
) -> None:
    paths = create_submission(tmp_path, "Answer from controlling evidence only.")
    archive_path = create_submission_archive(paths)

    validated = validate_submission_archive(
        submission_archive=archive_path,
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_cert_path=paths["scorer_cert_path"],
    )
    verified = verify_submission_archive(
        submission_archive=archive_path,
        allowlist_path=paths["allowlist_path"],
        tournament_ca_cert_path=paths["ca_cert_path"],
        scorer_private_key_path=paths["scorer_key_path"],
        scorer_cert_path=paths["scorer_cert_path"],
    )

    assert validated.team_id == "organizer-test"
    assert verified.prompt_text == "Answer from controlling evidence only."


@pytest.mark.parametrize(
    ("entry_name", "entry_content"),
    [
        ("prompt.txt", b"plaintext leak"),
        ("manifest.json", b"duplicate"),
    ],
)
def test_submission_archive_rejects_extra_or_duplicate_entries(
    tmp_path: Path,
    entry_name: str,
    entry_content: bytes,
) -> None:
    paths = create_submission(tmp_path, "Minimal prompt.")
    archive_path = create_submission_archive(paths)
    with zipfile.ZipFile(archive_path, mode="a") as archive:
        if entry_name == "manifest.json":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(entry_name, entry_content)
        else:
            archive.writestr(entry_name, entry_content)

    with pytest.raises(ValueError, match="archive"):
        validate_submission_archive(
            submission_archive=archive_path,
            allowlist_path=paths["allowlist_path"],
            tournament_ca_cert_path=paths["ca_cert_path"],
            scorer_cert_path=paths["scorer_cert_path"],
        )


def test_submission_archive_rejects_archive_larger_than_limit(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "submission.zip"
    archive_path.write_bytes(b"x" * (MAX_SUBMISSION_ARCHIVE_BYTES + 1))

    with pytest.raises(ValueError, match="Submission archive file is too large"):
        extract_submission_archive(archive_path, tmp_path / "output")


def test_submission_archive_rejects_entry_larger_than_limit(tmp_path: Path) -> None:
    manifest_limit = EXPECTED_ARCHIVE_ENTRIES["manifest.json"]
    archive_path = create_raw_submission_archive(
        tmp_path / "submission.zip",
        entries={"manifest.json": b"x" * (manifest_limit + 1)},
    )

    with pytest.raises(ValueError, match="manifest.json.*too large"):
        extract_submission_archive(archive_path, tmp_path / "output")


def test_submission_archive_rejects_traversal_without_writing_files(
    tmp_path: Path,
) -> None:
    archive_path = create_raw_submission_archive(
        tmp_path / "submission.zip",
        entries={"../manifest.json": b"escape"},
    )
    destination = tmp_path / "output"

    with pytest.raises(ValueError, match="archive"):
        extract_submission_archive(archive_path, destination)

    assert not destination.exists()
    assert not (tmp_path / "manifest.json").exists()


def test_submission_archive_rejects_symlink_entries(tmp_path: Path) -> None:
    archive_path = tmp_path / "submission.zip"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        symlink = zipfile.ZipInfo("manifest.json")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(symlink, b"target")
        archive.writestr("manifest.sig", b"x")
        archive.writestr("prompt.txt.cms", b"x")

    with pytest.raises(ValueError, match="regular files"):
        extract_submission_archive(archive_path, tmp_path / "output")


def test_submission_archive_rejects_symlink_destination(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("POSIX symlink semantics are required.")

    archive_path = create_raw_submission_archive(tmp_path / "submission.zip")
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "output"
    destination.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="destination.*directory"):
        extract_submission_archive(archive_path, destination)

    assert not any(outside.iterdir())


def _rewrite_and_resign_manifest(
    paths: SubmissionPaths,
    *,
    team_id: str | None = None,
    prompt_path: str | None = None,
) -> None:
    manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
    if team_id is not None:
        manifest["team_id"] = team_id
    if prompt_path is not None:
        manifest["prompt_path"] = prompt_path
    paths["manifest_path"].write_bytes(canonical_manifest_bytes(manifest))
    sign_manifest(
        paths["manifest_path"],
        paths["team_key_path"],
        paths["signature_path"],
    )
