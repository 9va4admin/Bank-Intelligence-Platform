/**
 * CTS Dashboard — the "Dashboard" nav target for every CTS user.
 *
 * SB users: two tabs.
 *   My Bank      — this bank's own clearing performance (today's val/vol,
 *                  STP/manual breakdown, sessions, 7-day trend, downloads).
 *   SMB Dashboard — the same OpsDashboardBody, fed either the combined total
 *                  across every sponsored SMB or one SMB's numbers via the
 *                  filter row (reuses BankContext's selectedSmbId drill-down).
 * SMB users: no tabs — this page IS their own SMB dashboard
 *   (SMBDashboardContent, shared with the standalone /cts/smb/dashboard route).
 */
import { useState, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'
import OpsDashboardBody from '../components/OpsDashboardBody'
import SMBDashboardContent from '../components/SMBDashboardContent'

// RPC zones — each is a live, independent connection to NGCH for its clearing
// zone (CLAUDE.md §2.2). Kept in sync with CTSRPCConsolidation.jsx's RPCS data.
// Shown first on My Bank: an RPC going DEGRADED is an NPCI-connectivity risk,
// not a routine stat — it belongs above the fold, not three clicks deep.
const ZONE_STATUS = [
  { zone: 'MUMBAI',    status: 'ACTIVE',   pending: 14, iet_risk: 2 },
  { zone: 'DELHI',     status: 'ACTIVE',   pending: 7,  iet_risk: 0 },
  { zone: 'CHENNAI',   status: 'ACTIVE',   pending: 4,  iet_risk: 0 },
  { zone: 'KOLKATA',   status: 'ACTIVE',   pending: 3,  iet_risk: 0 },
  { zone: 'HYDERABAD', status: 'DEGRADED', pending: 21, iet_risk: 5 },
]

function ZoneGatewayStrip({ isDark }) {
  const th = {
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    label: isDark ? 'text-slate-400' : 'text-slate-500',
  }
  const degraded = ZONE_STATUS.filter(z => z.status !== 'ACTIVE')
  return (
    <Link to="/cts/rpc" className={`block border rounded-xl px-4 py-3 mb-4 transition-colors hover:border-white/25 ${th.card}`}>
      <div className="flex items-center justify-between mb-2">
        <span className={`text-[10px] uppercase tracking-widest font-semibold ${th.label}`}>RPC — NGCH Gateway Status</span>
        {degraded.length > 0 && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-red-400/10 border border-red-400/30 text-red-400">
            {degraded.length} zone{degraded.length > 1 ? 's' : ''} degraded
          </span>
        )}
      </div>
      <div className="flex items-center gap-3 flex-wrap">
        {ZONE_STATUS.map(z => {
          const ok = z.status === 'ACTIVE'
          return (
            <div key={z.zone} className={`flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-lg border ${
              ok
                ? (isDark ? 'border-emerald-700/30 bg-emerald-900/10 text-emerald-300' : 'border-emerald-200 bg-emerald-50 text-emerald-700')
                : (isDark ? 'border-red-700/40 bg-red-900/20 text-red-300' : 'border-red-200 bg-red-50 text-red-700')
            }`}>
              <span className={`w-1.5 h-1.5 rounded-full ${ok ? 'bg-emerald-400' : 'bg-red-400 animate-pulse'}`} />
              <span className="font-medium">{z.zone}</span>
              {!ok && <span className="font-mono opacity-80">· {z.iet_risk} IET risk</span>}
            </div>
          )
        })}
      </div>
    </Link>
  )
}

// ─── Mock data (matches /v1/cts/sessions/today + /v1/cts/dashboard/ops) ──────

const SB_TODAY = {
  clearing_date: '2026-06-25',
  sessions_count: 4,
  sessions_settled: 2,
  total_inward: 5175,
  total_inward_value_paise: 135_80_00_000,
  stp_confirmed: 3674,
  stp_returned: 724,
  manual_confirmed: 466,
  manual_returned: 259,
  pending_review: 52,
  overall_stp_rate_pct: 84.9,
  overall_return_rate_pct: 19.1,
  total_outward: 3480,
  total_outward_value_paise: 98_40_00_000,
  outward_returned: 278,
  net_settlement_paise: 43_20_00_000,
}

// One representative SMB's numbers — reused when the SMB Dashboard tab is
// filtered down to a single sponsored SMB.
const SMB_TODAY = {
  clearing_date: '2026-06-25',
  sessions_count: 2,
  sessions_settled: 1,
  total_inward: 318,
  total_inward_value_paise: 8_45_00_000,
  stp_confirmed: 224,
  stp_returned: 49,
  manual_confirmed: 28,
  manual_returned: 13,
  pending_review: 4,
  overall_stp_rate_pct: 85.5,
  overall_return_rate_pct: 19.5,
  total_outward: 207,
  total_outward_value_paise: 5_80_00_000,
  outward_returned: 18,
  net_settlement_paise: 2_65_00_000,
}

