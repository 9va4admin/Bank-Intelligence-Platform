import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'

// ── Sub-member ledger mock data ───────────────────────────────────────────────
const SMB_LEDGERS = [
  {
    sub_member_id: 'SMB-MH-001',
    bank_name: 'Vasavi Co-op Bank',
    sponsor_bank_id: 'SVCB-DIRECT-001',
    total_received: 42,
    stp_pass: 28,
    stp_return: 12,
    eyeball: 2,
    fraud_hold: 0,
    iet_emergency: 0,
    return_rate_pct: 28.6,
    return_rate_threshold_pct: 15.0,
    soft_hold_threshold_pct: 25.0,
    shield_status: 'SOFT_HOLD',
    tier1_sent: 12,
    tier2_sent: false,
    soft_hold_active: true,
  },
  {
    sub_member_id: 'SMB-MH-002',
    bank_name: 'Andheri Urban Co-op Bank',
    sponsor_bank_id: 'SVCB-DIRECT-001',
    total_received: 31,
    stp_pass: 27,
    stp_return: 4,
    eyeball: 0,
    fraud_hold: 0,
    iet_emergency: 0,
    return_rate_pct: 12.9,
    return_rate_threshold_pct: 15.0,
    soft_hold_threshold_pct: 25.0,
    shield_status: 'SAFE',
    tier1_sent: 4,
    tier2_sent: false,
    soft_hold_active: false,
  },
]

const SHIELD_D = {
  SAFE:      'text-emerald-300 bg-emerald-900/30 border-emerald-700/40',
  SOFT_HOLD: 'text-amber-300 bg-amber-900/30 border-amber-700/40',
  HARD_STOP: 'text-red-300 bg-red-900/30 border-red-700/40',
}
const SHIELD_L = {
  SAFE:      'text-emerald-700 bg-emerald-50 border-emerald-300',
  SOFT_HOLD: 'text-amber-700 bg-amber-50 border-amber-300',
  HARD_STOP: 'text-red-700 bg-red-50 border-red-300',
}

function buildSmbCsv(ledger) {
  return [
    '# ASTRA CTS — Sub-Member Batch Return Summary',
    `# Bank: ${ledger.bank_name}`,
    `# Sub-Member ID: ${ledger.sub_member_id}`,
    `# Note: Amounts shown as range buckets only per RBI data handling guidelines`,
    '#',
    'Bucket,Count',
    `STP_PASS,${ledger.stp_pass}`,
    `STP_RETURN,${ledger.stp_return}`,
    `EYEBALL,${ledger.eyeball}`,
    `FRAUD_HOLD,${ledger.fraud_hold}`,
    `IET_EMERGENCY,${ledger.iet_emergency}`,
    '#',
    `# Total Received: ${ledger.total_received}`,
    `# Return Rate: ${ledger.return_rate_pct.toFixed(2)}%`,
    `# Shield Status: ${ledger.shield_status}`,
  ].join('\n')
}

// ── Mock data ────────────────────────────────────────────────────────────────
const SESSIONS = [
  { id: 'SES-0619-001', date: '2026-06-19', label: 'Jun 19 — Session 1' },
  { id: 'SES-0618-001', date: '2026-06-18', label: 'Jun 18 — Session 1' },
  { id: 'SES-0617-001', date: '2026-06-17', label: 'Jun 17 — Session 1' },
]

