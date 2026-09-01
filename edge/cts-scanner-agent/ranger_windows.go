//go:build windows && cgo

package main

// ranger_windows.go — Canon CR-120/CR-150 CSD API integration via CGO.
//
// Build requirements:
//   GOARCH=386 GOOS=windows CGO_ENABLED=1 CC=i686-w64-mingw32-gcc go build
//
// Runtime requirements (teller PC):
//   Canon CR-120/CR-150 driver installed; CanoCheetah.dll present in one of:
//     • Same directory as the agent binary
//     • %ProgramFiles(x86)%\Canon Electronics\CR150\CanoCheetah.dll
//     • %ProgramFiles%\Canon Electronics\CR150\CanoCheetah.dll
//
// Duplex scanning pattern (discovered from SDK C++ sample ScanCRDlg.cpp):
//   CsdReadPage is called TWICE per physical cheque:
//     call 1 → front image (CSD_OK) → capture front, read MICR
//     call 2 → rear  image (CSD_OK) → capture rear, return ScannedItem
//   The SDK returns pages interleaved: front1, rear1, front2, rear2, ...
//
// 10-minute idle timeout (CSD_TIMEOUT):
//   CsdReadPage returns CSD_TIMEOUT if no cheque is fed for 10 minutes.
//   We restart the scan transparently so the teller does not need to intervene.
//
// Double-feed (CSD_DOUBLEFEED):
//   We call CsdParSet(CSDP_DBLFEEDSTATUS, CSD_OK) to resume scanning, then
//   return ScannedItem{DoubleFeedDetected: true}.  scanner.go skips the item
//   and logs a warning.
//
// Imprinter:
//   The CSD API imprints automatically on every scanned cheque when CSDP_IMPRINTER
//   is enabled and CSDP_IMPSTRING is set before CsdStartScan.  There is no
//   per-cheque "print now" call.  PrintItem() is therefore a no-op — if the
//   imprinter is enabled at StartJob time, every cheque is stamped.

