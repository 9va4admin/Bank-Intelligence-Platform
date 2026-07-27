/**
 * OutwardReviewPanel — 3-stage wizard for outward instruments.
 *
 * Stage 1 — VERIFICATION  (ops_reviewer): read-only review; each OCR field has an
 *   info icon showing AI extraction detail (model, confidence, raw value).
 *   Action: Approve to Validation, or Reject outright.
 *
 * Stage 2 — VALIDATION  (ops_manager / senior reviewer): editable form pre-populated
 *   from OCR. Fields carry STP badge (AI high-confidence, untouched) or MANUAL badge
 *   (AI uncertain or edited). Diff indicator on changed fields. Save advances to
 *   Submission.
 *
 * Stage 3 — SUBMISSION  (ops_manager): read-only summary. MANUAL fields listed
 *   prominently. Final Submit CTA → fires to NGCH.
 */
import { useEffect, useState, useRef } from 'react'
import ChequeImageViewer from './ChequeImageViewer'
import { getReturnReasons } from '../data/returnReasons'

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

function reasonColor(isDark, key) {
  return REASON_COLORS[key] || (isDark ? 'bg-slate-400/10 border-slate-400/20 text-slate-300' : 'bg-slate-100 border-slate-300 text-slate-600')
}

// ─── AI Extraction Popover ───────────────────────────────────────────────────