// All sponsored SMBs summed — the SMB Dashboard tab's default ("All SMBs") view.
const SMB_COMBINED_TODAY = {
  clearing_date: '2026-06-25',
  sessions_count: 8,
  sessions_settled: 4,
  total_inward: 1284,
  total_inward_value_paise: 34_10_00_000,
  stp_confirmed: 902,
  stp_returned: 198,
  manual_confirmed: 113,
  manual_returned: 71,
  pending_review: 15,
  overall_stp_rate_pct: 84.7,
  overall_return_rate_pct: 20.9,
  total_outward: 836,
  total_outward_value_paise: 23_35_00_000,
  outward_returned: 74,
  net_settlement_paise: 10_75_00_000,
}

function makeSessions(bankIfsc, scale) {
  const prefix = `SES-${bankIfsc}-20260625`
  if (scale === 'smb') {
    return [
      { id: `${prefix}-001`, slot: '10:00–12:00', status: 'SETTLED', inward: 143, inward_val: 3_80_00_000, stp_rate: 86.7, return_rate: 18.2 },
      { id: `${prefix}-002`, slot: '12:00–14:00', status: 'OPEN',    inward: 175, inward_val: 4_65_00_000, stp_rate: 84.6, return_rate: 20.6 },
    ]
  }
  if (scale === 'smb_combined') {
    return [
      { id: `${prefix}-001`, slot: '10:00–12:00', status: 'SETTLED', inward: 612, inward_val: 16_20_00_000, stp_rate: 85.9, return_rate: 19.4 },
      { id: `${prefix}-002`, slot: '12:00–14:00', status: 'OPEN',    inward: 672, inward_val: 17_90_00_000, stp_rate: 83.5, return_rate: 22.3 },
    ]
  }
  return [
    { id: `${prefix}-001`, slot: '10:00–12:00', status: 'SETTLED', inward: 1840, inward_val: 42_30_00_000, stp_rate: 86.2, return_rate: 17.8 },
    { id: `${prefix}-002`, slot: '12:00–14:00', status: 'FILED',   inward: 2105, inward_val: 53_70_00_000, stp_rate: 84.9, return_rate: 19.1 },
    { id: `${prefix}-003`, slot: '14:00–16:00', status: 'OPEN',    inward: 1230, inward_val: 29_80_00_000, stp_rate: 82.4, return_rate: 20.4 },
    { id: `${prefix}-004`, slot: '16:00–18:00', status: 'UPCOMING',inward: 0,    inward_val: 0,            stp_rate: 0,    return_rate: 0 },
  ]
}

const SB_TREND = [
  { date: 'Jun 19', inward: 4820, return_rate_pct: 18.4, stp_rate_pct: 81.6 },
  { date: 'Jun 20', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 21', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 22', inward: 5210, return_rate_pct: 17.9, stp_rate_pct: 82.1 },
  { date: 'Jun 23', inward: 5640, return_rate_pct: 19.2, stp_rate_pct: 80.8 },
  { date: 'Jun 24', inward: 4980, return_rate_pct: 18.8, stp_rate_pct: 81.2 },
  { date: 'Jun 25', inward: 5175, return_rate_pct: 19.1, stp_rate_pct: 84.9 },
]

const SMB_TREND = [
  { date: 'Jun 19', inward: 295, return_rate_pct: 18.6, stp_rate_pct: 81.4 },
  { date: 'Jun 20', inward: 0,   return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 21', inward: 0,   return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 22', inward: 312, return_rate_pct: 18.3, stp_rate_pct: 81.7 },
  { date: 'Jun 23', inward: 341, return_rate_pct: 19.8, stp_rate_pct: 80.2 },
  { date: 'Jun 24', inward: 307, return_rate_pct: 19.0, stp_rate_pct: 81.0 },
  { date: 'Jun 25', inward: 318, return_rate_pct: 19.5, stp_rate_pct: 85.5 },
]

const SMB_COMBINED_TREND = [
  { date: 'Jun 19', inward: 1190, return_rate_pct: 19.9, stp_rate_pct: 80.3 },
  { date: 'Jun 20', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 21', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 22', inward: 1258, return_rate_pct: 19.5, stp_rate_pct: 80.9 },
  { date: 'Jun 23', inward: 1341, return_rate_pct: 21.2, stp_rate_pct: 79.4 },
  { date: 'Jun 24', inward: 1204, return_rate_pct: 20.1, stp_rate_pct: 80.6 },
  { date: 'Jun 25', inward: 1284, return_rate_pct: 20.9, stp_rate_pct: 84.7 },
]

