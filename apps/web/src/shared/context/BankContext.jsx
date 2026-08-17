import { createContext, useContext, useState } from 'react'
import { useAuthOptional } from './AuthContext'
import { BANK_CONFIG } from '../config/bank.config'

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
                       'config:layer3:submit', 'audit:read', 'smb:view_ledger',
                       'ai:model_metrics', 'login_log:read'],
  bank_it_admin:      ['admin:console', 'config:layer3:approve', 'config:layer2:change',
                       'audit:read', 'smb:register', 'smb:view_ledger', 'smb:vault_sync',
                       'smb:config_change', 'user:manage', 'ai:model_metrics', 'login_log:read'],
  compliance_officer: ['audit:read', 'pii:view', 'cts:view_analytics',
                       'ej:view_dashboard', 'smb:view_ledger', 'login_log:read'],
  rbi_examiner:       ['audit:read', 'login_log:read'],
  ml_engineer:        ['ai:model_metrics', 'ai:mlflow_access'],
  smb_it_admin:       ['smb:register', 'smb:view_ledger', 'smb:vault_sync',
                       'smb:config_change', 'audit:read', 'login_log:read'],
  branch_manager:     ['cts:view_hold_queue', 'cts:add_hold_note', 'login_log:read'],
  smb_admin:          ['cts:view_queue', 'cts:submit_decision', 'smb:view_ledger',
                       'audit:read', 'user:manage', 'login_log:read'],
  smb_editor:         ['cts:view_queue', 'cts:submit_decision', 'smb:view_ledger', 'login_log:read'],
  smb_viewer:         ['cts:view_queue', 'smb:view_ledger', 'login_log:read'],
}

export function roleHasPermission(role, permission) {
  return (ROLE_PERMISSIONS[role] ?? []).includes(permission)
}

// ─── Config-driven SB profile (follows bank.config.js / VITE_BANK_ID) ────────
// In production this is superseded by the JWT claim. For demo/POC the config
// determines which bank's identity to show so that any bank preset works without
// touching this file. smbs comes from bank.config.js preset automatically.
const CONFIG_PROFILE = {
  bankType:      'SB',
  bankId:        BANK_CONFIG.bank_id,
  bankIfsc:      `${BANK_CONFIG.ifsc_prefix}0000001`,
  bankName:      BANK_CONFIG.bank_name,
  bankShortName: BANK_CONFIG.bank_short_name,
  bankCity:      '',
  sponsorBankId: null,
  userRole:      'ops_manager',
  userName:      'Demo User',
  smbs:          BANK_CONFIG.smbs ?? [],
}

// ─── Config-driven demo toggle profiles ──────────────────────────────────────
// Derived entirely from bank.config.js — adding a new bank never requires
// touching this file. Just add the preset (with smbs[]) to bank.config.js.

// SMB toggle: the first SMB from the bank's configured smbs list.
// If the bank has no smbs configured, the SMB step is skipped in the toggle.
const _firstSmb = BANK_CONFIG.smbs?.[0] ?? null
const DEMO_SMB_FOR_BANK = _firstSmb
  ? {
      bankType:        'SMB',
      bankId:          _firstSmb.id,
      bankIfsc:        _firstSmb.ifsc,
      bankName:        _firstSmb.name,
      bankShortName:   _firstSmb.shortName ?? _firstSmb.name,
      bankCity:        _firstSmb.city ?? '',
      sponsorBankId:   BANK_CONFIG.bank_id,
      sponsorBankName: BANK_CONFIG.bank_name,
      sponsorBankIfsc: `${BANK_CONFIG.ifsc_prefix}0000001`,
      userRole:        'smb_editor',
      smbs:            [],
    }
  : null

// Branch-manager toggle: SB identity, role overridden to branch_manager.
const DEMO_BRANCH_FOR_BANK = {
  bankType:      'SB',
  bankId:        BANK_CONFIG.bank_id,
  bankIfsc:      `${BANK_CONFIG.ifsc_prefix}0000001`,
  bankName:      BANK_CONFIG.bank_name,
  bankShortName: BANK_CONFIG.bank_short_name,
  bankCity:      '',
  sponsorBankId: null,
  userRole:      'branch_manager',
  branchCode:    `${BANK_CONFIG.ifsc_prefix}-MAIN-001`,
  userName:      'Demo Branch Manager',
  smbs:          [],
}

