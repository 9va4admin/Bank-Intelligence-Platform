package main

// tiff_bw.go — pure-Go TIFF encoders + 4-sided black-border auto-crop.
//
// Public API:
//
//   findContentBounds — determines the tight bounding box of the cheque
//     by sampling the four corners to learn the scanner's background level,
//     then scanning every row and column for content pixels.  Returns a
//     ContentBounds with a configurable margin added on all four sides.
//
//   writeBinaryTIFF  — threshold 8bpp → 1bpp, write uncompressed 1-bpp TIFF
//     for the cropped region.  {MICR}_F_BW.tif / {MICR}_B_BW.tif.
//
//   writeGrayscaleTIFF — copy cropped rows, write uncompressed 8bpp TIFF.
//     {MICR}_F_GR.tif.
//
// Why 4-sided crop?
//   CSDP_WIDTH = MAXWIDTH and CSDP_LENGTH = MAXLENGTH cause the scanner to
//   capture the full transport-path area in both directions.  The cheque
//   sits inside that area with black (or bright-white, scanner-dependent)
//   background on all four sides — not just the bottom.

import (
	"bytes"
	"encoding/binary"
)

// ContentBounds is the bounding box of the cheque content within the raw scan.
// All coordinates are in pixels, inclusive.  After adding margins, the
// cropped region is [Top:Bottom+1, Left:Right+1].
type ContentBounds struct {
	Top, Left, Bottom, Right int
	BGLevel                  int // measured background level (0–255); logged for diagnostics
}

// CroppedWidth returns the pixel width of the cropped region.
func (b ContentBounds) CroppedWidth() int { return b.Right - b.Left + 1 }

// CroppedHeight returns the pixel height of the cropped region.
func (b ContentBounds) CroppedHeight() int { return b.Bottom - b.Top + 1 }

// findContentBounds detects the tight bounding box of the cheque within the
// raw scan buffer using an adaptive background-level measurement.
//
//   pixels     — raw 8-bpp bytes from C.GoBytes (len = srcStride × fullHeight).
//   srcStride  — bytes per row including scanner padding.
//   width      — logical pixels per row (no padding).
//   fullHeight — total captured rows.
//
// Algorithm:
//  1. Average a 20×20-px patch from each of the four corners — those patches
//     are always pure scanner background regardless of cheque placement.
//     bgLevel is the resulting reference value.
//  2. Per row: find leftmost and rightmost content pixels (deviation > 25 from
//     bgLevel).  Compute row "content span" = rightmost − leftmost.
//  3. Use ONLY rows whose content span exceeds half the image width to set the
//     left / right / top / bottom bounds.  This filters out thin vertical
//     scanner alignment marks (1–2 px wide) that would otherwise pull the left
//     boundary to the very edge of the image.
//  4. Add a 30-px safety margin on all four sides.
func findContentBounds(pixels []byte, srcStride, width, fullHeight int) ContentBounds {
	full := ContentBounds{Top: 0, Left: 0, Bottom: fullHeight - 1, Right: width - 1}
	if len(pixels) == 0 || srcStride <= 0 || width <= 0 || fullHeight <= 0 {
		return full
	}

	// safePixel reads a pixel without panicking if the buffer is smaller than
	// expected (e.g. tImageSize was wrong). Out-of-bounds reads return bgByte.
	const bgByte = byte(0) // used only for bounds-guard before bgLevel is known
	safeGet := func(idx int) byte {
		if idx < 0 || idx >= len(pixels) {
			return bgByte
		}
		return pixels[idx]
	}

	// --- 1. background level from BOTTOM corners only ---
	// The Canon CR-120 feeds cheques from the top — the cheque always occupies
	// the top portion of the captured area and the bottom portion is always pure
	// scanner transport background (black).  Averaging all four corners would
	// mix cheque paper (white ~255) with transport background (black ~0) and
	// produce bgLevel≈128, causing both the cheque and the transport to be
	// classified as "content" and making the crop a no-op.
	// Using only the bottom two corners gives bgLevel≈0 (pure transport), so
	// anything significantly brighter (the cheque paper) is correctly detected.
	patch := 20
	if patch > width/4      { patch = width / 4 }
	if patch > fullHeight/4 { patch = fullHeight / 4 }
	if patch < 1             { patch = 1 }
	var sum int64
	n := int64(patch * patch * 2) // two corners only
	for row := 0; row < patch; row++ {
		for col := 0; col < patch; col++ {
			sum += int64(safeGet((fullHeight-1-row)*srcStride + col))
			sum += int64(safeGet((fullHeight-1-row)*srcStride + (width - 1 - col)))
		}
	}
	bgLevel := int(sum / n)

	// --- 2 & 3. scan rows; only use "wide" rows for bounds ---
	const tolerance   = 25
	// A row must have content spanning > width/minSpanFrac pixels to be counted.
	// 4 means 25 % — lenient enough for cheques that don't fill the transport path.
	const minSpanFrac = 4

	top    := fullHeight // sentinel
	left   := width
	bottom := -1
	right  := -1

	for y := 0; y < fullHeight; y++ {
		rowBase  := y * srcStride
		rowLeft  := -1
		rowRight := -1
		for x := 0; x < width; x++ {
			v := int(safeGet(rowBase + x))
			if v < bgLevel-tolerance || v > bgLevel+tolerance {
				if rowLeft < 0 { rowLeft = x }
				rowRight = x
			}
		}
		if rowLeft < 0 {
			continue // blank row
		}
		span := rowRight - rowLeft
		if span <= width/minSpanFrac {
			// Thin content (alignment mark, edge noise) — skip for boundary calc.
			continue
		}
		// Wide row → counts toward the bounding box.
		if y < top    { top = y }
		if y > bottom { bottom = y }
		if rowLeft  < left  { left  = rowLeft }
		if rowRight > right { right = rowRight }
	}

	if bottom < 0 {
		// Nothing wide enough found — return the full image uncropped.
		full.BGLevel = bgLevel
		return full
	}

	// --- 4. add 30-px safety margin ---
	const margin = 30
	if top    > margin               { top    -= margin } else { top    = 0 }
	if left   > margin               { left   -= margin } else { left   = 0 }
	if bottom < fullHeight-1-margin  { bottom += margin } else { bottom = fullHeight - 1 }
	if right  < width-1-margin       { right  += margin } else { right  = width - 1 }

	return ContentBounds{Top: top, Left: left, Bottom: bottom, Right: right, BGLevel: bgLevel}
}

