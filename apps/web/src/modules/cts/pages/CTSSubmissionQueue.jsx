/**
 * CTSSubmissionQueue — Submission stage (Stage 3).
 * Cheque image visible in the detail panel via tabs: Front | Back | Pay-in Slip | Fields.
 */
import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { getReasonByLabel, getReturnReasons } from '../data/returnReasons'
import { MockChequeFront, MockChequeBack, MockPayinSlip } from '../components/MockCheque'

// ── Mock data ─────────────────────────────────────────────────────────────────

const MOCK_OUTWARD = [
  {
    instrument_id: 'CHQ-OUT-S001', drawee_bank: 'State Bank of India', drawee_branch: 'Andheri East', source_stage: 'STP',
    date: '15/07/2026', payee: 'Rajesh Kumar Verma', amount_figures: '₹12,50,000', amount_words: 'Twelve Lakh Fifty Thousand Only', micr: '400002123',
    alterations: false, manual_fields: [], ocr_score: 0.98, fraud_score: 0.03, sig_score: 0.96, iqa_score: 0.99,
  },
  {
    instrument_id: 'CHQ-OUT-S002', drawee_bank: 'HDFC Bank', drawee_branch: 'Bandra West', source_stage: 'VERIFIED',
    date: '14/07/2026', payee: 'Sunita P. Joshi', amount_figures: '₹2,40,000', amount_words: 'Two Lakh Forty Thousand Only', micr: '400001234',
    alterations: false, manual_fields: ['payee', 'amount_words'], ocr_score: 0.88, fraud_score: 0.07, sig_score: 0.91, iqa_score: 0.97,
  },
  {
    instrument_id: 'CHQ-OUT-S003', drawee_bank: 'Bank of Baroda', drawee_branch: 'Fort', source_stage: 'VERIFIED',
    date: '15/07/2026', payee: 'Kavita R. Desai', amount_figures: '₹3,80,500', amount_words: 'Three Lakh Eighty Thousand Five Hundred Only', micr: '400008901',
    alterations: false, manual_fields: ['payee', 'amount_figures', 'amount_words'], ocr_score: 0.85, fraud_score: 0.11, sig_score: 0.88, iqa_score: 0.96,
  },
]

