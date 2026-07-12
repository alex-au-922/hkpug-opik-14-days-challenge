package helper

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"crypto"
	"crypto/aes"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"fmt"
	"io"
	"math/big"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"testing"
	"time"

	pkcs7 "github.com/smallstep/pkcs7"
)

func TestPackCreatesAnOpenSSLCompatibleSignedSubmission(t *testing.T) {
	teamKey, teamCertificate := testIdentity(t, "team-07", 7)
	scorerKey, scorerCertificate := testIdentity(t, "HKPUG Trusted Scorer", 8)
	prompt := []byte("Answer from trusted evidence and cite the controlling source.")
	createdAt := time.Date(2026, time.July, 13, 4, 5, 6, 0, time.UTC)

	var output bytes.Buffer
	manifest, err := Pack(PackOptions{
		TeamID:            "team-07",
		Prompt:            prompt,
		TeamPrivateKey:    teamKey,
		ScorerCertificate: scorerCertificate,
		CreatedAt:         createdAt,
		Output:            &output,
	})
	if err != nil {
		t.Fatalf("Pack returned an error: %v", err)
	}

	files := readZip(t, output.Bytes())
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	wantNames := []string{"manifest.json", "manifest.sig", "prompt.txt.cms"}
	if !equalStrings(names, wantNames) {
		t.Fatalf("archive entries = %v, want %v", names, wantNames)
	}

	if manifest.TeamID != "team-07" || manifest.CreatedAt != "2026-07-13T04:05:06Z" {
		t.Fatalf("unexpected manifest: %#v", manifest)
	}
	if manifest.PromptSHA256 != sha256Hex(prompt) {
		t.Fatalf("prompt digest = %q, want %q", manifest.PromptSHA256, sha256Hex(prompt))
	}

	digest := sha256.Sum256(files["manifest.json"])
	if err := rsa.VerifyPKCS1v15(&teamKey.PublicKey, crypto.Hash(0), digest[:], files["manifest.sig"]); err == nil {
		t.Fatal("signature unexpectedly verified without the SHA-256 identifier")
	}
	if err := rsa.VerifyPKCS1v15(&teamKey.PublicKey, crypto.SHA256, digest[:], files["manifest.sig"]); err != nil {
		t.Fatalf("manifest signature did not verify: %v", err)
	}

	envelope, err := pkcs7.Parse(files["prompt.txt.cms"])
	if err != nil {
		t.Fatalf("ciphertext is not CMS DER: %v", err)
	}
	plaintext, err := envelope.Decrypt(scorerCertificate, scorerKey)
	if err != nil {
		t.Fatalf("ciphertext did not decrypt: %v", err)
	}
	if !bytes.Equal(plaintext, prompt) {
		t.Fatalf("decrypted prompt = %q, want %q", plaintext, prompt)
	}

	inspected, err := Inspect(output.Bytes(), teamCertificate)
	if err != nil {
		t.Fatalf("Inspect returned an error: %v", err)
	}
	if inspected != manifest {
		t.Fatalf("inspected manifest = %#v, want %#v", inspected, manifest)
	}
}

func TestPackRejectsInvalidParticipantInput(t *testing.T) {
	teamKey, _ := testIdentity(t, "team-07", 7)
	_, scorerCertificate := testIdentity(t, "HKPUG Trusted Scorer", 8)
	tests := []struct {
		name   string
		teamID string
		prompt []byte
	}{
		{name: "empty prompt", teamID: "team-07", prompt: nil},
		{name: "oversized prompt", teamID: "team-07", prompt: bytes.Repeat([]byte("x"), MaxPromptBytes+1)},
		{name: "invalid UTF-8", teamID: "team-07", prompt: []byte{0xff}},
		{name: "NUL byte", teamID: "team-07", prompt: []byte("bad\x00prompt")},
		{name: "invalid team ID", teamID: "Team 07", prompt: []byte("valid")},
		{name: "manifest too large", teamID: strings.Repeat("a", maxManifestBytes), prompt: []byte("valid")},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			var output bytes.Buffer
			_, err := Pack(PackOptions{
				TeamID:            test.teamID,
				Prompt:            test.prompt,
				TeamPrivateKey:    teamKey,
				ScorerCertificate: scorerCertificate,
				CreatedAt:         time.Now(),
				Output:            &output,
			})
			if err == nil {
				t.Fatal("Pack unexpectedly succeeded")
			}
		})
	}
}

