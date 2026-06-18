package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// OEM is an ATM manufacturer identifier detected by fingerprinting.
type OEM string

const (
	OEMUnknown          OEM = "UNKNOWN"
	OEMNCR              OEM = "NCR"
	OEMDieboldNixdorf   OEM = "DIEBOLD_NIXDORF"
	OEMNautilusHyosung  OEM = "NAUTILUS_HYOSUNG"
	OEMHitachi          OEM = "HITACHI"
	OEMGRGBanking       OEM = "GRG_BANKING"
)

// oemSignature describes how to identify one OEM from the file header.
type oemSignature struct {
	oem        OEM
	extensions []string // file extensions this OEM produces (lower-case, with dot)
	headers    [][]byte // byte patterns in first 512 bytes that confirm this OEM
}

// oemSignatures is the fingerprint registry — order matters (more specific first).
var oemSignatures = []oemSignature{
	{
		oem:        OEMNCR,
		extensions: []string{".ej", ".ejl"},
		headers:    [][]byte{[]byte("*EJ*"), []byte("NCR "), []byte("APTRA")},
	},
	{
		oem:        OEMDieboldNixdorf,
		extensions: []string{".dnt", ".dnj"},
		headers:    [][]byte{[]byte("WINCOR"), []byte("DIEBOLD"), []byte("DN EJ")},
	},
	{
		oem:        OEMNautilusHyosung,
		extensions: []string{".mci", ".nhej"},
		headers:    [][]byte{[]byte("MCI "), []byte("HYOSUNG"), []byte("NH ATM")},
	},
	{
		oem:        OEMHitachi,
		extensions: []string{".htj", ".log"},
		headers:    [][]byte{[]byte("HITACHI"), []byte("HT EJ "), []byte("OKI ")},
	},
	{
		oem:        OEMGRGBanking,
		extensions: []string{".grg", ".gej"},
		headers:    [][]byte{[]byte("GRG "), []byte("\xef\xbb\xbfGRG"), []byte("GRGBANKING")},
	},
}

// fingerprintOEM reads the first 512 bytes of a file and matches against
// known OEM header patterns. Extension is used as a tiebreaker when multiple
// header patterns match. Returns OEMUnknown if no pattern matches.
func fingerprintOEM(path string, header []byte) OEM {
	ext := strings.ToLower(filepath.Ext(path))
	upperHeader := bytes.ToUpper(header)

	var extMatch OEM
	for _, sig := range oemSignatures {
		// Check header bytes first (stronger signal than extension).
		for _, pattern := range sig.headers {
			if bytes.Contains(upperHeader, bytes.ToUpper(pattern)) {
				return sig.oem
			}
		}
		// Track extension match as fallback.
		if extMatch == OEMUnknown {
			for _, e := range sig.extensions {
				if ext == e {
					extMatch = sig.oem
					break
				}
			}
		}
	}
	if extMatch != "" {
		return extMatch
	}
	return OEMUnknown
}

// fileWatcher polls cfg.EJWatchDir for new EJ files at a fixed interval.
// On each new file: fingerprint → compress+encrypt → buffer → upload.
type fileWatcher struct {
	cfg  *config
	comp *compressor
	buf  *buffer
	up   *uploader
	seen map[string]struct{} // tracks files already processed in this session
}

func newFileWatcher(cfg *config, comp *compressor, buf *buffer, up *uploader) *fileWatcher {
	return &fileWatcher{
		cfg:  cfg,
		comp: comp,
		buf:  buf,
		up:   up,
		seen: make(map[string]struct{}),
	}
}

func (fw *fileWatcher) run(ctx context.Context) {
	// Seed seen map from the buffer DB so we don't reprocess files
	// that were already picked up before a restart.
	known, _ := fw.buf.listAllOriginalPaths()
	for _, p := range known {
		fw.seen[p] = struct{}{}
	}

	ticker := time.NewTicker(time.Duration(fw.cfg.WatchIntervalSec) * time.Second)
	defer ticker.Stop()

	slog.Info("file watcher started", "dir", fw.cfg.EJWatchDir, "interval_sec", fw.cfg.WatchIntervalSec)

	for {
		select {
		case <-ctx.Done():
			slog.Info("file watcher stopped")
			return
		case <-ticker.C:
			fw.scan()
		}
	}
}

func (fw *fileWatcher) scan() {
	entries, err := os.ReadDir(fw.cfg.EJWatchDir)
	if err != nil {
		slog.Error("watch dir read failed", "dir", fw.cfg.EJWatchDir, "err", err)
		return
	}

	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		path := filepath.Join(fw.cfg.EJWatchDir, entry.Name())
		if _, seen := fw.seen[path]; seen {
			continue
		}
		fw.seen[path] = struct{}{}
		fw.processFile(path)
	}
}

func (fw *fileWatcher) processFile(path string) {
	raw, err := os.ReadFile(path)
	if err != nil {
		slog.Error("file read failed", "path", path, "err", err)
		return
	}

	// Read up to 512 bytes for OEM fingerprinting — do not parse full file at edge.
	headerSize := 512
	if len(raw) < headerSize {
		headerSize = len(raw)
	}
	oem := fingerprintOEM(path, raw[:headerSize])

	// SHA-256 of raw content — sent to central so it can verify integrity after decrypt.
	hash := sha256.Sum256(raw)
	fileHash := hex.EncodeToString(hash[:])

	blob, err := fw.comp.process(raw)
	if err != nil {
		slog.Error("compress+encrypt failed", "path", path, "err", err)
		return
	}

	// Derive the file date from the file's modification time.
	info, err := os.Stat(path)
	if err != nil {
		slog.Error("stat failed", "path", path, "err", err)
		return
	}
	fileDate := info.ModTime().UTC().Format("2006-01-02")

	// Write the encrypted blob to the buffer staging directory.
	blobName := fmt.Sprintf("%s_%s_%s.enc", fw.cfg.ATMID, fileDate, fileHash[:12])
	blobPath := filepath.Join(fw.cfg.BufferDir, blobName)
	if err := os.MkdirAll(fw.cfg.BufferDir, 0o700); err != nil {
		slog.Error("buffer dir create failed", "err", err)
		return
	}
	if err := os.WriteFile(blobPath, blob, 0o600); err != nil {
		slog.Error("blob write failed", "path", blobPath, "err", err)
		return
	}

	id, err := fw.buf.enqueue(fw.cfg.ATMID, fileDate, path, blobPath, fileHash, string(oem))
	if err != nil {
		slog.Error("buffer enqueue failed", "path", path, "err", err)
		return
	}

	slog.Info("file queued",
		"id", id,
		"atm_id", fw.cfg.ATMID,
		"file_date", fileDate,
		"oem", oem,
		"original_bytes", len(raw),
		"compressed_encrypted_bytes", len(blob),
		"file_hash", fileHash[:12]+"...",
	)

	// Attempt immediate upload — if it fails, the retry loop picks it up.
	if err := fw.up.uploadOne(id, blobPath, fw.cfg.ATMID, fileDate, fileHash, string(oem)); err != nil {
		slog.Warn("immediate upload failed — queued for retry", "id", id, "err", err)
	}
}