/*
#cgo LDFLAGS: -lkernel32

#include <windows.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

// --- CSD error codes ---
#define CSD_OK           0
#define CSD_NOPAPER      6
#define CSD_JAM          7
#define CSD_COVEROPEN    8
#define CSD_DOUBLEFEED  20
#define CSD_CANCEL      29
#define CSD_TIMEOUT     35
#define CSD_HARDERROR   17

// --- CSD parameter IDs (from CsdScan.h) ---
#define CSDP_FEEDER           3
#define CSDP_MODE            22
#define CSDP_XRESOLUTION      6
#define CSDP_YRESOLUTION      7
#define CSDP_MICR           131
#define CSDP_MICRDATALEN    132
#define CSDP_MICRDATA       133
#define CSDP_MICR_FONT      170
#define CSDP_DBLFEEDUSS     174
#define CSDP_IMPRINTER       60
#define CSDP_IMPSTRING       62
#define CSDP_IMPCHARFONT    225
#define CSDP_IMPDYNAMIC     325
#define CSDP_IQA_BRIGHTNESS 355
#define CSDP_IQA_BRIGHTNESS_RESULT 356
#define CSDP_MOCR           367
#define CSDP_DBLFEEDSTATUS  366

// --- CSD parameter values ---
#define CSD_FEEDER_DUPLEX              1
#define CSD_BINARY_FINETEXTFILTERING  16
#define CSD_DETECT_E13B               13
#define CSD_IMPDYNAMIC_ENABLE          2
#define CSD_IQA_BRIGHTNESS_PASSED      0
#define CSD_IQA_BRIGHTNESS_TOOLIGHT    1
#define CSD_IQA_BRIGHTNESS_TOODARK     2

// --- TIFF output constants ---
#define CSD_TIFF_FILE  1
#define CSD_COMP_MMR   3   // CCITT Group 4 — CTS-2010 mandated compression

// --- CEIIMAGEINFO: image descriptor filled by CsdReadPage ---
// Default 4-byte alignment matches SDK's pshpack4.h requirement on 32-bit.
typedef struct tagCEIIMAGEINFO {
    size_t  cbSize;
    BYTE   *lpImage;
    long    lXpos;
    long    lYpos;
    long    lWidth;
    long    lHeight;
    long    lSync;
    size_t  tImageSize;
    long    lBps;
    long    lSpp;
    DWORD   dwRGBOrder;
    long    lXResolution;
    long    lYResolution;
} CEIIMAGEINFO;

typedef struct tagCEIIMAGEFILEINFO {
    size_t  cbSize;
    long    nFileType;
    long    nCompType;
    long    nPage;
    long    nJpegQuality;
} CEIIMAGEFILEINFO;

// --- Dynamic function pointer typedefs ---
typedef INT32 (WINAPI *FN_CsdProbe)(void);
typedef INT32 (WINAPI *FN_CsdProbeEx)(LPCSTR);
typedef INT32 (WINAPI *FN_CsdTerminate)(void);
typedef INT32 (WINAPI *FN_CsdParSet)(UINT, LPARAM);
typedef INT32 (WINAPI *FN_CsdParGet)(UINT, LPVOID);
typedef INT32 (WINAPI *FN_CsdStartScan)(LPCSTR, LPVOID, LPVOID);
typedef INT32 (WINAPI *FN_CsdReadPage)(CEIIMAGEINFO *);
typedef INT32 (WINAPI *FN_CsdStopScan)(void);
typedef INT32 (WINAPI *FN_CsdAbortScan)(void);
typedef INT32 (WINAPI *FN_CsdReleaseImage)(CEIIMAGEINFO *);
typedef INT32 (WINAPI *FN_CsdSaveImageEx)(CEIIMAGEINFO *, CEIIMAGEFILEINFO *, LPCSTR);

// --- Static DLL handle and resolved function pointers ---
static HMODULE          g_hDll            = NULL;
static FN_CsdProbe      g_CsdProbe        = NULL;
static FN_CsdProbeEx    g_CsdProbeEx      = NULL;
static FN_CsdTerminate  g_CsdTerminate    = NULL;
static FN_CsdParSet     g_CsdParSet       = NULL;
static FN_CsdParGet     g_CsdParGet       = NULL;
static FN_CsdStartScan  g_CsdStartScan    = NULL;
static FN_CsdReadPage   g_CsdReadPage     = NULL;
static FN_CsdStopScan   g_CsdStopScan     = NULL;
static FN_CsdAbortScan  g_CsdAbortScan    = NULL;
static FN_CsdReleaseImage  g_CsdReleaseImage  = NULL;
static FN_CsdSaveImageEx   g_CsdSaveImageEx   = NULL;

// astra_load_dll: loads CanoCheetah.dll and resolves all required exports.
// Returns 0 on success, -1 if DLL not found, -2 if a required export is missing.
static INT32 astra_load_dll(const char *explicitPath) {
    if (explicitPath && explicitPath[0] != '\0') {
        g_hDll = LoadLibraryA(explicitPath);
    }

    // Try canonical Canon installation paths.
    if (!g_hDll) {
        char pfdir[MAX_PATH];
        char path[MAX_PATH];
        if (GetEnvironmentVariableA("ProgramFiles(x86)", pfdir, MAX_PATH) > 0) {
            snprintf(path, sizeof(path),
                     "%s\\Canon Electronics\\CR150\\CanoCheetah.dll", pfdir);
            g_hDll = LoadLibraryA(path);
        }
    }
    if (!g_hDll) {
        char pfdir[MAX_PATH];
        char path[MAX_PATH];
        if (GetEnvironmentVariableA("ProgramFiles", pfdir, MAX_PATH) > 0) {
            snprintf(path, sizeof(path),
                     "%s\\Canon Electronics\\CR150\\CanoCheetah.dll", pfdir);
            g_hDll = LoadLibraryA(path);
        }
    }
    // Fall back to DLL search path (same dir as exe, System32, PATH).
    if (!g_hDll) {
        g_hDll = LoadLibraryA("CanoCheetah.dll");
    }
    if (!g_hDll) {
        return -1;
    }

    g_CsdProbe       = (FN_CsdProbe)      GetProcAddress(g_hDll, "CsdProbe");
    g_CsdProbeEx     = (FN_CsdProbeEx)    GetProcAddress(g_hDll, "CsdProbeEx");
    g_CsdTerminate   = (FN_CsdTerminate)  GetProcAddress(g_hDll, "CsdTerminate");
    g_CsdParSet      = (FN_CsdParSet)     GetProcAddress(g_hDll, "CsdParSet");
    g_CsdParGet      = (FN_CsdParGet)     GetProcAddress(g_hDll, "CsdParGet");
    g_CsdStartScan   = (FN_CsdStartScan)  GetProcAddress(g_hDll, "CsdStartScan");
    g_CsdReadPage    = (FN_CsdReadPage)   GetProcAddress(g_hDll, "CsdReadPage");
    g_CsdStopScan    = (FN_CsdStopScan)   GetProcAddress(g_hDll, "CsdStopScan");
    g_CsdAbortScan   = (FN_CsdAbortScan)  GetProcAddress(g_hDll, "CsdAbortScan");
    g_CsdReleaseImage  = (FN_CsdReleaseImage) GetProcAddress(g_hDll, "CsdReleaseImage");
    g_CsdSaveImageEx   = (FN_CsdSaveImageEx)  GetProcAddress(g_hDll, "CsdSaveImageEx");

    if (!g_CsdProbe || !g_CsdTerminate || !g_CsdParSet || !g_CsdParGet ||
        !g_CsdStartScan || !g_CsdReadPage || !g_CsdStopScan ||
        !g_CsdReleaseImage || !g_CsdSaveImageEx) {
        FreeLibrary(g_hDll);
        g_hDll = NULL;
        return -2;
    }
    return 0;
}

static void astra_unload_dll(void) {
    if (g_hDll) {
        FreeLibrary(g_hDll);
        g_hDll = NULL;
    }
}

// Thin C wrappers called from Go — avoids passing function pointers across CGO boundary.
static INT32 astra_probe(const char *driver) {
    if (driver && driver[0] && g_CsdProbeEx) return g_CsdProbeEx(driver);
    return g_CsdProbe();
}
static INT32 astra_par_set_long(UINT p, LONG v)  { return g_CsdParSet(p, (LPARAM)v); }
static INT32 astra_par_set_str(UINT p, const char *s) { return g_CsdParSet(p, (LPARAM)s); }
static INT32 astra_par_get_long(UINT p, LONG *v) { return g_CsdParGet(p, (LPVOID)v); }
static INT32 astra_par_get_buf(UINT p, char *b)  { return g_CsdParGet(p, (LPVOID)b); }
static INT32 astra_start_scan(void)              { return g_CsdStartScan(NULL, NULL, NULL); }
static INT32 astra_read_page(CEIIMAGEINFO *img)  { return g_CsdReadPage(img); }
static INT32 astra_stop_scan(void)               { return g_CsdStopScan(); }
static INT32 astra_terminate(void)               { return g_CsdTerminate(); }
static INT32 astra_release_image(CEIIMAGEINFO *img) { return g_CsdReleaseImage(img); }

// astra_save_tiff: saves the raw pixel buffer in img to a TIFF Group 4 file at path.
// This is the CTS-2010 mandated compression (CCITT MMR / Group 4).
static INT32 astra_save_tiff(CEIIMAGEINFO *img, const char *path) {
    CEIIMAGEFILEINFO fi;
    fi.cbSize       = sizeof(fi);
    fi.nFileType    = CSD_TIFF_FILE;
    fi.nCompType    = CSD_COMP_MMR;
    fi.nPage        = -1;
    fi.nJpegQuality = 0;
    return g_CsdSaveImageEx(img, &fi, path);
}
*/
import "C"

