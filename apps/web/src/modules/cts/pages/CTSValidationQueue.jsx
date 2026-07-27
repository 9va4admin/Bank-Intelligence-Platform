/**
 * CTSValidationQueue — Validation stage grid (Stage 2 of 3).
 *
 * Source column removed — instrument cell left-border colour codes STP (emerald) vs VERIFIED (sky).
 * Actions are icon buttons: ✓ approve · ↩ return (opens reason dropdown).
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
    instrument_id: 'CHQ-OUT-V001', source_stage: 'STP', drawee_bank: 'State Bank of India', drawee_branch: 'Andheri East',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.99), payee: makeMeta('Rajesh Kumar Verma', 0.97),
      amount_figures: makeMeta('₹12,50,000', 0.98), amount_words: makeMeta('Twelve Lakh Fifty Thousand Only', 0.95),
      micr: makeMeta('400002123', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V002', source_stage: 'VERIFIED', drawee_bank: 'HDFC Bank', drawee_branch: 'Bandra West',
    fields_meta: {
      date: makeMeta('14/07/2026', 0.97), payee: makeMeta('Sunita P. Joshi', 0.74),
      amount_figures: makeMeta('₹2,40,000', 0.91), amount_words: makeMeta('Two Lakh Forty Thousand Only', 0.88),
      micr: makeMeta('400001234', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V003', source_stage: 'STP', drawee_bank: 'ICICI Bank', drawee_branch: 'Powai',
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Amol Vilas Kulkarni', 0.96),
      amount_figures: makeMeta('₹75,000', 0.95), amount_words: makeMeta('Seventy Five Thousand Only', 0.93),
      micr: makeMeta('400004567', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V004', source_stage: 'VERIFIED', drawee_bank: 'Bank of Baroda', drawee_branch: 'Fort',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.98), payee: makeMeta('Kavita R. Desai', 0.85),
      amount_figures: makeMeta('₹3,80,500', 0.87), amount_words: makeMeta('Three Lakh Eighty Thousand Five Hundred Only', 0.82),
      micr: makeMeta('400008901', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V005', source_stage: 'STP', drawee_bank: 'Axis Bank', drawee_branch: 'Goregaon',
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Nikhil Santosh Pawar', 0.99),
      amount_figures: makeMeta('₹1,25,50,000', 0.99), amount_words: makeMeta('One Crore Twenty Five Lakh Fifty Thousand Only', 0.98),
      micr: makeMeta('400002345', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

const BASE_INSTRUMENTS_INWARD = [
  {
    instrument_id: 'CHQ-IN-V001', source_stage: 'STP', account_display: '****4521', iet_deadline: new Date(Date.now() + 72 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Dadar',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.99), payee: makeMeta('Ramesh N. Rao', 0.97),
      amount_figures: makeMeta('₹45,000', 0.98), amount_words: makeMeta('Forty Five Thousand Only', 0.95),
      micr: makeMeta('400005678', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V002', source_stage: 'VERIFIED', account_display: '****8912', iet_deadline: new Date(Date.now() + 28 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Vile Parle',
    fields_meta: {
      date: makeMeta('14/07/2026', 0.96), payee: makeMeta('Meena S. Sharma', 0.82),
      amount_figures: makeMeta('₹3,20,000', 0.88), amount_words: makeMeta('Three Lakh Twenty Thousand Only', 0.79),
      micr: makeMeta('400009012', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V003', source_stage: 'STP', account_display: '****2234', iet_deadline: new Date(Date.now() + 115 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Pune Main',
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Priya R. Nair', 0.96),
      amount_figures: makeMeta('₹8,000', 0.97), amount_words: makeMeta('Eight Thousand Only', 0.94),
      micr: makeMeta('400003456', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-IN-V004', source_stage: 'VERIFIED', account_display: '****6677', iet_deadline: new Date(Date.now() + 54 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Borivali',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.98), payee: makeMeta('Suresh B. Agarwal', 0.86),
      amount_figures: makeMeta('₹1,10,000', 0.89), amount_words: makeMeta('One Lakh Ten Thousand Only', 0.84),
      micr: makeMeta('400007890', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

// ── Mock cheque images ────────────────────────────────────────────────────────

function MockChequeFront({ inst }) {
  const fm      = inst.fields_meta || {}
  const bank    = inst.drawee_bank                 || 'HDFC Bank'
  const branch  = inst.drawee_branch               || 'Main Branch'
  const date    = fm.date?.actual_value            || ''
  const payee   = fm.payee?.actual_value           || '—'
  const amtFig  = (fm.amount_figures?.actual_value || '').replace('₹', '').trim()
  const amtWrd  = fm.amount_words?.actual_value    || '—'
  const micr    = fm.micr?.actual_value            || '000000000'
  const account = inst.account_display             || '●●●●●●●'
  const chqNo   = inst.instrument_id?.replace(/\D/g, '').slice(-6).padStart(6, '0') || '000001'

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
              <span style={{ fontSize: '7px', color: '#555', marginRight: '3px', lineHeight: 1.3, fontFamily: 'Arial,sans-serif' }}>दिनांक<br/>Date</span>
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
      border: '1.5px solid #b8953a', borderRadius: '8px', position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
    }}>
      <div style={{ padding: '12px 16px' }}>
        <div style={{ fontSize: '8px', color: '#888', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '1px' }}>Endorsement</div>
        {[0, 1, 2].map(i => <div key={i} style={{ borderBottom: '0.5px solid #bbb', marginBottom: i < 2 ? '20px' : 0 }} />)}
      </div>
      <div style={{ position: 'absolute', bottom: '10px', right: '14px', fontSize: '7px', color: '#bbb', fontFamily: 'monospace' }}>CTS-2010 Compliant</div>
    </div>
  )
}

function MockPayinSlip({ inst }) {
  const fm = inst.fields_meta || {}
  return (
    <div style={{
      width: '100%', maxWidth: '360px', aspectRatio: '1.55/1',
      background: 'linear-gradient(160deg, #f0f7ff 0%, #e8f0fc 100%)',
      border: '1.5px solid #4a7ab8', borderRadius: '8px', position: 'relative', overflow: 'hidden',
      boxShadow: '0 4px 20px rgba(0,0,0,0.12)',
    }}>
      <div style={{ background: '#1a3a6e', color: '#fff', padding: '6px 14px 5px', fontSize: '9px', fontWeight: 700 }}>PAY-IN SLIP / DEPOSIT SLIP</div>
      <div style={{ padding: '8px 14px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
        {[['Date', fm.date?.actual_value || '—'], ['Branch', inst.drawee_branch || '—'], ['A/c No.', inst.account_display || '—'], ['Cash / Cheque', 'Cheque']].map(([lbl, val]) => (
          <div key={lbl}>
            <div style={{ fontSize: '7px', color: '#666' }}>{lbl}</div>
            <div style={{ fontSize: '9px', fontWeight: 600, color: '#111', borderBottom: '0.5px solid #aaa', paddingBottom: '2px' }}>{val}</div>
          </div>
        ))}
      </div>
      <div style={{ padding: '0 14px 4px' }}>
        <div style={{ fontSize: '7px', color: '#666' }}>Payee</div>
        <div style={{ fontSize: '9px', fontWeight: 600, color: '#111', borderBottom: '0.5px solid #aaa', paddingBottom: '2px' }}>{fm.payee?.actual_value || '—'}</div>
      </div>
      <div style={{ padding: '4px 14px 0', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: '7px', color: '#666' }}>Amount</div>
          <div style={{ fontSize: '14px', fontFamily: 'monospace', fontWeight: 700, color: '#1a3a6e' }}>{fm.amount_figures?.actual_value || '—'}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ width: '80px', borderTop: '0.5px solid #555', marginBottom: '2px' }} />
          <div style={{ fontSize: '7px', color: '#888' }}>Bank Stamp & Sign</div>
        </div>
      </div>
    </div>
  )
}

// ── Cheque slide-in panel ─────────────────────────────────────────────────────

function ChequePanel({ inst, isDark, onClose }) {
  const [tab, setTab] = useState('front')
  const tabs = [{ id: 'front', label: '▣ Front' }, { id: 'back', label: '▣ Back' }, { id: 'payinslip', label: '🧾 Pay-in Slip' }]

  return (
    <div className={`flex flex-col border-l h-full shrink-0 ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`} style={{ width: '400px' }}>
      <div className={`flex items-center gap-2 px-4 py-3 border-b shrink-0 ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <span className={`font-mono text-[11px] font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{inst.instrument_id}</span>
        <button type="button" onClick={onClose} className={`ml-auto text-lg leading-none ${isDark ? 'text-slate-500 hover:text-white' : 'text-slate-400 hover:text-slate-800'}`}>×</button>
      </div>
      <div className={`flex border-b shrink-0 ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        {tabs.map(t => (
          <button key={t.id} type="button" onClick={() => setTab(t.id)}
            className={`px-4 py-2 text-[11px] font-medium border-b-2 -mb-px transition-colors ${tab === t.id
              ? (isDark ? 'border-amber-400 text-amber-300' : 'border-amber-500 text-amber-700')
              : (isDark ? 'border-transparent text-slate-500 hover:text-slate-300' : 'border-transparent text-slate-400 hover:text-slate-600')
            }`}
          >{t.label}</button>
        ))}
      </div>
      <div className="flex-1 overflow-auto flex flex-col items-center justify-center p-5 gap-3">
        {tab === 'front'     && <MockChequeFront inst={inst} />}
        {tab === 'back'      && <MockChequeBack />}
        {tab === 'payinslip' && <MockPayinSlip inst={inst} />}
        <div className={`text-[9px] ${isDark ? 'text-slate-600' : 'text-slate-400'} text-center`}>
          {tab === 'front'     && 'CTS-2010 · Front — colour scan'}
          {tab === 'back'      && 'CTS-2010 · Back — endorsement area'}
          {tab === 'payinslip' && 'Pay-in / deposit slip — branch capture'}
        </div>
      </div>
    </div>
  )
}

// ── Return reason dropdown ────────────────────────────────────────────────────

function ReturnDropdown({ isDark, onReturn, onClose }) {
  const [search, setSearch] = useState('')
  const grouped = getReturnReasons()

  return (
    <div className={`absolute right-0 top-full mt-1 z-50 w-80 rounded-xl border shadow-2xl overflow-hidden ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`}>
      <div className={`flex items-center gap-2 px-3 py-2 border-b ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <span className={`text-[10px] font-semibold ${isDark ? 'text-slate-400' : 'text-slate-600'}`}>Return reason</span>
        <button type="button" onClick={onClose} className={`ml-auto text-base leading-none ${isDark ? 'text-slate-600 hover:text-white' : 'text-slate-400 hover:text-slate-700'}`}>×</button>
      </div>
      <div className={`px-3 py-2 border-b ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <input autoFocus type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Search…"
          className={`w-full text-xs bg-transparent outline-none ${isDark ? 'text-slate-300 placeholder-slate-600' : 'text-slate-700 placeholder-slate-400'}`}
          onKeyDown={e => e.key === 'Escape' && onClose()}
        />
      </div>
      <div className="max-h-60 overflow-y-auto">
        {Object.entries(grouped).map(([group, reasons]) => {
          const filtered = search ? reasons.filter(r => r.toLowerCase().includes(search.toLowerCase())) : reasons
          if (!filtered.length) return null
          return (
            <div key={group}>
              <div className={`px-3 pt-2 pb-1 text-[9px] uppercase font-semibold tracking-widest ${isDark ? 'text-slate-600' : 'text-slate-400'}`}>{group}</div>
              {filtered.map(r => {
                const entry = getReasonByLabel(r)
                return (
                  <button key={r} type="button" onMouseDown={() => { onReturn(r, entry); onClose() }}
                    className={`w-full text-left px-3 py-2 text-xs flex items-center justify-between gap-2 transition-colors ${isDark ? 'hover:bg-white/5 text-slate-300' : 'hover:bg-slate-50 text-slate-700'}`}
                  >
                    <span className="truncate">{r}</span>
                    {entry && (
                      <span className={`shrink-0 text-[9px] font-mono font-bold px-1.5 py-0.5 rounded ${entry.customerFault
                        ? (isDark ? 'bg-red-500/10 text-red-400' : 'bg-red-50 text-red-600')
                        : (isDark ? 'bg-sky-500/10 text-sky-400' : 'bg-sky-50 text-sky-600')
                      }`}>{entry.code}</span>
                    )}
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
  if (isBoolean) {
    return (
      <select value={value ? 'yes' : 'no'} onChange={e => onChange(e.target.value === 'yes')}
        className={`w-full text-[11px] font-mono px-1 py-0.5 rounded border focus:outline-none ${isManual
          ? (isDark ? 'border-amber-400/50 bg-amber-400/5 text-amber-300' : 'border-amber-400 bg-amber-50 text-amber-800')
          : (isDark ? 'bg-transparent border-transparent text-slate-200 hover:border-white/15' : 'bg-transparent border-transparent text-slate-800 hover:border-slate-300')}`}
      >
        <option value="no">✓ None</option>
        <option value="yes">⚠ Detected</option>
      </select>
    )
  }
  return (
    <input type="text" value={String(value ?? '')} onChange={e => onChange(e.target.value)}
      className={`w-full text-[11px] font-mono px-1 py-0.5 rounded border focus:outline-none transition-colors ${isManual
        ? (isDark ? 'border-amber-400/50 bg-amber-400/5 text-amber-300' : 'border-amber-400 bg-amber-50 text-amber-800')
        : (isDark ? 'bg-transparent border-transparent text-slate-200 hover:border-white/15 focus:border-white/30' : 'bg-transparent border-transparent text-slate-800 hover:border-slate-300 focus:border-slate-400')}`}
    />
  )
}

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
  const [filter, setFilter]           = useState('ALL')
  const [returnOpenFor, setReturnOpenFor] = useState(null)
  const [chequeViewId, setChequeViewId]   = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    heading: isDark ? 'text-white'  : 'text-slate-900',
    lbl:     isDark ? 'text-slate-500' : 'text-slate-400',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    thCell:  isDark ? 'text-slate-500 border-white/8' : 'text-slate-400 border-slate-200',
    rowBase: isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const filtered = instruments.filter(i => {
    if (filter === 'STP')      return i.source_stage === 'STP'
    if (filter === 'VERIFIED') return i.source_stage === 'VERIFIED'
    return true
  })

  const stpCount      = instruments.filter(i => i.source_stage === 'STP').length
  const verifiedCount = instruments.filter(i => i.source_stage === 'VERIFIED').length
  const editedCount   = instruments.filter(i => Object.keys(i.edits).length > 0).length
  const chequeInst    = chequeViewId ? instruments.find(i => i.instrument_id === chequeViewId) : null

  function handleEdit(instrumentId, fieldKey, value) {
    setInstruments(prev => prev.map(inst => {
      if (inst.instrument_id !== instrumentId) return inst
      const cur = inst.fields_meta[fieldKey]
      return {
        ...inst,
        edits: { ...inst.edits, [fieldKey]: value },
        fields_meta: {
          ...inst.fields_meta,
          [fieldKey]: { ...cur, actual_value: value, source: String(value) !== String(cur.extracted_value) ? 'MANUAL' : cur.source },
        },
      }
    }))
  }

  function handleApprove(instrumentId) {
    if (chequeViewId === instrumentId) setChequeViewId(null)
    setInstruments(prev => prev.filter(i => i.instrument_id !== instrumentId))
  }

  function doReturn(instrumentId) {
    if (chequeViewId === instrumentId) setChequeViewId(null)
    setInstruments(prev => prev.filter(i => i.instrument_id !== instrumentId))
    setReturnOpenFor(null)
  }

  const OCR_COLS = [
    { key: 'date',           label: 'Date',           w: 'w-28', isBoolean: false },
    { key: 'payee',          label: 'Payee',          w: 'w-44', isBoolean: false },
    { key: 'amount_figures', label: 'Amount',         w: 'w-28', isBoolean: false },
    { key: 'amount_words',   label: 'Amount (words)', w: 'w-52', isBoolean: false },
    { key: 'micr',           label: 'MICR',           w: 'w-24', isBoolean: false },
    { key: 'alterations',    label: 'Altered?',       w: 'w-20', isBoolean: true  },
  ]

  // Source colour coding for the instrument cell left border
  const sourceBar = (source_stage) =>
    source_stage === 'STP'
      ? (isDark ? 'border-l-4 border-emerald-500' : 'border-l-4 border-emerald-500')
      : (isDark ? 'border-l-4 border-sky-500'     : 'border-l-4 border-sky-500')

  const sourceDot = (source_stage) =>
    source_stage === 'STP'
      ? `${isDark ? 'text-emerald-400 bg-emerald-500/10' : 'text-emerald-700 bg-emerald-50'} border border-emerald-500/30`
      : `${isDark ? 'text-sky-400 bg-sky-500/10' : 'text-sky-700 bg-sky-50'} border border-sky-500/30`

  const approveLabel = isInward ? 'Submission IQ' : 'Submission OQ'

  return (
    <AppShell>
      <div className={`flex-1 flex flex-col min-h-0 ${th.page}`}>
        {/* Header */}
        <div className={`px-6 py-4 border-b ${th.divider} shrink-0`}>
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className={`text-lg font-semibold ${th.heading}`}>{isInward ? 'Validation IQ' : 'Validation OQ'}</h1>
              <p className={`text-xs ${th.muted} mt-0.5`}>
                Inline-editable grid · Changed cells → MANUAL ·
                <span className={`mx-1.5 inline-flex items-center gap-1 text-[10px] font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>█ STP</span>
                <span className={`inline-flex items-center gap-1 text-[10px] font-semibold ${isDark ? 'text-sky-400' : 'text-sky-700'}`}>█ Verified</span>
              </p>
            </div>
            <div className={`text-[10px] px-3 py-1.5 rounded-lg border font-medium ${isDark ? 'bg-amber-400/5 border-amber-400/20 text-amber-400' : 'bg-amber-50 border-amber-300 text-amber-700'}`}>
              Stage 2 of 3 — Validation
            </div>
          </div>

          <div className="flex items-center gap-5 mb-3">
            {[
              { label: 'Total',          val: instruments.length, color: th.heading },
              { label: 'STP Auto',       val: stpCount,           color: isDark ? 'text-emerald-400' : 'text-emerald-600' },
              { label: 'Human Verified', val: verifiedCount,      color: isDark ? 'text-sky-400' : 'text-sky-600' },
              { label: 'Edited',         val: editedCount,        color: isDark ? 'text-amber-400' : 'text-amber-600' },
            ].map(({ label, val, color }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className={`text-2xl font-bold font-mono ${color}`}>{val}</span>
                <span className={`text-[10px] ${th.lbl}`}>{label}</span>
              </div>
            ))}
            <div className="ml-auto flex items-center gap-1">
              {[['ALL', 'All'], ['STP', 'STP'], ['VERIFIED', 'Verified']].map(([val, lbl]) => (
                <button key={val} onClick={() => setFilter(val)}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium transition-all ${filter === val
                    ? (isDark ? 'bg-white/15 text-white' : 'bg-slate-800 text-white')
                    : (isDark ? 'text-slate-400 hover:bg-white/5' : 'text-slate-500 hover:bg-slate-100')
                  }`}
                >{lbl}</button>
              ))}
            </div>
          </div>

          <div className={`text-[11px] ${th.lbl} flex items-center gap-3`}>
            <span>Click cell to edit</span><span>·</span>
            <span>Edited → <span className={isDark ? 'text-amber-400 font-semibold' : 'text-amber-600 font-semibold'}>amber / MANUAL</span></span><span>·</span>
            <span>🖼 view cheque · ✓ approve · ↩ return with reason</span>
          </div>
        </div>

        {/* Grid + optional cheque panel */}
        <div className="flex-1 flex min-h-0 overflow-hidden">
          <div className="flex-1 overflow-auto">
            <table className="w-full text-xs border-collapse" style={{ minWidth: chequeInst ? '820px' : '1020px' }}>
              <thead>
                <tr className={`border-b ${th.thCell} text-left`}>
                  {/* No Source column — colour on instrument cell */}
                  <th className={`sticky left-0 z-10 px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold ${isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'} border-r w-40`}>Instrument</th>
                  {!isInward && <th className="px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-36">Drawee Bank</th>}
                  {isInward  && <th className="px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-24">Account</th>}
                  {isInward  && <th className="px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-14 text-right">IET</th>}
                  {OCR_COLS.map(col => (
                    <th key={col.key} className={`px-2 py-2.5 text-[10px] uppercase tracking-wider font-semibold ${col.w}`}>{col.label}</th>
                  ))}
                  <th className="px-2 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-8 text-center">🖼</th>
                  <th className="px-3 py-2.5 text-[10px] uppercase tracking-wider font-semibold w-20 text-center">Actions</th>
                </tr>
              </thead>
              <tbody>
                {filtered.length === 0 && (
                  <tr><td colSpan={20} className={`text-center py-12 ${th.lbl}`}>No instruments in validation queue.</td></tr>
                )}
                {filtered.map(inst => {
                  const manualCount = Object.values(inst.fields_meta).filter(m => m.source === 'MANUAL').length
                  const isSTP       = inst.source_stage === 'STP'
                  const minsLeft    = inst.iet_deadline ? Math.max(0, Math.round((new Date(inst.iet_deadline) - Date.now()) / 60000)) : null
                  const ietUrgent   = minsLeft != null && minsLeft < 45
                  const isViewing   = chequeViewId === inst.instrument_id
                  const isReturning = returnOpenFor === inst.instrument_id

                  return (
                    <tr key={inst.instrument_id} className={`border-b transition-colors ${th.rowBase} ${isViewing ? (isDark ? 'bg-amber-400/4' : 'bg-amber-50/60') : ''}`}>

                      {/* Instrument — left border = source colour */}
                      <td className={`sticky left-0 z-10 border-r ${sourceBar(inst.source_stage)} ${isDark ? 'bg-navy-900 border-r-white/8' : 'bg-white border-r-slate-200'} ${isViewing ? (isDark ? '!bg-amber-400/8' : '!bg-amber-50') : ''} px-3 py-2`}>
                        <div className={`font-mono text-[11px] font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{inst.instrument_id}</div>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <span className={`text-[9px] font-bold px-1 py-0.5 rounded text-[9px] ${sourceDot(inst.source_stage)}`}>{isSTP ? 'STP' : 'VERIFIED'}</span>
                          {manualCount > 0 && <span className={`text-[9px] ${isDark ? 'text-amber-400/70' : 'text-amber-600/70'}`}>{manualCount} MANUAL</span>}
                        </div>
                      </td>

                      {/* Bank / Account */}
                      {!isInward && (
                        <td className={`px-3 py-2 text-[11px] ${th.muted} truncate max-w-[144px]`}>
                          <div className="truncate">{inst.drawee_bank}</div>
                          <div className={`text-[9px] ${th.lbl} truncate`}>{inst.drawee_branch}</div>
                        </td>
                      )}
                      {isInward && <td className={`px-3 py-2 font-mono text-[11px] ${th.muted}`}>{inst.account_display}</td>}

                      {/* IET */}
                      {isInward && (
                        <td className="px-2 py-2 text-right">
                          <span className={`text-[11px] font-mono font-semibold ${ietUrgent ? 'text-red-400 animate-pulse' : isDark ? 'text-sky-400' : 'text-sky-600'}`}>{minsLeft}m</span>
                        </td>
                      )}

                      {/* Editable OCR fields */}
                      {OCR_COLS.map(col => {
                        const fm = inst.fields_meta[col.key] ?? { actual_value: '', source: 'STP' }
                        return (
                          <td key={col.key} className={`px-1.5 py-1.5 ${col.w}`}>
                            <div className="flex flex-col gap-0.5">
                              <EditCell value={fm.actual_value} onChange={v => handleEdit(inst.instrument_id, col.key, v)}
                                isDark={isDark} isManual={fm.source === 'MANUAL'} isBoolean={col.isBoolean}
                              />
                              <SBadge source={fm.source} isDark={isDark} />
                            </div>
                          </td>
                        )
                      })}

                      {/* Cheque view toggle */}
                      <td className="px-2 py-2 text-center">
                        <button type="button"
                          onClick={() => setChequeViewId(isViewing ? null : inst.instrument_id)}
                          title="View cheque image"
                          className={`w-7 h-7 rounded-lg flex items-center justify-center mx-auto text-sm transition-all ${isViewing
                            ? (isDark ? 'bg-amber-400/15 text-amber-300' : 'bg-amber-100 text-amber-600')
                            : (isDark ? 'text-slate-500 hover:bg-white/5 hover:text-amber-400' : 'text-slate-400 hover:bg-slate-100 hover:text-amber-600')
                          }`}
                        >🖼</button>
                      </td>

                      {/* Actions — icon buttons only */}
                      <td className="px-2 py-2">
                        <div className="flex items-center gap-2 justify-center relative">
                          {/* Approve icon */}
                          <button
                            type="button"
                            onClick={() => handleApprove(inst.instrument_id)}
                            title={`Approve → ${approveLabel}`}
                            className={`w-8 h-8 rounded-lg flex items-center justify-center text-base font-bold transition-all ${isDark
                              ? 'bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/25'
                              : 'bg-emerald-50 border border-emerald-400 text-emerald-600 hover:bg-emerald-100'
                            }`}
                          >✓</button>

                          {/* Return icon — opens reason dropdown */}
                          <div className="relative">
                            <button
                              type="button"
                              onClick={() => setReturnOpenFor(isReturning ? null : inst.instrument_id)}
                              title="Return — select reason"
                              className={`w-8 h-8 rounded-lg flex items-center justify-center text-base font-bold transition-all ${isReturning
                                ? (isDark ? 'bg-red-500/25 border border-red-500/50 text-red-300' : 'bg-red-100 border border-red-400 text-red-700')
                                : (isDark ? 'bg-red-500/10 border border-red-500/25 text-red-400 hover:bg-red-500/20' : 'bg-red-50 border border-red-300 text-red-600 hover:bg-red-100')
                              }`}
                            >↩</button>

                            {isReturning && (
                              <ReturnDropdown
                                isDark={isDark}
                                onReturn={() => doReturn(inst.instrument_id)}
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

          {/* Cheque image slide-in */}
          {chequeInst && (
            <ChequePanel inst={chequeInst} isDark={isDark} onClose={() => setChequeViewId(null)} />
          )}
        </div>

        {/* Footer */}
        {instruments.length > 0 && (
          <div className={`px-6 py-2.5 border-t ${th.divider} flex items-center gap-4 shrink-0`}>
            <span className={`text-[11px] ${th.lbl}`}>{filtered.length} of {instruments.length} shown</span>
            {editedCount > 0 && <span className={`text-[11px] ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{editedCount} with manual edits</span>}
            <div className="ml-auto flex items-center gap-2">
              <span className={`text-[11px] ${th.lbl}`}>Approved →</span>
              <span className={`text-[11px] font-semibold ${isDark ? 'text-emerald-400' : 'text-emerald-700'}`}>{approveLabel}</span>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
