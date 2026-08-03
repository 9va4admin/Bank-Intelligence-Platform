package main

import (
	"errors"
	"os"
	"strconv"
	"strings"
	"time"
)

// Config is loaded once at startup from environment variables.
// On the teller PC, these are set via Windows Service properties or a .env
// file read by the installer — no Vault sidecar is available at the edge.
//
// The ASTRA_API_TOKEN is a long-lived service token issued per-scanner by
// the bank IT admin via the ASTRA Admin UI and stored in the Windows
// Credential Manager by the installer script.
type Config struct {
	// ASTRA backend
	ASTRABaseURL string        // e.g. https://api.astra.kotak-mah.internal
	ASTRAToken   string        // Bearer token for the scanner service account
	HTTPTimeout  time.Duration // default 30s

	// Scanner hardware
	ScannerPort   string // COM port or USB device path (Ranger API)
	BankIFSC      string // teller's branch IFSC code — embeds in every scan
	BankID        string // e.g. "kotak-mah"
	OperatorID    string // teller user ID stamped into scan metadata
	SessionPrefix string // clearing session prefix (e.g. "MUM-AM")

	// Local server
	ListenAddr string // default ":9201"

	// Scan options
	EnableUVScan        bool // true on CR-120 UV units
	EnableImprinter     bool // true when endorsement stamping is licensed
	EndorsementText     string
}

func loadConfig() (*Config, error) {
	c := &Config{
		ASTRABaseURL:    env("ASTRA_API_URL", ""),
		ASTRAToken:      env("ASTRA_API_TOKEN", ""),
		ScannerPort:     env("SCANNER_PORT", "USB"),
		BankIFSC:        env("BANK_IFSC", ""),
		BankID:          env("BANK_ID", ""),
		OperatorID:      env("OPERATOR_ID", "scanner-agent"),
		SessionPrefix:   env("SESSION_PREFIX", "CTS"),
		ListenAddr:      env("LISTEN_ADDR", ":9201"),
		EnableUVScan:    envBool("ENABLE_UV_SCAN", false),
		EnableImprinter: envBool("ENABLE_IMPRINTER", true),
		EndorsementText: env("ENDORSEMENT_TEXT", "ASTRA/CTS"),
		HTTPTimeout:     envDuration("HTTP_TIMEOUT_SECONDS", 30*time.Second),
	}

	var errs []string
	if c.ASTRABaseURL == "" {
		errs = append(errs, "ASTRA_API_URL is required")
	}
	if c.ASTRAToken == "" {
		errs = append(errs, "ASTRA_API_TOKEN is required")
	}
	if c.BankIFSC == "" {
		errs = append(errs, "BANK_IFSC is required")
	}
	if c.BankID == "" {
		errs = append(errs, "BANK_ID is required")
	}
	if len(errs) > 0 {
		return nil, errors.New(strings.Join(errs, "; "))
	}
	return c, nil
}

func env(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

func envBool(key string, fallback bool) bool {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	b, err := strconv.ParseBool(v)
	if err != nil {
		return fallback
	}
	return b
}

func envDuration(key string, fallback time.Duration) time.Duration {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	secs, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return time.Duration(secs) * time.Second
}
