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
//   Without UV: 2 CsdReadPage calls per cheque (standard CR-120/CR-150):
//     call 1 → front image (CSD_OK) → capture front, read MICR
//     call 2 → rear  image (CSD_OK) → capture rear, return ScannedItem
//   With UV (CR-120 UV / CR-150 UV, EnableUVScan=true): 3 calls:
//     call 1 → front image → capture front, read MICR
//     call 2 → rear  image → save front+rear TIFFs
//     call 3 → UV    image → save UV TIFF, return ScannedItem with UVImage set
//   The SDK returns pages interleaved: front1, rear1, [uv1,] front2, rear2, [uv2,] ...
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
#define CSD_NOTREADY    16
#define CSD_HARDERROR   17
#define CSD_DOUBLEFEED  20
#define CSD_CANCEL      29
#define CSD_TIMEOUT     35

// --- CSD parameter IDs (from CsdScan.h) ---
#define CSDP_WIDTH            1
#define CSDP_LENGTH           2
#define CSDP_FEEDER           3
#define CSDP_XRESOLUTION      6
#define CSDP_YRESOLUTION      7
#define CSDP_MODE            22
#define CSDP_IMPRINTER       60
#define CSDP_IMPSTRING       62
#define CSDP_MICR           131
#define CSDP_MICRDATALEN    132
#define CSDP_MICRDATA       133
#define CSDP_MICR_FONT      170
#define CSDP_DBLFEEDUSS     174
#define CSDP_IMPCHARFONT    225
#define CSDP_IMPDYNAMIC     325
#define CSDP_IQA_BRIGHTNESS 355
#define CSDP_IQA_BRIGHTNESS_RESULT 356
#define CSDP_DBLFEEDSTATUS  366
#define CSDP_MOCR           367
#define CSDP_MAXWIDTH       105
#define CSDP_MAXLENGTH      106

// --- CSD parameter values ---
#define CSD_FEEDER_DUPLEX              1
#define CSD_BINARY_FINETEXTFILTERING  16
#define CSD_DETECT_E13B               13
#define CSD_IMPDYNAMIC_ENABLE          2
#define CSD_IQA_BRIGHTNESS_PASSED      0
#define CSD_IQA_BRIGHTNESS_TOOLIGHT    1
#define CSD_IQA_BRIGHTNESS_TOODARK     2

// CSDP_UV offset is NOT defined here — it is read from config.ini at runtime
// via Config.UVParamID (default 380).  Canon must confirm the exact value from
// CsdScan.h in the CR-150 UV driver installation; change uv_param_id in config.ini,
// no rebuild required.

// --- TIFF output constants ---
#define CSD_TIFF_FILE  1
#define CSD_COMP_LZW   2   // LZW — used for grayscale and colour TIFFs (CTS-2010 front face)
#define CSD_COMP_MMR   3   // CCITT Group 4 — binary only (CTS-2010 rear face)

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
static INT32 astra_abort_scan(void)              { return g_CsdAbortScan(); }
static INT32 astra_terminate(void)               { return g_CsdTerminate(); }
static INT32 astra_release_image(CEIIMAGEINFO *img) { return g_CsdReleaseImage(img); }

// astra_save_tiff: saves the raw pixel buffer in img to a TIFF file at path.
// Compression is chosen automatically from the image bit depth:
//   1 bpp (binary)    → CCITT Group 4 / MMR  (CTS-2010 rear face)
//   8 bpp (grayscale) → LZW                  (CTS-2010 front face, default scan mode)
//   other             → LZW                  (safe fallback for colour)
static INT32 astra_save_tiff(CEIIMAGEINFO *img, const char *path) {
    CEIIMAGEFILEINFO fi;
    fi.cbSize       = sizeof(fi);
    fi.nFileType    = CSD_TIFF_FILE;
    fi.nCompType    = (img->lBps == 1) ? CSD_COMP_MMR : CSD_COMP_LZW;
    fi.nPage        = -1;
    fi.nJpegQuality = 0;
    return g_CsdSaveImageEx(img, &fi, path);
}

