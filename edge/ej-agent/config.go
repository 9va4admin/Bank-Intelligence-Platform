package main

import (
	"encoding/hex"
	"errors"
	"fmt"
	"os"
	"strconv"
)

type config struct {
	// Identity — injected by Vault agent sidecar at pod startup
	ATMID    string
	BankID   string
	BranchID string

	// Paths — writable PV mounts defined in Helm deployment
	EJWatchDir   string // directory ATM controller drops raw EJ files into
	BufferDir    string // staging area for compressed+encrypted files awaiting upload
	BufferDBPath string // SQLite WAL database (tracks upload state per file)

	// Encryption — AES-256-GCM key from Vault (32 bytes, hex-encoded in env var)
	EncryptionKey []byte

	// Central upload — mTLS to EJ ingestion gateway
	CentralURL  string // https://ej-ingestion.{bank_id}.internal/v1/inward/log
	TLSCertPath string // client cert (Vault PKI — rotated every 24h)
	TLSKeyPath  string // client key
	TLSCAPath   string // CA cert to verify central server

	// MCP server — presents server cert; verifies client cert of MCP caller
	MCPAddr    string // :8443
	MCPTLSCert string // server cert
	MCPTLSKey  string // server key
	MCPTLSCA   string // CA cert to verify MCP clients (ASTRA support workstation)

	// Tuning
	WatchIntervalSec int
	RetryIntervalSec int
	MaxUploadAttempts int
}

func loadConfig() (*config, error) {
	keyHex, err := requireEnv("ASTRA_EJ_ENCRYPTION_KEY")
	if err != nil {
		return nil, err
	}
	key, err := hex.DecodeString(keyHex)
	if err != nil || len(key) != 32 {
		return nil, errors.New("ASTRA_EJ_ENCRYPTION_KEY must be 64 hex chars (32 bytes for AES-256)")
	}

	centralURL, err := requireEnv("ASTRA_CENTRAL_EJ_URL")
	if err != nil {
		return nil, err
	}
	atmID, err := requireEnv("ASTRA_ATM_ID")
	if err != nil {
		return nil, err
	}
	bankID, err := requireEnv("ASTRA_BANK_ID")
	if err != nil {
		return nil, err
	}
	branchID, err := requireEnv("ASTRA_BRANCH_ID")
	if err != nil {
		return nil, err
	}
	ejWatchDir, err := requireEnv("ASTRA_EJ_WATCH_DIR")
	if err != nil {
		return nil, err
	}
	tlsCert, err := requireEnv("ASTRA_TLS_CERT_PATH")
	if err != nil {
		return nil, err
	}
	tlsKey, err := requireEnv("ASTRA_TLS_KEY_PATH")
	if err != nil {
		return nil, err
	}
	tlsCA, err := requireEnv("ASTRA_TLS_CA_PATH")
	if err != nil {
		return nil, err
	}
	mcpTLSCert, err := requireEnv("ASTRA_MCP_TLS_CERT_PATH")
	if err != nil {
		return nil, err
	}
	mcpTLSKey, err := requireEnv("ASTRA_MCP_TLS_KEY_PATH")
	if err != nil {
		return nil, err
	}
	mcpTLSCA, err := requireEnv("ASTRA_MCP_TLS_CA_PATH")
	if err != nil {
		return nil, err
	}

	return &config{
		ATMID:             atmID,
		BankID:            bankID,
		BranchID:          branchID,
		EJWatchDir:        ejWatchDir,
		BufferDir:         envOr("ASTRA_EJ_BUFFER_DIR", "/var/astra/ej-buffer/compressed"),
		BufferDBPath:      envOr("ASTRA_EJ_BUFFER_DB_PATH", "/var/astra/ej-buffer/buffer.db"),
		EncryptionKey:     key,
		CentralURL:        centralURL,
		TLSCertPath:       tlsCert,
		TLSKeyPath:        tlsKey,
		TLSCAPath:         tlsCA,
		MCPAddr:           envOr("ASTRA_MCP_ADDR", ":8443"),
		MCPTLSCert:        mcpTLSCert,
		MCPTLSKey:         mcpTLSKey,
		MCPTLSCA:          mcpTLSCA,
		WatchIntervalSec:  intEnvOr("ASTRA_WATCH_INTERVAL_SEC", 30),
		RetryIntervalSec:  intEnvOr("ASTRA_RETRY_INTERVAL_SEC", 60),
		MaxUploadAttempts: intEnvOr("ASTRA_MAX_UPLOAD_ATTEMPTS", 10),
	}, nil
}

func requireEnv(key string) (string, error) {
	v := os.Getenv(key)
	if v == "" {
		return "", fmt.Errorf("required env var %s is not set", key)
	}
	return v, nil
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func intEnvOr(key string, def int) int {
	v := os.Getenv(key)
	if v == "" {
		return def
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return def
	}
	return n
}
