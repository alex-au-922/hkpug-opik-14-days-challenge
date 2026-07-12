package main

import (
	"archive/zip"
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	helper "github.com/hkpug/hkpug-opik-helper"
)

func TestParticipantCanDoctorPackAndInspect(t *testing.T) {
	t.Parallel()

	directory := t.TempDir()
	privateKeyPath, certificatePath := writeTeamIdentity(t, directory, "team-07")
	promptPath := filepath.Join(directory, "prompt.txt")
	archivePath := filepath.Join(directory, "submission.zip")
	if err := os.WriteFile(promptPath, []byte("Use controlling evidence and cite it."), 0o600); err != nil {
		t.Fatal(err)
	}

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if code := run([]string{
		"doctor",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--team-cert", certificatePath,
	}, &stdout, &stderr); code != 0 {
		t.Fatalf("doctor returned %d: %s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "team-07 is ready") {
		t.Fatalf("unexpected doctor output: %q", stdout.String())
	}

	stdout.Reset()
	stderr.Reset()
	if code := run([]string{
		"pack",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--prompt", promptPath,
		"--out", archivePath,
	}, &stdout, &stderr); code != 0 {
		t.Fatalf("pack returned %d: %s", code, stderr.String())
	}
	if _, err := os.Stat(archivePath); err != nil {
		t.Fatalf("submission archive was not written: %v", err)
	}

	stdout.Reset()
	stderr.Reset()
	if code := run([]string{
		"inspect",
		"--submission", archivePath,
		"--team-cert", certificatePath,
	}, &stdout, &stderr); code != 0 {
		t.Fatalf("inspect returned %d: %s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), `"team_id": "team-07"`) {
		t.Fatalf("unexpected inspect output: %q", stdout.String())
	}
}

func TestPackLeavesMatchingSubmissionUnchanged(t *testing.T) {
	directory := t.TempDir()
	privateKeyPath, _ := writeTeamIdentity(t, directory, "team-07")
	promptPath := filepath.Join(directory, "prompt.txt")
	archivePath := filepath.Join(directory, "submission.zip")
	if err := os.WriteFile(promptPath, []byte("Use controlling evidence and cite it."), 0o600); err != nil {
		t.Fatal(err)
	}
	args := []string{
		"pack",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--prompt", promptPath,
		"--out", archivePath,
	}
	if code, _, stderr := runCommand(args); code != 0 {
		t.Fatalf("initial pack returned %d: %s", code, stderr)
	}
	before := snapshotFileAtHistoricalTime(t, archivePath)

	code, stdout, stderr := runCommand(args)

	if code != 0 {
		t.Fatalf("second pack returned %d: %s", code, stderr)
	}
	if !strings.Contains(stdout, "Unchanged") || !strings.Contains(stdout, "team ID and prompt SHA-256") {
		t.Fatalf("second pack did not report a semantic no-op: %q", stdout)
	}
	if stderr != "" {
		t.Fatalf("second pack wrote stderr: %q", stderr)
	}
	assertFileUnchanged(t, archivePath, before)
}

func TestPackRewritesSubmissionWhenSemanticInputChanges(t *testing.T) {
	tests := []struct {
		name            string
		requestedTeamID string
		requestedPrompt []byte
	}{
		{name: "team ID", requestedTeamID: "team-08", requestedPrompt: []byte("initial prompt")},
		{name: "prompt", requestedTeamID: "team-07", requestedPrompt: []byte("updated prompt")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			directory := t.TempDir()
			privateKeyPath, _ := writeTeamIdentity(t, directory, "team-07")
			promptPath := filepath.Join(directory, "prompt.txt")
			archivePath := filepath.Join(directory, "submission.zip")
			if err := os.WriteFile(promptPath, []byte("initial prompt"), 0o600); err != nil {
				t.Fatal(err)
			}
			initialArgs := []string{
				"pack",
				"--team-id", "team-07",
				"--private-key", privateKeyPath,
				"--prompt", promptPath,
				"--out", archivePath,
			}
			if code, _, stderr := runCommand(initialArgs); code != 0 {
				t.Fatalf("initial pack returned %d: %s", code, stderr)
			}
			before := snapshotFileAtHistoricalTime(t, archivePath)
			if err := os.WriteFile(promptPath, test.requestedPrompt, 0o600); err != nil {
				t.Fatal(err)
			}

			code, stdout, stderr := runCommand([]string{
				"pack",
				"--team-id", test.requestedTeamID,
				"--private-key", privateKeyPath,
				"--prompt", promptPath,
				"--out", archivePath,
			})

			if code != 0 {
				t.Fatalf("updated pack returned %d: %s", code, stderr)
			}
			if !strings.Contains(stdout, "Wrote ") || strings.Contains(stdout, "Unchanged") {
				t.Fatalf("updated pack output = %q", stdout)
			}
			after := snapshotFile(t, archivePath)
			if bytes.Equal(after.payload, before.payload) {
				t.Fatal("updated pack left the archive bytes unchanged")
			}
			if after.modTime.Equal(before.modTime) {
				t.Fatal("updated pack left the archive mtime unchanged")
			}
		})
	}
}

func TestPackFailsClosedForAnInvalidExistingSignature(t *testing.T) {
	directory := t.TempDir()
	privateKeyPath, _ := writeTeamIdentity(t, directory, "team-07")
	promptPath := filepath.Join(directory, "prompt.txt")
	archivePath := filepath.Join(directory, "submission.zip")
	if err := os.WriteFile(promptPath, []byte("valid prompt"), 0o600); err != nil {
		t.Fatal(err)
	}
	args := []string{
		"pack",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--prompt", promptPath,
		"--out", archivePath,
	}
	if code, _, stderr := runCommand(args); code != 0 {
		t.Fatalf("initial pack returned %d: %s", code, stderr)
	}
	payload, err := os.ReadFile(archivePath)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(archivePath, corruptZipEntry(t, payload, "manifest.sig"), 0o600); err != nil {
		t.Fatal(err)
	}
	before := snapshotFileAtHistoricalTime(t, archivePath)

	code, stdout, stderr := runCommand(args)

	if code == 0 {
		t.Fatalf("pack accepted an invalid existing signature with stdout %q", stdout)
	}
	if !strings.Contains(stderr, "signature") {
		t.Fatalf("pack error does not identify the invalid signature: %q", stderr)
	}
	if stdout != "" {
		t.Fatalf("failed pack wrote stdout: %q", stdout)
	}
	assertFileUnchanged(t, archivePath, before)
}

func TestPackFailsClosedForAnExistingSubmissionForAnotherOrganizer(t *testing.T) {
	directory := t.TempDir()
	privateKeyPath, _ := writeTeamIdentity(t, directory, "team-07")
	_, wrongScorerCertificatePath := writeTeamIdentity(t, t.TempDir(), "wrong-organizer")
	prompt := []byte("valid prompt")
	promptPath := filepath.Join(directory, "prompt.txt")
	archivePath := filepath.Join(directory, "submission.zip")
	if err := os.WriteFile(promptPath, prompt, 0o600); err != nil {
		t.Fatal(err)
	}
	teamKey, err := loadPrivateKey(privateKeyPath)
	if err != nil {
		t.Fatal(err)
	}
	wrongScorerCertificate, err := loadCertificate(wrongScorerCertificatePath)
	if err != nil {
		t.Fatal(err)
	}
	var archive bytes.Buffer
	if _, err := helper.Pack(helper.PackOptions{
		TeamID:            "team-07",
		Prompt:            prompt,
		TeamPrivateKey:    teamKey,
		ScorerCertificate: wrongScorerCertificate,
		CreatedAt:         time.Now().UTC(),
		Output:            &archive,
	}); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(archivePath, archive.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}
	before := snapshotFileAtHistoricalTime(t, archivePath)

	code, stdout, stderr := runCommand([]string{
		"pack",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--prompt", promptPath,
		"--out", archivePath,
	})

	if code == 0 {
		t.Fatalf("pack accepted the wrong organizer recipient with stdout %q", stdout)
	}
	if !strings.Contains(stderr, "recipient") {
		t.Fatalf("pack error does not identify the wrong recipient: %q", stderr)
	}
	if stdout != "" {
		t.Fatalf("failed pack wrote stdout: %q", stdout)
	}
	assertFileUnchanged(t, archivePath, before)
}

func TestPackRejectsAGroupReadablePrivateKey(t *testing.T) {
	if os.PathSeparator == '\\' {
		t.Skip("POSIX mode bits are not enforced on Windows")
	}
	directory := t.TempDir()
	privateKeyPath, _ := writeTeamIdentity(t, directory, "team-07")
	promptPath := filepath.Join(directory, "prompt.txt")
	if err := os.WriteFile(promptPath, []byte("valid prompt"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(privateKeyPath, 0o644); err != nil {
		t.Fatal(err)
	}

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	code := run([]string{
		"pack",
		"--team-id", "team-07",
		"--private-key", privateKeyPath,
		"--prompt", promptPath,
		"--out", filepath.Join(directory, "submission.zip"),
	}, &stdout, &stderr)

	if code == 0 || !strings.Contains(strings.ToLower(stderr.String()), "private key permissions") {
		t.Fatalf("pack returned %d with stderr %q", code, stderr.String())
	}
}

func TestInspectRejectsCiphertextForAnotherOrganizer(t *testing.T) {
	directory := t.TempDir()
	privateKeyPath, certificatePath := writeTeamIdentity(t, directory, "team-07")
	_, wrongScorerCertificatePath := writeTeamIdentity(t, t.TempDir(), "wrong-scorer")
	teamKey, err := loadPrivateKey(privateKeyPath)
	if err != nil {
		t.Fatal(err)
	}
	wrongScorerCertificate, err := loadCertificate(wrongScorerCertificatePath)
	if err != nil {
		t.Fatal(err)
	}
	var archive bytes.Buffer
	if _, err := helper.Pack(helper.PackOptions{
		TeamID:            "team-07",
		Prompt:            []byte("valid prompt"),
		TeamPrivateKey:    teamKey,
		ScorerCertificate: wrongScorerCertificate,
		CreatedAt:         time.Now().UTC(),
		Output:            &archive,
	}); err != nil {
		t.Fatal(err)
	}
	archivePath := filepath.Join(directory, "wrong-recipient.zip")
	if err := os.WriteFile(archivePath, archive.Bytes(), 0o600); err != nil {
		t.Fatal(err)
	}

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	code := run([]string{"inspect", "--submission", archivePath, "--team-cert", certificatePath}, &stdout, &stderr)
	if code == 0 || !strings.Contains(strings.ToLower(stderr.String()), "recipient") {
		t.Fatalf("inspect returned %d with stderr %q", code, stderr.String())
	}
}

func TestHelpListsTheLocalOpikLoadCommandAndFeedbackFilename(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if code := run([]string{"help"}, &stdout, &stderr); code != 0 {
		t.Fatalf("help returned %d: %s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "hkpug-opik-helper load") {
		t.Fatalf("help does not document load: %q", stdout.String())
	}
	if !strings.Contains(stdout.String(), "submission-feedback.cms") {
		t.Fatalf("help does not document the feedback filename: %q", stdout.String())
	}
	if strings.Contains(stdout.String(), "discovery-feedback.cms") {
		t.Fatalf("help still documents the legacy feedback filename: %q", stdout.String())
	}
}

func TestDecryptUsesSubmissionFeedbackDefaultAndHonorsLegacyOverride(t *testing.T) {
	directory := t.TempDir()
	privateKeyPath, certificatePath := writeTeamIdentity(t, directory, "team-07")
	outputPath := filepath.Join(directory, "feedback")

	code, _, stderr := runCommand([]string{
		"decrypt",
		"--private-key", privateKeyPath,
		"--team-cert", certificatePath,
		"--out", outputPath,
	})
	if code == 0 || !strings.Contains(stderr, "submission-feedback.cms") {
		t.Fatalf("decrypt default returned %d with stderr %q", code, stderr)
	}

	legacyPath := filepath.Join(directory, "discovery-feedback.cms")
	code, _, stderr = runCommand([]string{
		"decrypt",
		"--artifact", legacyPath,
		"--private-key", privateKeyPath,
		"--team-cert", certificatePath,
		"--out", outputPath,
	})
	if code == 0 || !strings.Contains(stderr, legacyPath) {
		t.Fatalf("decrypt legacy override returned %d with stderr %q", code, stderr)
	}
	if strings.Contains(stderr, "submission-feedback.cms") {
		t.Fatalf("decrypt ignored the explicit legacy path: %q", stderr)
	}
}

func writeTeamIdentity(t *testing.T, directory, teamID string) (string, string) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC()
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(7),
		Subject:               pkix.Name{CommonName: teamID},
		Issuer:                pkix.Name{CommonName: "Test CA"},
		NotBefore:             now.Add(-time.Hour),
		NotAfter:              now.Add(24 * time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}

	privateKeyPath := filepath.Join(directory, "team_private_key.pem")
	certificatePath := filepath.Join(directory, "team_cert.pem")
	privateKeyPEM := pem.EncodeToMemory(&pem.Block{Type: "RSA PRIVATE KEY", Bytes: x509.MarshalPKCS1PrivateKey(key)})
	certificatePEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	if err := os.WriteFile(privateKeyPath, privateKeyPEM, 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(certificatePath, certificatePEM, 0o644); err != nil {
		t.Fatal(err)
	}
	return privateKeyPath, certificatePath
}

type fileSnapshot struct {
	payload []byte
	modTime time.Time
}

func runCommand(args []string) (int, string, string) {
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	code := run(args, &stdout, &stderr)
	return code, stdout.String(), stderr.String()
}

func snapshotFileAtHistoricalTime(t *testing.T, path string) fileSnapshot {
	t.Helper()
	historicalTime := time.Date(2020, time.January, 2, 3, 4, 5, 0, time.UTC)
	if err := os.Chtimes(path, historicalTime, historicalTime); err != nil {
		t.Fatal(err)
	}
	return snapshotFile(t, path)
}

func snapshotFile(t *testing.T, path string) fileSnapshot {
	t.Helper()
	payload, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	return fileSnapshot{payload: payload, modTime: info.ModTime()}
}

func assertFileUnchanged(t *testing.T, path string, before fileSnapshot) {
	t.Helper()
	after := snapshotFile(t, path)
	if !bytes.Equal(after.payload, before.payload) {
		t.Fatal("archive bytes changed")
	}
	if !after.modTime.Equal(before.modTime) {
		t.Fatalf("archive mtime changed from %s to %s", before.modTime, after.modTime)
	}
}

func corruptZipEntry(t *testing.T, payload []byte, target string) []byte {
	t.Helper()
	reader, err := zip.NewReader(bytes.NewReader(payload), int64(len(payload)))
	if err != nil {
		t.Fatal(err)
	}
	var output bytes.Buffer
	writer := zip.NewWriter(&output)
	found := false
	for _, file := range reader.File {
		stream, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		body, readErr := io.ReadAll(stream)
		closeErr := stream.Close()
		if readErr != nil {
			t.Fatal(readErr)
		}
		if closeErr != nil {
			t.Fatal(closeErr)
		}
		if file.Name == target {
			if len(body) == 0 {
				t.Fatalf("ZIP entry %q is empty", target)
			}
			body[0] ^= 0xff
			found = true
		}
		header := file.FileHeader
		entry, err := writer.CreateHeader(&header)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := entry.Write(body); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	if !found {
		t.Fatalf("ZIP entry %q was not found", target)
	}
	return output.Bytes()
}
