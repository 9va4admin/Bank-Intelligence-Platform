package main

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// ---------------------------------------------------------------------------
// Config tests
// ---------------------------------------------------------------------------

func TestLoadConfigMissingRequired(t *testing.T) {
	t.Setenv("ASTRA_API_URL", "")
	t.Setenv("ASTRA_API_TOKEN", "")
	t.Setenv("BANK_IFSC", "")
	t.Setenv("BANK_ID", "")

	_, err := loadConfig()
	if err == nil {
		t.Fatal("expected error for missing required config, got nil")
	}
	errStr := err.Error()
	for _, field := range []string{"ASTRA_API_URL", "ASTRA_API_TOKEN", "BANK_IFSC", "BANK_ID"} {
		if !strings.Contains(errStr, field) {
			t.Errorf("error missing mention of %s: %s", field, errStr)
		}
	}
}

func TestLoadConfigDefaults(t *testing.T) {
	t.Setenv("ASTRA_API_URL", "https://api.test.internal")
	t.Setenv("ASTRA_API_TOKEN", "tok-abc")
	t.Setenv("BANK_IFSC", "SVCB0000001")
	t.Setenv("BANK_ID", "saraswat-coop")

	cfg, err := loadConfig()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ListenAddr != ":9201" {
		t.Errorf("expected default ListenAddr :9201, got %s", cfg.ListenAddr)
	}
	if cfg.HTTPTimeout != 30*time.Second {
		t.Errorf("expected default HTTPTimeout 30s, got %v", cfg.HTTPTimeout)
	}
	if !cfg.EnableImprinter {
		t.Error("expected default EnableImprinter true")
	}
}

// ---------------------------------------------------------------------------
// StubTransport tests
// ---------------------------------------------------------------------------

func TestStubTransportOrderedItems(t *testing.T) {
	items := []*ScannedItem{
		{FrontImage: []byte("img1"), MICRRaw: "001001001  12345 9876543210"},
		{FrontImage: []byte("img2"), MICRRaw: "002001002  67890 1234567890"},
	}
	st := NewStubTransport(items)

	if err := st.Open(); err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := st.StartJob("ASTRA/CTS", true); err != nil {
		t.Fatalf("StartJob: %v", err)
	}

	got1, err := st.ReadItem()
	if err != nil || got1 == nil {
		t.Fatalf("ReadItem 1: item=%v err=%v", got1, err)
	}
	if string(got1.FrontImage) != "img1" {
		t.Errorf("unexpected front image: %s", got1.FrontImage)
	}

	got2, _ := st.ReadItem()
	if string(got2.FrontImage) != "img2" {
		t.Errorf("unexpected front image: %s", got2.FrontImage)
	}

	// EndJob unblocks any blocked ReadItem
	done := make(chan struct{})
	go func() {
		item, _ := st.ReadItem() // will block until EndJob
		if item != nil {
			t.Errorf("expected nil after EndJob, got %v", item)
		}
		close(done)
	}()
	if err := st.EndJob(); err != nil {
		t.Fatalf("EndJob: %v", err)
	}
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("ReadItem did not return after EndJob")
	}
}

func TestStubTransportDoubleFeedFlag(t *testing.T) {
	items := []*ScannedItem{
		{DoubleFeedDetected: true, FrontImage: []byte("bad")},
	}
	st := NewStubTransport(items)
	st.Open()
	st.StartJob("", false)

	item, err := st.ReadItem()
	if err != nil {
		t.Fatalf("ReadItem: %v", err)
	}
	if !item.DoubleFeedDetected {
		t.Error("expected DoubleFeedDetected=true")
	}
}

// ---------------------------------------------------------------------------
// Scanner helper tests
// ---------------------------------------------------------------------------

func TestExtractChequeNumber(t *testing.T) {
	tests := []struct {
		micr string
		want string
	}{
		{"000123  00110001234  999999999", "000123"},
		{"", ""},
		{"  leading spaces", "leading"},
	}
	for _, tt := range tests {
		got := extractChequeNumber(tt.micr)
		if got != tt.want {
			t.Errorf("extractChequeNumber(%q) = %q, want %q", tt.micr, got, tt.want)
		}
	}
}

func TestMICRSuffix(t *testing.T) {
	got := micrSuffix("000123  00110001234  999999999")
	if !strings.HasPrefix(got, "****") {
		t.Errorf("micrSuffix must start with ****: %s", got)
	}
	if len(got) < 4 {
		t.Errorf("micrSuffix too short: %s", got)
	}

	// Short MICR — mask entire string
	short := micrSuffix("ab")
	if short != "**" {
		t.Errorf("expected ** for 2-char MICR, got %q", short)
	}
}

func TestScanIDFormat(t *testing.T) {
	cfg := &Config{SessionPrefix: "MUM"}
	s := newScanSession(cfg, NewStubTransport(nil), nil, slog.Default())
	id := s.generateScanID()
	if !strings.HasPrefix(id, "SCAN-") {
		t.Errorf("scan ID missing SCAN- prefix: %s", id)
	}
	if !strings.Contains(id, "MUM") {
		t.Errorf("scan ID missing session prefix: %s", id)
	}
	// Second ID must be different
	id2 := s.generateScanID()
	if id == id2 {
		t.Error("two successive scan IDs must differ")
	}
}

// ---------------------------------------------------------------------------
// HTTP handler tests
// ---------------------------------------------------------------------------

func newTestLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func TestHealthEndpoint(t *testing.T) {
	cfg := &Config{}
	session := newScanSession(cfg, NewStubTransport(nil), nil, newTestLogger())

	mux := http.NewServeMux()
	registerHandlers(mux, session, newTestLogger())

	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusOK {
		t.Errorf("expected 200, got %d", w.Code)
	}
	var resp map[string]any
	json.NewDecoder(w.Body).Decode(&resp)
	if resp["status"] != "ok" {
		t.Errorf("expected status ok, got %v", resp["status"])
	}
	if resp["session_active"] != false {
		t.Errorf("expected session_active=false, got %v", resp["session_active"])
	}
}

