package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"time"
)

// agentHeartbeatRequest mirrors POST /v1/cts/scanner/agent/heartbeat.
type agentHeartbeatRequest struct {
	BankID          string `json:"bank_id"`
	BranchID        string `json:"branch_id"`
	ActiveSessionID string `json:"active_session_id"` // empty = IDLE
}

// SendHeartbeat posts a single heartbeat. activeSessionID is empty when no
// scan session is running (IDLE state); non-empty means ACTIVE.
func (c *ASTRAClient) SendHeartbeat(ctx context.Context, bankID, branchID, activeSessionID string) error {
	body, _ := json.Marshal(agentHeartbeatRequest{
		BankID:          bankID,
		BranchID:        branchID,
		ActiveSessionID: activeSessionID,
	})
	req, err := http.NewRequestWithContext(ctx,
		http.MethodPost, c.baseURL+"/v1/cts/scanner/agent/heartbeat", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("heartbeat request: %w", err)
	}
	c.setHeaders(req)

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("heartbeat http: %w", err)
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body) //nolint:errcheck

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("heartbeat: server returned %d", resp.StatusCode)
	}
	return nil
}

// StartHeartbeatLoop sends a heartbeat every 30 seconds until ctx is cancelled.
// Runs in the background — call as a goroutine from main.
// A failed heartbeat is logged as a warning; it never stops the loop.
func StartHeartbeatLoop(ctx context.Context, cfg *Config, client *ASTRAClient, session *ScanSession, logger *slog.Logger) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	// Fire immediately so the dashboard shows a status as soon as the agent starts.
	doHeartbeat(ctx, cfg, client, session, logger)

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			doHeartbeat(ctx, cfg, client, session, logger)
		}
	}
}

func doHeartbeat(ctx context.Context, cfg *Config, client *ASTRAClient, session *ScanSession, logger *slog.Logger) {
	hbCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
	defer cancel()

	if err := client.SendHeartbeat(hbCtx, cfg.BankID, cfg.BranchID, session.CurrentSessionID()); err != nil {
		// Warn only — a transient network blip must not alarm the teller.
		// The dashboard will show OFFLINE after 90s of missed heartbeats.
		logger.Warn("heartbeat failed", "error", err)
	}
}
