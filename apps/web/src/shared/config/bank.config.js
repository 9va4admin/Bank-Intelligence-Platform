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
  'federal-bank': {
    bank_id:         'federal-bank',
    bank_name:       'Federal Bank Limited',
    bank_short_name: 'Federal',
    tagline:         'Your Perfect Banking Partner.',
    bank_logo:       'federal-bank-logo.png',
    primary_hex:     '#C62828',
    ifsc_prefix:     'FDRL',
    clearing_zone:   'SOUTH',
    // 25 UCB sub-members sponsored by Federal Bank for CTS clearing
    // Total combined outward volume: ~1,000 cheques/day
    smbs: [
      // Kerala — 12 banks (~600 chqs/day combined)
      { id: 'smb-kl-tsucb',  ifsc: 'TSUB0000001', name: 'Thrissur UCB',             shortName: 'Thrissur UCB',    city: 'Thrissur',          state: 'KL', daily_avg: 100 },
      { id: 'smb-kl-eklucb', ifsc: 'EKLB0000001', name: 'Ernakulam UCB',            shortName: 'Ernakulam UCB',   city: 'Kochi',             state: 'KL', daily_avg: 100 },
      { id: 'smb-kl-mlbcb',  ifsc: 'MLCB0000001', name: 'Malabar Co-operative Bank',shortName: 'Malabar Co-op',   city: 'Kozhikode',         state: 'KL', daily_avg: 80  },
      { id: 'smb-kl-ksucb',  ifsc: 'KSUB0000001', name: 'Kerala State UCB',         shortName: 'Kerala State UCB',city: 'Thiruvananthapuram', state: 'KL', daily_avg: 60  },
      { id: 'smb-kl-ktmucb', ifsc: 'KTMB0000001', name: 'Kottayam UCB',             shortName: 'Kottayam UCB',    city: 'Kottayam',          state: 'KL', daily_avg: 60  },
      { id: 'smb-kl-plkucb', ifsc: 'PLKB0000001', name: 'Palakkad UCB',             shortName: 'Palakkad UCB',    city: 'Palakkad',          state: 'KL', daily_avg: 40  },
      { id: 'smb-kl-knrucb', ifsc: 'KNRB0000001', name: 'Kannur District UCB',      shortName: 'Kannur UCB',      city: 'Kannur',            state: 'KL', daily_avg: 40  },
      { id: 'smb-kl-alpucb', ifsc: 'ALPB0000001', name: 'Alappuzha UCB',            shortName: 'Alappuzha UCB',   city: 'Alappuzha',         state: 'KL', daily_avg: 40  },
      { id: 'smb-kl-kollam', ifsc: 'KOLB0000001', name: 'Kollam UCB',               shortName: 'Kollam UCB',      city: 'Kollam',            state: 'KL', daily_avg: 30  },
      { id: 'smb-kl-idkucb', ifsc: 'IDKB0000001', name: 'Idukki UCB',               shortName: 'Idukki UCB',      city: 'Thodupuzha',        state: 'KL', daily_avg: 30  },
      { id: 'smb-kl-wndcb',  ifsc: 'WNDB0000001', name: 'Wayanad UCB',              shortName: 'Wayanad UCB',     city: 'Kalpetta',          state: 'KL', daily_avg: 20  },
      { id: 'smb-kl-trssur', ifsc: 'TRSB0000001', name: 'Tirur UCB',                shortName: 'Tirur UCB',       city: 'Malappuram',        state: 'KL', daily_avg: 20  },
      // Tamil Nadu — 5 banks (~140 chqs/day combined)
      { id: 'smb-tn-cbucb',  ifsc: 'CBUB0000001', name: 'Coimbatore City UCB',      shortName: 'Coimbatore UCB',  city: 'Coimbatore',        state: 'TN', daily_avg: 40  },
      { id: 'smb-tn-chucb',  ifsc: 'CHUB0000001', name: 'Chennai Urban Co-op Bank', shortName: 'Chennai UCB',     city: 'Chennai',           state: 'TN', daily_avg: 40  },
      { id: 'smb-tn-mduucb', ifsc: 'MDUB0000001', name: 'Madurai UCB',              shortName: 'Madurai UCB',     city: 'Madurai',           state: 'TN', daily_avg: 30  },
      { id: 'smb-tn-slmucb', ifsc: 'SLMB0000001', name: 'Salem UCB',                shortName: 'Salem UCB',       city: 'Salem',             state: 'TN', daily_avg: 20  },
      { id: 'smb-tn-tnlucb', ifsc: 'TNLB0000001', name: 'Tirunelveli UCB',          shortName: 'Tirunelveli UCB', city: 'Tirunelveli',       state: 'TN', daily_avg: 20  },
      // Karnataka — 4 banks (~110 chqs/day combined)
      { id: 'smb-ka-mgucb',  ifsc: 'MGUB0000001', name: 'Mangaluru UCB',            shortName: 'Mangaluru UCB',   city: 'Mangaluru',         state: 'KA', daily_avg: 50  },
      { id: 'smb-ka-mysucb', ifsc: 'MYSB0000001', name: 'Mysuru UCB',               shortName: 'Mysuru UCB',      city: 'Mysuru',            state: 'KA', daily_avg: 30  },
      { id: 'smb-ka-hblucb', ifsc: 'HBLB0000001', name: 'Hubballi UCB',             shortName: 'Hubballi UCB',    city: 'Hubballi',          state: 'KA', daily_avg: 20  },
      { id: 'smb-ka-udpucb', ifsc: 'UDPB0000001', name: 'Udupi UCB',                shortName: 'Udupi UCB',       city: 'Udupi',             state: 'KA', daily_avg: 20  },
      // Maharashtra — 2 banks (~60 chqs/day combined)
      { id: 'smb-mh-kmucb',  ifsc: 'KMUB0000001', name: 'Kerala Merchants UCB',     shortName: 'Kerala Merchants',city: 'Mumbai',            state: 'MH', daily_avg: 40  },
      { id: 'smb-mh-pneucb', ifsc: 'PNEB0000001', name: 'Pune UCB',                 shortName: 'Pune UCB',        city: 'Pune',              state: 'MH', daily_avg: 20  },
      // Andhra Pradesh — 2 banks (~40 chqs/day combined)
      { id: 'smb-ap-vjwucb', ifsc: 'VJWB0000001', name: 'Vijayawada UCB',           shortName: 'Vijayawada UCB',  city: 'Vijayawada',        state: 'AP', daily_avg: 20  },
      { id: 'smb-ap-vsaucb', ifsc: 'VSAB0000001', name: 'Visakhapatnam UCB',        shortName: 'Vizag UCB',       city: 'Visakhapatnam',     state: 'AP', daily_avg: 20  },
    ],
  },
}

const bankId        = import.meta.env.VITE_BANK_ID          ?? 'saraswat-coop'
const bankMode      = import.meta.env.VITE_BANK_MODE         ?? 'SB_SMB'
// DEMO  — pre-seeded mock data, no real services required
// POC   — full pipeline, real AI/DB/queues, folder-based I/O instead of scanner+NGCH
// PROD  — everything live: physical scanner, NGCH, on-prem vLLM, CBS
const deploymentMode = import.meta.env.VITE_DEPLOYMENT_MODE  ?? 'POC'

// BASE_URL already includes a trailing slash (e.g. '/Bank-Intelligence-Platform/')
// so we join without a leading slash on the asset path.
const base   = import.meta.env.BASE_URL ?? '/'
const preset = BANK_PRESETS[bankId] ?? BANK_PRESETS['saraswat-coop']


export const BANK_CONFIG = {
  ...preset,
  bank_logo:        `${base}logos/${preset.bank_logo.split('/').pop()}`,
  bank_mode:        bankMode,
  deployment_mode:  deploymentMode,
  api_base:         import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  astra_logo:       `${base}logos/astra-logo.png`,
}