func TestDoctorRejectsCertificatesTheTournamentWillNotAccept(t *testing.T) {
	now := time.Date(2026, time.July, 13, 0, 0, 0, 0, time.UTC)
	for _, test := range []struct {
		name   string
		mutate func(*x509.Certificate)
	}{
		{
			name: "missing basic constraints",
			mutate: func(certificate *x509.Certificate) {
				certificate.BasicConstraintsValid = false
			},
		},
		{
			name: "CA certificate",
			mutate: func(certificate *x509.Certificate) {
				certificate.IsCA = true
			},
		},
	} {
		t.Run(test.name, func(t *testing.T) {
			key, certificate := testIdentity(t, "team-07", 7)
			test.mutate(certificate)
			if err := Doctor("team-07", key, certificate, now); err == nil {
				t.Fatal("Doctor unexpectedly accepted an invalid leaf certificate")
			}
		})
	}
}

func TestInspectRejectsSubmissionForAnotherTeamIdentity(t *testing.T) {
	teamKey, teamCertificate := testIdentity(t, "team-07", 7)
	_, scorerCertificate := testIdentity(t, "HKPUG Scorer", 8)
	var output bytes.Buffer
	if _, err := Pack(PackOptions{
		TeamID:            "other-team",
		Prompt:            []byte("valid prompt"),
		TeamPrivateKey:    teamKey,
		ScorerCertificate: scorerCertificate,
		CreatedAt:         time.Date(2026, time.July, 13, 4, 5, 6, 0, time.UTC),
		Output:            &output,
	}); err != nil {
		t.Fatal(err)
	}

	if _, err := Inspect(output.Bytes(), teamCertificate); err == nil {
		t.Fatal("Inspect unexpectedly accepted a manifest for another team identity")
	}
}

func TestInspectRejectsNonAES256Ciphertext(t *testing.T) {
	teamKey, teamCertificate := testIdentity(t, "team-07", 7)
	_, scorerCertificate := testIdentity(t, "HKPUG Scorer", 8)
	var output bytes.Buffer
	if _, err := Pack(PackOptions{
		TeamID:            "team-07",
		Prompt:            []byte("valid prompt"),
		TeamPrivateKey:    teamKey,
		ScorerCertificate: scorerCertificate,
		CreatedAt:         time.Date(2026, time.July, 13, 4, 5, 6, 0, time.UTC),
		Output:            &output,
	}); err != nil {
		t.Fatal(err)
	}
	files := readZip(t, output.Bytes())
	files[ciphertextFilename] = encryptCMSForTest(t, []byte("valid prompt"), scorerCertificate, pkcs7.EncryptionAlgorithmAES128CBC)
	archive := makeZip(t, []zipEntry{
		{name: manifestFilename, body: files[manifestFilename]},
		{name: signatureFilename, body: files[signatureFilename]},
		{name: ciphertextFilename, body: files[ciphertextFilename]},
	})

	if _, err := Inspect(archive, teamCertificate); err == nil {
		t.Fatal("Inspect unexpectedly accepted non-AES-256-CBC ciphertext")
	}
}

func TestInspectRejectsExtraAndDuplicateFiles(t *testing.T) {
	_, teamCertificate := testIdentity(t, "team-07", 7)
	for _, entries := range [][]zipEntry{
		{{name: "manifest.json"}, {name: "manifest.sig"}, {name: "prompt.txt.cms"}, {name: "prompt.txt"}},
		{{name: "manifest.json"}, {name: "manifest.json"}, {name: "manifest.sig"}, {name: "prompt.txt.cms"}},
		{{name: "../manifest.json"}, {name: "manifest.sig"}, {name: "prompt.txt.cms"}},
	} {
		if _, err := Inspect(makeZip(t, entries), teamCertificate); err == nil {
			t.Fatalf("Inspect unexpectedly accepted entries: %#v", entries)
		}
	}
}

func TestDecryptFeedbackExtractsRegularFiles(t *testing.T) {
	teamKey, teamCertificate := testIdentity(t, "team-07", 7)
	payload := makeTarGzip(t, []tarEntry{
		{name: "run.json", body: []byte("{\"schema_version\":1}\n")},
		{name: "traces/trace_payload.json", body: []byte("{\"traces\":[]}")},
	})

	ciphertext := encryptCMSForTest(t, payload, teamCertificate, pkcs7.EncryptionAlgorithmAES256CBC)

	output := t.TempDir()
	paths, err := DecryptFeedback(ciphertext, teamCertificate, teamKey, output)
	if err != nil {
		t.Fatalf("DecryptFeedback returned an error: %v", err)
	}
	wantPaths := []string{"run.json", "traces/trace_payload.json"}
	if !equalStrings(paths, wantPaths) {
		t.Fatalf("extracted paths = %v, want %v", paths, wantPaths)
	}
	content, err := os.ReadFile(filepath.Join(output, "run.json"))
	if err != nil {
		t.Fatal(err)
	}
	if string(content) != "{\"schema_version\":1}\n" {
		t.Fatalf("unexpected extracted content: %q", content)
	}
}

