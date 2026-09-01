package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// ASTRAClient handles all HTTP communication with the ASTRA API.
// All calls use mTLS — Istio Ingress handles TLS termination on the server
// side; the scanner agent uses the bank's internal CA bundle for verification.
type ASTRAClient struct {
	baseURL    string
	token      string
	httpClient *http.Client
}

func newASTRAClient(cfg *Config) *ASTRAClient {
	return &ASTRAClient{
		baseURL: cfg.ASTRABaseURL,
		token:   cfg.ASTRAToken,
		httpClient: &http.Client{
			Timeout: cfg.HTTPTimeout,
		},
	}
}

// UploadURLResponse is returned by POST /v1/cts/outward/scan/upload-url.
type UploadURLResponse struct {
	FrontPresignedURL string `json:"front_presigned_url"`
	RearPresignedURL  string `json:"rear_presigned_url"`
	FrontObjectURL    string `json:"front_object_url"` // s3://... URL for submit request
	RearObjectURL     string `json:"rear_object_url"`
	ExpiresAt         int64  `json:"expires_at"` // Unix timestamp
}

// RequestUploadURLs asks ASTRA to provision a pair of pre-signed MinIO URLs
// for uploading front and rear cheque images for a given scan_id.
func (c *ASTRAClient) RequestUploadURLs(ctx context.Context, scanID string) (*UploadURLResponse, error) {
	body, _ := json.Marshal(map[string]string{"scan_id": scanID})
	req, err := http.NewRequestWithContext(ctx,
		http.MethodPost, c.baseURL+"/v1/cts/outward/scan/upload-url", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("upload-url request: %w", err)
	}
	c.setHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("upload-url http: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("upload-url: server returned %d: %s", resp.StatusCode, b)
	}

	var out UploadURLResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("upload-url decode: %w", err)
	}
	return &out, nil
}

// UploadImage PUTs image bytes to a pre-signed MinIO URL.
// The content-type is image/tiff for CTS-2010 compliant TIFF images.
func (c *ASTRAClient) UploadImage(ctx context.Context, presignedURL string, imageBytes []byte) error {
	req, err := http.NewRequestWithContext(ctx,
		http.MethodPut, presignedURL, bytes.NewReader(imageBytes))
	if err != nil {
		return fmt.Errorf("upload image request: %w", err)
	}
	req.Header.Set("Content-Type", "image/tiff")
	req.ContentLength = int64(len(imageBytes))

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("upload image http: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 256))
		return fmt.Errorf("upload image: MinIO returned %d: %s", resp.StatusCode, b)
	}
	return nil
}

// ScanSubmitRequest mirrors POST /v1/cts/outward/scan/submit request body.
type ScanSubmitRequest struct {
	ScanID           string   `json:"scan_id"`
	InstrumentID     string   `json:"instrument_id"`
	BankIFSC         string   `json:"bank_ifsc"`
	BankID           string   `json:"bank_id"`
	BranchID         string   `json:"branch_id"`         // ASTRA branch ID — required for ops dashboard routing
	SessionID        string   `json:"session_id"`
	ImageFrontURL    string   `json:"image_front_url"`
	ImageRearURL     string   `json:"image_rear_url"`
	ChequeNumber     string   `json:"cheque_number,omitempty"`
	FrontDPI         *int     `json:"front_dpi,omitempty"`
	RearDPI          *int     `json:"rear_dpi,omitempty"`
	FrontColourDepth *int     `json:"front_colour_depth,omitempty"`
	RearColourDepth  *int     `json:"rear_colour_depth,omitempty"`
	FrontFileSizeKB  *float64 `json:"front_file_size_kb,omitempty"`
	RearFileSizeKB   *float64 `json:"rear_file_size_kb,omitempty"`
	// MICRHardwareRaw is the raw E13B string from TransportGetMICR().
	// When present, the backend uses the CR-120 single-pass Qwen2-VL path.
	// Never logged in full on the server side — contains account number.
	MICRHardwareRaw  *string `json:"micr_hardware_raw,omitempty"`
	ImprinterStamped bool    `json:"imprinter_stamped"`  // true = rear endorsement was printed
	PuID             *string `json:"pu_id,omitempty"`
}

// ScanEventRequest mirrors POST /v1/cts/outward/scan/event — lightweight event
// for non-submit outcomes: double-feed detection, imprinter fault, etc.
type ScanEventRequest struct {
	BankID          string `json:"bank_id"`
	BranchID        string `json:"branch_id"`
	SessionID       string `json:"session_id"`
	ScanID          string `json:"scan_id"`           // generated even for failed scans
	EventType       string `json:"event_type"`        // DOUBLE_FEED_DETECTED | IMPRINTER_FAULT
	PositionInBatch int    `json:"position_in_batch"` // counter within the session
	MICRSuffix      string `json:"micr_suffix,omitempty"` // last 4 chars only
}

