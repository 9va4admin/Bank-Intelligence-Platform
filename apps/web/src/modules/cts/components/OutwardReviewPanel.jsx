/**
 * OutwardReviewPanel — Verification stage panel (Outward Clearing).
 *
 * Shows cheque images, IQA scores, OCR fields with AI extraction detail.
 * Decision: Approve → instrument moves to Validation OQ | Return with reason.
 * No wizard stages — this panel is Verification only.
 */
import { useState, useRef, useEffect } from 'react'
import ChequeImageViewer from './ChequeImageViewer'
import { getReturnReasons, getReasonByLabel } from '../data/returnReasons'

const REASON_COLORS = {
  AMOUNT_MISMATCH:          'bg-amber-400/10 border-amber-400/30 text-amber-300',
  ENDORSEMENT_IRREGULAR:    'bg-orange-400/10 border-orange-400/30 text-orange-300',
  HIGH_VALUE_DUAL_APPROVAL: 'bg-sky-400/10 border-sky-400/30 text-sky-300',
  CTS_COMPLIANCE_FAILURE:   'bg-red-400/10 border-red-400/30 text-red-300',
  DATE_INVALID:             'bg-red-400/10 border-red-400/30 text-red-300',
}

function reasonColor(key, isDark) {
  return REASON_COLORS[key] || (isDark
    ? 'bg-slate-400/10 border-slate-400/20 text-slate-300'
    : 'bg-slate-100 border-slate-300 text-slate-600')
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
    <div ref={ref}
      className={`absolute z-50 bottom-full mb-1 left-0 w-64 rounded-xl border shadow-2xl p-3 text-[11px] ${isDark ? 'bg-navy-900 border-white/15' : 'bg-white border-slate-200'}`}
    >
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
  const val = isBoolean
    ? (meta.actual_value ? '⚠ DETECTED' : '✓ None')
    : String(meta?.actual_value ?? meta?.extracted_value ?? '—')

  return (
    <div className="flex flex-col relative">
      <div className="flex items-center gap-1">
        <span className={`text-[10px] ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
        <button type="button" onClick={() => setOpen(o => !o)}
          className={`text-[10px] w-4 h-4 flex items-center justify-center rounded-full transition-colors ${isDark ? 'text-slate-500 hover:text-sky-400 hover:bg-sky-400/10' : 'text-slate-400 hover:text-sky-600 hover:bg-sky-100'}`}
          title="AI extraction detail"
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
    out[k] = {
      extracted_value:      ocr?.[k] ?? '',
      extracted_confidence: 0.95,
      extracted_by:         'GOT-OCR2.0',
      actual_value:         ocr?.[k] ?? '',
      source:               'STP',
    }
  })
  return out
}

// ── Score pill (AI confidence card) ──────────────────────────────────────────

function ScorePill({ label, value, isDark }) {
  const pct = Math.round((value ?? 0) * 100)
  const color = (value ?? 0) >= 0.95 ? 'emerald' : (value ?? 0) >= 0.85 ? 'amber' : 'red'
  const colors = {
    emerald: isDark ? 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' : 'text-emerald-700 bg-emerald-50 border-emerald-300',
    amber:   isDark ? 'text-amber-400 bg-amber-500/10 border-amber-500/30'       : 'text-amber-700 bg-amber-50 border-amber-300',
    red:     isDark ? 'text-red-400 bg-red-500/10 border-red-500/30'             : 'text-red-700 bg-red-50 border-red-300',
  }
  return (
    <div className={`flex flex-col items-center px-3 py-2 rounded-lg border text-center ${colors[color]}`}>
      <span className="text-xs font-bold">{pct}%</span>
      <span className="text-[9px] font-medium">{label}</span>
    </div>
  )
}

// ── IQA score card ────────────────────────────────────────────────────────────

function IQACard({ label, score, isDark }) {
  const color = score == null ? 'text-slate-400'
    : score >= 0.9 ? 'text-emerald-400'
    : score >= 0.75 ? 'text-amber-400'
    : 'text-red-400'
  const barColor = score == null ? 'bg-slate-500'
    : score >= 0.9 ? 'bg-emerald-400'
    : score >= 0.75 ? 'bg-amber-400'
    : 'bg-red-400'
  return (
    <div className={`flex-1 rounded-lg p-2.5 text-center ${isDark ? 'bg-white/5' : 'bg-slate-50'}`}>
      <div className={`text-[9px] uppercase tracking-wider ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</div>
      <div className={`text-xl font-mono font-bold mt-1 ${color}`}>{score != null ? `${Math.round(score * 100)}%` : 'N/A'}</div>
      {score != null && (
        <div className={`mt-1.5 h-1 ${isDark ? 'bg-white/5' : 'bg-slate-200'} rounded-full overflow-hidden`}>
          <div className={`h-full rounded-full ${barColor}`} style={{ width: `${score * 100}%` }} />
        </div>
      )}
    </div>
  )
}

// ── Return reason combobox ─────────────────────────────────────────────────────

const RECENT_KEY = 'astra-recent-return-reasons-outward'
const getRecentReasons = () => { try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]') } catch { return [] } }
const saveRecentReason = (r) => {
  const updated = [r, ...getRecentReasons().filter(x => x !== r)].slice(0, 3)
  localStorage.setItem(RECENT_KEY, JSON.stringify(updated))
}

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
  const th = { sel: isDark ? 'bg-white/5 border-white/10 text-slate-300' : 'bg-white border-slate-300 text-slate-700' }

  return (
    <div className="relative flex-1" ref={ref}>
      <button type="button" onClick={() => { setOpen(o => !o); setSearch('') }}
        className={`w-full flex items-center justify-between border rounded-lg px-3 py-2 text-xs focus:outline-none ${th.sel}`}
      >
        <span className={`truncate ${returnReason ? '' : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>
          {returnReason || 'Select Return Reason…'}
        </span>
        {selectedEntry && <span className={`ml-2 shrink-0 text-[9px] font-bold px-1.5 py-0.5 rounded border ${isDark ? 'bg-red-900/40 border-red-700/50 text-red-300' : 'bg-red-100 border-red-300 text-red-700'}`}>{selectedEntry.code}</span>}
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
                        className={`w-full text-left px-3 py-2 text-xs transition-colors flex items-center justify-between gap-2 ${r === returnReason ? (isDark ? 'bg-white/8 text-white' : 'bg-slate-100 text-slate-900') : (isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700')}`}
                      >
                        <span className="truncate">{r}</span>
                        {entry && <span className={`shrink-0 text-[9px] font-mono font-bold px-1 ${entry.customerFault ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-sky-400' : 'text-sky-600')}`}>{entry.code}</span>}
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

export default function OutwardReviewPanel({ item, onDecision, isDark, tabKind = 'review' }) {
  const [tab, setTab] = useState('images')
  const [returnReason, setReturnReason] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    setTab('images')
    setReturnReason('')
    setSubmitting(false)
  }, [item?.instrument_id])

  const th = {
    border:    isDark ? 'border-white/10'  : 'border-slate-200',
    heading:   isDark ? 'text-white'       : 'text-slate-900',
    lbl:       isDark ? 'text-slate-500'   : 'text-slate-400',
    val:       isDark ? 'text-slate-200'   : 'text-slate-800',
    glass:     isDark ? 'bg-white/5 border border-white/10' : 'bg-slate-50 border border-slate-200',
    tabActive: isDark ? 'bg-white/10 text-white border-t border-l border-r border-white/10' : 'bg-white text-slate-900 border-t border-l border-r border-slate-200',
    tabIdle:   isDark ? 'text-slate-500 hover:text-slate-300' : 'text-slate-400 hover:text-slate-700',
    foot:      isDark ? 'bg-navy-950/80'   : 'bg-white',
  }

  if (!item) {
    return (
      <div className={`flex-1 flex items-center justify-center text-sm ${th.lbl}`}>
        <div className="text-center">
          <div className="text-4xl mb-3">📄</div>
          <div>Select a cheque to verify</div>
        </div>
      </div>
    )
  }

  const meta = item.fields_meta ?? buildFallbackMeta(item.ocr_fields)
  const views = [
    { key: 'BFB', label: 'Front B/W',  url: item.front_bw_url   ?? null, iqaScore: item.iqa_front_bw   ?? null },
    { key: 'BBB', label: 'Back B/W',   url: item.back_bw_url    ?? null, iqaScore: item.iqa_back_bw    ?? null },
    { key: 'BFG', label: 'Front Gray', url: item.front_gray_url ?? null, iqaScore: item.iqa_front_gray ?? null },
  ]

  const iqaScores = [item.iqa_front_bw, item.iqa_back_bw, item.iqa_front_gray].filter(s => s != null)
  const overallIqa = iqaScores.length > 0 ? iqaScores.reduce((a, b) => a + b, 0) / iqaScores.length : null

  function handleReturn() {
    if (!returnReason) return
    saveRecentReason(returnReason)
    setSubmitting(true)
    const entry = getReasonByLabel(returnReason)
    onDecision(item.instrument_id, 'RETURN', { label: returnReason, code: entry?.code ?? null })
  }

  function handleApprove() {
    setSubmitting(true)
    onDecision(item.instrument_id, 'APPROVE_TO_VALIDATION', {})
  }

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
      {/* Header */}
      <div className={`px-5 pt-3 pb-0 border-b ${th.border} shrink-0`}>
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className={`text-xs font-mono ${isDark ? 'text-gold-400' : 'text-amber-600'}`}>{item.instrument_id}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-sm font-bold ${th.heading}`}>{item.ocr_fields?.payee ?? '—'}</span>
          <span className={`text-[10px] ${th.lbl}`}>·</span>
          <span className={`text-xs font-mono ${th.val}`}>{item.ocr_fields?.amount_figures ?? '—'}</span>
          <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${reasonColor(item.reason, isDark)}`}>{item.reason_label ?? item.reason}</span>
        </div>

        {/* IQA summary strip */}
        <div className="flex items-center gap-2 mb-3">
          {[
            { label: 'IQA Overall', score: overallIqa },
            { label: 'Front B/W',  score: item.iqa_front_bw   ?? null },
            { label: 'Back B/W',   score: item.iqa_back_bw    ?? null },
            { label: 'Front Gray', score: item.iqa_front_gray ?? null },
          ].map(({ label, score }) => <IQACard key={label} label={label} score={score} isDark={isDark} />)}
        </div>

        {/* Tabs */}
        <div className="flex gap-1 overflow-x-auto">
          {['images', 'ocr fields', 'cts-2010', 'ai analysis', 'passport'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors whitespace-nowrap ${tab === t ? th.tabActive : th.tabIdle}`}
            >{t}</button>
          ))}
        </div>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-5 py-4">
        {tab === 'images' && (
          <ChequeImageViewer
            views={views}
            fields={{ ...item.ocr_fields, deposit_channel: item.deposit_channel, deposit_data: item.deposit_data }}
            isDark={isDark}
            compact={false}
            title={item.instrument_id}
            depositInfo={item.deposit_channel ? { channel: item.deposit_channel, data: item.deposit_data } : null}
          />
        )}

        {tab === 'ocr fields' && (
          <div className="space-y-3">
            <div className={`text-xs ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
              Click ⓘ on any field to see the AI extraction model, raw output, and confidence score.
            </div>
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className="grid grid-cols-2 gap-x-6 gap-y-4">
                {ocrFieldDefs.map(([label, key]) => (
                  <VerifyFieldRow key={key} label={label} fieldKey={key}
                    meta={meta[key] ?? { extracted_value: item.ocr_fields?.[key], source: 'STP', extracted_confidence: 1 }}
                    isDark={isDark}
                  />
                ))}
              </div>
            </div>

            {/* MICR detail */}
            <div className={`rounded-xl p-4 ${th.glass}`}>
              <div className={`text-[10px] ${th.lbl} uppercase tracking-widest mb-2`}>MICR Line</div>
              <div className={`font-mono text-sm ${isDark ? 'text-emerald-300' : 'text-emerald-700'}`}>{item.ocr_fields?.micr ?? '—'}</div>
              <div className="grid grid-cols-3 gap-3 mt-3 text-[10px]">
                {[
                  ['Cheque No.',   item.ocr_fields?.micr?.slice(0, 6) ?? '—'],
                  ['MICR Code',    item.ocr_fields?.bank_micr ?? '—'],
                  ['Account',      item.ocr_fields?.account_suffix ?? '****'],
                ].map(([k, v]) => (
                  <div key={k} className="flex flex-col">
                    <span className={th.lbl}>{k}</span>
                    <span className={`font-mono mt-0.5 ${th.val}`}>{v}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'cts-2010' && (
          <div className="space-y-4">
            {/* Image + content checks */}
            <div className="space-y-2">
              {[
                { label: 'Image Quality ≥ 85%',     ok: overallIqa != null && overallIqa >= 0.85 },
                { label: 'MICR Line Extracted',      ok: !!item.ocr_fields?.micr },
                { label: 'Date Present + Parseable', ok: !!item.ocr_fields?.date },
                { label: 'Payee Name Present',       ok: !!item.ocr_fields?.payee },
                { label: 'Amount in Figures',        ok: !!item.ocr_fields?.amount_figures },
                { label: 'Amount in Words',          ok: !!item.ocr_fields?.amount_words },
                { label: 'Alteration Check',         ok: !item.ocr_fields?.alterations },
                { label: 'Endorsement Stamp',        ok: item.has_endorsement !== false },
              ].map(({ label, ok }) => (
                <div key={label} className={`flex items-center justify-between px-4 py-2.5 rounded-lg ${ok ? (isDark ? 'bg-emerald-500/5 border border-emerald-500/15' : 'bg-emerald-50 border border-emerald-200') : (isDark ? 'bg-red-500/5 border border-red-500/15' : 'bg-red-50 border border-red-200')}`}>
                  <span className={`text-xs ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{label}</span>
                  <span className={`text-sm ${ok ? 'text-emerald-400' : 'text-red-400'}`}>{ok ? '✓' : '✗'}</span>
                </div>
              ))}
            </div>
            {/* Security print features (Qwen2-VL) */}
            <div>
              <div className={`text-[9px] font-semibold uppercase tracking-widest mb-2 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Security Print Features</div>
              <div className="space-y-2">
                {[
                  { label: 'Void Pantograph',       key: 'void_pantograph'      },
                  { label: '₹ Symbol',              key: 'rupee_symbol'         },
                  { label: 'Micro-lettering',       key: 'micro_lettering'      },
                  { label: 'Printer Name CTS-2010', key: 'printer_name_cts2010' },
                ].map(({ label, key }) => {
                  const sf = item.security_features
                  const detected = sf ? sf[key] === true : null
                  const ok = detected !== false  // null = not checked yet → neutral
                  const isChecked = sf != null
                  return (
                    <div key={key} className={`flex items-center justify-between px-4 py-2.5 rounded-lg ${
                      !isChecked
                        ? (isDark ? 'bg-white/3 border border-white/8' : 'bg-slate-50 border border-slate-200')
                        : ok
                          ? (isDark ? 'bg-emerald-500/5 border border-emerald-500/15' : 'bg-emerald-50 border border-emerald-200')
                          : (isDark ? 'bg-red-500/5 border border-red-500/15' : 'bg-red-50 border border-red-200')
                    }`}>
                      <span className={`text-xs ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{label}</span>
                      <span className={`text-sm ${!isChecked ? (isDark ? 'text-slate-600' : 'text-slate-400') : ok ? 'text-emerald-400' : 'text-red-400'}`}>
                        {!isChecked ? '—' : ok ? '✓' : '✗'}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {tab === 'ai analysis' && (
          <div className="space-y-5">
            {/* Score pills */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2.5 ${th.lbl}`}>AI Confidence</div>
              <div className="grid grid-cols-2 gap-2">
                <ScorePill label="OCR Accuracy"    value={item.ocr_confidence}     isDark={isDark} />
                <ScorePill label="Vision / CTS-10" value={item.vision_compliance}  isDark={isDark} />
                <ScorePill label="MICR Confidence" value={item.micr_confidence}    isDark={isDark} />
                <ScorePill label="IQA Overall"     value={overallIqa} isDark={isDark} />
              </div>
            </div>

            {/* Field confidence */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2.5 ${th.lbl}`}>Field Confidence</div>
              <div className={`rounded-lg border overflow-hidden text-[11px] ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
                {Object.entries(meta).map(([key, m]) => {
                  if (!m || m.extracted_confidence == null) return null
                  const label = { date: 'Date', payee: 'Payee', amount_figures: 'Amount', amount_words: 'Amount (words)', micr: 'MICR', alterations: 'Alterations' }[key] ?? key
                  const conf = m.extracted_confidence
                  const pct = Math.round(conf * 100)
                  const confColor = conf >= 0.95 ? (isDark ? 'text-emerald-400' : 'text-emerald-700') : conf >= 0.85 ? (isDark ? 'text-amber-400' : 'text-amber-700') : (isDark ? 'text-red-400' : 'text-red-700')
                  return (
                    <div key={key} className={`flex items-center gap-3 px-3 py-2 border-b last:border-b-0 ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
                      <span className={`w-28 shrink-0 ${th.lbl}`}>{label}</span>
                      <div className={`flex-1 h-1.5 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-slate-200'}`}>
                        <div className={`h-full rounded-full ${conf >= 0.95 ? 'bg-emerald-500' : conf >= 0.85 ? 'bg-amber-400' : 'bg-red-500'}`} style={{ width: `${pct}%` }} />
                      </div>
                      <span className={`w-10 text-right font-mono font-semibold ${confColor}`}>{pct}%</span>
                      <span className={`w-14 text-right text-[9px] font-bold ${m.source === 'STP' ? (isDark ? 'text-emerald-400' : 'text-emerald-700') : (isDark ? 'text-amber-400' : 'text-amber-700')}`}>{m.source}</span>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Risk signals */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>Risk Signals</div>
              <div className={`rounded-lg border p-3 space-y-2 text-[11px] ${
                (!item.checks?.cts_valid || !item.checks?.date_valid || !item.checks?.signature_present)
                  ? (isDark ? 'bg-red-500/8 border-red-500/25' : 'bg-red-50 border-red-300')
                  : (isDark ? 'bg-emerald-500/5 border-emerald-500/15' : 'bg-emerald-50 border-emerald-200')
              }`}>
                {[
                  { label: 'Signature present',   val: item.checks?.signature_present  ? '✓ Detected' : '⚠ Missing', warn: !item.checks?.signature_present  },
                  { label: 'Amount words match',   val: item.checks?.amount_words_match ? '✓ Match'    : '⚠ Mismatch', warn: !item.checks?.amount_words_match },
                  { label: 'Date valid',            val: item.checks?.date_valid         ? '✓ Valid'    : '⚠ Invalid',  warn: !item.checks?.date_valid         },
                  { label: 'CTS-2010 compliant',    val: item.checks?.cts_valid          ? '✓ Pass'     : '⚠ Fail',     warn: !item.checks?.cts_valid          },
                  { label: 'Alteration detected',   val: item.ocr_fields?.alterations    ? '⚠ Yes'      : '✓ None',     warn: !!item.ocr_fields?.alterations   },
                ].map(({ label, val, warn }) => (
                  <div key={label} className="flex items-center justify-between">
                    <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>{label}</span>
                    <span className={`font-mono font-semibold ${warn ? (isDark ? 'text-red-400' : 'text-red-700') : (isDark ? 'text-emerald-400' : 'text-emerald-700')}`}>{val}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Security print features */}
            {item.security_features && (
              <div>
                <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>Security Print</div>
                <div className={`rounded-lg border p-3 space-y-2 text-[11px] ${
                  (item.security_features.missing ?? []).length > 0
                    ? (isDark ? 'bg-red-500/8 border-red-500/25' : 'bg-red-50 border-red-300')
                    : (isDark ? 'bg-emerald-500/5 border-emerald-500/15' : 'bg-emerald-50 border-emerald-200')
                }`}>
                  {[
                    { label: 'Void Pantograph',       key: 'void_pantograph'      },
                    { label: '₹ Symbol',              key: 'rupee_symbol'         },
                    { label: 'Micro-lettering',       key: 'micro_lettering'      },
                    { label: 'Printer CTS-2010',      key: 'printer_name_cts2010' },
                  ].map(({ label, key }) => {
                    const ok = item.security_features[key] === true
                    return (
                      <div key={key} className="flex items-center justify-between">
                        <span className={isDark ? 'text-slate-400' : 'text-slate-500'}>{label}</span>
                        <span className={`font-mono font-semibold ${ok ? (isDark ? 'text-emerald-400' : 'text-emerald-700') : (isDark ? 'text-red-400' : 'text-red-700')}`}>
                          {ok ? '✓ Present' : '⚠ Missing'}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Model attribution */}
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>Model Attribution</div>
              <div className="space-y-1.5 text-[11px]">
                {[
                  { task: 'OCR / MICR',        model: 'GOT-OCR2.0'            },
                  { task: 'Vision / CTS-2010',  model: 'Qwen2-VL 72B'          },
                  { task: 'Compliance check',   model: 'CTS-2010 Validator v3' },
                ].map(({ task, model }) => (
                  <div key={task} className="flex items-center justify-between">
                    <span className={th.lbl}>{task}</span>
                    <span className={`font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{model}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {tab === 'passport' && (() => {
          const ocr = item.ocr_fields ?? {}
          const DCFG = {
            PAY_IN_SLIP:     { label: 'Pay-in Slip', icon: '🧾' },
            BACK_ANNOTATION: { label: 'Back Note',   icon: '✍️' },
            KIOSK:           { label: 'Kiosk / CDM', icon: '🏧' },
          }
          const dd = item.deposit_data ?? {}
          const depositRows =
            item.deposit_channel === 'PAY_IN_SLIP' ? [
              { label: 'Depositor',    value: dd.depositor_name    },
              { label: 'Dep. Account', value: dd.depositor_account },
              { label: 'Deposit Amt',  value: dd.deposit_amount    },
              { label: 'Token',        value: dd.counter_token     },
              { label: 'Dep. Branch',  value: dd.branch            },
            ] : item.deposit_channel === 'BACK_ANNOTATION' ? [
              { label: 'Ext. Account', value: dd.extracted_account },
              { label: 'Ext. Mobile',  value: dd.extracted_mobile  },
            ] : item.deposit_channel === 'KIOSK' ? [
              { label: 'Depositor',    value: dd.name      },
              { label: 'CDM Account',  value: dd.account   },
              { label: 'Txn ID',       value: dd.txn_id    },
              { label: 'Timestamp',    value: dd.timestamp },
            ] : []

          return (
            <div>
              <div className={`text-[10px] font-semibold uppercase tracking-wider mb-3 ${th.lbl}`}>Cheque Passport</div>
              <div className={`rounded-xl border divide-y text-xs ${isDark ? 'border-white/10 divide-white/5' : 'border-slate-200 divide-slate-100'}`}>
                {/* Header */}
                <div className={`flex items-center justify-between px-4 py-2.5 ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                  <span className={`font-mono text-sm font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{item.instrument_id}</span>
                  <span className={`text-[9px] font-bold px-2 py-0.5 rounded border ${isDark ? 'border-amber-500/40 bg-amber-500/10 text-amber-400' : 'border-amber-400 bg-amber-50 text-amber-700'}`}>
                    {item.reason_label ?? item.reason}
                  </span>
                </div>
                {/* Cheque fields */}
                {[
                  { label: 'Payee',          value: ocr.payee           },
                  { label: 'Amount',         value: ocr.amount_figures  },
                  { label: 'Amount (words)', value: ocr.amount_words    },
                  { label: 'Date',           value: ocr.date            },
                  { label: 'MICR',           value: ocr.micr            },
                  { label: 'Account',        value: item.account_display },
                  { label: 'Drawee Bank',    value: ocr.bank_name       },
                  { label: 'Branch',         value: ocr.bank_branch     },
                  { label: 'IFSC',           value: ocr.bank_ifsc       },
                ].filter(r => r.value).map(({ label, value }) => (
                  <div key={label} className="flex items-start gap-3 px-4 py-2">
                    <span className={`w-28 shrink-0 ${th.lbl}`}>{label}</span>
                    <span className={`font-mono ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{value}</span>
                  </div>
                ))}
                {/* Deposit channel section */}
                {item.deposit_channel && depositRows.length > 0 && (
                  <>
                    <div className={`px-4 py-1.5 text-[9px] font-semibold uppercase tracking-wider ${isDark ? 'bg-white/2 text-slate-500' : 'bg-slate-50 text-slate-400'}`}>
                      {DCFG[item.deposit_channel]?.icon} {DCFG[item.deposit_channel]?.label ?? item.deposit_channel}
                    </div>
                    {depositRows.filter(r => r.value).map(({ label, value }) => (
                      <div key={label} className="flex items-start gap-3 px-4 py-2">
                        <span className={`w-28 shrink-0 ${th.lbl}`}>{label}</span>
                        <span className={`font-mono ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{value}</span>
                      </div>
                    ))}
                  </>
                )}
              </div>
            </div>
          )
        })()}
      </div>

      {/* Footer */}
      {tabKind === 'stp_success' ? (
        <div className={`shrink-0 border-t ${th.border} px-5 py-2.5 flex items-center gap-3 ${isDark ? 'bg-emerald-950/20' : 'bg-emerald-50'}`}>
          <span className="w-2 h-2 rounded-full bg-emerald-500 flex-none" />
          <span className={`text-xs font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>STP Auto-Filed to NGCH</span>
          <span className={`text-xs ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Read-only - No action required</span>
        </div>
      ) : (
        <div className={`shrink-0 border-t ${th.border} px-5 py-3 flex items-center gap-2 ${th.foot} backdrop-blur`}>
          <ReasonPicker returnReason={returnReason} setReturnReason={setReturnReason} isDark={isDark} />
          <button onClick={handleReturn} disabled={!returnReason || submitting}
            className="shrink-0 px-4 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
          >{submitting ? 'Filing…' : '✕ Return'}</button>
          <button onClick={handleApprove} disabled={submitting}
            className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-50 whitespace-nowrap"
          >Approve → Validation OQ</button>
        </div>
      )}
    </div>
  )
}
