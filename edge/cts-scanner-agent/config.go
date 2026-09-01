package main

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

// Config is loaded once at startup from config.ini in the exe directory.
// On the teller PC, config.ini is written by the ASTRA installer wizard.
// In CI / unit tests, env vars are used as fallback (no installer present).
//
// Secret separation:
//   config.ini  — non-secret, version-controlled per-branch settings
//   token.dat   — API bearer token; written by installer with restricted NTFS ACL
//                 (only SYSTEM + Administrators can read it)
type Config struct {
	// ASTRA backend
	ASTRABaseURL string
	ASTRAToken   string
	HTTPTimeout  time.Duration

	// Branch identity — set by installer per-teller-PC; never the same across branches
	BankIFSC  string
	BankID    string
	BranchID  string

	// Operator / session
	OperatorID    string
	SessionPrefix string

	// Local HTTP control server
	ListenAddr string

	// Scanner hardware
	ScannerPort          string // legacy compat
	ScannerDiscoveryMode string // usb | devname | ip | mac | serial
	ScannerDeviceName    string
	ScannerSerial        string
	ScannerIP            string
	ScannerMACAddress    string
	CSDDLLPath           string
	MICROCRWeight        int
	EnableIQA            bool

	// Scan options
	EnableUVScan    bool
	UVParamID       int // CSDP_UV offset in CsdScan.h — default 380; confirm with Canon on UV hardware

	// Scan quality — tunable without a rebuild
	ScanDPI          int // XRESOLUTION + YRESOLUTION; NPCI guideline default is 300; CTS-2010 minimum is 200
	ScanModeValue    int // value passed to CSDP_MODE; 16=binary fine-text (default); other values select grayscale or colour modes

	// IQA parameter offsets — model-dependent like CSDP_UV; confirm from CsdScan.h if IQA fails unexpectedly
	IQABrightnessParamID int // CSDP_IQA_BRIGHTNESS offset; default 355
	IQAResultParamID     int // CSDP_IQA_BRIGHTNESS_RESULT offset; default 356

	// Feeder polling
	FeederPollMS int // sleep between NoPaper restart attempts; default 300ms

	EnableImprinter bool
	EndorsementText string
}