// ScanSubmitResponse mirrors POST /v1/cts/outward/scan/submit response body.
type ScanSubmitResponse struct {
	ScanID       string `json:"scan_id"`
	InstrumentID string `json:"instrument_id"`
	WorkflowID   string `json:"workflow_id"`
	Status       string `json:"status"` // "ACCEPTED"
	Path         string `json:"path"`   // "CR120" | "LEGACY"
}

// ReportScanEvent calls POST /v1/cts/outward/scan/event for non-submit outcomes
// (double-feed, imprinter fault). The scan is held at the branch and not processed
// centrally — the ops dashboard shows it as requiring re-scan.
func (c *ASTRAClient) ReportScanEvent(ctx context.Context, req *ScanEventRequest) error {
	body, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("report scan event marshal: %w", err)
	}
	httpReq, err := http.NewRequestWithContext(ctx,
		http.MethodPost, c.baseURL+"/v1/cts/outward/scan/event", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("report scan event request: %w", err)
	}
	c.setHeaders(httpReq)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("report scan event http: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 256))
		return fmt.Errorf("report scan event: server returned %d: %s", resp.StatusCode, b)
	}
	return nil
}

// SubmitScan calls POST /v1/cts/outward/scan/submit and returns the workflow ID.
func (c *ASTRAClient) SubmitScan(ctx context.Context, req *ScanSubmitRequest) (*ScanSubmitResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("submit scan marshal: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx,
		http.MethodPost, c.baseURL+"/v1/cts/outward/scan/submit", bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("submit scan request: %w", err)
	}
	c.setHeaders(httpReq)

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return nil, fmt.Errorf("submit scan http: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusAccepted {
		b, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return nil, fmt.Errorf("submit scan: server returned %d: %s", resp.StatusCode, b)
	}

	var out ScanSubmitResponse
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		return nil, fmt.Errorf("submit scan decode: %w", err)
	}
	return &out, nil
}

func (c *ASTRAClient) setHeaders(req *http.Request) {
	req.Header.Set("Authorization", "Bearer "+c.token)
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("User-Agent", "astra-cts-scanner-agent/1.0")
}

// processScannedItem is the full pipeline for a single cheque after scan:
//  1. Request upload URLs from ASTRA
//  2. Upload front image to MinIO
//  3. Upload rear image to MinIO
//  4. POST scan submit to ASTRA
func processScannedItem(
	ctx context.Context,
	client *ASTRAClient,
	cfg *Config,
	sessionID string,
	scanID string,
	instrumentID string,
	item *ScannedItem,
	chequeNumber string,
) (*ScanSubmitResponse, error) {
	uploadCtx, cancel := context.WithTimeout(ctx, 60*time.Second)
	defer cancel()

	// Step 1 — get pre-signed upload URLs
	urls, err := client.RequestUploadURLs(uploadCtx, scanID)
	if err != nil {
		return nil, fmt.Errorf("request upload urls: %w", err)
	}

	// Step 2 — upload front image
	if err := client.UploadImage(uploadCtx, urls.FrontPresignedURL, item.FrontImage); err != nil {
		return nil, fmt.Errorf("upload front: %w", err)
	}

	// Step 3 — upload rear image
	if err := client.UploadImage(uploadCtx, urls.RearPresignedURL, item.RearImage); err != nil {
		return nil, fmt.Errorf("upload rear: %w", err)
	}

	// Step 4 — submit scan metadata
	submitReq := &ScanSubmitRequest{
		ScanID:           scanID,
		InstrumentID:     instrumentID,
		BankIFSC:         cfg.BankIFSC,
		BankID:           cfg.BankID,
		BranchID:         cfg.BranchID,
		SessionID:        sessionID,
		ImageFrontURL:    urls.FrontObjectURL,
		ImageRearURL:     urls.RearObjectURL,
		ChequeNumber:     chequeNumber,
		ImprinterStamped: item.ImprinterStamped,
	}

	// Populate optional hardware metrics
	frontDPI := item.FrontDPI
	rearDPI  := item.RearDPI
	frontCD  := item.FrontColourDepth
	rearCD   := item.RearColourDepth
	frontSz  := item.FrontFileSizeKB
	rearSz   := item.RearFileSizeKB

	if frontDPI > 0  { submitReq.FrontDPI = &frontDPI }
	if rearDPI > 0   { submitReq.RearDPI = &rearDPI }
	if frontCD > 0   { submitReq.FrontColourDepth = &frontCD }
	if rearCD > 0    { submitReq.RearColourDepth = &rearCD }
	if frontSz > 0   { submitReq.FrontFileSizeKB = &frontSz }
	if rearSz > 0    { submitReq.RearFileSizeKB = &rearSz }

	// Hardware MICR — if present, triggers the CR-120 Qwen2-VL path on the backend.
	// Never logged in full by the agent (contains account number in E13B format).
	if item.MICRRaw != "" {
		micrCopy := item.MICRRaw
		submitReq.MICRHardwareRaw = &micrCopy
	}

	submitCtx, cancel2 := context.WithTimeout(ctx, 30*time.Second)
	defer cancel2()
	return client.SubmitScan(submitCtx, submitReq)
}
