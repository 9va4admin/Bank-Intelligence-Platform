// astra-cts-scanner-agent — Local Windows service that bridges the Canon CR-120
// cheque scanner to the ASTRA CTS API.
//
// Deployment:
//   - Runs as a Windows service on the teller PC (one instance per scanner)
//   - Listens on localhost:9201 for control commands from the teller UI
//   - Connects to the ASTRA API over the bank's internal network (HTTPS, mTLS at Istio)
//
// Ranger Transport API:
//   - The real implementation lives in ranger_windows.go (build tag: windows && cgo)
//   - This file uses the stub implementation for non-Windows / non-CGO builds
//
// Data flow per cheque:
//   1. TransportReadItem() blocks until a cheque passes through the CR-120
//   2. TransportGetMICR() → hardware E13B MICR line (authoritative)
//   3. TransportGetImage() → front + rear TIFF images
//   4. Upload images to MinIO via ASTRA pre-signed URL API
//   5. POST /v1/cts/outward/scan/submit → triggers OutwardScanWorkflow
//      (CR-120 path: skip GOT-OCR2, use single Qwen2-VL call)

package main

import (
	"context"
	"encoding/json"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: slog.LevelInfo,
	}))
	slog.SetDefault(logger)

	cfg, err := loadConfig()
	if err != nil {
		logger.Error("config error", "error", err)
		os.Exit(1)
	}

	transport := newTransport(cfg)
	client := newASTRAClient(cfg)
	session := newScanSession(cfg, transport, client, logger)

	// HTTP control server — teller UI calls these endpoints
	mux := http.NewServeMux()
	registerHandlers(mux, session, logger)

	srv := &http.Server{
		Addr:         cfg.ListenAddr,
		Handler:      mux,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	go func() {
		logger.Info("scanner agent listening", "addr", cfg.ListenAddr)
		if err := srv.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
			logger.Error("http server error", "error", err)
		}
	}()

	<-ctx.Done()
	logger.Info("shutting down")

	shutCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutCtx); err != nil {
		logger.Warn("http shutdown error", "error", err)
	}
	session.Stop()
}

// registerHandlers wires all HTTP control endpoints.
func registerHandlers(mux *http.ServeMux, session *ScanSession, logger *slog.Logger) {
	// GET /health — Kubernetes-style liveness probe (also used by teller UI)
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"status":         "ok",
			"session_active": session.IsActive(),
		})
	})

	// POST /session/start — teller opens a clearing session
	// Body: {"session_id": "..."}
	mux.HandleFunc("POST /session/start", func(w http.ResponseWriter, r *http.Request) {
		if session.IsActive() {
			http.Error(w, `{"error":"session already active"}`, http.StatusConflict)
			return
		}
		var body struct {
			SessionID string `json:"session_id"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.SessionID == "" {
			http.Error(w, `{"error":"session_id required"}`, http.StatusBadRequest)
			return
		}

		go func() {
			// Run the scan loop in a goroutine — /session/stop will unblock it.
			if err := session.Start(context.Background(), body.SessionID); err != nil {
				logger.Error("scan session error", "session_id", body.SessionID, "error", err)
			}
		}()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(map[string]string{
			"status":     "STARTED",
			"session_id": body.SessionID,
		})
	})

	// POST /session/stop — teller closes the clearing session
	mux.HandleFunc("POST /session/stop", func(w http.ResponseWriter, r *http.Request) {
		session.Stop()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{"status": "STOPPED"})
	})

	// GET /session/status — teller UI polls this
	mux.HandleFunc("GET /session/status", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"active": session.IsActive(),
		})
	})
}