// ─── Combine helpers ──────────────────────────────────────────────────────────
// Counts/values sum directly. Rates are recomputed from the combined raw counts
// (never summed/averaged directly — two percentages don't add).

function combineToday(sb, smb) {
  const total_inward = sb.total_inward + smb.total_inward
  const total_outward = sb.total_outward + smb.total_outward
  const stp_confirmed = sb.stp_confirmed + smb.stp_confirmed
  const stp_returned = sb.stp_returned + smb.stp_returned
  const manual_confirmed = sb.manual_confirmed + smb.manual_confirmed
  const manual_returned = sb.manual_returned + smb.manual_returned
  const outward_returned = sb.outward_returned + smb.outward_returned
  return {
    clearing_date: sb.clearing_date,
    sessions_count: sb.sessions_count + smb.sessions_count,
    sessions_settled: sb.sessions_settled + smb.sessions_settled,
    total_inward,
    total_inward_value_paise: sb.total_inward_value_paise + smb.total_inward_value_paise,
    stp_confirmed,
    stp_returned,
    manual_confirmed,
    manual_returned,
    pending_review: sb.pending_review + smb.pending_review,
    overall_stp_rate_pct: total_inward > 0 ? +(((stp_confirmed + stp_returned) / total_inward) * 100).toFixed(1) : 0,
    overall_return_rate_pct: total_inward > 0 ? +(((stp_returned + manual_returned) / total_inward) * 100).toFixed(1) : 0,
    total_outward,
    total_outward_value_paise: sb.total_outward_value_paise + smb.total_outward_value_paise,
    outward_returned,
    net_settlement_paise: sb.net_settlement_paise + smb.net_settlement_paise,
  }
}

function combineTrend(sbTrend, smbTrend) {
  return sbTrend.map((sbDay, i) => {
    const smbDay = smbTrend[i]
    const inward = sbDay.inward + smbDay.inward
    // Volume-weighted average — the correct way to combine two rates when only
    // the rate + its own volume are known (no raw counts at the daily-trend level).
    const weighted = (field) =>
      inward > 0 ? +(((sbDay[field] * sbDay.inward) + (smbDay[field] * smbDay.inward)) / inward).toFixed(1) : 0
    return {
      date: sbDay.date,
      inward,
      return_rate_pct: weighted('return_rate_pct'),
      stp_rate_pct: weighted('stp_rate_pct'),
    }
  })
}

// ─── Tab bar ──────────────────────────────────────────────────────────────────

