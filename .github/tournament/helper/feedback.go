package helper

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"crypto/rsa"
	"crypto/x509"
	"errors"
	"fmt"
	"io"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"

	pkcs7 "github.com/smallstep/pkcs7"
)

const (
	maxFeedbackCiphertextBytes = 128 * 1024 * 1024
	maxFeedbackExtractedBytes  = 128 * 1024 * 1024
	maxFeedbackFiles           = 512
)

type extractedFile struct {
	name      string
	payload   []byte
	directory bool
}

func DecryptFeedback(ciphertext []byte, teamCertificate *x509.Certificate, teamPrivateKey *rsa.PrivateKey, outputDirectory string) ([]string, error) {
	if len(ciphertext) == 0 || len(ciphertext) > maxFeedbackCiphertextBytes {
		return nil, errors.New("feedback artifact size is invalid")
	}
	if teamCertificate == nil || teamPrivateKey == nil {
		return nil, errors.New("team certificate and private key are required")
	}
	if err := validateCMSEnvelope(ciphertext, teamCertificate, "feedback artifact"); err != nil {
		return nil, err
	}
	envelope, err := pkcs7.Parse(ciphertext)
	if err != nil {
		return nil, fmt.Errorf("feedback artifact is not CMS DER: %w", err)
	}
	payload, err := decryptCMSEnvelope(envelope, teamCertificate, teamPrivateKey)
	if err != nil {
		return nil, fmt.Errorf("decrypt feedback artifact: %w", err)
	}
	return ExtractTarGzip(payload, outputDirectory)
}

func ExtractTarGzip(payload []byte, outputDirectory string) ([]string, error) {
	gzipReader, err := gzip.NewReader(bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("feedback payload is not gzip: %w", err)
	}
	tarReader := tar.NewReader(gzipReader)
	files := make([]extractedFile, 0)
	totalBytes := int64(0)
	for {
		header, err := tarReader.Next()
		if errors.Is(err, io.EOF) {
			break
		}
		if err != nil {
			_ = gzipReader.Close()
			return nil, fmt.Errorf("read feedback tar: %w", err)
		}
		if len(files) >= maxFeedbackFiles {
			_ = gzipReader.Close()
			return nil, errors.New("feedback archive contains too many entries")
		}
		name, err := cleanArchivePath(header.Name)
		if err != nil {
			_ = gzipReader.Close()
			return nil, err
		}
		if name == "" {
			if header.Typeflag != tar.TypeDir {
				_ = gzipReader.Close()
				return nil, errors.New("feedback archive contains an unsafe path")
			}
			continue
		}
		switch header.Typeflag {
		case tar.TypeDir:
			files = append(files, extractedFile{name: name, directory: true})
		case tar.TypeReg, tar.TypeRegA:
			if header.Size < 0 || header.Size > maxFeedbackExtractedBytes-totalBytes {
				_ = gzipReader.Close()
				return nil, errors.New("feedback archive exceeds the extraction limit")
			}
			content, err := io.ReadAll(io.LimitReader(tarReader, header.Size+1))
			if err != nil || int64(len(content)) != header.Size {
				_ = gzipReader.Close()
				return nil, errors.New("feedback archive contains a truncated file")
			}
			totalBytes += int64(len(content))
			files = append(files, extractedFile{name: name, payload: content})
		default:
			_ = gzipReader.Close()
			return nil, errors.New("feedback archive contains a non-regular entry")
		}
	}
	if err := gzipReader.Close(); err != nil {
		return nil, fmt.Errorf("finish feedback gzip: %w", err)
	}
	if err := validateExtractedFiles(files); err != nil {
		return nil, err
	}

	if err := os.MkdirAll(outputDirectory, 0o700); err != nil {
		return nil, fmt.Errorf("create feedback directory: %w", err)
	}
	entries, err := os.ReadDir(outputDirectory)
	if err != nil {
		return nil, fmt.Errorf("read feedback directory: %w", err)
	}
	if len(entries) != 0 {
		return nil, errors.New("feedback output directory must be empty")
	}

	for _, file := range files {
		target := filepath.Join(outputDirectory, filepath.FromSlash(file.name))
		if file.directory {
			if err := os.MkdirAll(target, 0o700); err != nil {
				return nil, fmt.Errorf("create feedback directory %q: %w", file.name, err)
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(target), 0o700); err != nil {
			return nil, fmt.Errorf("create feedback parent for %q: %w", file.name, err)
		}
		descriptor, err := os.OpenFile(target, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err != nil {
			return nil, fmt.Errorf("create feedback file %q: %w", file.name, err)
		}
		_, writeErr := descriptor.Write(file.payload)
		closeErr := descriptor.Close()
		if writeErr != nil {
			return nil, fmt.Errorf("write feedback file %q: %w", file.name, writeErr)
		}
		if closeErr != nil {
			return nil, fmt.Errorf("close feedback file %q: %w", file.name, closeErr)
		}
	}

	paths := make([]string, 0)
	for _, file := range files {
		if !file.directory {
			paths = append(paths, file.name)
		}
	}
	sort.Strings(paths)
	return paths, nil
}

func cleanArchivePath(name string) (string, error) {
	if name == "" || strings.ContainsAny(name, "\x00\\") {
		return "", errors.New("feedback archive contains an unsafe path")
	}
	for strings.HasPrefix(name, "./") {
		name = strings.TrimPrefix(name, "./")
	}
	if name == "" {
		return "", nil
	}
	if path.IsAbs(name) {
		return "", errors.New("feedback archive contains an unsafe path")
	}
	cleaned := path.Clean(name)
	if cleaned == "." || cleaned == ".." || strings.HasPrefix(cleaned, "../") || cleaned != strings.TrimSuffix(name, "/") {
		return "", errors.New("feedback archive contains an unsafe path")
	}
	for _, component := range strings.Split(cleaned, "/") {
		if !portableArchiveComponent(component) {
			return "", errors.New("feedback archive contains a non-portable path")
		}
	}
	return cleaned, nil
}

func portableArchiveComponent(component string) bool {
	if strings.Contains(component, ":") || strings.HasSuffix(component, ".") || strings.HasSuffix(component, " ") {
		return false
	}
	base := strings.ToUpper(strings.SplitN(component, ".", 2)[0])
	if base == "CON" || base == "PRN" || base == "AUX" || base == "NUL" {
		return false
	}
	return !(len(base) == 4 && (strings.HasPrefix(base, "COM") || strings.HasPrefix(base, "LPT")) && base[3] >= '1' && base[3] <= '9')
}

func validateExtractedFiles(files []extractedFile) error {
	entries := make(map[string]extractedFile, len(files))
	for _, file := range files {
		key := strings.ToLower(file.name)
		if _, exists := entries[key]; exists {
			return errors.New("feedback archive contains duplicate or case-colliding paths")
		}
		entries[key] = file
	}
	for key := range entries {
		for parent := path.Dir(key); parent != "."; parent = path.Dir(parent) {
			if entry, exists := entries[parent]; exists && !entry.directory {
				return errors.New("feedback archive contains conflicting file paths")
			}
		}
	}
	return nil
}
