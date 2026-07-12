package main

import (
	"crypto/rsa"
	"crypto/x509"
	_ "embed"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"runtime"
	"time"

	helper "github.com/hkpug/hkpug-opik-helper"
)

const (
	maxPrivateKeyBytes  = 16 * 1024
	maxCertificateBytes = 16 * 1024
	maxFeedbackBytes    = 128 * 1024 * 1024
)

var version = "dev"

//go:embed scorer_cert.pem
var scorerCertificatePEM []byte

func main() {
	os.Exit(run(os.Args[1:], os.Stdout, os.Stderr))
}

func run(args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		printUsage(stderr)
		return 2
	}

	var err error
	switch args[0] {
	case "help", "-h", "--help":
		printUsage(stdout)
		return 0
	case "version", "--version":
		fmt.Fprintf(stdout, "hkpug-opik-helper %s\n", version)
		return 0
	case "doctor":
		err = runDoctor(args[1:], stdout, stderr)
	case "pack":
		err = runPack(args[1:], stdout, stderr)
	case "inspect":
		err = runInspect(args[1:], stdout, stderr)
	case "decrypt":
		err = runDecrypt(args[1:], stdout, stderr)
	case "load":
		err = runLoad(args[1:], stdout, stderr)
	default:
		fmt.Fprintf(stderr, "error: unknown command %q\n\n", args[0])
		printUsage(stderr)
		return 2
	}
	if err != nil {
		fmt.Fprintf(stderr, "error: %v\n", err)
		return 1
	}
	return 0
}

func runDoctor(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("doctor", flag.ContinueOnError)
	flags.SetOutput(stderr)
	teamID := flags.String("team-id", "", "registered team ID")
	privateKeyPath := flags.String("private-key", "", "path to the team private key")
	teamCertificatePath := flags.String("team-cert", "", "path to the team certificate")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if err := requireFlags(map[string]string{
		"--team-id":     *teamID,
		"--private-key": *privateKeyPath,
		"--team-cert":   *teamCertificatePath,
	}); err != nil {
		return err
	}
	privateKey, err := loadPrivateKey(*privateKeyPath)
	if err != nil {
		return err
	}
	teamCertificate, err := loadCertificate(*teamCertificatePath)
	if err != nil {
		return err
	}
	if err := helper.Doctor(*teamID, privateKey, teamCertificate, time.Now().UTC()); err != nil {
		return err
	}
	fmt.Fprintf(stdout, "%s is ready: the private key matches the team certificate.\n", *teamID)
	return nil
}

func runPack(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("pack", flag.ContinueOnError)
	flags.SetOutput(stderr)
	teamID := flags.String("team-id", "", "registered team ID")
	privateKeyPath := flags.String("private-key", "", "path to the team private key")
	promptPath := flags.String("prompt", "submission/prompt.txt", "path to the plaintext prompt")
	outputPath := flags.String("out", "submission/submission.zip", "submission ZIP path")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if err := requireFlags(map[string]string{
		"--team-id":     *teamID,
		"--private-key": *privateKeyPath,
		"--prompt":      *promptPath,
		"--out":         *outputPath,
	}); err != nil {
		return err
	}
	privateKey, err := loadPrivateKey(*privateKeyPath)
	if err != nil {
		return err
	}
	prompt, err := readBoundedRegularFile(*promptPath, helper.MaxPromptBytes, "prompt")
	if err != nil {
		return err
	}
	scorerCertificate, err := helper.ParseCertificatePEM(scorerCertificatePEM)
	if err != nil {
		return fmt.Errorf("embedded organizer certificate: %w", err)
	}

	if err := writeSubmissionAtomically(*outputPath, func(output io.Writer) error {
		_, packErr := helper.Pack(helper.PackOptions{
			TeamID:            *teamID,
			Prompt:            prompt,
			TeamPrivateKey:    privateKey,
			ScorerCertificate: scorerCertificate,
			CreatedAt:         time.Now().UTC(),
			Output:            output,
		})
		return packErr
	}); err != nil {
		return err
	}
	fmt.Fprintf(stdout, "Wrote %s. Commit only this encrypted submission file.\n", *outputPath)
	return nil
}

