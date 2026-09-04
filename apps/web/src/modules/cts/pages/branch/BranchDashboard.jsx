/**
 * Branch Portal — Dashboard (/branch)
 *
 * Accessed by branch operators at the physical scanning workstation.
 * Shows: active session status, today's counts, current lot, rate indicator,
 * and connection health to the EEH gateway.
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../../shared/context/BankContext'
import AppShell from '../../../../shared/layout/AppShell'

// ─── Mock state (replaced by SSE + REST hooks in production) ─────────────────
// Set SESSION_MOCK to null to simulate the no-session / pre-first-scan state.

const SESSION_MOCK = {
  session_id: 'sess-branch-01-2026-07-04',
  branch_id: 'BRANCH-ANDHERI-01',
  branch_name: 'Andheri (W) Branch',
  operator_id: 'AUTO_FIRST_SCAN',
  hub_type: 'EEH',
  clearing_date: '2026-07-04',
  status: 'ACTIVE',
  session_opened_at: '2026-07-04T09:14:32Z',   // auto-opened on first scan
  total_uploaded: 247,
  total_accepted: 241,
  total_rejected: 4,
  total_held: 2,
  current_lot_id: 'LOT-BRANCH01-0007',
  lot_instrument_count: 18,
  lot_target: 25,
}

const EEH_HEALTH = { status: 'CONNECTED', latency_ms: 12, last_ping: '2026-07-04T10:43:55Z' }

function StatusDot({ status }) {
  const cls = status === 'CONNECTED' || status === 'ACTIVE'
    ? 'bg-emerald-400'
    : status === 'WARN' ? 'bg-amber-400' : 'bg-red-400'
  return <span className={`inline-block w-2 h-2 rounded-full ${cls} mr-1.5`} />
}

// Scanner agent state dot — three states only.
function ScannerDot({ state }) {
  const cls =
    state === 'ACTIVE'  ? 'bg-emerald-400' :
    state === 'OFFLINE' ? 'bg-red-400' :
                          'bg-slate-500'   // IDLE or unknown
  return <span className={`inline-block w-2 h-2 rounded-full ${cls} mr-1.5`} />
}

function scannerLabel(state, secondsAgo) {
  if (state === 'ACTIVE')  return 'Scanning'
  if (state === 'OFFLINE') return 'OFFLINE'
  if (state === 'IDLE' && secondsAgo != null) return `Idle · ${secondsAgo}s ago`
  return 'Idle'
}

function StatCard({ label, value, sub, accent, isDark }) {
  const th = {
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    label: isDark ? 'text-slate-400' : 'text-slate-500',
    value: isDark ? 'text-white' : 'text-slate-900',
    sub: isDark ? 'text-slate-500' : 'text-slate-400',
  }
  return (
    <div className={`rounded-lg border p-4 ${th.card}`}>
      <p className={`text-xs font-medium uppercase tracking-wider ${th.label}`}>{label}</p>
      <p className={`mt-1 text-2xl font-bold tabular-nums ${accent || th.value}`}>{value}</p>
      {sub && <p className={`mt-0.5 text-xs ${th.sub}`}>{sub}</p>}
    </div>
  )
}

function LotProgress({ filled, target, isDark }) {
  const pct = Math.min(100, Math.round((filled / target) * 100))
  const bar = isDark ? 'bg-white/10' : 'bg-slate-100'
  const fill = pct >= 90 ? 'bg-emerald-500' : 'bg-blue-500'
  return (
    <div className="mt-2">
      <div className={`h-2 rounded-full overflow-hidden ${bar}`}>
        <div className={`h-full rounded-full transition-all ${fill}`} style={{ width: `${pct}%` }} />
      </div>
      <p className={`mt-1 text-xs ${isDark ? 'text-slate-400' : 'text-slate-500'}`}>
        {filled} / {target} instruments — {pct}% full
      </p>
    </div>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function BranchDashboard() {
  const { isDark } = useTheme()
  const { bankId, bankName, isDemo } = useBankContext()

  const { data: sessionData } = useQuery({
    queryKey: ['branch-session', bankId],
    queryFn: async () => {
      const res = await fetch(`/v1/cts/branch/session?bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) return null
      return res.json()
    },
    enabled: !isDemo,
    refetchInterval: isDemo ? false : 15_000,
    retry: false,
  })
  const session = isDemo || !sessionData ? SESSION_MOCK : sessionData

  const { data: eehData } = useQuery({
    queryKey: ['eeh-health', bankId],
    queryFn: async () => {
      const res = await fetch(`/v1/cts/branch/eeh-health?bank_id=${bankId}`, { credentials: 'include' })
      if (!res.ok) return null
      return res.json()
    },
    enabled: !isDemo,
    refetchInterval: isDemo ? false : 15_000,
    retry: false,
  })
  const eehHealth = isDemo || !eehData ? EEH_HEALTH : eehData
  const [elapsed, setElapsed] = useState(0)

  const branchId = session?.branch_id ?? ''
  const { data: scannerStatus } = useQuery({
    queryKey: ['scanner-agent-status', bankId, branchId],
    queryFn: async () => {
      const res = await fetch(`/v1/cts/scanner/agent/status?branch_id=${encodeURIComponent(branchId)}`)
      if (!res.ok) return null
      return res.json()
    },
    refetchInterval: 15_000,
    enabled: !!branchId,
  })

  useEffect(() => {
    const t = setInterval(() => setElapsed(e => e + 1), 1000)
    return () => clearInterval(t)
  }, [])

  const hasSession = session !== null && session.status === 'ACTIVE'
  const rejectRate = hasSession && session.total_uploaded > 0
    ? ((session.total_rejected / session.total_uploaded) * 100).toFixed(1)
    : '0.0'

  const th = {
    page:    isDark ? 'bg-navy-950'  : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'   : 'text-slate-900',
    body:    isDark ? 'text-slate-300' : 'text-slate-700',
    muted:   isDark ? 'text-slate-400' : 'text-slate-500',
    divider: isDark ? 'border-white/8' : 'border-slate-200',
  }

  const branchLabel = hasSession ? `${session.branch_name} · ${session.clearing_date}` : 'Branch Portal'

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>

        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>Branch Portal</h1>
            <p className={`text-sm ${th.muted}`}>{branchLabel}</p>
          </div>
          <div className={`flex items-center gap-3 text-sm ${th.muted}`}>
            <span className="flex items-center">
              <StatusDot status={eehHealth.status} />
              EEH {eehHealth.status} · {eehHealth.latency_ms}ms
            </span>
            <span className={`flex items-center ${scannerStatus?.state === 'OFFLINE' ? 'text-red-400' : ''}`}>
              <ScannerDot state={scannerStatus?.state} />
              Scanner · {scannerLabel(scannerStatus?.state, scannerStatus?.last_seen_seconds_ago)}
            </span>
            <Link
              to="/branch/scan"
              className="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-medium rounded-md transition-colors"
            >
              Open Scanner
            </Link>
          </div>
        </div>

        {/* No-session state — shown before first cheque is scanned */}
        {!hasSession && (
          <div className={`rounded-lg border px-5 py-8 mb-5 ${th.card} text-center`}>
            <div className="text-3xl mb-3">📡</div>
            <p className={`text-sm font-semibold ${th.heading} mb-1`}>Waiting for first scan</p>
            <p className={`text-xs ${th.muted}`}>
              Scan your first cheque to automatically start today's clearing session.
              No manual action needed.
            </p>
            <p className={`text-xs mt-3 ${th.muted}`}>
              EEH is <span className="text-emerald-400 font-medium">{eehHealth.status}</span> · {eehHealth.latency_ms}ms
            </p>
          </div>
        )}

        {/* Session status bar — shown only when session is active */}
        {hasSession && (
          <div className={`rounded-lg border px-4 py-3 mb-5 ${th.card} flex items-center justify-between`}>
            <div className="flex items-center gap-4">
              <span className="flex items-center text-sm font-medium">
                <StatusDot status="ACTIVE" />
                <span className={th.heading}>Session Active</span>
              </span>
              <span className={`text-xs ${th.muted}`}>ID: {session.session_id.slice(-8)}</span>
              <span className={`text-xs ${th.muted}`}>Hub: {session.hub_type}</span>
              {session.session_opened_at && (
                <span className={`text-xs ${th.muted}`}>
                  Started {session.session_opened_at.slice(11, 16)} · auto
                </span>
              )}
            </div>
            <span className={`text-xs ${th.muted}`}>
              Closes at clearing window end
            </span>
          </div>
        )}

        {/* Stat cards — shown only when session is active */}
        {hasSession && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
            <StatCard label="Uploaded" value={session.total_uploaded} sub="today" isDark={isDark} />
            <StatCard label="Accepted" value={session.total_accepted}
              accent="text-emerald-400"
              sub={session.total_uploaded > 0 ? `${((session.total_accepted / session.total_uploaded) * 100).toFixed(1)}%` : '—'}
              isDark={isDark} />
            <StatCard label="Rejected" value={session.total_rejected}
              accent={session.total_rejected > 0 ? 'text-red-400' : undefined}
              sub={`${rejectRate}% reject rate`} isDark={isDark} />
            <StatCard label="On Hold" value={session.total_held}
              accent={session.total_held > 0 ? 'text-amber-400' : undefined}
              sub="pending review" isDark={isDark} />
          </div>
        )}

        {/* Current lot — shown only when session is active */}
        {hasSession && (
          <div className={`rounded-lg border p-4 mb-5 ${th.card}`}>
            <div className="flex items-center justify-between mb-2">
              <h2 className={`text-sm font-semibold ${th.heading}`}>Current Lot</h2>
              <span className={`text-xs font-mono ${th.muted}`}>{session.current_lot_id}</span>
            </div>
            <LotProgress filled={session.lot_instrument_count} target={session.lot_target} isDark={isDark} />
            <div className="mt-3 flex gap-2">
              <button className={`text-xs px-3 py-1.5 border rounded ${th.divider} ${th.muted} transition-colors hover:text-white`}>
                View Lot Detail
              </button>
            </div>
          </div>
        )}

        {/* Quick links */}
        <div className="grid grid-cols-2 gap-3">
          <Link to="/branch/scan" className={`rounded-lg border p-4 ${th.card} hover:border-blue-500/50 transition-colors group`}>
            <p className={`text-sm font-medium ${th.heading} group-hover:text-blue-400`}>Scanner Monitor</p>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Live cheque upload feed + per-item status</p>
          </Link>
          <Link to="/branch/mismatch" className={`rounded-lg border p-4 ${th.card} hover:border-amber-500/50 transition-colors group`}>
            <p className={`text-sm font-medium ${th.heading} group-hover:text-amber-400`}>
              Mismatch Queue
              {hasSession && session.total_held > 0 && (
                <span className="ml-2 text-xs bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded px-1.5 py-0.5">
                  {session.total_held}
                </span>
              )}
            </p>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Resolve held items</p>
          </Link>
          <Link to="/branch/history" className={`rounded-lg border p-4 ${th.card} hover:border-slate-500/50 transition-colors group`}>
            <p className={`text-sm font-medium ${th.heading} group-hover:text-slate-300`}>Session History</p>
            <p className={`text-xs mt-0.5 ${th.muted}`}>Past sessions, lots, and downloads</p>
          </Link>
          <div className={`rounded-lg border p-4 ${th.card}`}>
            <p className={`text-sm font-medium ${th.heading}`}>EEH Status</p>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {eehHealth.status} · {eehHealth.latency_ms}ms · Last ping {eehHealth.last_ping?.slice(11, 16) ?? '—'}
            </p>
          </div>
        </div>

      </div>
    </AppShell>
  )
}
