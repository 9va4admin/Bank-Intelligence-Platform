/**
 * ReviewPanel — Verification stage panel (Inward Clearing).
 *
 * Shows the detailed cheque evidence: overview, images, AI analysis, passport.
 * IET Timer is always visible — inward IET breach rate must be 0.000%.
 * Decision: Approve → Validation IQ | Return (with URRBCH reason code).
 * No wizard stages — this panel is Verification only.
 */
import { useState, useRef, useEffect } from 'react'
import IETTimer from './IETTimer'
import FraudGauge from './FraudGauge'
import ShapExplainer from './ShapExplainer'
import ChequeImageViewer from './ChequeImageViewer'
import { getReturnReasons, getReasonByLabel } from '../data/returnReasons'

const RECENT_KEY = 'astra-recent-return-reasons'
const getRecentReasons = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] } }
const saveRecentReason = (r) => {
  const updated = [r, ...getRecentReasons().filter(x => x !== r)].slice(0, 3)
  localStorage.setItem(RECENT_KEY, JSON.stringify(updated))
}

const REASON_COLORS = {
  SIGNATURE_LOW_CONFIDENCE:  'bg-amber-400/10 border-amber-400/30 text-amber-300',
  FRAUD_SCORE_HIGH:          'bg-red-400/10 border-red-400/30 text-red-300',
  OCR_LOW_CONFIDENCE:        'bg-orange-400/10 border-orange-400/30 text-orange-300',
  VAULT_MISS:                'bg-purple-400/10 border-purple-400/30 text-purple-300',
  HIGH_VALUE_DUAL_APPROVAL:  'bg-sky-400/10 border-sky-400/30 text-sky-300',
}

// ── AI Extraction Popover ─────────────────────────────────────────────────────

