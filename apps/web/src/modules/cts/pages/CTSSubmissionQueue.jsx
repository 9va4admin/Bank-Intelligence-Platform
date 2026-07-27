/**
 * CTSSubmissionQueue — Submission stage (Stage 3).
 * Cheque image visible in the detail panel via tabs: Front | Back | Pay-in Slip | Fields.
 */
import { useState, useEffect, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { getReasonByLabel, getReturnReasons } from '../data/returnReasons'

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

// ── Mock cheque images ────────────────────────────────────────────────────────

function MockChequeFront({ item }) {
  const bank    = item.drawee_bank    || 'HDFC Bank'
  const branch  = item.drawee_branch  || 'Main Branch'
  const date    = item.date           || ''
  const payee   = item.payee          || '—'
  const amtFig  = (item.amount_figures || '').replace('₹', '').trim()
  const amtWrd  = item.amount_words   || '—'
  const micr    = item.micr           || '000000000'
  const account = item.account_display || '●●●●●●●'
  const chqNo   = item.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'

  const parts   = date.split('/')
  const dd      = (parts[0] || '').padStart(2, ' ')
  const mm      = (parts[1] || '').padStart(2, ' ')
  const yyyy    = (parts[2] || '').padStart(4, ' ')
  const dDigits = [...dd, ...mm, ...yyyy]

  return (
    <div style={{ width: '100%', maxWidth: '560px', aspectRatio: '2.45/1', background: '#fefefe', border: '1.5px solid #aaa', borderRadius: '3px', position: 'relative', overflow: 'hidden', boxShadow: '0 4px 24px rgba(0,0,0,0.22)', userSelect: 'none' }}>
      {/* Left security strip */}
      <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: '16px', background: 'repeating-linear-gradient(45deg,#d8e8f0,#d8e8f0 1.5px,#f5f8fc 1.5px,#f5f8fc 6px)', borderRight: '1px solid #bcd' }} />
      <div style={{ position: 'absolute', left: '3px', top: '50%', transform: 'translateY(-50%) rotate(-90deg)', fontSize: '5px', color: '#aab', whiteSpace: 'nowrap', letterSpacing: '1px', fontFamily: 'Arial,sans-serif' }}>CTS-2010 • CLEARING SYSTEM</div>
      {/* Watermark */}
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.025, fontSize: '52px', fontWeight: 900, color: '#000', letterSpacing: 8, fontFamily: 'Arial Black,sans-serif', pointerEvents: 'none' }}>ORIGINAL</div>

      <div style={{ marginLeft: '18px', height: '100%', display: 'flex', flexDirection: 'column', padding: '5px 8px 2px 6px', boxSizing: 'border-box', fontFamily: 'Arial,sans-serif' }}>
        {/* Header: bank + date */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '3px' }}>
          <div>
            <div style={{ fontWeight: 800, fontSize: '12px', color: '#003087' }}>{bank}</div>
            <div style={{ fontSize: '7px', color: '#444', marginTop: '1px' }}>{branch} Branch</div>
            <div style={{ fontSize: '6.5px', color: '#666' }}>RTGS / NEFT IFSC : {bank.replace(/\s/g,'').slice(0,4).toUpperCase()}0{micr.slice(0,6)}</div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '6px', color: '#777', marginBottom: '2px' }}>VALID FOR THREE MONTHS FROM DATE OF ISSUE</div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', alignItems: 'center' }}>
              <span style={{ fontSize: '7px', color: '#555', marginRight: '3px', lineHeight: 1.3 }}>दिनांक<br/>Date</span>
              {dDigits.map((d, i) => (
                <span key={i} style={{ display: 'inline-flex', width: '14px', height: '17px', border: '1px solid #555', justifyContent: 'center', alignItems: 'center', fontFamily: 'monospace', fontWeight: 'bold', fontSize: '11px', background: '#fff', marginLeft: (i === 2 || i === 4) ? '3px' : '0' }}>{d?.trim() || ''}</span>
              ))}
            </div>
            <div style={{ display: 'flex', gap: '1.5px', justifyContent: 'flex-end', marginTop: '1px', paddingLeft: '28px' }}>
              <span style={{ fontSize: '5.5px', color: '#999', width: '30px', textAlign: 'center' }}>D D</span>
              <span style={{ fontSize: '5.5px', color: '#999', width: '30px', textAlign: 'center', marginLeft: '3px' }}>M M</span>
              <span style={{ fontSize: '5.5px', color: '#999', width: '58px', textAlign: 'center', marginLeft: '3px' }}>Y Y Y Y</span>
            </div>
          </div>
        </div>

        {/* Pay line */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', borderBottom: '0.8px solid #222', paddingBottom: '1px', marginBottom: '2px' }}>
          <span style={{ fontSize: '8.5px', fontWeight: 'bold', minWidth: '20px' }}>Pay</span>
          <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '13px', fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{payee}</span>
          <span style={{ fontSize: '7.5px', color: '#111', whiteSpace: 'nowrap' }}>या धारक को Or Bearer</span>
        </div>

        {/* Rupees + amount box */}
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '6px', marginBottom: '4px' }}>
          <div style={{ flex: 1, borderBottom: '0.8px solid #222', paddingBottom: '1px', display: 'flex', alignItems: 'baseline', gap: '4px' }}>
            <span style={{ fontSize: '8px', fontWeight: 'bold', whiteSpace: 'nowrap' }}>Rupees रुपये</span>
            <span style={{ flex: 1, fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{amtWrd}</span>
          </div>
          <div style={{ display: 'flex', border: '1.5px solid #333', borderRadius: '2px', height: '30px', minWidth: '130px', overflow: 'hidden', flexShrink: 0 }}>
            <div style={{ padding: '1px 4px', borderRight: '1px solid #555', display: 'flex', flexDirection: 'column', justifyContent: 'center', background: '#f2f2ec', width: '40px', flexShrink: 0, textAlign: 'center' }}>
              <span style={{ fontSize: '5.5px', color: '#555' }}>अदा करें</span>
              <span style={{ fontSize: '12px', fontWeight: 'bold' }}>₹</span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '0 6px' }}>
              <span style={{ fontFamily: 'Georgia,serif', fontStyle: 'italic', fontSize: '14px', fontWeight: 700, whiteSpace: 'nowrap' }}>{amtFig}</span>
            </div>
          </div>
        </div>

        {/* Account No */}
        <div style={{ marginBottom: '2px' }}>
          <div style={{ display: 'inline-flex', border: '1px solid #888', borderRadius: '2px', padding: '1px 8px' }}>
            <div>
              <div style={{ fontSize: '6px', color: '#666' }}>खाता सं. A/c No.</div>
              <div style={{ fontFamily: 'monospace', fontSize: '11px', fontWeight: 'bold', letterSpacing: '0.5px' }}>{account}</div>
            </div>
          </div>
        </div>

        {/* Payable at par + signature */}
        <div style={{ flex: 1, display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end' }}>
          <div style={{ fontSize: '6px', color: '#888' }}>Payable at par through clearing/transfer at all branches</div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ width: '110px', borderTop: '1px solid #111', marginBottom: '1px' }} />
            <div style={{ fontSize: '7.5px', fontWeight: 'bold', textTransform: 'uppercase', letterSpacing: '0.3px' }}>{payee}</div>
            <div style={{ fontSize: '6px', color: '#666' }}>Please sign above / कृपया ऊपर हस्ताक्षर करें</div>
          </div>
        </div>

        {/* MICR line */}
        <div style={{ textAlign: 'center', fontFamily: 'monospace', fontSize: '8.5px', color: '#111', letterSpacing: '1.5px', borderTop: '0.5px solid #ddd', paddingTop: '2px', marginTop: '1px' }}>
          ⑆{chqNo}⑆{'  '}⑆{micr}⑆{'  '}{account.replace(/[●*]/g,'0').slice(0,12)}⑆{'  '}31
        </div>
      </div>
    </div>
  )
}

