/**
 * Bank deployment configuration.
 * This is the ONLY file that changes when deploying for a different bank.
 * Swap logos in public/logos/ and update this file — rest of the UI adapts automatically.
 */
export const BANK_CONFIG = {
  // Identity
  bank_id:         'kbl',
  bank_name:       'Karnataka Bank Limited',
  bank_short_name: 'KBL',
  tagline:         'Your Family Bank. Across India.',

  // Logos
  // Set bank_logo to whatever file the bank provides — .svg .png .jpg .jpeg .webp all work.
  // Note: .tiff is NOT supported by browsers natively; ask the bank for a web-format export.
  // ASTRA logo lives at public/logos/astra-logo.svg — do not change that path.
  bank_logo:  '/logos/karnataka-bank-logo-static.png',

  // Brand colour used for sidebar accent, active nav indicator, badges
  // Must be a valid CSS hex — tailwind JIT picks it up via style prop
  primary_hex: '#6B21A8',

  // Network identity
  ifsc_prefix:   'KARB',
  clearing_zone: 'SOUTH',

  // Backend — override via .env.local
  api_base: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
}
