/**
 * CTSOutwardQueue — "Outward Q". Actionable, unlike Outward Monitor (view-only).
 *
 * Two tabs:
 *   Human Review   — outward instruments flagged before NGCH filing. Confirm (proceed)
 *                     or Reject (with reason) — both close the review.
 *   STP Rejected   — instruments auto-rejected by STP pre-checks. Only Confirm
 *                     (override, mandatory reason) is offered — they're already rejected.
 *
 * Processing Unit (PU) tagging: every instrument here is tagged bank/branch/PU
 * BEFORE it goes to NGCH (mirrors CRLService's IFSC/MICR -> branch resolution on
 * the backend, per docs/astra-multi-scenario-cts-plan.html). This page shows that
 * tag on every row. Real per-user branch/PU visibility scoping (who is mapped to
 * which PUs) is a backend RBAC feature — see the note at the bottom of this file.
 */
import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import OutwardReviewPanel from '../components/OutwardReviewPanel'
import { demoChequeUrl } from '../demoImages'

// ─── Mock data ──────────────────────────────────────────────────────────────
// bank_slug mirrors Inward Q's convention: SMB sees only its own bank's rows.
// pu / branch: tagged pre-NGCH, same as the backend CRL resolution.
// bank / branch / pu = presenting bank (Saraswat or SMB that scanned the cheque).
// ocr_fields.bank_name etc. = drawee bank (the bank on which the cheque is drawn).

function ocrFields(over = {}) {
  return {
    date: '19-Jun-2026', payee: over.payee ?? 'Payee', amount_figures: over.amount_figures ?? '₹0',
    amount_words: over.amount_words ?? '', micr: '400160002' + Math.floor(Math.random() * 900 + 100),
    alterations: over.alterations ?? false, ...over,
  }
}

// Build fields_meta from ocr_fields + per-field confidence overrides.
// This models the extracted_value (immutable AI output) vs actual_value (what goes to NGCH).
function makeFieldsMeta(ocr, confidences = {}) {
  const defaults = { date: 0.97, payee: 0.95, amount_figures: 0.93, amount_words: 0.88, micr: 0.99, alterations: 0.99 }
  const out = {}
  Object.keys(defaults).forEach(k => {
    const conf = confidences[k] ?? defaults[k]
    out[k] = {
      extracted_value:      ocr[k] ?? '',
      extracted_confidence: conf,
      extracted_by:         'GOT-OCR2.0',
      actual_value:         ocr[k] ?? '',
      source:               conf >= 0.90 ? 'STP' : 'MANUAL',
      corrected_by:         null,
      corrected_at:         null,
    }
  })
  return out
}