function DashboardTabs({ tab, onChange, isDark }) {
  return (
    <div className="flex gap-1">
      {[['mybank', 'My Bank'], ['smb', 'SMB Dashboard']].map(([key, label]) => (
        <button
          key={key}
          onClick={() => onChange(key)}
          className={`text-xs font-semibold px-4 py-2 rounded-lg border transition-all ${
            tab === key
              ? (isDark ? 'bg-white/10 text-white border-white/15' : 'bg-slate-800 text-white border-slate-800')
              : (isDark ? 'text-slate-400 border-white/8 hover:bg-white/5' : 'text-slate-500 border-slate-200 hover:bg-slate-50')
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  )
}

function SMBFilterBar({ smbs, selectedSmbId, onSelect, isDark }) {
  const pills = [{ id: null, shortName: 'All SMBs' }, ...smbs]
  return (
    <div className="flex gap-1.5 flex-wrap mb-4">
      {pills.map(s => (
        <button
          key={s.id ?? 'all'}
          onClick={() => onSelect(s.id)}
          className={`text-[11px] font-medium px-3 py-1.5 rounded-full border transition-all ${
            selectedSmbId === s.id
              ? (isDark ? 'bg-violet-500/20 border-violet-400/40 text-violet-300' : 'bg-violet-100 border-violet-300 text-violet-700')
              : (isDark ? 'border-white/10 text-slate-400 hover:border-white/25' : 'border-slate-200 text-slate-500 hover:border-slate-300')
          }`}
        >
          {s.id === null ? '◆ ' : ''}{s.shortName}
        </button>
      ))}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSOpsDashboard() {
  const { isDark } = useTheme()
  const { bankName, bankIfsc, isSMB, smbs, selectedSmbId, setSelectedSmbId, selectedSmb } = useBankContext()
  const [dashTab, setDashTab] = useState('mybank') // 'mybank' | 'smb' — SB only
  const [includeSMB, setIncludeSMB] = useState(false) // My Bank tab: combine with sponsored SMBs
  const [downloading, setDownloading] = useState(null)

  // All hooks called unconditionally, every render — the isSMB early return
  // below must never skip a hook that ran on a previous render.
  const sbSessions = useMemo(() => makeSessions(bankIfsc, 'sb'), [bankIfsc])
  const smbSessions = useMemo(() => makeSessions(selectedSmb?.ifsc || bankIfsc, 'smb'), [selectedSmb, bankIfsc])
  const smbCombinedSessions = useMemo(() => makeSessions(bankIfsc, 'smb_combined'), [bankIfsc])

  function handleDownload(sessionId, type) {
    const pathMap = { 'NPCI RRF': 'npci', 'MIS CSV': 'mis', 'Settlement': 'settlement' }
    const path = pathMap[type]
    setDownloading(`${sessionId}-${path}`)
    // In production: call /v1/cts/sessions/{id}/download/{path}
    setTimeout(() => setDownloading(null), 1200)
  }

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  // SMB users: this page IS their own dashboard — no tabs, nothing to filter.
  if (isSMB) {
    return (
      <AppShell>
        <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
          <SMBDashboardContent />
        </div>
      </AppShell>
    )
  }

  // Sessions grid stays SB's own regardless of the checkbox — a "session" is a
  // clearing window scoped to this bank; merging SMB session rows into the same
  // grid would mix two banks' processing windows in one list.
  const myBank = includeSMB
    ? { TODAY: combineToday(SB_TODAY, SMB_COMBINED_TODAY), SESSIONS: sbSessions, TREND: combineTrend(SB_TREND, SMB_COMBINED_TREND) }
    : { TODAY: SB_TODAY, SESSIONS: sbSessions, TREND: SB_TREND }
  const smbView = selectedSmbId
    ? { TODAY: SMB_TODAY, SESSIONS: smbSessions, TREND: SMB_TREND }
    : { TODAY: SMB_COMBINED_TODAY, SESSIONS: smbCombinedSessions, TREND: SMB_COMBINED_TREND }

  const active = dashTab === 'mybank' ? myBank : smbView
  const totalSessions = active.TODAY.sessions_count
  const settledSessions = active.TODAY.sessions_settled

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>Clearing Operations Dashboard</h1>
              <p className={`text-[11px] ${th.muted}`}>
                {dashTab === 'mybank'
                  ? (includeSMB ? `${bankName} + ${smbs.length} Sponsored SMBs (combined)` : bankName)
                  : (selectedSmbId ? selectedSmb?.name : 'All Sponsored SMBs')}
                {' · '}{active.TODAY.clearing_date} · {totalSessions} sessions · {settledSessions} settled
              </p>
            </div>
            <div className="flex items-center gap-3 flex-wrap">
              {dashTab === 'mybank' && (
                <label className={`flex items-center gap-1.5 text-[11px] font-medium cursor-pointer select-none ${isDark ? 'text-slate-300' : 'text-slate-600'}`}>
                  <input
                    type="checkbox"
                    checked={includeSMB}
                    onChange={(e) => setIncludeSMB(e.target.checked)}
                    className="w-3.5 h-3.5 rounded accent-violet-500"
                  />
                  + SMB
                </label>
              )}
              <DashboardTabs tab={dashTab} onChange={setDashTab} isDark={isDark} />
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-400/10 border border-emerald-400/20 text-emerald-400">● Live</span>
              <button
                onClick={() => handleDownload('TODAY', 'MIS CSV')}
                className={`text-[11px] px-3 py-1.5 rounded-lg border transition-colors
                  ${isDark ? 'border-white/15 text-slate-300 hover:text-white hover:bg-white/5' : 'border-slate-200 text-slate-600 hover:text-slate-900 hover:bg-slate-100'}`}
              >
                ↓ Today's MIS
              </button>
            </div>
          </div>
        </div>

        <div className="px-6 py-5 max-w-7xl">
          {dashTab === 'mybank' && <ZoneGatewayStrip isDark={isDark} />}
          {dashTab === 'smb' && (
            <SMBFilterBar smbs={smbs} selectedSmbId={selectedSmbId} onSelect={setSelectedSmbId} isDark={isDark} />
          )}
          <OpsDashboardBody
            TODAY={active.TODAY}
            SESSIONS={active.SESSIONS}
            TREND={active.TREND}
            isDark={isDark}
            downloading={downloading}
            onDownload={handleDownload}
          />
        </div>
      </div>
    </AppShell>
  )
}
