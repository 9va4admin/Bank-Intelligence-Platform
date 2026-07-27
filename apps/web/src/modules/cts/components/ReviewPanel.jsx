/**
 * ReviewPanel — Inward Q detail/decision panel.
 *
 * 3-stage wizard:
 *   Stage 1 — VERIFICATION  (ops_reviewer): existing Overview/Cheque/AI/Passport tabs,
 *     plus per-field ⓘ info icon showing AI extraction detail popover.
 *     Footer: Approve → Validation (green) | Return (red — always available, any stage)
 *
 *   Stage 2 — VALIDATION  (ops_manager): editable OCR form, STP/MANUAL badges per field,
 *     diff indicator + original extracted value shown below changed fields.
 *     Footer: ← Back | Return | Save → Submission
 *
 *   Stage 3 — SUBMISSION  (ops_manager): read-only final values, MANUAL fields summary,
 *     Return (red) | Confirm (green, 2-sec cancellable countdown → files to NGCH)
 *
 * IET Timer stays in the header at ALL stages — it's always time-critical.
 * Return reason combobox appears in Verification footer and in Submission footer.
 * "Confirm" is only available in Stage 3 — ensures Validation has been reviewed.
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import IETTimer from './IETTimer'
import FraudGauge from './FraudGauge'
import ShapExplainer from './ShapExplainer'
import ChequeImageViewer from './ChequeImageViewer'
import { getReturnReasons, getReasonByLabel } from '../data/returnReasons'

const PROCEED_REASONS_GROUP = 'Proceed Reason'
const PROCEED_REASONS = [
  'Second Signature Verified',
  'Exception Approved by Manager',
  'Account Holder Confirmed',
  'Minor OCR Variance — Accepted',
  'Risk Accepted',
  'OPA Override Authorized by Compliance',
  'IET Constraint — Proceed Before Expiry',
]

const RECENT_KEY = 'astra-recent-return-reasons'
const getRecentReasons = () => {
  try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] }
}
const saveRecentReason = (reason) => {
  const updated = [reason, ...getRecentReasons().filter(r => r !== reason)].slice(0, 3)
  localStorage.setItem(RECENT_KEY, JSON.stringify(updated))
}

function getReasonColors(isDark) {
  return {
    SIGNATURE_LOW_CONFIDENCE:  isDark ? 'bg-amber-400/10 border-amber-400/30 text-amber-300' : 'bg-amber-100 border-amber-400 text-amber-700',
    FRAUD_SCORE_HIGH:          isDark ? 'bg-red-400/10 border-red-400/30 text-red-300'    : 'bg-red-100 border-red-400 text-red-700',
    OCR_LOW_CONFIDENCE:        isDark ? 'bg-orange-400/10 border-orange-400/30 text-orange-300' : 'bg-orange-100 border-orange-400 text-orange-700',
    VAULT_MISS:                isDark ? 'bg-purple-400/10 border-purple-400/30 text-purple-300' : 'bg-purple-100 border-purple-400 text-purple-700',
    HIGH_VALUE_DUAL_APPROVAL:  isDark ? 'bg-sky-400/10 border-sky-400/30 text-sky-300'    : 'bg-sky-100 border-sky-400 text-sky-700',
  }
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

// ─── Field row with info icon (Verification stage) ────────────────────────────

function VerifyFieldRow({ label, fieldKey, meta, isDark }) {
  const [open, setOpen] = useState(false)
  const isBoolean = typeof (meta.extracted_value) === 'boolean'
  const val = isBoolean
    ? (meta.actual_value ? '⚠ DETECTED' : '✓ None')
    : String(meta.actual_value ?? meta.extracted_value ?? '—')

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
        <span className={`text-xs font-mono ${fieldKey === 'alterations' && meta.extracted_value ? 'text-red-400 font-semibold' : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{val}</span>
        <SourceBadge source={meta.source ?? 'STP'} isDark={isDark} />
      </div>
    </div>
  )
}

// ─── Editable field row (Validation stage) ────────────────────────────────────

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

// ─── Stage progress bar ───────────────────────────────────────────────────────

function StageBar({ stage, isDark }) {
  const stages = ['Verification', 'Validation', 'Submission']
  const idx = stages.indexOf(stage)
  return (
    <div className="flex items-center gap-0 py-1.5">
      {stages.map((s, i) => {
        const done    = i < idx
        const active  = i === idx
        return (
          <div key={s} className="flex items-center flex-1">
            <div className="flex items-center gap-1">
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

// ─── Signature panel (used in Verification stage) ────────────────────────────

function SigPanel({ item, isDark }) {
  const muted  = isDark ? 'text-slate-400' : 'text-slate-500'
  const noteBg = isDark ? 'bg-white/5' : 'bg-slate-50'
  const barBg  = isDark ? 'bg-white/5' : 'bg-slate-100'
  const tick   = isDark ? 'text-slate-600' : 'text-slate-400'

  if (!item.sig_specimen_available) {
    return (
      <div className="rounded-xl border border-purple-400/30 bg-purple-400/5 p-4">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Signature Verification</div>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🔍</span>
          <div>
            <div className="text-sm font-semibold text-purple-300">No Specimen On File</div>
            <div className={`text-xs ${muted} mt-0.5`}>{item.sig_specimen_label}</div>
          </div>
        </div>
        <div className={`text-xs leading-relaxed ${noteBg} rounded-lg p-3 ${muted}`}>
          Vault miss — no signature specimen found for {item.account_display} in the Signature Vault.
          Routed to human review per policy. Auto-return is <span className="text-purple-300 font-medium">never</span> permitted on vault miss.
        </div>
      </div>
    )
  }

  const matchPct = Math.round((item.sig_match_score ?? 0) * 100)
  const color = matchPct < 70 ? 'text-red-400' : matchPct < 85 ? 'text-amber-400' : 'text-emerald-400'
  const borderColor = matchPct < 70 ? 'border-red-400/30 bg-red-400/5' : matchPct < 85 ? 'border-amber-400/30 bg-amber-400/5' : 'border-emerald-400/30 bg-emerald-400/5'

  return (
    <div className={`rounded-xl border px-4 py-3 ${borderColor}`}>
      <div className="flex items-center gap-4">
        <div className="shrink-0 flex items-baseline gap-1">
          <span className={`text-2xl font-bold font-mono ${color}`}>{matchPct}%</span>
          <span className="text-[10px] text-slate-500">match</span>
        </div>
        <div className="flex-1 space-y-1">
          <div className={`h-1.5 ${barBg} rounded-full overflow-hidden`}>
            <div className={`h-full rounded-full transition-all ${matchPct >= 85 ? 'bg-emerald-400' : matchPct >= 70 ? 'bg-amber-400' : 'bg-red-400'}`}
              style={{ width: `${matchPct}%` }} />
          </div>
          <div className={`flex justify-between text-[10px] ${tick}`}>
            <span>0%</span>
            <span>threshold: 85%</span>
            <span>100%</span>
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest">Siamese SNN</div>
          <div className="text-[10px] text-slate-500">{item.sig_specimen_label}</div>
        </div>
      </div>
    </div>
  )
}

// ─── Return reason combobox (reused in Verification + Submission footers) ─────

function ReturnReasonPicker({ returnReason, setReturnReason, reasonOpen, setReasonOpen, reasonSearch, setReasonSearch, reasonDropdownRef, confirming, isDark }) {
  const th = {
    border:   isDark ? 'border-white/10' : 'border-slate-200',
    val:      isDark ? 'text-slate-300'  : 'text-slate-700',
    lbl:      isDark ? 'text-slate-500'  : 'text-slate-400',
    footNote: isDark ? 'text-slate-600'  : 'text-slate-400',
    sel:      isDark ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-white border-slate-300 text-slate-700',
  }
  const RETURN_REASONS_GROUPED = getReturnReasons()
  const ALL_REASONS = [...PROCEED_REASONS, ...Object.values(RETURN_REASONS_GROUPED).flat()].sort()
  const selectedReason = getReasonByLabel(returnReason)

  return (
    <div className="relative flex-1" ref={reasonDropdownRef}>
      <button
        type="button"
        onClick={() => { setReasonOpen(o => !o); setReasonSearch('') }}
        disabled={!!confirming}
        className={`w-full flex items-center justify-between border rounded-lg px-3 py-2 text-xs focus:outline-none transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${th.sel}`}
      >
        <span className={`flex items-center gap-2 min-w-0 ${returnReason ? th.val : th.lbl}`}>
          <span className="truncate">{returnReason || 'Select Return Reason (for Return action)…'}</span>
          {selectedReason && (
            <span className={`shrink-0 text-[9px] font-bold font-mono px-1.5 py-0.5 rounded border ${
              selectedReason.customerFault
                ? (isDark ? 'bg-red-900/40 border-red-700/50 text-red-300' : 'bg-red-100 border-red-300 text-red-700')
                : (isDark ? 'bg-sky-900/40 border-sky-700/50 text-sky-300' : 'bg-sky-100 border-sky-300 text-sky-700')
            }`}>{selectedReason.code}</span>
          )}
        </span>
        <span className={`ml-2 shrink-0 ${th.lbl}`}>{reasonOpen ? '▲' : '▼'}</span>
      </button>

      {reasonOpen && (
        <div className={`absolute bottom-full mb-1 left-0 right-0 z-50 rounded-lg border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
          <div className={`px-3 py-2 border-b ${th.border}`}>
            <input autoFocus type="text" value={reasonSearch} onChange={e => setReasonSearch(e.target.value)}
              placeholder="Search reasons…"
              className={`w-full text-xs bg-transparent outline-none ${th.val}`}
            />
          </div>
          <div className="max-h-52 overflow-y-auto">
            {!reasonSearch && getRecentReasons().length > 0 && (
              <div>
                <div className={`px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest ${th.footNote}`}>Recent</div>
                {getRecentReasons().map(r => {
                  const entry = getReasonByLabel(r)
                  return (
                    <button key={`recent-${r}`} type="button"
                      onMouseDown={() => { setReturnReason(r); setReasonOpen(false); setReasonSearch('') }}
                      className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between gap-2 ${isDark ? 'hover:bg-white/5 text-gold-400' : 'hover:bg-amber-50 text-amber-600'}`}
                    >
                      <span className="truncate">{r}</span>
                      {entry && <span className={`shrink-0 text-[9px] font-mono font-bold px-1 rounded ${entry.customerFault ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>{entry.code}</span>}
                    </button>
                  )
                })}
                <div className={`mx-3 border-t ${th.border} my-1`} />
              </div>
            )}
            {!reasonSearch && (
              <div>
                <div className={`px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest ${isDark ? 'text-amber-400/70' : 'text-amber-600'}`}>{PROCEED_REASONS_GROUP}</div>
                {PROCEED_REASONS.map(r => (
                  <button key={`p-${r}`} type="button"
                    onMouseDown={() => { setReturnReason(r); setReasonOpen(false); setReasonSearch('') }}
                    className={`w-full text-left px-3 py-2 text-xs transition-colors ${r === returnReason ? (isDark ? 'bg-amber-400/12 text-amber-300' : 'bg-amber-50 text-amber-700') : (isDark ? 'hover:bg-amber-400/8 text-slate-300' : 'hover:bg-amber-50 text-slate-700')}`}
                  >{r}</button>
                ))}
                <div className={`mx-3 border-t ${th.border} my-1`} />
              </div>
            )}
            {reasonSearch && PROCEED_REASONS.filter(r => r.toLowerCase().includes(reasonSearch.toLowerCase())).map(r => (
              <button key={`ps-${r}`} type="button"
                onMouseDown={() => { setReturnReason(r); setReasonOpen(false); setReasonSearch('') }}
                className={`w-full text-left px-3 py-2 text-xs transition-colors ${r === returnReason ? (isDark ? 'bg-amber-400/12 text-amber-300' : 'bg-amber-50 text-amber-700') : (isDark ? 'hover:bg-amber-400/8 text-slate-300' : 'hover:bg-amber-50 text-slate-700')}`}
              >{r}</button>
            ))}
            {Object.entries(getReturnReasons()).sort(([a], [b]) => a.localeCompare(b)).map(([group, reasons]) => {
              const filtered = reasonSearch
                ? reasons.filter(r => r.toLowerCase().includes(reasonSearch.toLowerCase()))
                : reasons
              if (!filtered.length) return null
              return (
                <div key={group}>
                  <div className={`px-3 pt-2 pb-1 text-[9px] font-semibold uppercase tracking-widest ${th.footNote}`}>{group}</div>
                  {filtered.map(r => {
                    const entry = getReasonByLabel(r)
                    return (
                      <button key={r} type="button"
                        onMouseDown={() => { setReturnReason(r); setReasonOpen(false); setReasonSearch('') }}
                        className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between gap-2 ${r === returnReason ? (isDark ? 'bg-white/8 text-white' : 'bg-slate-100 text-slate-900') : (isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700')}`}
                      >
                        <span className="truncate">{r}</span>
                        {entry && <span className={`shrink-0 text-[9px] font-mono font-bold px-1 rounded ${entry.customerFault ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>{entry.code}</span>}
                      </button>
                    )
                  })}
                </div>
              )
            })}
            {reasonSearch && ALL_REASONS.filter(r => r.toLowerCase().includes(reasonSearch.toLowerCase())).length === 0 && (
              <div className={`px-3 py-4 text-xs text-center ${th.footNote}`}>No matching reasons</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── buildFallbackMeta ────────────────────────────────────────────────────────

function buildFallbackMeta(ocr) {
  const fields = ['date', 'payee', 'amount_figures', 'amount_words', 'micr', 'alterations']
  const out = {}
  fields.forEach(k => {
    out[k] = {
      extracted_value:      ocr?.[k] ?? '',
      extracted_confidence: 0.95,
      extracted_by:         'GOT-OCR2.0',
      actual_value:         ocr?.[k] ?? '',
      source:               'STP',
      corrected_by:         null,
      corrected_at:         null,
    }
  })
  return out
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ReviewPanel({ item, onDecision, isDark }) {
  // Wizard stage
  const [stage, setStage] = useState('Verification')
  // Verification: inner tab
  const [tab, setTab] = useState('overview')
  // Shared: return reason (available at any stage for Return action)
  const [returnReason, setReturnReason] = useState('')
  const [reasonSearch, setReasonSearch] = useState('')
  const [reasonOpen, setReasonOpen] = useState(false)
  // Submission: confirm countdown
  const [confirming, setConfirming] = useState(null)
  const [confirmSecs, setConfirmSecs] = useState(null)
  // Validation: editable fields meta
  const [fieldsMeta, setFieldsMeta] = useState(null)

  const confirmTimerRef  = useRef(null)
  const confirmCountRef  = useRef(null)
  const reasonDropdownRef = useRef(null)

  const REASON_COLORS = getReasonColors(isDark)

  // Reset everything when instrument changes
  useEffect(() => {
    setStage('Verification')
    setTab('overview')
    setReturnReason('')
    setReasonSearch('')
    setReasonOpen(false)
    setConfirming(null)
    setConfirmSecs(null)
    setFieldsMeta(null)
    clearInterval(confirmCountRef.current)
    clearTimeout(confirmTimerRef.current)
  }, [item?.instrument_id])

  // Initialise fieldsMeta on entering Validation
  useEffect(() => {
    if (stage === 'Validation' && item && !fieldsMeta) {
      setFieldsMeta(JSON.parse(JSON.stringify(item.fields_meta ?? buildFallbackMeta(item.ocr_fields))))
    }
  }, [stage, item, fieldsMeta])

  // Global keyboard shortcuts
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') {
        if (confirmSecs !== null) {
          clearInterval(confirmCountRef.current)
          clearTimeout(confirmTimerRef.current)
          setConfirmSecs(null)
          setConfirming(null)
        }
        if (reasonOpen) setReasonOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmSecs, reasonOpen])

  // Click outside reason dropdown
  useEffect(() => {
    if (!reasonOpen) return
    const onOutside = (e) => {
      if (reasonDropdownRef.current && !reasonDropdownRef.current.contains(e.target)) setReasonOpen(false)
    }
    document.addEventListener('mousedown', onOutside)
    return () => document.removeEventListener('mousedown', onOutside)
  }, [reasonOpen])

  useEffect(() => () => {
    clearInterval(confirmCountRef.current)
    clearTimeout(confirmTimerRef.current)
  }, [])

  const th = {
    border:    isDark ? 'border-white/10' : 'border-slate-200',
    id:        isDark ? 'text-slate-500'  : 'text-slate-400',
    heading:   isDark ? 'text-white'      : 'text-slate-900',
    dot:       isDark ? 'text-slate-500'  : 'text-slate-400',
    meta:      isDark ? 'text-slate-500'  : 'text-slate-400',
    tabActive: isDark ? 'bg-white/5 text-white border-t border-l border-r border-white/10' : 'bg-slate-100 text-slate-900 border-t border-l border-r border-slate-200',
    tabIdle:   isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    glass:     isDark ? 'bg-white/5 border border-white/10' : 'bg-slate-50 border border-slate-200',
    lbl:       isDark ? 'text-slate-500'  : 'text-slate-400',
    val:       isDark ? 'text-slate-200'  : 'text-slate-800',
    barBg:     isDark ? 'bg-white/5'      : 'bg-slate-100',
    foot:      isDark ? 'bg-navy-950/80'  : 'bg-white',
    footNote:  isDark ? 'text-slate-600'  : 'text-slate-400',
  }

  // Derived
  const selectedReason = getReasonByLabel(returnReason)
  const totalIetMs   = new Date(item?.iet_deadline) - new Date(item?.received_at)
  const remainingMs  = new Date(item?.iet_deadline) - Date.now()
  const ietPct       = item ? Math.max(0, Math.min(1, remainingMs / totalIetMs)) : 0
  const minsLeft     = item ? Math.max(0, Math.round(remainingMs / 60000)) : 0
  const activeMeta   = fieldsMeta ?? buildFallbackMeta(item?.ocr_fields)

  // Cheque image hover state
  const [chequeHover, setChequeHover] = useState(false)
  const hoverTimeout = useRef(null)
  const showCheque = () => { clearTimeout(hoverTimeout.current); setChequeHover(true) }
  const hideCheque = () => { hoverTimeout.current = setTimeout(() => setChequeHover(false), 120) }

  const cheqViews = item ? [
    { key: 'BFB', label: 'Front B/W',  url: item.front_bw_url   ?? null, iqaScore: item.iqa_front_bw   ?? null },
    { key: 'BBB', label: 'Back B/W',   url: item.back_bw_url    ?? null, iqaScore: item.iqa_back_bw    ?? null },
    { key: 'BFG', label: 'Front Gray', url: item.front_gray_url ?? null, iqaScore: item.iqa_front_gray ?? null },
  ] : []

  // ── Handlers ─────────────────────────────────────────────────────────────────

  function handleReturn() {
    if (!returnReason) return
    setConfirming('RETURN')
    saveRecentReason(returnReason)
    setTimeout(() => {
      onDecision(item.instrument_id, 'RETURN', {
        label: returnReason,
        urrbch_code: selectedReason?.code ?? null,
        customer_fault: selectedReason?.customerFault ?? null,
      })
      setConfirming(null)
    }, 800)
  }

  function handleConfirm() {
    setConfirming('CONFIRM')
    setConfirmSecs(2)
    confirmCountRef.current = setInterval(() => {
      setConfirmSecs(s => {
        if (s <= 1) { clearInterval(confirmCountRef.current); return null }
        return s - 1
      })
    }, 1000)
    confirmTimerRef.current = setTimeout(() => {
      onDecision(item.instrument_id, 'CONFIRM', '')
      setConfirming(null)
      setConfirmSecs(null)
    }, 2000)
  }

  function handleEditField(key, value) {
    setFieldsMeta(prev => ({ ...prev, [key]: { ...prev[key], actual_value: value, source: 'MANUAL' } }))
  }

  function handleValidationSave() {
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

  if (!item) {
    return (
      <div className={`flex-1 flex items-center justify-center text-sm ${th.lbl}`}>
        <div className="text-center">
          <div className="text-4xl mb-3">📋</div>
          <div>Select a cheque from the queue to review</div>
        </div>
      </div>
    )
  }

  const reasonColor = REASON_COLORS[item.reason] || (
    isDark ? 'bg-slate-400/10 border-slate-400/20 text-slate-300' : 'bg-slate-100 border-slate-300 text-slate-600'
  )
  const chequePopupBg = isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'
  const instrumentIdColor = isDark ? 'text-gold-400 decoration-gold-400/40' : 'text-amber-600 decoration-amber-400/60'
  const subMemberBanner  = isDark ? 'bg-amber-400/5 border-amber-400/20 text-amber-300' : 'bg-amber-50 border-amber-300 text-amber-700'

  const ocrFieldDefs = [
    ['Date',             'date'],
    ['Payee',            'payee'],
    ['Amount (figures)', 'amount_figures'],
    ['Amount (words)',   'amount_words'],
    ['MICR Code',        'micr'],
    ['Alterations',      'alterations'],
  ]

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {/* Sub-member banner */}
      {item.principal_tag === 'SUB_MEMBER' && (
        <div className={`px-6 py-2 flex items-center gap-2 border-b text-[11px] font-medium ${subMemberBanner}`}>
          <span className="font-semibold">SUB-MEMBER CHEQUE</span>
          <span className="opacity-60">·</span>
          <span>{item.sub_member_name}</span>
          <span className="opacity-60">·</span>
          <span className="font-mono opacity-70">{item.sub_member_id}</span>
          <span className="ml-auto opacity-60">Sponsor bank notified on return</span>
        </div>
      )}

      {/* Header — always visible */}
      <div className={`px-6 pt-2 pb-0 border-b ${th.border} shrink-0`}>
        {/* Instrument identity row */}
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <div className="relative" onMouseEnter={showCheque} onMouseLeave={hideCheque}>
            <span className={`text-[11px] font-mono cursor-default underline decoration-dotted ${instrumentIdColor}`}>{item.instrument_id}</span>
            {chequeHover && (
              <div className={`absolute left-0 top-6 z-50 w-[500px] rounded-xl shadow-2xl border p-3 ${chequePopupBg}`}
                onMouseEnter={showCheque} onMouseLeave={hideCheque}
              >
                <div className={`text-[9px] ${th.lbl} uppercase tracking-widest mb-2`}>Cheque Images — hover to compare</div>
                <ChequeImageViewer views={cheqViews} fields={item.ocr_fields} isDark={isDark} compact title={item.instrument_id} />
              </div>
            )}
          </div>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-[10px] font-mono ${th.id}`}>{item.clearing_zone}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.account_display}</span>
          <span className={`text-[10px] ${th.dot}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.payee_display}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>{item.reason_label}</span>
          <span className={`text-[10px] ${th.meta}`}>{item.amount_range}</span>
          {item.opa_rule && <span className="text-[10px] text-sky-400/70 font-mono">OPA</span>}
          <div className="ml-auto"><IETTimer deadline={item.iet_deadline} compact bright /></div>
        </div>

        {/* Confidence strip */}
        <div className="flex items-center gap-3 py-1.5">
          {[
            { label: 'OCR',   pct: item.ocr_confidence,              bar: item.ocr_confidence >= 0.92 ? 'bg-emerald-500' : item.ocr_confidence >= 0.80 ? 'bg-amber-400' : 'bg-red-400' },
            { label: 'Sig',   pct: item.sig_match_score ?? 0,         bar: item.sig_match_score == null ? 'bg-purple-400' : item.sig_match_score >= 0.85 ? 'bg-emerald-500' : item.sig_match_score >= 0.70 ? 'bg-amber-400' : 'bg-red-400', display: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A' },
            { label: 'Fraud', pct: item.fraud_score,                  bar: item.fraud_score >= 0.80 ? 'bg-red-400' : item.fraud_score >= 0.72 ? 'bg-amber-400' : 'bg-emerald-500' },
            { label: 'IET',   pct: ietPct, display: `${minsLeft}m`,  bar: ietPct <= 0.20 ? 'bg-red-400 animate-pulse' : ietPct <= 0.40 ? 'bg-amber-400' : 'bg-sky-400' },
          ].map(({ label, pct, bar, display }) => (
            <div key={label} className="flex items-center gap-1.5 min-w-0">
              <span className={`text-[9px] font-semibold uppercase tracking-wider ${th.lbl} w-6 shrink-0`}>{label}</span>
              <div className={`w-16 h-1 ${th.barBg} rounded-full overflow-hidden`}>
                <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct * 100}%` }} />
              </div>
              <span className={`text-[10px] font-mono ${th.lbl}`}>{display ?? `${Math.round(pct * 100)}%`}</span>
            </div>
          ))}
        </div>

        {/* Stage bar */}
        <StageBar stage={stage} isDark={isDark} />

        {/* Inner tabs — Verification only */}
        {stage === 'Verification' && (
          <div className="flex gap-1 pt-0.5">
            {['overview', 'cheque', 'ai analysis', 'passport'].map(t => (
              <button key={t} onClick={() => setTab(t)}
                className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${tab === t ? th.tabActive : th.tabIdle}`}
              >{t}</button>
            ))}
          </div>
        )}

        {/* Stage subtitle — Validation & Submission */}
        {stage !== 'Verification' && (
          <div className={`text-[11px] pb-2 font-semibold ${isDark ? 'text-gold-400' : 'text-amber-600'}`}>
            {stage === 'Validation' ? 'Validation — review and correct OCR-extracted fields' : 'Submission — final review before confirming payment'}
          </div>
        )}
      </div>

      {/* ── VERIFICATION content ─────────────────────────────────────────────── */}
      {stage === 'Verification' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
          {tab === 'overview' && (
            <>
              <div className={`flex items-start gap-3 rounded-xl border px-4 py-2.5 ${reasonColor}`}>
                <span className="text-base mt-0.5">⚠</span>
                <div>
                  <div className="text-xs font-semibold">Flagged: {item.reason_label}</div>
                  <div className="text-[11px] opacity-70 mt-0.5">
                    {item.reason === 'VAULT_MISS'
                      ? 'Signature vault returned no specimen — auto-return is never permitted. Human must decide.'
                      : item.reason === 'HIGH_VALUE_DUAL_APPROVAL'
                      ? `OPA policy: ${item.opa_rule} — cheque >₹1Cr requires dual reviewer approval.`
                      : 'AI confidence below threshold — decision required before IET deadline.'}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                {[
                  { label: 'OCR',       val: `${Math.round(item.ocr_confidence * 100)}%`,              sub: 'confidence',  color: th.heading },
                  { label: 'Signature', val: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A', sub: item.sig_match_score != null ? 'match score' : 'vault miss', color: item.sig_match_score == null ? 'text-purple-400' : item.sig_match_score < 0.70 ? 'text-red-400' : item.sig_match_score < 0.85 ? 'text-amber-400' : 'text-emerald-400' },
                  { label: 'Fraud',     val: `${Math.round(item.fraud_score * 100)}%`,                 sub: 'XGBoost score',color: item.fraud_score >= 0.80 ? 'text-red-400' : 'text-amber-400' },
                ].map(({ label, val, sub, color }) => (
                  <div key={label} className={`rounded-xl p-3 text-center ${th.glass}`}>
                    <div className={`text-[10px] ${th.lbl} uppercase tracking-wide mb-0.5`}>{label}</div>
                    <div className={`text-3xl font-mono font-bold ${color}`}>{val}</div>
                    <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                  </div>
                ))}
              </div>

              {/* OCR fields with ⓘ info icons */}
              <div className={`rounded-xl p-4 ${th.glass}`}>
                <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>OCR Extracted Fields · click ⓘ for AI detail</div>
                <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                  {ocrFieldDefs.map(([label, key]) => (
                    <VerifyFieldRow key={key} label={label} fieldKey={key}
                      meta={activeMeta[key] ?? { extracted_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }}
                      isDark={isDark}
                    />
                  ))}
                </div>
              </div>

              <SigPanel item={item} isDark={isDark} />
            </>
          )}

          {tab === 'cheque' && (
            <ChequeImageViewer views={cheqViews} fields={item.ocr_fields} isDark={isDark} compact={false} title={item.instrument_id} />
          )}

          {tab === 'ai analysis' && (
            <div className="space-y-3">
              <div className="flex items-center gap-4">
                <FraudGauge score={item.fraud_score} />
                <div className={`flex-1 rounded-xl p-4 space-y-2 ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-2`}>Model Stack</div>
                  {[
                    ['OCR',       'GOT-OCR2.0',    item.ocr_confidence],
                    ['Vision',    'Qwen2-VL 72B',  0.94],
                    ['Signature', 'Siamese SNN',   item.sig_match_score ?? 0],
                    ['Fraud',     'XGBoost',        item.fraud_score],
                  ].map(([label, model, score]) => (
                    <div key={label} className="flex items-center gap-3">
                      <span className={`text-[10px] ${th.lbl} w-16`}>{label}</span>
                      <div className={`flex-1 h-1.5 ${th.barBg} rounded-full overflow-hidden`}>
                        <div className="h-full bg-gold-400/60 rounded-full" style={{ width: `${score * 100}%` }} />
                      </div>
                      <span className={`text-[10px] font-mono ${th.meta} w-8 text-right`}>{Math.round(score * 100)}%</span>
                      <span className={`text-[10px] ${th.lbl} w-28 truncate`}>{model}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className={`rounded-xl p-4 ${th.glass}`}>
                <ShapExplainer shapValues={item.shap_values} isDark={isDark} />
              </div>
            </div>
          )}

          {tab === 'passport' && (() => {
            const base = new Date(item.received_at).getTime()
            const steps = [
              { phase: 'PRESENTING BANK', label: 'Image Quality + CTS-2010', ts: base, icon: '📥', note: `IQA passed · CTS-2010 compliant · Zone: ${item.clearing_zone}`, status: 'done' },
              { label: 'MICR Line Extraction', ts: base + 2400, icon: '🔢', note: `GOT-OCR2.0 · MICR: ${item.ocr_fields.micr} · IFSC verified`, status: 'done' },
              { label: 'OCR — Fields Extraction', ts: base + 46000, icon: '📄', note: `Conf: ${Math.round(item.ocr_confidence * 100)}% · Payee: ${item.payee_display} · Amount: ${item.ocr_fields.amount_figures}`, status: item.ocr_confidence < 0.88 ? 'warn' : 'done' },
              { label: 'CTS Compliance Check', ts: base + 65000, icon: '✅', note: `Date: ${item.ocr_fields.date} ✓ · Words/Figures match · Endorsement ✓`, status: item.ocr_fields.alterations ? 'warn' : 'done' },
              { label: 'Duplicate Instrument Check', ts: base + 68000, icon: '🔁', note: 'Redis dedup check · No prior filing found for this MICR + date', status: 'done' },
              { phase: 'NGCH GATEWAY', label: 'Presented to NGCH MUMBAI', ts: base + 82000, icon: '🌐', note: `Routed to drawee bank · ${item.cbs_type} · Ack received`, status: 'done' },
              { phase: 'DRAWEE BANK', label: 'Account Validity Check', ts: base + 97000, icon: '🏦', note: `Active · KYC valid · No freeze/NPA/court hold`, status: 'done' },
              { label: 'Stop Cheque Instruction', ts: base + 99000, icon: '🛑', note: 'No stop payment instruction found in CBS', status: 'done' },
              { label: 'Positive Pay System (PPS)', ts: base + 115000, icon: '📋', note: item.sig_match_score != null ? 'PPS record found · Amount and payee match ✓' : 'PPS not registered — mandatory for >₹50K', status: item.sig_match_score != null ? 'done' : 'warn' },
              { label: 'Signature Verification', ts: base + 152000, icon: '✍', note: item.sig_match_score != null ? `Siamese SNN · ${Math.round(item.sig_match_score * 100)}% match · ${item.sig_specimen_label}` : 'Vault miss — no specimen on file', status: item.sig_match_score == null ? 'warn' : item.sig_match_score < 0.80 ? 'warn' : 'done' },
              { label: 'Vision — Alteration Detection', ts: base + 194000, icon: '🔍', note: `Qwen2-VL 72B · ${item.ocr_fields.alterations ? '⚠ Alteration flag on amount field' : '✓ No alteration detected'}`, status: item.ocr_fields.alterations ? 'warn' : 'done' },
              { label: 'Fraud Scoring', ts: base + 235000, icon: '🛡', note: `XGBoost · Score: ${Math.round(item.fraud_score * 100)}% · SHAP: ${item.shap_values[0].feature} (top driver)`, status: item.fraud_score >= 0.80 ? 'risk' : 'warn' },
              { label: 'Routed to Human Review', ts: base + 241000, icon: '👤', note: `OPA decision · Reason: ${item.reason_label}`, status: 'review' },
              { label: 'Awaiting Verification',  ts: Date.now(), icon: '⏳', note: `IET deadline in ${minsLeft} min · Step 1 of 3`, status: 'pending' },
            ]
            const stC = { done: 'bg-emerald-500', warn: 'bg-amber-400', risk: 'bg-red-400', review: 'bg-sky-400', pending: 'bg-slate-400 animate-pulse' }
            const stT = { done: 'text-emerald-400', warn: 'text-amber-400', risk: 'text-red-400', review: 'text-sky-400', pending: 'text-slate-400' }
            const phaseColors = {
              'PRESENTING BANK': 'text-amber-400 border-amber-400/20 bg-amber-400/5',
              'NGCH GATEWAY':    'text-cyan-400 border-cyan-400/20 bg-cyan-400/5',
              'DRAWEE BANK':     'text-violet-400 border-violet-400/20 bg-violet-400/5',
            }
            return (
              <div className="space-y-3">
                <div className={`rounded-xl p-4 ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-4`}>Two-Bank Processing Timeline · {item.instrument_id}</div>
                  <div className="relative">
                    <div className={`absolute left-3 top-3 bottom-3 w-px ${th.barBg}`} />
                    <div className="space-y-3">
                      {steps.map((s, i) => (
                        <div key={i}>
                          {s.phase && (
                            <div className={`inline-flex items-center gap-1.5 text-[9px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border mb-2 ml-10 ${phaseColors[s.phase] || ''}`}>{s.phase}</div>
                          )}
                          <div className="flex items-start gap-3 relative">
                            <div className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center z-10 ${stC[s.status]} text-white text-[11px]`}>{s.icon}</div>
                            <div className="flex-1 min-w-0 pt-0.5">
                              <div className="flex items-baseline gap-2 flex-wrap">
                                <span className={`text-xs font-semibold ${th.heading}`}>{s.label}</span>
                                <span className={`text-[9px] font-mono ${th.lbl}`}>{new Date(s.ts).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}</span>
                                {i > 0 && <span className={`text-[9px] ${th.lbl}`}>+{((s.ts - base) / 1000).toFixed(1)}s</span>}
                              </div>
                              <div className={`text-[11px] ${th.lbl} mt-0.5`}>{s.note}</div>
                            </div>
                            <span className={`text-[9px] font-semibold uppercase ${stT[s.status]} shrink-0`}>{s.status}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
                <div className={`rounded-xl p-4 ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Instrument Metadata</div>
                  <div className="grid grid-cols-2 gap-x-6 gap-y-2">
                    {[
                      ['Instrument ID',  item.instrument_id],
                      ['Clearing Zone',  item.clearing_zone],
                      ['CBS Type',       item.cbs_type],
                      ['Received',       new Date(item.received_at).toLocaleTimeString('en-IN')],
                      ['IET Deadline',   new Date(item.iet_deadline).toLocaleTimeString('en-IN')],
                      ['Amount Range',   item.amount_range],
                      ...(item.principal_tag === 'SUB_MEMBER' ? [['Sub-Member', item.sub_member_name], ['SMB ID', item.sub_member_id]] : []),
                      ...(item.opa_rule ? [['OPA Rule', item.opa_rule]] : []),
                    ].map(([k, v]) => (
                      <div key={k} className="flex flex-col">
                        <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                        <span className={`text-xs font-mono mt-0.5 ${th.val} truncate`}>{v}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )
          })()}
        </div>
      )}

      {/* ── VALIDATION content ───────────────────────────────────────────────── */}
      {stage === 'Validation' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className={`text-xs ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
            Pre-populated from OCR extraction. Edit any field that needs correction — changed fields are highlighted and marked <span className={`font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>MANUAL</span>.
          </div>

          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Editable Fields</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-4">
              {ocrFieldDefs.map(([label, key]) => (
                <EditFieldRow key={key} label={label} fieldKey={key}
                  meta={activeMeta[key] ?? { extracted_value: item.ocr_fields?.[key], actual_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }}
                  isDark={isDark} onEdit={handleEditField}
                />
              ))}
            </div>
          </div>

          {(() => {
            const changed = Object.entries(activeMeta).filter(([, m]) => String(m.actual_value) !== String(m.extracted_value))
            if (!changed.length) return null
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

      {/* ── SUBMISSION content ───────────────────────────────────────────────── */}
      {stage === 'Submission' && (
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className={`flex items-start gap-2 rounded-xl border px-4 py-3 ${isDark ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-emerald-50 border-emerald-300'}`}>
            <span className="text-base">✅</span>
            <div>
              <div className={`text-xs font-semibold ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>Ready for decision</div>
              <div className={`text-[11px] mt-0.5 ${isDark ? 'text-emerald-400/70' : 'text-emerald-600'}`}>Verification and Validation complete. Confirm to honor payment, or Return to send back with a reason.</div>
            </div>
          </div>

          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Final Values — what will be filed</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-3">
              {ocrFieldDefs.map(([label, key]) => {
                const m = activeMeta[key] ?? {}
                const val = typeof (m.actual_value ?? m.extracted_value) === 'boolean'
                  ? (m.actual_value ? '⚠ DETECTED' : '✓ None')
                  : String(m.actual_value ?? m.extracted_value ?? item.ocr_fields?.[key] ?? '—')
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

          {(() => {
            const manualFields = Object.entries(activeMeta).filter(([, m]) => m.source === 'MANUAL')
            if (!manualFields.length) return (
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
                      <> · <span className="line-through opacity-60 font-mono">{String(m.extracted_value)}</span> → <span className="font-mono font-semibold">{String(m.actual_value)}</span></>
                    )}
                    {m.corrected_by && <span className={`ml-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>by {m.corrected_by} at {m.corrected_at}</span>}
                  </div>
                ))}
              </div>
            )
          })()}

          {/* Non-customer-fault notice */}
          {selectedReason && !selectedReason.customerFault && (
            <div className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-[10px] ${isDark ? 'bg-sky-900/30 border border-sky-700/40 text-sky-300' : 'bg-sky-50 border border-sky-200 text-sky-700'}`}>
              <span className="font-bold font-mono">Code {selectedReason.code}</span>
              <span>·</span>
              <span>Non-customer fault — no return charge may be levied (RBI/NPCI mandate)</span>
            </div>
          )}
        </div>
      )}

      {/* ── Footer ──────────────────────────────────────────────────────────── */}
      <div className={`relative z-20 shrink-0 border-t ${th.border} px-6 py-3 ${th.foot} backdrop-blur`}>

        {/* Verification footer */}
        {stage === 'Verification' && (
          <div className="flex items-center gap-2">
            <ReturnReasonPicker {...{ returnReason, setReturnReason, reasonOpen, setReasonOpen, reasonSearch, setReasonSearch, reasonDropdownRef, confirming, isDark }} />
            <button onClick={handleReturn} disabled={!returnReason || !!confirming}
              className="shrink-0 px-5 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >{confirming === 'RETURN' ? 'Filing…' : selectedReason ? `✕ Return (${selectedReason.code})` : '✕ Return'}</button>
            <button onClick={() => setStage('Validation')}
              className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all whitespace-nowrap"
            >Approve → Validation</button>
          </div>
        )}

        {/* Validation footer */}
        {stage === 'Validation' && (
          <div className="flex items-center justify-between gap-3">
            <button onClick={() => setStage('Verification')}
              className={`px-4 py-2 rounded-lg border text-xs font-semibold transition-all ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
            >← Back to Verification</button>
            <div className="flex gap-2">
              <button onClick={handleReturn} disabled={!returnReason || !!confirming}
                className="shrink-0 px-4 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
              >✕ Return</button>
              <button onClick={handleValidationSave}
                className="px-6 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all whitespace-nowrap"
              >Save → Submission →</button>
            </div>
          </div>
        )}

        {/* Submission footer */}
        {stage === 'Submission' && (
          <div className="flex items-center gap-2">
            <button onClick={() => setStage('Validation')}
              className={`shrink-0 px-3 py-2 rounded-lg border text-xs font-semibold transition-all ${isDark ? 'border-white/15 text-slate-300 hover:bg-white/5' : 'border-slate-300 text-slate-600 hover:bg-slate-50'}`}
            >←</button>
            <ReturnReasonPicker {...{ returnReason, setReturnReason, reasonOpen, setReasonOpen, reasonSearch, setReasonSearch, reasonDropdownRef, confirming, isDark }} />
            <button onClick={handleReturn} disabled={!returnReason || !!confirming}
              className="shrink-0 px-5 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
            >{confirming === 'RETURN' ? 'Filing…' : selectedReason ? `✕ Return (${selectedReason.code})` : '✕ Return'}</button>
            <button onClick={handleConfirm} disabled={!!confirming}
              className={`shrink-0 px-6 py-2 rounded-lg border text-xs font-semibold transition-all whitespace-nowrap disabled:opacity-40 ${
                confirmSecs !== null
                  ? 'bg-amber-400/10 border-amber-400/40 text-amber-300'
                  : 'bg-emerald-500/30 border-emerald-500/60 text-emerald-300 hover:bg-emerald-500/40'
              }`}
            >
              {confirming === 'CONFIRM' && confirmSecs !== null
                ? `Confirming in ${confirmSecs}s · Esc to cancel`
                : confirming === 'CONFIRM'
                ? 'Filing…'
                : '✓ Confirm Payment'}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
