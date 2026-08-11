import { createContext, useContext } from 'react'
import { BANK_CONFIG } from '../config/bank.config'

export const ROLE_PERMISSIONS = {
  ops_manager: ['cts:view_queue','cts:submit_decision','cts:view_analytics',
                'config:layer3:submit','audit:read','smb:view_ledger',
                'pii:view','user:manage','smb:register','smb:vault_sync',
                'smb:config_change','config:layer2:change','admin:console',
                'cts:view_hold_queue','cts:add_hold_note','login_log:read'],
}

const BankContext = createContext(null)

const PROFILE = {
  bankType: 'SB',
  bankId: BANK_CONFIG.bank_id,
  bankIfsc: BANK_CONFIG.ifsc_prefix + '0000001',
  bankName: BANK_CONFIG.bank_name,
  bankShortName: BANK_CONFIG.bank_short_name,
  bankCity: 'Mangalore',
  sponsorBankId: null,
  userRole: 'ops_manager',
  userName: 'Demo User',
  smbs: [],
  isDemoMode: true,
}

export function BankProvider({ children }) {
  const perms = ROLE_PERMISSIONS['ops_manager']
  const value = {
    ...PROFILE,
    isSB: true,
    isSMB: false,
    selectedSmbId: null,
    setSelectedSmbId: () => {},
    selectedSmb: null,
    userPermissions: perms,
    hasPermission: (p) => perms.includes(p),
    toggleBankType: () => {},
  }
  return <BankContext.Provider value={value}>{children}</BankContext.Provider>
}

export function useBankContext() {
  const ctx = useContext(BankContext)
  if (!ctx) throw new Error('useBankContext must be used inside <BankProvider>')
  return ctx
}