function ExtractionPopover({ meta, isDark, onClose }) {
  const ref = useRef()
  useEffect(() => {
    function handler(e) { if (ref.current && !ref.current.contains(e.target)) onClose() }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [onClose])
  const confPct = Math.round((meta?.extracted_confidence ?? 1) * 100)
  const confColor = confPct >= 92 ? 'text-emerald-400' : confPct >= 80 ? 'text-amber-400' : 'text-red-400'
  return (
    <div ref={ref} className={`absolute z-50 bottom-full mb-1 left-0 w-64 rounded-xl border shadow-2xl p-3 text-[11px] ${isDark ? 'bg-navy-900 border-white/15' : 'bg-white border-slate-200'}`}>
      <div className={`text-[9px] uppercase tracking-widest mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>AI Extraction Detail</div>
      <div className="space-y-1.5">
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Extracted by</span>
          <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{meta?.extracted_by ?? 'GOT-OCR2.0'}</span>
        </div>
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Raw value</span>
          <span className={`font-mono font-semibold ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{String(meta?.extracted_value ?? '—')}</span>
        </div>
        <div className="flex justify-between">
          <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>Confidence</span>
          <span className={`font-mono font-semibold ${confColor}`}>{confPct}%</span>
        </div>
      </div>
    </div>
  )
}

// ── Source badge ──────────────────────────────────────────────────────────────

function SourceBadge({ source, isDark }) {
  if (source === 'STP') return (
    <span className={`inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700'}`}>STP</span>
  )
  return (
    <span className={`inline-flex items-center text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-400 text-amber-700'}`}>MANUAL</span>
  )
}

// ── Field row with ⓘ info icon ────────────────────────────────────────────────

function VerifyFieldRow({ label, fieldKey, meta, isDark }) {
  const [open, setOpen] = useState(false)
  const isBoolean = typeof meta?.extracted_value === 'boolean'
  const val = isBoolean ? (meta.actual_value ? '⚠ DETECTED' : '✓ None') : String(meta?.actual_value ?? meta?.extracted_value ?? '—')
  return (
    <div className="flex flex-col relative">
      <div className="flex items-center gap-1">
        <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
        <button type="button" onClick={() => setOpen(o => !o)}
          className={`text-[10px] w-4 h-4 flex items-center justify-center rounded-full transition-colors ${isDark ? 'text-slate-500 hover:text-sky-400 hover:bg-sky-400/10' : 'text-slate-400 hover:text-sky-600 hover:bg-sky-100'}`}
        >ⓘ</button>
        {open && <ExtractionPopover meta={meta} isDark={isDark} onClose={() => setOpen(false)} />}
      </div>
      <div className="flex items-center gap-1.5 mt-0.5">
        <span className={`text-xs font-mono ${fieldKey === 'alterations' && meta?.extracted_value ? 'text-red-400 font-semibold' : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{val}</span>
        <SourceBadge source={meta?.source ?? 'STP'} isDark={isDark} />
      </div>
    </div>
  )
}

// ── buildFallbackMeta ─────────────────────────────────────────────────────────

function buildFallbackMeta(ocr) {
  const fields = ['date', 'payee', 'amount_figures', 'amount_words', 'micr', 'alterations']
  const out = {}
  fields.forEach(k => {
    out[k] = { extracted_value: ocr?.[k] ?? '', extracted_confidence: 0.95, extracted_by: 'GOT-OCR2.0', actual_value: ocr?.[k] ?? '', source: 'STP' }
  })
  return out
}

// ── Signature panel ───────────────────────────────────────────────────────────

function SigPanel({ item, isDark }) {
  const muted = isDark ? 'text-slate-400' : 'text-slate-500'
  if (!item.sig_specimen_available) {
    return (
      <div className="rounded-xl border border-purple-400/30 bg-purple-400/5 p-4">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-3">Signature Verification</div>
        <div className="flex items-center gap-3 mb-3">
          <span className="text-2xl">🔍</span>
          <div>
            <div className="text-sm font-semibold text-purple-300">No Specimen On File</div>
            <div className={`text-xs mt-0.5 ${muted}`}>{item.sig_specimen_label}</div>
          </div>
        </div>
        <div className={`text-xs ${isDark ? 'bg-white/5' : 'bg-slate-50'} rounded-lg p-3 ${muted}`}>
          Vault miss — no specimen for {item.account_display}. Auto-return is <span className="text-purple-300 font-medium">never</span> permitted.
        </div>
      </div>
    )
  }
  const matchPct = Math.round((item.sig_match_score ?? 0) * 100)
  const color    = matchPct < 70 ? 'text-red-400' : matchPct < 85 ? 'text-amber-400' : 'text-emerald-400'
  const barColor = matchPct < 70 ? 'bg-red-400'   : matchPct < 85 ? 'bg-amber-400'   : 'bg-emerald-400'
  const border   = matchPct < 70 ? 'border-red-400/30 bg-red-400/5' : matchPct < 85 ? 'border-amber-400/30 bg-amber-400/5' : 'border-emerald-400/30 bg-emerald-400/5'
  return (
    <div className={`rounded-xl border px-4 py-3 ${border}`}>
      <div className="flex items-center gap-4">
        <div className="shrink-0 flex items-baseline gap-1">
          <span className={`text-2xl font-bold font-mono ${color}`}>{matchPct}%</span>
          <span className="text-[10px] text-slate-500">match</span>
        </div>
        <div className="flex-1 space-y-1">
          <div className={`h-1.5 ${isDark ? 'bg-white/5' : 'bg-slate-100'} rounded-full overflow-hidden`}>
            <div className={`h-full rounded-full ${barColor}`} style={{ width: `${matchPct}%` }} />
          </div>
          <div className={`flex justify-between text-[10px] ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>
            <span>0%</span><span>threshold 85%</span><span>100%</span>
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest">Siamese SNN</div>
          <div className="text-[10px] text-slate-500">{item.sig_specimen_label}</div>
        </div>
      </div>
    </div>
  )
}

// ── Return reason picker ──────────────────────────────────────────────────────

function ReasonPicker({ returnReason, setReturnReason, isDark }) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef()
  useEffect(() => {
    if (!open) return
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [open])
  const grouped = getReturnReasons()
  const selectedEntry = getReasonByLabel(returnReason)
  const sel = isDark ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-white border-slate-300 text-slate-700'
  return (
    <div className="relative flex-1" ref={ref}>
      <button type="button" onClick={() => { setOpen(o => !o); setSearch('') }}
        className={`w-full flex items-center justify-between border rounded-lg px-3 py-2 text-xs focus:outline-none ${sel}`}
      >
        <span className={`truncate flex items-center gap-2 min-w-0 ${returnReason ? '' : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>
          <span className="truncate">{returnReason || 'Select Return Reason…'}</span>
          {selectedEntry && (
            <span className={`shrink-0 text-[9px] font-bold font-mono px-1.5 py-0.5 rounded border ${selectedEntry.customerFault ? (isDark ? 'bg-red-900/40 border-red-700/50 text-red-300' : 'bg-red-100 border-red-300 text-red-700') : (isDark ? 'bg-sky-900/40 border-sky-700/50 text-sky-300' : 'bg-sky-100 border-sky-300 text-sky-700')}`}>{selectedEntry.code}</span>
          )}
        </span>
        <span className={`ml-1 shrink-0 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{open ? '▲' : '▼'}</span>
      </button>
      {open && (
        <div className={`absolute bottom-full mb-1 left-0 right-0 z-50 rounded-lg border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
          <div className={`px-3 py-2 border-b ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
            <input autoFocus type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search reasons…"
              className={`w-full text-xs bg-transparent outline-none ${isDark ? 'text-slate-300' : 'text-slate-700'}`}
            />
          </div>
          <div className="max-h-52 overflow-y-auto">
            {!search && getRecentReasons().length > 0 && (
              <div>
                <div className={`px-3 pt-2 pb-1 text-[9px] uppercase font-semibold tracking-widest ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Recent</div>
                {getRecentReasons().map(r => (
                  <button key={r} type="button" onMouseDown={() => { setReturnReason(r); setOpen(false) }}
                    className={`w-full text-left px-3 py-2 text-xs transition-colors ${isDark ? 'hover:bg-white/5 text-amber-400' : 'hover:bg-amber-50 text-amber-600'}`}
                  >{r}</button>
                ))}
                <div className={`mx-3 border-t ${isDark ? 'border-white/10' : 'border-slate-200'} my-1`} />
              </div>
            )}
            {Object.entries(grouped).map(([group, reasons]) => {
              const filtered = search ? reasons.filter(r => r.toLowerCase().includes(search.toLowerCase())) : reasons
              if (!filtered.length) return null
              return (
                <div key={group}>
                  <div className={`px-3 pt-2 pb-1 text-[9px] uppercase font-semibold tracking-widest ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{group}</div>
                  {filtered.map(r => {
                    const entry = getReasonByLabel(r)
                    return (
                      <button key={r} type="button" onMouseDown={() => { setReturnReason(r); setOpen(false) }}
                        className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors ${r === returnReason ? (isDark ? 'bg-white/8 text-white' : 'bg-slate-100 text-slate-900') : (isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700')}`}
                      >
                        <span className="truncate">{r}</span>
                        {entry && <span className={`shrink-0 text-[9px] font-mono font-bold ${entry.customerFault ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>{entry.code}</span>}
                      </button>
                    )
                  })}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function ReviewPanel({ item, onDecision, isDark }) {
  const [tab, setTab] = useState('overview')
  const [returnReason, setReturnReason] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [chequeHover, setChequeHover] = useState(false)
  const hoverT = useRef(null)

  useEffect(() => {
    setTab('overview')
    setReturnReason('')
    setSubmitting(false)
  }, [item?.instrument_id])

  const th = {
    border:    isDark ? 'border-white/10'  : 'border-slate-200',
    heading:   isDark ? 'text-white'       : 'text-slate-900',
    lbl:       isDark ? 'text-slate-500'   : 'text-slate-400',
    val:       isDark ? 'text-slate-200'   : 'text-slate-800',
    glass:     isDark ? 'bg-white/5 border border-white/10' : 'bg-slate-50 border border-slate-200',
    tabActive: isDark ? 'bg-white/5 text-white border-t border-l border-r border-white/10' : 'bg-slate-100 text-slate-900 border-t border-l border-r border-slate-200',
    tabIdle:   isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    barBg:     isDark ? 'bg-white/5'       : 'bg-slate-100',
    foot:      isDark ? 'bg-navy-950/80'   : 'bg-white',
  }

  if (!item) {
    return (
      <div className={`flex-1 flex items-center justify-center text-sm ${th.lbl}`}>
        <div className="text-center"><div className="text-4xl mb-3">📋</div><div>Select a cheque to verify</div></div>
      </div>
    )
  }

  const reasonColor = REASON_COLORS[item.reason] || (isDark ? 'bg-slate-400/10 border-slate-400/20 text-slate-300' : 'bg-slate-100 border-slate-300 text-slate-600')
  const meta        = item.fields_meta ?? buildFallbackMeta(item.ocr_fields)
  const remainingMs = new Date(item.iet_deadline) - Date.now()
  const totalIetMs  = new Date(item.iet_deadline) - new Date(item.received_at)
  const ietPct      = Math.max(0, Math.min(1, remainingMs / totalIetMs))
  const minsLeft    = Math.max(0, Math.round(remainingMs / 60000))

  const cheqViews = [
    { key: 'BFB', label: 'Front B/W',  url: item.front_bw_url   ?? null, iqaScore: item.iqa_front_bw   ?? null },
    { key: 'BBB', label: 'Back B/W',   url: item.back_bw_url    ?? null, iqaScore: item.iqa_back_bw    ?? null },
    { key: 'BFG', label: 'Front Gray', url: item.front_gray_url ?? null, iqaScore: item.iqa_front_gray ?? null },
  ]

  const ocrFieldDefs = [
    ['Date', 'date'], ['Payee', 'payee'],
    ['Amount (figures)', 'amount_figures'], ['Amount (words)', 'amount_words'],
    ['MICR Code', 'micr'], ['Alterations', 'alterations'],
  ]

  function handleReturn() {
    if (!returnReason) return
    saveRecentReason(returnReason)
    setSubmitting(true)
    const entry = getReasonByLabel(returnReason)
    onDecision(item.instrument_id, 'RETURN', { label: returnReason, urrbch_code: entry?.code ?? null, customer_fault: entry?.customerFault ?? null })
  }

  function handleApprove() {
    setSubmitting(true)
    onDecision(item.instrument_id, 'APPROVE_TO_VALIDATION', {})
  }

  return (
    <div className="flex-1 flex flex-col min-h-0 overflow-hidden">
      {item.principal_tag === 'SUB_MEMBER' && (
        <div className={`px-6 py-1.5 flex items-center gap-2 border-b text-[11px] font-medium ${isDark ? 'bg-amber-400/5 border-amber-400/20 text-amber-300' : 'bg-amber-50 border-amber-300 text-amber-700'}`}>
          <span className="font-semibold">SUB-MEMBER</span>
          <span className="opacity-60">·</span>
          <span>{item.sub_member_name}</span>
        </div>
      )}

      {/* Header */}
      <div className={`px-6 pt-2 pb-0 border-b ${th.border} shrink-0`}>
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <div className="relative"
            onMouseEnter={() => { clearTimeout(hoverT.current); setChequeHover(true) }}
            onMouseLeave={() => { hoverT.current = setTimeout(() => setChequeHover(false), 120) }}
          >
            <span className={`text-[11px] font-mono cursor-default underline decoration-dotted ${isDark ? 'text-gold-400 decoration-gold-400/40' : 'text-amber-600 decoration-amber-400/60'}`}>{item.instrument_id}</span>
            {chequeHover && (
              <div className={`absolute left-0 top-6 z-50 w-[480px] rounded-xl shadow-2xl border p-3 ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}
                onMouseEnter={() => clearTimeout(hoverT.current)} onMouseLeave={() => setChequeHover(false)}
              >
                <ChequeImageViewer views={cheqViews} fields={item.ocr_fields} isDark={isDark} compact title={item.instrument_id} />
              </div>
            )}
          </div>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.account_display}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.payee_display}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor}`}>{item.reason_label}</span>
          <span className={`text-[10px] ${th.lbl}`}>{item.amount_range}</span>
          <div className="ml-auto"><IETTimer deadline={item.iet_deadline} compact bright /></div>
        </div>

        {/* Confidence strip */}
        <div className="flex items-center gap-3 py-1.5">
          {[
            { label: 'OCR',   pct: item.ocr_confidence,                      bar: item.ocr_confidence >= 0.92 ? 'bg-emerald-500' : item.ocr_confidence >= 0.80 ? 'bg-amber-400' : 'bg-red-400' },
            { label: 'Sig',   pct: item.sig_match_score ?? 0,                 display: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A', bar: item.sig_match_score == null ? 'bg-purple-400' : item.sig_match_score >= 0.85 ? 'bg-emerald-500' : item.sig_match_score >= 0.70 ? 'bg-amber-400' : 'bg-red-400' },
            { label: 'Fraud', pct: item.fraud_score,                          bar: item.fraud_score >= 0.80 ? 'bg-red-400' : item.fraud_score >= 0.72 ? 'bg-amber-400' : 'bg-emerald-500' },
            { label: 'IET',   pct: ietPct, display: `${minsLeft}m`,           bar: ietPct <= 0.20 ? 'bg-red-400 animate-pulse' : ietPct <= 0.40 ? 'bg-amber-400' : 'bg-sky-400' },
          ].map(({ label, pct, bar, display }) => (
            <div key={label} className="flex items-center gap-1.5">
              <span className={`text-[9px] font-semibold uppercase tracking-wider ${th.lbl} w-6`}>{label}</span>
              <div className={`w-16 h-1 ${th.barBg} rounded-full overflow-hidden`}>
                <div className={`h-full rounded-full ${bar}`} style={{ width: `${pct * 100}%` }} />
              </div>
              <span className={`text-[10px] font-mono ${th.lbl}`}>{display ?? `${Math.round(pct * 100)}%`}</span>
            </div>
          ))}
        </div>

        <div className="flex gap-1 pt-0.5">
          {['overview', 'cheque', 'ai analysis', 'passport'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${tab === t ? th.tabActive : th.tabIdle}`}
            >{t}</button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-3">
        {tab === 'overview' && (
          <>
            <div className={`flex items-start gap-3 rounded-xl border px-4 py-2.5 ${reasonColor}`}>
              <span className="text-base mt-0.5">⚠</span>
              <div>
                <div className="text-xs font-semibold">Flagged: {item.reason_label}</div>
                <div className="text-[11px] opacity-70 mt-0.5">
                  {item.reason === 'VAULT_MISS' ? 'Vault miss — no specimen on file. Auto-return is never permitted.' : 'AI confidence below threshold — manual verification required before IET.'}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: 'OCR',       val: `${Math.round(item.ocr_confidence * 100)}%`,       sub: 'confidence', color: th.heading },
                { label: 'Signature', val: item.sig_match_score != null ? `${Math.round(item.sig_match_score * 100)}%` : 'N/A', sub: item.sig_match_score != null ? 'match' : 'vault miss', color: item.sig_match_score == null ? 'text-purple-400' : item.sig_match_score < 0.70 ? 'text-red-400' : 'text-emerald-400' },
                { label: 'Fraud',     val: `${Math.round(item.fraud_score * 100)}%`,           sub: 'risk score',  color: item.fraud_score >= 0.80 ? 'text-red-400' : 'text-amber-400' },
              ].map(({ label, val, sub, color }) => (
                <div key={label} className={`rounded-xl p-3 text-center ${th.glass}`}>
                  <div className={`text-[10px] ${th.lbl} uppercase tracking-wide mb-0.5`}>{label}</div>
                  <div className={`text-3xl font-mono font-bold ${color}`}>{val}</div>
                  <div className={`text-[10px] ${th.lbl}`}>{sub}</div>
                </div>
              ))}
            </div>
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>OCR Fields · click ⓘ for AI detail</div>
              <div className="grid grid-cols-2 gap-x-6 gap-y-3">
                {ocrFieldDefs.map(([label, key]) => (
                  <VerifyFieldRow key={key} label={label} fieldKey={key}
                    meta={meta[key] ?? { extracted_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }}
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
                {[['OCR','GOT-OCR2.0',item.ocr_confidence],['Vision','Qwen2-VL 72B',0.94],['Signature','Siamese SNN',item.sig_match_score??0],['Fraud','XGBoost',item.fraud_score]].map(([lbl,model,score]) => (
                  <div key={lbl} className="flex items-center gap-3">
                    <span className={`text-[10px] ${th.lbl} w-16`}>{lbl}</span>
                    <div className={`flex-1 h-1.5 ${th.barBg} rounded-full overflow-hidden`}>
                      <div className="h-full bg-gold-400/60 rounded-full" style={{ width: `${score * 100}%` }} />
                    </div>
                    <span className={`text-[10px] font-mono ${th.lbl} w-8 text-right`}>{Math.round(score * 100)}%</span>
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

        {tab === 'passport' && (
          <div className={`rounded-xl p-4 ${th.glass}`}>
            <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-3`}>Instrument Metadata</div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-2">
              {[
                ['Instrument ID', item.instrument_id], ['Clearing Zone', item.clearing_zone],
                ['CBS Type', item.cbs_type],           ['Received', new Date(item.received_at).toLocaleTimeString('en-IN')],
                ['IET Deadline', new Date(item.iet_deadline).toLocaleTimeString('en-IN')],
                ['Amount Range', item.amount_range],   ['OPA Rule', item.opa_rule || '—'],
                ...(item.principal_tag === 'SUB_MEMBER' ? [['Sub-Member', item.sub_member_name]] : []),
              ].map(([k, v]) => (
                <div key={k} className="flex flex-col">
                  <span className={`text-[10px] ${th.lbl}`}>{k}</span>
                  <span className={`text-xs font-mono mt-0.5 ${th.val} truncate`}>{v}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className={`shrink-0 border-t ${th.border} px-6 py-3 flex items-center gap-2 ${th.foot} backdrop-blur`}>
        <ReasonPicker returnReason={returnReason} setReturnReason={setReturnReason} isDark={isDark} />
        <button onClick={handleReturn} disabled={!returnReason || submitting}
          className="shrink-0 px-4 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
        >{submitting ? 'Filing…' : '✕ Return'}</button>
        <button onClick={handleApprove} disabled={submitting}
          className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-50 whitespace-nowrap"
        >Approve → Validation IQ</button>
      </div>
    </div>
  )
}
