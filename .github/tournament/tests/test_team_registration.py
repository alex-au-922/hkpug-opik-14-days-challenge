from __future__ import annotations

from pathlib import Path

from hkpug_challenge.submission import (
    load_allowlist,
    load_certificate,
    require_allowlist_digest,
    require_team_identity,
    require_team_key_usage,
    verify_leaf_certificate_against_ca,
)


TOURNAMENT_ROOT = Path(__file__).resolve().parents[1]


def test_fifteen_team_ids_are_registered_without_placeholder_names() -> None:
    allowlist_path = TOURNAMENT_ROOT / "team_allowlist.json"
    allowlist = load_allowlist(allowlist_path)
    participants = [
        entry for entry in allowlist.teams if entry.team_id != "organizer-test"
    ]

    assert [entry.team_id for entry in participants] == [
        f"team-{number:02d}" for number in range(1, 16)
    ]
    assert all(entry.display_name is None for entry in participants)

    ca_certificate = load_certificate(
        TOURNAMENT_ROOT / "public_keys" / "tournament_ca_cert.pem"
    )
    for entry in participants:
        certificate = load_certificate(TOURNAMENT_ROOT / entry.cert_path)
        require_allowlist_digest(certificate, entry.cert_sha256)
        require_team_identity(certificate, entry.team_id)
        require_team_key_usage(certificate)
        verify_leaf_certificate_against_ca(
            certificate=certificate,
            ca_certificate=ca_certificate,
            label="Team certificate",
        )
