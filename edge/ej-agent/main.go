package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

// version and gitSHA are injected at build time via -ldflags.
var (
	version = "dev"
	gitSHA  = "unknown"
)

func main() {
	// Dockerfile HEALTHCHECK calls: /ej-agent -health-check
	// It performs a local HTTP GET to the liveness endpoint and exits 0/1.
	if len(os.Args) == 2 && os.Args[1] == "-health-check" {
		runHealthCheck()
		return
	}
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(log)

	cfg, err := loadConfig()
	if err != nil {
		slog.Error("config load failed", "err", err)
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()

	buf, err := newBuffer(cfg.BufferDBPath)
	if err != nil {
		slog.Error("buffer init failed", "err", err)
		os.Exit(1)
	}
	defer buf.close()

	comp, err := newCompressor(cfg.EncryptionKey)
	if err != nil {
		slog.Error("compressor init failed", "err", err)
		os.Exit(1)
	}

	up := newUploader(cfg, buf)
	fw := newFileWatcher(cfg, comp, buf, up)

	srv, err := newMCPServer(cfg, buf)
	if err != nil {
		slog.Error("mcp server init failed", "err", err)
		os.Exit(1)
	}

	go fw.run(ctx)
	go up.runRetryLoop(ctx)

	slog.Info("ej-agent started",
		"atm_id", cfg.ATMID,
		"bank_id", cfg.BankID,
		"branch_id", cfg.BranchID,
		"watch_dir", cfg.EJWatchDir,
		"mcp_addr", cfg.MCPAddr,
	)

	// MCP server blocks until ctx is cancelled (SIGTERM/SIGINT).
	if err := srv.run(ctx); err != nil {
		slog.Error("mcp server stopped", "err", err)
		os.Exit(1)
	}

	slog.Info("ej-agent stopped cleanly")
}

func runHealthCheck() {
	addr := envOr("ASTRA_MCP_ADDR", ":8443")
	url := fmt.Sprintf("https://localhost%s/health/live", addr)

	// Use a plain client — no mTLS for loopback health check.
	client := &http.Client{Timeout: 4 * time.Second}
	resp, err := client.Get(url)
	if err != nil || resp.StatusCode != http.StatusOK {
		os.Exit(1)
	}
	os.Exit(0)
}
