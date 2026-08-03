import { createContext, useContext, useState } from 'react'
import { useAuthOptional } from './AuthContext'

// ─── Demo bank profiles ───────────────────────────────────────────────────────
// In production these come from the decoded JWT / SAML assertion.
// NEVER derive bank identity from URL params or user input.

// Role → permission matrix (mirrors shared/auth/rbac.py _ROLE_PERMISSIONS)
// Used by AppShell nav filtering — each nav item declares which roles may see it.
export const ROLE_PERMISSIONS = {
  ops_reviewer:       ['cts:view_queue', 'cts:submit_decision', 'login_log:read'],
  fraud_analyst:      ['cts:view_analytics', 'ej:view_dashboard', 'ej:view_disputes', 'login_log:read'],
  ops_manager:        ['cts:view_queue', 'cts:submit_decision', 'cts:view_analytics',
                       'ej:view_dashboard', 'ej:view_disputes', 'pii:view',
                       'config:layer3:submit', 'audit:read', 'smb:view_ledger', 'login_log:read'],
  bank_it_admin:      ['admin:console', 'config:layer3:approve', 'config:layer2:change',
                       'audit:read', 'smb:register', 'smb:view_ledger', 'smb:vault_sync',
                       'smb:config_change', 'user:manage', 'login_log:read'],
  compliance_officer: ['audit:read', 'pii:view', 'cts:view_analytics',
                       'ej:view_dashboard', 'smb:view_ledger', 'login_log:read'],
  rbi_examiner:       ['audit:read', 'login_log:read'],
  ml_engineer:        ['ai:model_metrics', 'ai:mlflow_access'],
  smb_it_admin:       ['smb:register', 'smb:view_ledger', 'smb:vault_sync',
                       'smb:config_change', 'audit:read', 'login_log:read'],
  smb_admin:          ['cts:view_queue', 'cts:submit_decision', 'smb:view_ledger',
                       'audit:read', 'user:manage', 'login_log:read'],
  smb_editor:         ['cts:view_queue', 'cts:submit_decision', 'smb:view_ledger', 'login_log:read'],
  smb_viewer:         ['cts:view_queue', 'smb:view_ledger', 'login_log:read'],
}

export function roleHasPermission(role, permission) {
  return (ROLE_PERMISSIONS[role] ?? []).includes(permission)
}

const DEMO_SB = {
  bankType:       'SB',
  bankId:         'saraswat-coop',
  bankIfsc:       'SRCB0000001',
  bankName:       'Saraswat Co-operative Bank',
  bankShortName:  'Saraswat',
  bankCity:       'Mumbai',
  sponsorBankId:  null,
  userRole:       'ops_manager', // demo: SB user is ops_manager
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
  userRole:       'smb_editor', // demo: SMB user is smb_editor
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

  // When a real ASTRA session exists it drives identity (role, bank, type).
  // With no session (demo / standalone tests) fall back to the demo profile + toggle.
  const auth = useAuthOptional()
  const sessionUser = auth && auth.status === 'authenticated' ? auth.user : null
  const active = sessionUser
    ? {
        ...(sessionUser.bank_type === 'SMB' ? DEMO_SMB : DEMO_SB),
        bankType: sessionUser.bank_type || 'SB',
        bankId: sessionUser.bank_id,
        userRole: sessionUser.role,
        userName: sessionUser.username,
      }
    : profile

  // The effective SMB context when SB has drilled into one SMB
  const selectedSmb = active.bankType === 'SB'
    ? active.smbs.find(s => s.id === selectedSmbId) ?? null
    : null

  const userPerms = ROLE_PERMISSIONS[active.userRole] ?? []

  const value = {
    ...active,
    isDemoMode,
    toggleBankType,
    // SMB drill-down (SB only)
    selectedSmbId,
    setSelectedSmbId,
    selectedSmb,
    // Convenience
    isSB:  active.bankType === 'SB',
    isSMB: active.bankType === 'SMB',
    // Role-based access
    userPermissions: userPerms,
    hasPermission: (perm) => userPerms.includes(perm),
  }

  return <BankContext.Provider value={value}>{children}</BankContext.Provider>
}

export function useBankContext() {
  const ctx = useContext(BankContext)
  if (!ctx) throw new Error('useBankContext must be used inside <BankProvider>')
  return ctx
}
