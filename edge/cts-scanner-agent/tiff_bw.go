package main

// tiff_bw.go — pure-Go TIFF encoders + black-border auto-crop.
//
// Three exported functions:
//
//   findContentHeight — scans from the bottom row upward to find where the
//     cheque ends; used to discard the black scanner-transport area below it.
//
//   writeBinaryTIFF  — threshold 8bpp → 1bpp, write uncompressed 1-bpp TIFF.
//     Used for {MICR}_F_BW.tif and {MICR}_B_BW.tif.
//
//   writeGrayscaleTIFF — copy cropped rows, write uncompressed 8bpp TIFF.
//     Used for {MICR}_F_GR.tif.  Replaces the CsdSaveImageEx path so the
//     grayscale image is also auto-cropped from the same raw pixel data.
//
// Why bypass CsdSaveImageEx for grayscale?
//   CSDP_LENGTH = CSDP_MAXLENGTH forces the DLL to capture the full transport
//   path (≈200 mm) every time; there is no per-image crop API.  We get the raw
//   8-bpp buffer via C.GoBytes anyway, so writing the TIFF ourselves costs
//   nothing extra and lets us drop the blank rows in one pass.
//
// TIFF layout (little-endian, 11 tags, same structure for both encoders):
//   offset  0 : 8-byte header  (II + 42 + IFD offset)
//   offset  8 : IFD            (2 + 11×12 + 4 = 138 bytes)
//   offset 146 : image data    (raw rows, Compression=1 uncompressed)
//   after data : XResolution rational (8 bytes)
//   after that : YResolution rational (8 bytes)

import (
	"bytes"
	"encoding/binary"
)

// findContentHeight scans from the bottom row upward and returns the 1-based
// row count of the last row that contains meaningful image content, along with
// the detected background level (for logging).
//
//   pixels     — raw 8-bpp bytes from C.GoBytes; len = srcStride * fullHeight.
//   srcStride  — actual bytes per row including any scanner padding.
//   width      — logical pixels per row (no padding).
//   fullHeight — total rows captured (including scanner-transport area).
//
// Strategy — adaptive background detection:
//   1. Average the last 30 rows → that is the background level (works whether
//      the transport area is bright-white or pitch-black, scanner-dependent).
//   2. A row is "content" when ≥10 % of its pixels deviate from bgLevel by
//      more than 25 counts in either direction.
//   3. A 30-pixel safety margin is added below the detected boundary.
//
// Returns (contentH, bgLevel).
func findContentHeight(pixels []byte, srcStride, width, fullHeight int) (contentH, bgLevel int) {
	if len(pixels) == 0 || fullHeight <= 0 || width <= 0 || srcStride <= 0 {
		return fullHeight, 0
	}

	// --- step 1: measure background level from the bottom 30 rows ---
	sampleRows := 30
	if sampleRows > fullHeight/4 { // never use more than 25 % of image
		sampleRows = fullHeight / 4
	}
	if sampleRows < 1 {
		sampleRows = 1
	}
	var sum int64
	for y := fullHeight - sampleRows; y < fullHeight; y++ {
		for x := 0; x < width; x++ {
			sum += int64(pixels[y*srcStride+x])
		}
	}
	bgLevel = int(sum / int64(sampleRows*width))

	// --- step 2: scan upward for the last row that differs from bg ---
	const tolerance = 25         // pixel deviation to be "not background"
	minPixels := width / 10      // 10 % of row must differ
	if minPixels < 1 {
		minPixels = 1
	}

	for y := fullHeight - 1; y >= 0; y-- {
		diffCount := 0
		for x := 0; x < width; x++ {
			v := int(pixels[y*srcStride+x])
			if v < bgLevel-tolerance || v > bgLevel+tolerance {
				diffCount++
				if diffCount >= minPixels {
					contentH = y + 1 + 30 // 30-px safety margin
					if contentH > fullHeight {
						contentH = fullHeight
					}
					return
				}
			}
		}
	}
	contentH = fullHeight // no background detected — keep everything
	return
}

