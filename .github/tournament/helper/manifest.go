package helper

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"time"
	"unicode/utf8"
)

const (
	MaxPromptBytes     = 8192
	MaxSubmissionBytes = 128 * 1024
	manifestFilename   = "manifest.json"
	signatureFilename  = "manifest.sig"
	ciphertextFilename = "prompt.txt.cms"
	expectedPromptPath = "submission/prompt.txt.cms"
	maxManifestBytes   = 4096
	maxSignatureBytes  = 8192
	maxCiphertextBytes = 65536
)

var teamIDPattern = regexp.MustCompile(`^[a-z0-9]+(?:-[a-z0-9]+)*$`)

type Manifest struct {
	SchemaVersion int    `json:"schema_version"`
	TeamID        string `json:"team_id"`
	PromptPath    string `json:"prompt_path"`
	PromptSHA256  string `json:"prompt_sha256"`
	CreatedAt     string `json:"created_at"`
}

func newManifest(teamID string, prompt []byte, createdAt time.Time) (Manifest, error) {
	if err := validateTeamID(teamID); err != nil {
		return Manifest{}, err
	}
	if err := validatePrompt(prompt); err != nil {
		return Manifest{}, err
	}
	digest := sha256.Sum256(prompt)
	return Manifest{
		SchemaVersion: 1,
		TeamID:        teamID,
		PromptPath:    expectedPromptPath,
		PromptSHA256:  hex.EncodeToString(digest[:]),
		CreatedAt:     createdAt.UTC().Truncate(time.Second).Format(time.RFC3339),
	}, nil
}

func canonicalManifest(manifest Manifest) ([]byte, error) {
	if err := validateManifest(manifest); err != nil {
		return nil, err
	}
	payload, err := json.Marshal(manifest)
	if err != nil {
		return nil, fmt.Errorf("encode manifest: %w", err)
	}
	payload = append(payload, '\n')
	if len(payload) > maxManifestBytes {
		return nil, errors.New("manifest exceeds the submission limit")
	}
	return payload, nil
}

func parseManifest(payload []byte) (Manifest, error) {
	if len(payload) == 0 || len(payload) > maxManifestBytes {
		return Manifest{}, errors.New("manifest size is invalid")
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	var manifest Manifest
	if err := decoder.Decode(&manifest); err != nil {
		return Manifest{}, fmt.Errorf("decode manifest: %w", err)
	}
	if decoder.More() {
		return Manifest{}, errors.New("manifest contains trailing JSON values")
	}
	canonical, err := canonicalManifest(manifest)
	if err != nil {
		return Manifest{}, err
	}
	if !bytes.Equal(payload, canonical) {
		return Manifest{}, errors.New("manifest is not in canonical form")
	}
	return manifest, nil
}

func validateManifest(manifest Manifest) error {
	if manifest.SchemaVersion != 1 {
		return errors.New("manifest schema_version must be 1")
	}
	if err := validateTeamID(manifest.TeamID); err != nil {
		return err
	}
	if manifest.PromptPath != expectedPromptPath {
		return fmt.Errorf("manifest prompt_path must be %q", expectedPromptPath)
	}
	if len(manifest.PromptSHA256) != sha256.Size*2 {
		return errors.New("manifest prompt_sha256 must be lowercase SHA-256 hex")
	}
	decoded, err := hex.DecodeString(manifest.PromptSHA256)
	if err != nil || hex.EncodeToString(decoded) != manifest.PromptSHA256 {
		return errors.New("manifest prompt_sha256 must be lowercase SHA-256 hex")
	}
	createdAt, err := time.Parse(time.RFC3339, manifest.CreatedAt)
	if err != nil || createdAt.Location() != time.UTC || createdAt.Nanosecond() != 0 {
		return errors.New("manifest created_at must be whole-second UTC RFC 3339")
	}
	return nil
}

func validateTeamID(teamID string) error {
	if !teamIDPattern.MatchString(teamID) {
		return errors.New("team ID must use lowercase letters, digits, and single hyphens")
	}
	return nil
}

func validatePrompt(prompt []byte) error {
	if len(prompt) == 0 {
		return errors.New("prompt must not be empty")
	}
	if len(prompt) > MaxPromptBytes {
		return fmt.Errorf("prompt must be at most %d bytes", MaxPromptBytes)
	}
	if !utf8.Valid(prompt) {
		return errors.New("prompt must be valid UTF-8")
	}
	if bytes.IndexByte(prompt, 0) >= 0 {
		return errors.New("prompt must not contain a NUL byte")
	}
	return nil
}
