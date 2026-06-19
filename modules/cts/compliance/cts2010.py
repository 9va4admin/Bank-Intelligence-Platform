"""
CTS-2010 Standard constants (RBI-mandated — never configurable by bank).

Source: RBI CTS-2010 Standard Specifications for Cheque Truncation System.
These values are immutable regulatory requirements, not Layer 3 business thresholds.
"""


class CTS2010Standard:
    MIN_DPI:              int   = 200      # minimum dots per inch for cheque image
    MIN_COLOUR_DEPTH:     int   = 24       # bits — RGB colour (front image)
    GRAYSCALE_DEPTH:      int   = 8        # bits — rear image may be grayscale
    MAX_FILE_SIZE_KB:     float = 50.0     # maximum image file size per side
    MIN_IQA_SCORE:        float = 0.70     # minimum overall Image Quality Assessment score
    MICR_BAND_MIN_SCORE:  float = 0.80     # minimum MICR line legibility score
    FRONT_IMAGE_REQUIRED: bool  = True
    REAR_IMAGE_REQUIRED:  bool  = True