function ExtractionPopover({ meta, isDark, onClose }) {
  const ref = useRef()
  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) onClose() }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])

  const confPct = Math.round((meta.extracted_confidence ?? 1) * 100)
  const confColor = confPct >= 92 ? 'text-emerald-400' : confPct >= 80 ? 'text-amber-400' : 'text-red-400'

  return (
    <div ref={ref}
      className={`absolute z-50 bottom-full mb-1 left-0 w-64 rounded-xl border shadow-2xl p-3 text-[11px] ${isDark ? 'bg-navy-900 border-white/15' : 'bg-white border-slate-200'}`}
    >
      <div className={`text-[9px] uppercase tracking-widest mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>AI Extraction Detail</div>
      <div className="space-y-1.5">
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Extracted by</span>
          <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{meta.extracted_by ?? 'GOT-OCR2.0'}</span>
        </div>
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Raw value</span>
          <span className={`font-mono font-semibold ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{String(meta.extracted_value ?? '—')}</span>
        </div>
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Confidence</span>
          <span className={`font-mono font-semibold ${confColor}`}>{confPct}%</span>
        </div>
        {meta.corrected_by && (
          <div className={`pt-1.5 mt-1 border-t ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
            <div className="flex justify-between">
              <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Corrected by</span>
              <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{meta.corrected_by}</span>
            </div>
            {meta.corrected_at && (
              <div className="flex justify-between mt-1">
                <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Corrected at</span>
                <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{meta.corrected_at}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Source badge ────────────────────────────────────────────────────────────

function SourceBadge({ source, isDark }) {
  if (source === 'STP') return (
    <span className={`inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700'}`}>STP</span>
  )
  return (
    <span className={`inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-400 text-amber-700'}`}>MANUAL</span>
  )
}

// ─── Field row with info icon (Verification stage) ───────────────────────────

function VerifyFieldRow({ label, meta, isDark }) {
  const [open, setOpen] = useState(false)
  const val = String(meta.actual_value ?? meta.extracted_value ?? '—')
  const isAltered = typeof meta.actual_value === 'boolean'
    ? (meta.actual_value ? '⚠ DETECTED' : '✓ None')
    : null
  const display = isAltered ?? val

  return (
    <div className="flex flex-col relative">
      <div className="flex items-center gap-1">
        <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          className={`text-[10px] w-4 h-4 flex items-center justify-center rounded-full transition-colors ${isDark ? 'text-slate-500 hover:text-sky-400 hover:bg-sky-400/10' : 'text-slate-400 hover:text-sky-600 hover:bg-sky-100'}`}
          title="AI extraction detail"
        >ⓘ</button>
        {open && <ExtractionPopover meta={meta} isDark={isDark} onClose={() => setOpen(false)} />}
      </div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className={`text-xs font-mono ${label === 'Alterations' && meta.extracted_value ? 'text-red-400 font-semibold' : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{display}</span>
        <SourceBadge source={meta.source ?? 'STP'} isDark={isDark} />
      </div>
    </div>
  )
}

// ─── Editable field row (Validation stage) ───────────────────────────────────

function EditFieldRow({ label, fieldKey, meta, isDark, onEdit }) {
  const isBoolean = typeof meta.extracted_value === 'boolean'
  const val = meta.actual_value ?? meta.extracted_value
  const isDirty = String(meta.actual_value) !== String(meta.extracted_value)

  if (isBoolean) {
    return (
      <div className="flex flex-col">
        <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
        <div className="flex items-center gap-2 mt-0.5">
          <select
            value={val ? 'yes' : 'no'}
            onChange={e => onEdit(fieldKey, e.target.value === 'yes')}
            className={`text-xs px-2 py-1 rounded border focus:outline-none ${isDark ? 'bg-white/5 border-white/15 text-slate-200' : 'bg-white border-slate-300 text-slate-800'}`}
          >
            <option value="no">✓ None</option>
            <option value="yes">⚠ DETECTED</option>
          </select>
          <SourceBadge source={meta.source} isDark={isDark} />
          {isDirty && <span className={`text-[9px] font-semibold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>changed</span>}
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col">
      <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
      <div className="flex items-center gap-1.5 mt-0.5">
        <input
          type="text"
          value={String(val ?? '')}
          onChange={e => onEdit(fieldKey, e.target.value)}
          className={`flex-1 text-xs font-mono px-2 py-1 rounded border focus:outline-none transition-colors ${
            isDirty
              ? (isDark ? 'border-amber-400/50 bg-amber-400/5 text-amber-300' : 'border-amber-400 bg-amber-50 text-amber-800')
              : (isDark ? 'bg-white/5 border-white/15 text-slate-200' : 'bg-white border-slate-300 text-slate-800')
          }`}
        />
        <SourceBadge source={meta.source} isDark={isDark} />
        {isDirty && <span className={`text-[9px] font-semibold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>↺</span>}
      </div>
      {isDirty && (
        <div className={`text-[9px] mt-0.5 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>
          Extracted: <span className="font-mono">{String(meta.extracted_value)}</span>
        </div>
      )}
    </div>
  )
}

// ─── CTS-2010 Compliance block ────────────────────────────────────────────────

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

// ─── Stage indicator ──────────────────────────────────────────────────────────

function StageBar({ stage, isDark }) {
  const stages = ['Verification', 'Validation', 'Submission']
  const idx = stages.indexOf(stage)
  return (
    <div className="flex items-center gap-0 py-2 px-6">
      {stages.map((s, i) => {
        const done    = i < idx
        const active  = i === idx
        const pending = i > idx
        return (
          <div key={s} className="flex items-center flex-1">
            <div className="flex items-center gap-1.5">
              <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ${
                done    ? 'bg-emerald-500 text-white' :
                active  ? (isDark ? 'bg-gold-400 text-navy-950' : 'bg-amber-500 text-white') :
                           (isDark ? 'bg-white/10 text-slate-500' : 'bg-slate-200 text-slate-400')
              }`}>
                {done ? '✓' : i + 1}
              </div>
              <span className={`text-[10px] font-semibold whitespace-nowrap ${
                done    ? 'text-emerald-400' :
                active  ? (isDark ? 'text-gold-400' : 'text-amber-600') :
                           (isDark ? 'text-slate-500' : 'text-slate-400')
              }`}>{s}</span>
            </div>
            {i < stages.length - 1 && (
              <div className={`flex-1 h-px mx-2 ${done ? 'bg-emerald-500/50' : (isDark ? 'bg-white/10' : 'bg-slate-200')}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function OutwardReviewPanel({ item, tabKind, onDecision, isDark }) {
  // Inner tab (within Verification stage)
  const [verifyTab, setVerifyTab] = useState('overview')
  // Wizard stage
  const [stage, setStage] = useState('Verification')
  // Reason for Verification reject/confirm footer
  const [reason, setReason] = useState('')
  const [reasonCategory, setReasonCategory] = useState(null)
  const [reasonOpen, setReasonOpen] = useState(false)
  // Editable field meta (Validation stage) — deep copy from item.fields_meta
  const [fieldsMeta, setFieldsMeta] = useState(null)

  useEffect(() => {
    setReason('')
    setReasonCategory(null)
    setVerifyTab('overview')
    setStage('Verification')
    setFieldsMeta(null)
  }, [item?.instrument_id])

  // Initialise fieldsMeta when entering Validation
  useEffect(() => {
    if (stage === 'Validation' && item && !fieldsMeta) {
      setFieldsMeta(JSON.parse(JSON.stringify(item.fields_meta ?? buildFallbackMeta(item.ocr_fields ?? {}))))
    }
  }, [stage, item, fieldsMeta])

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
  const rc = reasonColor(isDark, item.reason)

  // Fields meta — use item.fields_meta if available, else build fallback
  const activeMeta = fieldsMeta ?? buildFallbackMeta(item.ocr_fields ?? {})

  const REJECT_REASONS_GROUPED = Object.fromEntries(
    Object.entries(getReturnReasons()).filter(([group]) => group !== 'Drawee Bank')
  )

  function pickReason(r, category) {
    setReason(r)
    setReasonCategory(category)
    setReasonOpen(false)
  }

  function handleVerifyDecision(action) {
    const requiredCategory = action === 'CONFIRMED' ? 'confirm' : 'reject'
    if (!reason || reasonCategory !== requiredCategory) return
    if (action === 'CONFIRMED') {
      setStage('Validation')
    } else {
      onDecision(item.instrument_id, 'REJECTED', reason)
    }
  }

  function handleEditField(key, value) {
    setFieldsMeta(prev => {
      const next = { ...prev, [key]: { ...prev[key], actual_value: value, source: 'MANUAL' } }
      return next
    })
  }

  function handleValidationSave() {
    // Annotate corrected_by / corrected_at for changed fields
    const now = new Date().toLocaleTimeString()
    setFieldsMeta(prev => {
      const next = { ...prev }
      Object.keys(next).forEach(k => {
        if (String(next[k].actual_value) !== String(next[k].extracted_value) && !next[k].corrected_by) {
          next[k] = { ...next[k], corrected_by: 'ops.reviewer', corrected_at: now }
        }
      })
      return next
    })
    setStage('Submission')
  }

  function handleFinalSubmit() {
    onDecision(item.instrument_id, 'CONFIRMED', reason || 'Verified + Validated — NGCH submission')
  }

  // ── Verification stage ─────────────────────────────────────────────────────
  const verifyTabs = isRejected
    ? ['overview', 'cheque', 'ai analysis', 'passport', 'reject decision']
    : ['overview', 'cheque', 'ai analysis', 'passport']

  const cheqViews = [
    { key: 'BFB', label: 'Front B/W',  url: item.front_bw_url   ?? null },
    { key: 'BBB', label: 'Back B/W',   url: item.back_bw_url    ?? null },
    { key: 'BFG', label: 'Front Gray', url: item.front_gray_url ?? null },
  ]

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Instrument header — always visible */}
      <div className={`px-6 pt-3 pb-0 border-b ${th.border} shrink-0`}>
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className={`text-[12px] font-mono font-semibold ${th.id}`}>{item.instrument_id}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.account_display}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.payee_display}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${rc}`}>{item.reason_label}</span>
          <span className={`text-[10px] ml-auto ${th.meta}`}>{item.amount_range}</span>
        </div>
        <div className={`text-[11px] mb-1 ${th.meta}`}>{item.bank} · {item.branch} · <span className="font-mono">{item.pu}</span> · Lot {item.lot_number}</div>

        {/* Stage progress bar */}
        <StageBar stage={stage} isDark={isDark} />

        {/* Confidence strip — only on Verification */}
        {stage === 'Verification' && (
          <div className="flex items-center gap-3 py-1.5">
            {[
              { label: 'OCR',   pct: item.ocr_confidence,    bar: item.ocr_confidence >= 0.92 ? 'bg-emerald-500' : item.ocr_confidence >= 0.80 ? 'bg-amber-400' : 'bg-red-400' },
              { label: 'CTS',   pct: item.vision_compliance,  bar: item.vision_compliance >= 0.85 ? 'bg-emerald-500' : item.vision_compliance >= 0.70 ? 'bg-amber-400' : 'bg-red-400' },
              { label: 'MICR',  pct: item.micr_confidence,    bar: item.micr_confidence >= 0.95 ? 'bg-emerald-500' : 'bg-amber-400' },
            ].map(({ label, pct, bar }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className={`text-[9px] font-semibold uppercase tracking-wider ${th.lbl} w-10`}>{label}</span>
                <div className={`w-16 h-1 ${th.barBg} rounded-full overflow-hidden`}>
                  <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct * 100}%` }} />
                </div>
                <span className={`text-[10px] font-mono ${th.lbl}`}>{Math.round(pct * 100)}%</span>
              </div>
            ))}
          </div>
        )}

        {/* Inner tabs — only on Verification */}
        {stage === 'Verification' && (
          <div className="flex gap-1 pt-1">
            {verifyTabs.map(t => (
              <button key={t} onClick={() => setVerifyTab(t)}
                className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${verifyTab === t ? th.tabActive : th.tabIdle} ${t === 'reject decision' ? (isDark ? 'text-red-300' : 'text-red-600') : ''}`}
              >{t}</button>
            ))}
          </div>
        )}

        {/* Stage label — Validation & Submission */}
        {stage !== 'Verification' && (
          <div className={`text-[11px] pb-2 font-semibold ${isDark ? 'text-gold-400' : 'text-amber-600'}`}>
            {stage === 'Validation' ? 'Validation — review and edit extracted fields' : 'Submission — final review before NGCH filing'}
          </div>
        )}
      </div>

      {/* ── VERIFICATION content ────────────────────────────────────────────── */}
      {stage === 'Verification' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {verifyTab === 'overview' && (
            <>
              <div className={`flex items-start gap-3 rounded-xl border px-4 py-2.5 ${rc}`}>
                <span className="text-base mt-0.5">{isRejected ? '⛔' : '⚠'}</span>
                <div>
                  <div className="text-xs font-semibold">{isRejected ? 'Auto-rejected: ' : 'Flagged: '}{item.reason_label}</div>
                  <div className="text-[11px] opacity-70 mt-0.5">
                    {isRejected
                      ? 'Rejected by the STP compliance engine — see Reject Decision tab.'
                      : 'Outward instrument held for human review before NGCH submission.'}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'OCR',     val: `${Math.round(item.ocr_confidence * 100)}%`,   sub: 'confidence' },
                  { label: 'CTS-2010',val: `${Math.round(item.vision_compliance * 100)}%`, sub: 'compliance' },
                  { label: 'MICR',    val: `${Math.round(item.micr_confidence * 100)}%`,   sub: 'extraction' },
                ].map(({ label, val, sub }) => (
                  <div key={label} className={`rounded-xl p-3 text-center ${th.glass}`}>
                    <div className={`text-[10px] ${th.lbl} uppercase tracking-wide mb-0.5`}>{label}</div>
                    <div className={`text-3xl font-mono font-bold ${th.heading}`}>{val}</div>
                    <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                  </div>
                ))}
              </div>

              {/* OCR fields with info icons */}
              <div className={`rounded-xl p-4 ${th.glass}`}>
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>OCR Extracted Fields · click ⓘ for AI detail</div>
                <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                  {[
                    ['Date',             'date'],
                    ['Payee',            'payee'],
                    ['Amount (figures)', 'amount_figures'],
                    ['Amount (words)',   'amount_words'],
                    ['MICR Code',        'micr'],
                    ['Alterations',      'alterations'],
                  ].map(([label, key]) => (
                    <VerifyFieldRow key={key} label={label} meta={activeMeta[key] ?? { extracted_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }} isDark={isDark} />
                  ))}
                </div>
              </div>

              <CompliancePanel item={item} isDark={isDark} />
            </>
          )}

          {verifyTab === 'cheque' && (
            <ChequeImageViewer views={cheqViews} fields={item.ocr_fields} isDark={isDark} compact={false} title={item.instrument_id} />
          )}

          {verifyTab === 'ai analysis' && (
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-2`}>Model Stack — Outward Capture</div>
              {[
                ['OCR',    'GOT-OCR2.0',            item.ocr_confidence],
                ['Vision', 'Qwen2-VL 72B · CTS-2010', item.vision_compliance],
                ['MICR',   'GOT-OCR2.0 · MICR line', item.micr_confidence],
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

          {verifyTab === 'passport' && (() => {
            const steps = [
              { label: 'Scanner Capture',        icon: '📷', note: `${item.scanner_id} · CTS-2010 image capture`, status: 'done' },
              { label: 'Image Quality (IQA)',     icon: '🖼',  note: item.vision_compliance >= 0.85 ? 'IQA passed' : 'IQA borderline — flagged', status: item.vision_compliance >= 0.85 ? 'done' : 'warn' },
              { label: 'MICR Line Extraction',    icon: '🔢', note: `MICR: ${item.ocr_fields.micr} · ${Math.round(item.micr_confidence * 100)}% confidence`, status: 'done' },
              { label: 'CTS-2010 Compliance',     icon: '✅', note: item.checks.cts_valid ? 'Compliant' : 'Non-compliant — see Overview', status: item.checks.cts_valid ? 'done' : 'warn' },
              { label: 'Lot Assignment',          icon: '📦', note: item.lot_number, status: 'done' },
              { label: isRejected ? 'Auto-Rejected by STP Engine' : 'Routed to Human Review', icon: isRejected ? '⛔' : '👤', note: item.reason_label, status: isRejected ? 'risk' : 'review' },
              { label: 'Awaiting Verification',   icon: '⏳', note: 'Step 1 of 3', status: 'pending' },
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

          {verifyTab === 'reject decision' && isRejected && (
            <div className={`rounded-xl border-2 p-4 ${isDark ? 'border-red-500/30 bg-red-500/5' : 'border-red-300 bg-red-50'}`}>
              <div className={`text-[10px] uppercase tracking-widest mb-3 ${isDark ? 'text-red-300' : 'text-red-600'}`}>
                Automated STP Rejection — What The Engine Decided
              </div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                {[
                  ['Engine',               item.stp_decision.engine],
                  ['Rule fired',           item.stp_decision.rule],
                  ['Confidence',           `${Math.round(item.stp_decision.confidence * 100)}%`],
                  ['Auto-reject threshold',`${Math.round(item.stp_decision.threshold * 100)}%`],
                  ['Decided at',           item.stp_decision.decided_at],
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
            </div>
          )}
        </div>
      )}

      {/* ── VALIDATION content ──────────────────────────────────────────────── */}
      {stage === 'Validation' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className={`text-xs ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
            All fields are pre-populated from OCR extraction. Edit any field that needs correction — changed fields are highlighted and marked <span className={`font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>MANUAL</span>. Original extracted values remain visible below each edited field.
          </div>

          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Editable Fields</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-4">
              {[
                ['Date',             'date'],
                ['Payee',            'payee'],
                ['Amount (figures)', 'amount_figures'],
                ['Amount (words)',   'amount_words'],
                ['MICR Code',        'micr'],
                ['Alterations',      'alterations'],
              ].map(([label, key]) => (
                <EditFieldRow
                  key={key} label={label} fieldKey={key}
                  meta={activeMeta[key] ?? { extracted_value: item.ocr_fields?.[key], actual_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }}
                  isDark={isDark} onEdit={handleEditField}
                />
              ))}
            </div>
          </div>

          {/* Summary of changes */}
          {(() => {
            const changed = Object.entries(activeMeta).filter(([, m]) => String(m.actual_value) !== String(m.extracted_value))
            if (changed.length === 0) return null
            return (
              <div className={`rounded-xl p-3 ${isDark ? 'bg-amber-400/8 border border-amber-400/20' : 'bg-amber-50 border border-amber-300'}`}>
                <div className={`text-[10px] uppercase tracking-widest mb-2 ${isDark ? 'text-amber-400' : 'text-amber-700'}`}>{changed.length} field{changed.length > 1 ? 's' : ''} modified</div>
                {changed.map(([k, m]) => (
                  <div key={k} className={`text-[11px] ${isDark ? 'text-amber-300' : 'text-amber-800'}`}>
                    <span className="font-semibold">{k}</span>: <span className="line-through opacity-60">{String(m.extracted_value)}</span> → <span className="font-mono font-semibold">{String(m.actual_value)}</span>
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
      )}

      {/* ── SUBMISSION content ──────────────────────────────────────────────── */}
      {stage === 'Submission' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className={`flex items-start gap-2 rounded-xl border px-4 py-3 ${isDark ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-emerald-50 border-emerald-300'}`}>
            <span className="text-base">✅</span>
            <div>
              <div className={`text-xs font-semibold ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>Ready for NGCH filing</div>
              <div className={`text-[11px] mt-0.5 ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>Verification and Validation complete. Review final values below before submission.</div>
            </div>
          </div>

          {/* Final field values */}
          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Final Values — what will be filed to NGCH</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3">
              {[
                ['Date',             'date'],
                ['Payee',            'payee'],
                ['Amount (figures)', 'amount_figures'],
                ['Amount (words)',   'amount_words'],
                ['MICR Code',        'micr'],
                ['Alterations',      'alterations'],
              ].map(([label, key]) => {
                const m = activeMeta[key] ?? {}
                const val = String(m.actual_value ?? m.extracted_value ?? item.ocr_fields?.[key] ?? '—')
                const isDirty = String(m.actual_value) !== String(m.extracted_value)
                return (
                  <div key={key} className="flex flex-col">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-[10px] ${th.lbl}`}>{label}</span>
                      <SourceBadge source={m.source ?? 'STP'} isDark={isDark} />
                    </div>
                    <span className={`text-xs font-mono mt-0.5 font-semibold ${isDirty ? (isDark ? 'text-amber-300' : 'text-amber-700') : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{val}</span>
                  </div>
                )
              })}
            </div>
          </div>

          {/* MANUAL fields summary */}
          {(() => {
            const manualFields = Object.entries(activeMeta).filter(([, m]) => m.source === 'MANUAL')
            if (manualFields.length === 0) return (
              <div className={`rounded-xl p-3 text-xs ${isDark ? 'bg-emerald-500/5 border border-emerald-500/15 text-emerald-400' : 'bg-emerald-50 border border-emerald-200 text-emerald-700'}`}>
                All fields confirmed as STP — no manual corrections.
              </div>
            )
            return (
              <div className={`rounded-xl p-3 ${isDark ? 'bg-amber-400/8 border border-amber-400/20' : 'bg-amber-50 border border-amber-300'}`}>
                <div className={`text-[10px] uppercase tracking-widest mb-2 ${isDark ? 'text-amber-400' : 'text-amber-700'}`}>MANUAL fields ({manualFields.length})</div>
                {manualFields.map(([k, m]) => (
                  <div key={k} className={`text-[11px] ${isDark ? 'text-amber-300' : 'text-amber-800'}`}>
                    <span className="font-semibold">{k}</span>
                    {String(m.actual_value) !== String(m.extracted_value) && (
                      <> · corrected from <span className="line-through opacity-60 font-mono">{String(m.extracted_value)}</span> → <span className="font-mono font-semibold">{String(m.actual_value)}</span></>
                    )}
                    {m.corrected_by && <span className={`ml-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>by {m.corrected_by} at {m.corrected_at}</span>}
                  </div>
                ))}
              </div>
            )
          })()}
        </div>
      )}

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <div className={`relative z-20 shrink-0 border-t ${th.border} px-6 py-3 ${th.foot} backdrop-blur`}>

        {/* Verification footer */}
        {stage === 'Verification' && (
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
                  <div>
                    <div className={`px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>Confirmation Reasons</div>
                    {CONFIRM_REASONS.map(r => (
                      <button key={r} type="button" onMouseDown={() => pickReason(r, 'confirm')}
                        className={`w-full text-left px-3 py-2 text-xs transition-colors ${r === reason ? (isDark ? 'bg-emerald-400/12 text-emerald-300' : 'bg-emerald-50 text-emerald-700') : (isDark ? 'hover:bg-emerald-400/8 text-slate-300' : 'hover:bg-emerald-50 text-slate-700')}`}
                      >{r}</button>
                    ))}
                  </div>
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
              <button onClick={() => handleVerifyDecision('REJECTED')} disabled={reasonCategory !== 'reject'}
                className="shrink-0 px-5 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
              >✕ Reject</button>
            )}
            <button onClick={() => handleVerifyDecision('CONFIRMED')} disabled={reasonCategory !== 'confirm'}
              className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >{isRejected ? '✓ Override → Validation' : '✓ Approve → Validation'}</button>
          </div>
        )}

        {/* Validation footer */}
        {stage === 'Validation' && (
          <div className="flex items-center justify-between gap-3">
            <button onClick={() => setStage('Verification')}
              className={`px-4 py-2 rounded-lg border text-xs font-semibold transition-all ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
            >← Back to Verification</button>
            <button onClick={handleValidationSave}
              className="px-6 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all whitespace-nowrap"
            >Save & Proceed to Submission →</button>
          </div>
        )}

        {/* Submission footer */}
        {stage === 'Submission' && (
          <div className="flex items-center justify-between gap-3">
            <button onClick={() => setStage('Validation')}
              className={`px-4 py-2 rounded-lg border text-xs font-semibold transition-all ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
            >← Back to Validation</button>
            <button onClick={handleFinalSubmit}
              className="px-8 py-2 rounded-lg border border-emerald-500/60 bg-emerald-500/30 text-emerald-300 text-xs font-bold hover:bg-emerald-500/40 transition-all whitespace-nowrap"
            >🚀 Submit to NGCH</button>
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Helper: build fallback meta from flat ocr_fields ─────────────────────────
function buildFallbackMeta(ocr) {
  const fields = ['date', 'payee', 'amount_figures', 'amount_words', 'micr', 'alterations']
  const out = {}
  fields.forEach(k => {
    out[k] = {
      extracted_value:      ocr[k] ?? '',
      extracted_confidence: 0.95,
      extracted_by:         'GOT-OCR2.0',
      actual_value:         ocr[k] ?? '',
      source:               'STP',
      corrected_by:         null,
      corrected_at:         null,
    }
  })
  return out
}
