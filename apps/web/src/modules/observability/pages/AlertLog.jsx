/**
 * ASTRA Alert Log — recent CRITICAL/ERROR events from the audit trail.
 *
 * Last 24 hours, max 50 rows. Bank-scoped. No PII — event_type and severity only.
 * Access: ops_manager, bank_it_admin.
 */
import { useState, useEffect, useCallback } from 'react'
import { Link } from 'react-router-dom'
import { useTheme } from '../../../shared/theme/ThemeContext'
import { useBankContext } from '../../../shared/context/BankContext'
import AppShell from '../../../shared/layout/AppShell'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

function useAlerts(bankId, limit) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/v1/ops/alerts?limit=${limit}`, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      setData(await res.json())
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [bankId, limit])

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}

const SEV_D = {
  CRITICAL: 'bg-red-900/40 text-red-300 border-red-700/40',
  ERROR:    'bg-orange-900/30 text-orange-300 border-orange-700/30',
  WARN:     'bg-amber-900/20 text-amber-300 border-amber-700/30',
  INFO:     'bg-slate-800 text-slate-400 border-white/8',
}
const SEV_L = {
  CRITICAL: 'bg-red-100 text-red-700 border-red-300',
  ERROR:    'bg-orange-50 text-orange-700 border-orange-200',
  WARN:     'bg-amber-50 text-amber-700 border-amber-200',
  INFO:     'bg-slate-50 text-slate-500 border-slate-200',
}

function SevBadge({ sev, isDark }) {
  const cls = (isDark ? SEV_D : SEV_L)[sev] ?? SEV_D.INFO
  return (
    <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full border uppercase ${cls}`}>
      {sev}
    </span>
  )
}

function fmtTime(iso) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-IN', { hour12: false,
      day: '2-digit', month: 'short',
      hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return iso }
}

export default function AlertLog() {
  const { isDark } = useTheme()
  const { bankId } = useBankContext()
  const [limit, setLimit] = useState(25)
  const { data, loading, error, reload } = useAlerts(bankId, limit)

  const th = {
    page:    isDark ? 'bg-navy-950'                 : 'bg-slate-50',
    card:    isDark ? 'bg-navy-900 border-white/8'  : 'bg-white border-slate-200',
    heading: isDark ? 'text-white'                  : 'text-slate-900',
    muted:   isDark ? 'text-slate-400'              : 'text-slate-500',
    row:     isDark ? 'border-white/5 hover:bg-white/2' : 'border-slate-50 hover:bg-slate-50',
    col:     isDark ? 'text-slate-300'              : 'text-slate-700',
    mono:    isDark ? 'text-slate-300 font-mono'    : 'text-slate-700 font-mono',
  }

  const alerts = data?.alerts ?? []
  const total  = data?.total  ?? 0
  const degraded = data?.degraded ?? true

  return (
    <AppShell>
      <div className={`flex-1 overflow-y-auto ${th.page} px-6 py-5`}>
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <div className="flex items-center gap-2 mb-0.5">
              <Link to="/ops/dashboard" className={`text-xs ${th.muted} hover:underline`}>Ops Dashboard</Link>
              <span className={`text-xs ${th.muted}`}>/</span>
              <span className={`text-xs ${th.muted}`}>Alert Log</span>
            </div>
            <h1 className={`text-lg font-semibold ${th.heading}`}>
              Alert Log
              {total > 0 && (
                <span className="ml-2 text-sm font-normal text-red-400">
                  {total} event{total !== 1 ? 's' : ''} (24h)
                </span>
              )}
            </h1>
            <p className={`text-xs mt-0.5 ${th.muted}`}>CRITICAL + ERROR events — last 24 hours — no PII</p>
          </div>
          <div className="flex items-center gap-3">
            <select
              value={limit}
              onChange={e => setLimit(Number(e.target.value))}
              className={`text-xs rounded-lg border px-2.5 py-1.5 bg-transparent
                ${isDark ? 'border-white/12 text-slate-300' : 'border-slate-200 text-slate-700'}`}
            >
              <option value={10}>Last 10</option>
              <option value={25}>Last 25</option>
              <option value={50}>Last 50</option>
            </select>
            <button
              onClick={reload}
              disabled={loading}
              className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-opacity disabled:opacity-50
                ${isDark ? 'border-white/12 text-slate-300 hover:bg-white/5' : 'border-slate-200 text-slate-700 hover:bg-slate-50'}`}
            >
              {loading ? 'Loading…' : 'Refresh'}
            </button>
          </div>
        </div>

        {error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
            {error}
          </div>
        )}

        {degraded && !error && (
          <div className={`text-sm px-4 py-3 rounded-xl mb-4 border
            ${isDark ? 'bg-amber-900/10 border-amber-700/30 text-amber-400' : 'bg-amber-50 border-amber-200 text-amber-700'}`}>
            Audit DB unavailable — alert log cannot be fetched.
          </div>
        )}

        <div className={`rounded-xl border overflow-hidden ${th.card}`}>
          {/* Table header */}
          <div className={`grid grid-cols-12 px-5 py-3 border-b text-[11px] uppercase tracking-widest font-semibold ${th.muted}
            ${isDark ? 'border-white/8' : 'border-slate-100'}`}>
            <span className="col-span-2">Severity</span>
            <span className="col-span-5">Event Type</span>
            <span className="col-span-3">Time</span>
            <span className="col-span-2 text-right">Ack.</span>
          </div>

          {alerts.length === 0 && !loading && (
            <div className={`px-5 py-10 text-center ${th.muted} text-sm`}>
              {degraded ? 'Audit DB unavailable.' : 'No CRITICAL/ERROR events in the last 24 hours.'}
            </div>
          )}

          {alerts.map((a, i) => (
            <div
              key={i}
              className={`grid grid-cols-12 px-5 py-3.5 border-b last:border-0 ${th.row}
                ${isDark ? 'border-white/5' : 'border-slate-50'}`}
            >
              <div className="col-span-2 flex items-center">
                <SevBadge sev={a.severity} isDark={isDark} />
              </div>
              <div className="col-span-5 flex items-center">
                <span className={`text-sm ${th.mono}`}>{a.event_type}</span>
              </div>
              <div className="col-span-3 flex items-center">
                <span className={`text-xs ${th.muted}`}>{fmtTime(a.occurred_at)}</span>
              </div>
              <div className="col-span-2 flex items-center justify-end">
                <span className={`text-xs ${a.acknowledged
                  ? (isDark ? 'text-emerald-400' : 'text-emerald-600')
                  : (isDark ? 'text-slate-500' : 'text-slate-400')
                }`}>
                  {a.acknowledged ? 'Yes' : 'No'}
                </span>
              </div>
            </div>
          ))}
        </div>

        {alerts.length > 0 && total > alerts.length && (
          <p className={`text-xs mt-3 text-center ${th.muted}`}>
            Showing {alerts.length} of {total} events. Increase limit to see more.
          </p>
        )}
      </div>
    </AppShell>
  )
}
