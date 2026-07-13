/**
 * SMBDashboardContent — an SMB's own dashboard (identity, today's stats, IET
 * countdown, recent decisions, quick links).
 *
 * Presentational only (no AppShell, no usePageHeader) so it can be mounted two
 * ways: standalone at /cts/smb/dashboard (CTSSMBDashboard.jsx), and embedded as
 * what "Dashboard" shows for an SMB user (CTSOpsDashboard.jsx) — same content,
 * one source of truth, per the SB/SMB dashboard restructure.
 */
import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'

// ─── Mock data ────────────────────────────────────────────────────────────────

const MOCK_TODAY = {
  clearing_date: '2026-07-05',
  sessions_count: 2,
  sessions_open: 1,
  total_inward: 318,
  stp_confirmed: 224,
  stp_returned: 49,
  pending_review: 4,
  iet_at_risk: 1,
  overall_stp_rate_pct: 85.5,
}

const MOCK_IET_ITEMS = [
  {
    instrument_id: 'CHQ-SMB-001733',
    account_display: '****5509',
    amount_range: '₹[>1Cr]',
    reason: 'HIGH_VALUE_DUAL_APPROVAL',
    iet_deadline: Math.floor(Date.now() / 1000) + 1740, // 29 min
  },
]

const MOCK_RECENT = [
  { instrument_id: 'CHQ-SMB-001847', decision: 'CONFIRMED', filed_by: 'R. Mehta', filed_at: '13:42', amount_range: '₹[1L-5L]', reason: 'SIGNATURE_LOW_CONFIDENCE' },
  { instrument_id: 'CHQ-SMB-001680', decision: 'STP_CONFIRM', filed_by: 'ASTRA Agent', filed_at: '13:38', amount_range: '₹[<1L]', reason: null },
  { instrument_id: 'CHQ-SMB-001641', decision: 'STP_RETURN',  filed_by: 'ASTRA Agent', filed_at: '13:35', amount_range: '₹[1L-5L]', reason: 'STOP_PAYMENT' },
  { instrument_id: 'CHQ-SMB-001580', decision: 'CONFIRMED',   filed_by: 'P. Joshi',  filed_at: '13:22', amount_range: '₹[5L-10L]', reason: 'FRAUD_SCORE_HIGH' },
  { instrument_id: 'CHQ-SMB-001503', decision: 'RETURNED',    filed_by: 'R. Mehta',  filed_at: '13:10', amount_range: '₹[1L-5L]', reason: 'SIGNATURE_MISMATCH' },
]

// ─── Countdown hook ───────────────────────────────────────────────────────────