func runInspect(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("inspect", flag.ContinueOnError)
	flags.SetOutput(stderr)
	submissionPath := flags.String("submission", "submission/submission.zip", "submission ZIP path")
	teamCertificatePath := flags.String("team-cert", "", "path to the team certificate")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if err := requireFlags(map[string]string{
		"--submission": *submissionPath,
		"--team-cert":  *teamCertificatePath,
	}); err != nil {
		return err
	}
	payload, err := readBoundedRegularFile(*submissionPath, helper.MaxSubmissionBytes, "submission archive")
	if err != nil {
		return err
	}
	teamCertificate, err := loadCertificate(*teamCertificatePath)
	if err != nil {
		return err
	}
	manifest, err := helper.Inspect(payload, teamCertificate)
	if err != nil {
		return err
	}
	encoded, err := helper.MarshalManifest(manifest)
	if err != nil {
		return err
	}
	fmt.Fprintln(stdout, string(encoded))
	return nil
}

func runDecrypt(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("decrypt", flag.ContinueOnError)
	flags.SetOutput(stderr)
	artifactPath := flags.String("artifact", "discovery-feedback.cms", "encrypted feedback artifact")
	privateKeyPath := flags.String("private-key", "", "path to the team private key")
	teamCertificatePath := flags.String("team-cert", "", "path to the team certificate")
	outputPath := flags.String("out", "feedback", "empty output directory")
	if err := flags.Parse(args); err != nil {
		return err
	}
	if err := requireFlags(map[string]string{
		"--artifact":    *artifactPath,
		"--private-key": *privateKeyPath,
		"--team-cert":   *teamCertificatePath,
		"--out":         *outputPath,
	}); err != nil {
		return err
	}
	privateKey, err := loadPrivateKey(*privateKeyPath)
	if err != nil {
		return err
	}
	teamCertificate, err := loadCertificate(*teamCertificatePath)
	if err != nil {
		return err
	}
	if err := helper.Doctor(teamCertificate.Subject.CommonName, privateKey, teamCertificate, time.Now().UTC()); err != nil {
		return err
	}
	ciphertext, err := readBoundedRegularFile(*artifactPath, maxFeedbackBytes, "feedback artifact")
	if err != nil {
		return err
	}
	paths, err := helper.DecryptFeedback(ciphertext, teamCertificate, privateKey, *outputPath)
	if err != nil {
		return err
	}
	fmt.Fprintf(stdout, "Decrypted %d feedback files into %s.\n", len(paths), *outputPath)
	return nil
}

func runLoad(args []string, stdout, stderr io.Writer) error {
	flags := flag.NewFlagSet("load", flag.ContinueOnError)
	flags.SetOutput(stderr)
	feedbackPath := flags.String("feedback", "feedback", "decrypted feedback directory")
	opikURL := flags.String("opik-url", "http://localhost:5173/api", "local Opik API URL")
	workspace := flags.String("workspace", "default", "Opik workspace name")
	if err := flags.Parse(args); err != nil {
		return err
	}
	result, err := helper.LoadOpik(helper.LoadOpikOptions{
		FeedbackDirectory: *feedbackPath,
		BaseURL:           *opikURL,
		Workspace:         *workspace,
	})
	if err != nil {
		return err
	}
	payload, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return fmt.Errorf("encode Opik import result: %w", err)
	}
	fmt.Fprintln(stdout, string(payload))
	return nil
}

func loadPrivateKey(path string) (*rsa.PrivateKey, error) {
	if err := requirePrivatePermissions(path); err != nil {
		return nil, err
	}
	payload, err := readBoundedRegularFile(path, maxPrivateKeyBytes, "private key")
	if err != nil {
		return nil, err
	}
	key, err := helper.ParsePrivateKeyPEM(payload)
	if err != nil {
		return nil, err
	}
	return key, nil
}

