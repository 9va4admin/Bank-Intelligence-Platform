package main

// Transport is the Go abstraction over the Canon CSD (Cheque Scanner Driver) API.
//
// Production implementation (ranger_windows.go, build tag: windows && cgo):
//   Calls the Canon CSD API via CanoCheetah.dll loaded dynamically at runtime:
//     Open (CsdProbe) → StartJob (CsdParSet × N + CsdStartScan) →
//     loop ReadItem (CsdReadPage × 2 per cheque — front then rear) →
//     MICR via CsdParGet(CSDP_MICRDATA) → TIFF via CsdSaveImageEx →
//     EndJob (CsdStopScan) → Close (CsdTerminate)
//
// The real implementation requires:
//   - Canon CR-120/CR-150 driver installed (provides CanoCheetah.dll, a 32-bit DLL)
//   - Binary built as GOARCH=386: GOARCH=386 GOOS=windows CGO_ENABLED=1
//     CC=i686-w64-mingw32-gcc go build
//   - Build tag: //go:build windows && cgo
//
// This file defines the interface and the data types shared across all builds.

import "errors"

// Sentinel errors returned by Transport.ReadItem for hardware events that need
// to be reported to central and may need operator intervention before resuming.
// scanner.go uses errors.Is to distinguish these from generic transport failures.
var (
	ErrPaperJam  = errors.New("paper jam — operator must clear the transport")
	ErrCoverOpen = errors.New("scanner cover is open — close before scanning")
)

// ScannedItem is the normalised output from one cheque pass through the scanner.
type ScannedItem struct {
	FrontImage   []byte // grayscale 8-bit LZW TIFF — saved as {MICR}_F_GR.tif
	FrontImageBW []byte // binary 1-bit CCITT G4 TIFF derived by thresholding FrontImage — saved as {MICR}_F_BW.tif
	RearImage    []byte // binary 1-bit CCITT G4 TIFF — saved as {MICR}_B_BW.tif
	FrontDPI   int
	RearDPI    int
	// FrontFileSizeKB and RearFileSizeKB are derived from image byte length.
	FrontFileSizeKB float64
	RearFileSizeKB  float64
	// ColourDepth is 1 for 1-bit B&W (standard CTS-2010 mode).
	FrontColourDepth int
	RearColourDepth  int

	// MICRRaw is the raw E13B MICR line string from the hardware MICR reader.
	// Format: "<cheque-number> <MICR-code-line> <account-number>"
	// Never log in full — contains account number.
	MICRRaw string

	// UVImage is populated when the scanner is a CR-120 UV and UV scanning
	// is enabled in config. nil otherwise.
	UVImage []byte

	// ImprinterStamped is true when the Ranger API confirmed the endorsement
	// text was successfully printed on the rear of the cheque.
	ImprinterStamped bool

	// DoubleFeedDetected is true when the ultrasonic sensor detected a
	// multi-sheet feed. The caller must reject this item.
	DoubleFeedDetected bool

	// IQAFailed is true when the hardware IQA brightness check failed on the
	// front image. The scanner has already physically ejected the cheque back to
	// the operator tray via CsdAbortScan. The caller must re-feed the cheque.
	IQAFailed bool
}

// Transport is the interface every Ranger API implementation must satisfy.
type Transport interface {
	// Open initialises communication with the physical scanner.
	// Must be called once before StartJob.
	Open() error

	// StartJob puts the scanner into scanning mode.
	// After StartJob, ReadItem blocks until a cheque is inserted.
	StartJob(endorsementText string, enableImprinter bool) error

	// ReadItem blocks until a cheque passes through the transport and returns
	// the captured images + hardware MICR. Returns nil, nil when the job is
	// ended normally (EndJob was called while waiting).
	ReadItem() (*ScannedItem, error)

	// PrintItem stamps the endorsement text on the cheque that is still in the
	// scanner transport path immediately after ReadItem returned it. Must be
	// called before the next ReadItem. On the Canon CR-120 this maps to
	// TransportPrintItem() in the Ranger COM SDK.
	// Returns an error if the imprinter mechanism reports a hardware fault.
	PrintItem(text string) error

	// EndJob stops the scan session. Outstanding ReadItem calls return nil, nil.
	EndJob() error

	// Close releases all scanner resources. Must be called even if Open failed.
	Close() error
}