const MOCK_INWARD = [
  {
    instrument_id: 'CHQ-IN-S001', account_display: '****4521', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Dadar', source_stage: 'STP',
    iet_deadline: new Date(Date.now() + 68 * 60000).toISOString(),
    date: '15/07/2026', payee: 'Ramesh N. Rao', amount_figures: '₹45,000', amount_words: 'Forty Five Thousand Only', micr: '400005678',
    alterations: false, manual_fields: [], ocr_score: 0.99, fraud_score: 0.02, sig_score: 0.98, iqa_score: 0.99,
  },
  {
    instrument_id: 'CHQ-IN-S002', account_display: '****8912', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Vile Parle', source_stage: 'VERIFIED',
    iet_deadline: new Date(Date.now() + 22 * 60000).toISOString(),
    date: '14/07/2026', payee: 'Meena S. Sharma', amount_figures: '₹3,20,000', amount_words: 'Three Lakh Twenty Thousand Only', micr: '400009012',
    alterations: false, manual_fields: ['payee', 'amount_words'], ocr_score: 0.88, fraud_score: 0.09, sig_score: 0.92, iqa_score: 0.97,
  },
  {
    instrument_id: 'CHQ-IN-S003', account_display: '****6677', drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Borivali', source_stage: 'VERIFIED',
    iet_deadline: new Date(Date.now() + 51 * 60000).toISOString(),
    date: '15/07/2026', payee: 'Suresh B. Agarwal', amount_figures: '₹1,10,000', amount_words: 'One Lakh Ten Thousand Only', micr: '400007890',
    alterations: false, manual_fields: ['payee'], ocr_score: 0.89, fraud_score: 0.07, sig_score: 0.93, iqa_score: 0.97,
  },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

function ScorePill({ label, value, isDark }) {
  const pct = Math.round(value * 100)
  const color = value >= 0.95 ? 'emerald' : value >= 0.85 ? 'amber' : 'red'
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

function FieldRow({ label, value, isDark, isManual }) {
  return (
    <div className={`flex items-start gap-2 py-1.5 border-b text-xs ${isDark ? 'border-white/5' : 'border-slate-100'}`}>
      <span className={`w-32 shrink-0 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{label}</span>
      <span className={`flex-1 font-mono ${isManual ? (isDark ? 'text-amber-300' : 'text-amber-700') : (isDark ? 'text-slate-200' : 'text-slate-800')}`}>{value}</span>
      {isManual && <span className={`text-[9px] font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>MANUAL</span>}
    </div>
  )
}

function IETMini({ deadline, isDark }) {
  const [mins, setMins] = useState(0)
  useEffect(() => {
    function tick() { setMins(Math.max(0, Math.round((new Date(deadline) - Date.now()) / 60000))) }
    tick()
    const t = setInterval(tick, 10000)
    return () => clearInterval(t)
  }, [deadline])
  const urgent = mins < 30
  return (
    <span className={`font-mono text-[11px] font-semibold ${urgent ? 'text-red-400 animate-pulse' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>
      IET {mins}m {urgent ? '⚠' : ''}
    </span>
  )
}

function ReturnPicker({ isDark, onReturn, onClose }) {
  const [search, setSearch] = useState('')
  const grouped = getReturnReasons()
  return (
    <div className={`absolute bottom-14 left-0 z-50 w-72 rounded-xl border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
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

function ConfirmCountdown({ onConfirm, onCancel, isDark }) {
  const [count, setCount] = useState(2)
  const timerRef = useRef(null)
  useEffect(() => {
    timerRef.current = setInterval(() => {
      setCount(c => {
        if (c <= 1) { clearInterval(timerRef.current); onConfirm(); return 0 }
        return c - 1
      })
    }, 1000)
    return () => clearInterval(timerRef.current)
  }, [onConfirm])

  return (
    <div className={`flex items-center gap-3 px-4 py-2.5 rounded-xl border ${isDark ? 'bg-emerald-500/10 border-emerald-500/30' : 'bg-emerald-50 border-emerald-400'}`}>
      <div className={`text-sm font-bold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>Confirming in {count}s…</div>
      <div className={`flex-1 h-1 rounded-full overflow-hidden ${isDark ? 'bg-white/10' : 'bg-emerald-200'}`}>
        <div className={`h-full rounded-full ${isDark ? 'bg-emerald-400' : 'bg-emerald-500'} transition-all`} style={{ width: `${(count / 2) * 100}%` }} />
      </div>
      <button type="button" onClick={() => { clearInterval(timerRef.current); onCancel() }}
        className={`text-xs font-semibold ${isDark ? 'text-slate-400 hover:text-white' : 'text-slate-500 hover:text-slate-800'}`}
      >Cancel</button>
    </div>
  )
}

// ── Detail panel ──────────────────────────────────────────────────────────────

const IMG_TABS = [
  { id: 'front',      label: '▣ Front' },
  { id: 'back',       label: '▣ Back' },
  { id: 'payinslip',  label: '🧾 Pay-in Slip' },
  { id: 'fields',     label: '📋 Fields' },
]

function DetailPanel({ item, isInward, isDark, onConfirm, onReturn }) {
  const [imgTab, setImgTab] = useState('front')
  const [showReturnPicker, setShowReturnPicker] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [submitted, setSubmitted] = useState(false)

  const th = {
    heading: isDark ? 'text-white' : 'text-slate-900',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  function handleConfirm() { setSubmitted(true); onConfirm(item.instrument_id) }

  if (submitted) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3">
        <div className="text-4xl">✓</div>
        <div className={`text-lg font-semibold ${th.heading}`}>{isInward ? 'Confirmed' : 'Filed to NGCH'}</div>
        <div className={`text-sm ${th.muted}`}>{item.instrument_id}</div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Panel header */}
      <div className={`px-5 py-3 border-b ${th.divider} shrink-0`}>
        <div className="flex items-center gap-3">
          <div>
            <div className={`font-mono text-sm font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{item.instrument_id}</div>
            {isInward
              ? <div className={`text-xs mt-0.5 ${th.muted}`}>Account {item.account_display} · {item.drawee_bank}</div>
              : <div className={`text-xs mt-0.5 ${th.muted}`}>{item.drawee_bank} · {item.drawee_branch}</div>
            }
          </div>
          <div className="ml-auto flex flex-col items-end gap-1">
            <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border ${
              item.source_stage === 'STP'
                ? (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700')
                : (isDark ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' : 'bg-sky-50 border-sky-400 text-sky-700')
            }`}>{item.source_stage}</span>
            {isInward && item.iet_deadline && <IETMini deadline={item.iet_deadline} isDark={isDark} />}
          </div>
        </div>
      </div>

      {/* AI scores */}
      <div className={`px-5 py-3 border-b ${th.divider} shrink-0`}>
        <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>AI Scores</div>
        <div className="grid grid-cols-4 gap-2">
          <ScorePill label="OCR"   value={item.ocr_score}         isDark={isDark} />
          <ScorePill label="Sig"   value={item.sig_score}         isDark={isDark} />
          <ScorePill label="Fraud" value={1 - item.fraud_score}   isDark={isDark} />
          <ScorePill label="IQA"   value={item.iqa_score}         isDark={isDark} />
        </div>
      </div>

      {/* Image / fields tabs */}
      <div className={`flex border-b ${th.divider} shrink-0`}>
        {IMG_TABS.map(t => (
          <button key={t.id} type="button" onClick={() => setImgTab(t.id)}
            className={`px-3 py-2 text-[11px] font-medium transition-colors border-b-2 -mb-px whitespace-nowrap ${imgTab === t.id
              ? (isDark ? 'border-amber-400 text-amber-300' : 'border-amber-500 text-amber-700')
              : (isDark ? 'border-transparent text-slate-500 hover:text-slate-300' : 'border-transparent text-slate-400 hover:text-slate-600')
            }`}
          >{t.label}</button>
        ))}
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto">
        {imgTab === 'front' && (
          <div className="flex flex-col items-center justify-center p-5 gap-2 min-h-full">
            <MockChequeFront item={item} />
            <div className={`text-[9px] ${th.lbl}`}>CTS-2010 · Front of cheque — colour scan</div>
          </div>
        )}
        {imgTab === 'back' && (
          <div className="flex flex-col items-center justify-center p-5 gap-2 min-h-full">
            <MockChequeBack />
            <div className={`text-[9px] ${th.lbl}`}>CTS-2010 · Back of cheque — endorsement area</div>
          </div>
        )}
        {imgTab === 'payinslip' && (
          <div className="flex flex-col items-center justify-center p-5 gap-2 min-h-full">
            <MockPayinSlip item={item} />
            <div className={`text-[9px] ${th.lbl}`}>Pay-in / deposit slip captured at branch</div>
          </div>
        )}
        {imgTab === 'fields' && (
          <div className="px-5 py-3">
            <div className={`text-[10px] font-semibold uppercase tracking-wider mb-2 ${th.lbl}`}>
              Validated Fields
              {item.manual_fields?.length > 0 && (
                <span className={`ml-2 font-normal lowercase ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>
                  ({item.manual_fields.length} manually corrected)
                </span>
              )}
            </div>
            <FieldRow label="Date"           value={item.date}           isDark={isDark} />
            <FieldRow label="Payee"          value={item.payee}          isDark={isDark} isManual={item.manual_fields?.includes('payee')} />
            <FieldRow label="Amount"         value={item.amount_figures}  isDark={isDark} isManual={item.manual_fields?.includes('amount_figures')} />
            <FieldRow label="Amount (words)" value={item.amount_words}    isDark={isDark} isManual={item.manual_fields?.includes('amount_words')} />
            <FieldRow label="MICR"           value={item.micr}            isDark={isDark} />
            <FieldRow label="Alterations"    value={item.alterations ? '⚠ Detected' : '✓ None'} isDark={isDark} />
          </div>
        )}
      </div>

      {/* Footer actions */}
      <div className={`px-5 py-3 border-t ${th.divider} shrink-0 flex flex-col gap-2 relative`}>
        {showReturnPicker && (
          <ReturnPicker isDark={isDark}
            onReturn={(reason, entry) => { setShowReturnPicker(false); onReturn(item.instrument_id, reason, entry) }}
            onClose={() => setShowReturnPicker(false)}
          />
        )}
        {confirming && isInward
          ? <ConfirmCountdown isDark={isDark} onConfirm={handleConfirm} onCancel={() => setConfirming(false)} />
          : (
            <button type="button" onClick={() => isInward ? setConfirming(true) : handleConfirm()}
              className={`w-full py-2.5 rounded-xl text-sm font-semibold transition-all ${isDark ? 'bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/30' : 'bg-emerald-500 text-white hover:bg-emerald-600'}`}
            >{isInward ? '✓ Confirm — File to NGCH' : '↑ Submit to NGCH'}</button>
          )
        }
        <button type="button" onClick={() => setShowReturnPicker(v => !v)}
          className={`w-full py-2 rounded-xl text-sm font-semibold transition-all border ${isDark ? 'border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20' : 'border-red-300 bg-red-50 text-red-700 hover:bg-red-100'}`}
        >✕ Return to Verification</button>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function CTSSubmissionQueue({ mode = 'outward' }) {
  const { isDark } = useTheme()
  const isInward = mode === 'inward'
  const BASE = isInward ? MOCK_INWARD : MOCK_OUTWARD

  const [instruments, setInstruments] = useState(BASE)
  const [selected, setSelected]       = useState(BASE[0]?.instrument_id ?? null)

  const th = {
    page:    isDark ? 'bg-navy-950'       : 'bg-slate-50',
    heading: isDark ? 'text-white'        : 'text-slate-900',
    lbl:     isDark ? 'text-slate-500'    : 'text-slate-400',
    muted:   isDark ? 'text-slate-400'    : 'text-slate-500',
    divider: isDark ? 'border-white/8'    : 'border-slate-200',
    row:     isDark ? 'border-white/5'    : 'border-slate-100',
    rowHov:  isDark ? 'hover:bg-white/3'  : 'hover:bg-slate-50',
    selRow:  isDark ? 'bg-white/6 border-l-2 border-amber-400' : 'bg-amber-50 border-l-2 border-amber-500',
  }

  const selectedItem = instruments.find(i => i.instrument_id === selected)

  function handleConfirm(instrumentId) {
    setTimeout(() => {
      setInstruments(prev => {
        const next = prev.filter(i => i.instrument_id !== instrumentId)
        setSelected(next[0]?.instrument_id ?? null)
        return next
      })
    }, 1200)
  }

  function handleReturn(instrumentId) {
    setInstruments(prev => {
      const next = prev.filter(i => i.instrument_id !== instrumentId)
      setSelected(next[0]?.instrument_id ?? null)
      return next
    })
  }

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>
        {/* Page header */}
        <div className={`px-6 py-3 border-b ${th.divider} shrink-0 flex items-center gap-4`}>
          <div>
            <h1 className={`text-base font-semibold ${th.heading}`}>{isInward ? 'Submission IQ' : 'Submission OQ'}</h1>
            <p className={`text-[11px] ${th.muted}`}>
              {isInward ? 'Cheque image · 2s cancellable confirm before NGCH filing' : 'Cheque image · Submit to NGCH · Confirmed → Outward File'}
            </p>
          </div>
          <div className={`ml-auto text-[10px] px-3 py-1 rounded-lg border font-medium ${isDark ? 'bg-violet-400/5 border-violet-400/20 text-violet-400' : 'bg-violet-50 border-violet-300 text-violet-700'}`}>
            Stage 3 of 3 — Submission
          </div>
          <div className={`text-[11px] font-semibold ${th.heading}`}>{instruments.length} pending</div>
        </div>

        {/* Split layout */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          {/* Left: instrument list */}
          <div className={`w-64 shrink-0 flex flex-col border-r ${th.divider} overflow-hidden`}>
            <div className="flex-1 overflow-y-auto">
              {instruments.length === 0 ? (
                <div className={`flex flex-col items-center justify-center h-full gap-2 ${th.lbl}`}>
                  <div className="text-3xl">✓</div>
                  <div className="text-sm">Queue empty</div>
                  <div className="text-[11px]">All instruments filed</div>
                </div>
              ) : instruments.map(inst => {
                const isSel = inst.instrument_id === selected
                const minsLeft = inst.iet_deadline ? Math.max(0, Math.round((new Date(inst.iet_deadline) - Date.now()) / 60000)) : null
                const urgent = minsLeft != null && minsLeft < 30
                return (
                  <button key={inst.instrument_id} type="button" onClick={() => setSelected(inst.instrument_id)}
                    className={`w-full text-left px-4 py-3 border-b transition-all ${th.row} ${isSel ? th.selRow : th.rowHov}`}
                  >
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-[11px] font-bold truncate ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{inst.instrument_id}</span>
                      <span className={`ml-auto text-[9px] font-bold px-1.5 py-0.5 rounded-full border shrink-0 ${
                        inst.source_stage === 'STP'
                          ? (isDark ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400' : 'bg-emerald-50 border-emerald-400 text-emerald-700')
                          : (isDark ? 'bg-sky-500/10 border-sky-500/30 text-sky-400' : 'bg-sky-50 border-sky-400 text-sky-700')
                      }`}>{inst.source_stage}</span>
                    </div>
                    <div className={`text-[11px] ${th.muted} mt-0.5 truncate`}>
                      {isInward ? `Acct ${inst.account_display}` : inst.drawee_bank}
                    </div>
                    {isInward && minsLeft != null && (
                      <div className={`text-[10px] font-mono font-semibold mt-0.5 ${urgent ? 'text-red-400' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>
                        IET {minsLeft}m {urgent ? '⚠' : ''}
                      </div>
                    )}
                    <div className={`text-[11px] ${th.muted} mt-0.5`}>{inst.amount_figures}</div>
                    {inst.manual_fields?.length > 0 && (
                      <div className={`text-[9px] mt-0.5 ${isDark ? 'text-amber-400/60' : 'text-amber-600/60'}`}>
                        {inst.manual_fields.length} MANUAL field{inst.manual_fields.length > 1 ? 's' : ''}
                      </div>
                    )}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Right: detail panel with cheque image tabs */}
          <div className="flex-1 min-w-0 overflow-hidden">
            {selectedItem
              ? <DetailPanel key={selectedItem.instrument_id} item={selectedItem} isInward={isInward} isDark={isDark} onConfirm={handleConfirm} onReturn={handleReturn} />
              : (
                <div className={`h-full flex flex-col items-center justify-center gap-2 ${th.lbl}`}>
                  <div className="text-4xl">✓</div>
                  <div className="text-sm font-medium">Submission queue empty</div>
                  <div className="text-[11px]">All instruments processed</div>
                </div>
              )
            }
          </div>
        </div>
      </div>
    </AppShell>
  )
}