import (
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"
	"unsafe"
)

// CSD return code constants mirrored in Go for switch statements.
const (
	csdOK         = int32(C.CSD_OK)
	csdNoPaper    = int32(C.CSD_NOPAPER)
	csdJam        = int32(C.CSD_JAM)
	csdCoverOpen  = int32(C.CSD_COVEROPEN)
	csdDoubleFeed = int32(C.CSD_DOUBLEFEED)
	csdCancel     = int32(C.CSD_CANCEL)
	csdTimeout    = int32(C.CSD_TIMEOUT)
	csdHardError  = int32(C.CSD_HARDERROR)
)

// CanonTransport implements the Transport interface via the Canon CSD API.
// It is only compiled for GOARCH=386 Windows builds (CGO enabled).
// The CanoCheetah.dll is 32-bit; this binary must be built as GOARCH=386.
type CanonTransport struct {
	cfg    *Config
	logger *slog.Logger

	mu      sync.Mutex
	started bool

	doneOnce sync.Once
	done     chan struct{} // closed by EndJob; unblocks ReadItem
}

// newTransport is the factory used by main.go.
func newTransport(cfg *Config) Transport {
	return &CanonTransport{
		cfg:    cfg,
		logger: slog.Default(),
		done:   make(chan struct{}),
	}
}

