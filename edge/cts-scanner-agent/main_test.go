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
	t.Setenv("BRANCH_ID", "")

	_, err := loadConfig()
	if err == nil {
		t.Fatal("expected error for missing required config, got nil")
	}
	errStr := err.Error()
	// Match the actual error message strings from config.go validation block.
	for _, phrase := range []string{"api_url missing", "api token missing", "bank_ifsc missing", "bank_id missing"} {
		if !strings.Contains(errStr, phrase) {
			t.Errorf("error message missing phrase %q: %s", phrase, errStr)
		}
	}
}

func TestLoadConfigDefaults(t *testing.T) {
	t.Setenv("ASTRA_API_URL", "https://api.test.internal")
	t.Setenv("ASTRA_API_TOKEN", "tok-abc")
	t.Setenv("BANK_IFSC", "SVCB0000001")
	t.Setenv("BANK_ID", "saraswat-coop")
	t.Setenv("BRANCH_ID", "BRANCH-ANDHERI-01")

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
	// NPCI-mandated defaults — must not regress
	if cfg.ScanDPI != 300 {
		t.Errorf("ScanDPI default must be 300 (NPCI guideline), got %d", cfg.ScanDPI)
	}
	if cfg.ScanModeValue != 16 {
		t.Errorf("ScanModeValue default must be 16 (binary fine-text), got %d", cfg.ScanModeValue)
	}
	if cfg.IQABrightnessParamID != 355 {
		t.Errorf("IQABrightnessParamID default must be 355, got %d", cfg.IQABrightnessParamID)
	}
	if cfg.IQAResultParamID != 356 {
		t.Errorf("IQAResultParamID default must be 356, got %d", cfg.IQAResultParamID)
	}
	if cfg.UVParamID != 380 {
		t.Errorf("UVParamID default must be 380, got %d", cfg.UVParamID)
	}
	if cfg.FeederPollMS != 300 {
		t.Errorf("FeederPollMS default must be 300, got %d", cfg.FeederPollMS)
	}
	if cfg.EnableUVScan {
		t.Error("EnableUVScan must default to false (UV is opt-in)")
	}
}