// ─── Context ──────────────────────────────────────────────────────────────────

const BankContext = createContext(null)

export function BankProvider({ children }) {
  // In production: resolve from JWT on mount, never allow toggle
  // DEMO ONLY: toggle between SB and SMB profiles
  const isDemoMode = import.meta.env.VITE_DEMO_MODE !== 'false'

  const [profile, setProfile] = useState(() => {
    if (!isDemoMode) return CONFIG_PROFILE // non-demo: bank identity from bank.config.js until JWT
    const saved = localStorage.getItem('astra-bank-type')
    if (saved === 'SMB' && DEMO_SMB_FOR_BANK) return DEMO_SMB_FOR_BANK
    if (saved === 'BRANCH') return DEMO_BRANCH_FOR_BANK
    return CONFIG_PROFILE  // base SB profile from bank.config.js (not hardcoded)
  })

  // SB can drill into a specific SMB — null means "show all / consolidated"
  const [selectedSmbId, setSelectedSmbId] = useState(null)

  function toggleBankType() {
    if (!isDemoMode) return
    // Cycle: SB → SMB (if bank has smbs) → BRANCH → SB
    let next, key
    if (profile.userRole === 'ops_manager') {
      if (DEMO_SMB_FOR_BANK) { next = DEMO_SMB_FOR_BANK;    key = 'SMB'    }
      else                   { next = DEMO_BRANCH_FOR_BANK; key = 'BRANCH' }
    } else if (profile.userRole === 'smb_editor') {
      next = DEMO_BRANCH_FOR_BANK; key = 'BRANCH'
    } else {
      next = CONFIG_PROFILE; key = 'SB'
    }
    localStorage.setItem('astra-bank-type', key)
    setSelectedSmbId(null)
    setProfile(next)
  }

  // When a real ASTRA session exists it drives identity (role, bank, type).
  // With no session (demo / standalone tests) fall back to the demo profile + toggle.
  const auth = useAuthOptional()
  const sessionUser = auth && auth.status === 'authenticated' ? auth.user : null
  const active = sessionUser
    ? {
        // SMB session: overlay the config-driven SMB profile so sponsor name is correct.
        // SB session: use CONFIG_PROFILE so smbs list matches the deployed bank.
        ...(sessionUser.bank_type === 'SMB' ? DEMO_SMB_FOR_BANK ?? CONFIG_PROFILE : CONFIG_PROFILE),
        bankType:   sessionUser.bank_type  || 'SB',
        bankId:     sessionUser.bank_id,
        userRole:   sessionUser.role,
        userName:   sessionUser.username,
        branchCode: sessionUser.branch_code ?? null,  // branch_manager ABAC scope from JWT
      }
    : profile

  // The effective SMB context when SB has drilled into one SMB
  const selectedSmb = active.bankType === 'SB'
    ? active.smbs.find(s => s.id === selectedSmbId) ?? null
    : null

  const userPerms = ROLE_PERMISSIONS[active.userRole] ?? []

  // Demo mode bypasses permission gating so all nav items are visible during
  // development. In production (VITE_DEMO_MODE=false) only the role's real
  // permissions apply.
  const hasPermission = isDemoMode
    ? () => true
    : (perm) => userPerms.includes(perm)

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
    // Deployment mode — from VITE_BANK_MODE env var, not per-user
    bankMode: BANK_CONFIG.bank_mode,  // 'SB_SMB' | 'SB_ONLY' | 'SMB_ONLY'
    // Deployment mode — controls live vs stubbed integrations
    deploymentMode: BANK_CONFIG.deployment_mode,  // 'DEMO' | 'POC' | 'PROD'
    isDemo: BANK_CONFIG.deployment_mode === 'DEMO',
    isPOC:  BANK_CONFIG.deployment_mode === 'POC',
    isProd: BANK_CONFIG.deployment_mode === 'PROD',
    // Role-based access
    userPermissions: userPerms,
    hasPermission,
  }

  return <BankContext.Provider value={value}>{children}</BankContext.Provider>
}

export function useBankContext() {
  const ctx = useContext(BankContext)
  if (!ctx) throw new Error('useBankContext must be used inside <BankProvider>')
  return ctx
}
