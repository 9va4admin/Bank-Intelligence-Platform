package main

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"
)

// ScanSession manages the lifecycle of one clearing session on a teller terminal.
// One session maps to one clearing window (e.g. morning session, afternoon session).
// A session contains multiple lots; lot assignment is handled server-side.
type ScanSession struct {
	cfg       *Config
	transport Transport
	client    *ASTRAClient
	logger    *slog.Logger

	sessionID string
	counter   atomic.Uint64 // per-session instrument counter for scan ID generation
	active    atomic.Bool
}

func newScanSession(cfg *Config, transport Transport, client *ASTRAClient, logger *slog.Logger) *ScanSession {
	return &ScanSession{
		cfg:       cfg,
		transport: transport,
		client:    client,
		logger:    logger,
	}
}

// Start opens the scanner, starts a job, and runs the scan loop until ctx is cancelled.
// sessionID is the clearing session identifier provided by the teller UI.
func (s *ScanSession) Start(ctx context.Context, sessionID string) error {
	if !s.active.CompareAndSwap(false, true) {
		return fmt.Errorf("scan session already active")
	}
	defer s.active.Store(false)

	s.sessionID = sessionID

	if err := s.transport.Open(); err != nil {
		return fmt.Errorf("transport open: %w", err)
	}
	defer s.transport.Close()

	endorsementText := ""
	if s.cfg.EnableImprinter {
		endorsementText = s.cfg.EndorsementText
	}

	if err := s.transport.StartJob(endorsementText, s.cfg.EnableImprinter); err != nil {
		return fmt.Errorf("transport start job: %w", err)
	}

	s.logger.Info("scan session started", "session_id", sessionID)

	go func() {
		<-ctx.Done()
		if err := s.transport.EndJob(); err != nil {
			s.logger.Warn("transport end job error", "error", err)
		}
	}()

	return s.runLoop(ctx)
}

// Stop signals the scan loop to end. Safe to call from any goroutine.
// The scan loop exits after the current cheque (if any) completes.
func (s *ScanSession) Stop() {
	_ = s.transport.EndJob()
}

// IsActive returns true if a scan session is running.
func (s *ScanSession) IsActive() bool {
	return s.active.Load()
}

func (s *ScanSession) runLoop(ctx context.Context) error {
	for {
		item, err := s.transport.ReadItem()
		if err != nil {
			if ctx.Err() != nil {
				return nil // clean shutdown
			}
			s.logger.Error("transport read item error", "error", err)
			// Brief pause before retrying — don't spin on repeated hardware errors
			select {
			case <-ctx.Done():
				return nil
			case <-time.After(500 * time.Millisecond):
			}
			continue
		}

		if item == nil {
			// EndJob was called — session complete
			s.logger.Info("scan session ended", "session_id", s.sessionID)
			return nil
		}

		if item.DoubleFeedDetected {
			s.logger.Warn("double feed detected — item skipped",
				"session_id", s.sessionID)
			// Operator must re-scan; scanner ejects the multi-feed automatically
			continue
		}

		if err := s.handleItem(ctx, item); err != nil {
			// Log and continue — one bad cheque must not kill the session
			s.logger.Error("item processing failed",
				"session_id", s.sessionID, "error", err)
		}
	}
}

func (s *ScanSession) handleItem(ctx context.Context, item *ScannedItem) error {
	scanID := s.generateScanID()
	instrumentID := "INS-" + scanID

	// cheque_number is extracted from the MICR line if present.
	chequeNumber := extractChequeNumber(item.MICRRaw)

	s.logger.Info("processing scanned cheque",
		"scan_id", scanID,
		"session_id", s.sessionID,
		"micr_suffix", micrSuffix(item.MICRRaw), // last 4 chars only — never full MICR
		"imprinter_stamped", item.ImprinterStamped,
	)

	resp, err := processScannedItem(ctx, s.client, s.cfg,
		s.sessionID, scanID, instrumentID, item, chequeNumber)
	if err != nil {
		return fmt.Errorf("processScannedItem scan_id=%s: %w", scanID, err)
	}

	s.logger.Info("cheque submitted to ASTRA",
		"scan_id", resp.ScanID,
		"workflow_id", resp.WorkflowID,
		"path", resp.Path,
	)
	return nil
}

// generateScanID produces a deterministic, per-session unique scan ID.
// Format: SCAN-{YYYYMMDD}-{SessionPrefix}-{counter:05d}
func (s *ScanSession) generateScanID() string {
	n := s.counter.Add(1)
	date := time.Now().UTC().Format("20060102")
	return fmt.Sprintf("SCAN-%s-%s-%05d", date, s.cfg.SessionPrefix, n)
}

// extractChequeNumber parses the first field of the MICR line as the cheque number.
// E13B MICR line: "<cheque> <code-line> <account>  <serial>"
// Returns empty string if line is malformed.
func extractChequeNumber(micrRaw string) string {
	if micrRaw == "" {
		return ""
	}
	parts := strings.Fields(micrRaw)
	if len(parts) == 0 {
		return ""
	}
	return parts[0]
}

// micrSuffix returns the last 4 characters of the MICR line for safe logging.
func micrSuffix(micrRaw string) string {
	if len(micrRaw) <= 4 {
		return strings.Repeat("*", len(micrRaw))
	}
	return "****" + micrRaw[len(micrRaw)-4:]
}
