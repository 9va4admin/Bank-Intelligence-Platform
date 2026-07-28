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

export default function OutwardReviewPanel({ item, onDecision, isDark }) {
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

  const overallIqa = ((item.iqa_front_bw ?? 0) + (item.iqa_back_bw ?? 0) + (item.iqa_front_gray ?? 0)) / 3

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
        <div className="flex gap-1">
          {['images', 'ocr fields', 'cts-2010'].map(t => (
            <button key={t} onClick={() => setTab(t)}
              className={`px-4 py-1.5 text-xs font-medium rounded-t-lg capitalize transition-colors ${tab === t ? th.tabActive : th.tabIdle}`}
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
          <div className="space-y-2">
            {[
              { label: 'Image Quality ≥ 85%',     ok: overallIqa >= 0.85 },
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
        )}
      </div>

      {/* Footer */}
      <div className={`shrink-0 border-t ${th.border} px-5 py-3 flex items-center gap-2 ${th.foot} backdrop-blur`}>
        <ReasonPicker returnReason={returnReason} setReturnReason={setReturnReason} isDark={isDark} />
        <button onClick={handleReturn} disabled={!returnReason || submitting}
          className="shrink-0 px-4 py-2 rounded-lg border border-red-500/40 bg-red-500/10 text-red-400 text-xs font-semibold hover:bg-red-500/20 transition-all disabled:opacity-40 disabled:cursor-not-allowed whitespace-nowrap"
        >{submitting ? 'Filing…' : '✕ Return'}</button>
        <button onClick={handleApprove} disabled={submitting}
          className="shrink-0 px-5 py-2 rounded-lg border border-emerald-500/40 bg-emerald-500/20 text-emerald-400 text-xs font-semibold hover:bg-emerald-500/30 transition-all disabled:opacity-50 whitespace-nowrap"
        >Approve → Validation OQ</button>
      </div>
    </div>
  )
}