// tiffBuild encodes image data as an uncompressed little-endian TIFF (11 tags).
//
//   bps          — bits per sample: 1 or 8.
//   photometric  — 0 = WhiteIsZero (for 1bpp), 1 = BlackIsZero (for 8bpp).
//   imgData      — packed pixel bytes: 1bpp → dstStride×h, 8bpp → width×h.
//   width, height — dimensions of imgData in pixels.
//   dpi           — written to XResolution / YResolution tags.
func tiffBuild(bps, photometric uint16, imgData []byte, width, height, dpi int) []byte {
	const (
		numTags = 11
		ifdSize = 2 + numTags*12 + 4 // 138
		hdrSize = 8
	)
	imgOffset  := uint32(hdrSize + ifdSize) // 146
	imgSize    := uint32(len(imgData))
	xResOffset := imgOffset + imgSize
	yResOffset := xResOffset + 8

	var buf bytes.Buffer
	le := binary.LittleEndian

	p16 := func(v uint16) { var b [2]byte; le.PutUint16(b[:], v); buf.Write(b[:]) }
	p32 := func(v uint32) { var b [4]byte; le.PutUint32(b[:], v); buf.Write(b[:]) }
	tag := func(id, typ uint16, count, val uint32) { p16(id); p16(typ); p32(count); p32(val) }

	const (
		SHORT    = uint16(3)
		LONG     = uint16(4)
		RATIONAL = uint16(5)
	)

	// Header
	buf.Write([]byte{0x49, 0x49}) // 'II' = little-endian
	p16(42)
	p32(uint32(hdrSize)) // IFD at offset 8

	// IFD — tags in ascending numeric order (TIFF 6.0 requirement)
	p16(numTags)
	tag(256, LONG,     1, uint32(width))
	tag(257, LONG,     1, uint32(height))
	tag(258, SHORT,    1, uint32(bps))
	tag(259, SHORT,    1, 1)                  // Compression = 1 (uncompressed)
	tag(262, SHORT,    1, uint32(photometric))
	tag(273, LONG,     1, imgOffset)
	tag(278, LONG,     1, uint32(height))     // RowsPerStrip = height (single strip)
	tag(279, LONG,     1, imgSize)
	tag(282, RATIONAL, 1, xResOffset)
	tag(283, RATIONAL, 1, yResOffset)
	tag(296, SHORT,    1, 2)                  // ResolutionUnit = inch
	p32(0)                                    // NextIFD = 0 (last IFD)

	buf.Write(imgData)

	p32(uint32(dpi)); p32(1) // XResolution = dpi/1
	p32(uint32(dpi)); p32(1) // YResolution = dpi/1

	return buf.Bytes()
}

// writeBinaryTIFF thresholds an 8-bpp buffer to 1-bpp and encodes it as an
// uncompressed TIFF.  Pass contentHeight from findContentHeight to crop the
// black scanner-transport border; srcStride is the full-image bytes per row.
//
// Threshold: pixel >= 128 → white (bit=1, MSB-first).
// PhotometricInterpretation = 0 (WhiteIsZero): bit=1 displays as white. ✓
func writeBinaryTIFF(pixels []byte, srcStride, width, contentHeight, dpi int) []byte {
	if len(pixels) == 0 || width <= 0 || contentHeight <= 0 || srcStride <= 0 {
		return nil
	}
	dstStride := (width + 7) / 8
	imgData := make([]byte, dstStride*contentHeight)
	for y := 0; y < contentHeight; y++ {
		for x := 0; x < width; x++ {
			if pixels[y*srcStride+x] >= 128 {
				imgData[y*dstStride+x/8] |= 0x80 >> uint(x%8)
			}
		}
	}
	return tiffBuild(1, 0, imgData, width, contentHeight, dpi)
}

// writeGrayscaleTIFF copies the content rows of an 8-bpp buffer and encodes
// them as an uncompressed 8-bpp TIFF.  Pass contentHeight from findContentHeight
// to crop the black scanner-transport border; srcStride is the full-image
// bytes per row (scanner may pad each row beyond the logical width).
//
// PhotometricInterpretation = 1 (BlackIsZero): 0=black ink, 255=white paper. ✓
func writeGrayscaleTIFF(pixels []byte, srcStride, width, contentHeight, dpi int) []byte {
	if len(pixels) == 0 || width <= 0 || contentHeight <= 0 || srcStride <= 0 {
		return nil
	}
	imgData := make([]byte, width*contentHeight)
	for y := 0; y < contentHeight; y++ {
		copy(imgData[y*width:], pixels[y*srcStride:y*srcStride+width])
	}
	return tiffBuild(8, 1, imgData, width, contentHeight, dpi)
}
