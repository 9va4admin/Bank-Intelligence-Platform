/**
 * OutwardReviewPanel — the Outward Q detail/decision panel.
 *
 * Mirrors ReviewPanel's tab structure (Overview / Cheque / AI Analysis / Passport)
 * so a reviewer has the same depth of information on both inward and outward
 * decisions — a cheque image, extraction confidence, and a processing timeline,
 * not just a reason label. Content differs because the checks differ: outward is
 * scanner-side (IQA, MICR, CTS-2010 vision compliance), not drawee-side fraud/IET.
 *
 * STP Rejected items get a 5th tab — Reject Decision — showing exactly what the
 * automated engine decided (rule, confidence, threshold) before a human overrides it.
 */
import { useEffect, useState } from 'react'
import ChequeImageViewer from './ChequeImageViewer'
import { getReturnReasons } from '../data/returnReasons'

// Reasons a reviewer can proceed despite the flag — outward-side, no drawee context.
const CONFIRM_REASONS = [
  'Manual Verification Passed',
  'Amount Discrepancy Resolved with Branch',
  'Second Reviewer Confirmed',
  'Manager Override Approved',
  'Re-scanned — CTS-2010 Compliant',
  'Risk Accepted — Proceed to NGCH',
]

const REASON_COLORS = {
  AMOUNT_MISMATCH:          'bg-amber-400/10 border-amber-400/30 text-amber-300',
  ENDORSEMENT_IRREGULAR:    'bg-orange-400/10 border-orange-400/30 text-orange-300',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-400/10 border-sky-400/30 text-sky-300',
  CTS_COMPLIANCE_FAILURE:   'bg-red-400/10 border-red-400/30 text-red-300',
  DATE_INVALID:             'bg-red-400/10 border-red-400/30 text-red-300',
}

function ReasonColor(isDark, key) {
  return REASON_COLORS[key] || (isDark ? 'bg-slate-400/10 border-slate-400/20 text-slate-300' : 'bg-slate-100 border-slate-300 text-slate-600')
}

