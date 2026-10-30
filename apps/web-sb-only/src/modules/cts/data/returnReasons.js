import { msg } from '../../../shared/messages'
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
  { label: msg('UI_RETURNREASONS_INSUFFICIENT_FUNDS_2'),                                        code: '01', customerFault: true  },
  { label: msg('UI_RETURNREASONS_EXCEEDS_ARRANGEMENT_CREDIT_LIMIT_2'),                        code: '02', customerFault: true  },
  { label: msg('UI_RETURNREASONS_EFFECTS_NOT_CLEARED_IN_TIME_2'),                               code: '03', customerFault: true  },
  { label: msg('UI_RETURNREASONS_REFER_TO_DRAWER_2'),                                           code: '04', customerFault: true  },
  { label: msg('UI_RETURNREASONS_CONTACT_DRAWER_AND_PRESENT_AGAIN_2'),                          code: '05', customerFault: true  },
  // ── 10–17: Drawer signature / authority ─────────────────────────────────
  { label: msg('UI_RETURNREASONS_DRAWER_S_SIGNATURE_INCOMPLETE_2'),                             code: '10', customerFault: true  },
  { label: msg('UI_RETURNREASONS_DRAWER_S_SIGNATURE_ILLEGIBLE_2'),                              code: '11', customerFault: true  },
  { label: msg('UI_RETURNREASONS_DRAWER_S_SIGNATURE_DIFFERS_FROM_2'),                  code: '12', customerFault: true  },
  { label: msg('UI_RETURNREASONS_DRAWER_S_SIGNATURE_REQUIRED_2'),                               code: '13', customerFault: true  },
  { label: msg('UI_RETURNREASONS_DRAWER_S_SIGNATURE_NOT_AS_2'),                     code: '14', customerFault: true  },
  { label: msg('UI_RETURNREASONS_SIGNATURE_TO_OPERATE_ACCOUNT_NOT_2'),                 code: '15', customerFault: true  },
  { label: msg('UI_RETURNREASONS_AUTHORITY_TO_OPERATE_ACCOUNT_NOT_2'),                 code: '16', customerFault: true  },
  { label: msg('UI_RETURNREASONS_ALTERATION_REQUIRES_AUTHENTICATION_2'),                        code: '17', customerFault: true  },
  // ── 20–25: Payment stopped / withdrawal frozen ───────────────────────────
  { label: msg('UI_RETURNREASONS_PAYMENT_STOPPED_BY_DRAWER_2'),                                 code: '20', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PAYMENT_STOPPED_ATTACHMENT_ORDER_2'),                        code: '21', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PAYMENT_STOPPED_COURT_ORDER_2'),                             code: '22', customerFault: true  },
  { label: msg('UI_RETURNREASONS_WITHDRAWAL_STOPPED_DRAWER_DECEASED_2'),                      code: '23', customerFault: true  },
  { label: msg('UI_RETURNREASONS_WITHDRAWAL_STOPPED_DRAWER_OF_UNSOUND_2'),               code: '24', customerFault: true  },
  { label: msg('UI_RETURNREASONS_WITHDRAWAL_STOPPED_INSOLVENCY_2'),                           code: '25', customerFault: true  },
  // ── 30–42: Date / amount / presentation / endorsement ───────────────────
  { label: msg('UI_RETURNREASONS_POST_DATED_CHEQUE_2'),                                         code: '30', customerFault: false },
  { label: msg('UI_RETURNREASONS_STALE_CHEQUE_VALIDITY_PERIOD_EXPIRED_2'),                    code: '31', customerFault: false },
  { label: msg('UI_RETURNREASONS_UNDATED_CHEQUE_2'),                                            code: '32', customerFault: false },
  { label: msg('UI_RETURNREASONS_INSTRUMENT_MUTILATED_REQUIRES_BANK_G_2'),            code: '33', customerFault: false },
  { label: msg('UI_RETURNREASONS_AMOUNT_IN_WORDS_AND_FIGURES_2'),                        code: '34', customerFault: true  },
  { label: msg('UI_RETURNREASONS_CLEARING_HOUSE_STAMP_DATE_REQUIRED_2'),                      code: '35', customerFault: false },
  { label: msg('UI_RETURNREASONS_WRONGLY_DELIVERED_NOT_DRAWN_ON_2'),                       code: '36', customerFault: false },
  { label: msg('UI_RETURNREASONS_PRESENT_INSTRUMENT_IN_PROPER_ZONE_2'),                         code: '37', customerFault: false },
  { label: msg('UI_RETURNREASONS_INSTRUMENT_CONTAINS_EXTRANEOUS_MATTE_2'),                     code: '38', customerFault: false },
  { label: msg('UI_RETURNREASONS_IMAGE_NOT_CLEAR_RE_SCAN_2'),                        code: '39', customerFault: false },
  { label: msg('UI_RETURNREASONS_PRESENT_WITH_DOCUMENT_2'),                                     code: '40', customerFault: false },
  { label: msg('UI_RETURNREASONS_ITEM_LISTED_TWICE_2'),                                         code: '41', customerFault: false },
  { label: msg('UI_RETURNREASONS_PAPER_INSTRUMENT_NOT_RECEIVED_2'),                           code: '42', customerFault: false },
  // ── 50–55: Account status ───────────────────────────────────────────────
  { label: msg('UI_RETURNREASONS_ACCOUNT_CLOSED_2'),                                            code: '50', customerFault: true  },
  { label: msg('UI_RETURNREASONS_ACCOUNT_TRANSFERRED_TO_ANOTHER_BRANC_2'),              code: '51', customerFault: true  },
  { label: msg('UI_RETURNREASONS_NO_SUCH_ACCOUNT_2'),                                           code: '52', customerFault: true  },
  { label: msg('UI_RETURNREASONS_TITLE_OF_ACCOUNT_REQUIRED_2'),                                 code: '53', customerFault: true  },
  { label: msg('UI_RETURNREASONS_TITLE_OF_ACCOUNT_INCORRECT_2'),                                code: '54', customerFault: true  },
  { label: msg('UI_RETURNREASONS_ACCOUNT_FROZEN_REGULATORY_LEGAL_HOLD_2'),                  code: '55', customerFault: false },
  // ── 60–68: Crossing / endorsement ───────────────────────────────────────
  { label: msg('UI_RETURNREASONS_INSTRUMENT_CROSSED_TO_TWO_BANKS_2'),                           code: '60', customerFault: false },
  { label: msg('UI_RETURNREASONS_CROSSING_STAMP_NOT_CANCELLED_BY_2'),           code: '61', customerFault: false },
  { label: msg('UI_RETURNREASONS_CLEARING_STAMP_NOT_CANCELLED_BY_2'),           code: '62', customerFault: false },
  { label: msg('UI_RETURNREASONS_INSTRUMENT_SPECIALLY_CROSSED_TO_ANOT_2'),              code: '63', customerFault: false },
  { label: msg('UI_RETURNREASONS_PROTECTIVE_CROSSING_APPLIED_INCORREC_2'),                   code: '64', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PROTECTIVE_CROSSING_ILLEGIBLE_2'),                             code: '65', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PAYEE_S_ENDORSEMENT_REQUIRED_2'),                              code: '66', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PAYEE_S_ENDORSEMENT_IRREGULAR_COLLEC_2'),code: '67', customerFault: false },
  { label: msg('UI_RETURNREASONS_ENDORSEMENT_BY_THUMB_IMPRESSION_MAGI_2'), code: '68', customerFault: false },
  // ── 70–76: Advice / SMB settlement ──────────────────────────────────────
  // Citibank/NPCI numbering; CBI uses 69–75 for the same range
  { label: msg('UI_RETURNREASONS_ADVICE_NOT_RECEIVED_2'),                                       code: '70', customerFault: false },
  { label: msg('UI_RETURNREASONS_AMOUNT_NAME_DIFFERS_ON_ADVICE_2'),                           code: '71', customerFault: false },
  { label: msg('UI_RETURNREASONS_DRAWEE_BANK_S_FUNDS_WITH_2'),        code: '72', customerFault: false },
  { label: msg('UI_RETURNREASONS_PAYEE_S_SEPARATE_DISCHARGE_TO_2'),               code: '73', customerFault: false },
  { label: msg('UI_RETURNREASONS_NOT_PAYABLE_TILL_1ST_PROXIMO_2'),                              code: '74', customerFault: false },
  { label: msg('UI_RETURNREASONS_PAY_ORDER_CHEQUE_REQUIRES_COUNTER_2'),             code: '75', customerFault: false },
  { label: msg('UI_RETURNREASONS_REQUIRED_INFORMATION_NOT_LEGIBLE_OR_2'),               code: '76', customerFault: false },
  // ── 80–88: Technical / connectivity / fraud ──────────────────────────────
  { label: msg('UI_RETURNREASONS_BANK_S_CERTIFICATE_AMBIGUOUS_INCOMPL_2'),      code: '80', customerFault: false },
  { label: msg('UI_RETURNREASONS_DRAFT_LOST_BY_ISSUING_OFFICE_2'),                              code: '81', customerFault: false },
  { label: msg('UI_RETURNREASONS_BANK_BRANCH_BLOCKED_2'),                                     code: '82', customerFault: false },
  { label: msg('UI_RETURNREASONS_DIGITAL_CERTIFICATE_VALIDATION_FAILU_2'),                    code: '83', customerFault: false },
  { label: msg('UI_RETURNREASONS_OTHER_CONNECTIVITY_FAILURE_2'),                                code: '84', customerFault: false },
  { label: msg('UI_RETURNREASONS_CTS_2010_ALTERATION_DETECTED_IN_2'),           code: '85', customerFault: true  },
  { label: msg('UI_RETURNREASONS_FORGED_FAKE_INSTRUMENT_2'),                                  code: '86', customerFault: true  },
  { label: msg('UI_RETURNREASONS_PAYEE_S_ACCOUNT_CREDITED_STAMP_2'),                 code: '87', customerFault: false },
  { label: msg('UI_RETURNREASONS_OTHER_REASON_NOT_LISTED_ABOVE_2'),                           code: '88', customerFault: true  },
  // ── 92: Administrative ───────────────────────────────────────────────────
  { label: msg('UI_RETURNREASONS_BANK_EXCLUDE_2'),                                              code: '92', customerFault: false },
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
