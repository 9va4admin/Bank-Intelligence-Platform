/**
 * CTS Return Reasons — URRBCH taxonomy (all 92 codes per NPCI mandate).
 * Every return filed to NGCH must carry a URRBCH code.
 * customerFault: false = bank must NOT levy return charges (RBI/NPCI non-fault codes).
 */
const STORAGE_KEY = 'astra-cts-return-reasons'

/**
 * Structured return reasons with URRBCH codes.
 * Each entry: { label, code, customerFault }
 *
 * label         — human-readable text shown in the dropdown
 * code          — URRBCH code (2-digit string) filed to NGCH
 * customerFault — false = RBI rule: no return charges may be levied
 */
export const URRBCH_REASONS = [
  // ── Financial / account status ──────────────────────────────────────────
  { label: 'Insufficient funds',                      code: '01', customerFault: true  },
  { label: 'Exceeds arrangement / credit limit',      code: '02', customerFault: true  },
  { label: 'Effects not cleared in time',             code: '03', customerFault: true  },
  { label: 'Full cover not received',                 code: '04', customerFault: true  },
  { label: 'Payment stopped by drawer',               code: '05', customerFault: true  },
  { label: 'Payment countermanded by drawer',         code: '06', customerFault: true  },
  { label: 'Drawer deceased',                         code: '07', customerFault: true  },
  { label: 'Insolvency / liquidation',                code: '08', customerFault: true  },
  { label: 'Account transferred to another branch',   code: '09', customerFault: true  },
  { label: 'Account closed',                          code: '10', customerFault: true  },
  { label: 'Account does not exist',                  code: '11', customerFault: true  },
  { label: 'Signature mismatch confirmed',            code: '12', customerFault: true  },
  { label: 'Signature / authentication required',     code: '13', customerFault: true  },
  { label: 'Duplicate item — listed twice',           code: '14', customerFault: false },
  { label: 'Instrument mutilated / damaged',          code: '15', customerFault: true  },
  { label: 'Instrument incomplete',                   code: '16', customerFault: true  },
  { label: 'Alteration requires authentication',      code: '17', customerFault: true  },
  { label: 'Instrument date invalid',                 code: '18', customerFault: true  },
  { label: 'Not arranged for',                        code: '19', customerFault: true  },
  // ── Special instructions / SMB ──────────────────────────────────────────
  { label: 'Stop payment instruction active',         code: '20', customerFault: true  },
  { label: 'Any one or survivor — one deceased',      code: '21', customerFault: true  },
  { label: 'Sole operator deceased',                  code: '22', customerFault: true  },
  { label: 'Liquidator not appointed',                code: '23', customerFault: true  },
  { label: 'Endorsement irregular or missing',        code: '24', customerFault: true  },
  { label: 'SMB sponsor funds insufficient',          code: '25', customerFault: false },
  { label: 'Bank insolvency',                         code: '26', customerFault: false },
  // ── Date / amount / crossing ────────────────────────────────────────────
  { label: 'Post-dated cheque',                       code: '30', customerFault: false },
  { label: 'Stale cheque — validity period expired',  code: '31', customerFault: false },
  { label: 'Undated cheque',                          code: '32', customerFault: false },
  { label: 'Crossed cheque — presented for cash',     code: '33', customerFault: false },
  { label: 'Amount in words and figures differ',      code: '34', customerFault: true  },
  { label: 'Crossing irregular',                      code: '35', customerFault: false },
  { label: 'Open cheque — bank cannot accept',        code: '36', customerFault: false },
  { label: 'Present instrument in proper zone',       code: '37', customerFault: false },
  { label: 'Drawee bank on holiday',                  code: '38', customerFault: false },
  { label: 'Image not clear — re-scan required',      code: '39', customerFault: false },
  { label: 'Presenting bank endorsement missing',     code: '40', customerFault: false },
  { label: "Payee's endorsement required",            code: '41', customerFault: false },
  { label: "Payee's endorsement irregular",           code: '42', customerFault: false },
  // ── Account status ──────────────────────────────────────────────────────
  { label: 'Account frozen (regulatory / legal hold)', code: '55', customerFault: false },
  // ── Technical / routing ─────────────────────────────────────────────────
  { label: 'Clearing zone not served by drawee bank', code: '60', customerFault: false },
  { label: 'Instrument left unpaid — technical',      code: '61', customerFault: false },
  { label: 'Drawer bank not on CBLS',                 code: '62', customerFault: false },
  { label: 'Non-CTS cheque presented in CTS zone',    code: '63', customerFault: false },
  { label: 'MICR band defective — re-scan',           code: '67', customerFault: false },
  { label: 'Digital certificate validation failure',  code: '68', customerFault: false },
  { label: 'Bank not on CBS',                         code: '69', customerFault: false },
  { label: 'Drawee bank offline',                     code: '70', customerFault: false },
  { label: 'Routing incorrect',                       code: '71', customerFault: false },
  { label: 'Mandate expired',                         code: '72', customerFault: false },
  { label: 'Mandate cancelled',                       code: '73', customerFault: false },
  { label: 'Mandate amount exceeded',                 code: '74', customerFault: false },
  { label: 'Mandate revoked',                         code: '75', customerFault: false },
  // ── Security / fraud ────────────────────────────────────────────────────
  { label: 'Technical reason 80',                     code: '80', customerFault: false },
  { label: 'Technical reason 81',                     code: '81', customerFault: false },
  { label: 'Technical reason 82',                     code: '82', customerFault: false },
  { label: 'Technical reason 83',                     code: '83', customerFault: false },
  { label: 'Technical reason 84',                     code: '84', customerFault: false },
  { label: 'CTS-2010 alteration in non-date field',   code: '85', customerFault: true  },
  { label: 'Forged instrument',                       code: '86', customerFault: true  },
  { label: 'Spurious instrument',                     code: '87', customerFault: false },
  { label: 'Fraud suspected',                         code: '88', customerFault: false },
  { label: 'Others — reason not listed above',        code: '92', customerFault: false },
]

