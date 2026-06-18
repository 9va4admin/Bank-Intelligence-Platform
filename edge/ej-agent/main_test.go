package main

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

// ── compressor tests ──────────────────────────────────────────────────────────

func TestGzipCompressDecompress(t *testing.T) {
	original := []byte("NCR ATM EJ LOG 2026-06-18 DISPENSE 5000 OK\nSESSION 001 CARD 4521 AMOUNT 5000")
	compressed, err := gzipCompress(original)
	if err != nil {
		t.Fatalf("gzipCompress: %v", err)
	}
	if len(compressed) == 0 {
		t.Fatal("expected non-empty compressed output")
	}
	recovered, err := gzipDecompress(compressed)
	if err != nil {
		t.Fatalf("gzipDecompress: %v", err)
	}
	if !bytes.Equal(original, recovered) {
		t.Fatalf("roundtrip mismatch: got %q, want %q", recovered, original)
	}
}

func TestGzipCompressEmpty(t *testing.T) {
	compressed, err := gzipCompress([]byte{})
	if err != nil {
		t.Fatalf("gzipCompress empty: %v", err)
	}
	recovered, err := gzipDecompress(compressed)
	if err != nil {
		t.Fatalf("gzipDecompress empty: %v", err)
	}
	if len(recovered) != 0 {
		t.Fatalf("expected empty output, got %q", recovered)
	}
}

func TestAESCompressorRoundtrip(t *testing.T) {
	key := bytes.Repeat([]byte("k"), 32)
	comp, err := newCompressor(key)
	if err != nil {
		t.Fatalf("newCompressor: %v", err)
	}
	original := []byte("EJ log content for AES roundtrip test")
	blob, err := comp.process(original)
	if err != nil {
		t.Fatalf("process: %v", err)
	}
	recovered, err := comp.decompress(blob)
	if err != nil {
		t.Fatalf("decompress: %v", err)
	}
	if !bytes.Equal(original, recovered) {
		t.Fatalf("AES roundtrip mismatch")
	}
}

func TestAESCompressorInvalidKeyLength(t *testing.T) {
	_, err := newCompressor([]byte("tooshort"))
	if err == nil {
		t.Fatal("expected error for short key, got nil")
	}
}

// ── buffer tests ──────────────────────────────────────────────────────────────

func TestBufferCreateAndList(t *testing.T) {
	dir := t.TempDir()
	dbPath := filepath.Join(dir, "test.db")

	buf, err := newBuffer(dbPath)
	if err != nil {
		t.Fatalf("newBuffer: %v", err)
	}
	defer buf.close()

	// Should start empty
	records, err := buf.listPending()
	if err != nil {
		t.Fatalf("listPending: %v", err)
	}
	if len(records) != 0 {
		t.Fatalf("expected 0 pending, got %d", len(records))
	}
}

func TestBufferInsertAndMarkUploaded(t *testing.T) {
	dir := t.TempDir()
	buf, err := newBuffer(filepath.Join(dir, "buf.db"))
	if err != nil {
		t.Fatalf("newBuffer: %v", err)
	}
	defer buf.close()

	blobPath := filepath.Join(dir, "test.blob")
	if err := os.WriteFile(blobPath, []byte("fake blob"), 0600); err != nil {
		t.Fatal(err)
	}

	id, err := buf.enqueue("ATM001", "2026-06-18", blobPath, blobPath, "abc123", "NCR_SELFSERV")
	if err != nil {
		t.Fatalf("enqueue: %v", err)
	}

	pending, err := buf.listPending()
	if err != nil {
		t.Fatalf("listPending: %v", err)
	}
	if len(pending) != 1 {
		t.Fatalf("expected 1 pending, got %d", len(pending))
	}
	if pending[0].ID != id {
		t.Fatalf("unexpected ID: got %d, want %d", pending[0].ID, id)
	}

	if err := buf.markUploaded(id); err != nil {
		t.Fatalf("markUploaded: %v", err)
	}

	pending2, _ := buf.listPending()
	if len(pending2) != 0 {
		t.Fatalf("expected 0 pending after mark, got %d", len(pending2))
	}
}

