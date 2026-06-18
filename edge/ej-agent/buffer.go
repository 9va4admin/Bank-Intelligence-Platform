package main

import (
	"database/sql"
	"fmt"
	"time"

	_ "modernc.org/sqlite"
)

const schema = `
CREATE TABLE IF NOT EXISTS pending_uploads (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    atm_id           TEXT    NOT NULL,
    file_date        TEXT    NOT NULL,
    original_path    TEXT    NOT NULL,
    blob_path        TEXT    NOT NULL,
    file_hash        TEXT    NOT NULL,
    oem              TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'PENDING',
    attempt_count    INTEGER NOT NULL DEFAULT 0,
    last_attempt_at  TEXT,
    created_at       TEXT    NOT NULL,
    uploaded_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON pending_uploads(status);
CREATE INDEX IF NOT EXISTS idx_atm_date ON pending_uploads(atm_id, file_date);
`

// uploadRecord mirrors a row in pending_uploads.
type uploadRecord struct {
	ID             int64
	ATMID          string
	FileDate       string
	OriginalPath   string
	BlobPath       string
	FileHash       string
	OEM            string
	Status         string
	AttemptCount   int
	LastAttemptAt  *string
	CreatedAt      string
	UploadedAt     *string
}

type buffer struct {
	db *sql.DB
}

func newBuffer(dbPath string) (*buffer, error) {
	db, err := sql.Open("sqlite", dbPath+"?_journal=WAL&_timeout=5000")
	if err != nil {
		return nil, fmt.Errorf("sqlite open: %w", err)
	}
	db.SetMaxOpenConns(1) // SQLite WAL supports one writer
	if _, err := db.Exec(schema); err != nil {
		return nil, fmt.Errorf("schema init: %w", err)
	}
	return &buffer{db: db}, nil
}

func (b *buffer) close() {
	b.db.Close()
}

func (b *buffer) enqueue(atmID, fileDate, originalPath, blobPath, fileHash, oem string) (int64, error) {
	res, err := b.db.Exec(
		`INSERT INTO pending_uploads (atm_id, file_date, original_path, blob_path, file_hash, oem, created_at)
		 VALUES (?, ?, ?, ?, ?, ?, ?)`,
		atmID, fileDate, originalPath, blobPath, fileHash, oem,
		time.Now().UTC().Format(time.RFC3339),
	)
	if err != nil {
		return 0, err
	}
	return res.LastInsertId()
}

func (b *buffer) markUploaded(id int64) error {
	_, err := b.db.Exec(
		`UPDATE pending_uploads SET status='UPLOADED', uploaded_at=? WHERE id=?`,
		time.Now().UTC().Format(time.RFC3339), id,
	)
	return err
}

func (b *buffer) markAttempt(id int64, failed bool) error {
	status := "PENDING"
	if failed {
		status = "PENDING" // stays PENDING for retry; FAILED only after max attempts
	}
	_, err := b.db.Exec(
		`UPDATE pending_uploads
		 SET attempt_count = attempt_count + 1,
		     last_attempt_at = ?,
		     status = CASE WHEN attempt_count + 1 >= ? THEN 'FAILED' ELSE ? END
		 WHERE id = ?`,
		time.Now().UTC().Format(time.RFC3339),
		maxUploadAttemptsConst,
		status,
		id,
	)
	return err
}

// maxUploadAttemptsConst is the hard ceiling used in SQL — must match config default.
// The actual configured value governs the retry loop; this catches anything
// that slips through (e.g. concurrent restarts).
const maxUploadAttemptsConst = 10

func (b *buffer) listPending() ([]uploadRecord, error) {
	rows, err := b.db.Query(
		`SELECT id, atm_id, file_date, original_path, blob_path, file_hash, oem,
		        status, attempt_count, last_attempt_at, created_at, uploaded_at
		 FROM pending_uploads
		 WHERE status = 'PENDING'
		 ORDER BY created_at ASC`,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRecords(rows)
}

func (b *buffer) listByATMAndDate(atmID, fileDate string) ([]uploadRecord, error) {
	rows, err := b.db.Query(
		`SELECT id, atm_id, file_date, original_path, blob_path, file_hash, oem,
		        status, attempt_count, last_attempt_at, created_at, uploaded_at
		 FROM pending_uploads
		 WHERE atm_id = ? AND file_date = ?
		 ORDER BY created_at ASC`,
		atmID, fileDate,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	return scanRecords(rows)
}

func (b *buffer) listAllOriginalPaths() ([]string, error) {
	rows, err := b.db.Query(`SELECT original_path FROM pending_uploads`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var paths []string
	for rows.Next() {
		var p string
		if err := rows.Scan(&p); err != nil {
			return nil, err
		}
		paths = append(paths, p)
	}
	return paths, rows.Err()
}

func scanRecords(rows *sql.Rows) ([]uploadRecord, error) {
	var records []uploadRecord
	for rows.Next() {
		var r uploadRecord
		if err := rows.Scan(
			&r.ID, &r.ATMID, &r.FileDate, &r.OriginalPath, &r.BlobPath,
			&r.FileHash, &r.OEM, &r.Status, &r.AttemptCount,
			&r.LastAttemptAt, &r.CreatedAt, &r.UploadedAt,
		); err != nil {
			return nil, err
		}
		records = append(records, r)
	}
	return records, rows.Err()
}
