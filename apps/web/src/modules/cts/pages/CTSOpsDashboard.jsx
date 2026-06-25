/**
 * CTS Ops Dashboard — Morning view for the clearing ops head.
 *
 * Shows:
 *   - Today's val/vol across all sessions (live)
 *   - STP confirmed / STP returned / Manual confirmed / Manual returned
 *   - Presenting bank (inward) + Drawee bank (outward) positions
 *   - Net settlement position (receive / pay)
 *   - 7-day trend (sparklines)
 *   - Per-session cards with drill-down link
 *   - File download buttons (NPCI RRF, MIS CSV, Settlement statement)
 */
import { useState } from 'react'
import { useTheme } from '../../../shared/theme/ThemeContext'
import AppShell from '../../../shared/layout/AppShell'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(n) {
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)}Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(2)}L`
  return `₹${n.toLocaleString('en-IN')}`
}

function fmtPaise(p) { return fmt(p / 100) }

function pct(n, d) { return d > 0 ? ((n / d) * 100).toFixed(1) : '0.0' }

// ─── Mock data (matches /v1/cts/sessions/today + /v1/cts/dashboard/ops) ──────

const TODAY = {
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

const SESSIONS = [
  { id: 'SES-20260625-001', slot: '10:00–12:00', status: 'SETTLED', inward: 1840, inward_val: 42_30_00_000, stp_rate: 86.2, return_rate: 17.8 },
  { id: 'SES-20260625-002', slot: '12:00–14:00', status: 'FILED',   inward: 2105, inward_val: 53_70_00_000, stp_rate: 84.9, return_rate: 19.1 },
  { id: 'SES-20260625-003', slot: '14:00–16:00', status: 'OPEN',    inward: 1230, inward_val: 29_80_00_000, stp_rate: 82.4, return_rate: 20.4 },
  { id: 'SES-20260625-004', slot: '16:00–18:00', status: 'UPCOMING',inward: 0,    inward_val: 0,            stp_rate: 0,    return_rate: 0 },
]

const TREND = [
  { date: 'Jun 19', inward: 4820, return_rate_pct: 18.4, stp_rate_pct: 81.6 },
  { date: 'Jun 20', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 21', inward: 0,    return_rate_pct: 0,    stp_rate_pct: 0 },
  { date: 'Jun 22', inward: 5210, return_rate_pct: 17.9, stp_rate_pct: 82.1 },
  { date: 'Jun 23', inward: 5640, return_rate_pct: 19.2, stp_rate_pct: 80.8 },
  { date: 'Jun 24', inward: 4980, return_rate_pct: 18.8, stp_rate_pct: 81.2 },
  { date: 'Jun 25', inward: 5175, return_rate_pct: 19.1, stp_rate_pct: 84.9 },
]

const SESSION_STATUS_STYLE = {
  SETTLED:  'bg-emerald-400/10 text-emerald-400 border-emerald-400/20',
  FILED:    'bg-blue-400/10 text-blue-400 border-blue-400/20',
  OPEN:     'bg-amber-400/10 text-amber-400 border-amber-400/20',
  UPCOMING: 'bg-slate-400/10 text-slate-400 border-slate-400/20',
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function KPICard({ label, value, sub, color, isDark }) {
  const card  = isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200'
  const lbl   = isDark ? 'text-slate-400' : 'text-slate-500'
  const subC  = isDark ? 'text-slate-500' : 'text-slate-400'
  return (
    <div className={`border rounded-xl p-4 ${card}`}>
      <div className={`text-[11px] uppercase tracking-wide ${lbl} mb-1`}>{label}</div>
      <div className={`text-2xl font-bold font-mono ${color}`}>{value}</div>
      {sub && <div className={`text-[11px] mt-1 ${subC}`}>{sub}</div>}
    </div>
  )
}

function DecisionBar({ stp_c, stp_r, man_c, man_r, pend, total, isDark }) {
  const bg = isDark ? 'bg-white/5' : 'bg-slate-100'
  const segments = [
    { w: pct(stp_c,  total), color: 'bg-emerald-500', label: 'STP Confirmed' },
    { w: pct(stp_r,  total), color: 'bg-red-400',     label: 'STP Returned' },
    { w: pct(man_c,  total), color: 'bg-blue-400',    label: 'Manual Confirmed' },
    { w: pct(man_r,  total), color: 'bg-orange-400',  label: 'Manual Returned' },
    { w: pct(pend,   total), color: 'bg-slate-500',   label: 'Pending' },
  ]
  return (
    <div>
      <div className={`h-3 rounded-full ${bg} flex overflow-hidden`}>
        {segments.map((s, i) => (
          <div key={i} className={`${s.color} h-full transition-all`} style={{ width: `${s.w}%` }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-3 mt-2">
        {segments.map((s, i) => (
          <div key={i} className="flex items-center gap-1">
            <span className={`w-2 h-2 rounded-full ${s.color}`} />
            <span className={`text-[10px] ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>{s.label}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TrendBar({ days, isDark }) {
  const max = Math.max(...days.map(d => d.inward), 1)
  const lbl = isDark ? 'text-slate-500' : 'text-slate-400'
  const bar = isDark ? 'bg-gold-400/70 hover:bg-gold-400' : 'bg-amber-500/70 hover:bg-amber-500'
  const hol = isDark ? 'bg-white/5' : 'bg-slate-100'
  return (
    <div className="flex items-end gap-1 h-16">
      {days.map((d, i) => {
        const h = d.inward > 0 ? Math.max((d.inward / max) * 100, 8) : 0
        return (
          <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
            <div className="w-full flex items-end" style={{ height: '48px' }}>
              {d.inward > 0
                ? <div className={`w-full rounded-t transition-all cursor-default ${bar}`} style={{ height: `${h}%` }} title={`${d.date}: ${d.inward} cheques, ${d.return_rate_pct}% return`} />
                : <div className={`w-full rounded-t ${hol}`} style={{ height: '8%' }} title="Holiday" />
              }
            </div>
            <span className={`text-[9px] ${lbl}`}>{d.date.split(' ')[1]}</span>
          </div>
        )
      })}
    </div>
  )
}