// Open loads CanoCheetah.dll and initialises the Canon CSD driver via CsdProbe.
func (t *CanonTransport) Open() error {
	dllPath := t.cfg.CSDDLLPath
	var cPath *C.char
	if dllPath != "" {
		cPath = C.CString(dllPath)
		defer C.free(unsafe.Pointer(cPath))
	}

	var explicitArg *C.char
	if cPath != nil {
		explicitArg = cPath
	}

	if ret := C.astra_load_dll(explicitArg); ret != 0 {
		switch ret {
		case -1:
			return fmt.Errorf("CanoCheetah.dll not found — install Canon CR-120/150 driver first")
		case -2:
			return fmt.Errorf("CanoCheetah.dll loaded but required exports are missing — wrong driver version")
		default:
			return fmt.Errorf("astra_load_dll returned %d", ret)
		}
	}

	// CsdProbe (or CsdProbeEx with driver name for USB named-device discovery).
	driverName := "" // empty = auto-detect via CsdProbe
	if t.cfg.ScannerDiscoveryMode == "devname" && t.cfg.ScannerDeviceName != "" {
		driverName = t.cfg.ScannerDeviceName
	}
	cDriver := C.CString(driverName)
	defer C.free(unsafe.Pointer(cDriver))

	if ret := C.astra_probe(cDriver); int32(ret) != csdOK {
		C.astra_unload_dll()
		return fmt.Errorf("CsdProbe failed: code %d — scanner not detected", ret)
	}

	t.logger.Info("canon CSD driver initialised",
		"discovery_mode", t.cfg.ScannerDiscoveryMode,
		"dll_path", dllPath,
	)
	return nil
}

// StartJob configures all scan parameters and calls CsdStartScan.
func (t *CanonTransport) StartJob(endorsementText string, enableImprinter bool) error {
	t.mu.Lock()
	defer t.mu.Unlock()

	// Duplex: capture both front and rear sides per cheque.
	if ret := C.astra_par_set_long(C.CSDP_FEEDER, C.CSD_FEEDER_DUPLEX); int32(ret) != csdOK {
		return fmt.Errorf("set duplex mode failed: %d", ret)
	}

	// Binary fine-text-filtering — sharpest B&W mode for printed cheques.
	if ret := C.astra_par_set_long(C.CSDP_MODE, C.CSD_BINARY_FINETEXTFILTERING); int32(ret) != csdOK {
		return fmt.Errorf("set scan mode failed: %d", ret)
	}

	// 200 DPI — CTS-2010 mandated resolution.
	C.astra_par_set_long(C.CSDP_XRESOLUTION, 200)
	C.astra_par_set_long(C.CSDP_YRESOLUTION, 200)

	// MICR: enable hardware reader, E13B font (Indian CTS-2010 standard).
	if ret := C.astra_par_set_long(C.CSDP_MICR, 1); int32(ret) != csdOK {
		return fmt.Errorf("enable MICR failed: %d", ret)
	}
	C.astra_par_set_long(C.CSDP_MICR_FONT, C.CSD_DETECT_E13B)

	// Ultrasonic double-feed detection — CR-120/150 uses USS, not infrared.
	// Must be explicitly enabled; default is FALSE on these models.
	C.astra_par_set_long(C.CSDP_DBLFEEDUSS, 1)

	// MOCR weight: 0=pure magnetic, 50=hybrid, 100=pure optical.
	// Indian banking default 50: recovers faded MICR ink without eliminating
	// the magnetic signal check that catches zero-ink forgeries.
	mocrWeight := C.LONG(t.cfg.MICROCRWeight)
	C.astra_par_set_long(C.CSDP_MOCR, mocrWeight)

	// IQA brightness check — requires CeiIQA.ini in the driver directory.
	if t.cfg.EnableIQA {
		C.astra_par_set_long(C.CSDP_IQA_BRIGHTNESS, 1)
	}

	// Imprinter / endorsement stamp.
	impEnabled := C.LONG(0)
	if enableImprinter {
		impEnabled = 1
	}
	if ret := C.astra_par_set_long(C.CSDP_IMPRINTER, impEnabled); int32(ret) != csdOK {
		t.logger.Warn("set imprinter enable failed — continuing without endorsement",
			"code", int32(ret))
	}
	if enableImprinter && endorsementText != "" {
		cText := C.CString(endorsementText)
		defer C.free(unsafe.Pointer(cText))
		C.astra_par_set_str(C.CSDP_IMPSTRING, cText)
		C.astra_par_set_long(C.CSDP_IMPCHARFONT, 1)
		C.astra_par_set_long(C.CSDP_IMPDYNAMIC, C.CSD_IMPDYNAMIC_ENABLE)
	}

	if ret := C.astra_start_scan(); int32(ret) != csdOK {
		return fmt.Errorf("CsdStartScan failed: %d", ret)
	}

	t.started = true
	t.logger.Info("scan job started",
		"imprinter", enableImprinter,
		"mocr_weight", int(mocrWeight),
		"iqa", t.cfg.EnableIQA,
	)
	return nil
}

