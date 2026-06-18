package main

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"os"
	"strings"
	"time"
)

// MCP JSON-RPC 2.0 envelope types.
type mcpRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type mcpResponse struct {
	JSONRPC string `json:"jsonrpc"`
	ID      any    `json:"id,omitempty"`
	Result  any    `json:"result,omitempty"`
	Error   *mcpError `json:"error,omitempty"`
}

type mcpError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type mcpServer struct {
	cfg *config
	buf *buffer
	srv *http.Server
}

func newMCPServer(cfg *config, buf *buffer) (*mcpServer, error) {
	s := &mcpServer{cfg: cfg, buf: buf}

	mux := http.NewServeMux()
	mux.HandleFunc("/mcp", s.handleMCP)
	mux.HandleFunc("/health/live", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})

	tlsCfg, err := buildServerTLS(cfg.MCPTLSCert, cfg.MCPTLSKey, cfg.MCPTLSCA)
	if err != nil {
		return nil, fmt.Errorf("mcp server TLS: %w", err)
	}

	s.srv = &http.Server{
		Addr:         cfg.MCPAddr,
		Handler:      mux,
		TLSConfig:    tlsCfg,
		ReadTimeout:  30 * time.Second,
		WriteTimeout: 60 * time.Second,
		IdleTimeout:  120 * time.Second,
	}
	return s, nil
}

func (s *mcpServer) run(ctx context.Context) error {
	ln, err := net.Listen("tcp", s.cfg.MCPAddr)
	if err != nil {
		return fmt.Errorf("listen %s: %w", s.cfg.MCPAddr, err)
	}

	go func() {
		<-ctx.Done()
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		_ = s.srv.Shutdown(shutdownCtx)
	}()

	slog.Info("mcp server listening", "addr", s.cfg.MCPAddr)
	if err := s.srv.ServeTLS(ln, s.cfg.MCPTLSCert, s.cfg.MCPTLSKey); err != nil && err != http.ErrServerClosed {
		return err
	}
	return nil
}

func (s *mcpServer) handleMCP(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req mcpRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, nil, -32700, "parse error")
		return
	}
	if req.JSONRPC != "2.0" {
		writeError(w, req.ID, -32600, "invalid request: jsonrpc must be 2.0")
		return
	}

	slog.Info("mcp request", "method", req.Method, "remote", r.RemoteAddr)

	var result any
	var mcpErr *mcpError

	switch req.Method {
	case "initialize":
		result = s.handleInitialize()
	case "tools/list":
		result = s.handleToolsList()
	case "tools/call":
		result, mcpErr = s.handleToolsCall(req.Params)
	case "resources/list":
		result, mcpErr = s.handleResourcesList(req.Params)
	case "resources/read":
		result, mcpErr = s.handleResourcesRead(req.Params)
	default:
		mcpErr = &mcpError{Code: -32601, Message: fmt.Sprintf("method not found: %s", req.Method)}
	}

	resp := mcpResponse{JSONRPC: "2.0", ID: req.ID, Result: result, Error: mcpErr}
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(resp)
}

// ── initialize ───────────────────────────────────────────────────────────────

func (s *mcpServer) handleInitialize() any {
	return map[string]any{
		"protocolVersion": "2024-11-05",
		"serverInfo": map[string]any{
			"name":    "astra-ej-branch-agent",
			"version": "1.0.0",
		},
		"capabilities": map[string]any{
			"tools":     map[string]any{},
			"resources": map[string]any{},
		},
	}
}

// ── tools/list ───────────────────────────────────────────────────────────────

func (s *mcpServer) handleToolsList() any {
	return map[string]any{
		"tools": []map[string]any{
			{
				"name":        "list_pending",
				"description": "List EJ files pending upload for a given ATM and date.",
				"inputSchema": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"atm_id":    map[string]any{"type": "string", "description": "ATM identifier"},
						"file_date": map[string]any{"type": "string", "description": "Date in YYYY-MM-DD format"},
					},
					"required": []string{"atm_id", "file_date"},
				},
			},
			{
				"name":        "fetch_ej_file",
				"description": "Fetch a decrypted EJ file by buffer record ID. Returns base64-encoded raw content.",
				"inputSchema": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"buffer_id": map[string]any{"type": "integer", "description": "Buffer record ID from list_pending"},
					},
					"required": []string{"buffer_id"},
				},
			},
			{
				"name":        "confirm_receipt",
				"description": "Mark a buffer record as uploaded after central confirms receipt.",
				"inputSchema": map[string]any{
					"type": "object",
					"properties": map[string]any{
						"buffer_id": map[string]any{"type": "integer", "description": "Buffer record ID to mark uploaded"},
					},
					"required": []string{"buffer_id"},
				},
			},
		},
	}
}

// ── tools/call ───────────────────────────────────────────────────────────────