// loadConfig reads config.ini from the exe directory.
// Falls back to environment variables when no config.ini exists (CI / dev).
func loadConfig() (*Config, error) {
	kv, source, err := readConfigSource()
	if err != nil {
		return nil, fmt.Errorf("config: %w", err)
	}

	get := func(section, key, def string) string {
		// Tries "section.key", then bare "key" (env-var mode where sections don't exist)
		if v := kv[section+"."+key]; v != "" {
			return v
		}
		if v := kv[key]; v != "" {
			return v
		}
		return def
	}
	getBool := func(section, key string, def bool) bool {
		v := get(section, key, "")
		if v == "" {
			return def
		}
		b, e := strconv.ParseBool(v)
		if e != nil {
			return def
		}
		return b
	}
	getInt := func(section, key string, def int) int {
		v := get(section, key, "")
		if v == "" {
			return def
		}
		n, e := strconv.Atoi(v)
		if e != nil {
			return def
		}
		return n
	}

	c := &Config{
		ASTRABaseURL: get("astra", "api_url", ""),
		ASTRAToken:   get("astra", "api_token", ""), // overridden by token.dat below
		BankIFSC:     get("astra", "bank_ifsc", ""),
		BankID:       get("astra", "bank_id", ""),
		BranchID:     get("astra", "branch_id", ""),

		OperatorID:    get("scanner", "operator_id", "scanner-agent"),
		SessionPrefix: get("scanner", "session_prefix", "CTS"),
		ListenAddr:    get("scanner", "listen_addr", ":9201"),
		ScannerPort:   get("scanner", "port", "USB"),

		ScannerDiscoveryMode: get("scanner", "discovery_mode", "usb"),
		ScannerDeviceName:    get("scanner", "device_name", ""),
		ScannerSerial:        get("scanner", "serial", ""),
		ScannerIP:            get("scanner", "ip", ""),
		ScannerMACAddress:    get("scanner", "mac", ""),
		CSDDLLPath:           get("scanner", "csd_dll_path", ""),
		MICROCRWeight:        getInt("scanner", "mocr_weight", 50),
		EnableIQA:            getBool("scanner", "enable_iqa", true),

		EnableUVScan:    getBool("scanner", "enable_uv_scan", false),
		UVParamID:       getInt("scanner", "uv_param_id", 380),

		ScanDPI:              getInt("scanner", "scan_dpi", 300),
		ScanModeValue:        getInt("scanner", "scan_mode_value", 16),
		IQABrightnessParamID: getInt("scanner", "iqa_brightness_param_id", 355),
		IQAResultParamID:     getInt("scanner", "iqa_result_param_id", 356),
		FeederPollMS:         getInt("scanner", "feeder_poll_ms", 300),

		EnableImprinter: getBool("scanner", "enable_imprinter", true),
		EndorsementText: get("scanner", "endorsement_text", "ASTRA/CTS"),

		HTTPTimeout: func() time.Duration {
			secs := getInt("scanner", "http_timeout_seconds", 30)
			return time.Duration(secs) * time.Second
		}(),
	}

	// token.dat overrides api_token in config.ini (token.dat has stricter NTFS ACL).
	if tok, err := readTokenFile(); err == nil && tok != "" {
		c.ASTRAToken = tok
	}

	var errs []string
	if c.ASTRABaseURL == "" {
		errs = append(errs, "api_url missing — set in config.ini [astra] section")
	}
	if c.ASTRAToken == "" {
		errs = append(errs, "api token missing — re-run the ASTRA installer to write token.dat")
	}
	if c.BankIFSC == "" {
		errs = append(errs, "bank_ifsc missing in config.ini [astra] section")
	}
	if c.BankID == "" {
		errs = append(errs, "bank_id missing in config.ini [astra] section")
	}
	if c.BranchID == "" {
		errs = append(errs, "branch_id missing in config.ini [astra] section — re-run installer and select this branch")
	}
	if len(errs) > 0 {
		return nil, fmt.Errorf("config validation failed (source: %s)\n  - %s", source, strings.Join(errs, "\n  - "))
	}
	return c, nil
}

// readConfigSource returns the key-value map from config.ini if present,
// or from environment variables as a fallback for CI / developer machines.
func readConfigSource() (kv map[string]string, source string, err error) {
	iniPath, dirErr := configFilePath()
	if dirErr == nil {
		if _, statErr := os.Stat(iniPath); statErr == nil {
			kv, err = parseINI(iniPath)
			if err != nil {
				return nil, "", fmt.Errorf("parse %s: %w", iniPath, err)
			}
			return kv, iniPath, nil
		}
	}
	// Fall back to env vars (CI, developer workstation without installer)
	return envMap(), "environment variables", nil
}

// configFilePath returns the expected path of config.ini.
// On Windows: same directory as the running exe.
// On other OS (CI Linux runner): current working directory.
func configFilePath() (string, error) {
	if runtime.GOOS == "windows" {
		exe, err := os.Executable()
		if err != nil {
			return "", err
		}
		return filepath.Join(filepath.Dir(exe), "config.ini"), nil
	}
	wd, err := os.Getwd()
	if err != nil {
		return "", err
	}
	return filepath.Join(wd, "config.ini"), nil
}

// readTokenFile reads token.dat from the same directory as config.ini.
// The file contains only the raw bearer token on a single line.
// Written by the installer with restricted NTFS ACL (SYSTEM + Administrators only).
func readTokenFile() (string, error) {
	iniPath, err := configFilePath()
	if err != nil {
		return "", err
	}
	tokenPath := filepath.Join(filepath.Dir(iniPath), "token.dat")
	data, err := os.ReadFile(tokenPath)
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(data)), nil
}