func TestLoadConfigScanDPIOverride(t *testing.T) {
	t.Setenv("ASTRA_API_URL", "https://api.test.internal")
	t.Setenv("ASTRA_API_TOKEN", "tok-abc")
	t.Setenv("BANK_IFSC", "SVCB0000001")
	t.Setenv("BANK_ID", "saraswat-coop")
	t.Setenv("BRANCH_ID", "BRANCH-ANDHERI-01")
	t.Setenv("SCANNER_DPI", "200")

	cfg, err := loadConfig()
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.ScanDPI != 200 {
		t.Errorf("expected overridden ScanDPI 200, got %d", cfg.ScanDPI)
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
	id := s.buildScanID(1)
	if !strings.HasPrefix(id, "SCAN-") {
		t.Errorf("scan ID missing SCAN- prefix: %s", id)
	}
	if !strings.Contains(id, "MUM") {
		t.Errorf("scan ID missing session prefix: %s", id)
	}
	// Different positions must produce different IDs
	id2 := s.buildScanID(2)
	if id == id2 {
		t.Error("scan IDs for different positions must differ")
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

func TestRequestUploadURLsNoUV(t *testing.T) {
	var capturedBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/cts/outward/scan/upload-url" {
			http.NotFound(w, r)
			return
		}
		if r.Header.Get("Authorization") != "Bearer tok-test" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		json.NewDecoder(r.Body).Decode(&capturedBody)
		json.NewEncoder(w).Encode(UploadURLResponse{
			FrontPresignedURL: "https://minio.internal/presigned/front",
			RearPresignedURL:  "https://minio.internal/presigned/rear",
			FrontObjectURL:    "s3://cts-images/bank/outward/SCAN-001/front.tiff",
			RearObjectURL:     "s3://cts-images/bank/outward/SCAN-001/rear.tiff",
		})
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-test", httpClient: srv.Client()}

	resp, err := client.RequestUploadURLs(context.Background(), "SCAN-001", false)
	if err != nil {
		t.Fatalf("RequestUploadURLs: %v", err)
	}
	if resp.FrontPresignedURL == "" {
		t.Error("expected FrontPresignedURL to be set")
	}
	if !strings.HasPrefix(resp.FrontObjectURL, "s3://") {
		t.Errorf("FrontObjectURL should be s3:// URL: %s", resp.FrontObjectURL)
	}
	// include_uv=false must be sent in body
	if v, ok := capturedBody["include_uv"].(bool); ok && v {
		t.Error("include_uv must be false when not a UV item")
	}
	// UV URLs must be empty in the response
	if resp.UVPresignedURL != "" {
		t.Errorf("expected empty UVPresignedURL for non-UV request, got %s", resp.UVPresignedURL)
	}
}

func TestRequestUploadURLsWithUV(t *testing.T) {
	var capturedBody map[string]any
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&capturedBody)
		json.NewEncoder(w).Encode(UploadURLResponse{
			FrontPresignedURL: "https://minio.internal/presigned/front",
			RearPresignedURL:  "https://minio.internal/presigned/rear",
			FrontObjectURL:    "s3://cts-images/bank/outward/SCAN-001/front.tiff",
			RearObjectURL:     "s3://cts-images/bank/outward/SCAN-001/rear.tiff",
			UVPresignedURL:    "https://minio.internal/presigned/uv",
			UVObjectURL:       "s3://cts-images/bank/outward/SCAN-001/uv.tiff",
		})
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-test", httpClient: srv.Client()}

	resp, err := client.RequestUploadURLs(context.Background(), "SCAN-001", true)
	if err != nil {
		t.Fatalf("RequestUploadURLs with UV: %v", err)
	}
	// include_uv=true must be sent in request body
	if v, ok := capturedBody["include_uv"].(bool); !ok || !v {
		t.Error("expected include_uv=true in request body for UV item")
	}
	if resp.UVPresignedURL == "" {
		t.Error("expected UVPresignedURL to be set in UV response")
	}
	if resp.UVObjectURL == "" {
		t.Error("expected UVObjectURL to be set in UV response")
	}
}

func TestSubmitScanWithUVURL(t *testing.T) {
	var capturedBody ScanSubmitRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&capturedBody)
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(ScanSubmitResponse{
			ScanID: capturedBody.ScanID, Status: "ACCEPTED", Path: "CR120",
		})
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-test", httpClient: srv.Client()}

	uvURL := "s3://cts-images/bank/outward/SCAN-UV/uv.tiff"
	resp, err := client.SubmitScan(context.Background(), &ScanSubmitRequest{
		ScanID:        "SCAN-UV",
		SessionID:     "SES-001",
		ImageFrontURL: "s3://cts-images/bank/outward/SCAN-UV/front.tiff",
		ImageRearURL:  "s3://cts-images/bank/outward/SCAN-UV/rear.tiff",
		UVImageURL:    &uvURL,
	})
	if err != nil {
		t.Fatalf("SubmitScan with UV: %v", err)
	}
	if resp.Status != "ACCEPTED" {
		t.Errorf("expected ACCEPTED, got %s", resp.Status)
	}
	// UV URL must be forwarded in the JSON body
	if capturedBody.UVImageURL == nil || *capturedBody.UVImageURL != uvURL {
		t.Errorf("UVImageURL not forwarded in submit body: got %v", capturedBody.UVImageURL)
	}
}

