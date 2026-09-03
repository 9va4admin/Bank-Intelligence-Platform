import { useState, useMemo, useEffect, useCallback, useRef } from 'react'
import AppShell from '../../../shared/layout/AppShell'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { usePageHeader } from '../../../shared/layout/PageHeaderContext'
import { useBankContext } from '../../../shared/context/BankContext'
import { BANK_CONFIG } from '../../../shared/config/bank.config'
import useSMBList from '../hooks/useSMBList'

const _API_BASE = import.meta.env.VITE_API_BASE ?? ''

function useReturnEvents({ pollEnabled }) {
  const [events, setEvents] = useState(null)
  const timerRef = useRef(null)
  const fetch_ = useCallback(async () => {
    try {
      const res = await fetch(`${_API_BASE}/v1/cts/smb/return-events?limit=200`, { credentials: 'include' })
      if (!res.ok) return
      const json = await res.json()
      setEvents(json.events ?? [])
    } catch { /* keep last */ }
  }, [])
  useEffect(() => {
    if (!pollEnabled) return
    fetch_()
    timerRef.current = setInterval(fetch_, 60_000)
    return () => clearInterval(timerRef.current)
  }, [fetch_, pollEnabled])
  return events
}

// ── Derive sub-member session data from BANK_CONFIG.smbs ─────────────────────

const RETURN_REASONS_POOL = [
  'SIGNATURE_MISMATCH', 'AMOUNT_ALTERATION', 'STALE_CHEQUE',
  'PPS_MISMATCH', 'DRAWEE_ACCOUNT_FROZEN', 'STOP_PAYMENT_ACTIVE', 'FRAUD_RISK',
]
const BUCKETS_POOL = ['STP_RETURN', 'FRAUD_HOLD', 'EYEBALL', 'STP_RETURN', 'STP_RETURN']
const AMOUNTS_POOL = ['₹[<1L]', '₹[1L–5L]', '₹[5L–10L]', '₹[10L–1Cr]']
const TIMES_POOL   = ['09:14', '09:21', '09:35', '09:42', '10:03', '10:28', '10:51']

function buildMockSubMembers(bankConfig) {
  const smbs = bankConfig.smbs ?? []
  const session = `MORNING ${new Date().toISOString().slice(0, 10)}`
  return smbs.map((smb, i) => {
    const daily = smb.daily_avg ?? 80
    const total = Math.round(daily * (0.6 + (i % 5) * 0.1))
    const returnRate = [0.04, 0.20, 0.07, 0.11, 0.05, 0.09, 0.15, 0.03][i % 8]
    const stp_return = Math.round(total * returnRate)
    const eyeball   = Math.round(total * 0.02 + i)
    const fraud_hold = Math.round(total * 0.005)
    const stp_pass  = total - stp_return - eyeball - fraud_hold
    const softThreshold = 0.18 + (i % 3) * 0.04
    const domain = smb.name.toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 10)
    return {
      id:               smb.id,
      bank_name:        smb.name,
      ifsc_prefix:      smb.ifsc?.slice(0, 4) ?? 'SMBB',
      micr_prefix:      `${400 + i * 11}${String(i + 1).padStart(3, '0')}`,
      sponsor:          bankConfig.bank_name,
      session,
      total,
      stp_pass:         Math.max(0, stp_pass),
      stp_return,
      eyeball,
      fraud_hold,
      iet_emergency:    0,
      soft_hold:        returnRate >= softThreshold,
      bm_email:         `bm.${smb.city?.toLowerCase() ?? 'main'}@${domain}.coop`,
      return_threshold: 0.12,
      soft_hold_threshold: softThreshold,
    }
  })
}

function buildReturnEvents(smbs) {
  if (!smbs.length) return []
  return smbs.slice(0, Math.min(smbs.length, 3)).flatMap((smb, si) =>
    Array.from({ length: 1 + (si % 2) }, (_, ei) => ({
      id:     `CHQ-IN-20260831-${String(si * 10 + ei + 42).padStart(4, '0')}`,
      smb:    smb.id,
      reason: RETURN_REASONS_POOL[(si * 3 + ei) % RETURN_REASONS_POOL.length],
      bucket: BUCKETS_POOL[(si + ei) % BUCKETS_POOL.length],
      amount: AMOUNTS_POOL[(si + ei) % AMOUNTS_POOL.length],
      suffix: String(1000 + (si * 37 + ei * 13) % 9000),
      time:   TIMES_POOL[(si * 2 + ei) % TIMES_POOL.length],
      tier:   1 + (ei % 2),
    }))
  )
}