// parseINI parses a simple INI file into a flat key-value map.
// Keys are namespaced as "section.key". Lines starting with # or ; are comments.
// Duplicate keys: last value wins.
func parseINI(path string) (map[string]string, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer f.Close()

	kv := make(map[string]string)
	section := ""
	scanner := bufio.NewScanner(f)
	lineNum := 0

	for scanner.Scan() {
		lineNum++
		line := strings.TrimSpace(scanner.Text())

		if line == "" || strings.HasPrefix(line, "#") || strings.HasPrefix(line, ";") {
			continue
		}
		if strings.HasPrefix(line, "[") {
			end := strings.Index(line, "]")
			if end < 0 {
				return nil, fmt.Errorf("line %d: unclosed section header: %q", lineNum, line)
			}
			section = strings.ToLower(strings.TrimSpace(line[1:end]))
			continue
		}
		eq := strings.IndexByte(line, '=')
		if eq < 0 {
			return nil, fmt.Errorf("line %d: expected key=value, got: %q", lineNum, line)
		}
		key := strings.ToLower(strings.TrimSpace(line[:eq]))
		val := strings.TrimSpace(line[eq+1:])
		// Strip inline comments after value (e.g. "50  ; recommended")
		if ci := strings.IndexByte(val, ';'); ci >= 0 {
			val = strings.TrimSpace(val[:ci])
		}
		if section != "" {
			kv[section+"."+key] = val
		} else {
			kv[key] = val
		}
	}
	if err := scanner.Err(); err != nil {
		return nil, fmt.Errorf("reading %s: %w", path, err)
	}
	return kv, nil
}

// envMap builds the same section.key namespace from environment variables.
// Used as fallback when no config.ini is present (CI / dev machines).
func envMap() map[string]string {
	return map[string]string{
		"astra.api_url":               os.Getenv("ASTRA_API_URL"),
		"astra.api_token":             os.Getenv("ASTRA_API_TOKEN"),
		"astra.bank_id":               os.Getenv("BANK_ID"),
		"astra.bank_ifsc":             os.Getenv("BANK_IFSC"),
		"astra.branch_id":             os.Getenv("BRANCH_ID"),
		"scanner.operator_id":         os.Getenv("OPERATOR_ID"),
		"scanner.session_prefix":      os.Getenv("SESSION_PREFIX"),
		"scanner.listen_addr":         os.Getenv("LISTEN_ADDR"),
		"scanner.port":                os.Getenv("SCANNER_PORT"),
		"scanner.discovery_mode":      os.Getenv("SCANNER_DISCOVERY_MODE"),
		"scanner.device_name":         os.Getenv("SCANNER_DEVICE_NAME"),
		"scanner.serial":              os.Getenv("SCANNER_SERIAL"),
		"scanner.ip":                  os.Getenv("SCANNER_IP"),
		"scanner.mac":                 os.Getenv("SCANNER_MAC"),
		"scanner.csd_dll_path":        os.Getenv("CSD_DLL_PATH"),
		"scanner.mocr_weight":         os.Getenv("SCANNER_MOCR_WEIGHT"),
		"scanner.enable_iqa":          os.Getenv("SCANNER_ENABLE_IQA"),
		"scanner.enable_uv_scan":           os.Getenv("ENABLE_UV_SCAN"),
		"scanner.uv_param_id":              os.Getenv("SCANNER_UV_PARAM_ID"),
		"scanner.scan_dpi":                 os.Getenv("SCANNER_DPI"),
		"scanner.scan_mode_value":          os.Getenv("SCANNER_MODE_VALUE"),
		"scanner.iqa_brightness_param_id":  os.Getenv("SCANNER_IQA_BRIGHTNESS_PARAM_ID"),
		"scanner.iqa_result_param_id":      os.Getenv("SCANNER_IQA_RESULT_PARAM_ID"),
		"scanner.feeder_poll_ms":           os.Getenv("SCANNER_FEEDER_POLL_MS"),
		"scanner.enable_imprinter":    os.Getenv("ENABLE_IMPRINTER"),
		"scanner.endorsement_text":    os.Getenv("ENDORSEMENT_TEXT"),
		"scanner.http_timeout_seconds": os.Getenv("HTTP_TIMEOUT_SECONDS"),
	}
}
