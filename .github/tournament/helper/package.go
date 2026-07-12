package helper

import (
	"archive/zip"
	"bytes"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"sort"
	"sync"
	"time"

	pkcs7 "github.com/smallstep/pkcs7"
)

var cmsEncryptionLock sync.Mutex

type PackOptions struct {
	TeamID            string
	Prompt            []byte
	TeamPrivateKey    *rsa.PrivateKey
	ScorerCertificate *x509.Certificate
	CreatedAt         time.Time
	Output            io.Writer
}

func Pack(options PackOptions) (Manifest, error) {
	if options.TeamPrivateKey == nil {
		return Manifest{}, errors.New("team private key is required")
	}
	if options.ScorerCertificate == nil {
		return Manifest{}, errors.New("organizer certificate is required")
	}
	if options.Output == nil {
		return Manifest{}, errors.New("submission output is required")
	}
	if _, ok := options.ScorerCertificate.PublicKey.(*rsa.PublicKey); !ok {
		return Manifest{}, errors.New("organizer certificate must contain an RSA public key")
	}
	manifest, err := newManifest(options.TeamID, options.Prompt, options.CreatedAt)
	if err != nil {
		return Manifest{}, err
	}
	manifestBytes, err := canonicalManifest(manifest)
	if err != nil {
		return Manifest{}, err
	}

	digest := sha256.Sum256(manifestBytes)
	signature, err := rsa.SignPKCS1v15(rand.Reader, options.TeamPrivateKey, crypto.SHA256, digest[:])
	if err != nil {
		return Manifest{}, fmt.Errorf("sign manifest: %w", err)
	}
	ciphertext, err := encryptPrompt(options.Prompt, options.ScorerCertificate)
	if err != nil {
		return Manifest{}, err
	}
	if len(ciphertext) > maxCiphertextBytes {
		return Manifest{}, errors.New("encrypted prompt exceeds the submission limit")
	}

	archive := zip.NewWriter(options.Output)
	files := []struct {
		name    string
		payload []byte
	}{
		{name: manifestFilename, payload: manifestBytes},
		{name: signatureFilename, payload: signature},
		{name: ciphertextFilename, payload: ciphertext},
	}
	for _, file := range files {
		header := &zip.FileHeader{Name: file.name, Method: zip.Deflate}
		header.SetMode(0o600)
		header.SetModTime(options.CreatedAt.UTC().Truncate(time.Second))
		stream, err := archive.CreateHeader(header)
		if err != nil {
			_ = archive.Close()
			return Manifest{}, fmt.Errorf("create ZIP entry %s: %w", file.name, err)
		}
		if _, err := stream.Write(file.payload); err != nil {
			_ = archive.Close()
			return Manifest{}, fmt.Errorf("write ZIP entry %s: %w", file.name, err)
		}
	}
	if err := archive.Close(); err != nil {
		return Manifest{}, fmt.Errorf("finish submission ZIP: %w", err)
	}
	return manifest, nil
}

func Inspect(payload []byte, teamCertificate *x509.Certificate) (Manifest, error) {
	if len(payload) == 0 || len(payload) > MaxSubmissionBytes {
		return Manifest{}, errors.New("submission archive size is invalid")
	}
	if teamCertificate == nil {
		return Manifest{}, errors.New("team certificate is required")
	}
	publicKey, ok := teamCertificate.PublicKey.(*rsa.PublicKey)
	if !ok {
		return Manifest{}, errors.New("team certificate must contain an RSA public key")
	}
	files, err := readSubmissionZip(payload)
	if err != nil {
		return Manifest{}, err
	}
	manifest, err := parseManifest(files[manifestFilename])
	if err != nil {
		return Manifest{}, err
	}
	digest := sha256.Sum256(files[manifestFilename])
	if err := rsa.VerifyPKCS1v15(publicKey, crypto.SHA256, digest[:], files[signatureFilename]); err != nil {
		return Manifest{}, errors.New("manifest signature does not match the team certificate")
	}
	if _, err := pkcs7.Parse(files[ciphertextFilename]); err != nil {
		return Manifest{}, fmt.Errorf("prompt ciphertext is not CMS DER: %w", err)
	}
	return manifest, nil
}

func readSubmissionZip(payload []byte) (map[string][]byte, error) {
	reader, err := zip.NewReader(bytes.NewReader(payload), int64(len(payload)))
	if err != nil {
		return nil, fmt.Errorf("submission archive is not valid ZIP: %w", err)
	}
	expected := map[string]uint64{
		manifestFilename:   maxManifestBytes,
		signatureFilename:  maxSignatureBytes,
		ciphertextFilename: maxCiphertextBytes,
	}
	files := make(map[string][]byte, len(expected))
	for _, file := range reader.File {
		limit, ok := expected[file.Name]
		if !ok || file.FileInfo().IsDir() || file.Flags&0x1 != 0 {
			return nil, errors.New("submission archive contains an unexpected or unsafe entry")
		}
		if _, duplicate := files[file.Name]; duplicate {
			return nil, errors.New("submission archive contains duplicate entries")
		}
		if file.UncompressedSize64 > limit {
			return nil, fmt.Errorf("submission archive entry %q is too large", file.Name)
		}
		stream, err := file.Open()
		if err != nil {
			return nil, fmt.Errorf("open submission archive entry %q: %w", file.Name, err)
		}
		content, readErr := io.ReadAll(io.LimitReader(stream, int64(limit)+1))
		closeErr := stream.Close()
		if readErr != nil {
			return nil, fmt.Errorf("read submission archive entry %q: %w", file.Name, readErr)
		}
		if closeErr != nil {
			return nil, fmt.Errorf("close submission archive entry %q: %w", file.Name, closeErr)
		}
		if uint64(len(content)) > limit {
			return nil, fmt.Errorf("submission archive entry %q is too large", file.Name)
		}
		files[file.Name] = content
	}
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	if len(names) != 3 || names[0] != manifestFilename || names[1] != signatureFilename || names[2] != ciphertextFilename {
		return nil, errors.New("submission archive must contain exactly manifest.json, manifest.sig, and prompt.txt.cms")
	}
	return files, nil
}

func encryptPrompt(prompt []byte, scorerCertificate *x509.Certificate) ([]byte, error) {
	cmsEncryptionLock.Lock()
	defer cmsEncryptionLock.Unlock()

	previousContentAlgorithm := pkcs7.ContentEncryptionAlgorithm
	previousKeyAlgorithm := pkcs7.KeyEncryptionAlgorithm
	pkcs7.ContentEncryptionAlgorithm = pkcs7.EncryptionAlgorithmAES256CBC
	pkcs7.KeyEncryptionAlgorithm = pkcs7.OIDEncryptionAlgorithmRSA
	defer func() {
		pkcs7.ContentEncryptionAlgorithm = previousContentAlgorithm
		pkcs7.KeyEncryptionAlgorithm = previousKeyAlgorithm
	}()

	ciphertext, err := pkcs7.Encrypt(prompt, []*x509.Certificate{scorerCertificate})
	if err != nil {
		return nil, fmt.Errorf("encrypt prompt: %w", err)
	}
	return ciphertext, nil
}

func MarshalManifest(manifest Manifest) ([]byte, error) {
	return json.MarshalIndent(manifest, "", "  ")
}
