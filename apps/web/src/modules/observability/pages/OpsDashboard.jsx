/**
 * ASTRA Ops Dashboard — replaces Grafana dashboards for bank operators.
 *
 * Shows: IET risk (near-breach cheques), human review queue depth,
 * quick-links to model health, alert log, system health.
 * Auto-refreshes every 30 seconds.
 *
 * Access: ops_manager, bank_it_admin.
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'
const REFRESH_MS = 30_000

function useOpsDashboard(bankId) {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState(null)
  const [lastFetch, setLastFetch] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/dashboard`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
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

function MetricCard({ label, value, sub, alert, isDark }) {
  const th = {
    card:  isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    label: isDark ? 'text-slate-400'              : 'text-slate-500',
    value: isDark ? 'text-white'                  : 'text-slate-900',
    sub:   isDark ? 'text-slate-500'              : 'text-slate-400',
  }
  const alertRing = alert === 'critical'
    ? 'ring-2 ring-red-500/50'
    : alert === 'warn'
    ? 'ring-2 ring-amber-500/40'
    : ''

  return (
    <div className={`rounded-xl border px-5 py-4 ${th.card} ${alertRing}`}>
      <p className={`text-[11px] uppercase tracking-widest font-semibold mb-2 ${th.label}`}>{label}</p>
      <p className={`text-3xl font-bold tabular-nums ${th.value}`}>{value}</p>
      {sub && <p className={`text-xs mt-1 ${th.sub}`}>{sub}</p>}
    </div>
  )
}

function IETRiskBanner({ panel, isDark }) {
  if (!panel || panel.near_breach_count === 0) return null
  return (
    <div className={`flex items-center gap-3 px-4 py-3 rounded-xl mb-4 border
      ${isDark ? 'bg-red-900/20 border-red-700/40' : 'bg-red-50 border-red-200'}`}>
      <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse flex-shrink-0" />
      <p className={`text-sm font-semibold ${isDark ? 'text-red-300' : 'text-red-700'}`}>
        IET Alert: {panel.near_breach_count} cheque{panel.near_breach_count !== 1 ? 's' : ''} within 30 seconds of IET deadline
      </p>
    </div>
  )
}

export default function OpsDashboard() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const { data, loading, error, lastFetch, reload } = useOpsDashboard(bankId)

  const th = {
    page:    isDark ? 'bg-navy-950'           : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'            : 'text-slate-900',
    body:    isDark ? 'text-slate-300'        : 'text-slate-700',
    muted:   isDark ? 'text-slate-400'        : 'text-slate-500',
    divider: isDark ? 'border-white/8'        : 'border-slate-200',
  }

  const iet  = data?.iet_risk    ?? { near_breach_count: 0, in_processing_count: 0, degraded: true }
  const hr   = data?.human_review ?? { queue_depth: 0, avg_wait_minutes: 0, degraded: true }
  const deg  = data?.degraded ?? true

  const ietAlert = iet.near_breach_count > 0 ? 'critical' : undefined

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>ASTRA Ops Dashboard</h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>
              {lastFetch ? `Updated ${lastFetch.toLocaleTimeString()}` : 'Loading…'}&nbsp;·&nbsp;Auto-refresh 30s
            </p>
          </div>
          <div className="flex items-center gap-3">
            {deg && (
              <span className={`text-[11px] px-2.5 py-1 rounded-full border font-medium
                ${isDark ? 'bg-amber-900/20 border-amber-700/40 text-amber-300' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
                Degraded
              </span>
            )}
            <button
              onClick={reload}
              disabled={loading}
              className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-opacity disabled:opacity-50
                ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
            >
              {loading ? 'Refreshing…' : 'Refresh'}
            </button>
          </div>
        </div>

        {/* IET risk banner */}
        <IETRiskBanner panel={iet} isDark={isDark} />

        {/* Error banner */}
        {error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
            Could not reach API: {error}. Showing last known state.
          </div>
        )}

        {/* KPI grid */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <MetricCard
            label="IET Near-Breach"
            value={iet.near_breach_count}
            sub="cheques within 30s of deadline"
            alert={ietAlert}
            isDark={isDark}
          />
          <MetricCard
            label="In Processing"
            value={iet.in_processing_count}
            sub="cheques active now"
            isDark={isDark}
          />
          <MetricCard
            label="Review Queue"
            value={hr.queue_depth}
            sub="awaiting ops_reviewer"
            isDark={isDark}
          />
          <MetricCard
            label="Avg Wait"
            value={hr.avg_wait_minutes > 0 ? `${hr.avg_wait_minutes.toFixed(1)} min` : '—'}
            sub="time in human review"
            alert={hr.avg_wait_minutes > 45 ? 'warn' : undefined}
            isDark={isDark}
          />
        </div>

        {/* Quick-nav cards */}
        <p className={`text-[11px] uppercase tracking-widest font-semibold mb-3 ${th.muted}`}>Platform Health</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { to: '/ops/model-health', title: 'Model Health',   desc: 'OCR + fraud score drift over 7 days',          icon: '🤖' },
            { to: '/ops/alerts',       title: 'Alert Log',      desc: 'Recent CRITICAL/ERROR events (last 24h)',       icon: '🔔' },
            { to: '/ops/system',       title: 'System Health',  desc: 'Redis, YugabyteDB, Vault connectivity',        icon: '🖥️' },
          ].map(({ to, title, desc, icon }) => (
            <Link
              key={to}
              to={to}
              className={`block rounded-xl border px-5 py-4 transition-colors hover:border-violet-500/40
                ${th.card}`}
            >
              <p className="text-xl mb-2">{icon}</p>
              <p className={`font-semibold text-sm mb-1 ${th.heading}`}>{title}</p>
              <p className={`text-xs ${th.muted}`}>{desc}</p>
            </Link>
          ))}
        </div>
      </div>
    </AppShell>
  )
}