function CompliancePanel({ item, isDark }) {
  const rows = [
    ['Amount words = figures', item.checks.amount_words_match],
    ['Date validity', item.checks.date_valid],
    ['CTS-2010 image compliant', item.checks.cts_valid],
  ]
  return (
    <div className={`rounded-xl border px-4 py-3 ${isDark ? 'border-white/10 bg-white/5' : 'border-slate-200 bg-slate-50'}`}>
      <div className={`text-[10px] uppercase tracking-widest mb-3 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>CTS-2010 Compliance Checks</div>
      <div className="space-y-2">
        {rows.map(([label, ok]) => (
          <div key={label} className="flex items-center justify-between">
            <span className={`text-xs ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>{label}</span>
            <span className={`text-xs font-semibold ${ok ? 'text-emerald-400' : 'text-red-400'}`}>{ok ? '✓ Pass' : '✗ Fail'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function OutwardReviewPanel({ item, tabKind, onDecision, isDark }) {
  const [tab, setTab] = useState('overview')
  const [reason, setReason] = useState('')
  const [reasonCategory, setReasonCategory] = useState(null) // 'confirm' | 'reject' | null
  const [reasonOpen, setReasonOpen] = useState(false)

  // A new item was selected — the previous item's reason/tab must not carry over.
  useEffect(() => {
    setReason('')
    setReasonCategory(null)
    setTab('overview')
  }, [item?.instrument_id])

  if (!item) {
    return (
      <div className={`flex-1 flex items-center justify-center text-sm ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
        <div className="text-center">
          <div className="text-4xl mb-3">📋</div>
          <div>Select an instrument to decide</div>
        </div>
      </div>
    )
  }

  const th = {
    border:    isDark ? 'border-white/10' : 'border-slate-200',
    heading:   isDark ? 'text-white' : 'text-slate-900',
    id:        isDark ? 'text-gold-400' : 'text-amber-600',
    lbl:       isDark ? 'text-slate-500' : 'text-slate-400',
    meta:      isDark ? 'text-slate-400' : 'text-slate-500',
    glass:     isDark ? 'bg-white/5 border border-white/10' : 'bg-slate-50 border border-slate-200',
    val:       isDark ? 'text-slate-200' : 'text-slate-800',
    barBg:     isDark ? 'bg-white/5' : 'bg-slate-100',
    tabActive: isDark ? 'bg-white/5 text-white border-t border-l border-r border-white/10' : 'bg-slate-100 text-slate-900 border-t border-l border-r border-slate-200',
    tabIdle:   isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    foot:      isDark ? 'bg-navy-950/80' : 'bg-white',
    sel:       isDark ? 'bg-white/5 border-white/10 text-slate-300 focus:border-gold-400/40' : 'bg-white border-slate-300 text-slate-700 focus:border-amber-400',
  }

  const isRejected = tabKind === 'stp_rejected'
  const tabs = isRejected
    ? ['overview', 'cheque', 'ai analysis', 'passport', 'reject decision']
    : ['overview', 'cheque', 'ai analysis', 'passport']

  const reasonColor = ReasonColor(isDark, item.reason)
  // Outward Q is presenting-bank side only — "Drawee Bank" reject reasons don't apply here.
  const REJECT_REASONS_GROUPED = Object.fromEntries(
    Object.entries(getReturnReasons()).filter(([group]) => group !== 'Drawee Bank')
  )

  function pickReason(r, category) {
    setReason(r)
    setReasonCategory(category)
    setReasonOpen(false)
  }

  function decide(action) {
    const requiredCategory = action === 'CONFIRMED' ? 'confirm' : 'reject'
    if (!reason || reasonCategory !== requiredCategory) return
    onDecision(item.instrument_id, action, reason)
  }

  const cheqViews = [
    { key: 'BFB', label: 'Front B/W',  url: item.front_bw_url   ?? null },
    { key: 'BBB', label: 'Back B/W',   url: item.back_bw_url    ?? null },
    { key: 'BFG', label: 'Front Gray', url: item.front_gray_url ?? null },
  ]

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Header */}
      <div className={`px-6 pt-3 pb-0 border-b ${th.border} shrink-0`}>
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className={`text-[12px] font-mono font-semibold ${th.id}`}>{item.instrument_id}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.account_display}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.payee_display}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>{item.reason_label}</span>
          <span className={`text-[10px] ml-auto ${th.meta}`}>{item.amount_range}</span>
          {item.opa_rule && <span className="text-[10px] text-sky-400/70 font-mono">OPA</span>}
        </div>
        <div className={`text-[11px] mb-2 ${th.meta}`}>{item.bank} · {item.branch} · <span className="font-mono">{item.pu}</span> · Lot {item.lot_number}</div>

        {/* Confidence strip */}
        <div className="flex items-center gap-3 py-2">
          {[
            { label: 'OCR',   pct: item.ocr_confidence,      bar: item.ocr_confidence >= 0.92 ? 'bg-emerald-500' : item.ocr_confidence >= 0.80 ? 'bg-amber-400' : 'bg-red-400' },
            { label: 'CTS-2010',  pct: item.vision_compliance,   bar: item.vision_compliance >= 0.85 ? 'bg-emerald-500' : item.vision_compliance >= 0.70 ? 'bg-amber-400' : 'bg-red-400' },
            { label: 'MICR',  pct: item.micr_confidence,      bar: item.micr_confidence >= 0.95 ? 'bg-emerald-500' : 'bg-amber-400' },
          ].map(({ label, pct, bar }) => (
            <div key={label} className="flex items-center gap-1.5 min-w-0">
              <span className={`text-[9px] font-semibold uppercase tracking-wider ${th.lbl} w-14 shrink-0`}>{label}</span>
              <div className={`w-16 h-1 ${th.barBg} rounded-full overflow-hidden`}>
                <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct * 100}%` }} />
              </div>
              <span className={`text-[10px] font-mono ${th.lbl}`}>{Math.round(pct * 100)}%</span>
            </div>
          ))}
        </div>

        <div className="flex gap-1">
          {tabs.map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${tab === t ? th.tabActive : th.tabIdle} ${t === 'reject decision' ? (isDark ? 'text-red-300' : 'text-red-600') : ''}`}
            >{t}</button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {tab === 'overview' && (
          <>
            <div className={`flex items-start gap-3 rounded-xl border px-4 py-2.5 ${reasonColor}`}>
              <span className="text-base mt-0.5">{isRejected ? '⛔' : '⚠'}</span>
              <div>
                <div className="text-xs font-semibold">{isRejected ? 'Auto-rejected: ' : 'Flagged: '}{item.reason_label}</div>
                <div className="text-[11px] opacity-70 mt-0.5">
                  {isRejected
                    ? 'Rejected by the STP compliance engine before NGCH submission — see Reject Decision tab for details.'
                    : 'Outward instrument held for human review before NGCH submission.'}
                </div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'OCR', val: `${Math.round(item.ocr_confidence * 100)}%`, sub: 'confidence' },
                { label: 'CTS-2010', val: `${Math.round(item.vision_compliance * 100)}%`, sub: 'compliance' },
                { label: 'MICR', val: `${Math.round(item.micr_confidence * 100)}%`, sub: 'extraction' },
              ].map(({ label, val, sub }) => (
                <div key={label} className={`rounded-xl p-3 text-center ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-wide mb-0.5`}>{label}</div>
                  <div className={`text-3xl font-mono font-bold ${th.heading}`}>{val}</div>
                  <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                </div>
              ))}
            </div>

            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>OCR Extracted Fields · GOT-OCR2.0</div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                {[
                  ['Date', item.ocr_fields.date],
                  ['Payee', item.ocr_fields.payee],
                  ['Amount (figures)', item.ocr_fields.amount_figures],
                  ['Amount (words)', item.ocr_fields.amount_words],
                  ['MICR Code', item.ocr_fields.micr],
                  ['Alterations', item.ocr_fields.alterations ? '⚠ DETECTED' : '✓ None'],
                ].map(([k, v]) => (
                  <div key={k} className="flex flex-col">
                    <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                    <span className={`text-xs font-mono mt-0.5 ${k === 'Alterations' && item.ocr_fields.alterations ? 'text-red-400 font-semibold' : th.val}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>

            <CompliancePanel item={item} isDark={isDark} />
          </>
        )}

        {tab === 'cheque' && (
          <ChequeImageViewer views={cheqViews} fields={item.ocr_fields} isDark={isDark} compact={false} title={item.instrument_id} />
        )}

        {tab === 'ai analysis' && (
          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-2`}>Model Stack — Outward Capture</div>
            {[
              ['OCR', 'GOT-OCR2.0', item.ocr_confidence],
              ['Vision', 'Qwen2-VL 72B · CTS-2010', item.vision_compliance],
              ['MICR', 'GOT-OCR2.0 · MICR line', item.micr_confidence],
            ].map(([label, model, score]) => (
              <div key={label} className="flex items-center gap-3 py-1.5">
                <span className={`text-[10px] ${th.lbl} w-14`}>{label}</span>
                <div className={`flex-1 h-1.5 ${th.barBg} rounded-full overflow-hidden`}>
                  <div className="h-full bg-gold-400/60 rounded-full" style={{ width: `${score * 100}%` }} />
                </div>
                <span className={`text-[10px] font-mono ${th.meta} w-8 text-right`}>{Math.round(score * 100)}%</span>
                <span className={`text-[10px] ${th.lbl} w-40 truncate`}>{model}</span>
              </div>
            ))}
            <div className={`text-[11px] mt-3 pt-3 border-t ${th.border} ${th.meta}`}>
              Outward capture has no drawee-side fraud/IET scoring — that runs when the instrument is presented for payment on the inward side.
            </div>
          </div>
        )}

        {tab === 'passport' && (() => {
          const steps = [
            { label: 'Scanner Capture', icon: '📷', note: `${item.scanner_id} · CTS-2010 image capture`, status: 'done' },
            { label: 'Image Quality (IQA)', icon: '🖼', note: item.vision_compliance >= 0.85 ? 'IQA passed' : 'IQA borderline — flagged', status: item.vision_compliance >= 0.85 ? 'done' : 'warn' },
            { label: 'MICR Line Extraction', icon: '🔢', note: `MICR: ${item.ocr_fields.micr} · ${Math.round(item.micr_confidence * 100)}% confidence`, status: 'done' },
            { label: 'CTS-2010 Compliance', icon: '✅', note: item.checks.cts_valid ? 'Compliant — crossing, endorsement, format OK' : 'Non-compliant — see Overview', status: item.checks.cts_valid ? 'done' : 'warn' },
            { label: 'Lot Assignment', icon: '📦', note: item.lot_number, status: 'done' },
            { label: isRejected ? 'Auto-Rejected by STP Engine' : 'Routed to Human Review', icon: isRejected ? '⛔' : '👤', note: item.reason_label, status: isRejected ? 'risk' : 'review' },
            { label: isRejected ? 'Awaiting Manual Override' : 'Awaiting Reviewer Decision', icon: '⏳', note: 'Held before NGCH submission', status: 'pending' },
          ]
          const stC = { done: 'bg-emerald-500', warn: 'bg-amber-400', risk: 'bg-red-400', review: 'bg-sky-400', pending: 'bg-slate-400 animate-pulse' }
          const stT = { done: 'text-emerald-400', warn: 'text-amber-400', risk: 'text-red-400', review: 'text-sky-400', pending: 'text-slate-400' }
          return (
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-4`}>Outward Processing Timeline · {item.instrument_id}</div>
              <div className="relative">
                <div className={`absolute left-3 top-3 bottom-3 w-px ${th.barBg}`} />
                <div className="space-y-3">
                  {steps.map((s, i) => (
                    <div key={i} className="flex items-start gap-3 relative">
                      <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center z-10 ${stC[s.status]} text-white text-[11px]`}>{s.icon}</div>
                      <div className="flex-1 min-w-0 pt-0.5">
                        <div className={`text-xs font-semibold ${th.heading}`}>{s.label}</div>
                        <div className={`text-[11px] ${th.lbl} mt-0.5`}>{s.note}</div>
                      </div>
                      <span className={`text-[9px] font-semibold uppercase ${stT[s.status]} shrink-0`}>{s.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )
        })()}

        {tab === 'reject decision' && isRejected && (
          <div className={`rounded-xl border-2 p-4 ${isDark ? 'border-red-500/30 bg-red-500/5' : 'border-red-300 bg-red-50'}`}>
            <div className={`text-[10px] uppercase tracking-widest mb-3 ${isDark ? 'text-red-300' : 'text-red-600'}`}>
              Automated STP Rejection — What The Engine Decided
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3">
              {[
                ['Engine', item.stp_decision.engine],
                ['Rule fired', item.stp_decision.rule],
                ['Confidence', `${Math.round(item.stp_decision.confidence * 100)}%`],
                ['Auto-reject threshold', `${Math.round(item.stp_decision.threshold * 100)}%`],
                ['Decided at', item.stp_decision.decided_at],
              ].map(([k, v]) => (
                <div key={k} className="flex flex-col">
                  <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                  <span className={`text-xs font-mono mt-0.5 ${th.val}`}>{v}</span>
                </div>
              ))}
            </div>
            <div className={`mt-4 pt-3 border-t ${isDark ? 'border-red-500/20' : 'border-red-200'} text-xs leading-relaxed ${th.val}`}>
              {item.stp_decision.detail}
            </div>
            <div className={`mt-3 text-[11px] ${th.meta}`}>
              A manual Confirm below overrides this decision and proceeds the instrument to NGCH — record a reason before overriding.
            </div>
          </div>
        )}
      </div>

      {/* Action footer */}
      <div className={`relative z-20 shrink-0 border-t ${th.border} px-6 py-3 ${th.foot} backdrop-blur`}>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <button type="button" onClick={() => setReasonOpen(o => !o)}
              className={`w-full flex items-center justify-between border rounded-lg px-3 py-2 text-xs focus:outline-none transition-colors ${th.sel}`}
            >
              <span className={reason ? th.val : th.lbl}>{reason || 'Select reason (required)…'}</span>
              <span className={`ml-2 shrink-0 ${th.lbl}`}>{reasonOpen ? '▲' : '▼'}</span>
            </button>
            {reasonOpen && (
              <div className={`absolute bottom-full mb-1 left-0 right-0 z-50 rounded-lg border shadow-2xl overflow-y-auto ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`} style={{ maxHeight: 320 }}>
                {/* Confirmation Reasons — enables Confirm */}
                <div>
                  <div className={`px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>Confirmation Reasons</div>
                  {CONFIRM_REASONS.map(r => (
                    <button key={r} type="button" onMouseDown={() => pickReason(r, 'confirm')}
                      className={`w-full text-left px-3 py-2 text-xs transition-colors ${r === reason ? (isDark ? 'bg-emerald-400/12 text-emerald-300' : 'bg-emerald-50 text-emerald-700') : (isDark ? 'hover:bg-emerald-400/8 text-slate-300' : 'hover:bg-emerald-50 text-slate-700')}`}
                    >{r}</button>
                  ))}
                </div>
                {/* Rejection Reasons — enables Reject. Not shown on STP Rejected (no Reject button there). */}
                {!isRejected && Object.entries(REJECT_REASONS_GROUPED).map(([group, reasons]) => (
                  <div key={group}>
                    <div className={`px-3 pt-3 pb-1 text-[9px] font-semibold uppercase tracking-widest ${isDark ? 'text-red-400/70' : 'text-red-600'}`}>{group} — Rejection Reasons</div>
                    {reasons.map(r => (
                      <button key={r} type="button" onMouseDown={() => pickReason(r, 'reject')}
                        className={`w-full text-left px-3 py-2 text-xs transition-colors ${r === reason ? (isDark ? 'bg-red-400/12 text-red-300' : 'bg-red-50 text-red-700') : (isDark ? 'hover:bg-red-400/8 text-slate-300' : 'hover:bg-red-50 text-slate-700')}`}
                      >{r}</button>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </div>

          {!isRejected && (
            <button onClick={() => decide('REJECTED')} disabled={reasonCategory !== 'reject'}
              className="shrink-0 px-5 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >✕ Reject</button>
          )}
          <button onClick={() => decide('CONFIRMED')} disabled={reasonCategory !== 'confirm'}
            className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >{isRejected ? '✓ Confirm (Override)' : '✓ Confirm'}</button>
        </div>
      </div>
    </div>
  )
}