func TestBufferListByATMAndDate(t *testing.T) {
	dir := t.TempDir()
	buf, err := newBuffer(filepath.Join(dir, "buf2.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer buf.close()

	blobPath := filepath.Join(dir, "b.blob")
	_ = os.WriteFile(blobPath, []byte("x"), 0600)

	_, _ = buf.enqueue("ATM001", "2026-06-18", blobPath, blobPath, "h1", "NCR")
	_, _ = buf.enqueue("ATM001", "2026-06-19", blobPath, blobPath, "h2", "NCR")
	_, _ = buf.enqueue("ATM002", "2026-06-18", blobPath, blobPath, "h3", "DIEBOLD")

	records, err := buf.listByATMAndDate("ATM001", "2026-06-18")
	if err != nil {
		t.Fatalf("listByATMAndDate: %v", err)
	}
	if len(records) != 1 {
		t.Fatalf("expected 1 record for ATM001/2026-06-18, got %d", len(records))
	}
}

// ── MCP server HTTP tests ─────────────────────────────────────────────────────

func makePlainServer(t *testing.T) (*mcpServer, *buffer) {
	t.Helper()
	dir := t.TempDir()
	buf, err := newBuffer(filepath.Join(dir, "test.db"))
	if err != nil {
		t.Fatalf("newBuffer: %v", err)
	}
	cfg := &config{
		BankID:   "test-bank",
		ATMID:    "ATM001",
		BranchID: "BR001",
		MCPAddr:  "127.0.0.1:0",
		// TLS paths empty — tests use plain HTTP via httptest.NewServer
	}
	// Build mux directly without TLS for testing
	s := &mcpServer{cfg: cfg, buf: buf}
	return s, buf
}

func TestLivenessEndpoint(t *testing.T) {
	mux := http.NewServeMux()
	mux.HandleFunc("/health/live", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte(`{"status":"ok"}`))
	})
	ts := httptest.NewServer(mux)
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/health/live")
	if err != nil {
		t.Fatalf("GET /health/live: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}
}

func TestMCPInitialize(t *testing.T) {
	s, buf := makePlainServer(t)
	defer buf.close()

	mux := http.NewServeMux()
	mux.HandleFunc("/mcp", s.handleMCP)
	ts := httptest.NewServer(mux)
	defer ts.Close()

	reqBody, _ := json.Marshal(mcpRequest{
		JSONRPC: "2.0",
		ID:      1,
		Method:  "initialize",
	})
	resp, err := http.Post(ts.URL+"/mcp", "application/json", bytes.NewReader(reqBody))
	if err != nil {
		t.Fatalf("POST /mcp: %v", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("expected 200, got %d", resp.StatusCode)
	}

	var result mcpResponse
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if result.Error != nil {
		t.Fatalf("unexpected error: %v", result.Error)
	}
}

func TestMCPToolsList(t *testing.T) {
	s, buf := makePlainServer(t)
	defer buf.close()

	mux := http.NewServeMux()
	mux.HandleFunc("/mcp", s.handleMCP)
	ts := httptest.NewServer(mux)
	defer ts.Close()

	reqBody, _ := json.Marshal(mcpRequest{
		JSONRPC: "2.0",
		ID:      2,
		Method:  "tools/list",
	})
	resp, _ := http.Post(ts.URL+"/mcp", "application/json", bytes.NewReader(reqBody))
	defer resp.Body.Close()

	var result mcpResponse
	_ = json.NewDecoder(resp.Body).Decode(&result)
	if result.Error != nil {
		t.Fatalf("unexpected error: %v", result.Error)
	}

	// Result should contain "tools" key
	resultMap, ok := result.Result.(map[string]any)
	if !ok {
		t.Fatalf("expected map result, got %T", result.Result)
	}
	tools, ok := resultMap["tools"].([]any)
	if !ok || len(tools) == 0 {
		t.Fatal("expected non-empty tools list")
	}
}

func TestMCPUnknownMethod(t *testing.T) {
	s, buf := makePlainServer(t)
	defer buf.close()

	mux := http.NewServeMux()
	mux.HandleFunc("/mcp", s.handleMCP)
	ts := httptest.NewServer(mux)
	defer ts.Close()

	reqBody, _ := json.Marshal(mcpRequest{
		JSONRPC: "2.0",
		ID:      3,
		Method:  "nonexistent/method",
	})
	resp, _ := http.Post(ts.URL+"/mcp", "application/json", bytes.NewReader(reqBody))
	defer resp.Body.Close()

	var result mcpResponse
	_ = json.NewDecoder(resp.Body).Decode(&result)
	if result.Error == nil {
		t.Fatal("expected error for unknown method, got nil")
	}
	if result.Error.Code != -32601 {
		t.Fatalf("expected -32601, got %d", result.Error.Code)
	}
}