// ReadItem blocks until a complete duplex cheque (front+rear) has passed through
// the scanner, then returns the captured images and hardware MICR.
//
// Returns (nil, nil) when EndJob has been called — the caller interprets this
// as a clean session end and exits the scan loop.
func (t *CanonTransport) ReadItem() (*ScannedItem, error) {
	var (
		frontImg  C.CEIIMAGEINFO
		hasFront  bool
		micrRaw   string
		frontDPI  int
		frontTIFF []byte
		iqaPassed = true
	)

	for {
		var img C.CEIIMAGEINFO
		img.cbSize = C.size_t(unsafe.Sizeof(img))

		ret := int32(C.astra_read_page(&img))

		switch ret {
		case csdOK:
			if !hasFront {
				// First pass: front side of the cheque.
				frontImg = img
				hasFront = true
				frontDPI = int(img.lXResolution)

				// MICR is read by hardware on the first transport pass.
				micrRaw = t.readMICR()

				// IQA brightness result for the front image.
				if t.cfg.EnableIQA {
					var iqaResult C.LONG
					if r := C.astra_par_get_long(C.CSDP_IQA_BRIGHTNESS_RESULT, &iqaResult); int32(r) == csdOK {
						if int32(iqaResult) != C.CSD_IQA_BRIGHTNESS_PASSED {
							iqaPassed = false
							t.logger.Warn("IQA brightness fail on front image",
								"result", int32(iqaResult))
						}
					}
				}
			} else {
				// Second pass: rear side.  Assemble the complete ScannedItem.
				rearDPI := int(img.lXResolution)

				// Save both sides as TIFF Group 4 (CTS-2010 mandated compression).
				var err error
				frontTIFF, err = t.saveImageToBytes(&frontImg)
				C.astra_release_image(&frontImg)
				if err != nil {
					C.astra_release_image(&img)
					hasFront = false
					return nil, fmt.Errorf("save front image: %w", err)
				}

				rearTIFF, err := t.saveImageToBytes(&img)
				C.astra_release_image(&img)
				hasFront = false

				if err != nil {
					return nil, fmt.Errorf("save rear image: %w", err)
				}

				item := &ScannedItem{
					FrontImage:       frontTIFF,
					RearImage:        rearTIFF,
					FrontDPI:         frontDPI,
					RearDPI:          rearDPI,
					FrontFileSizeKB:  float64(len(frontTIFF)) / 1024.0,
					RearFileSizeKB:   float64(len(rearTIFF)) / 1024.0,
					FrontColourDepth: 1,
					RearColourDepth:  1,
					MICRRaw:          micrRaw,
					ImprinterStamped: t.cfg.EnableImprinter,
				}
				_ = iqaPassed // surfaced via logger; field can be added to ScannedItem if needed
				return item, nil
			}

		case csdDoubleFeed:
			// Ultrasonic sensor triggered.  Release any partial image and tell the
			// SDK to resume scanning (without this call, the scanner stalls).
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			C.astra_par_set_long(C.CSDP_DBLFEEDSTATUS, C.LONG(csdOK))
			t.logger.Warn("double-feed detected by ultrasonic sensor")
			return &ScannedItem{DoubleFeedDetected: true}, nil

		case csdNoPaper:
			// Feeder exhausted.  In a live clearing session the operator will feed
			// the next cheque; restart the scan and keep waiting rather than ending
			// the session.  If EndJob was called, exit cleanly.
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			select {
			case <-t.done:
				return nil, nil // clean session end
			default:
			}
			// Small back-off before restarting — avoids spinning the CPU.
			time.Sleep(300 * time.Millisecond)
			select {
			case <-t.done:
				return nil, nil
			default:
			}
			if r := int32(C.astra_start_scan()); r != csdOK {
				return nil, fmt.Errorf("restart scan after feeder empty: code %d", r)
			}

		case csdTimeout:
			// Scanner entered standby after 10-minute idle.  Restart transparently.
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			t.logger.Info("scanner 10-minute idle timeout — restarting scan")
			select {
			case <-t.done:
				return nil, nil
			default:
			}
			C.astra_stop_scan()
			if r := int32(C.astra_start_scan()); r != csdOK {
				return nil, fmt.Errorf("restart scan after timeout: code %d", r)
			}

		case csdCancel:
			// CsdStopScan was called from EndJob — clean session end.
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			return nil, nil

		case csdJam:
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			return nil, fmt.Errorf("paper jam detected — operator must clear the transport")

		case csdCoverOpen:
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			return nil, fmt.Errorf("scanner cover is open")

		default:
			if hasFront {
				C.astra_release_image(&frontImg)
				hasFront = false
			}
			return nil, fmt.Errorf("CsdReadPage unexpected code %d", ret)
		}
	}
}