func TestExtractTarGzipAcceptsWorkflowRootEntries(t *testing.T) {
	payload := makeTarGzip(t, []tarEntry{
		{name: "./", typeflag: tar.TypeDir},
		{name: "./run.json", body: []byte("{\"schema_version\":1}\n")},
		{name: "./trace_payload.json", body: []byte("{\"traces\":[]}")},
	})
	output := filepath.Join(t.TempDir(), "feedback")

	paths, err := ExtractTarGzip(payload, output)
	if err != nil {
		t.Fatalf("ExtractTarGzip rejected the workflow tar layout: %v", err)
	}
	wantPaths := []string{"run.json", "trace_payload.json"}
	if !equalStrings(paths, wantPaths) {
		t.Fatalf("extracted paths = %v, want %v", paths, wantPaths)
	}
}

func TestExtractTarGzipRejectsTraversal(t *testing.T) {
	parent := t.TempDir()
	output := filepath.Join(parent, "feedback")
	payload := makeTarGzip(t, []tarEntry{{name: "../escape.txt", body: []byte("bad")}})
	if _, err := ExtractTarGzip(payload, output); err == nil {
		t.Fatal("ExtractTarGzip unexpectedly accepted path traversal")
	}
	if _, err := os.Stat(filepath.Join(parent, "escape.txt")); !os.IsNotExist(err) {
		t.Fatalf("escape path exists or returned unexpected error: %v", err)
	}
}

func TestExtractTarGzipRejectsNonPortablePaths(t *testing.T) {
	for _, name := range []string{"C:/escape.txt", "NUL", "folder/trailing."} {
		t.Run(name, func(t *testing.T) {
			output := filepath.Join(t.TempDir(), "feedback")
			payload := makeTarGzip(t, []tarEntry{{name: name, body: []byte("bad")}})
			if _, err := ExtractTarGzip(payload, output); err == nil {
				t.Fatalf("ExtractTarGzip unexpectedly accepted %q", name)
			}
		})
	}
}

func TestExtractTarGzipRejectsCollisionsBeforeWriting(t *testing.T) {
	for _, entries := range [][]tarEntry{
		{
			{name: "run.json", body: []byte("first")},
			{name: "run.json", body: []byte("second")},
		},
		{
			{name: "Run.json", body: []byte("first")},
			{name: "run.json", body: []byte("second")},
		},
		{
			{name: "traces", body: []byte("file")},
			{name: "traces/trace_payload.json", body: []byte("nested")},
		},
	} {
		output := filepath.Join(t.TempDir(), "feedback")
		if _, err := ExtractTarGzip(makeTarGzip(t, entries), output); err == nil {
			t.Fatalf("ExtractTarGzip unexpectedly accepted colliding entries: %#v", entries)
		}
		if directoryEntries, err := os.ReadDir(output); err == nil && len(directoryEntries) != 0 {
			t.Fatalf("rejected archive left partial output: %v", directoryEntries)
		}
	}
}

func TestDecryptFeedbackRejectsMalformedCiphertextWithoutPanicking(t *testing.T) {
	teamKey, teamCertificate := testIdentity(t, "team-07", 7)
	ciphertext := encryptCMSForTest(t, []byte("not important"), teamCertificate, pkcs7.EncryptionAlgorithmAES256CBC)
	malformed := truncateCMSEncryptedContent(t, ciphertext)

	if _, err := DecryptFeedback(malformed, teamCertificate, teamKey, t.TempDir()); err == nil {
		t.Fatal("DecryptFeedback unexpectedly accepted malformed encrypted content")
	}
}

type zipEntry struct {
	name string
	body []byte
}

type tarEntry struct {
	name     string
	body     []byte
	typeflag byte
}

func testIdentity(t *testing.T, commonName string, serial int64) (*rsa.PrivateKey, *x509.Certificate) {
	t.Helper()
	key, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, time.July, 13, 0, 0, 0, 0, time.UTC)
	template := &x509.Certificate{
		SerialNumber:          big.NewInt(serial),
		Subject:               pkix.Name{CommonName: commonName},
		Issuer:                pkix.Name{CommonName: commonName},
		NotBefore:             now.Add(-time.Hour),
		NotAfter:              now.Add(365 * 24 * time.Hour),
		KeyUsage:              x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment,
		BasicConstraintsValid: true,
	}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return key, certificate
}

func readZip(t *testing.T, payload []byte) map[string][]byte {
	t.Helper()
	reader, err := zip.NewReader(bytes.NewReader(payload), int64(len(payload)))
	if err != nil {
		t.Fatal(err)
	}
	files := make(map[string][]byte, len(reader.File))
	for _, file := range reader.File {
		stream, err := file.Open()
		if err != nil {
			t.Fatal(err)
		}
		content, err := io.ReadAll(stream)
		closeErr := stream.Close()
		if err != nil {
			t.Fatal(err)
		}
		if closeErr != nil {
			t.Fatal(closeErr)
		}
		files[file.Name] = content
	}
	return files
}

