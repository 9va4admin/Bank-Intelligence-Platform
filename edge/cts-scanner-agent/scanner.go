package main

import (
	"context"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// SessionItemStatus represents the processing outcome of one cheque in the session.
type SessionItemStatus string

const (
	StatusSubmitted       SessionItemStatus = "SUBMITTED"
	StatusDoubleFeed      SessionItemStatus = "DOUBLE_FEED_DETECTED"
	StatusImprinterFault  SessionItemStatus = "IMPRINTER_FAULT"
	StatusUploadFailed    SessionItemStatus = "UPLOAD_FAILED"
)

// SessionItem is a teller-visible record of one cheque position in the scan session.
// Shown in the Branch Scan Dashboard — doubles as the local session log.
type SessionItem struct {
	Position         int               `json:"position"`           // 1-based counter within session
	ScanID           string            `json:"scan_id"`
	InstrumentID     string            `json:"instrument_id,omitempty"`
	WorkflowID       string            `json:"workflow_id,omitempty"`
	Status           SessionItemStatus `json:"status"`
	ImprinterStamped bool              `json:"imprinter_stamped"`
	MICRSuffix       string            `json:"micr_suffix"`        // last 4 chars — safe to display
	Timestamp        time.Time         `json:"timestamp"`
	ErrorMessage     string            `json:"error_message,omitempty"`
}

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

	itemsMu sync.RWMutex
	items   []SessionItem // in-memory session log — survives for the life of the session
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

// GetItems returns a snapshot of all session items — safe for concurrent reads.
func (s *ScanSession) GetItems() []SessionItem {
	s.itemsMu.RLock()
	defer s.itemsMu.RUnlock()
	out := make([]SessionItem, len(s.items))
	copy(out, s.items)
	return out
}

func (s *ScanSession) appendItem(item SessionItem) {
	s.itemsMu.Lock()
	defer s.itemsMu.Unlock()
	s.items = append(s.items, item)
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
			position := int(s.counter.Add(1))
			scanID := s.buildScanID(position)
			s.logger.Warn("double feed detected — held at branch, not sent to central",
				"session_id", s.sessionID,
				"position", position,
				"scan_id", scanID,
			)

			// Record in local session log so Branch Dashboard shows it
			s.appendItem(SessionItem{
				Position:   position,
				ScanID:     scanID,
				Status:     StatusDoubleFeed,
				MICRSuffix: micrSuffix(item.MICRRaw),
				Timestamp:  time.Now().UTC(),
			})

			// Report to central so the Branch Dashboard (React) can surface it.
			// Best-effort — a network failure must not block the scan session.
			go func(pos int, sid string) {
				reportCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
				defer cancel()
				if err := s.client.ReportScanEvent(reportCtx, &ScanEventRequest{
					BankID:          s.cfg.BankID,
					BranchID:        s.cfg.BranchID,
					SessionID:       s.sessionID,
					ScanID:          sid,
					EventType:       "DOUBLE_FEED_DETECTED",
					PositionInBatch: pos,
					MICRSuffix:      micrSuffix(item.MICRRaw),
				}); err != nil {
					s.logger.Warn("double feed event report failed — local log still present",
						"scan_id", sid, "error", err)
				}
			}(position, scanID)

			// Scanner has already physically ejected the overlapping documents.
			// Operator must separate them and re-feed individually.
			continue
		}

		// Hardware endorsement stamp — called while the cheque is still inside
		// the scanner transport path, before it exits to the output pocket.
		// Must happen immediately after ReadItem, before the next cheque is fed.
		imprinterFault := false
		if s.cfg.EnableImprinter {
			if printErr := s.transport.PrintItem(s.cfg.EndorsementText); printErr != nil {
				s.logger.Error("imprinter hardware fault — cheque not stamped",
					"session_id", s.sessionID, "error", printErr)
				imprinterFault = true
				// Non-fatal: cheque continues but ASTRA flags it needs manual re-stamp.
			} else {
				item.ImprinterStamped = true
			}
		}

		if err := s.handleItem(ctx, item, imprinterFault); err != nil {
			// Log and continue — one bad cheque must not kill the session
			s.logger.Error("item processing failed",
				"session_id", s.sessionID, "error", err)
		}
	}
}

func (s *ScanSession) handleItem(ctx context.Context, item *ScannedItem, imprinterFault bool) error {
	position := int(s.counter.Add(1))
	scanID := s.buildScanID(position)
	instrumentID := "INS-" + scanID

	chequeNumber := extractChequeNumber(item.MICRRaw)
	suffix := micrSuffix(item.MICRRaw)

	s.logger.Info("processing scanned cheque",
		"scan_id", scanID,
		"session_id", s.sessionID,
		"position", position,
		"micr_suffix", suffix,
		"imprinter_stamped", item.ImprinterStamped,
		"imprinter_fault", imprinterFault,
	)

	// Determine initial status — imprinter fault is advisory, not a hold.
	status := StatusSubmitted
	if imprinterFault {
		status = StatusImprinterFault
	}

	// Optimistically append to session log before upload; update on failure.
	sessionItem := SessionItem{
		Position:         position,
		ScanID:           scanID,
		InstrumentID:     instrumentID,
		Status:           status,
		ImprinterStamped: item.ImprinterStamped,
		MICRSuffix:       suffix,
		Timestamp:        time.Now().UTC(),
	}
	s.appendItem(sessionItem)

	resp, err := processScannedItem(ctx, s.client, s.cfg,
		s.sessionID, scanID, instrumentID, item, chequeNumber)
	if err != nil {
		// Update the session item to reflect upload/submit failure.
		s.itemsMu.Lock()
		for i := range s.items {
			if s.items[i].ScanID == scanID {
				s.items[i].Status = StatusUploadFailed
				s.items[i].ErrorMessage = err.Error()
				break
			}
		}
		s.itemsMu.Unlock()
		return fmt.Errorf("processScannedItem scan_id=%s: %w", scanID, err)
	}

	// Update session item with workflow ID returned from central.
	s.itemsMu.Lock()
	for i := range s.items {
		if s.items[i].ScanID == scanID {
			s.items[i].WorkflowID = resp.WorkflowID
			break
		}
	}
	s.itemsMu.Unlock()

	s.logger.Info("cheque submitted to ASTRA",
		"scan_id", resp.ScanID,
		"workflow_id", resp.WorkflowID,
		"path", resp.Path,
	)
	return nil
}

// buildScanID produces a deterministic, per-session unique scan ID from a position.
// Format: SCAN-{YYYYMMDD}-{SessionPrefix}-{position:05d}
// position is the 1-based counter already incremented by the caller.
func (s *ScanSession) buildScanID(position int) string {
	date := time.Now().UTC().Format("20060102")
	return fmt.Sprintf("SCAN-%s-%s-%05d", date, s.cfg.SessionPrefix, position)
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