const MOCK_SMBS   = buildMockSubMembers(BANK_CONFIG)
const RETURN_EVENTS = buildReturnEvents(MOCK_SMBS)

const BUCKET_COLORS_D = {
  STP_PASS:      'bg-emerald-900/40 text-emerald-300 border-emerald-700/40',
  STP_RETURN:    'bg-red-900/40 text-red-300 border-red-700/40',
  EYEBALL:       'bg-amber-900/40 text-amber-300 border-amber-700/40',
  FRAUD_HOLD:    'bg-violet-900/40 text-violet-300 border-violet-700/40',
  IET_EMERGENCY: 'bg-rose-900/60 text-rose-200 border-rose-600/50',
}
const BUCKET_COLORS_L = {
  STP_PASS:      'bg-emerald-50 text-emerald-700 border-emerald-200',
  STP_RETURN:    'bg-red-50 text-red-700 border-red-200',
  EYEBALL:       'bg-amber-50 text-amber-700 border-amber-200',
  FRAUD_HOLD:    'bg-violet-50 text-violet-700 border-violet-200',
  IET_EMERGENCY: 'bg-rose-100 text-rose-700 border-rose-300',
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
  const map_D = {
    SAFE:      { cls: 'bg-emerald-900/40 text-emerald-300', label: '✓ SAFE' },
    WARN:      { cls: 'bg-amber-900/40 text-amber-300',     label: '⚠ WARN' },
    SOFT_HOLD: { cls: 'bg-red-900/50 text-red-300',         label: '⏸ SOFT-HOLD' },
    HARD_STOP: { cls: 'bg-rose-900/70 text-rose-200',       label: '⛔ HARD-STOP' },
  }
  const map_L = {
    SAFE:      { cls: 'bg-emerald-50 text-emerald-700', label: '✓ SAFE' },
    WARN:      { cls: 'bg-amber-50 text-amber-700',     label: '⚠ WARN' },
    SOFT_HOLD: { cls: 'bg-red-100 text-red-700',        label: '⏸ SOFT-HOLD' },
    HARD_STOP: { cls: 'bg-rose-200 text-rose-800',      label: '⛔ HARD-STOP' },
  }
  const map = isDark ? map_D : map_L
  const m = map[status] || map.SAFE
  return (
    <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${m.cls}`}>
      {m.label}
    </span>
  )
}

function DetailPanel({ smb, onClose, isDark, BUCKET_COLORS, returnEvents: allReturnEvents }) {
  const th = {
    panel:   isDark ? 'bg-navy-900 border-white/10' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    label:   isDark ? 'text-slate-400' : 'text-slate-500',
    value:   isDark ? 'text-slate-200' : 'text-slate-700',
    divider: isDark ? 'border-white/10' : 'border-slate-100',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
  }

  const rate = smb.stp_return / smb.total
  const status = shieldStatus(smb)

  const returnItems = (allReturnEvents ?? RETURN_EVENTS).filter(e => e.smb === smb.id)

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
            <div key={bucket} className={`rounded border px-2 py-1.5 text-center ${bc}`}>
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
                      <span className={`px-1.5 py-0.5 rounded text-[9px] border ${bc}`}>
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
  const { bankName, bankIfsc, isSB, isSMB, isDemo } = useBankContext()
  const { isDark } = useTheme()
  const [selected, setSelected] = useState(null)

  const BUCKET_COLORS = isDark ? BUCKET_COLORS_D : BUCKET_COLORS_L

  const th = {
    page:    isDark ? 'bg-navy-950 text-white' : 'bg-slate-50 text-slate-900',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    label:   isDark ? 'text-slate-600' : 'text-slate-400',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    row:     isDark ? 'border-white/4 hover:bg-white/2' : 'border-slate-100 hover:bg-slate-50',
    kpi:     isDark ? 'bg-navy-900/70 border-white/6' : 'bg-white border-slate-200',
    select:  isDark ? 'bg-navy-900 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
    input:   isDark ? 'bg-navy-800 border-white/10 text-white' : 'bg-white border-slate-300 text-slate-900',
  }

  const { subMembers: liveSubMembers } = useSMBList({ pollEnabled: !isDemo })
  const liveReturnEvents = useReturnEvents({ pollEnabled: !isDemo })
  const returnEvents = isDemo || !liveReturnEvents ? RETURN_EVENTS : liveReturnEvents

  // Demo invariant: use live data only when non-empty
  const subMembers = useMemo(() => {
    if (isDemo || !liveSubMembers || liveSubMembers.length === 0) return MOCK_SMBS
    // Map SMBListItem → CTSSubMember display shape
    return liveSubMembers.map((m, i) => {
      const total = m.cheques_today ?? 0
      const stp_return = Math.round(total * (m.return_rate_today ?? 0) / 100)
      const eyeball = Math.round(total * 0.02)
      const fraud_hold = Math.round(total * 0.005)
      const stp_pass = Math.max(0, total - stp_return - eyeball - fraud_hold)
      const rt = m.return_rate_today ?? 0
      return {
        id: m.sub_member_id,
        bank_name: m.bank_name,
        ifsc_prefix: m.bank_ifsc?.slice(0, 4) ?? 'SMBB',
        micr_prefix: m.micr_prefix || `${400 + i * 11}${String(i + 1).padStart(3, '0')}`,
        sponsor: m.sponsor_bank_name || 'Sponsor Bank',
        session: 'Today',
        total,
        stp_pass,
        stp_return,
        eyeball,
        fraud_hold,
        iet_emergency: 0,
        soft_hold: rt >= (m.hard_stop_threshold ?? 20),
        bm_email: '',
        return_threshold: 0.12,
        soft_hold_threshold: (m.hard_stop_threshold ?? 20) / 100,
      }
    })
  }, [isDemo, liveSubMembers])
  const totalInward  = subMembers.reduce((s, m) => s + m.total, 0)
  const totalReturns = subMembers.reduce((s, m) => s + m.stp_return, 0)
  const totalEyeball = subMembers.reduce((s, m) => s + m.eyeball, 0)
  const totalFraud   = subMembers.reduce((s, m) => s + m.fraud_hold, 0)
  const avgReturnRate = totalInward ? (totalReturns / totalInward * 100).toFixed(1) : '0.0'
  const softHoldCount = subMembers.filter(m => shieldStatus(m) === 'SOFT_HOLD' || shieldStatus(m) === 'HARD_STOP').length

  const KPIs = [
    { label: 'Sub-Member Banks', value: subMembers.length, color: 'text-sky-400' },
    { label: 'Total Inward',     value: totalInward,         color: isDark ? 'text-slate-200' : 'text-slate-900' },
    { label: 'Total Returns',    value: totalReturns,        color: 'text-red-400' },
    { label: 'Avg Return Rate',  value: `${avgReturnRate}%`, color: totalReturns / totalInward > 0.15 ? 'text-red-400' : 'text-emerald-400' },
    { label: 'Eyeball Queue',    value: totalEyeball,        color: 'text-amber-400' },
    { label: 'Fraud Hold',       value: totalFraud,          color: 'text-violet-400' },
    { label: 'Shield Active',    value: softHoldCount,       color: softHoldCount > 0 ? 'text-red-400' : 'text-emerald-400' },
  ]

  usePageHeader({
    subtitle: 'Sponsor routing · Bucket classification · Return rate shield · Tier 1/2/3 notifications',
  })

  if (isSMB) {
    return (
      <AppShell>
        <div className={`flex-1 flex items-center justify-center ${th.page}`}>
          <div className="text-center">
            <div className="text-4xl mb-4">🏦</div>
            <div className={`text-lg font-semibold mb-1 ${th.heading}`}>SB-Only Feature</div>
            <div className={`text-sm ${th.muted}`}>Sub-member routing is managed by the Sponsor Bank. This page is not available for SMB users.</div>
          </div>
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <div className={`${th.page} px-6 py-5`}>

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
            smb={subMembers.find(m => m.id === selected)}
            onClose={() => setSelected(null)}
            isDark={isDark}
            BUCKET_COLORS={BUCKET_COLORS}
            returnEvents={returnEvents}
          />
        )}

        {/* Sub-member cards */}
        <div className="grid grid-cols-2 gap-4 mb-6">
          {subMembers.map(smb => {
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
                        className={`relative h-6 rounded text-[9px] flex items-center justify-center font-bold border ${bc}`}
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
              {returnEvents.map(e => {
                const smb = subMembers.find(m => m.id === e.smb)
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
                      <span className={`px-1.5 py-0.5 rounded text-[10px] border ${bc}`}>
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
