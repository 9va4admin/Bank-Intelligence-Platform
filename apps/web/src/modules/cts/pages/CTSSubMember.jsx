import { useState } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'

const SUB_MEMBERS = [
  {
    id: 'SMB-MH-001',
    bank_name: 'Vasavi Co-op Bank',
    ifsc_prefix: 'VASB',
    micr_prefix: '400053',
    sponsor: 'Saraswat Co-op Bank (Direct)',
    session: 'MORNING 2026-06-19',
    total: 124,
    stp_pass: 105,
    stp_return: 14,
    eyeball: 4,
    fraud_hold: 1,
    iet_emergency: 0,
    soft_hold: false,
    bm_email: 'bm.andheri@vasavi.bank',
    return_threshold: 0.15,
    soft_hold_threshold: 0.25,
  },
  {
    id: 'SMB-MH-002',
    bank_name: 'Kalyan Janata Sahakari Bank',
    ifsc_prefix: 'KJSB',
    micr_prefix: '421301',
    sponsor: 'SBI (Direct)',
    session: 'MORNING 2026-06-19',
    total: 87,
    stp_pass: 64,
    stp_return: 18,
    eyeball: 4,
    fraud_hold: 1,
    iet_emergency: 0,
    soft_hold: true,
    bm_email: 'bm.kalyan@kjsb.bank',
    return_threshold: 0.15,
    soft_hold_threshold: 0.20,
  },
  {
    id: 'SMB-GJ-001',
    bank_name: 'Mehsana Urban Co-op Bank',
    ifsc_prefix: 'MUCB',
    micr_prefix: '384001',
    sponsor: 'Bank of Baroda (Direct)',
    session: 'MORNING 2026-06-19',
    total: 211,
    stp_pass: 198,
    stp_return: 9,
    eyeball: 3,
    fraud_hold: 1,
    iet_emergency: 0,
    soft_hold: false,
    bm_email: 'bm.mehsana@mucb.bank',
    return_threshold: 0.12,
    soft_hold_threshold: 0.22,
  },
  {
    id: 'SMB-DL-001',
    bank_name: 'Delhi Mercantile Co-op Bank',
    ifsc_prefix: 'DMCB',
    micr_prefix: '110083',
    sponsor: 'Punjab National Bank (Direct)',
    session: 'MORNING 2026-06-19',
    total: 63,
    stp_pass: 60,
    stp_return: 2,
    eyeball: 1,
    fraud_hold: 0,
    iet_emergency: 0,
    soft_hold: false,
    bm_email: 'bm.chandni@dmcb.bank',
    return_threshold: 0.15,
    soft_hold_threshold: 0.25,
  },
]

const RETURN_EVENTS = [
  { id: 'CHQ-IN-20260619-0042', smb: 'SMB-MH-001', reason: 'SIGNATURE_MISMATCH',  bucket: 'STP_RETURN',  amount: '₹[1L–5L]',    suffix: '7823', time: '09:14', tier: 1 },
  { id: 'CHQ-IN-20260619-0055', smb: 'SMB-MH-001', reason: 'AMOUNT_ALTERATION',   bucket: 'FRAUD_HOLD',  amount: '₹[10L–1Cr]',  suffix: '3341', time: '09:21', tier: 1 },
  { id: 'CHQ-IN-20260619-0071', smb: 'SMB-MH-002', reason: 'STALE_CHEQUE',        bucket: 'STP_RETURN',  amount: '₹[<1L]',       suffix: '0019', time: '09:35', tier: 1 },
  { id: 'CHQ-IN-20260619-0098', smb: 'SMB-MH-002', reason: 'PPS_MISMATCH',        bucket: 'EYEBALL',     amount: '₹[5L–10L]',    suffix: '4492', time: '09:42', tier: 2 },
  { id: 'CHQ-IN-20260619-0134', smb: 'SMB-MH-002', reason: 'DRAWEE_ACCOUNT_FROZEN', bucket: 'STP_RETURN', amount: '₹[1L–5L]',   suffix: '1127', time: '10:03', tier: 1 },
]

