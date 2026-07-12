#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
team_id="${TEAM_ID:-organizer-test}"
prompt_path="${PROMPT_PATH:-$repo_root/submission/prompt.txt}"
submission_dir="${SUBMISSION_DIR:-$repo_root/submission}"
scorer_cert_path="${SCORER_CERT_PATH:-$repo_root/.github/tournament/public_keys/scorer_cert.pem}"
team_private_key_path="${TEAM_PRIVATE_KEY_PATH:-$repo_root/.local/teams/$team_id/team_private_key.pem}"
manifest_path="$submission_dir/manifest.json"
signature_path="$submission_dir/manifest.sig"
ciphertext_path="$submission_dir/prompt.txt.cms"

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

require_file() {
  local path="$1"
  local message="$2"
  [[ -f "$path" ]] || fail "$message"
}

[[ -n "$team_id" ]] || fail "TEAM_ID must be set."

require_command openssl
require_command uv
require_file "$prompt_path" "Prompt text file not found. Set PROMPT_PATH to a UTF-8 text file."
require_file "$scorer_cert_path" "Scorer certificate not found. Set SCORER_CERT_PATH to the tracked scorer certificate."
require_file "$team_private_key_path" "Team private key not found. Set TEAM_PRIVATE_KEY_PATH to your local RSA private key."

mkdir -p "$submission_dir"

(
  cd "$repo_root"
  uv run python -m hkpug_challenge.submission create-manifest \
    --team-id "$team_id" \
    --prompt-path "$prompt_path" \
    --manifest-path "$manifest_path"
) || fail "Prompt validation failed. Ensure the prompt is valid UTF-8 text and no larger than 8192 bytes."

openssl cms \
  -encrypt \
  -binary \
  -aes-256-cbc \
  -in "$prompt_path" \
  -outform DER \
  -out "$ciphertext_path" \
  "$scorer_cert_path" || fail "OpenSSL failed to encrypt the prompt to the scorer certificate."

(
  cd "$repo_root"
  uv run python -m hkpug_challenge.submission sign-manifest \
    --manifest-path "$manifest_path" \
    --private-key-path "$team_private_key_path" \
    --signature-path "$signature_path"
) || fail "Manifest signing failed. Ensure the team private key is a readable RSA PEM key."

printf 'Wrote %s, %s, and %s\n' \
  "$ciphertext_path" \
  "$manifest_path" \
  "$signature_path"
