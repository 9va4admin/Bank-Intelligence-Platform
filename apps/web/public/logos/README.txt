Place the bank logo here and update bank_logo in src/shared/config/bank.config.js
to point to the actual filename.

Supported formats (browser-native):
  .svg   — best for logos; scales perfectly at any size
  .png   — good; transparent background supported
  .jpg / .jpeg — fine if no transparency needed
  .webp  — modern, smaller file size

NOT supported natively in browsers:
  .tiff / .tif — ask the bank's design team for a PNG or SVG export

astra-logo.svg is the ASTRA platform logo — do not rename or replace.

When deploying for a new bank:
  1. Drop their logo here (any supported format above)
  2. Update src/shared/config/bank.config.js:
       bank_logo: '/logos/their-logo.png'   ← match exact filename + extension
       bank_id, bank_name, primary_hex, tagline, ifsc_prefix
  3. Update tailwind.config.js brand.800 to match the bank's primary colour
  4. npm run build
