/**
 * CTS Return Reasons — URRBCH Annexure D taxonomy (all codes per NPCI mandate).
 * Every return filed to NGCH must carry a URRBCH code.
 * customerFault: false = bank must NOT levy return charges (RBI/NPCI non-fault codes).
 *
 * Numbering follows Citibank/NPCI Annexure C for the 70–76 range.
 * (Central Bank of India CCP uses 69–75 for the same reasons.)
 *
 * Keep in sync with modules/cts/compliance/models.py ReturnReasonCode enum.
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
  // ── 01–05: Financial — drawee / refer to drawer ──────────────────────────
  { label: 'Insufficient funds',                                        code: '01', customerFault: true  },
  { label: 'Exceeds arrangement / credit limit',                        code: '02', customerFault: true  },
  { label: 'Effects not cleared in time',                               code: '03', customerFault: true  },
  { label: 'Refer to drawer',                                           code: '04', customerFault: true  },
  { label: 'Contact drawer and present again',                          code: '05', customerFault: true  },
  // ── 10–17: Drawer signature / authority ─────────────────────────────────
  { label: "Drawer's signature incomplete",                             code: '10', customerFault: true  },
  { label: "Drawer's signature illegible",                              code: '11', customerFault: true  },
  { label: "Drawer's signature differs from specimen",                  code: '12', customerFault: true  },
  { label: "Drawer's signature required",                               code: '13', customerFault: true  },
  { label: "Drawer's signature not as per mandate",                     code: '14', customerFault: true  },
  { label: 'Signature to operate account not received',                 code: '15', customerFault: true  },
  { label: 'Authority to operate account not received',                 code: '16', customerFault: true  },
  { label: 'Alteration requires authentication',                        code: '17', customerFault: true  },
  // ── 20–25: Payment stopped / withdrawal frozen ───────────────────────────
  { label: 'Payment stopped by drawer',                                 code: '20', customerFault: true  },
  { label: 'Payment stopped — attachment order',                        code: '21', customerFault: true  },
  { label: 'Payment stopped — court order',                             code: '22', customerFault: true  },
  { label: 'Withdrawal stopped — drawer deceased',                      code: '23', customerFault: true  },
  { label: 'Withdrawal stopped — drawer of unsound mind',               code: '24', customerFault: true  },
  { label: 'Withdrawal stopped — insolvency',                           code: '25', customerFault: true  },
  // ── 30–42: Date / amount / presentation / endorsement ───────────────────
  { label: 'Post-dated cheque',                                         code: '30', customerFault: false },
  { label: 'Stale cheque — validity period expired',                    code: '31', customerFault: false },
  { label: 'Undated cheque',                                            code: '32', customerFault: false },
  { label: 'Instrument mutilated / requires bank guarantee',            code: '33', customerFault: false },
  { label: 'Amount in words and figures differ',                        code: '34', customerFault: true  },
  { label: 'Clearing House stamp / date required',                      code: '35', customerFault: false },
  { label: 'Wrongly delivered / not drawn on us',                       code: '36', customerFault: false },
  { label: 'Present instrument in proper zone',                         code: '37', customerFault: false },
  { label: 'Instrument contains extraneous matter',                     code: '38', customerFault: false },
  { label: 'Image not clear — re-scan required',                        code: '39', customerFault: false },
  { label: 'Present with document',                                     code: '40', customerFault: false },
  { label: 'Item listed twice',                                         code: '41', customerFault: false },
  { label: 'Paper / instrument not received',                           code: '42', customerFault: false },
  // ── 50–55: Account status ───────────────────────────────────────────────
  { label: 'Account closed',                                            code: '50', customerFault: true  },
  { label: 'Account transferred to another branch / bank',              code: '51', customerFault: true  },
  { label: 'No such account',                                           code: '52', customerFault: true  },
  { label: 'Title of account required',                                 code: '53', customerFault: true  },
  { label: 'Title of account incorrect',                                code: '54', customerFault: true  },
  { label: 'Account frozen (regulatory / legal hold)',                  code: '55', customerFault: false },
  // ── 60–68: Crossing / endorsement ───────────────────────────────────────
  { label: 'Instrument crossed to two banks',                           code: '60', customerFault: false },
  { label: 'Crossing stamp not cancelled by collecting bank',           code: '61', customerFault: false },
  { label: 'Clearing stamp not cancelled by collecting bank',           code: '62', customerFault: false },
  { label: 'Instrument specially crossed to another bank',              code: '63', customerFault: false },
  { label: 'Protective crossing applied incorrectly',                   code: '64', customerFault: true  },
  { label: 'Protective crossing illegible',                             code: '65', customerFault: true  },
  { label: "Payee's endorsement required",                              code: '66', customerFault: true  },
  { label: "Payee's endorsement irregular — collecting bank to confirm",code: '67', customerFault: false },
  { label: 'Endorsement by thumb impression — Magistrate attestation required', code: '68', customerFault: false },
  // ── 70–76: Advice / SMB settlement ──────────────────────────────────────
  // Citibank/NPCI numbering; CBI uses 69–75 for the same range
  { label: 'Advice not received',                                       code: '70', customerFault: false },
  { label: 'Amount / name differs on advice',                           code: '71', customerFault: false },
  { label: "Drawee bank's funds with sponsor bank insufficient",        code: '72', customerFault: false },
  { label: "Payee's separate discharge to bank required",               code: '73', customerFault: false },
  { label: 'Not payable till 1st proximo',                              code: '74', customerFault: false },
  { label: 'Pay order / cheque requires counter-signature',             code: '75', customerFault: false },
  { label: 'Required information not legible or correct',               code: '76', customerFault: false },
  // ── 80–88: Technical / connectivity / fraud ──────────────────────────────
  { label: "Bank's certificate ambiguous / incomplete / required",      code: '80', customerFault: false },
  { label: 'Draft lost by issuing office',                              code: '81', customerFault: false },
  { label: 'Bank / Branch blocked',                                     code: '82', customerFault: false },
  { label: 'Digital Certificate Validation failure',                    code: '83', customerFault: false },
  { label: 'Other connectivity failure',                                code: '84', customerFault: false },
  { label: 'CTS-2010 alteration detected in non-date field',           code: '85', customerFault: true  },
  { label: 'Forged / fake instrument',                                  code: '86', customerFault: true  },
  { label: "Payee's account credited — stamp required",                 code: '87', customerFault: false },
  { label: 'Other reason (not listed above)',                           code: '88', customerFault: true  },
  // ── 92: Administrative ───────────────────────────────────────────────────
  { label: 'Bank exclude',                                              code: '92', customerFault: false },
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
  'Financial — Drawee / Refer to Drawer': URRBCH_REASONS
    .filter(r => ['01','02','03','04','05'].includes(r.code))
    .map(r => r.label),
  'Drawer Signature / Authority': URRBCH_REASONS
    .filter(r => ['10','11','12','13','14','15','16','17'].includes(r.code))
    .map(r => r.label),
  'Payment Stopped / Withdrawal Frozen': URRBCH_REASONS
    .filter(r => ['20','21','22','23','24','25'].includes(r.code))
    .map(r => r.label),
  'Date / Amount / Presentation / Endorsement': URRBCH_REASONS
    .filter(r => ['30','31','32','33','34','35','36','37','38','39','40','41','42'].includes(r.code))
    .map(r => r.label),
  'Account Status': URRBCH_REASONS
    .filter(r => ['50','51','52','53','54','55'].includes(r.code))
    .map(r => r.label),
  'Crossing / Endorsement': URRBCH_REASONS
    .filter(r => ['60','61','62','63','64','65','66','67','68'].includes(r.code))
    .map(r => r.label),
  'Advice / SMB Settlement': URRBCH_REASONS
    .filter(r => ['70','71','72','73','74','75','76'].includes(r.code))
    .map(r => r.label),
  'Technical / Connectivity / Fraud': URRBCH_REASONS
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