const DEPOSIT_CHANNEL_CFG = {
  PAY_IN_SLIP:     { label: 'Pay-in Slip', icon: '🧾', clr: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30', clrL: 'text-emerald-700 bg-emerald-50 border-emerald-400' },
  BACK_ANNOTATION: { label: 'Back Note',   icon: '✍️',  clr: 'text-sky-400 bg-sky-500/10 border-sky-500/30',             clrL: 'text-sky-700 bg-sky-50 border-sky-400'             },
  KIOSK:           { label: 'Kiosk/CDM',   icon: '🏧',  clr: 'text-violet-400 bg-violet-500/10 border-violet-500/30',    clrL: 'text-violet-700 bg-violet-50 border-violet-400'    },
}

const MOCK_HUMAN_REVIEW = [
  {
    instrument_id: 'CHQ-OUT-00512', front_bw_url: null, front_gray_url: null, account_display: '****4471', payee_display: 'Kiran Traders',
    amount_range: '₹[5L-10L]', micr: '400160002841', bank: 'Saraswat Co-operative Bank',
    branch: 'Fort', pu: 'PU-MUM-01', bank_slug: 'saraswat-coop',
    reason: 'AMOUNT_MISMATCH', reason_label: 'Amount words/figures variance', received_at: '11:42 AM',
    scanner_id: 'SCN-FORT-02', lot_number: 'LOT_SRCB0000001_20260619_01',
    ocr_confidence: 0.91, vision_compliance: 0.97, micr_confidence: 0.99,
    checks: { signature_present: true, amount_words_match: false, date_valid: true, cts_valid: true },
    security_features: { void_pantograph: true, rupee_symbol: true, micro_lettering: true, printer_name_cts2010: true, missing: [] },
    deposit_channel: 'BACK_ANNOTATION',
    deposit_data: { extracted_account: '4000123471', extracted_mobile: '9876543210', ocr_confidence: 0.91 },
    ocr_fields: ocrFields({
      payee: 'Kiran Traders', amount_figures: '₹7,40,000', amount_words: 'Seven lakhs fifty thousand only', alterations: false,
      bank_name: 'HDFC Bank Ltd.', bank_branch: 'Fort Branch, Mumbai', bank_ifsc: 'HDFC0000060', bank_micr: '400240060',
    }),
    get fields_meta() { return makeFieldsMeta(this.ocr_fields, { amount_words: 0.74, amount_figures: 0.91 }) },
  },
  {
    instrument_id: 'CHQ-OUT-00519', front_bw_url: null, front_gray_url: null, account_display: '****9021', payee_display: 'Om Enterprises',
    amount_range: '₹[1L-5L]', micr: '400160002855', bank: 'Saraswat Co-operative Bank',
    branch: 'Vashi', pu: 'PU-MUM-02', bank_slug: 'saraswat-coop',
    reason: 'ENDORSEMENT_IRREGULAR', reason_label: 'Endorsement irregular', received_at: '11:47 AM',
    scanner_id: 'SCN-VASH-01', lot_number: 'LOT_SRCB0000001_20260619_02',
    ocr_confidence: 0.95, vision_compliance: 0.88, micr_confidence: 0.98,
    checks: { signature_present: true, amount_words_match: true, date_valid: true, cts_valid: false },
    security_features: { void_pantograph: false, rupee_symbol: true, micro_lettering: true, printer_name_cts2010: false, missing: ['void_pantograph', 'printer_name_cts2010'] },
    deposit_channel: 'PAY_IN_SLIP',
    deposit_data: { depositor_name: 'Om Enterprises', depositor_account: '4000295021', deposit_amount: '₹2,15,000', counter_token: 'T-0019', date: '19/06/2026', branch: 'Nariman Point, Mumbai' },
    ocr_fields: ocrFields({
      payee: 'Om Enterprises', amount_figures: '₹2,15,000', amount_words: 'Two lakhs fifteen thousand only',
      bank_name: 'ICICI Bank Ltd.', bank_branch: 'Nariman Point, Mumbai', bank_ifsc: 'ICIC0000001', bank_micr: '400229001',
    }),
    get fields_meta() { return makeFieldsMeta(this.ocr_fields) },
  },
  {
    instrument_id: 'CHQ-OUT-00527', front_bw_url: null, front_gray_url: null, account_display: '****3308', payee_display: 'Deshmukh & Co.',
    amount_range: '₹[10L-1Cr]', micr: '400160002863', bank: 'Vasavi Co-operative Bank',
    branch: 'Andheri (W)', pu: 'PU-MUM-03', bank_slug: 'smb-mh-vasavi',
    reason: 'HIGH_VALUE_DUAL_APPROVAL', reason_label: 'High value — dual approval', received_at: '11:53 AM',
    scanner_id: 'SCN-ANDH-03', lot_number: 'LOT_VASB0000001_20260619_01',
    ocr_confidence: 0.98, vision_compliance: 0.99, micr_confidence: 0.99,
    checks: { signature_present: true, amount_words_match: true, date_valid: true, cts_valid: true },
    security_features: { void_pantograph: true, rupee_symbol: true, micro_lettering: true, printer_name_cts2010: true, missing: [] },
    deposit_channel: 'KIOSK',
    deposit_data: { name: 'Deshmukh & Co.', account: '4000273308', txn_id: 'CDM-027-20260619', timestamp: '10:47 AM  19/06/2026' },
    ocr_fields: ocrFields({
      payee: 'Deshmukh & Co.', amount_figures: '₹42,00,000', amount_words: 'Forty two lakhs only',
      bank_name: 'State Bank of India', bank_branch: 'Fort Branch, Mumbai', bank_ifsc: 'SBIN0000300', bank_micr: '400002003',
    }),
    get fields_meta() { return makeFieldsMeta(this.ocr_fields, { date: 0.99, payee: 0.99, amount_figures: 0.99, amount_words: 0.98, micr: 0.99 }) },
    opa_rule: 'cts_routing.rego · rule: high_value_dual_approval',
  },
]

const MOCK_STP_REJECTED = [
  {
    instrument_id: 'CHQ-OUT-00488', front_bw_url: null, front_gray_url: null, account_display: '****7712', payee_display: 'Bhagwati Steels',
    amount_range: '₹[1L-5L]', micr: '400160002771', bank: 'Saraswat Co-operative Bank',
    branch: 'Dadar (E)', pu: 'PU-MUM-01', bank_slug: 'saraswat-coop',
    reason: 'CTS_COMPLIANCE_FAILURE', reason_label: 'CTS compliance failure — auto-rejected', received_at: '10:58 AM',
    scanner_id: 'SCN-DADR-01', lot_number: 'LOT_SRCB0000001_20260619_01',
    ocr_confidence: 0.86, vision_compliance: 0.61, micr_confidence: 0.94,
    checks: { signature_present: true, amount_words_match: true, date_valid: true, cts_valid: false },
    security_features: { void_pantograph: true, rupee_symbol: true, micro_lettering: true, printer_name_cts2010: true, missing: [] },
    deposit_channel: 'PAY_IN_SLIP',
    deposit_data: { depositor_name: 'Bhagwati Steels', depositor_account: '4000187712', deposit_amount: '₹1,88,000', counter_token: 'T-0088', date: '19/06/2026', branch: 'Dadar (E)' },
    ocr_fields: ocrFields({
      payee: 'Bhagwati Steels', amount_figures: '₹1,88,000', amount_words: 'One lakh eighty eight thousand only',
      bank_name: 'Axis Bank Ltd.', bank_branch: 'Andheri West, Mumbai', bank_ifsc: 'UTIB0000067', bank_micr: '400211067',
    }),
    get fields_meta() { return makeFieldsMeta(this.ocr_fields, { payee: 0.86, amount_figures: 0.88 }) },
    stp_decision: {
      engine: 'CTS-2010 Compliance Validator', rule: 'crossing_lines_missing',
      confidence: 0.61, threshold: 0.85, decided_at: '10:58:41 AM',
      detail: 'Vision compliance score 61% below the 85% CTS-2010 auto-accept threshold — account-payee crossing lines not detected on front image. Auto-rejected before NGCH submission.',
    },
  },
  {
    instrument_id: 'CHQ-OUT-00495', front_bw_url: null, front_gray_url: null, account_display: '****2245', payee_display: 'Shree Ambika Traders',
    amount_range: '₹[<1L]', micr: '400160002788', bank: 'Andheri Urban Co-op Bank',
    branch: 'Andheri (E)', pu: 'PU-MUM-04', bank_slug: 'smb-mh-andheri',
    reason: 'DATE_INVALID', reason_label: 'Date invalid / stale — auto-rejected', received_at: '11:05 AM',
    scanner_id: 'SCN-ANDE-02', lot_number: 'LOT_VASB0000001_20260619_02',
    ocr_confidence: 0.93, vision_compliance: 0.95, micr_confidence: 0.97,
    checks: { signature_present: true, amount_words_match: true, date_valid: false, cts_valid: true },
    security_features: { void_pantograph: true, rupee_symbol: true, micro_lettering: true, printer_name_cts2010: true, missing: [] },
    deposit_channel: 'BACK_ANNOTATION',
    deposit_data: { extracted_account: '4000272245', extracted_mobile: '9765432100', ocr_confidence: 0.87 },
    ocr_fields: ocrFields({
      payee: 'Shree Ambika Traders', amount_figures: '₹42,500', amount_words: 'Forty two thousand five hundred only', date: '02-Jan-2026',
      bank_name: 'Bank of Baroda', bank_branch: 'Churchgate, Mumbai', bank_ifsc: 'BARB0CHURCH', bank_micr: '400012009',
    }),
    get fields_meta() { return makeFieldsMeta(this.ocr_fields, { date: 0.97 }) },
    stp_decision: {
      engine: 'CTS-2010 Compliance Validator', rule: 'stale_instrument_date',
      confidence: 0.97, threshold: 0.90, decided_at: '11:05:18 AM',
      detail: 'Cheque date 02-Jan-2026 exceeds the 3-month validity window as of presentation (19-Jun-2026). Auto-rejected per NI Act staleness rule — never auto-returned to drawee without human sign-off on outward side.',
    },
  },
]

// ─── Row card ───────────────────────────────────────────────────────────────

function OutwardRow({ item, isDark, selected, onClick }) {
  const th = isDark
    ? { idle: 'border-white/8 bg-white/5 hover:border-white/15 hover:bg-white/8', id: 'text-slate-500', name: 'text-white', sub: 'text-slate-400' }
    : { idle: 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50', id: 'text-slate-400', name: 'text-slate-900', sub: 'text-slate-500' }

  return (
    <button onClick={onClick} className={`w-full text-left rounded-xl border p-4 transition-all ${selected ? 'border-gold-400/40 bg-gold-400/5' : th.idle}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className={`text-[11px] font-mono ${th.id}`}>{item.instrument_id}</div>
          <div className={`text-sm font-semibold ${th.name} mt-0.5 truncate`}>{item.account_display} · {item.payee_display}</div>
          <div className={`text-[10px] mt-0.5 truncate ${th.sub}`}>{item.bank} · {item.branch} · {item.pu}</div>
        </div>
        <span className={`text-[10px] shrink-0 ${th.sub}`}>{item.received_at}</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap mt-2">
        <span className={`text-[10px] font-mono px-2 py-0.5 rounded border ${isDark ? 'text-amber-300 bg-amber-400/10 border-amber-400/20' : 'text-amber-700 bg-amber-100 border-amber-400'}`}>
          {item.reason_label}
        </span>
        {item.deposit_channel && (() => {
          const ch = DEPOSIT_CHANNEL_CFG[item.deposit_channel]
          return ch ? (
            <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border inline-flex items-center gap-1 ${isDark ? ch.clr : ch.clrL}`}>
              {ch.icon} {ch.label}
            </span>
          ) : null
        })()}
        <span className={`text-[10px] ml-auto ${th.sub}`}>{item.amount_range}</span>
      </div>
    </button>
  )
}