func makeZip(t *testing.T, entries []zipEntry) []byte {
	t.Helper()
	var payload bytes.Buffer
	writer := zip.NewWriter(&payload)
	for _, entry := range entries {
		file, err := writer.Create(entry.name)
		if err != nil {
			t.Fatal(err)
		}
		if _, err := file.Write(entry.body); err != nil {
			t.Fatal(err)
		}
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return payload.Bytes()
}

func makeTarGzip(t *testing.T, entries []tarEntry) []byte {
	t.Helper()
	var payload bytes.Buffer
	gzipWriter := gzip.NewWriter(&payload)
	tarWriter := tar.NewWriter(gzipWriter)
	for _, entry := range entries {
		mode := int64(0o600)
		if entry.typeflag == tar.TypeDir {
			mode = 0o700
		}
		header := &tar.Header{
			Name:     entry.name,
			Mode:     mode,
			Size:     int64(len(entry.body)),
			Typeflag: entry.typeflag,
		}
		if err := tarWriter.WriteHeader(header); err != nil {
			t.Fatal(err)
		}
		if _, err := tarWriter.Write(entry.body); err != nil {
			t.Fatal(err)
		}
	}
	if err := tarWriter.Close(); err != nil {
		t.Fatal(err)
	}
	if err := gzipWriter.Close(); err != nil {
		t.Fatal(err)
	}
	return payload.Bytes()
}

func encryptCMSForTest(t *testing.T, payload []byte, certificate *x509.Certificate, algorithm int) []byte {
	t.Helper()
	cmsEncryptionLock.Lock()
	defer cmsEncryptionLock.Unlock()
	previous := pkcs7.ContentEncryptionAlgorithm
	pkcs7.ContentEncryptionAlgorithm = algorithm
	defer func() { pkcs7.ContentEncryptionAlgorithm = previous }()
	ciphertext, err := pkcs7.Encrypt(payload, []*x509.Certificate{certificate})
	if err != nil {
		t.Fatalf("encrypt CMS fixture: %v", err)
	}
	return ciphertext
}

type testCMSContentInfo struct {
	ContentType asn1.ObjectIdentifier
	Content     asn1.RawValue `asn1:"explicit,tag:0"`
}

type testCMSEnvelopedData struct {
	Version              int
	RecipientInfos       []testCMSRecipientInfo `asn1:"set"`
	EncryptedContentInfo testCMSEncryptedContentInfo
}

type testCMSRecipientInfo struct {
	Version                int
	IssuerAndSerialNumber  testCMSIssuerAndSerial
	KeyEncryptionAlgorithm pkix.AlgorithmIdentifier
	EncryptedKey           []byte
}

type testCMSIssuerAndSerial struct {
	IssuerName   asn1.RawValue
	SerialNumber *big.Int
}

type testCMSEncryptedContentInfo struct {
	ContentType                asn1.ObjectIdentifier
	ContentEncryptionAlgorithm pkix.AlgorithmIdentifier
	EncryptedContent           asn1.RawValue `asn1:"tag:0,optional"`
}

func truncateCMSEncryptedContent(t *testing.T, payload []byte) []byte {
	t.Helper()
	var contentInfo testCMSContentInfo
	if rest, err := asn1.Unmarshal(payload, &contentInfo); err != nil || len(rest) != 0 {
		t.Fatalf("parse CMS content info: %v", err)
	}
	var envelope testCMSEnvelopedData
	if rest, err := asn1.Unmarshal(contentInfo.Content.Bytes, &envelope); err != nil || len(rest) != 0 {
		t.Fatalf("parse CMS envelope: %v", err)
	}
	encryptedContent := envelope.EncryptedContentInfo.EncryptedContent.Bytes
	if len(encryptedContent) < aes.BlockSize {
		t.Fatalf("encrypted content is only %d bytes", len(encryptedContent))
	}
	envelope.EncryptedContentInfo.EncryptedContent.Bytes = encryptedContent[:len(encryptedContent)-1]
	envelope.EncryptedContentInfo.EncryptedContent.FullBytes = nil
	inner, err := asn1.Marshal(envelope)
	if err != nil {
		t.Fatal(err)
	}
	contentInfo.Content.Bytes = inner
	contentInfo.Content.FullBytes = nil
	result, err := asn1.Marshal(contentInfo)
	if err != nil {
		t.Fatal(err)
	}
	return result
}

func sha256Hex(value []byte) string {
	digest := sha256.Sum256(value)
	return fmt.Sprintf("%x", digest)
}

func equalStrings(left, right []string) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}
