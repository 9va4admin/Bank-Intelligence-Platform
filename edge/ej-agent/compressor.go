package main

import (
	"bytes"
	"compress/gzip"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"errors"
	"io"
)

// compressor gzip-compresses then AES-256-GCM-encrypts EJ file content.
// The wire format is: [12-byte nonce][GCM ciphertext+tag].
// The receiver decrypts first, then decompresses.
type compressor struct {
	gcm cipher.AEAD
}

func newCompressor(key []byte) (*compressor, error) {
	if len(key) != 32 {
		return nil, errors.New("encryption key must be 32 bytes (AES-256)")
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, err
	}
	gcm, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}
	return &compressor{gcm: gcm}, nil
}

// Process compresses src with gzip then encrypts with AES-256-GCM.
// Returns the encrypted blob ready for storage and upload.
func (c *compressor) process(src []byte) ([]byte, error) {
	compressed, err := gzipCompress(src)
	if err != nil {
		return nil, err
	}

	nonce := make([]byte, c.gcm.NonceSize()) // 12 bytes for GCM
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return nil, err
	}

	// Seal appends ciphertext+tag to nonce prefix.
	out := c.gcm.Seal(nonce, nonce, compressed, nil)
	return out, nil
}

// Decompress decrypts then gunzips — used by MCP server when serving file content.
func (c *compressor) decompress(blob []byte) ([]byte, error) {
	nonceSize := c.gcm.NonceSize()
	if len(blob) < nonceSize {
		return nil, errors.New("blob too short to contain nonce")
	}
	nonce, ciphertext := blob[:nonceSize], blob[nonceSize:]

	compressed, err := c.gcm.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return nil, err
	}
	return gzipDecompress(compressed)
}

func gzipCompress(src []byte) ([]byte, error) {
	var buf bytes.Buffer
	w := gzip.NewWriter(&buf)
	if _, err := w.Write(src); err != nil {
		return nil, err
	}
	if err := w.Close(); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}

func gzipDecompress(src []byte) ([]byte, error) {
	r, err := gzip.NewReader(bytes.NewReader(src))
	if err != nil {
		return nil, err
	}
	defer r.Close()
	return io.ReadAll(r)
}