// ─── Main page ──────────────────────────────────────────────────────────────

export default function CTSOutwardQueue() {
  const { isDark } = useTheme()
  const { bankId, isSMB, isDemo } = useBankContext()
  const [tab, setTab] = useState('review') // 'review' | 'stp_rejected'
  // In POC/PROD start empty — real instruments arrive from the folder-watcher pipeline
  const [review, setReview] = useState(isDemo ? MOCK_HUMAN_REVIEW : [])
  const [rejected, setRejected] = useState(isDemo ? MOCK_STP_REJECTED : [])
  const [decided, setDecided] = useState([]) // { instrument_id, action, reason, ts }
  const [selected, setSelected] = useState(null)

  const inScope = (item) => (isSMB ? item.bank_slug === bankId : true)

  const reviewQueue   = review.filter(inScope)
  const rejectedQueue = rejected.filter(inScope)
  const activeList = tab === 'review' ? reviewQueue : rejectedQueue

  usePageHeader({
    subtitle: 'Outward Q · Human Review + STP Rejected · action required before NGCH filing',
    actions: (
      <div className={`text-[10px] font-mono px-3 py-1.5 rounded-lg border ${isDark ? 'border-white/10 text-slate-300 bg-white/4' : 'border-slate-200 text-slate-600 bg-white'}`}>
        {reviewQueue.length + rejectedQueue.length} pending
      </div>
    ),
  })

  function decide(instrumentId, action, reason) {
    const entry = { instrument_id: instrumentId, action, reason, ts: new Date().toLocaleTimeString() }
    setDecided(d => [entry, ...d])
    if (tab === 'review') setReview(r => r.filter(i => i.instrument_id !== instrumentId))
    else setRejected(r => r.filter(i => i.instrument_id !== instrumentId))

    // Immudb audit trail — fire-and-forget, never blocks the reviewer's decision.
    // POST /v1/cts/outward/queue/decisions -> platform.audit.events -> audit-service -> Immudb.
    fetch('/v1/cts/outward/queue/decisions', {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRF-Token': sessionStorage.getItem('astra-csrf') || '',
      },
      body: JSON.stringify({
        instrument_id: instrumentId,
        tab,
        action,
        reason,
        reason_category: action === 'CONFIRMED' ? 'confirm' : 'reject',
      }),
    }).catch(err => console.warn('outward Q audit write failed (non-blocking):', err))
    setSelected(null)
  }

  function selectItem(item) {
    setSelected(item)
  }

  const th = {
    page: isDark ? 'bg-transparent' : 'bg-slate-50',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    empty: isDark ? 'text-slate-500' : 'text-slate-400',
  }

  return (
    <AppShell>
      <div className={`flex h-full ${th.page}`}>
        {/* List column */}
        <div className={`w-96 shrink-0 border-r ${th.divider} flex flex-col`}>
          {/* Tabs */}
          <div className={`flex gap-1 px-3 pt-3 border-b ${th.divider} pb-2`}>
            {[['review', 'Human Review', reviewQueue.length], ['stp_rejected', 'STP Rejected', rejectedQueue.length]].map(([key, label, count]) => (
              <button
                key={key}
                onClick={() => { setTab(key); setSelected(null) }}
                className={`flex-1 text-[11px] font-semibold px-2 py-2 rounded-lg border transition-all flex items-center justify-center gap-1.5 ${
                  tab === key
                    ? (isDark ? 'bg-white/10 text-white border-white/15' : 'bg-slate-800 text-white border-slate-800')
                    : (isDark ? 'text-slate-400 border-white/8 hover:bg-white/5' : 'text-slate-500 border-slate-200 hover:bg-slate-50')
                }`}
              >
                {label}
                <span className={`text-[9px] font-mono px-1.5 rounded-full ${tab === key ? 'bg-white/20' : (isDark ? 'bg-white/10' : 'bg-slate-200')}`}>{count}</span>
              </button>
            ))}
          </div>

          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
            {activeList.length === 0 && (
              <div className={`text-center ${th.empty} text-sm py-12`}>
                <div className="text-3xl mb-2">✓</div>
                <div>{tab === 'review' ? 'No items awaiting review' : 'No STP rejections pending'}</div>
              </div>
            )}
            {activeList.map(item => (
              <OutwardRow key={item.instrument_id} item={item} isDark={isDark}
                selected={selected?.instrument_id === item.instrument_id} onClick={() => selectItem(item)} />
            ))}

            {decided.length > 0 && (
              <>
                <div className={`text-[10px] ${th.muted} uppercase tracking-widest pt-3 pb-1 px-1`}>Decided this session</div>
                {decided.map(d => (
                  <div key={d.instrument_id} className={`rounded-xl border px-4 py-3 opacity-50 ${isDark ? 'border-white/5 bg-white/5' : 'border-slate-100 bg-slate-50'}`}>
                    <div className="flex items-center justify-between">
                      <span className={`text-[11px] font-mono ${th.muted}`}>{d.instrument_id}</span>
                      <span className={`text-[10px] font-semibold ${d.action === 'CONFIRMED' ? 'text-emerald-500' : 'text-red-500'}`}>
                        {d.action === 'CONFIRMED' ? '✓ Confirmed' : '✕ Rejected'}
                      </span>
                    </div>
                  </div>
                ))}
              </>
            )}
          </div>
        </div>

        {/* Decision panel — same depth as Inward Q: Overview/Cheque/AI Analysis/Passport (+ Reject Decision) */}
        <OutwardReviewPanel item={selected} tabKind={tab} onDecision={decide} isDark={isDark} />
      </div>
    </AppShell>
  )
}

// ─── PU / branch scoping — current state and what's next ───────────────────
//
// Every row above is tagged bank / branch / pu (mirrors the backend CRLService
// IFSC/MICR -> BranchResolution mapping that runs before NGCH filing). Today the
// frontend only enforces bank-level scoping (isSMB -> own bank_slug only, same
// pattern as Inward Q), because there is no live backend feeding this page yet.
//
// Real branch/PU-level scoping needs a user->PU/branch assignment, which is a
// backend RBAC extension (a user record listing which PU(s)/branch(es) they may
// see), enforced server-side the same way bank_id isolation is enforced today —
// not something this frontend mock can decide on its own.
