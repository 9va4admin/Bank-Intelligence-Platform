const STORAGE_KEY = 'astra-cts-return-reasons'

const DEFAULTS = {
  'Drawee Bank': [
    'Account dormant — no txn >2 years',
    'Account frozen / NPA / closed',
    'Amount alteration / overwrite detected',
    'Insufficient funds',
    'KYC expired — refer to branch',
    'Legal / court hold on account',
    'No specimen on file — cannot verify',
    'Payee name discrepancy',
    'Payment stopped by drawer',
    'Positive Pay mismatch',
    'Post-dated cheque',
    'Signature mismatch confirmed',
  ],
  'Presenting Bank': [
    'CTS compliance failure',
    'Date invalid or stale cheque',
    'Duplicate instrument',
    'Endorsement irregular',
    'Instrument mutilated / damaged',
    'Words and figures differ',
  ],
}

export function getReturnReasons() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return DEFAULTS
}

export function saveReturnReasons(grouped) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(grouped))
}

export function getDefaultReturnReasons() {
  return DEFAULTS
}
