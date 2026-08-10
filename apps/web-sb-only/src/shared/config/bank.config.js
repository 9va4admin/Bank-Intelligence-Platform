/**
 * Bank deployment configuration.
 * This is the ONLY file that changes when deploying for a different bank.
 * Swap logos in public/logos/ and update this file — rest of the UI adapts automatically.
 */
export const BANK_CONFIG = {
  // Identity
  bank_id:         'federal-bank',
  bank_name:       'Federal Bank Limited',
  bank_short_name: 'Federal',
  tagline:         'Your Perfect Banking Partner.',

  // Logos
  bank_logo:  '/logos/federal-bank-logo.png',

  // Brand colour used for sidebar accent, active nav indicator, badges
  primary_hex: '#C62828',

  // Network identity
  ifsc_prefix:   'FDRL',
  clearing_zone: 'SOUTH',

  // Backend — override via .env.local
  api_base: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
}
