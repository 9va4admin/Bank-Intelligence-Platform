package main

// Transport is the Go abstraction over the Canon Ranger Transport API.
//
// Production implementation (ranger_windows.go, build tag: windows && cgo):
//   Calls the Ranger COM SDK:
//     TransportOpen  → TransportStartJob → loop TransportReadItem →
//     TransportGetMICR / TransportGetImage / TransportPrintItem →
//     TransportEndJob → TransportClose
//
// The real implementation requires:
//   - Canon Ranger SDK installed on the teller PC (C headers + .lib)
//   - CGO_ENABLED=1 on a Windows host with a C compiler (MSVC or MinGW)
//   - Build tag: //go:build windows && cgo
//
// This file defines the interface and the data types shared across all builds.

// ScannedItem is the normalised output from one cheque pass through the scanner.
type ScannedItem struct {
	FrontImage []byte // TIFF Group 4, 200 dpi — CTS-2010 compliant
	RearImage  []byte // TIFF Group 4, 200 dpi — CTS-2010 compliant
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