// tiffBuild encodes image data as an uncompressed little-endian TIFF (11 tags).
//
//   bps         — bits per sample: 1 or 8.
//   photometric — 0 = WhiteIsZero (1bpp), 1 = BlackIsZero (8bpp grayscale).
//   imgData     — packed pixel bytes for the cropped region.
//   w, h        — width and height of imgData in pixels.
//   dpi         — written to XResolution / YResolution.
func tiffBuild(bps, photometric uint16, imgData []byte, w, h, dpi int) []byte {
	const (
		numTags = 11
		ifdSize = 2 + numTags*12 + 4 // 138 bytes
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

	buf.Write([]byte{0x49, 0x49}) // 'II' = little-endian
	p16(42)
	p32(uint32(hdrSize))

	p16(numTags)
	tag(256, LONG,     1, uint32(w))
	tag(257, LONG,     1, uint32(h))
	tag(258, SHORT,    1, uint32(bps))
	tag(259, SHORT,    1, 1)                   // Compression = 1 (uncompressed)
	tag(262, SHORT,    1, uint32(photometric))
	tag(273, LONG,     1, imgOffset)
	tag(278, LONG,     1, uint32(h))           // RowsPerStrip = h (single strip)
	tag(279, LONG,     1, imgSize)
	tag(282, RATIONAL, 1, xResOffset)
	tag(283, RATIONAL, 1, yResOffset)
	tag(296, SHORT,    1, 2)                   // ResolutionUnit = inch
	p32(0)                                     // NextIFD = 0

	buf.Write(imgData)
	p32(uint32(dpi)); p32(1) // XResolution = dpi/1
	p32(uint32(dpi)); p32(1) // YResolution = dpi/1
	return buf.Bytes()
}

// writeBinaryTIFF thresholds the cropped region of an 8-bpp pixel buffer to
// 1-bpp and encodes it as an uncompressed TIFF.
//
// Threshold: pixel >= 128 → white (bit=1, MSB-first).
// PhotometricInterpretation = 0 (WhiteIsZero): bit=1 displays as white. ✓
func writeBinaryTIFF(pixels []byte, srcStride int, b ContentBounds, dpi int) []byte {
	w := b.CroppedWidth()
	h := b.CroppedHeight()
	if len(pixels) == 0 || w <= 0 || h <= 0 {
		return nil
	}
	dstStride := (w + 7) / 8
	imgData := make([]byte, dstStride*h)
	plen := len(pixels)
	for y := 0; y < h; y++ {
		srcRow := (b.Top + y) * srcStride
		for x := 0; x < w; x++ {
			idx := srcRow + b.Left + x
			if idx >= plen {
				break // treat out-of-bounds pixels as background (bit stays 0)
			}
			if pixels[idx] >= 128 {
				imgData[y*dstStride+x/8] |= 0x80 >> uint(x%8)
			}
		}
	}
	return tiffBuild(1, 0, imgData, w, h, dpi)
}

// writeGrayscaleTIFF copies the cropped region of an 8-bpp pixel buffer and
// encodes it as an uncompressed 8-bpp TIFF.
//
// PhotometricInterpretation = 1 (BlackIsZero): 0=black ink, 255=white paper. ✓
func writeGrayscaleTIFF(pixels []byte, srcStride int, b ContentBounds, dpi int) []byte {
	w := b.CroppedWidth()
	h := b.CroppedHeight()
	if len(pixels) == 0 || w <= 0 || h <= 0 {
		return nil
	}
	imgData := make([]byte, w*h)
	plen := len(pixels)
	for y := 0; y < h; y++ {
		srcRow := (b.Top + y) * srcStride
		start := srcRow + b.Left
		end   := start + w
		if start >= plen {
			break // no more pixel data; remaining rows stay as 0 (black)
		}
		if end > plen {
			end = plen // partial row — copy what we have, rest stays 0
		}
		copy(imgData[y*w:], pixels[start:end])
	}
	return tiffBuild(8, 1, imgData, w, h, dpi)
}