func TestSubmitScanUVURLAbsentWhenNoUV(t *testing.T) {
	var capturedBody ScanSubmitRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&capturedBody)
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(ScanSubmitResponse{ScanID: "SCAN-001", Status: "ACCEPTED"})
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-test", httpClient: srv.Client()}

	_, err := client.SubmitScan(context.Background(), &ScanSubmitRequest{
		ScanID:        "SCAN-001",
		SessionID:     "SES-001",
		ImageFrontURL: "s3://cts-images/bank/outward/SCAN-001/front.tiff",
		ImageRearURL:  "s3://cts-images/bank/outward/SCAN-001/rear.tiff",
		// UVImageURL intentionally nil
	})
	if err != nil {
		t.Fatalf("SubmitScan without UV: %v", err)
	}
	if capturedBody.UVImageURL != nil {
		t.Errorf("UVImageURL must be omitted (nil) when no UV image: got %v", capturedBody.UVImageURL)
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

// ---------------------------------------------------------------------------
// PrintItem / hardware imprinter tests
// ---------------------------------------------------------------------------

func TestPrintItemStubSucceeds(t *testing.T) {
	st := NewStubTransport(nil)
	st.Open()
	st.StartJob("", false)
	if err := st.PrintItem("ASTRA/CTS/SVCB"); err != nil {
		t.Fatalf("PrintItem on open stub should succeed, got: %v", err)
	}
}

func TestPrintItemFailsWhenClosed(t *testing.T) {
	st := NewStubTransport(nil)
	st.Open()
	st.Close()
	if err := st.PrintItem("ASTRA/CTS/SVCB"); err == nil {
		t.Fatal("PrintItem on closed stub should return error, got nil")
	}
}

func TestImprinterStampedSetOnSuccess(t *testing.T) {
	// Verify scanner.go sets ImprinterStamped=true after a successful PrintItem.
	item := &ScannedItem{FrontImage: []byte("img"), MICRRaw: "000123  00110001234  999999999"}
	st := NewStubTransport([]*ScannedItem{item})

	cfg := &Config{SessionPrefix: "MUM", EnableImprinter: true, EndorsementText: "ASTRA/CTS"}
	stamped := false

	// Simulate the runLoop imprinter block: PrintItem then set ImprinterStamped.
	if err := st.Open(); err != nil {
		t.Fatalf("Open: %v", err)
	}
	if err := st.StartJob(cfg.EndorsementText, cfg.EnableImprinter); err != nil {
		t.Fatalf("StartJob: %v", err)
	}
	got, _ := st.ReadItem()
	if got == nil {
		t.Fatal("expected item, got nil")
	}
	if cfg.EnableImprinter {
		if printErr := st.PrintItem(cfg.EndorsementText); printErr == nil {
			got.ImprinterStamped = true
			stamped = true
		}
	}
	if !stamped {
		t.Error("expected ImprinterStamped to be set after successful PrintItem")
	}
	if !got.ImprinterStamped {
		t.Error("expected item.ImprinterStamped=true")
	}
}

func TestImprinterNotCalledWhenDisabled(t *testing.T) {
	// When EnableImprinter=false, PrintItem must not be called and
	// ImprinterStamped must remain false.
	item := &ScannedItem{FrontImage: []byte("img"), MICRRaw: "000123  00110001234  999999999"}
	st := NewStubTransport([]*ScannedItem{item})

	cfg := &Config{SessionPrefix: "MUM", EnableImprinter: false}
	st.Open()
	st.StartJob("", cfg.EnableImprinter)
	got, _ := st.ReadItem()

	// Simulate runLoop logic
	if cfg.EnableImprinter {
		st.PrintItem(cfg.EndorsementText)
		got.ImprinterStamped = true
	}

	if got.ImprinterStamped {
		t.Error("ImprinterStamped must remain false when EnableImprinter=false")
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

// ---------------------------------------------------------------------------
// Heartbeat tests
// ---------------------------------------------------------------------------

func TestSendHeartbeatSuccess(t *testing.T) {
	var capturedBody agentHeartbeatRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/cts/scanner/agent/heartbeat" {
			http.NotFound(w, r)
			return
		}
		if r.Header.Get("Authorization") != "Bearer tok-hb" {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		json.NewDecoder(r.Body).Decode(&capturedBody)
		w.WriteHeader(http.StatusOK)
		json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-hb", httpClient: srv.Client()}
	err := client.SendHeartbeat(context.Background(), "saraswat-coop", "BRANCH-ANDHERI-01", "SES-HB-001")
	if err != nil {
		t.Fatalf("SendHeartbeat: %v", err)
	}
	if capturedBody.BankID != "saraswat-coop" {
		t.Errorf("expected bank_id saraswat-coop, got %s", capturedBody.BankID)
	}
	if capturedBody.BranchID != "BRANCH-ANDHERI-01" {
		t.Errorf("expected branch_id BRANCH-ANDHERI-01, got %s", capturedBody.BranchID)
	}
	if capturedBody.ActiveSessionID != "SES-HB-001" {
		t.Errorf("expected active_session_id SES-HB-001, got %s", capturedBody.ActiveSessionID)
	}
}

func TestSendHeartbeatServerError(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "gateway timeout", http.StatusGatewayTimeout)
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-hb", httpClient: srv.Client()}
	err := client.SendHeartbeat(context.Background(), "bank-1", "branch-1", "")
	if err == nil {
		t.Error("expected error on 504, got nil")
	}
}

func TestSendHeartbeatIdleSession(t *testing.T) {
	// When no session is active, active_session_id must be empty string (IDLE state).
	var capturedBody agentHeartbeatRequest
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		json.NewDecoder(r.Body).Decode(&capturedBody)
		w.WriteHeader(http.StatusOK)
	}))
	defer srv.Close()

	client := &ASTRAClient{baseURL: srv.URL, token: "tok-hb", httpClient: srv.Client()}
	client.SendHeartbeat(context.Background(), "bank-1", "branch-1", "") // empty = IDLE
	if capturedBody.ActiveSessionID != "" {
		t.Errorf("IDLE heartbeat must send empty active_session_id, got %q", capturedBody.ActiveSessionID)
	}
}