function useCountdown(deadlineEpoch) {
  const [remaining, setRemaining] = useState(deadlineEpoch - Math.floor(Date.now() / 1000))
  useEffect(() => {
    const id = setInterval(() => setRemaining(deadlineEpoch - Math.floor(Date.now() / 1000)), 1000)
    return () => clearInterval(id)
  }, [deadlineEpoch])
  return remaining
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatCard({ label, value, sub, accent, isDark }) {
  const th = {
    card:  isDark ? 'bg-navy-900 border-white/8'       : 'bg-white border-slate-200',
    label: isDark ? 'text-slate-400'                   : 'text-slate-500',
    value: isDark ? 'text-white'                       : 'text-slate-900',
    sub:   isDark ? 'text-slate-500'                   : 'text-slate-400',
  }
  return (
    <div className={`rounded-xl border p-4 flex flex-col gap-1 ${th.card}`}>
      <span className={`text-xs uppercase tracking-wide font-medium ${th.label}`}>{label}</span>
      <span className={`text-3xl font-bold tabular-nums ${accent || th.value}`}>{value}</span>
      {sub && <span className={`text-xs ${th.sub}`}>{sub}</span>}
    </div>
  )
}

function IETCountdownCard({ item, isDark }) {
  const remaining = useCountdown(item.iet_deadline)
  const mins = Math.floor(Math.max(0, remaining) / 60)
  const secs = Math.max(0, remaining) % 60
  const critical = remaining < 1800  // < 30 min
  const urgent   = remaining < 3600  // < 60 min

  const th = {
    card:     isDark ? 'bg-red-900/20 border-red-700/40'   : 'bg-red-50 border-red-200',
    heading:  isDark ? 'text-red-300'                       : 'text-red-700',
    body:     isDark ? 'text-slate-300'                     : 'text-slate-700',
    meta:     isDark ? 'text-slate-400'                     : 'text-slate-500',
    timer:    critical ? 'text-red-400' : urgent ? 'text-amber-400' : (isDark ? 'text-emerald-400' : 'text-emerald-600'),
  }

  return (
    <div className={`rounded-xl border p-4 flex items-center justify-between gap-4 ${th.card}`}>
      <div className="flex-1 min-w-0">
        <div className={`text-xs font-semibold uppercase tracking-wide mb-1 ${th.heading}`}>IET Countdown</div>
        <div className={`text-sm font-medium ${th.body}`}>{item.instrument_id}</div>
        <div className={`text-xs ${th.meta}`}>{item.amount_range} · {item.reason.replace(/_/g, ' ')}</div>
      </div>
      <div className={`text-3xl font-bold tabular-nums shrink-0 ${th.timer}`}>
        {String(mins).padStart(2, '0')}:{String(secs).padStart(2, '0')}
      </div>
    </div>
  )
}

const DECISION_PILL = {
  CONFIRMED:   { dark: 'bg-emerald-900/40 text-emerald-300 border-emerald-700/40', light: 'bg-emerald-50 text-emerald-700 border-emerald-200', label: 'CONFIRMED' },
  RETURNED:    { dark: 'bg-red-900/40 text-red-300 border-red-700/40',             light: 'bg-red-50 text-red-700 border-red-200',             label: 'RETURNED'  },
  STP_CONFIRM: { dark: 'bg-sky-900/40 text-sky-300 border-sky-700/40',             light: 'bg-sky-50 text-sky-700 border-sky-200',             label: 'STP ✓'     },
  STP_RETURN:  { dark: 'bg-amber-900/40 text-amber-300 border-amber-700/40',       light: 'bg-amber-50 text-amber-700 border-amber-200',       label: 'STP ✗'     },
}

function RecentDecisionsTable({ items, isDark }) {
  const th = {
    header:  isDark ? 'text-slate-500 border-white/8'          : 'text-slate-400 border-slate-200',
    row:     isDark ? 'border-white/5 hover:bg-white/2'        : 'border-slate-100 hover:bg-slate-50',
    cell:    isDark ? 'text-slate-300'                          : 'text-slate-700',
    id:      isDark ? 'text-white font-medium'                  : 'text-slate-900 font-medium',
    meta:    isDark ? 'text-slate-500'                          : 'text-slate-400',
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className={`text-xs uppercase tracking-wide border-b ${th.header}`}>
            <th className="text-left py-2 pr-4 font-medium">Instrument</th>
            <th className="text-left py-2 pr-4 font-medium">Amount</th>
            <th className="text-left py-2 pr-4 font-medium">Decision</th>
            <th className="text-left py-2 pr-4 font-medium">Filed by</th>
            <th className="text-left py-2 font-medium">Time</th>
          </tr>
        </thead>
        <tbody>
          {items.map(row => {
            const pill = DECISION_PILL[row.decision] || DECISION_PILL.CONFIRMED
            return (
              <tr key={row.instrument_id} className={`border-b ${th.row}`}>
                <td className={`py-2.5 pr-4 ${th.id}`}>{row.instrument_id}</td>
                <td className={`py-2.5 pr-4 tabular-nums ${th.cell}`}>{row.amount_range}</td>
                <td className="py-2.5 pr-4">
                  <span className={`inline-block text-xs px-2 py-0.5 rounded border font-medium ${isDark ? pill.dark : pill.light}`}>
                    {pill.label}
                  </span>
                </td>
                <td className={`py-2.5 pr-4 ${th.cell}`}>{row.filed_by}</td>
                <td className={`py-2.5 tabular-nums ${th.meta}`}>{row.filed_at}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function QuickLink({ to, label, icon, isDark }) {
  const th = {
    btn: isDark
      ? 'bg-white/5 hover:bg-white/10 border-white/8 text-slate-300 hover:text-white'
      : 'bg-white hover:bg-slate-50 border-slate-200 text-slate-600 hover:text-slate-900',
  }
  return (
    <Link
      to={to}
      className={`flex items-center gap-2 px-4 py-2.5 rounded-lg border text-sm font-medium transition-colors ${th.btn}`}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </Link>
  )
}

// ─── Main content ───────────────────────────────────────────────────────────

export default function SMBDashboardContent() {
  const { bankName, bankIfsc, bankId, sponsorBankId } = useBankContext()
  const { isDark } = useTheme()

  const th = {
    card:     isDark ? 'bg-navy-900 border-white/8'             : 'bg-white border-slate-200',
    heading:  isDark ? 'text-white'                             : 'text-slate-900',
    muted:    isDark ? 'text-slate-400'                         : 'text-slate-500',
    divider:  isDark ? 'border-white/8'                         : 'border-slate-200',
    banner:   isDark ? 'bg-violet-900/25 border-violet-700/40'  : 'bg-violet-50 border-violet-200',
    bannerHd: isDark ? 'text-violet-300'                        : 'text-violet-700',
    bannerMt: isDark ? 'text-violet-400/80'                     : 'text-violet-500',
  }

  const initials = (bankName || 'SMB').split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()
  const today = MOCK_TODAY
  const stpRateColor = today.overall_stp_rate_pct >= 90
    ? (isDark ? 'text-emerald-400' : 'text-emerald-600')
    : today.overall_stp_rate_pct >= 80
      ? (isDark ? 'text-amber-400' : 'text-amber-600')
      : (isDark ? 'text-red-400'   : 'text-red-600')

  return (
    <div className="space-y-5">
      {/* SMB Identity Banner */}
      <div className={`rounded-xl border px-5 py-4 flex items-center gap-4 ${th.banner}`}>
        <div className="w-12 h-12 rounded-full bg-violet-600 flex items-center justify-center text-white font-bold text-sm shrink-0">
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <div className={`text-base font-semibold ${th.bannerHd}`}>{bankName || 'Sub-Member Bank'}</div>
          <div className={`text-xs ${th.bannerMt}`}>
            IFSC: {bankIfsc || bankId?.toUpperCase()} · Sponsor: {sponsorBankId || 'Saraswat Co-op Bank'} · Zone: MUMBAI
          </div>
        </div>
        <div className={`text-xs px-2.5 py-1 rounded-full border font-medium ${th.bannerHd} ${isDark ? 'border-violet-700/40 bg-violet-900/30' : 'border-violet-300 bg-violet-100'}`}>
          SMB
        </div>
      </div>

      {/* Today's Stats */}
      <section>
        <h2 className={`text-xs font-semibold uppercase tracking-widest mb-3 ${th.muted}`}>Today · {today.clearing_date}</h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <StatCard label="Total Inward" value={today.total_inward.toLocaleString()} sub={`${today.sessions_count} sessions, ${today.sessions_open} open`} isDark={isDark} />
          <StatCard label="STP Confirmed" value={today.stp_confirmed.toLocaleString()} sub={`${today.overall_stp_rate_pct}% STP rate`} accent={stpRateColor} isDark={isDark} />
          <StatCard
            label="Pending Review"
            value={today.pending_review}
            sub="In human review queue"
            accent={today.pending_review > 0 ? (isDark ? 'text-amber-400' : 'text-amber-600') : undefined}
            isDark={isDark}
          />
          <StatCard
            label="IET At-Risk"
            value={today.iet_at_risk}
            sub="Items within 60-min IET window"
            accent={today.iet_at_risk > 0 ? (isDark ? 'text-red-400' : 'text-red-600') : undefined}
            isDark={isDark}
          />
        </div>
      </section>

      {/* IET Countdown (only shown when items at-risk) */}
      {MOCK_IET_ITEMS.length > 0 && (
        <section>
          <h2 className={`text-xs font-semibold uppercase tracking-widest mb-3 ${th.muted}`}>IET Countdown</h2>
          <div className="space-y-2">
            {MOCK_IET_ITEMS.map(item => (
              <IETCountdownCard key={item.instrument_id} item={item} isDark={isDark} />
            ))}
          </div>
        </section>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
        {/* Recent Decisions */}
        <div className={`lg:col-span-2 rounded-xl border p-5 ${th.card}`}>
          <div className="flex items-center justify-between mb-4">
            <h2 className={`text-sm font-semibold ${th.heading}`}>Recent Decisions</h2>
            <Link to="/cts/decisions" className={`text-xs ${th.muted} hover:underline`}>View all →</Link>
          </div>
          <RecentDecisionsTable items={MOCK_RECENT} isDark={isDark} />
        </div>

        {/* Quick Actions */}
        <div className={`rounded-xl border p-5 ${th.card}`}>
          <h2 className={`text-sm font-semibold mb-4 ${th.heading}`}>Quick Actions</h2>
          <div className="flex flex-col gap-2">
            <QuickLink to="/cts/smb/review-queue" label="Review Queue" icon="📋" isDark={isDark} />
            <QuickLink to="/cts/inward-pipeline" label="Inward Pipeline" icon="🔄" isDark={isDark} />
            <QuickLink to="/cts/settlement" label="Settlement" icon="🏦" isDark={isDark} />
            <QuickLink to="/cts/decisions" label="Decision Log" icon="📊" isDark={isDark} />
            <QuickLink to="/cts/vault" label="Signature Vault" icon="🔐" isDark={isDark} />
          </div>

          <div className={`mt-5 pt-4 border-t ${th.divider}`}>
            <div className={`text-xs font-semibold uppercase tracking-wide mb-2 ${th.muted}`}>Today's Return Rate</div>
            <div className="flex items-center gap-2">
              <div className="flex-1 bg-white/5 rounded-full h-2 overflow-hidden">
                <div
                  className="h-full bg-red-500 rounded-full"
                  style={{ width: `${((today.stp_returned) / today.total_inward * 100).toFixed(1)}%` }}
                />
              </div>
              <span className={`text-sm font-semibold tabular-nums ${isDark ? 'text-red-400' : 'text-red-600'}`}>
                {((today.stp_returned / today.total_inward) * 100).toFixed(1)}%
              </span>
            </div>
            <div className={`text-xs mt-1 ${th.muted}`}>{today.stp_returned} returns out of {today.total_inward}</div>
          </div>
        </div>
      </div>
    </div>
  )
}
