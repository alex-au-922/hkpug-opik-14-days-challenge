package helper

import (
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
	"time"
)

func ParsePrivateKeyPEM(payload []byte) (*rsa.PrivateKey, error) {
	block, rest := pem.Decode(payload)
	if block == nil || len(rest) != 0 {
		return nil, errors.New("private key must contain one PEM block")
	}
	if x509.IsEncryptedPEMBlock(block) {
		return nil, errors.New("encrypted private keys are not supported")
	}

	var key any
	var err error
	switch block.Type {
	case "RSA PRIVATE KEY":
		key, err = x509.ParsePKCS1PrivateKey(block.Bytes)
	case "PRIVATE KEY":
		key, err = x509.ParsePKCS8PrivateKey(block.Bytes)
	default:
		return nil, fmt.Errorf("unsupported private key PEM type %q", block.Type)
	}
	if err != nil {
		return nil, fmt.Errorf("parse private key: %w", err)
	}
	rsaKey, ok := key.(*rsa.PrivateKey)
	if !ok {
		return nil, errors.New("private key must be RSA")
	}
	if rsaKey.N.BitLen() < 2048 {
		return nil, errors.New("private key must be at least 2048-bit RSA")
	}
	if err := rsaKey.Validate(); err != nil {
		return nil, fmt.Errorf("validate private key: %w", err)
	}
	return rsaKey, nil
}

func ParseCertificatePEM(payload []byte) (*x509.Certificate, error) {
	block, rest := pem.Decode(payload)
	if block == nil || block.Type != "CERTIFICATE" || len(rest) != 0 {
		return nil, errors.New("certificate must contain one CERTIFICATE PEM block")
	}
	certificate, err := x509.ParseCertificate(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("parse certificate: %w", err)
	}
	if _, ok := certificate.PublicKey.(*rsa.PublicKey); !ok {
		return nil, errors.New("certificate must contain an RSA public key")
	}
	return certificate, nil
}

func Doctor(teamID string, privateKey *rsa.PrivateKey, certificate *x509.Certificate, now time.Time) error {
	if err := validateTeamID(teamID); err != nil {
		return err
	}
	if privateKey == nil || certificate == nil {
		return errors.New("team private key and certificate are required")
	}
	publicKey, ok := certificate.PublicKey.(*rsa.PublicKey)
	if !ok || publicKey.N.Cmp(privateKey.N) != 0 || publicKey.E != privateKey.E {
		return errors.New("team private key does not match the team certificate")
	}
	if certificate.Subject.CommonName != teamID {
		return errors.New("team certificate common name does not match the team ID")
	}
	if !certificate.BasicConstraintsValid || certificate.IsCA {
		return errors.New("team certificate must be a leaf certificate with basic constraints")
	}
	if now.Before(certificate.NotBefore) || now.After(certificate.NotAfter) {
		return errors.New("team certificate is not currently valid")
	}
	wantUsage := x509.KeyUsageDigitalSignature | x509.KeyUsageKeyEncipherment
	if certificate.KeyUsage&wantUsage != wantUsage {
		return errors.New("team certificate must allow signing and key encipherment")
	}
	return nil
}
