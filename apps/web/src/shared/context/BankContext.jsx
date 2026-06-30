import { createContext, useContext, useState } from 'react'

// ─── Demo bank profiles ───────────────────────────────────────────────────────
// In production these come from the decoded JWT / SAML assertion.
// NEVER derive bank identity from URL params or user input.

const DEMO_SB = {
  bankType:       'SB',
  bankId:         'saraswat-coop',
  bankIfsc:       'SRCB0000001',
  bankName:       'Saraswat Co-operative Bank',
  bankShortName:  'Saraswat',
  bankCity:       'Mumbai',
  sponsorBankId:  null,
  // SMBs sponsored by this SB — available only to SB users
  smbs: [
    { id: 'smb-mh-vasavi',  ifsc: 'VASB0000001', name: 'Vasavi Co-op Bank',       shortName: 'Vasavi',   city: 'Mumbai'    },
    { id: 'smb-mh-kjsb',    ifsc: 'KJSB0000001', name: 'Kalyan Janata Sah. Bank', shortName: 'KJSB',     city: 'Kalyan'    },
    { id: 'smb-gj-mucb',    ifsc: 'MUCB0000001', name: 'Mehsana Urban Co-op Bank', shortName: 'MUCB',    city: 'Mehsana'   },
    { id: 'smb-mh-janata',  ifsc: 'JNSB0000001', name: 'Janata Sah. Bank',        shortName: 'Janata',   city: 'Pune'      },
  ],
}

const DEMO_SMB = {
  bankType:       'SMB',
  bankId:         'smb-mh-vasavi',
  bankIfsc:       'VASB0000001',
  bankName:       'Vasavi Co-operative Bank',
  bankShortName:  'Vasavi',
  bankCity:       'Mumbai',
  sponsorBankId:  'saraswat-coop',
  sponsorBankName: 'Saraswat Co-operative Bank',
  sponsorBankIfsc: 'SRCB0000001',
  smbs: [], // SMB has no sub-members of its own
}

// ─── Context ──────────────────────────────────────────────────────────────────

const BankContext = createContext(null)

export function BankProvider({ children }) {
  // In production: resolve from JWT on mount, never allow toggle
  // DEMO ONLY: toggle between SB and SMB profiles
  const isDemoMode = import.meta.env.VITE_DEMO_MODE !== 'false'

  const [profile, setProfile] = useState(() => {
    if (!isDemoMode) return DEMO_SB // production always reads from JWT
    const saved = localStorage.getItem('astra-bank-type')
    return saved === 'SMB' ? DEMO_SMB : DEMO_SB
  })

  // SB can drill into a specific SMB — null means "show all / consolidated"
  const [selectedSmbId, setSelectedSmbId] = useState(null)

  function toggleBankType() {
    if (!isDemoMode) return
    const next = profile.bankType === 'SB' ? DEMO_SMB : DEMO_SB
    localStorage.setItem('astra-bank-type', next.bankType)
    setSelectedSmbId(null)
    setProfile(next)
  }

  // The effective SMB context when SB has drilled into one SMB
  const selectedSmb = profile.bankType === 'SB'
    ? profile.smbs.find(s => s.id === selectedSmbId) ?? null
    : null

  const value = {
    ...profile,
    isDemoMode,
    toggleBankType,
    // SMB drill-down (SB only)
    selectedSmbId,
    setSelectedSmbId,
    selectedSmb,
    // Convenience
    isSB:  profile.bankType === 'SB',
    isSMB: profile.bankType === 'SMB',
  }

  return <BankContext.Provider value={value}>{children}</BankContext.Provider>
}

export function useBankContext() {
  const ctx = useContext(BankContext)
  if (!ctx) throw new Error('useBankContext must be used inside <BankProvider>')
  return ctx
}