// astra_save_tiff_bw: threshold a grayscale (8 bpp) image in-memory to 1 bpp
// and save as a CCITT Group 4 / MMR TIFF — the CTS-2010 binary format.
//
// Thresholding rule: pixel >= 128 → white (bit=1, MSB-first per TIFF spec),
//                   pixel <  128 → black (bit=0).
//
// If the source image is already 1 bpp, the function delegates to astra_save_tiff.
// Row stride of the source is derived from tImageSize/lHeight to handle any
// padding the scanner driver may have added.
static INT32 astra_save_tiff_bw(CEIIMAGEINFO *orig, const char *path) {
    if (orig->lBps != 8) {
        return astra_save_tiff(orig, path); // already binary or unsupported depth
    }

    long width     = orig->lWidth;
    long height    = orig->lHeight;
    long srcStride = (orig->tImageSize > 0 && height > 0)
                     ? (long)(orig->tImageSize / height)
                     : width; // bytes per source row (may include padding)
    long dstStride = (width + 7) / 8; // bytes per 1-bpp destination row (no padding)
    long dstSize   = dstStride * height;

    BYTE *bwBuf = (BYTE *)calloc((size_t)dstSize, 1);
    if (!bwBuf) return -98;

    BYTE *src = orig->lpImage;
    for (long y = 0; y < height; y++) {
        for (long x = 0; x < width; x++) {
            if (src[y * srcStride + x] >= 128) {
                bwBuf[y * dstStride + x / 8] |= (BYTE)(0x80u >> (x % 8));
            }
        }
    }

    CEIIMAGEINFO bwImg  = *orig;
    bwImg.lBps          = 1;
    bwImg.lpImage       = bwBuf;
    bwImg.tImageSize    = (size_t)dstSize;

    CEIIMAGEFILEINFO fi;
    fi.cbSize       = sizeof(fi);
    fi.nFileType    = CSD_TIFF_FILE;
    fi.nCompType    = CSD_COMP_MMR;
    fi.nPage        = -1;
    fi.nJpegQuality = 0;

    INT32 ret = g_CsdSaveImageEx(&bwImg, &fi, path);
    free(bwBuf);
    return ret;
}
*/
import "C"

