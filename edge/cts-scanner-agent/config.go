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

	// Scanner hardware — basic
	ScannerPort   string // kept for legacy config compatibility; discovery mode takes precedence
	BankIFSC      string // teller's branch IFSC code — embeds in every scan
	BankID        string // e.g. "kotak-mah"
	OperatorID    string // teller user ID stamped into scan metadata
	SessionPrefix string // clearing session prefix (e.g. "MUM-AM")

	// Scanner discovery — Canon CR-120/150 CSD API
	// ScannerDiscoveryMode: "usb" (default) | "devname" | "ip" | "mac" | "serial"
	// "usb" calls CsdProbe() — auto-detects the first USB-connected scanner.
	// "devname" calls CsdProbeEx(ScannerDeviceName) — useful when multiple models present.
	// "ip"/"mac"/"serial" use CsdProbe2() for the network-variant CR-120/150 (future).
	ScannerDiscoveryMode string
	ScannerDeviceName    string // used when ScannerDiscoveryMode == "devname"
	ScannerSerial        string // used when ScannerDiscoveryMode == "serial" (network model)
	ScannerIP            string // used when ScannerDiscoveryMode == "ip"    (network model)
	ScannerMACAddress    string // used when ScannerDiscoveryMode == "mac"   (network model)

	// CSD DLL path — override default CanoCheetah.dll search.
	// Leave empty to use default search: exe dir → %ProgramFiles(x86)%\Canon Electronics\CR150 → PATH.
	CSDDLLPath string

	// MICR OCR weight — CR-120/150 only (CSDP_MOCR parameter).
	// 0   = pure magnetic MICR (strictest; best for high-quality ink)
	// 50  = hybrid magnetic+optical (recommended for Indian banking; handles faded ink)
	// 100 = pure optical MICR (lowest fraud resistance; use only when ink is severely degraded)
	MICROCRWeight int

	// IQA — Image Quality Assessment (requires CeiIQA.ini in the driver directory).
	// Results logged per cheque; brightness failures flagged in the scan log.
	EnableIQA bool

	// Local server
	ListenAddr string // default ":9201"

	// Scan options
	EnableUVScan        bool // true on CR-120 UV units only; false on standard CR-120/CR-150
	EnableImprinter     bool // true when endorsement stamping hardware is present and licensed
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

		// Canon CSD discovery
		ScannerDiscoveryMode: env("SCANNER_DISCOVERY_MODE", "usb"),
		ScannerDeviceName:    env("SCANNER_DEVICE_NAME", ""),
		ScannerSerial:        env("SCANNER_SERIAL", ""),
		ScannerIP:            env("SCANNER_IP", ""),
		ScannerMACAddress:    env("SCANNER_MAC", ""),
		CSDDLLPath:           env("CSD_DLL_PATH", ""),

		// MICR and IQA
		MICROCRWeight: envInt("SCANNER_MOCR_WEIGHT", 50),
		EnableIQA:     envBool("SCANNER_ENABLE_IQA", true),
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

func envInt(key string, fallback int) int {
	v := os.Getenv(key)
	if v == "" {
		return fallback
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		return fallback
	}
	return n
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