/** Map from URRBCH code string to entry (for fast lookup by code). */
export const URRBCH_BY_CODE = Object.fromEntries(
  URRBCH_REASONS.map(r => [r.code, r])
)

/**
 * Grouped map for the dropdown — backward-compatible with old `getReturnReasons()`.
 * Keys are group names, values are arrays of label strings.
 */
const DEFAULTS_GROUPED = {
  'Drawee Bank — Financial': URRBCH_REASONS
    .filter(r => ['01','02','03','04','05','06','07','08','09','10','11','12','13','14','15','16','17','18','19'].includes(r.code))
    .map(r => r.label),
  'Drawee Bank — Special Instructions': URRBCH_REASONS
    .filter(r => ['20','21','22','23','24','25','26'].includes(r.code))
    .map(r => r.label),
  'Date / Amount / Crossing': URRBCH_REASONS
    .filter(r => ['30','31','32','33','34','35','36','37','38','39','40','41','42'].includes(r.code))
    .map(r => r.label),
  'Account Status': URRBCH_REASONS
    .filter(r => ['55'].includes(r.code))
    .map(r => r.label),
  'Technical / Routing': URRBCH_REASONS
    .filter(r => ['60','61','62','63','67','68','69','70','71','72','73','74','75'].includes(r.code))
    .map(r => r.label),
  'Security / Fraud': URRBCH_REASONS
    .filter(r => ['80','81','82','83','84','85','86','87','88','92'].includes(r.code))
    .map(r => r.label),
}

/** Returns grouped map { groupName: [labelString] } — used by ReviewPanel dropdown. */
export function getReturnReasons() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored) return JSON.parse(stored)
  } catch { /* ignore */ }
  return DEFAULTS_GROUPED
}

export function saveReturnReasons(grouped) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(grouped))
}

export function getDefaultReturnReasons() {
  return DEFAULTS_GROUPED
}

/** Look up the URRBCH entry for a given human-readable label. */
export function getReasonByLabel(label) {
  return URRBCH_REASONS.find(r => r.label === label) ?? null
}
