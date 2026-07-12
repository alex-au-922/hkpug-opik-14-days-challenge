#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 4 ]]; then
  printf 'usage: %s FEEDBACK_CMS TEAM_PRIVATE_KEY TEAM_CERT OUTPUT_DIRECTORY\n' "$0" >&2
  exit 2
fi

feedback_cms="$1"
team_private_key="$2"
team_cert="$3"
output_directory="$4"

mkdir -p "$output_directory"
archive="$output_directory/discovery-feedback.tar.gz"
openssl cms \
  -decrypt \
  -binary \
  -inform DER \
  -in "$feedback_cms" \
  -inkey "$team_private_key" \
  -recip "$team_cert" \
  -out "$archive"
tar -xzf "$archive" -C "$output_directory"
rm -f "$archive"