const RECON_DATA = {
  'SES-0619-001': [
    { id: 'CHQ-IN-00001', cheque: '100001', suffix: '4521', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00002', cheque: '100002', suffix: '7832', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[1L-5L]', cbs_amt: '₹[1L-5L]', status: 'MATCHED' },
    { id: 'CHQ-IN-00003', cheque: '100003', suffix: '2291', ngch: 'RETURNED',  cbs: 'REVERSED', ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00004', cheque: '100004', suffix: '6610', ngch: 'CONFIRMED', cbs: 'PENDING',  ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'PENDING' },
    { id: 'CHQ-IN-00005', cheque: '100005', suffix: '3347', ngch: 'CONFIRMED', cbs: 'PENDING',  ngch_amt: '₹[1L-5L]', cbs_amt: '₹[1L-5L]', status: 'PENDING' },
    { id: 'CHQ-IN-00006', cheque: '100006', suffix: '9901', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[<1L]',   cbs_amt: '₹[1L-5L]', status: 'AMOUNT_MISMATCH' },
    { id: 'CHQ-IN-00007', cheque: '100007', suffix: '1123', ngch: 'CONFIRMED', cbs: '',         ngch_amt: '₹[<1L]',   cbs_amt: '',          status: 'NGCH_ONLY' },
    { id: 'CHQ-IN-00008', cheque: '100008', suffix: '5580', ngch: '',          cbs: 'POSTED',   ngch_amt: '',          cbs_amt: '₹[<1L]',   status: 'CBS_ONLY' },
    { id: 'CHQ-IN-00009', cheque: '100009', suffix: '7744', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00010', cheque: '100010', suffix: '2256', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[1L-5L]', cbs_amt: '₹[1L-5L]', status: 'MATCHED' },
    { id: 'CHQ-IN-00011', cheque: '100011', suffix: '8832', ngch: 'CONFIRMED', cbs: 'POSTED',   ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00012', cheque: '100012', suffix: '4419', ngch: 'RETURNED',  cbs: 'REVERSED', ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
  ],
  'SES-0618-001': [
    { id: 'CHQ-IN-00501', cheque: '200001', suffix: '1122', ngch: 'CONFIRMED', cbs: 'POSTED',  ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00502', cheque: '200002', suffix: '3344', ngch: 'CONFIRMED', cbs: 'POSTED',  ngch_amt: '₹[<1L]',   cbs_amt: '₹[<1L]',   status: 'MATCHED' },
    { id: 'CHQ-IN-00503', cheque: '200003', suffix: '5566', ngch: 'CONFIRMED', cbs: 'PENDING', ngch_amt: '₹[1L-5L]', cbs_amt: '₹[1L-5L]', status: 'PENDING' },
  ],
  'SES-0617-001': [
    { id: 'CHQ-IN-00701', cheque: '300001', suffix: '9988', ngch: 'CONFIRMED', cbs: 'POSTED', ngch_amt: '₹[<1L]', cbs_amt: '₹[<1L]', status: 'MATCHED' },
    { id: 'CHQ-IN-00702', cheque: '300002', suffix: '7766', ngch: 'RETURNED',  cbs: 'REVERSED', ngch_amt: '₹[<1L]', cbs_amt: '₹[<1L]', status: 'MATCHED' },
  ],
}

const STATUS_META = {
  MATCHED:         { label: 'Matched',        icon: '✓' },
  PENDING:         { label: 'Pending',        icon: '⏳' },
  AMOUNT_MISMATCH: { label: 'Amt Mismatch',   icon: '≠' },
  NGCH_ONLY:       { label: 'NGCH Only',      icon: '!' },
  CBS_ONLY:        { label: 'CBS Only',       icon: '!' },
}

function buildCsv(items, session) {
  const header = [
    'InstrumentID', 'ChequeNumber', 'AccountSuffix',
    'NGCHStatus', 'CBSStatus', 'NGCHAmountRange', 'CBSAmountRange',
    'ReconciliationStatus',
  ].join(',')
  const rows = items.map(i =>
    [i.id, i.cheque, `****${i.suffix}`, i.ngch, i.cbs, i.ngch_amt, i.cbs_amt, i.status].join(',')
  )
  const matched   = items.filter(i => i.status === 'MATCHED').length
  const unmatched = items.filter(i => !['MATCHED','PENDING'].includes(i.status)).length
  const pending   = items.filter(i => i.status === 'PENDING').length
  const rate      = items.length ? ((matched / items.length) * 100).toFixed(1) : '0.0'
  const summary = [
    `# ASTRA CTS Reconciliation Report`,
    `# Session: ${session.id}  Date: ${session.date}`,
    `# Total: ${items.length}  Matched: ${matched}  Unmatched: ${unmatched}  Pending: ${pending}  Match Rate: ${rate}%`,
    '#',
  ].join('\n')
  return summary + '\n' + header + '\n' + rows.join('\n')
}

function downloadCsv(csv, filename) {
  const blob = new Blob([csv], { type: 'text/csv' })
  const url  = URL.createObjectURL(blob)
  const a    = document.createElement('a')
  a.href     = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

// ── Component ────────────────────────────────────────────────────────────────
export default function CTSReconciliation() {
  const { isDark } = useTheme()
  const [sessionIdx, setSessionIdx] = useState(0)
  const [filterStatus, setFilterStatus] = useState('ALL')

  const session = SESSIONS[sessionIdx]
  const items   = RECON_DATA[session.id] || []

  const matched   = items.filter(i => i.status === 'MATCHED').length
  const pending   = items.filter(i => i.status === 'PENDING').length
  const unmatched = items.filter(i => !['MATCHED','PENDING'].includes(i.status)).length
  const matchRate = items.length ? ((matched / items.length) * 100).toFixed(1) : '0.0'

  const visible = filterStatus === 'ALL' ? items : items.filter(i => i.status === filterStatus)

  const th = {
    page:    isDark ? 'bg-transparent'                        : 'bg-slate-50',
    card:    isDark ? 'bg-white/4 border-white/8'         : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                         : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                     : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                     : 'text-slate-500',
    faint:   isDark ? 'text-slate-600'                     : 'text-slate-400',
    divider: isDark ? 'border-white/8'                     : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2'    : 'border-slate-100 hover:bg-slate-50',
    select:  isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    mono:    isDark ? 'text-slate-300 font-mono text-xs'   : 'text-slate-600 font-mono text-xs',
  }

  const ST_D = {
    MATCHED:         'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
    PENDING:         'bg-amber-900/40   text-amber-300   border-amber-700/40',
    AMOUNT_MISMATCH: 'bg-orange-900/40  text-orange-300  border-orange-700/40',
    NGCH_ONLY:       'bg-red-900/40     text-red-300     border-red-700/40',
    CBS_ONLY:        'bg-purple-900/40  text-purple-300  border-purple-700/40',
  }
  const ST_L = {
    MATCHED:         'bg-emerald-50  text-emerald-700 border-emerald-200',
    PENDING:         'bg-amber-50    text-amber-700   border-amber-200',
    AMOUNT_MISMATCH: 'bg-orange-50   text-orange-700  border-orange-200',
    NGCH_ONLY:       'bg-red-50      text-red-700     border-red-200',
    CBS_ONLY:        'bg-purple-50   text-purple-700  border-purple-200',
  }
  const ST = isDark ? ST_D : ST_L

  function handleDownload() {
    const csv  = buildCsv(items, session)
    const date = session.date.replace(/-/g, '')
    downloadCsv(csv, `RECON_SVCB0000001_${date}_${session.id}.csv`)
  }

  usePageHeader({
    subtitle: session.label,
    actions: (
      <div className="flex items-center gap-3">
        <select
          value={sessionIdx}
          onChange={e => { setSessionIdx(Number(e.target.value)); setFilterStatus('ALL') }}
          className={`text-xs border rounded-lg px-3 py-1.5 ${th.select}`}
        >
          {SESSIONS.map((s, i) => (
            <option key={s.id} value={i}>{s.label}</option>
          ))}
        </select>
        <button
          onClick={handleDownload}
          className="flex items-center gap-2 text-xs bg-violet-600 hover:bg-violet-500 text-white rounded-lg px-3 py-1.5"
        >
          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          Download CSV
        </button>
      </div>
    ),
  })

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* KPI Strip */}
        <div className="grid grid-cols-5 gap-3 mb-6">
          {[
            { label: 'Total Items',  value: items.length,  color: th.heading },
            { label: 'Matched',      value: matched,       color: 'text-emerald-500' },
            { label: 'Match Rate',   value: `${matchRate}%`, color: matched === items.length ? 'text-emerald-500' : 'text-amber-500' },
            { label: 'Pending',      value: pending,       color: 'text-amber-500' },
            { label: 'Unmatched',    value: unmatched,     color: unmatched > 0 ? 'text-red-400' : 'text-emerald-500' },
          ].map(k => (
            <div key={k.label} className={`border rounded-xl px-4 py-3 ${th.card}`}>
              <div className={`text-[10px] ${th.faint} mb-1`}>{k.label}</div>
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
            </div>
          ))}
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 mb-4">
          <span className={`text-xs ${th.muted}`}>Filter:</span>
          {['ALL', 'MATCHED', 'PENDING', 'AMOUNT_MISMATCH', 'NGCH_ONLY', 'CBS_ONLY'].map(s => (
            <button
              key={s}
              onClick={() => setFilterStatus(s)}
              className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                filterStatus === s
                  ? 'bg-violet-600 text-white border-violet-600'
                  : isDark
                    ? 'border-white/10 text-slate-400 hover:text-white'
                    : 'border-slate-200 text-slate-500 hover:text-slate-900'
              }`}
            >
              {s === 'ALL' ? 'All' : (STATUS_META[s]?.label || s)}
            </button>
          ))}
        </div>

        {/* Table */}
        <div className={`border rounded-xl overflow-hidden ${th.card}`}>
          {/* Table header */}
          <div className={`grid grid-cols-12 gap-2 px-4 py-2 border-b ${th.divider} text-[10px] ${th.faint} font-medium uppercase tracking-wider`}>
            <div className="col-span-3">Instrument ID</div>
            <div className="col-span-1">Cheque #</div>
            <div className="col-span-2">Account</div>
            <div className="col-span-1">NGCH</div>
            <div className="col-span-1">CBS</div>
            <div className="col-span-2">Amount Range</div>
            <div className="col-span-2">Status</div>
          </div>

          {visible.length === 0 && (
            <div className={`px-4 py-8 text-center text-sm ${th.muted}`}>No items for this filter.</div>
          )}

          {visible.map(item => (
            <div
              key={item.id}
              className={`grid grid-cols-12 gap-2 px-4 py-3 border-b ${th.row} transition-colors`}
            >
              <div className={`col-span-3 ${th.mono}`}>{item.id}</div>
              <div className={`col-span-1 text-xs ${th.body}`}>{item.cheque}</div>
              <div className={`col-span-2 ${th.mono}`}>****{item.suffix}</div>

              {/* NGCH status */}
              <div className="col-span-1">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                  item.ngch === 'CONFIRMED' ? (isDark ? 'text-emerald-400' : 'text-emerald-700') :
                  item.ngch === 'RETURNED'  ? (isDark ? 'text-red-400'     : 'text-red-700')     :
                  item.ngch === 'FILED'     ? (isDark ? 'text-amber-400'   : 'text-amber-700')   :
                  th.faint
                }`}>{item.ngch || '—'}</span>
              </div>

              {/* CBS status */}
              <div className="col-span-1">
                <span className={`text-[10px] font-medium ${
                  item.cbs === 'POSTED'   ? (isDark ? 'text-emerald-400' : 'text-emerald-700') :
                  item.cbs === 'REVERSED' ? (isDark ? 'text-red-400'     : 'text-red-700')     :
                  item.cbs === 'PENDING'  ? (isDark ? 'text-amber-400'   : 'text-amber-700')   :
                  th.faint
                }`}>{item.cbs || '—'}</span>
              </div>

              {/* Amount ranges */}
              <div className="col-span-2">
                <div className={`text-[10px] ${th.muted}`}>
                  {item.ngch_amt || '—'}
                  {item.ngch_amt && item.cbs_amt && item.ngch_amt !== item.cbs_amt && (
                    <span className="text-orange-400 ml-1">≠ {item.cbs_amt}</span>
                  )}
                </div>
              </div>

              {/* Reconciliation status badge */}
              <div className="col-span-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${ST[item.status] || ''}`}>
                  {STATUS_META[item.status]?.icon} {STATUS_META[item.status]?.label || item.status}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className={`mt-4 border rounded-xl p-4 ${th.card}`}>
          <div className={`text-xs font-medium ${th.heading} mb-3`}>Status Reference</div>
          <div className="grid grid-cols-5 gap-3">
            {Object.entries(STATUS_META).map(([key, meta]) => (
              <div key={key} className="flex items-start gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-medium mt-0.5 ${ST[key]}`}>
                  {meta.icon} {meta.label}
                </span>
              </div>
            ))}
          </div>
          <div className={`mt-3 text-[10px] ${th.faint} space-y-0.5`}>
            <div><strong className={th.muted}>Matched</strong> — NGCH confirmed + CBS posted, amounts agree</div>
            <div><strong className={th.muted}>Pending</strong> — Filed to NGCH, CBS settlement in progress</div>
            <div><strong className={th.muted}>Amt Mismatch</strong> — Both records present but amount ranges differ</div>
            <div><strong className={th.muted}>NGCH Only</strong> — Filed to NGCH, no corresponding CBS posting found</div>
            <div><strong className={th.muted}>CBS Only</strong> — CBS posting found, no corresponding NGCH record</div>
          </div>
        </div>

        {/* Sub-Member Ledger Section */}
        <div className="mt-6">
          <div className={`flex items-center justify-between mb-3`}>
            <div>
              <h2 className={`text-sm font-semibold ${th.heading}`}>Sub-Member Ledger</h2>
              <p className={`text-[11px] ${th.muted} mt-0.5`}>Per-session clearing breakdown for sub-member banks routed through this sponsor</p>
            </div>
          </div>

          <div className="space-y-3">
            {SMB_LEDGERS.map(smb => {
              const SHIELD = isDark ? SHIELD_D : SHIELD_L
              const shieldCls = SHIELD[smb.shield_status] || SHIELD.SAFE
              const returnBarPct = Math.min(100, (smb.return_rate_pct / smb.return_rate_threshold_pct) * 100)
              const barColor = smb.shield_status === 'HARD_STOP' ? 'bg-red-400' : smb.shield_status === 'SOFT_HOLD' ? 'bg-amber-400' : 'bg-emerald-400'

              return (
                <div key={smb.sub_member_id} className={`border rounded-xl p-4 ${th.card} ${smb.soft_hold_active ? (isDark ? 'border-amber-400/30' : 'border-amber-300') : ''}`}>
                  {/* Row 1: Name + shield + CSV */}
                  <div className="flex items-start justify-between gap-3 mb-3">
                    <div>
                      <div className={`text-sm font-semibold ${th.heading}`}>{smb.bank_name}</div>
                      <div className={`text-[10px] font-mono ${th.faint} mt-0.5`}>{smb.sub_member_id} · {smb.sponsor_bank_id}</div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className={`text-[10px] font-semibold px-2.5 py-1 rounded-full border ${shieldCls}`}>
                        {smb.shield_status === 'SAFE' ? '✓ SAFE' : smb.shield_status === 'SOFT_HOLD' ? '⚠ SOFT HOLD' : '✕ HARD STOP'}
                      </span>
                      <button
                        onClick={() => downloadCsv(buildSmbCsv(smb), `SMB_${smb.sub_member_id}_${session.date.replace(/-/g,'')}.csv`)}
                        className={`text-[10px] px-2.5 py-1 rounded-lg border flex items-center gap-1 transition-colors ${isDark ? 'border-white/10 text-slate-400 hover:text-white hover:border-white/20' : 'border-slate-200 text-slate-500 hover:text-slate-800'}`}
                      >
                        <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                        </svg>
                        CSV
                      </button>
                    </div>
                  </div>

                  {/* Row 2: Bucket grid */}
                  <div className="grid grid-cols-6 gap-2 mb-3">
                    {[
                      { label: 'Total',    value: smb.total_received, color: th.heading },
                      { label: 'STP Pass', value: smb.stp_pass,       color: 'text-emerald-500' },
                      { label: 'Return',   value: smb.stp_return,     color: 'text-red-400' },
                      { label: 'Eyeball',  value: smb.eyeball,        color: 'text-amber-400' },
                      { label: 'Fraud Hld',value: smb.fraud_hold,     color: 'text-orange-400' },
                      { label: 'IET Emrg', value: smb.iet_emergency,  color: smb.iet_emergency > 0 ? 'text-red-400' : th.faint },
                    ].map(b => (
                      <div key={b.label} className={`rounded-lg px-3 py-2 ${isDark ? 'bg-white/3' : 'bg-slate-50'}`}>
                        <div className={`text-[9px] ${th.faint} mb-1`}>{b.label}</div>
                        <div className={`text-lg font-bold ${b.color}`}>{b.value}</div>
                      </div>
                    ))}
                  </div>

                  {/* Row 3: Return rate bar + notification status */}
                  <div className="flex items-center gap-4">
                    <div className="flex-1">
                      <div className="flex items-center justify-between mb-1">
                        <span className={`text-[10px] ${th.faint}`}>Return rate</span>
                        <span className={`text-[10px] font-semibold ${smb.shield_status !== 'SAFE' ? (isDark ? 'text-amber-300' : 'text-amber-700') : (isDark ? 'text-emerald-400' : 'text-emerald-700')}`}>
                          {smb.return_rate_pct.toFixed(1)}% / {smb.return_rate_threshold_pct.toFixed(1)}% threshold
                        </span>
                      </div>
                      <div className={`h-1.5 rounded-full ${isDark ? 'bg-white/5' : 'bg-slate-100'}`}>
                        <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(returnBarPct, 100)}%` }} />
                      </div>
                    </div>
                    <div className="flex items-center gap-3 shrink-0">
                      <div className={`text-[10px] ${th.faint}`}>
                        Tier 1 notif:
                        <span className={`ml-1 font-semibold ${isDark ? 'text-sky-400' : 'text-sky-600'}`}>{smb.tier1_sent} sent</span>
                      </div>
                      <div className={`text-[10px] ${th.faint}`}>
                        Tier 2 batch:
                        <span className={`ml-1 font-semibold ${smb.tier2_sent ? (isDark ? 'text-emerald-400' : 'text-emerald-700') : (isDark ? 'text-slate-500' : 'text-slate-400')}`}>
                          {smb.tier2_sent ? 'sent' : 'pending (session active)'}
                        </span>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

      </div>
    </AppShell>
  )
}
