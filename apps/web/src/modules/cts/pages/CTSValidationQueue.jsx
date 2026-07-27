/**
 * CTSValidationQueue — Validation stage grid page.
 *
 * Instruments arrive here from two paths:
 *   1. Human-approved from Verification Q (ops_reviewer clicks "Approve → Validation")
 *   2. STP auto-confirmed (AI confidence ≥ 92% on all fields — no human review needed)
 *
 * Grid layout: each row = one instrument. All OCR field columns are inline-editable.
 * Changing a cell automatically marks that field MANUAL (was STP).
 * Row actions: Approve → Submission | Return ↓ (with reason).
 *
 * Props:
 *   mode: 'outward' | 'inward'  — controls labels, IET visibility, approval CTA
 */
import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { getReasonByLabel, getReturnReasons } from '../data/returnReasons'

// ── Mock data ─────────────────────────────────────────────────────────────────

function makeMeta(val, conf, by = 'GOT-OCR2.0') {
  return { extracted_value: val, extracted_confidence: conf, extracted_by: by, actual_value: val, source: conf >= 0.90 ? 'STP' : 'MANUAL' }
}

const BASE_INSTRUMENTS_OUTWARD = [
  {
    instrument_id: 'CHQ-OUT-V001', source_stage: 'STP',      drawee_bank: 'State Bank of India',         drawee_branch: 'Andheri East',
    fields_meta: {
      date:           makeMeta('15/07/2026', 0.99),
      payee:          makeMeta('Reliance Industries Ltd', 0.97),
      amount_figures: makeMeta('₹12,50,000', 0.98),
      amount_words:   makeMeta('Twelve Lakh Fifty Thousand Only', 0.95),
      micr:           makeMeta('400002123', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V002', source_stage: 'VERIFIED',  drawee_bank: 'HDFC Bank',                  drawee_branch: 'Bandra West',
    fields_meta: {
      date:           makeMeta('14/07/2026', 0.97),
      payee:          makeMeta('Kiran Traders', 0.74),
      amount_figures: makeMeta('₹2,40,000', 0.91),
      amount_words:   makeMeta('Two Lakh Forty Thousand Only', 0.88),
      micr:           makeMeta('400001234', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V003', source_stage: 'STP',      drawee_bank: 'ICICI Bank',                  drawee_branch: 'Powai',
    fields_meta: {
      date:           makeMeta('16/07/2026', 0.99),
      payee:          makeMeta('TechMahindra Solutions', 0.96),
      amount_figures: makeMeta('₹75,000', 0.95),
      amount_words:   makeMeta('Seventy Five Thousand Only', 0.93),
      micr:           makeMeta('400004567', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V004', source_stage: 'VERIFIED',  drawee_bank: 'Bank of Baroda',             drawee_branch: 'Fort',
    fields_meta: {
      date:           makeMeta('15/07/2026', 0.98),
      payee:          makeMeta('Sunrise Exports', 0.85),
      amount_figures: makeMeta('₹3,80,500', 0.87),
      amount_words:   makeMeta('Three Lakh Eighty Thousand Five Hundred Only', 0.82),
      micr:           makeMeta('400008901', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V005', source_stage: 'STP',      drawee_bank: 'Axis Bank',                   drawee_branch: 'Goregaon',
    fields_meta: {
      date:           makeMeta('16/07/2026', 0.99),
      payee:          makeMeta('Future Enterprises Pvt Ltd', 0.99),
      amount_figures: makeMeta('₹1,25,50,000', 0.99),
      amount_words:   makeMeta('One Crore Twenty Five Lakh Fifty Thousand Only', 0.98),
      micr:           makeMeta('400002345', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

const BASE_INSTRUMENTS_INWARD = [
  {
    instrument_id: 'CHQ-IN-V001', source_stage: 'STP',      account_display: '****4521', payee_display: 'R***', iet_deadline: new Date(Date.now() + 72 * 60000).toISOString(),
    fields_meta: {
      date:           makeMeta('15/07/2026', 0.99),
      payee:          makeMeta('Ramesh Traders', 0.97),
      amount_figures: makeMeta('₹45,000', 0.98),
      amount_words:   makeMeta('Forty Five Thousand Only', 0.95),
      micr:           makeMeta('400005678', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V002', source_stage: 'VERIFIED',  account_display: '****8912', payee_display: 'M***', iet_deadline: new Date(Date.now() + 28 * 60000).toISOString(),
    fields_meta: {
      date:           makeMeta('14/07/2026', 0.96),
      payee:          makeMeta('Mumbai Steel', 0.82),
      amount_figures: makeMeta('₹3,20,000', 0.88),
      amount_words:   makeMeta('Three Lakh Twenty Thousand Only', 0.79),
      micr:           makeMeta('400009012', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V003', source_stage: 'STP',      account_display: '****2234', payee_display: 'P***', iet_deadline: new Date(Date.now() + 115 * 60000).toISOString(),
    fields_meta: {
      date:           makeMeta('16/07/2026', 0.99),
      payee:          makeMeta('Priya Enterprises', 0.96),
      amount_figures: makeMeta('₹8,000', 0.97),
      amount_words:   makeMeta('Eight Thousand Only', 0.94),
      micr:           makeMeta('400003456', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V004', source_stage: 'VERIFIED',  account_display: '****6677', payee_display: 'S***', iet_deadline: new Date(Date.now() + 54 * 60000).toISOString(),
    fields_meta: {
      date:           makeMeta('15/07/2026', 0.98),
      payee:          makeMeta('Sharma & Sons', 0.86),
      amount_figures: makeMeta('₹1,10,000', 0.89),
      amount_words:   makeMeta('One Lakh Ten Thousand Only', 0.84),
      micr:           makeMeta('400007890', 0.99),
      alterations:    { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

// ── Return reason popup (row-level) ───────────────────────────────────────────

function RowReturnMenu({ isDark, onReturn, onClose }) {
  const [search, setSearch] = useState('')
  const grouped = getReturnReasons()
  return (
    <div className={`absolute right-0 top-full mt-1 z-50 w-72 rounded-xl border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
      <div className={`px-3 py-2 border-b ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <input autoFocus type="text" value={search} onChange={e => setSearch(e.target.value)} placeholder="Search return reasons…"
          className={`w-full text-xs bg-transparent outline-none ${isDark ? 'text-slate-300' : 'text-slate-700'}`}
          onKeyDown={e => e.key === 'Escape' && onClose()}
        />
      </div>
      <div className="max-h-56 overflow-y-auto">
        {Object.entries(grouped).map(([group, reasons]) => {
          const filtered = search ? reasons.filter(r => r.toLowerCase().includes(search.toLowerCase())) : reasons
          if (!filtered.length) return null
          return (
            <div key={group}>
              <div className={`px-3 pt-2 pb-1 text-[9px] uppercase font-semibold tracking-widest ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{group}</div>
              {filtered.map(r => {
                const entry = getReasonByLabel(r)
                return (
                  <button key={r} type="button" onMouseDown={() => { onReturn(r, entry); onClose() }}
                    className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors ${isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700'}`}
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
  )
}

// ── Editable cell ─────────────────────────────────────────────────────────────

function EditCell({ value, onChange, isDark, isManual, isBoolean }) {
  const changed = isManual
  if (isBoolean) {
    return (
      <select value={value ? 'yes' : 'no'} onChange={e => onChange(e.target.value === 'yes')}
        className={`w-full text-[11px] font-mono px-1 py-0.5 rounded border focus:outline-none ${changed ? (isDark ? 'border-amber-400/50 bg-amber-400/5 text-amber-300' : 'border-amber-400 bg-amber-50 text-amber-800') : (isDark ? 'bg-transparent border-transparent text-slate-200 hover:border-white/15' : 'bg-transparent border-transparent text-slate-800 hover:border-slate-300')}`}
      >
        <option value="no">✓ None</option>
        <option value="yes">⚠ Detected</option>
      </select>
    )
  }
  return (
    <input type="text" value={String(value ?? '')} onChange={e => onChange(e.target.value)}
      className={`w-full text-[11px] font-mono px-1 py-0.5 rounded border focus:outline-none transition-colors ${changed ? (isDark ? 'border-amber-400/50 bg-amber-400/5 text-amber-300' : 'border-amber-400 bg-amber-50 text-amber-800') : (isDark ? 'bg-transparent border-transparent text-slate-200 hover:border-white/15 focus:border-white/30' : 'bg-transparent border-transparent text-slate-800 hover:border-slate-300 focus:border-slate-400')}`}
    />
  )
}

// ── Source badge ──────────────────────────────────────────────────────────────

function SBadge({ source, isDark }) {
  if (source === 'STP') return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border whitespace-nowrap ${isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700'}`}>STP</span>
  )
  return (
    <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border whitespace-nowrap ${isDark ? 'bg-amber-500/10 border-amber-500/30 text-amber-400' : 'bg-amber-50 border-amber-400 text-amber-700'}`}>MANUAL</span>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTSValidationQueue({ mode = 'outward' }) {
  const { isDark } = useTheme()
  const isInward = mode === 'inward'

  const BASE = isInward ? BASE_INSTRUMENTS_INWARD : BASE_INSTRUMENTS_OUTWARD
  const [instruments, setInstruments] = useState(() => BASE.map(i => ({ ...i, edits: {} })))
  const [filter, setFilter] = useState('ALL')
  const [returnOpenFor, setReturnOpenFor] = useState(null)

  const th = {
    page:     isDark ? 'bg-navy-950'       : 'bg-slate-50',
    card:     isDark ? 'bg-navy-900 border-white/8'    : 'bg-white border-slate-200',
    heading:  isDark ? 'text-white'        : 'text-slate-900',
    lbl:      isDark ? 'text-slate-500'    : 'text-slate-400',
    muted:    isDark ? 'text-slate-400'    : 'text-slate-500',
    th:       isDark ? 'text-slate-500 border-white/8' : 'text-slate-400 border-slate-200',
    row:      isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    divider:  isDark ? 'border-white/8'    : 'border-slate-200',
  }

  const filtered = instruments.filter(i => {
    if (filter === 'STP')      return i.source_stage === 'STP'
    if (filter === 'VERIFIED') return i.source_stage === 'VERIFIED'
    return true
  })

  const stpCount      = instruments.filter(i => i.source_stage === 'STP').length
  const verifiedCount = instruments.filter(i => i.source_stage === 'VERIFIED').length
  const editedCount   = instruments.filter(i => Object.keys(i.edits).length > 0).length

  function handleEdit(instrumentId, fieldKey, value) {
    setInstruments(prev => prev.map(inst => {
      if (inst.instrument_id !== instrumentId) return inst
      const currentMeta = inst.fields_meta[fieldKey]
      const isChanged = String(value) !== String(currentMeta.extracted_value)
      return {
        ...inst,
        edits: { ...inst.edits, [fieldKey]: value },
        fields_meta: {
          ...inst.fields_meta,
          [fieldKey]: {
            ...currentMeta,
            actual_value: value,
            source: isChanged ? 'MANUAL' : currentMeta.source,
          },
        },
      }
    }))
  }

  function handleApprove(instrumentId) {
    setInstruments(prev => prev.filter(i => i.instrument_id !== instrumentId))
  }

  function handleReturn(instrumentId) {
    setReturnOpenFor(instrumentId)
  }

  function doReturn(instrumentId, reason, entry) {
    setInstruments(prev => prev.filter(i => i.instrument_id !== instrumentId))
    setReturnOpenFor(null)
  }

  const OCR_COLS = [
    { key: 'date',           label: 'Date',           w: 'w-28',  isBoolean: false },
    { key: 'payee',          label: 'Payee',          w: 'w-48',  isBoolean: false },
    { key: 'amount_figures', label: 'Amount',         w: 'w-32',  isBoolean: false },
    { key: 'amount_words',   label: 'Amount (words)', w: 'w-56',  isBoolean: false },
    { key: 'micr',           label: 'MICR',           w: 'w-28',  isBoolean: false },
    { key: 'alterations',    label: 'Alterations',    w: 'w-24',  isBoolean: true  },
  ]

  const approveLabel = isInward ? 'Approve → Submission IQ' : 'Approve → Submission OQ'

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>
        {/* Page header */}
        <div className={`px-6 py-4 border-b ${th.divider} shrink-0`}>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className={`text-lg font-semibold ${th.heading}`}>
                {isInward ? 'Validation IQ' : 'Validation OQ'}
              </h1>
              <p className={`text-xs ${th.muted} mt-0.5`}>
                Inline-editable OCR fields · Changed cells marked MANUAL · {approveLabel} to proceed
              </p>
            </div>
            <div className={`text-[10px] px-3 py-1.5 rounded-lg border font-medium ${isDark ? 'bg-amber-400/5 border-amber-400/20 text-amber-400' : 'bg-amber-50 border-amber-300 text-amber-700'}`}>
              Stage 2 of 3 — Validation
            </div>
          </div>

          {/* Stats */}
          <div className="flex items-center gap-4 mb-3">
            {[
              { label: 'Total', val: instruments.length, color: th.heading },
              { label: 'STP Auto',  val: stpCount,      color: 'text-emerald-400' },
              { label: 'Human Verified', val: verifiedCount, color: isDark ? 'text-amber-400' : 'text-amber-600' },
              { label: 'Edited', val: editedCount,       color: 'text-sky-400' },
            ].map(({ label, val, color }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className={`text-2xl font-bold font-mono ${color}`}>{val}</span>
                <span className={`text-[10px] ${th.lbl}`}>{label}</span>
              </div>
            ))}

            <div className="ml-auto flex items-center gap-1">
              {[['ALL', 'All'], ['STP', 'STP Auto'], ['VERIFIED', 'Human Approved']].map(([val, lbl]) => (
                <button key={val} onClick={() => setFilter(val)}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium transition-all ${filter === val ? (isDark ? 'bg-white/15 text-white' : 'bg-slate-800 text-white') : (isDark ? 'text-slate-400 hover:bg-white/5' : 'text-slate-500 hover:bg-slate-100')}`}
                >{lbl}</button>
              ))}
            </div>
          </div>

          {/* Help text */}
          <div className={`text-[11px] ${th.lbl} flex items-center gap-3`}>
            <span>Click any cell to edit</span>
            <span>·</span>
            <span>Edited cells highlight <span className={isDark ? 'text-amber-400 font-semibold' : 'text-amber-600 font-semibold'}>amber</span> and mark field as MANUAL</span>
            <span>·</span>
            <span>Bulk approve coming soon</span>
          </div>
        </div>

        {/* Grid */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs border-collapse" style={{ minWidth: '1100px' }}>
            <thead>
              <tr className={`border-b ${th.th} text-left`}>
                <th className={`sticky left-0 z-10 px-4 py-2.5 text-[10px] uppercase tracking-wider font-semibold ${isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'} border-r w-36`}>Instrument</th>
                <th className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-24`}>Source</th>
                {!isInward && <th className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-40`}>Drawee Bank</th>}
                {isInward  && <th className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-28`}>Account</th>}
                {isInward  && <th className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-20 text-right`}>IET</th>}
                {OCR_COLS.map(col => (
                  <th key={col.key} className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold ${col.w}`}>{col.label}</th>
                ))}
                <th className={`px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-20 text-center`}>Flags</th>
                <th className="px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-56 text-right">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={20} className={`text-center py-12 ${th.lbl}`}>
                    No instruments in validation queue.
                  </td>
                </tr>
              )}
              {filtered.map(inst => {
                const manualCount = Object.values(inst.fields_meta).filter(m => m.source === 'MANUAL').length
                const isSTP       = inst.source_stage === 'STP'
                const minsLeft    = inst.iet_deadline ? Math.max(0, Math.round((new Date(inst.iet_deadline) - Date.now()) / 60000)) : null
                const ietUrgent   = minsLeft != null && minsLeft < 45

                return (
                  <tr key={inst.instrument_id} className={`border-b ${th.row} transition-colors`}>
                    {/* Instrument ID */}
                    <td className={`sticky left-0 z-10 px-4 py-2 border-r ${isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'}`}>
                      <div className={`font-mono text-[11px] font-semibold ${isDark ? 'text-gold-400' : 'text-amber-600'}`}>{inst.instrument_id}</div>
                      {manualCount > 0 && (
                        <div className={`text-[9px] mt-0.5 ${isDark ? 'text-amber-400/70' : 'text-amber-600/70'}`}>{manualCount} MANUAL field{manualCount > 1 ? 's' : ''}</div>
                      )}
                    </td>

                    {/* Source stage */}
                    <td className="px-3 py-2">
                      <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border whitespace-nowrap ${
                        isSTP
                          ? (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700')
                          : (isDark ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' : 'bg-sky-50 border-sky-400 text-sky-700')
                      }`}>{isSTP ? 'STP' : 'VERIFIED'}</span>
                    </td>

                    {/* Bank / Account */}
                    {!isInward && (
                      <td className={`px-3 py-2 text-[11px] ${th.muted} truncate max-w-[160px]`}>
                        <div>{inst.drawee_bank}</div>
                        <div className={`text-[9px] ${th.lbl}`}>{inst.drawee_branch}</div>
                      </td>
                    )}
                    {isInward && (
                      <td className={`px-3 py-2 font-mono text-[11px] ${th.muted}`}>{inst.account_display}</td>
                    )}

                    {/* IET — inward only */}
                    {isInward && (
                      <td className="px-3 py-2 text-right">
                        <span className={`text-[11px] font-mono font-semibold ${ietUrgent ? 'text-red-400 animate-pulse' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>
                          {minsLeft}m
                        </span>
                      </td>
                    )}

                    {/* Editable OCR field cells */}
                    {OCR_COLS.map(col => {
                      const fieldMeta = inst.fields_meta[col.key] ?? { actual_value: '', source: 'STP' }
                      return (
                        <td key={col.key} className={`px-2 py-1.5 ${col.w}`}>
                          <div className="flex flex-col gap-0.5">
                            <EditCell
                              value={fieldMeta.actual_value}
                              onChange={v => handleEdit(inst.instrument_id, col.key, v)}
                              isDark={isDark}
                              isManual={fieldMeta.source === 'MANUAL'}
                              isBoolean={col.isBoolean}
                            />
                            <SBadge source={fieldMeta.source} isDark={isDark} />
                          </div>
                        </td>
                      )
                    })}

                    {/* Flags */}
                    <td className="px-3 py-2 text-center">
                      {inst.fields_meta.alterations?.actual_value
                        ? <span className="text-[10px] text-red-400 font-semibold">⚠ ALT</span>
                        : <span className={`text-[10px] ${th.lbl}`}>—</span>
                      }
                    </td>

                    {/* Actions */}
                    <td className="px-3 py-2">
                      <div className="flex items-center gap-2 justify-end relative">
                        <button onClick={() => handleApprove(inst.instrument_id)}
                          className={`px-3 py-1 rounded-lg border text-[11px] font-semibold transition-all whitespace-nowrap ${isDark ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20' : 'border-emerald-500 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'}`}
                        >✓ {approveLabel}</button>
                        <div className="relative">
                          <button onClick={() => setReturnOpenFor(returnOpenFor === inst.instrument_id ? null : inst.instrument_id)}
                            className={`px-2 py-1 rounded-lg border text-[11px] font-semibold transition-all ${isDark ? 'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'border-red-400 bg-red-50 text-red-700 hover:bg-red-100'}`}
                          >✕ Return ↓</button>
                          {returnOpenFor === inst.instrument_id && (
                            <RowReturnMenu isDark={isDark}
                              onReturn={(reason, entry) => doReturn(inst.instrument_id, reason, entry)}
                              onClose={() => setReturnOpenFor(null)}
                            />
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        {/* Footer summary */}
        {instruments.length > 0 && (
          <div className={`px-6 py-2.5 border-t ${th.divider} flex items-center gap-4 shrink-0`}>
            <span className={`text-[11px] ${th.lbl}`}>{filtered.length} of {instruments.length} instrument{instruments.length !== 1 ? 's' : ''} shown</span>
            {editedCount > 0 && (
              <span className={`text-[11px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{editedCount} with manual edits</span>
            )}
            <div className="ml-auto flex items-center gap-2">
              <span className={`text-[11px] ${th.lbl}`}>Approved instruments flow to</span>
              <span className={`text-[11px] font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>{isInward ? 'Submission IQ' : 'Submission OQ'}</span>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