func (s *mcpServer) handleToolsCall(params json.RawMessage) (any, *mcpError) {
	var p struct {
		Name      string          `json:"name"`
		Arguments json.RawMessage `json:"arguments"`
	}
	if err := json.Unmarshal(params, &p); err != nil {
		return nil, &mcpError{Code: -32602, Message: "invalid params"}
	}

	switch p.Name {
	case "list_pending":
		return s.toolListPending(p.Arguments)
	case "fetch_ej_file":
		return s.toolFetchEJFile(p.Arguments)
	case "confirm_receipt":
		return s.toolConfirmReceipt(p.Arguments)
	default:
		return nil, &mcpError{Code: -32602, Message: fmt.Sprintf("unknown tool: %s", p.Name)}
	}
}

func (s *mcpServer) toolListPending(args json.RawMessage) (any, *mcpError) {
	var a struct {
		ATMID    string `json:"atm_id"`
		FileDate string `json:"file_date"`
	}
	if err := json.Unmarshal(args, &a); err != nil || a.ATMID == "" || a.FileDate == "" {
		return nil, &mcpError{Code: -32602, Message: "atm_id and file_date are required"}
	}

	records, err := s.buf.listByATMAndDate(a.ATMID, a.FileDate)
	if err != nil {
		return nil, &mcpError{Code: -32603, Message: fmt.Sprintf("buffer query failed: %v", err)}
	}

	items := make([]map[string]any, 0, len(records))
	for _, r := range records {
		items = append(items, map[string]any{
			"buffer_id":     r.ID,
			"atm_id":        r.ATMID,
			"file_date":     r.FileDate,
			"oem":           r.OEM,
			"status":        r.Status,
			"attempt_count": r.AttemptCount,
			"created_at":    r.CreatedAt,
		})
	}

	return map[string]any{
		"content": []map[string]any{
			{"type": "text", "text": fmt.Sprintf("%d record(s) found", len(items))},
		},
		"records": items,
	}, nil
}

func (s *mcpServer) toolFetchEJFile(args json.RawMessage) (any, *mcpError) {
	var a struct {
		BufferID int64 `json:"buffer_id"`
	}
	if err := json.Unmarshal(args, &a); err != nil || a.BufferID == 0 {
		return nil, &mcpError{Code: -32602, Message: "buffer_id is required"}
	}

	records, err := s.buf.listPending()
	if err != nil {
		return nil, &mcpError{Code: -32603, Message: "buffer query failed"}
	}

	var rec *uploadRecord
	for i := range records {
		if records[i].ID == a.BufferID {
			rec = &records[i]
			break
		}
	}
	if rec == nil {
		return nil, &mcpError{Code: -32602, Message: fmt.Sprintf("buffer_id %d not found", a.BufferID)}
	}

	blob, err := os.ReadFile(rec.BlobPath)
	if err != nil {
		return nil, &mcpError{Code: -32603, Message: fmt.Sprintf("blob read failed: %v", err)}
	}

	return map[string]any{
		"content": []map[string]any{
			{
				"type": "text",
				"text": fmt.Sprintf("EJ file for ATM %s dated %s (OEM: %s, hash: %s)",
					rec.ATMID, rec.FileDate, rec.OEM, rec.FileHash[:12]+"..."),
			},
		},
		"buffer_id":  rec.ID,
		"atm_id":     rec.ATMID,
		"file_date":  rec.FileDate,
		"oem":        rec.OEM,
		"file_hash":  rec.FileHash,
		// Encrypted blob — central decrypts with the shared AES key.
		// Served as-is; caller must present the key out-of-band.
		"blob_base64": base64.StdEncoding.EncodeToString(blob),
		"encoding":    "gzip+aes256gcm",
	}, nil
}

func (s *mcpServer) toolConfirmReceipt(args json.RawMessage) (any, *mcpError) {
	var a struct {
		BufferID int64 `json:"buffer_id"`
	}
	if err := json.Unmarshal(args, &a); err != nil || a.BufferID == 0 {
		return nil, &mcpError{Code: -32602, Message: "buffer_id is required"}
	}

	if err := s.buf.markUploaded(a.BufferID); err != nil {
		return nil, &mcpError{Code: -32603, Message: fmt.Sprintf("mark uploaded failed: %v", err)}
	}

	slog.Info("receipt confirmed via MCP", "buffer_id", a.BufferID)
	return map[string]any{
		"content": []map[string]any{
			{"type": "text", "text": fmt.Sprintf("buffer_id %d marked as UPLOADED", a.BufferID)},
		},
	}, nil
}

// ── resources/list ───────────────────────────────────────────────────────────

