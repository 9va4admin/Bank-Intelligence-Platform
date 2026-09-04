package main

// tiff_bw.go — minimal uncompressed 1-bpp TIFF encoder (pure Go, no CGO).
//
// Used to derive the {MICR}_F_BW.tif binary front image from the grayscale
// front scan (CTS-2010 supplementary binary image).  We cannot reuse
// CsdSaveImageEx for this because the Canon DLL validates that lpImage points
// to a buffer it allocated internally — passing a calloc'd threshold buffer
// causes the call to fail.  Writing the TIFF ourselves sidesteps that
// restriction and avoids a temp-file round-trip.
//
// TIFF layout (little-endian):
//   offset  0: 8-byte header  (magic + IFD offset)
//   offset  8: IFD            (2 + N×12 + 4 bytes)
//   offset  8+IFD: image data (1bpp, MSB-first, rows padded to byte boundary)
//   after image data: XResolution rational (8 bytes)
//   after that:       YResolution rational (8 bytes)

import (
	"bytes"
	"encoding/binary"
)

// writeBinaryTIFF thresholds an 8-bpp grayscale pixel buffer to 1-bpp and
// encodes it as an uncompressed TIFF (Compression=1).
//
// pixels    — raw 8-bpp bytes, row-major. Row stride = len(pixels)/height
//             (the scanner driver may add padding bytes per row).
// width, height — image dimensions in pixels.
// dpi       — scan resolution; written to XResolution / YResolution tags.
//
// Thresholding rule: pixel >= 128 → white (bit=1, MSB-first), else black.
func writeBinaryTIFF(pixels []byte, width, height, dpi int) []byte {
	if len(pixels) == 0 || width <= 0 || height <= 0 {
		return nil
	}

	// --- threshold: 8bpp → 1bpp -------------------------------------------------
	srcStride := len(pixels) / height // actual bytes per row (may include padding)
	dstStride := (width + 7) / 8     // bytes per 1bpp row, no padding
	imgData := make([]byte, dstStride*height)
	for y := 0; y < height; y++ {
		for x := 0; x < width; x++ {
			if pixels[y*srcStride+x] >= 128 {
				imgData[y*dstStride+x/8] |= 0x80 >> uint(x%8)
			}
		}
	}

	// --- TIFF layout ------------------------------------------------------------
	// IFD size: 2 (count) + 11 entries × 12 bytes + 4 (next-IFD offset) = 138
	const (
		numTags = 11
		ifdSize = 2 + numTags*12 + 4
		hdrSize = 8
	)
	imgOffset  := uint32(hdrSize + ifdSize)     // image data starts here
	imgSize    := uint32(len(imgData))
	xResOffset := imgOffset + imgSize            // XResolution rational
	yResOffset := xResOffset + 8                 // YResolution rational

	var buf bytes.Buffer
	le := binary.LittleEndian

	put16 := func(v uint16) {
		var b [2]byte
		le.PutUint16(b[:], v)
		buf.Write(b[:])
	}
	put32 := func(v uint32) {
		var b [4]byte
		le.PutUint32(b[:], v)
		buf.Write(b[:])
	}
	// IFD entry: tag (SHORT) + type (SHORT) + count (LONG) + value/offset (LONG)
	entry := func(tag, typ uint16, count, val uint32) {
		put16(tag)
		put16(typ)
		put32(count)
		put32(val)
	}
	const (
		tSHORT    = uint16(3)
		tLONG     = uint16(4)
		tRATIONAL = uint16(5)
	)

	// TIFF header (little-endian byte order marker + version + IFD offset)
	buf.Write([]byte{0x49, 0x49}) // 'II' = little-endian
	put16(42)                      // TIFF version
	put32(uint32(hdrSize))         // IFD starts immediately after header

	// IFD — tags must be in ascending numeric order (TIFF spec 6.0)
	put16(numTags)
	entry(256, tLONG,     1, uint32(width))      // ImageWidth
	entry(257, tLONG,     1, uint32(height))     // ImageLength
	entry(258, tSHORT,    1, 1)                  // BitsPerSample = 1
	entry(259, tSHORT,    1, 1)                  // Compression = 1 (uncompressed)
	entry(262, tSHORT,    1, 0)                  // PhotometricInterpretation = 0 (WhiteIsZero)
	entry(273, tLONG,     1, imgOffset)          // StripOffsets
	entry(278, tLONG,     1, uint32(height))     // RowsPerStrip (single strip)
	entry(279, tLONG,     1, imgSize)            // StripByteCounts
	entry(282, tRATIONAL, 1, xResOffset)        // XResolution
	entry(283, tRATIONAL, 1, yResOffset)        // YResolution
	entry(296, tSHORT,    1, 2)                  // ResolutionUnit = 2 (inch)
	put32(0) // NextIFD = 0 (last IFD)

	// Image data
	buf.Write(imgData)

	// RATIONAL values: numerator (uint32) / denominator (uint32)
	put32(uint32(dpi)); put32(1) // XResolution = dpi/1
	put32(uint32(dpi)); put32(1) // YResolution = dpi/1

	return buf.Bytes()
}
