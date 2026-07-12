package main

import (
	"bytes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
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

func TestHelpListsTheLocalOpikLoadCommand(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if code := run([]string{"help"}, &stdout, &stderr); code != 0 {
		t.Fatalf("help returned %d: %s", code, stderr.String())
	}
	if !strings.Contains(stdout.String(), "hkpug-opik-helper load") {
		t.Fatalf("help does not document load: %q", stdout.String())
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
		SerialNumber: big.NewInt(7),
		Subject:      pkix.Name{CommonName: teamID},
		Issuer:       pkix.Name{CommonName: "Test CA"},
		NotBefore:    now.Add(-time.Hour),
		NotAfter:     now.Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
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