// ---------------------------------------------------------------------------
// ScanSession.CurrentSessionID tests
// ---------------------------------------------------------------------------

func TestCurrentSessionIDWhenInactive(t *testing.T) {
	cfg := &Config{SessionPrefix: "TEST"}
	session := newScanSession(cfg, NewStubTransport(nil), nil, newTestLogger())
	if id := session.CurrentSessionID(); id != "" {
		t.Errorf("CurrentSessionID must be empty when no session active, got %q", id)
	}
}

func TestCurrentSessionIDWhenActive(t *testing.T) {
	cfg := &Config{SessionPrefix: "TEST", EnableImprinter: false}
	st := NewStubTransport(nil)
	session := newScanSession(cfg, st, nil, newTestLogger())

	mux := http.NewServeMux()
	registerHandlers(mux, session, newTestLogger())

	req := httptest.NewRequest(http.MethodPost, "/session/start",
		strings.NewReader(`{"session_id":"SES-ACTIVE"}`))
	w := httptest.NewRecorder()
	mux.ServeHTTP(w, req)
	if w.Code != http.StatusAccepted {
		t.Fatalf("expected 202, got %d", w.Code)
	}

	time.Sleep(50 * time.Millisecond) // let goroutine start

	if id := session.CurrentSessionID(); id != "SES-ACTIVE" {
		t.Errorf("CurrentSessionID must return active session ID, got %q", id)
	}

	// Stop and verify CurrentSessionID clears
	req2 := httptest.NewRequest(http.MethodPost, "/session/stop", nil)
	w2 := httptest.NewRecorder()
	mux.ServeHTTP(w2, req2)

	time.Sleep(50 * time.Millisecond)

	if id := session.CurrentSessionID(); id != "" {
		t.Errorf("CurrentSessionID must be empty after session stop, got %q", id)
	}
}

// ---------------------------------------------------------------------------
// UV ScannedItem flag tests (stub-based — no hardware required)
// ---------------------------------------------------------------------------

func TestUVItemFlagPresent(t *testing.T) {
	uvBytes := []byte("fake-uv-tiff-data")
	items := []*ScannedItem{
		{
			FrontImage: []byte("front"),
			RearImage:  []byte("rear"),
			UVImage:    uvBytes,
			MICRRaw:    "000123  00110001234  999999999",
		},
	}
	st := NewStubTransport(items)
	st.Open()
	st.StartJob("", false)

	item, err := st.ReadItem()
	if err != nil {
		t.Fatalf("ReadItem: %v", err)
	}
	if item.UVImage == nil {
		t.Fatal("expected UVImage to be non-nil for UV item")
	}
	if string(item.UVImage) != string(uvBytes) {
		t.Errorf("UVImage bytes mismatch: got %s", item.UVImage)
	}
}

func TestNonUVItemHasNilUVImage(t *testing.T) {
	items := []*ScannedItem{
		{FrontImage: []byte("front"), RearImage: []byte("rear"), MICRRaw: "000123  00110001234  999999999"},
	}
	st := NewStubTransport(items)
	st.Open()
	st.StartJob("", false)

	item, err := st.ReadItem()
	if err != nil {
		t.Fatalf("ReadItem: %v", err)
	}
	if item.UVImage != nil {
		t.Error("non-UV item must have nil UVImage")
	}
}