const BUCKET_COLORS = {
  STP_PASS:      { d: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40', l: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  STP_RETURN:    { d: 'bg-red-900/40 text-red-300 border-red-700/40',             l: 'bg-red-50 text-red-700 border-red-200' },
  EYEBALL:       { d: 'bg-amber-900/40 text-amber-300 border-amber-700/40',       l: 'bg-amber-50 text-amber-700 border-amber-200' },
  FRAUD_HOLD:    { d: 'bg-violet-900/40 text-violet-300 border-violet-700/40',    l: 'bg-violet-50 text-violet-700 border-violet-200' },
  IET_EMERGENCY: { d: 'bg-rose-900/60 text-rose-200 border-rose-600/50',          l: 'bg-rose-100 text-rose-700 border-rose-300' },
}

function shieldStatus(smb) {
  const rate = smb.stp_return / smb.total
  if (rate >= smb.soft_hold_threshold * 2) return 'HARD_STOP'
  if (rate >= smb.soft_hold_threshold) return 'SOFT_HOLD'
  if (rate >= smb.return_threshold) return 'WARN'
  return 'SAFE'
}

function ReturnRateBar({ value, threshold, softThreshold, isDark }) {
  const pct = Math.min(value * 100, 100)
  const color = value >= softThreshold ? 'bg-red-500' : value >= threshold ? 'bg-amber-400' : 'bg-emerald-400'
  const track = isDark ? 'bg-white/10' : 'bg-slate-200'
  return (
    <div className={`relative h-2 rounded-full overflow-visible ${track}`}>
      <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      {/* threshold marker */}
      <div className="absolute top-0 h-full w-0.5 bg-amber-400/70" style={{ left: `${threshold * 100}%` }} />
      <div className="absolute top-0 h-full w-0.5 bg-red-500/70"   style={{ left: `${softThreshold * 100}%` }} />
    </div>
  )
}

function ShieldBadge({ status, isDark }) {
  const map = {
    SAFE:      { d: 'bg-emerald-900/40 text-emerald-300', l: 'bg-emerald-50 text-emerald-700', label: '✓ SAFE' },
    WARN:      { d: 'bg-amber-900/40 text-amber-300',     l: 'bg-amber-50 text-amber-700',     label: '⚠ WARN' },
    SOFT_HOLD: { d: 'bg-red-900/50 text-red-300',         l: 'bg-red-100 text-red-700',         label: '⏸ SOFT-HOLD' },
    HARD_STOP: { d: 'bg-rose-900/70 text-rose-200',       l: 'bg-rose-200 text-rose-800',       label: '⛔ HARD-STOP' },
  }
  const m = map[status] || map.SAFE
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${isDark ? m.d : m.l}`}>
      {m.label}
    </span>
  )
}

function DetailPanel({ smb, isDark, onClose }) {
  const th = {
    panel:   isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    label:   isDark ? 'text-slate-400' : 'text-slate-500',
    value:   isDark ? 'text-slate-200' : 'text-slate-700',
    divider: isDark ? 'border-white/8' : 'border-slate-100',
    row:     isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
  }

  const rate = smb.stp_return / smb.total
  const status = shieldStatus(smb)

  const returnItems = RETURN_EVENTS.filter(e => e.smb === smb.id)

  return (
    <div className={`border rounded-lg p-4 mb-4 ${th.panel}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className={`text-sm font-semibold ${th.heading}`}>{smb.bank_name} — Detail</div>
          <div className={`text-xs ${th.label}`}>{smb.ifsc_prefix} · MICR {smb.micr_prefix} · Sponsor: {smb.sponsor}</div>
        </div>
        <button onClick={onClose} className={`text-sm px-2 py-1 rounded ${isDark ? 'hover:bg-white/8 text-slate-400' : 'hover:bg-slate-100 text-slate-500'}`}>✕</button>
      </div>

      {/* Notification config */}
      <div className={`flex items-center gap-2 mb-3 py-2 border-t border-b ${th.divider}`}>
        <span className={`text-[10px] ${th.label}`}>BM Email:</span>
        <span className={`text-[11px] font-mono ${th.value}`}>{smb.bm_email}</span>
        <span className={`text-[10px] ${th.label} ml-4`}>Thresholds:</span>
        <span className={`text-[11px] ${th.value}`}>Warn {(smb.return_threshold * 100).toFixed(0)}% / Hold {(smb.soft_hold_threshold * 100).toFixed(0)}%</span>
      </div>

      {/* Bucket grid */}
      <div className="grid grid-cols-5 gap-2 mb-3">
        {[
          { label: 'STP Pass',    count: smb.stp_pass,      bucket: 'STP_PASS'      },
          { label: 'STP Return',  count: smb.stp_return,    bucket: 'STP_RETURN'    },
          { label: 'Eyeball',     count: smb.eyeball,       bucket: 'EYEBALL'       },
          { label: 'Fraud Hold',  count: smb.fraud_hold,    bucket: 'FRAUD_HOLD'    },
          { label: 'IET Emerg.',  count: smb.iet_emergency, bucket: 'IET_EMERGENCY' },
        ].map(({ label, count, bucket }) => {
          const bc = BUCKET_COLORS[bucket]
          return (
            <div key={bucket} className={`rounded border px-2 py-1.5 text-center ${isDark ? bc.d : bc.l}`}>
              <div className="text-lg font-bold">{count}</div>
              <div className="text-[10px] opacity-80">{label}</div>
            </div>
          )
        })}
      </div>

      {/* Return rate bar */}
      <div className="mb-3">
        <div className="flex justify-between mb-1">
          <span className={`text-[11px] ${th.label}`}>Return Rate</span>
          <span className={`text-[11px] font-semibold ${rate >= smb.soft_hold_threshold ? 'text-red-400' : rate >= smb.return_threshold ? 'text-amber-400' : 'text-emerald-400'}`}>
            {(rate * 100).toFixed(1)}%
          </span>
        </div>
        <ReturnRateBar value={rate} threshold={smb.return_threshold} softThreshold={smb.soft_hold_threshold} isDark={isDark} />
        <div className={`flex gap-4 mt-1 text-[9px] ${th.label}`}>
          <span>● Warn at {(smb.return_threshold * 100).toFixed(0)}%</span>
          <span>● Soft-Hold at {(smb.soft_hold_threshold * 100).toFixed(0)}%</span>
          <span>● Hard-Stop at {(smb.soft_hold_threshold * 200).toFixed(0)}%</span>
        </div>
      </div>

      {/* Return event log */}
      {returnItems.length > 0 && (
        <div>
          <div className={`text-[11px] font-medium mb-1 ${th.label}`}>Return Events (This Session)</div>
          <table className="w-full text-[11px]">
            <thead>
              <tr className={`border-b ${th.divider}`}>
                {['Time', 'Ref (last 4)', 'Reason', 'Bucket', 'Amount'].map(h => (
                  <th key={h} className={`py-1 text-left font-medium ${th.label}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {returnItems.map(e => {
                const bc = BUCKET_COLORS[e.bucket]
                return (
                  <tr key={e.id} className={`border-b ${th.row}`}>
                    <td className={`py-1 ${th.value}`}>{e.time}</td>
                    <td className={`py-1 font-mono ${th.value}`}>...{e.suffix}</td>
                    <td className={`py-1 ${th.value}`}>{e.reason}</td>
                    <td className="py-1">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] border ${isDark ? bc.d : bc.l}`}>
                        {e.bucket}
                      </span>
                    </td>
                    <td className={`py-1 ${th.value}`}>{e.amount}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function CTSSubMember() {
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950 text-white'          : 'bg-slate-50 text-slate-900',
    card:    isDark ? 'bg-white/4 border-white/8'      : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                      : 'text-slate-900',
    body:    isDark ? 'text-slate-300'                  : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'                  : 'text-slate-500',
    label:   isDark ? 'text-slate-500'                  : 'text-slate-400',
    divider: isDark ? 'border-white/8'                  : 'border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/3' : 'border-slate-100 hover:bg-slate-50',
    kpi:     isDark ? 'bg-navy-900/70 border-white/6'   : 'bg-white border-slate-200',
  }

  const totalInward  = SUB_MEMBERS.reduce((s, m) => s + m.total, 0)
  const totalReturns = SUB_MEMBERS.reduce((s, m) => s + m.stp_return, 0)
  const totalEyeball = SUB_MEMBERS.reduce((s, m) => s + m.eyeball, 0)
  const totalFraud   = SUB_MEMBERS.reduce((s, m) => s + m.fraud_hold, 0)
  const avgReturnRate = totalInward ? (totalReturns / totalInward * 100).toFixed(1) : '0.0'
  const softHoldCount = SUB_MEMBERS.filter(m => shieldStatus(m) === 'SOFT_HOLD' || shieldStatus(m) === 'HARD_STOP').length

  const KPIs = [
    { label: 'Sub-Member Banks', value: SUB_MEMBERS.length, color: 'text-sky-400' },
    { label: 'Total Inward',     value: totalInward,         color: 'text-slate-200' },
    { label: 'Total Returns',    value: totalReturns,        color: 'text-red-400' },
    { label: 'Avg Return Rate',  value: `${avgReturnRate}%`, color: totalReturns / totalInward > 0.15 ? 'text-red-400' : 'text-emerald-400' },
    { label: 'Eyeball Queue',    value: totalEyeball,        color: 'text-amber-400' },
    { label: 'Fraud Hold',       value: totalFraud,          color: 'text-violet-400' },
    { label: 'Shield Active',    value: softHoldCount,       color: softHoldCount > 0 ? 'text-red-400' : 'text-emerald-400' },
  ]

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Sub-Member Bank Monitoring</h1>
            <p className={`text-xs ${th.muted}`}>Sponsor routing · Bucket classification · Return rate shield · Tier 1/2/3 notifications</p>
          </div>
          <div className={`text-[11px] px-2 py-1 rounded border ${th.kpi} ${th.muted}`}>
            Session: MORNING 2026-06-19
          </div>
        </div>

        {/* KPI Strip */}
        <div className="grid grid-cols-7 gap-2 mb-5">
          {KPIs.map(({ label, value, color }) => (
            <div key={label} className={`border rounded-lg px-3 py-2 ${th.kpi}`}>
              <div className={`text-xl font-bold ${color}`}>{value}</div>
              <div className={`text-[10px] ${th.label} mt-0.5`}>{label}</div>
            </div>
          ))}
        </div>

        {/* Detail panel */}
        {selected && (
          <DetailPanel
            smb={SUB_MEMBERS.find(m => m.id === selected)}
            isDark={isDark}
            onClose={() => setSelected(null)}
          />
        )}

        {/* Sub-member cards */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {SUB_MEMBERS.map(smb => {
            const rate = smb.stp_return / smb.total
            const status = shieldStatus(smb)
            const isActive = selected === smb.id
            return (
              <div
                key={smb.id}
                onClick={() => setSelected(isActive ? null : smb.id)}
                className={`border rounded-lg p-4 cursor-pointer transition-all ${th.card} ${isActive ? (isDark ? 'ring-1 ring-gold-400/50' : 'ring-1 ring-amber-400/60') : ''}`}
              >
                {/* Card header */}
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <div className={`text-sm font-semibold ${th.heading}`}>{smb.bank_name}</div>
                    <div className={`text-[11px] ${th.muted}`}>
                      {smb.ifsc_prefix} · MICR {smb.micr_prefix} · {smb.id}
                    </div>
                    <div className={`text-[10px] ${th.label} mt-0.5`}>Sponsor: {smb.sponsor}</div>
                  </div>
                  <ShieldBadge status={status} isDark={isDark} />
                </div>

                {/* Mini bucket bar */}
                <div className="flex gap-1 mb-3">
                  {[
                    { count: smb.stp_pass,      bucket: 'STP_PASS',      label: 'P' },
                    { count: smb.stp_return,    bucket: 'STP_RETURN',    label: 'R' },
                    { count: smb.eyeball,       bucket: 'EYEBALL',       label: 'E' },
                    { count: smb.fraud_hold,    bucket: 'FRAUD_HOLD',    label: 'F' },
                    { count: smb.iet_emergency, bucket: 'IET_EMERGENCY', label: '!' },
                  ].map(({ count, bucket, label }) => {
                    const bc = BUCKET_COLORS[bucket]
                    const width = smb.total ? Math.max((count / smb.total) * 100, count > 0 ? 4 : 0) : 0
                    return count > 0 ? (
                      <div
                        key={bucket}
                        className={`relative h-6 rounded text-[9px] flex items-center justify-center font-bold border ${isDark ? bc.d : bc.l}`}
                        style={{ width: `${width}%`, minWidth: '20px' }}
                        title={`${bucket}: ${count}`}
                      >
                        {label}:{count}
                      </div>
                    ) : null
                  })}
                </div>

                {/* Stats row */}
                <div className="flex items-center justify-between">
                  <div className="flex gap-4">
                    <div>
                      <span className={`text-xs ${th.label}`}>Total: </span>
                      <span className={`text-xs font-semibold ${th.body}`}>{smb.total}</span>
                    </div>
                    <div>
                      <span className={`text-xs ${th.label}`}>Return: </span>
                      <span className={`text-xs font-semibold ${rate >= smb.soft_hold_threshold ? 'text-red-400' : rate >= smb.return_threshold ? 'text-amber-400' : 'text-emerald-400'}`}>
                        {(rate * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                  {smb.soft_hold && (
                    <span className="text-[10px] text-red-400 font-medium animate-pulse">⏸ Soft Hold Active</span>
                  )}
                </div>

                {/* Return rate bar */}
                <div className="mt-2">
                  <ReturnRateBar
                    value={rate}
                    threshold={smb.return_threshold}
                    softThreshold={smb.soft_hold_threshold}
                    isDark={isDark}
                  />
                </div>
              </div>
            )
          })}
        </div>

        {/* Notification log */}
        <div className={`border rounded-lg ${th.card}`}>
          <div className={`px-4 py-3 border-b ${th.divider} flex items-center justify-between`}>
            <div className={`text-sm font-semibold ${th.heading}`}>Notification Log — Today</div>
            <div className={`text-[10px] ${th.muted}`}>Tier 1 = immediate · Tier 2 = batch · Tier 3 = GM escalation</div>
          </div>
          <table className="w-full text-[12px]">
            <thead className={`border-b ${th.divider}`}>
              <tr>
                {['Time', 'Bank', 'Ref (…last4)', 'Reason', 'Bucket', 'Amount', 'Tier', 'Recipient'].map(h => (
                  <th key={h} className={`px-4 py-2 text-left font-medium ${th.label}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {RETURN_EVENTS.map(e => {
                const smb = SUB_MEMBERS.find(m => m.id === e.smb)
                const bc = BUCKET_COLORS[e.bucket]
                const tierColor = e.tier === 3
                  ? (isDark ? 'bg-red-900/40 text-red-300 border-red-700/40' : 'bg-red-50 text-red-700 border-red-200')
                  : e.tier === 2
                  ? (isDark ? 'bg-amber-900/40 text-amber-300 border-amber-700/40' : 'bg-amber-50 text-amber-700 border-amber-200')
                  : (isDark ? 'bg-sky-900/40 text-sky-300 border-sky-700/40' : 'bg-sky-50 text-sky-700 border-sky-200')
                return (
                  <tr key={e.id} className={`border-b ${th.row}`}>
                    <td className={`px-4 py-2 ${th.body}`}>{e.time}</td>
                    <td className={`px-4 py-2 ${th.body}`}>{smb?.bank_name}</td>
                    <td className={`px-4 py-2 font-mono ${th.body}`}>…{e.suffix}</td>
                    <td className={`px-4 py-2 ${th.body}`}>{e.reason}</td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] border ${isDark ? bc.d : bc.l}`}>
                        {e.bucket}
                      </span>
                    </td>
                    <td className={`px-4 py-2 ${th.body}`}>{e.amount}</td>
                    <td className="px-4 py-2">
                      <span className={`px-1.5 py-0.5 rounded text-[10px] border ${tierColor}`}>
                        Tier {e.tier}
                      </span>
                    </td>
                    <td className={`px-4 py-2 font-mono text-[11px] ${th.muted}`}>{smb?.bm_email}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

      </div>
    </AppShell>
  )
}
