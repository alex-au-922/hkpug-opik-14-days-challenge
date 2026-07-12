from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Callable, TypedDict

import pytest

from hkpug_challenge.submission import canonical_manifest_bytes, verify_submission


REPO_ROOT = Path(__file__).resolve().parents[1]
ENCRYPT_SCRIPT = REPO_ROOT / "submission" / "encrypt_prompt.sh"
EXPECTED_PROMPT_PATH = "submission/prompt.txt.cms"


class CertificateMaterial(TypedDict):
    allowlist_path: Path
    ca_cert_path: Path
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

    write_file(
        scorer_ext_path,
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
    run_checked(
        ["openssl", "genrsa", "-out", str(scorer_key_path), "2048"], cwd=workspace
    )
    run_checked(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(scorer_key_path),
            "-subj",
            "/CN=HKPUG Scorer",
            "-out",
            str(scorer_csr_path),
        ],
        cwd=workspace,
    )
    run_checked(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(scorer_csr_path),
            "-CA",
            str(ca_cert_path),
            "-CAkey",
            str(ca_key_path),
            "-CAcreateserial",
            "-out",
            str(scorer_cert_path),
            "-days",
            "825",
            "-sha256",
            "-extfile",
            str(scorer_ext_path),
        ],
        cwd=workspace,
    )

    write_file(
        team_ext_path,
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
    run_checked(
        ["openssl", "genrsa", "-out", str(team_key_path), "2048"], cwd=workspace
    )
    run_checked(
        [
            "openssl",
            "req",
            "-new",
            "-key",
            str(team_key_path),
            "-subj",
            "/CN=organizer-test",
            "-out",
            str(team_csr_path),
        ],
        cwd=workspace,
    )
    run_checked(
        [
            "openssl",
            "x509",
            "-req",
            "-in",
            str(team_csr_path),
            "-CA",
            str(ca_cert_path),
            "-CAkey",
            str(ca_key_path),
            "-CAcreateserial",
            "-out",
            str(team_cert_path),
            "-days",
            "825",
            "-sha256",
            "-extfile",
            str(team_ext_path),
        ],
        cwd=workspace,
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
        "scorer_cert_path": scorer_cert_path,
        "scorer_key_path": scorer_key_path,
        "team_cert_path": team_cert_path,
        "team_key_path": team_key_path,
    }


def create_submission(workspace: Path, prompt_text: str) -> SubmissionPaths:
    paths = create_certificate_material(workspace)
    prompt_path = workspace / "prompt.txt"
    submission_directory = workspace / "submission"
    prompt_path.write_text(prompt_text, encoding="utf-8")

    env = os.environ | {
        "TEAM_ID": "organizer-test",
        "PROMPT_PATH": str(prompt_path),
        "SCORER_CERT_PATH": str(paths["scorer_cert_path"]),
        "TEAM_PRIVATE_KEY_PATH": str(paths["team_key_path"]),
        "SUBMISSION_DIR": str(submission_directory),
    }
    run_checked([str(ENCRYPT_SCRIPT)], cwd=workspace, env=env)

    return SubmissionPaths(
        allowlist_path=paths["allowlist_path"],
        ca_cert_path=paths["ca_cert_path"],
        scorer_cert_path=paths["scorer_cert_path"],
        scorer_key_path=paths["scorer_key_path"],
        team_cert_path=paths["team_cert_path"],
        team_key_path=paths["team_key_path"],
        prompt_path=prompt_path,
        submission_directory=submission_directory,
        ciphertext_path=submission_directory / "prompt.txt.cms",
        manifest_path=submission_directory / "manifest.json",
        signature_path=submission_directory / "manifest.sig",
    )


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


def test_encrypt_prompt_script_produces_a_verifiable_submission(tmp_path: Path) -> None:
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
def test_verify_submission_rejects_tampering(
    tmp_path: Path,
    label: str,
    mutator: PathMutator,
    message: str,
) -> None:
    del label
    paths = create_submission(tmp_path, "Minimal prompt.")
    mutator(paths)

    with pytest.raises(ValueError, match=message):
        verify_submission(
            submission_dir=paths["submission_directory"],
            allowlist_path=paths["allowlist_path"],
            tournament_ca_cert_path=paths["ca_cert_path"],
            scorer_private_key_path=paths["scorer_key_path"],
            scorer_cert_path=paths["scorer_cert_path"],
        )


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


def test_encrypt_prompt_script_rejects_prompts_larger_than_8192_bytes(
    tmp_path: Path,
) -> None:
    paths = create_certificate_material(tmp_path)
    prompt_path = tmp_path / "prompt.txt"
    prompt_path.write_text("a" * 8193, encoding="utf-8")
    submission_directory = tmp_path / "submission"

    env = os.environ | {
        "TEAM_ID": "organizer-test",
        "PROMPT_PATH": str(prompt_path),
        "SCORER_CERT_PATH": str(paths["scorer_cert_path"]),
        "TEAM_PRIVATE_KEY_PATH": str(paths["team_key_path"]),
        "SUBMISSION_DIR": str(submission_directory),
    }
    result = subprocess.run(
        [str(ENCRYPT_SCRIPT)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "8192 bytes" in result.stderr
