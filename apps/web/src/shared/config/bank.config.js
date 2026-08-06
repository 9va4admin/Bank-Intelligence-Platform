// Bank identity + deployment mode — driven entirely by env vars.
// Set VITE_BANK_ID to select a preset; set VITE_BANK_MODE to control SMB features.
//
//   VITE_BANK_ID   — 'saraswat-coop' (default) | 'karnataka-bank' | any future preset
//   VITE_BANK_MODE — 'SB_SMB' (default) | 'SB_ONLY' | 'SMB_ONLY'
//   deploymentMode = 'DEMO' | 'POC' | 'PROD'

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
    bank_logo:       'saraswat-logo.png',
    primary_hex:     '#1E3A8A',
    ifsc_prefix:     'SRCB',
    clearing_zone:   'WEST',
  },
  'karnataka-bank': {
    bank_id:         'karnataka-bank',
    bank_name:       'Karnataka Bank Limited',
    bank_short_name: 'KBL',
    tagline:         'Your Family Bank. Across India.',
    bank_logo:       'karnataka-bank-logo-static.png',
    primary_hex:     '#6B21A8',
    ifsc_prefix:     'KARB',
    clearing_zone:   'SOUTH',
  },
}

// const bankId   = import.meta.env.VITE_BANK_ID   ?? 'saraswat-coop'
// const bankMode = import.meta.env.VITE_BANK_MODE  ?? 'SB_SMB'

const bankId   = import.meta.env.VITE_BANK_ID   ?? 'karnataka-bank'
const bankMode = import.meta.env.VITE_BANK_MODE  ?? 'SB_ONLY'

// BASE_URL already includes a trailing slash (e.g. '/Bank-Intelligence-Platform/')
// so we join without a leading slash on the asset path.

// VITE_DEPLOYMENT_MODE controls which integrations are live vs stubbed:
//   DEMO  — pre-seeded mock data, no real services required (default)
//   POC   — full pipeline, real AI/DB/queues, folder-based I/O instead of scanner+NGCH
//   PROD  — everything live: physical scanner, NGCH, on-prem vLLM, CBS
const deploymentMode = import.meta.env.VITE_DEPLOYMENT_MODE ?? 'POC'

const base = import.meta.env.BASE_URL ?? '/'

const preset = BANK_PRESETS[bankId] ?? BANK_PRESETS['karnataka-ban']

export const BANK_CONFIG = {
  ...preset,
  bank_logo:        `${base}logos/${preset.bank_logo.split('/').pop()}`,
  bank_mode:        bankMode,
  deployment_mode:  deploymentMode,
  api_base:         import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  astra_logo:       `${base}logos/astra-logo.png`,
}