function SessionCard({ s, isDark, onDownload }) {
  const card   = isDark ? 'bg-navy-900 border-white/8 hover:border-white/15' : 'bg-white border-slate-200 hover:border-slate-300'
  const head   = isDark ? 'text-white' : 'text-slate-900'
  const muted  = isDark ? 'text-slate-400' : 'text-slate-500'
  return (
    <div className={`border rounded-xl p-4 transition-colors ${card}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className={`text-sm font-semibold ${head}`}>{s.slot}</div>
          <div className={`text-[11px] ${muted}`}>{s.id}</div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${SESSION_STATUS_STYLE[s.status]}`}>
          {s.status}
        </span>
      </div>
      {s.inward > 0 ? (
        <>
          <div className="grid grid-cols-3 gap-2 mb-3">
            <div>
              <div className={`text-[10px] ${muted}`}>Inward</div>
              <div className={`text-sm font-bold font-mono ${head}`}>{s.inward.toLocaleString()}</div>
            </div>
            <div>
              <div className={`text-[10px] ${muted}`}>Value</div>
              <div className="text-sm font-bold font-mono text-gold-400">{fmtPaise(s.inward_val)}</div>
            </div>
            <div>
              <div className={`text-[10px] ${muted}`}>Return %</div>
              <div className={`text-sm font-bold font-mono ${s.return_rate > 20 ? 'text-red-400' : 'text-emerald-400'}`}>
                {s.return_rate.toFixed(1)}%
              </div>
            </div>
          </div>
          {s.status !== 'UPCOMING' && (
            <div className="flex gap-1.5 flex-wrap">
              {['NPCI RRF', 'MIS CSV', 'Settlement'].map(label => (
                <button
                  key={label}
                  onClick={() => onDownload(s.id, label)}
                  className={`text-[10px] px-2 py-1 rounded border transition-colors
                    ${isDark ? 'border-white/10 text-slate-400 hover:text-white hover:border-white/25' : 'border-slate-200 text-slate-500 hover:text-slate-800 hover:border-slate-300'}`}
                >
                  ↓ {label}
                </button>
              ))}
            </div>
          )}
        </>
      ) : (
        <div className={`text-[11px] ${muted}`}>Session not yet open</div>
      )}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function CTSOpsDashboard() {
  const { isDark } = useTheme()
  const [downloading, setDownloading] = useState(null)

  const th = {
    page:    isDark ? 'bg-navy-950' : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
    section: isDark ? 'text-slate-300' : 'text-slate-700',
  }

  function handleDownload(sessionId, type) {
    const pathMap = { 'NPCI RRF': 'npci', 'MIS CSV': 'mis', 'Settlement': 'settlement' }
    const path = pathMap[type]
    setDownloading(`${sessionId}-${path}`)
    // In production: call /v1/cts/sessions/{id}/download/{path}
    setTimeout(() => setDownloading(null), 1200)
  }

  const netDir = TODAY.net_settlement_paise >= 0 ? 'RECEIVE' : 'PAY'
  const netColor = netDir === 'RECEIVE' ? 'text-emerald-400' : 'text-red-400'

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page}`}>
        {/* Header */}
        <div className={`sticky top-0 z-10 ${isDark ? 'bg-navy-950/95' : 'bg-slate-50/95'} backdrop-blur border-b ${th.divider} px-6 py-3`}>
          <div className="flex items-center justify-between">
            <div>
              <h1 className={`text-base font-semibold ${th.heading}`}>Clearing Operations Dashboard</h1>
              <p className={`text-[11px] ${th.muted}`}>
                {TODAY.clearing_date} · {TODAY.sessions_count} sessions · {TODAY.sessions_settled} settled
              </p>
            </div>
            <div className="flex items-center gap-2">
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

        <div className="px-6 py-5 space-y-6 max-w-7xl">

          {/* KPI row — today totals */}
          <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
            <KPICard label="Total Inward"      value={TODAY.total_inward.toLocaleString()} sub={fmtPaise(TODAY.total_inward_value_paise)} color={th.heading} isDark={isDark} />
            <KPICard label="STP Confirmed"     value={TODAY.stp_confirmed.toLocaleString()} sub={`${pct(TODAY.stp_confirmed, TODAY.total_inward)}%`} color="text-emerald-400" isDark={isDark} />
            <KPICard label="STP Returned"      value={TODAY.stp_returned.toLocaleString()} sub={`${pct(TODAY.stp_returned, TODAY.total_inward)}%`} color="text-red-400" isDark={isDark} />
            <KPICard label="Manual Confirmed"  value={TODAY.manual_confirmed.toLocaleString()} sub={`${pct(TODAY.manual_confirmed, TODAY.total_inward)}%`} color="text-blue-400" isDark={isDark} />
            <KPICard label="Manual Returned"   value={TODAY.manual_returned.toLocaleString()} sub={`${pct(TODAY.manual_returned, TODAY.total_inward)}%`} color="text-orange-400" isDark={isDark} />
            <KPICard label="Pending Review"    value={TODAY.pending_review} sub="in queue" color="text-amber-400" isDark={isDark} />
            <KPICard label="Total Outward"     value={TODAY.total_outward.toLocaleString()} sub={fmtPaise(TODAY.total_outward_value_paise)} color={th.muted} isDark={isDark} />
            <KPICard label={`Net (${netDir})`} value={fmtPaise(Math.abs(TODAY.net_settlement_paise))} sub="settlement position" color={netColor} isDark={isDark} />
          </div>

          {/* Decision breakdown bar */}
          <div className={`border rounded-xl p-4 ${th.card}`}>
            <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-3`}>Decision Breakdown — Inward</div>
            <DecisionBar
              stp_c={TODAY.stp_confirmed}
              stp_r={TODAY.stp_returned}
              man_c={TODAY.manual_confirmed}
              man_r={TODAY.manual_returned}
              pend={TODAY.pending_review}
              total={TODAY.total_inward}
              isDark={isDark}
            />
            <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t ${th.divider}">
              <div>
                <div className={`text-[10px] ${th.muted}`}>STP Rate</div>
                <div className={`text-lg font-bold font-mono ${TODAY.overall_stp_rate_pct >= 80 ? 'text-emerald-400' : 'text-amber-400'}`}>
                  {TODAY.overall_stp_rate_pct}%
                </div>
              </div>
              <div>
                <div className={`text-[10px] ${th.muted}`}>Return Rate</div>
                <div className={`text-lg font-bold font-mono ${TODAY.overall_return_rate_pct > 22 ? 'text-red-400' : 'text-slate-300'}`}>
                  {TODAY.overall_return_rate_pct}%
                </div>
              </div>
              <div>
                <div className={`text-[10px] ${th.muted}`}>Outward Returns</div>
                <div className="text-lg font-bold font-mono text-orange-400">
                  {TODAY.outward_returned} ({pct(TODAY.outward_returned, TODAY.total_outward)}%)
                </div>
              </div>
            </div>
          </div>

          {/* Sessions grid + trend side by side */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            {/* Sessions */}
            <div className="lg:col-span-2">
              <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-3`}>Today's Sessions</div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {SESSIONS.map(s => (
                  <SessionCard key={s.id} s={s} isDark={isDark} onDownload={handleDownload} />
                ))}
              </div>
            </div>

            {/* 7-day trend */}
            <div className={`border rounded-xl p-4 ${th.card}`}>
              <div className={`text-[11px] font-semibold uppercase tracking-wide ${th.muted} mb-3`}>7-Day Trend</div>
              <TrendBar days={TREND} isDark={isDark} />
              <div className={`mt-4 pt-3 border-t ${th.divider} space-y-2`}>
                {TREND.filter(d => d.inward > 0).slice(-3).reverse().map(d => (
                  <div key={d.date} className="flex items-center justify-between">
                    <span className={`text-[11px] ${th.muted}`}>{d.date}</span>
                    <div className="flex items-center gap-3">
                      <span className={`text-[11px] font-mono ${th.body}`}>{d.inward.toLocaleString()}</span>
                      <span className={`text-[11px] font-mono ${d.return_rate_pct > 20 ? 'text-red-400' : 'text-emerald-400'}`}>
                        {d.return_rate_pct}% ret
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {downloading && (
            <div className="fixed bottom-4 right-4 bg-emerald-500 text-white text-sm px-4 py-2 rounded-lg shadow-lg">
              Downloading...
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
