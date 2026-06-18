package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"log/slog"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"os"
	"time"
)

type uploader struct {
	cfg    *config
	buf    *buffer
	client *http.Client
}

func newUploader(cfg *config, buf *buffer) *uploader {
	client, err := buildMTLSClient(cfg.TLSCertPath, cfg.TLSKeyPath, cfg.TLSCAPath)
	if err != nil {
		// Fatal — without mTLS we cannot upload securely.
		slog.Error("mTLS client build failed", "err", err)
		os.Exit(1)
	}
	return &uploader{cfg: cfg, buf: buf, client: client}
}

// runRetryLoop picks up PENDING records from the buffer and retries uploads
// until they succeed or hit MaxUploadAttempts. Runs until ctx is cancelled.
func (u *uploader) runRetryLoop(ctx context.Context) {
	ticker := time.NewTicker(time.Duration(u.cfg.RetryIntervalSec) * time.Second)
	defer ticker.Stop()

	slog.Info("uploader retry loop started", "interval_sec", u.cfg.RetryIntervalSec)

	for {
		select {
		case <-ctx.Done():
			slog.Info("uploader retry loop stopped")
			return
		case <-ticker.C:
			u.retryPending()
		}
	}
}

func (u *uploader) retryPending() {
	records, err := u.buf.listPending()
	if err != nil {
		slog.Error("buffer list pending failed", "err", err)
		return
	}
	for _, r := range records {
		if r.AttemptCount >= u.cfg.MaxUploadAttempts {
			continue // markAttempt already set status=FAILED
		}
		if err := u.uploadOne(r.ID, r.BlobPath, r.ATMID, r.FileDate, r.FileHash, r.OEM); err != nil {
			slog.Warn("retry upload failed", "id", r.ID, "attempt", r.AttemptCount+1, "err", err)
		}
	}
}

// uploadOne sends a single encrypted blob to the central EJ ingestion gateway.
// On success it marks the buffer record as UPLOADED.
// On failure it increments the attempt counter (buffer handles FAILED threshold).
func (u *uploader) uploadOne(id int64, blobPath, atmID, fileDate, fileHash, oem string) error {
	blob, err := os.ReadFile(blobPath)
	if err != nil {
		_ = u.buf.markAttempt(id, true)
		return fmt.Errorf("read blob %s: %w", blobPath, err)
	}

	body, contentType, err := buildMultipartBody(blob, atmID, fileDate, fileHash, oem, u.cfg.BankID)
	if err != nil {
		_ = u.buf.markAttempt(id, true)
		return fmt.Errorf("build multipart: %w", err)
	}

	req, err := http.NewRequest(http.MethodPost, u.cfg.CentralURL, body)
	if err != nil {
		_ = u.buf.markAttempt(id, true)
		return fmt.Errorf("build request: %w", err)
	}
	req.Header.Set("Content-Type", contentType)
	req.Header.Set("X-ASTRA-ATM-ID", atmID)
	req.Header.Set("X-ASTRA-Bank-ID", u.cfg.BankID)
	req.Header.Set("X-ASTRA-Branch-ID", u.cfg.BranchID)
	req.Header.Set("X-ASTRA-File-Date", fileDate)
	req.Header.Set("X-ASTRA-File-Hash", fileHash)
	req.Header.Set("X-ASTRA-OEM", oem)
	req.Header.Set("X-ASTRA-Buffer-ID", fmt.Sprintf("%d", id))

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	req = req.WithContext(ctx)

	resp, err := u.client.Do(req)
	if err != nil {
		_ = u.buf.markAttempt(id, true)
		return fmt.Errorf("http do: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusAccepted && resp.StatusCode != http.StatusOK {
		_ = u.buf.markAttempt(id, true)
		return fmt.Errorf("central returned %d", resp.StatusCode)
	}

	if err := u.buf.markUploaded(id); err != nil {
		slog.Error("mark uploaded failed", "id", id, "err", err)
	}

	slog.Info("upload ok",
		"id", id,
		"atm_id", atmID,
		"file_date", fileDate,
		"oem", oem,
		"bytes", len(blob),
	)
	return nil
}

func buildMultipartBody(blob []byte, atmID, fileDate, fileHash, oem, bankID string) (*bytes.Buffer, string, error) {
	var body bytes.Buffer
	w := multipart.NewWriter(&body)

	// Metadata part — plain JSON-like fields as form values.
	_ = w.WriteField("atm_id", atmID)
	_ = w.WriteField("bank_id", bankID)
	_ = w.WriteField("file_date", fileDate)
	_ = w.WriteField("file_hash", fileHash)
	_ = w.WriteField("oem", oem)

	// Blob part — encrypted+compressed binary content.
	partHeader := make(textproto.MIMEHeader)
	partHeader.Set("Content-Disposition", fmt.Sprintf(
		`form-data; name="ej_blob"; filename="%s_%s.enc"`, atmID, fileDate))
	partHeader.Set("Content-Type", "application/octet-stream")

	part, err := w.CreatePart(partHeader)
	if err != nil {
		return nil, "", err
	}
	if _, err := part.Write(blob); err != nil {
		return nil, "", err
	}
	if err := w.Close(); err != nil {
		return nil, "", err
	}
	return &body, w.FormDataContentType(), nil
}

func buildMTLSClient(certPath, keyPath, caPath string) (*http.Client, error) {
	cert, err := tls.LoadX509KeyPair(certPath, keyPath)
	if err != nil {
		return nil, fmt.Errorf("load client cert: %w", err)
	}

	caPEM, err := os.ReadFile(caPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert: %w", err)
	}
	pool := x509.NewCertPool()
	if !pool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert failed")
	}

	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{cert},
		RootCAs:      pool,
		MinVersion:   tls.VersionTLS13,
	}

	return &http.Client{
		Transport: &http.Transport{TLSClientConfig: tlsCfg},
		Timeout:   45 * time.Second,
	}, nil
}