func (s *mcpServer) handleResourcesList(params json.RawMessage) (any, *mcpError) {
	records, err := s.buf.listPending()
	if err != nil {
		return nil, &mcpError{Code: -32603, Message: "buffer query failed"}
	}

	seen := make(map[string]struct{})
	var resources []map[string]any

	for _, r := range records {
		uri := fmt.Sprintf("ej://atm/%s/logs/%s", r.ATMID, r.FileDate)
		if _, exists := seen[uri]; exists {
			continue
		}
		seen[uri] = struct{}{}
		resources = append(resources, map[string]any{
			"uri":         uri,
			"name":        fmt.Sprintf("EJ logs for %s on %s", r.ATMID, r.FileDate),
			"description": fmt.Sprintf("OEM: %s — %d file(s)", r.OEM, countByATMAndDate(records, r.ATMID, r.FileDate)),
			"mimeType":    "application/octet-stream",
		})
	}

	// Always expose the ATM health resource — it exists regardless of pending files.
	healthURI := fmt.Sprintf("ej://atm/%s/health", s.cfg.ATMID)
	resources = append(resources, map[string]any{
		"uri":         healthURI,
		"name":        fmt.Sprintf("ATM health signal for %s", s.cfg.ATMID),
		"description": "Last-known ATM health state from the edge agent buffer",
		"mimeType":    "application/json",
	})

	return map[string]any{"resources": resources}, nil
}

// ── resources/read ───────────────────────────────────────────────────────────

func (s *mcpServer) handleResourcesRead(params json.RawMessage) (any, *mcpError) {
	var p struct {
		URI string `json:"uri"`
	}
	if err := json.Unmarshal(params, &p); err != nil || p.URI == "" {
		return nil, &mcpError{Code: -32602, Message: "uri is required"}
	}

	// ej://atm/{atm_id}/health
	if strings.HasSuffix(p.URI, "/health") {
		return s.readHealthResource(p.URI)
	}

	// ej://atm/{atm_id}/logs/{date}
	if strings.Contains(p.URI, "/logs/") {
		return s.readLogsResource(p.URI)
	}

	return nil, &mcpError{Code: -32602, Message: fmt.Sprintf("unknown resource URI: %s", p.URI)}
}

func (s *mcpServer) readLogsResource(uri string) (any, *mcpError) {
	// URI format: ej://atm/{atm_id}/logs/{date}
	parts := strings.Split(strings.TrimPrefix(uri, "ej://atm/"), "/")
	if len(parts) < 3 || parts[1] != "logs" {
		return nil, &mcpError{Code: -32602, Message: "invalid resource URI format — expected ej://atm/{atm_id}/logs/{date}"}
	}
	atmID := parts[0]
	fileDate := parts[2]

	records, err := s.buf.listByATMAndDate(atmID, fileDate)
	if err != nil {
		return nil, &mcpError{Code: -32603, Message: "buffer query failed"}
	}
	if len(records) == 0 {
		return nil, &mcpError{Code: -32602, Message: fmt.Sprintf("no records for %s on %s", atmID, fileDate)}
	}

	summary := fmt.Sprintf("ATM: %s | Date: %s | Files: %d | OEM: %s",
		atmID, fileDate, len(records), records[0].OEM)

	return map[string]any{
		"contents": []map[string]any{
			{
				"uri":      uri,
				"mimeType": "application/json",
				"text":     summary,
			},
		},
	}, nil
}

func (s *mcpServer) readHealthResource(uri string) (any, *mcpError) {
	pending, _ := s.buf.listPending()
	health := map[string]any{
		"atm_id":          s.cfg.ATMID,
		"bank_id":         s.cfg.BankID,
		"branch_id":       s.cfg.BranchID,
		"pending_uploads": len(pending),
		"agent_status":    "RUNNING",
		"checked_at":      time.Now().UTC().Format(time.RFC3339),
	}

	healthJSON, _ := json.Marshal(health)
	return map[string]any{
		"contents": []map[string]any{
			{
				"uri":      uri,
				"mimeType": "application/json",
				"text":     string(healthJSON),
			},
		},
	}, nil
}

// ── helpers ──────────────────────────────────────────────────────────────────

func writeError(w http.ResponseWriter, id any, code int, msg string) {
	resp := mcpResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error:   &mcpError{Code: code, Message: msg},
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK) // JSON-RPC errors return HTTP 200
	_ = json.NewEncoder(w).Encode(resp)
}

func countByATMAndDate(records []uploadRecord, atmID, fileDate string) int {
	n := 0
	for _, r := range records {
		if r.ATMID == atmID && r.FileDate == fileDate {
			n++
		}
	}
	return n
}

func buildServerTLS(certPath, keyPath, caPath string) (*tls.Config, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load server cert: %w", err)
	}

	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert failed")
	}

	return &tls.Config{
		Certificates: []tls.Certificate{cert},
		ClientCAs:    pool,
		ClientAuth:   tls.RequireAndVerifyClientCert, // mTLS — no unauthenticated connections
		MinVersion:   tls.VersionTLS13,
	}, nil
}