import (
	"fmt"
	"log/slog"
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
	csdNotReady   = int32(C.CSD_NOTREADY)
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
// It also resets the session-end channel so this session's ReadItem loop does
// not immediately exit.  EndJob from a prior session closes the previous done
// channel via doneOnce; without this reset, every subsequent AutoFeeder cycle
// would see a closed channel and return nil on the first csdNoPaper, preventing
// the scanner from accepting any cheque after the first session ends.
func (t *CanonTransport) Open() error {
	t.mu.Lock()
	t.done = make(chan struct{})
	t.doneOnce = sync.Once{}
	t.mu.Unlock()

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
	// CSD_NOTREADY (16) means the scanner firmware/rollers are still initialising
	// after power-on or USB reconnect — retry up to 5 times (3 s apart) before failing.
	driverName := "" // empty = auto-detect via CsdProbe
	if t.cfg.ScannerDiscoveryMode == "devname" && t.cfg.ScannerDeviceName != "" {
		driverName = t.cfg.ScannerDeviceName
	}
	cDriver := C.CString(driverName)
	defer C.free(unsafe.Pointer(cDriver))

	const probeMaxAttempts = 5
	var probeRet C.INT32
	for attempt := 1; attempt <= probeMaxAttempts; attempt++ {
		probeRet = C.astra_probe(cDriver)
		if int32(probeRet) == csdOK {
			break
		}
		if int32(probeRet) == csdNotReady && attempt < probeMaxAttempts {
			t.logger.Warn("CsdProbe: scanner not ready — retrying",
				"attempt", attempt, "max", probeMaxAttempts)
			time.Sleep(3 * time.Second)
			continue
		}
		C.astra_unload_dll()
		return fmt.Errorf("CsdProbe failed: code %d — scanner not detected", int32(probeRet))
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

	// Scan mode — default 2 (8-bit grayscale; CTS-2010 requires grayscale for the front face).
	// Use 16 (CSD_BINARY_FINETEXTFILTERING) only when both faces must be binary.
	// TIFF compression is auto-selected: LZW for grayscale, CCITT G4 for binary.
	if ret := C.astra_par_set_long(C.CSDP_MODE, C.LONG(t.cfg.ScanModeValue)); int32(ret) != csdOK {
		return fmt.Errorf("set scan mode failed: %d", ret)
	}

	// DPI — NPCI guideline default is 300; CTS-2010 minimum is 200 (override via scan_dpi in config.ini).
	C.astra_par_set_long(C.CSDP_XRESOLUTION, C.LONG(t.cfg.ScanDPI))
	C.astra_par_set_long(C.CSDP_YRESOLUTION, C.LONG(t.cfg.ScanDPI))

	// Scan area — set both dimensions to the scanner's reported maximums.
	// CSDP_MAXWIDTH/MAXLENGTH are in scanner-native units (model-dependent).
	// Using max ensures no cheque is cropped regardless of physical size.
	// The black border below the cheque is a cosmetic artefact of capturing
	// the full transport path; it does not affect MICR or image content.
	// TODO: once CSDP_LENGTH unit (dots vs 1/100mm) is confirmed from Canon SDK
	// docs, set a cheque-height value (90mm) to eliminate the black border.
	var maxW, maxL C.LONG
	if C.astra_par_get_long(C.CSDP_MAXWIDTH, &maxW) == C.INT32(csdOK) && maxW > 0 {
		C.astra_par_set_long(C.CSDP_WIDTH, maxW)
		t.logger.Info("scan area width set to scanner max", "dots", int32(maxW))
	} else {
		t.logger.Warn("could not read CSDP_MAXWIDTH — using driver default (image may be cropped)")
	}
	if C.astra_par_get_long(C.CSDP_MAXLENGTH, &maxL) == C.INT32(csdOK) && maxL > 0 {
		C.astra_par_set_long(C.CSDP_LENGTH, maxL)
		t.logger.Info("scan area length set to scanner max", "dots", int32(maxL))
	} else {
		t.logger.Warn("could not read CSDP_MAXLENGTH — using driver default (image may be cropped)")
	}

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
	// Param IDs default to 355/356; override iqa_brightness_param_id / iqa_result_param_id
	// in config.ini if Canon confirms different offsets for your model.
	if t.cfg.EnableIQA {
		C.astra_par_set_long(C.UINT(t.cfg.IQABrightnessParamID), C.LONG(1))
	}

	// UV lamp — CR-120 UV / CR-150 UV models only.
	// Parameter ID comes from Config.UVParamID (config.ini: uv_param_id, default 380).
	// When enabled, CsdReadPage yields a third page per cheque (UV image of the front)
	// after the regular front+rear duplex pair.
	if t.cfg.EnableUVScan {
		uvParam := C.UINT(t.cfg.UVParamID)
		if ret := C.astra_par_set_long(uvParam, C.LONG(1)); int32(ret) != csdOK {
			t.logger.Warn("UV lamp enable failed — continuing without UV (non-UV model, wrong uv_param_id, or unsupported driver?)",
				"code", int32(ret), "uv_param_id", t.cfg.UVParamID)
			// Don't fail the job; UV is advisory, not mandatory for CTS clearance.
		}
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
		"dpi", t.cfg.ScanDPI,
		"scan_mode", t.cfg.ScanModeValue,
		"imprinter", enableImprinter,
		"mocr_weight", int(mocrWeight),
		"iqa", t.cfg.EnableIQA,
		"iqa_brightness_param_id", t.cfg.IQABrightnessParamID,
		"iqa_result_param_id", t.cfg.IQAResultParamID,
		"uv", t.cfg.EnableUVScan,
		"uv_param_id", t.cfg.UVParamID,
		"feeder_poll_ms", t.cfg.FeederPollMS,
	)
	return nil
}

// ReadItem blocks until a complete cheque has passed through the scanner and
// returns the captured images and hardware MICR.
//
// Without UV: 2 CsdReadPage calls per cheque — front then rear.
// With UV (CR-120 UV / CR-150 UV, EnableUVScan=true): 3 calls — front, rear, UV.
// The SDK sequences the UV page immediately after the rear page.
//
// Returns (nil, nil) when EndJob has been called — the caller interprets this
// as a clean session end and exits the scan loop.
func (t *CanonTransport) ReadItem() (*ScannedItem, error) {
	var (
		frontImg    C.CEIIMAGEINFO
		hasFront    bool   // front image held in frontImg (not yet released)
		hasRear     bool   // front+rear saved to TIFF; waiting for UV page
		micrRaw     string
		frontDPI    int
		rearDPI     int
		frontTIFF   []byte // grayscale — {MICR}_F_GR.tif
		frontBWTIFF []byte // binary thresholded — {MICR}_F_BW.tif
		rearTIFF    []byte // binary — {MICR}_B_BW.tif
	)

	// releaseFront releases the front CEIIMAGEINFO buffer and resets hasFront.
	releaseFront := func() {
		if hasFront {
			C.astra_release_image(&frontImg)
			hasFront = false
		}
	}

	for {
		var img C.CEIIMAGEINFO
		img.cbSize = C.size_t(unsafe.Sizeof(img))

		ret := int32(C.astra_read_page(&img))

		switch ret {
		case csdOK:
			switch {
			case !hasFront && !hasRear:
				// Pass 1 — front side of the cheque.
				// Read MICR HERE immediately after CsdReadPage returns — this is the
				// only guaranteed-valid window in the Canon CSD API. The MICR head
				// sits before the front camera in the transport path; by the time
				// CsdReadPage(front) returns the hardware has fully decoded E13B.
				// Reading at the rear pass causes alternating empty MICR because the
				// cheque has already exited the transport and the register is cleared.
				// MOCR weight=0 ensures pure magnetic (synchronous) decode with no
				// async optical component that caused @ corruption in batch.
				frontImg = img
				hasFront = true
				frontDPI = int(img.lXResolution)
				micrRaw = t.readMICR()

				// IQA brightness check on the front image.
				// On failure: eject the cheque back to the operator tray via
				// CsdAbortScan, restart scanning, return synthetic IQA item.
				if t.cfg.EnableIQA {
					var iqaResult C.LONG
					if r := C.astra_par_get_long(C.UINT(t.cfg.IQAResultParamID), &iqaResult); int32(r) == csdOK {
						if int32(iqaResult) != C.CSD_IQA_BRIGHTNESS_PASSED {
							t.logger.Warn("IQA brightness fail — ejecting cheque to operator tray",
								"result", int32(iqaResult))
							releaseFront()
							C.astra_abort_scan()
							if r2 := int32(C.astra_start_scan()); r2 != csdOK {
								return nil, fmt.Errorf("restart scan after IQA reject: code %d", r2)
							}
							return &ScannedItem{IQAFailed: true, MICRRaw: micrRaw}, nil
						}
					}
				}

			case hasFront && !hasRear:
				// Pass 2 — rear side.
				// Save front in two formats before releasing the buffer:
				//   grayscale (LZW)   → frontTIFF   → {MICR}_F_GR.tif
				//   binary threshold  → frontBWTIFF → {MICR}_F_BW.tif
				// Save rear as binary (threshold same way) → {MICR}_B_BW.tif
				rearDPI = int(img.lXResolution)

				var err error
				frontTIFF, err = t.saveImageToBytes(&frontImg) // grayscale, LZW
				if err != nil {
					releaseFront()
					C.astra_release_image(&img)
					return nil, fmt.Errorf("save front grayscale: %w", err)
				}
				frontBWTIFF, err = t.saveImageToBytesBW(&frontImg) // binary, CCITT G4
				releaseFront()
				if err != nil {
					// Non-fatal: F_BW is derived; GR is the authoritative image.
					t.logger.Warn("front binary threshold failed — F_BW omitted", "error", err)
				}

				rearTIFF, err = t.saveImageToBytesBW(&img) // rear binary, CCITT G4
				C.astra_release_image(&img)
				if err != nil {
					return nil, fmt.Errorf("save rear binary: %w", err)
				}

				if !t.cfg.EnableUVScan {
					// No UV lamp — assemble and return now.
					return t.assembleItem(frontTIFF, frontBWTIFF, rearTIFF, nil, frontDPI, rearDPI, micrRaw), nil
				}
				// UV enabled: stay in the loop to receive the UV page.
				hasRear = true

			default:
				// Pass 3 — UV image (only reached when EnableUVScan=true).
				uvTIFF, err := t.saveImageToBytes(&img)
				C.astra_release_image(&img)
				hasRear = false
				if err != nil {
					// UV save failed — return item without UV rather than failing the cheque.
					// The workflow will route to human review (security feature check skipped).
					t.logger.Warn("save UV image failed — submitting without UV", "error", err)
					return t.assembleItem(frontTIFF, frontBWTIFF, rearTIFF, nil, frontDPI, rearDPI, micrRaw), nil
				}
				return t.assembleItem(frontTIFF, frontBWTIFF, rearTIFF, uvTIFF, frontDPI, rearDPI, micrRaw), nil
			}

		case csdDoubleFeed:
			// Ultrasonic sensor triggered.  Release any partial image and tell the
			// SDK to resume scanning (without this call, the scanner stalls).
			releaseFront()
			hasRear = false
			C.astra_par_set_long(C.CSDP_DBLFEEDSTATUS, C.LONG(csdOK))
			t.logger.Warn("double-feed detected by ultrasonic sensor")
			return &ScannedItem{DoubleFeedDetected: true}, nil

		case csdNoPaper:
			// Feeder exhausted.  In a live clearing session the operator will feed
			// the next cheque; restart the scan and keep waiting rather than ending
			// the session.  If EndJob was called, exit cleanly.
			releaseFront()
			hasRear = false
			select {
			case <-t.done:
				return nil, nil // clean session end
			default:
			}
			// Back-off before restarting — avoids spinning the CPU while waiting for next cheque.
			time.Sleep(time.Duration(t.cfg.FeederPollMS) * time.Millisecond)
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
			releaseFront()
			hasRear = false
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
			releaseFront()
			hasRear = false
			return nil, nil

		case csdJam:
			releaseFront()
			hasRear = false
			return nil, ErrPaperJam

		case csdCoverOpen:
			releaseFront()
			hasRear = false
			return nil, ErrCoverOpen

		default:
			releaseFront()
			hasRear = false
			return nil, fmt.Errorf("CsdReadPage unexpected code %d", ret)
		}
	}
}

// assembleItem constructs a ScannedItem from the captured image buffers.
// frontBWTIFF may be nil if binary thresholding failed (non-fatal).
// uvTIFF may be nil when the scanner is a non-UV model or UV capture failed.
func (t *CanonTransport) assembleItem(frontTIFF, frontBWTIFF, rearTIFF, uvTIFF []byte, frontDPI, rearDPI int, micrRaw string) *ScannedItem {
	return &ScannedItem{
		FrontImage:       frontTIFF,
		FrontImageBW:     frontBWTIFF,
		RearImage:        rearTIFF,
		UVImage:          uvTIFF,
		FrontDPI:         frontDPI,
		RearDPI:          rearDPI,
		FrontFileSizeKB:  float64(len(frontTIFF)) / 1024.0,
		RearFileSizeKB:   float64(len(rearTIFF)) / 1024.0,
		FrontColourDepth: 8, // grayscale scan mode
		RearColourDepth:  1, // binary after threshold
		MICRRaw:          micrRaw,
		ImprinterStamped: t.cfg.EnableImprinter,
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

// rawPixels copies the scanner's C-allocated image buffer into a Go slice and
// returns the slice plus the computed row stride.
// Safe to call before astra_release_image; C.GoBytes makes its own allocation.
func (t *CanonTransport) rawPixels(img *C.CEIIMAGEINFO) (pixels []byte, srcStride, width, height, dpi int, err error) {
	width   = int(img.lWidth)
	height  = int(img.lHeight)
	dpi     = int(img.lXResolution)
	imgSize := int(img.tImageSize)

	if imgSize <= 0 || width <= 0 || height <= 0 {
		err = fmt.Errorf("invalid image dimensions %dx%d size=%d", width, height, imgSize)
		return
	}
	if dpi <= 0 {
		dpi = t.cfg.ScanDPI
	}
	pixels    = C.GoBytes(unsafe.Pointer(img.lpImage), C.int(imgSize))
	srcStride = imgSize / height
	return
}

// saveImageToBytes encodes a scanner image as an uncompressed 8-bpp TIFF with
// the black scanner-transport border auto-cropped from the bottom.
//
// This replaces the former CsdSaveImageEx path: we already have the raw pixel
// bytes via rawPixels(), so writing the TIFF in pure Go is simpler and lets us
// crop in the same pass without any extra CSD call.
func (t *CanonTransport) saveImageToBytes(img *C.CEIIMAGEINFO) ([]byte, error) {
	pixels, srcStride, width, height, dpi, err := t.rawPixels(img)
	if err != nil {
		return nil, fmt.Errorf("saveImageToBytes: %w", err)
	}
	contentH := findContentHeight(pixels, srcStride, width, height)
	t.logger.Debug("grayscale crop", "full_h", height, "content_h", contentH,
		"cropped_px", height-contentH)

	data := writeGrayscaleTIFF(pixels, srcStride, width, contentH, dpi)
	if len(data) == 0 {
		return nil, fmt.Errorf("writeGrayscaleTIFF produced empty output for %dx%d image", width, contentH)
	}
	return data, nil
}

// saveImageToBytesBW thresholds a scanner image to 1-bpp and encodes it as an
// uncompressed 1-bpp TIFF with the black scanner-transport border auto-cropped.
func (t *CanonTransport) saveImageToBytesBW(img *C.CEIIMAGEINFO) ([]byte, error) {
	if img.lBps != 8 {
		// Already binary — use the grayscale path (returns as-is, still cropped).
		return t.saveImageToBytes(img)
	}
	pixels, srcStride, width, height, dpi, err := t.rawPixels(img)
	if err != nil {
		return nil, fmt.Errorf("saveImageToBytesBW: %w", err)
	}
	contentH := findContentHeight(pixels, srcStride, width, height)
	t.logger.Debug("binary crop", "full_h", height, "content_h", contentH,
		"cropped_px", height-contentH)

	data := writeBinaryTIFF(pixels, srcStride, width, contentH, dpi)
	if len(data) == 0 {
		return nil, fmt.Errorf("writeBinaryTIFF produced empty output for %dx%d image", width, contentH)
	}
	return data, nil
}
