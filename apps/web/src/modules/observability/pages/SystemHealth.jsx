/**
 * ASTRA System Health — Redis CTS + YugabyteDB pool status.
 *
 * Access: ops_manager, bank_it_admin.
 * No PII. Degrade gracefully when deps are None.
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
const REFRESH_MS = 60_000

function useSystemHealth(bankId) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)
  const [lastFetch, setLastFetch] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/system`, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
      setLastFetch(new Date())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [bankId])

  useEffect(() => {
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  return { data, loading, error, lastFetch, reload: load }
}

function StatusDot({ ok, isDark }) {
  return (
    <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ok ? 'bg-emerald-400' : 'bg-red-400 animate-pulse'}`} />
  )
}

function HealthCard({ title, children, isDark }) {
  const th = {
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
  }
  return (
    <div className={`rounded-xl border px-6 py-5 ${th.card}`}>
      <h2 className={`text-sm font-semibold mb-4 ${th.heading}`}>{title}</h2>
      {children}
    </div>
  )
}

function Row({ label, value, isDark }) {
  const th = {
    label: isDark ? 'text-slate-400' : 'text-slate-500',
    value: isDark ? 'text-white'     : 'text-slate-900',
  }
  return (
    <div className="flex items-center justify-between py-2">
      <span className={`text-xs ${th.label}`}>{label}</span>
      <span className={`text-sm font-medium tabular-nums ${th.value}`}>{value}</span>
    </div>
  )
}

export default function SystemHealth() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const { data, loading, error, lastFetch, reload } = useSystemHealth(bankId)

  const th = {
    page:    isDark ? 'bg-navy-950'                 : 'bg-slate-50',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    divider: isDark ? 'border-white/8'              : 'border-slate-100',
  }

  const redis = data?.redis_cts ?? { connected: false, hit_rate_pct: 0, degraded: true }
  const yb    = data?.yugabyte  ?? { connected: false, pool_size: 0, active_connections: 0, degraded: true }

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <Link to="/ops/dashboard" className={`text-xs ${th.muted} hover:underline`}>Ops Dashboard</Link>
              <span className={`text-xs ${th.muted}`}>/</span>
              <span className={`text-xs ${th.muted}`}>System Health</span>
            </div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>System Health</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {lastFetch ? `Updated ${lastFetch.toLocaleTimeString()}` : 'Loading…'}&nbsp;·&nbsp;Auto-refresh 60s
            </p>
          </div>
          <button
            onClick={reload}
            disabled={loading}
            className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-opacity disabled:opacity-50
              ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
          >
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>

        {error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

          {/* Redis CTS */}
          <HealthCard title="Redis CTS" isDark={isDark}>
            <div className="flex items-center gap-2 mb-4">
              <StatusDot ok={redis.connected} isDark={isDark} />
              <span className={`text-sm font-medium ${redis.connected
                ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300'     : 'text-red-700')
              }`}>
                {redis.degraded ? 'Degraded / Unreachable' : redis.connected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            {!redis.degraded && (
              <>
                <div className={`border-t ${th.divider} pt-3`}>
                  <Row label="Hit rate" value={`${redis.hit_rate_pct.toFixed(1)}%`} isDark={isDark} />
                </div>
                <div className="mt-2">
                  <div className={`h-2 rounded-full overflow-hidden ${isDark ? 'bg-white/8' : 'bg-slate-100'}`}>
                    <div
                      className={`h-full rounded-full transition-all ${redis.hit_rate_pct >= 95 ? 'bg-emerald-400' : redis.hit_rate_pct >= 80 ? 'bg-amber-400' : 'bg-red-400'}`}
                      style={{ width: `${redis.hit_rate_pct}%` }}
                    />
                  </div>
                  <p className={`text-[10px] mt-1 ${th.muted}`}>Vault hit rate — target: &gt;95%</p>
                </div>
              </>
            )}
          </HealthCard>

          {/* YugabyteDB */}
          <HealthCard title="YugabyteDB (CTS pool)" isDark={isDark}>
            <div className="flex items-center gap-2 mb-4">
              <StatusDot ok={yb.connected} isDark={isDark} />
              <span className={`text-sm font-medium ${yb.connected
                ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                : (isDark ? 'text-red-300'     : 'text-red-700')
              }`}>
                {yb.degraded ? 'Degraded / Unreachable' : yb.connected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
            {!yb.degraded && (
              <div className={`border-t ${th.divider} pt-3`}>
                <Row label="Pool size"    value={yb.pool_size}           isDark={isDark} />
                <Row label="Active conns" value={yb.active_connections}  isDark={isDark} />
                <Row label="Idle conns"   value={Math.max(0, yb.pool_size - yb.active_connections)} isDark={isDark} />
              </div>
            )}
          </HealthCard>

        </div>

        <p className={`text-xs mt-6 ${th.muted}`}>
          OTel instrumentation running in all pods (zero Docker overhead).
          For developer-level distributed traces, install the optional
          <code className="mx-1 px-1.5 py-0.5 rounded text-[10px] bg-white/8">astra-observability</code>
          Helm chart.
        </p>
      </div>
    </AppShell>
  )
}
