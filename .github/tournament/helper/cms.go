package helper

import (
	"bytes"
	"crypto/aes"
	"crypto/rsa"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/asn1"
	"errors"
	"fmt"
	"math/big"

	pkcs7 "github.com/smallstep/pkcs7"
)

var (
	oidCMSData       = asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 7, 1}
	oidCMSEnveloped  = asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 7, 3}
	oidRSAEncryption = asn1.ObjectIdentifier{1, 2, 840, 113549, 1, 1, 1}
	oidAES256CBC     = asn1.ObjectIdentifier{2, 16, 840, 1, 101, 3, 4, 1, 42}
)

type cmsContentInfo struct {
	ContentType asn1.ObjectIdentifier
	Content     asn1.RawValue `asn1:"explicit,tag:0"`
}

type cmsEnvelopedData struct {
	Version              int
	RecipientInfos       []cmsRecipientInfo `asn1:"set"`
	EncryptedContentInfo cmsEncryptedContentInfo
}

type cmsRecipientInfo struct {
	Version                int
	IssuerAndSerialNumber  cmsIssuerAndSerial
	KeyEncryptionAlgorithm pkix.AlgorithmIdentifier
	EncryptedKey           []byte
}

type cmsIssuerAndSerial struct {
	IssuerName   asn1.RawValue
	SerialNumber *big.Int
}

type cmsEncryptedContentInfo struct {
	ContentType                asn1.ObjectIdentifier
	ContentEncryptionAlgorithm pkix.AlgorithmIdentifier
	EncryptedContent           asn1.RawValue `asn1:"tag:0,optional"`
}

func validateCMSEnvelope(payload []byte, recipient *x509.Certificate, label string) error {
	var contentInfo cmsContentInfo
	rest, err := asn1.Unmarshal(payload, &contentInfo)
	if err != nil || len(rest) != 0 || !contentInfo.ContentType.Equal(oidCMSEnveloped) {
		return fmt.Errorf("%s must be DER CMS EnvelopedData", label)
	}
	var envelope cmsEnvelopedData
	rest, err = asn1.Unmarshal(contentInfo.Content.Bytes, &envelope)
	if err != nil || len(rest) != 0 {
		return fmt.Errorf("%s must be DER CMS EnvelopedData", label)
	}
	if len(envelope.RecipientInfos) != 1 {
		return fmt.Errorf("%s must contain exactly one recipient", label)
	}
	recipientInfo := envelope.RecipientInfos[0]
	if !recipientInfo.KeyEncryptionAlgorithm.Algorithm.Equal(oidRSAEncryption) || len(recipientInfo.EncryptedKey) == 0 {
		return fmt.Errorf("%s recipient must use RSA key transport", label)
	}
	content := envelope.EncryptedContentInfo
	if !content.ContentType.Equal(oidCMSData) || !content.ContentEncryptionAlgorithm.Algorithm.Equal(oidAES256CBC) {
		return fmt.Errorf("%s must use AES-256-CBC", label)
	}
	var iv []byte
	rest, err = asn1.Unmarshal(content.ContentEncryptionAlgorithm.Parameters.FullBytes, &iv)
	if err != nil || len(rest) != 0 || len(iv) != aes.BlockSize {
		return fmt.Errorf("%s has invalid AES-256-CBC parameters", label)
	}
	if content.EncryptedContent.Class != 2 || content.EncryptedContent.Tag != 0 || content.EncryptedContent.IsCompound || len(content.EncryptedContent.Bytes) == 0 || len(content.EncryptedContent.Bytes)%aes.BlockSize != 0 {
		return fmt.Errorf("%s has malformed encrypted content", label)
	}
	if recipient != nil {
		if _, ok := recipient.PublicKey.(*rsa.PublicKey); !ok || recipient.SerialNumber == nil || recipientInfo.IssuerAndSerialNumber.SerialNumber == nil || recipient.SerialNumber.Cmp(recipientInfo.IssuerAndSerialNumber.SerialNumber) != 0 || !bytes.Equal(recipient.RawIssuer, recipientInfo.IssuerAndSerialNumber.IssuerName.FullBytes) {
			return fmt.Errorf("%s recipient does not match the supplied certificate", label)
		}
	}
	return nil
}

func decryptCMSEnvelope(envelope *pkcs7.PKCS7, certificate *x509.Certificate, key *rsa.PrivateKey) (plaintext []byte, err error) {
	defer func() {
		if recover() != nil {
			plaintext = nil
			err = errors.New("CMS encrypted content is malformed")
		}
	}()
	return envelope.Decrypt(certificate, key)
}