func loadCertificate(path string) (*x509.Certificate, error) {
	payload, err := readBoundedRegularFile(path, maxCertificateBytes, "certificate")
	if err != nil {
		return nil, err
	}
	certificate, err := helper.ParseCertificatePEM(payload)
	if err != nil {
		return nil, err
	}
	return certificate, nil
}

func readBoundedRegularFile(path string, limit int, label string) ([]byte, error) {
	info, err := os.Lstat(path)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", label, err)
	}
	if !info.Mode().IsRegular() {
		return nil, fmt.Errorf("%s must be a regular file", label)
	}
	if info.Size() > int64(limit) {
		return nil, fmt.Errorf("%s exceeds the %d-byte limit", label, limit)
	}
	file, err := os.Open(path)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w", label, err)
	}
	defer file.Close()
	payload, err := io.ReadAll(io.LimitReader(file, int64(limit)+1))
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", label, err)
	}
	if len(payload) > limit {
		return nil, fmt.Errorf("%s exceeds the %d-byte limit", label, limit)
	}
	return payload, nil
}

func requirePrivatePermissions(path string) error {
	if runtime.GOOS == "windows" {
		return nil
	}
	info, err := os.Lstat(path)
	if err != nil {
		return fmt.Errorf("read private key permissions: %w", err)
	}
	if info.Mode().Perm()&0o077 != 0 {
		return errors.New("private key permissions must deny access to group and other users; run chmod 600 on the key")
	}
	return nil
}

func writeSubmissionAtomically(outputPath string, write func(io.Writer) error) (returnErr error) {
	directory := filepath.Dir(outputPath)
	if err := os.MkdirAll(directory, 0o700); err != nil {
		return fmt.Errorf("create submission directory: %w", err)
	}
	temporary, err := os.CreateTemp(directory, ".submission-*.zip")
	if err != nil {
		return fmt.Errorf("create temporary submission: %w", err)
	}
	temporaryPath := temporary.Name()
	defer func() {
		if returnErr != nil {
			_ = temporary.Close()
			_ = os.Remove(temporaryPath)
		}
	}()
	if err := temporary.Chmod(0o600); err != nil {
		return fmt.Errorf("protect temporary submission: %w", err)
	}
	if err := write(temporary); err != nil {
		return err
	}
	if err := temporary.Sync(); err != nil {
		return fmt.Errorf("sync submission: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return fmt.Errorf("close submission: %w", err)
	}
	if err := os.Rename(temporaryPath, outputPath); err != nil {
		if removeErr := os.Remove(outputPath); removeErr != nil && !os.IsNotExist(removeErr) {
			return fmt.Errorf("replace submission: %w", err)
		}
		if retryErr := os.Rename(temporaryPath, outputPath); retryErr != nil {
			return fmt.Errorf("write submission: %w", retryErr)
		}
	}
	return nil
}

func requireFlags(values map[string]string) error {
	for flagName, value := range values {
		if value == "" {
			return fmt.Errorf("%s is required", flagName)
		}
	}
	return nil
}

func printUsage(output io.Writer) {
	fmt.Fprintln(output, `hkpug-opik-helper protects tournament submissions and feedback.

Usage:
  hkpug-opik-helper doctor  --team-id ID --private-key PATH --team-cert PATH
  hkpug-opik-helper pack    --team-id ID --private-key PATH [--prompt PATH] [--out PATH]
  hkpug-opik-helper inspect [--submission PATH] --team-cert PATH
  hkpug-opik-helper decrypt [--artifact PATH] --private-key PATH --team-cert PATH [--out DIR]
  hkpug-opik-helper load    [--feedback DIR] [--opik-url URL] [--workspace NAME]
  hkpug-opik-helper version`)
}