function MockChequeBack() {
  return (
    <div style={{
      width: '100%', maxWidth: '520px', aspectRatio: '2.38/1',
      background: 'linear-gradient(160deg, #f5f5f0 0%, #efefea 100%)',
      border: '1.5px solid #b8953a', borderRadius: '8px',
      fontFamily: 'serif', position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
    }}>
      <div style={{ position: 'absolute', inset: '4px', border: '0.5px dashed #aaa4', borderRadius: '5px' }} />
      <div style={{ padding: '12px 16px' }}>
        <div style={{ fontSize: '8px', color: '#888', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>Endorsement</div>
        {[0, 1, 2].map(i => (
          <div key={i} style={{ borderBottom: '0.5px solid #bbb', marginBottom: i < 2 ? '20px' : 0 }} />
        ))}
      </div>
      <div style={{ position: 'absolute', bottom: '10px', right: '14px', fontSize: '7px', color: '#bbb', fontFamily: 'monospace' }}>CTS-2010 Compliant</div>
    </div>
  )
}

function MockPayinSlip({ item }) {
  return (
    <div style={{
      width: '100%', maxWidth: '360px', aspectRatio: '1.55/1',
      background: 'linear-gradient(160deg, #f0f7ff 0%, #e8f0fc 100%)',
      border: '1.5px solid #4a7ab8', borderRadius: '8px',
      fontFamily: 'serif', position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
    }}>
      <div style={{ background: '#1a3a6e', color: '#fff', padding: '6px 14px 5px', fontSize: '9px', fontWeight: 700, letterSpacing: '0.5px' }}>
        PAY-IN SLIP / DEPOSIT SLIP
      </div>
      <div style={{ padding: '8px 14px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
        {[['Date', item.date], ['Branch', item.drawee_branch || '—'], ['A/c No.', item.account_display || '—●●●'], ['Cash / Cheque', 'Cheque']].map(([lbl, val]) => (
          <div key={lbl}>
            <div style={{ fontSize: '7px', color: '#666' }}>{lbl}</div>
            <div style={{ fontSize: '9px', fontWeight: 600, color: '#111', borderBottom: '0.5px solid #aaa', paddingBottom: '2px' }}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: '0 14px 6px' }}>
        <div style={{ fontSize: '7px', color: '#666' }}>Deposited by / Payee</div>
        <div style={{ fontSize: '9px', fontWeight: 600, color: '#111', borderBottom: '0.5px solid #aaa', paddingBottom: '2px' }}>{item.payee}</div>
      </div>
      <div style={{ padding: '4px 14px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '7px', color: '#666' }}>Amount</div>
          <div style={{ fontSize: '14px', fontFamily: 'monospace', fontWeight: 700, color: '#1a3a6e' }}>{item.amount_figures}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ width: '80px', borderTop: '0.5px solid #555', marginBottom: '2px' }} />
          <div style={{ fontSize: '7px', color: '#888' }}>Bank Stamp & Sign</div>
        </div>
      </div>
    </div>
  )
}

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
