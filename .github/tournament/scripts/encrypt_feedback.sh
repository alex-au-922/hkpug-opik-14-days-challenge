#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  printf 'usage: %s BUNDLE_ARCHIVE TEAM_CERT OUTPUT_CMS\n' "$0" >&2
  exit 2
fi

bundle_archive="$1"
team_cert="$2"
output_cms="$3"

[[ -f "$bundle_archive" ]] || { printf 'error: bundle archive not found\n' >&2; exit 1; }
[[ -f "$team_cert" ]] || { printf 'error: team certificate not found\n' >&2; exit 1; }

mkdir -p "$(dirname "$output_cms")"
openssl cms \
  -encrypt \
  -binary \
  -aes-256-cbc \
  -in "$bundle_archive" \
  -outform DER \
  -out "$output_cms" \
  "$team_cert"

chmod 600 "$output_cms"
