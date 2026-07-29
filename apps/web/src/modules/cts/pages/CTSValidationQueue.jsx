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
import ChequeImageViewer from '../components/ChequeImageViewer'
import { demoChequeUrl } from '../demoImages'

// ── Mock data ─────────────────────────────────────────────────────────────────

function makeMeta(val, conf, by = 'GOT-OCR2.0') {
  return { extracted_value: val, extracted_confidence: conf, extracted_by: by, actual_value: val, source: conf >= 0.90 ? 'STP' : 'MANUAL' }
}

const BASE_INSTRUMENTS_OUTWARD = [
  {
    instrument_id: 'CHQ-OUT-V001', source_stage: 'STP', front_bw_url: null, front_gray_url: null, drawee_bank: 'State Bank of India', drawee_branch: 'Andheri East',
    drawee_ifsc: 'SBIN0000300', drawee_micr: '400002003',
    drawer_name: 'Krishnamurthy P. Iyer', account_display: '31994023456',
    deposit_channel: 'PAY_IN_SLIP',
    deposit_data: { depositor_name: 'Rajesh Kumar Verma', depositor_account: '4000401001', deposit_amount: '₹12,50,000', counter_token: 'T-0001', date: '15/07/2026', branch: 'Andheri East' },
    name_match: 'FULL_MATCH', name_match_cbs_name: 'Rajesh Kumar Verma',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.99), payee: makeMeta('Rajesh Kumar Verma', 0.97),
      amount_figures: makeMeta('₹12,50,000', 0.98), amount_words: makeMeta('Twelve Lakh Fifty Thousand Only', 0.95),
      micr: makeMeta('400002123', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V002', source_stage: 'VERIFIED', front_bw_url: null, front_gray_url: null, drawee_bank: 'HDFC Bank', drawee_branch: 'Bandra West',
    drawee_ifsc: 'HDFC0000060', drawee_micr: '400240060',
    drawer_name: 'Anand R. Mehta', account_display: '50100042378901',
    deposit_channel: 'BACK_ANNOTATION',
    deposit_data: { extracted_account: '4000512347', extracted_mobile: '9876543210', ocr_confidence: 0.82 },
    name_match: 'PARTIAL_MATCH', name_match_cbs_name: 'Sunita Joshi',
    fields_meta: {
      date: makeMeta('14/07/2026', 0.97), payee: makeMeta('Sunita P. Joshi', 0.74),
      amount_figures: makeMeta('₹2,40,000', 0.91), amount_words: makeMeta('Two Lakh Forty Thousand Only', 0.88),
      micr: makeMeta('400001234', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V003', source_stage: 'STP', front_bw_url: null, front_gray_url: null, drawee_bank: 'ICICI Bank', drawee_branch: 'Powai',
    drawee_ifsc: 'ICIC0000001', drawee_micr: '400229001',
    drawer_name: 'Pradeep S. Nair', account_display: '022601510783',
    deposit_channel: 'KIOSK',
    deposit_data: { name: 'Amol Vilas Kulkarni', account: '4000623003', txn_id: 'CDM-003-20260716', timestamp: '09:30 AM  16/07/2026' },
    name_match: 'FULL_MATCH', name_match_cbs_name: 'Amol Vilas Kulkarni',
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Amol Vilas Kulkarni', 0.96),
      amount_figures: makeMeta('₹75,000', 0.95), amount_words: makeMeta('Seventy Five Thousand Only', 0.93),
      micr: makeMeta('400004567', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V004', source_stage: 'VERIFIED', front_bw_url: null, front_gray_url: null, drawee_bank: 'Bank of Baroda', drawee_branch: 'Fort',
    drawee_ifsc: 'BARB0CHURCH', drawee_micr: '400012009',
    drawer_name: 'Ramesh D. Shah', account_display: '05520010078341',
    deposit_channel: 'PAY_IN_SLIP',
    deposit_data: { depositor_name: 'Kavita R. Desai', depositor_account: '4000734004', deposit_amount: '₹3,80,500', counter_token: 'T-0004', date: '15/07/2026', branch: 'Fort' },
    name_match: 'NO_MATCH', name_match_cbs_name: 'Vikram S. Patil',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.98), payee: makeMeta('Kavita R. Desai', 0.85),
      amount_figures: makeMeta('₹3,80,500', 0.87), amount_words: makeMeta('Three Lakh Eighty Thousand Five Hundred Only', 0.82),
      micr: makeMeta('400008901', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    instrument_id: 'CHQ-OUT-V005', source_stage: 'STP', front_bw_url: null, front_gray_url: null, drawee_bank: 'Axis Bank', drawee_branch: 'Goregaon',
    drawee_ifsc: 'UTIB0000067', drawee_micr: '400211067',
    drawer_name: 'Suresh V. Rao', account_display: '914010019234781',
    deposit_channel: 'BACK_ANNOTATION',
    deposit_data: { extracted_account: '4000845005', extracted_mobile: '9123456780', ocr_confidence: 0.94 },
    name_match: 'ACCOUNT_NOT_FOUND', name_match_cbs_name: null,
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Nikhil Santosh Pawar', 0.99),
      amount_figures: makeMeta('₹1,25,50,000', 0.99), amount_words: makeMeta('One Crore Twenty Five Lakh Fifty Thousand Only', 0.98),
      micr: makeMeta('400002345', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

const BASE_INSTRUMENTS_INWARD = [
  {
    // Payer (drawer): Suresh B. Patkar — Saraswat customer; Payee: Ramesh N. Rao — received at presenting bank
    instrument_id: 'CHQ-IN-V001', source_stage: 'STP', front_bw_url: null, front_gray_url: null,
    account_display: '00000000004521', iet_deadline: new Date(Date.now() + 72 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Dadar',
    drawer_name: 'Suresh B. Patkar',
    name_match: 'FULL_MATCH', name_match_cbs_name: 'Suresh B. Patkar',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.99), payee: makeMeta('Ramesh N. Rao', 0.97),
      amount_figures: makeMeta('₹45,000', 0.98), amount_words: makeMeta('Forty Five Thousand Only', 0.95),
      micr: makeMeta('400005678', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    // Payer (drawer): Prakash V. Rane — Saraswat customer; Payee: Meena S. Sharma
    instrument_id: 'CHQ-IN-V002', source_stage: 'VERIFIED', front_bw_url: null, front_gray_url: null,
    account_display: '00000000008912', iet_deadline: new Date(Date.now() + 28 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Vile Parle',
    drawer_name: 'Prakash V. Rane',
    name_match: 'PARTIAL_MATCH', name_match_cbs_name: 'Prakash Rane',
    fields_meta: {
      date: makeMeta('14/07/2026', 0.96), payee: makeMeta('Meena S. Sharma', 0.82),
      amount_figures: makeMeta('₹3,20,000', 0.88), amount_words: makeMeta('Three Lakh Twenty Thousand Only', 0.79),
      micr: makeMeta('400009012', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    // Payer (drawer): Anand M. Kulkarni — Saraswat customer; Payee: Priya R. Nair
    instrument_id: 'CHQ-IN-V003', source_stage: 'STP', front_bw_url: null, front_gray_url: null,
    account_display: '00000000002234', iet_deadline: new Date(Date.now() + 115 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Pune Main',
    drawer_name: 'Anand M. Kulkarni',
    name_match: 'FULL_MATCH', name_match_cbs_name: 'Anand M. Kulkarni',
    fields_meta: {
      date: makeMeta('16/07/2026', 0.99), payee: makeMeta('Priya R. Nair', 0.96),
      amount_figures: makeMeta('₹8,000', 0.97), amount_words: makeMeta('Eight Thousand Only', 0.94),
      micr: makeMeta('400003456', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
  {
    // Payer (drawer): Deepak R. Joshi — but CBS shows this account belongs to Ramesh T. Mehta — mismatch
    instrument_id: 'CHQ-IN-V004', source_stage: 'VERIFIED', front_bw_url: null, front_gray_url: null,
    account_display: '00000000006677', iet_deadline: new Date(Date.now() + 54 * 60000).toISOString(),
    drawee_bank: 'Saraswat Co-op Bank', drawee_branch: 'Borivali',
    drawer_name: 'Deepak R. Joshi',
    name_match: 'NO_MATCH', name_match_cbs_name: 'Ramesh T. Mehta',
    fields_meta: {
      date: makeMeta('15/07/2026', 0.98), payee: makeMeta('Suresh B. Agarwal', 0.86),
      amount_figures: makeMeta('₹1,10,000', 0.89), amount_words: makeMeta('One Lakh Ten Thousand Only', 0.84),
      micr: makeMeta('400007890', 0.99), alterations: { ...makeMeta(false, 0.99), source: 'STP' },
    },
  },
]

// ── Cheque slide-in panel ─────────────────────────────────────────────────────

function ChequePanel({ inst, isInward, isDark, onClose }) {
  const fm = inst.fields_meta ?? {}
  const fields = {
    payee:           fm.payee?.actual_value          ?? '',
    drawer_name:     inst.drawer_name,
    account_display: inst.account_display,
    date:            fm.date?.actual_value            ?? '',
    amount_figures:  fm.amount_figures?.actual_value  ?? '',
    amount_words:    fm.amount_words?.actual_value    ?? '',
    micr:            fm.micr?.actual_value            ?? '',
    alterations:     fm.alterations?.actual_value     ?? false,
    bank_name:       inst.drawee_bank                 ?? '',
    bank_branch:     inst.drawee_branch               ?? '',
    bank_ifsc:       inst.drawee_ifsc                 ?? '',
    bank_micr:       inst.drawee_micr                 ?? '',
    deposit_channel: !isInward ? inst.deposit_channel : undefined,
    deposit_data:    !isInward ? inst.deposit_data    : undefined,
  }
  return (
    <div className={`flex flex-col border-l h-full shrink-0 ${isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200'}`} style={{ width: '440px' }}>
      <div className={`flex items-center gap-2 px-4 py-3 border-b shrink-0 ${isDark ? 'border-white/10' : 'border-slate-200'}`}>
        <span className={`font-mono text-[11px] font-bold ${isDark ? 'text-amber-400' : 'text-amber-600'}`}>{inst.instrument_id}</span>
        <button type="button" onClick={onClose} className={`ml-auto text-lg leading-none ${isDark ? 'text-slate-500 hover:text-white' : 'text-slate-400 hover:text-slate-800'}`}>×</button>
      </div>
      <div className="flex-1 overflow-auto p-3">
        <NameMatchCard inst={inst} isInward={isInward} isDark={isDark} />
        <ChequeImageViewer
          views={[
            { key: 'BFB', label: 'BFB — Front Black', url: inst.front_bw_url   ?? null },
            { key: 'BBB', label: 'BBB — Back Black',  url: null },
            { key: 'BFG', label: 'BFG — Front Grey',  url: inst.front_gray_url ?? null },
          ]}
          fields={fields}
          isDark={isDark}
          compact={false}
          title={inst.instrument_id}
          depositInfo={!isInward && inst.deposit_channel ? { channel: inst.deposit_channel, data: inst.deposit_data } : null}
        />
      </div>
    </div>
  )
}

// ── Name-Account match verdict config ────────────────────────────────────────

const NAME_MATCH_CFG = {
  FULL_MATCH:        { label: 'Name Matched',       shortLabel: 'Matched',    icon: '✓', darkCls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30', lightCls: 'text-emerald-700 bg-emerald-50 border-emerald-400' },
  PARTIAL_MATCH:     { label: 'Partial Match',      shortLabel: 'Partial',    icon: '≈', darkCls: 'text-amber-400 bg-amber-500/10 border-amber-500/30',       lightCls: 'text-amber-700 bg-amber-50 border-amber-400'       },
  NO_MATCH:          { label: 'Name Mismatch',      shortLabel: 'Mismatch',   icon: '✗', darkCls: 'text-red-400 bg-red-500/10 border-red-500/30',             lightCls: 'text-red-700 bg-red-50 border-red-400'             },
  ACCOUNT_NOT_FOUND: { label: 'Account Not Found',  shortLabel: 'Acct N/F',   icon: '!', darkCls: 'text-red-400 bg-red-500/10 border-red-500/30',             lightCls: 'text-red-700 bg-red-50 border-red-400'             },
  CBS_UNAVAILABLE:   { label: 'CBS Unavailable',    shortLabel: 'CBS Down',   icon: '?', darkCls: 'text-slate-400 bg-slate-500/10 border-slate-500/30',        lightCls: 'text-slate-500 bg-slate-100 border-slate-300'      },
}

function isNameAlert(verdict) {
  return verdict === 'NO_MATCH' || verdict === 'ACCOUNT_NOT_FOUND'
}

function NameMatchBadge({ verdict, isDark, short = true }) {
  if (!verdict) return null
  const cfg = NAME_MATCH_CFG[verdict]
  if (!cfg) return null
  return (
    <span className={`inline-flex items-center gap-0.5 text-[9px] font-semibold px-1.5 py-0.5 rounded border whitespace-nowrap ${isDark ? cfg.darkCls : cfg.lightCls}`}>
      {cfg.icon} {short ? cfg.shortLabel : cfg.label}
    </span>
  )
}

// Shown inside ChequePanel — full comparison card
function NameMatchCard({ inst, isInward, isDark }) {
  if (!inst.name_match) return null
  // Outward: must have deposit_channel (credit account known); Inward: always show (account is on cheque)
  if (!isInward && !inst.deposit_channel) return null
  const cfg = NAME_MATCH_CFG[inst.name_match]
  if (!cfg) return null

  const alert = isNameAlert(inst.name_match)

  // Inward: verify PAYER (drawer) name against the drawee account
  // Outward: verify PAYEE name against the credit account from deposit channel
  const chequeName  = isInward
    ? (inst.drawer_name || '—')
    : (inst.fields_meta?.payee?.actual_value || '—')
  const cbsName     = inst.name_match_cbs_name || '—'
  const accountNo   = isInward
    ? inst.account_display          // full account from MICR / NPCI file — never masked
    : (() => { const dd = inst.deposit_data || {}; return dd.depositor_account || dd.extracted_account || dd.account || '—' })()
  const nameLabel   = isInward ? 'Drawer Name on Cheque' : 'Cheque Payee Name'
  const acctLabel   = isInward ? "Drawer's A/C (MICR / NPCI)" : 'Credit Account'
  const notePrefix  = isInward ? 'Drawer' : 'Payee'

  return (
    <div className={`mb-3 rounded-lg border p-3 ${alert
      ? (isDark ? 'bg-red-500/8 border-red-500/30' : 'bg-red-50 border-red-300')
      : inst.name_match === 'PARTIAL_MATCH'
        ? (isDark ? 'bg-amber-500/8 border-amber-500/30' : 'bg-amber-50 border-amber-300')
        : (isDark ? 'bg-emerald-500/5 border-emerald-500/20' : 'bg-emerald-50/60 border-emerald-300')
    }`}>
      <div className="flex items-center gap-2 mb-2.5">
        <span className={`text-[9px] font-semibold uppercase tracking-widest ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
          CBS {isInward ? 'Payer' : 'Payee'} Name Verification
        </span>
        <NameMatchBadge verdict={inst.name_match} isDark={isDark} short={false} />
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1.5">
        <div>
          <div className={`text-[9px] uppercase tracking-wide mb-0.5 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{nameLabel}</div>
          <div className={`text-[11px] font-semibold ${isDark ? 'text-slate-200' : 'text-slate-800'}`}>{chequeName}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wide mb-0.5 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>CBS Account Holder</div>
          <div className={`text-[11px] font-semibold ${alert ? (isDark ? 'text-red-400' : 'text-red-700') : inst.name_match === 'PARTIAL_MATCH' ? (isDark ? 'text-amber-400' : 'text-amber-700') : (isDark ? 'text-emerald-400' : 'text-emerald-700')}`}>{cbsName}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wide mb-0.5 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>{acctLabel}</div>
          <div className={`text-[11px] font-mono ${isDark ? 'text-slate-300' : 'text-slate-700'}`}>{accountNo}</div>
        </div>
        <div>
          <div className={`text-[9px] uppercase tracking-wide mb-0.5 ${isDark ? 'text-slate-500' : 'text-slate-400'}`}>Verified via</div>
          <div className={`text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-600'}`}>CBS Finacle API · real-time</div>
        </div>
      </div>
      {inst.name_match === 'PARTIAL_MATCH' && (
        <div className={`mt-2 text-[9px] px-2 py-1.5 rounded ${isDark ? 'bg-amber-400/10 text-amber-300' : 'bg-amber-100 text-amber-800'}`}>
          {notePrefix} name is similar but not identical to CBS record — verify before {isInward ? 'passing' : 'approval'}.
        </div>
      )}
      {inst.name_match === 'NO_MATCH' && (
        <div className={`mt-2 text-[9px] px-2 py-1.5 rounded ${isDark ? 'bg-red-400/10 text-red-300' : 'bg-red-100 text-red-800'}`}>
          {isInward
            ? 'Drawer name does not match CBS account holder — possible cheque theft or forged signature. Do not pass without investigation.'
            : 'Payee name does not match account holder — suspected wrong account or fraud. Do not approve without branch confirmation.'}
        </div>
      )}
      {inst.name_match === 'ACCOUNT_NOT_FOUND' && (
        <div className={`mt-2 text-[9px] px-2 py-1.5 rounded ${isDark ? 'bg-red-400/10 text-red-300' : 'bg-red-100 text-red-800'}`}>
          Account number does not exist in CBS — possible data entry error or fictitious account.
        </div>
      )}
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

// ── Helpers ───────────────────────────────────────────────────────────────────

// In production this value comes from bank config:
//   GET /v1/config/cts → { high_value_amount_threshold: <bank-specific> }
// Hardcoding is forbidden per CLAUDE.md — this mock constant is UI-only.
const MOCK_HV_THRESHOLD = 500000   // ₹5,00,000 default; real value = bank config

function parseAmtNum(amtStr) {
  return parseInt((amtStr || '').replace(/[₹,\s]/g, ''), 10) || 0
}
function isHighValue(inst, threshold = MOCK_HV_THRESHOLD) {
  return parseAmtNum(inst.fields_meta?.amount_figures?.actual_value) >= threshold
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
    if (filter === 'STP')        return i.source_stage === 'STP'
    if (filter === 'VERIFIED')   return i.source_stage === 'VERIFIED'
    if (filter === 'HIGH_VALUE') return isHighValue(i)
    if (filter === 'NAME_ALERT') return isNameAlert(i.name_match)
    return true
  })

  const stpCount        = instruments.filter(i => i.source_stage === 'STP').length
  const verifiedCount   = instruments.filter(i => i.source_stage === 'VERIFIED').length
  const editedCount     = instruments.filter(i => Object.keys(i.edits).length > 0).length
  const hvCount         = instruments.filter(i => isHighValue(i)).length
  const nameAlertCount  = instruments.filter(i => isNameAlert(i.name_match)).length
  const chequeInst      = chequeViewId ? instruments.find(i => i.instrument_id === chequeViewId) : null

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
              { label: 'High Value',     val: hvCount,            color: isDark ? 'text-red-400' : 'text-red-600' },
              { label: 'Name Alerts', val: nameAlertCount, color: nameAlertCount > 0 ? (isDark ? 'text-red-400' : 'text-red-600') : (isDark ? 'text-slate-500' : 'text-slate-400') },
            ].map(({ label, val, color }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className={`text-2xl font-bold font-mono ${color}`}>{val}</span>
                <span className={`text-[10px] ${th.lbl}`}>{label}</span>
              </div>
            ))}
            <div className="ml-auto flex items-center gap-1">
              {[
                ['ALL',        'All',         'default'],
                ['STP',        'STP',         'default'],
                ['VERIFIED',   'Verified',    'default'],
                ['HIGH_VALUE', `HV ≥₹${(MOCK_HV_THRESHOLD/100000).toFixed(0)}L`, 'red'],
                ['NAME_ALERT', `Name Alerts${nameAlertCount > 0 ? ` (${nameAlertCount})` : ''}`, 'red'],
              ].map(([val, lbl, type]) => (
                <button key={val} onClick={() => setFilter(val)}
                  className={`px-3 py-1 rounded-lg text-[11px] font-medium transition-all ${filter === val
                    ? type === 'red'
                      ? (isDark ? 'bg-red-500/20 text-red-300' : 'bg-red-600 text-white')
                      : (isDark ? 'bg-white/15 text-white' : 'bg-slate-800 text-white')
                    : type === 'red'
                      ? (isDark ? 'text-red-400/70 hover:bg-red-500/10' : 'text-red-600 hover:bg-red-50')
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
                        <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                          <span className={`text-[9px] font-bold px-1 py-0.5 rounded text-[9px] ${sourceDot(inst.source_stage)}`}>{isSTP ? 'STP' : 'VERIFIED'}</span>
                          {manualCount > 0 && <span className={`text-[9px] ${isDark ? 'text-amber-400/70' : 'text-amber-600/70'}`}>{manualCount} MANUAL</span>}
                          {inst.name_match && <NameMatchBadge verdict={inst.name_match} isDark={isDark} short />}
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
            <ChequePanel inst={chequeInst} isInward={isInward} isDark={isDark} onClose={() => setChequeViewId(null)} />
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