func TestSessionStartRequiresSessionID(t *testing.T) {
	cfg := &Config{}
	session := newScanSession(cfg, NewStubTransport(nil), nil, newTestLogger())

	mux := http.NewServeMux()
	registerHandlers(mux, session, newTestLogger())

	req := httptest.NewRequest(http.MethodPost, "/session/start",
		strings.NewReader(`{}`))
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)

	if w.Code != http.StatusBadRequest {
		t.Errorf("expected 400 for missing session_id, got %d", w.Code)
	}
}

func TestSessionStartAndStop(t *testing.T) {
	cfg := &Config{SessionPrefix: "TEST", EnableImprinter: false}
	st := NewStubTransport(nil) // no items — ReadItem blocks until EndJob
	session := newScanSession(cfg, st, nil, newTestLogger())

	mux := http.NewServeMux()
	registerHandlers(mux, session, newTestLogger())

	// Start session
	req := httptest.NewRequest(http.MethodPost, "/session/start",
		strings.NewReader(`{"session_id":"SES-001"}`))
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusAccepted {
		t.Errorf("expected 202, got %d", w.Code)
	}

	// Give the goroutine time to start
	time.Sleep(50 * time.Millisecond)

	// Conflict: start while active
	req2 := httptest.NewRequest(http.MethodPost, "/session/start",
		strings.NewReader(`{"session_id":"SES-002"}`))
	w2 := httptest.NewRecorder()
	mux.ServeHTTP(w2, req2)
	if w2.Code != http.StatusConflict {
		t.Errorf("expected 409 when session active, got %d", w2.Code)
	}

	// Stop session
	req3 := httptest.NewRequest(http.MethodPost, "/session/stop", nil)
	w3 := httptest.NewRecorder()
	mux.ServeHTTP(w3, req3)
	if w3.Code != http.StatusOK {
		t.Errorf("expected 200 for stop, got %d", w3.Code)
	}
}

// ---------------------------------------------------------------------------
// ASTRA HTTP client tests (against mock server)
// ---------------------------------------------------------------------------

func TestRequestUploadURLs(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/cts/outward/scan/upload-url" {
			http.NotFound(w, r)
			return
		}
		if r.Header.Get("Authorization") != "Bearer tok-test" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		json.NewEncoder(w).Encode(UploadURLResponse{
			FrontPresignedURL: "https://minio.internal/presigned/front",
			RearPresignedURL:  "https://minio.internal/presigned/rear",
			FrontObjectURL:    "s3://cts-images/bank/outward/SCAN-001/front.tiff",
			RearObjectURL:     "s3://cts-images/bank/outward/SCAN-001/rear.tiff",
		})
	}))
	defer srv.Close()

	client := &ASTRAClient{
		baseURL:    srv.URL,
		token:      "tok-test",
		httpClient: srv.Client(),
	}

	resp, err := client.RequestUploadURLs(context.Background(), "SCAN-001")
	if err != nil {
		t.Fatalf("RequestUploadURLs: %v", err)
	}
	if resp.FrontPresignedURL == "" {
		t.Error("expected FrontPresignedURL to be set")
	}
	if !strings.HasPrefix(resp.FrontObjectURL, "s3://") {
		t.Errorf("FrontObjectURL should be s3:// URL: %s", resp.FrontObjectURL)
	}
}

func TestSubmitScan(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/cts/outward/scan/submit" {
			http.NotFound(w, r)
			return
		}
		var body ScanSubmitRequest
		json.NewDecoder(r.Body).Decode(&body)
		if body.ScanID == "" {
			http.Error(w, "missing scan_id", http.StatusBadRequest)
			return
		}
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(ScanSubmitResponse{
			ScanID:       body.ScanID,
			InstrumentID: body.InstrumentID,
			WorkflowID:   "cts-outscan-test-bank-" + body.ScanID,
			Status:       "ACCEPTED",
			Path:         "CR120",
		})
	}))
	defer srv.Close()

	client := &ASTRAClient{
		baseURL:    srv.URL,
		token:      "tok-test",
		httpClient: srv.Client(),
	}

	micrRaw := "000123  00110001234  999999999"
	resp, err := client.SubmitScan(context.Background(), &ScanSubmitRequest{
		ScanID:          "SCAN-20260715-MUM-00001",
		InstrumentID:    "INS-SCAN-20260715-MUM-00001",
		BankIFSC:        "SVCB0000001",
		SessionID:       "SES-001",
		ImageFrontURL:   "s3://cts-images/bank/outward/SCAN-001/front.tiff",
		ImageRearURL:    "s3://cts-images/bank/outward/SCAN-001/rear.tiff",
		MICRHardwareRaw: &micrRaw,
	})
	if err != nil {
		t.Fatalf("SubmitScan: %v", err)
	}
	if resp.Status != "ACCEPTED" {
		t.Errorf("expected ACCEPTED, got %s", resp.Status)
	}
	if resp.Path != "CR120" {
		t.Errorf("expected CR120 path, got %s", resp.Path)
	}
}

func TestSubmitScanServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "service unavailable", http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	client := &ASTRAClient{
		baseURL:    srv.URL,
		token:      "tok-test",
		httpClient: srv.Client(),
	}
	_, err := client.SubmitScan(context.Background(), &ScanSubmitRequest{
		ScanID: "SCAN-ERR", SessionID: "SES-001",
	})
	if err == nil {
		t.Error("expected error on 503, got nil")
	}
}
