// Bank identity + deployment mode — driven entirely by env vars.
// Set VITE_BANK_ID to select a preset; set VITE_BANK_MODE to control SMB features.
//
//   VITE_BANK_ID   — 'saraswat-coop' (default) | 'karnataka-bank' | any future preset
//   VITE_BANK_MODE — 'SB_SMB' (default) | 'SB_ONLY' | 'SMB_ONLY'
//
// SB_SMB  → Sponsor Bank deployment that also manages Sub-Members (full nav)
// SB_ONLY → Sponsor Bank deployment without any SMB management (no SMB nav items)
// SMB_ONLY → Sub-Member Bank standalone deployment (SMB-user view only)

const BANK_PRESETS = {
  'saraswat-coop': {
    bank_id:         'saraswat-coop',
    bank_name:       'Saraswat Co-operative Bank',
    bank_short_name: 'Saraswat',
    tagline:         'A Century of Trust.',
    bank_logo:       '/logos/saraswat-logo.png',
    primary_hex:     '#1E3A8A',
    ifsc_prefix:     'SRCB',
    clearing_zone:   'WEST',
  },
  'karnataka-bank': {
    bank_id:         'karnataka-bank',
    bank_name:       'Karnataka Bank Limited',
    bank_short_name: 'KBL',
    tagline:         'Your Family Bank. Across India.',
    bank_logo:       '/logos/karnataka-bank-logo-static.png',
    primary_hex:     '#6B21A8',
    ifsc_prefix:     'KARB',
    clearing_zone:   'SOUTH',
  },
}

const bankId   = import.meta.env.VITE_BANK_ID   ?? 'saraswat-coop'
const bankMode = import.meta.env.VITE_BANK_MODE  ?? 'SB_SMB'

export const BANK_CONFIG = {
  ...(BANK_PRESETS[bankId] ?? BANK_PRESETS['saraswat-coop']),
  bank_mode:  bankMode,
  api_base:   import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  astra_logo: '/logos/astra-logo.png',
}