// PrintItem is a no-op for the Canon CSD API.
// The imprinter fires automatically on every cheque when CSDP_IMPRINTER is
// enabled at StartJob time.  There is no per-cheque print command in CsdScan.
// scanner.go sets item.ImprinterStamped based on whether this returns nil.
func (t *CanonTransport) PrintItem(_ string) error {
	return nil // imprinter already fired during the hardware transport pass
}

// EndJob stops the active scan.  CsdStopScan unblocks any in-progress CsdReadPage
// call in the scan loop goroutine, which will then return csdCancel or csdNoPaper.
func (t *CanonTransport) EndJob() error {
	t.doneOnce.Do(func() {
		close(t.done)
		C.astra_stop_scan()
	})
	return nil
}

// Close releases the scanner connection and unloads CanoCheetah.dll.
// Must be called even if Open failed — safe to call multiple times.
func (t *CanonTransport) Close() error {
	C.astra_terminate()
	C.astra_unload_dll()
	t.logger.Info("canon CSD driver released")
	return nil
}

// --- helpers ---

// readMICR retrieves the E13B MICR string from the scanner hardware buffer.
// Called immediately after the first CsdReadPage (front image pass) — the
// hardware MICR reader has already decoded the line during the transport pass.
func (t *CanonTransport) readMICR() string {
	var micrLen C.LONG
	if ret := C.astra_par_get_long(C.CSDP_MICRDATALEN, &micrLen); int32(ret) != csdOK || micrLen == 0 {
		return ""
	}
	// Allocate +1 for NUL terminator.
	buf := make([]C.char, int(micrLen)+1)
	if ret := C.astra_par_get_buf(C.CSDP_MICRDATA, &buf[0]); int32(ret) != csdOK {
		return ""
	}
	return C.GoStringN(&buf[0], C.int(micrLen))
}

// saveImageToBytes compresses the raw pixel buffer in img to TIFF Group 4
// via CsdSaveImageEx, reads the resulting file into memory, and deletes the temp file.
//
// We use a temp file rather than an in-memory buffer because the CSD API only
// exposes file-based image export (CsdSaveImageEx writes to a path).
func (t *CanonTransport) saveImageToBytes(img *C.CEIIMAGEINFO) ([]byte, error) {
	// Create a temp file to receive the TIFF output.
	tmp, err := os.CreateTemp("", "astra-scan-*.tiff")
	if err != nil {
		return nil, fmt.Errorf("create temp file: %w", err)
	}
	tmpPath := tmp.Name()
	tmp.Close() // CsdSaveImageEx opens and writes the file itself
	defer os.Remove(tmpPath)

	cPath := C.CString(tmpPath)
	defer C.free(unsafe.Pointer(cPath))

	if ret := C.astra_save_tiff(img, cPath); int32(ret) != csdOK {
		return nil, fmt.Errorf("CsdSaveImageEx error %d", ret)
	}

	data, err := os.ReadFile(tmpPath)
	if err != nil {
		return nil, fmt.Errorf("read temp TIFF: %w", err)
	}
	if len(data) == 0 {
		return nil, fmt.Errorf("CsdSaveImageEx produced empty TIFF file")
	}
	return data, nil
}
