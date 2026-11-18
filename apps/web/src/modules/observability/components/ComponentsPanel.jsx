/**
 * Platform components: what the infrastructure health monitor knows about each dependency (database, Redis, Kafka, Temporal, MinIO, Immudb,
 * Vault, the AI services, CBS, NGCH ...): state, latency, since when, and the last error. Also says when the monitor itself has stopped, so a
 * frozen list is never read as "all fine".
 */
import { useState, useEffect, useCallback } from 'react'
import { msg } from '../../../shared/messages'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const REFRESH_MS = 30_000

function useComponents(enabled) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/ops/components`, { credentials: 'include' })
      if (!res.ok) throw new Error(msg('UI_COMMON_HTTP', { status: res.status }))
      setData(await res.json())
      setError(null)
    } catch (e) {
      setError(e.message)
    }
  }, [])
  useEffect(() => {
    if (!enabled) return undefined
    load()
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load, enabled])
  return { data, error }
}

const BADGE = {
  OK: 'bg-emerald-500/15 text-emerald-500 border-emerald-500/30',
  SLOW: 'bg-amber-500/15 text-amber-500 border-amber-500/30',
  DOWN: 'bg-red-500/15 text-red-500 border-red-500/30',
  UNKNOWN: 'bg-slate-500/15 text-slate-400 border-slate-500/30',
}
const LABEL = {
  OK: () => msg('UI_COMPONENTS_STATUS_OK'),
  SLOW: () => msg('UI_COMPONENTS_STATUS_SLOW'),
  DOWN: () => msg('UI_COMPONENTS_STATUS_DOWN'),
  UNKNOWN: () => msg('UI_COMPONENTS_STATUS_UNKNOWN'),
}

function ago(epoch) {
  if (!epoch) return ''
  const s = Math.max(0, Math.round(Date.now() / 1000 - epoch))
  if (s < 90) return `${s}s`
  const m = Math.round(s / 60)
  return m < 90 ? `${m}m` : `${Math.floor(m / 60)}h ${m % 60}m`
}

export default function ComponentsPanel({ isDark, enabled = true }) {
  const { data, error } = useComponents(enabled)
  const th = {
    card: isDark ? 'bg-navy-900 border-white/8' : 'bg-white border-slate-200',
    heading: isDark ? 'text-white' : 'text-slate-900',
    muted: isDark ? 'text-slate-400' : 'text-slate-500',
    row: isDark ? 'border-white/5' : 'border-slate-100',
  }

  let banner = null
  if (error) banner = error
  else if (data?.monitor === 'NOT_RUNNING') banner = msg('UI_COMPONENTS_MONITOR_NOT_RUNNING')
  else if (data?.monitor === 'UNAVAILABLE') banner = msg('UI_COMPONENTS_MONITOR_UNAVAILABLE')
  else if (data?.monitor === 'STALE') banner = msg('UI_COMPONENTS_MONITOR_STALE', { minutes: Math.round((data.last_tick_age_seconds ?? 0) / 60) })

  const components = data?.components ?? []
  return (
    <div className={`rounded-xl border px-5 py-4 mb-5 ${th.card}`}>
      <h2 className={`text-sm font-semibold mb-3 ${th.heading}`}>{msg('UI_COMPONENTS_TITLE')}</h2>
      {banner && (
        <div role="alert" className={`text-xs px-3 py-2 rounded-lg mb-3 border ${isDark ? 'bg-red-900/10 border-red-700/30 text-red-400' : 'bg-red-50 border-red-200 text-red-700'}`}>
          {banner}
        </div>
      )}
      {!banner && data && components.length === 0 && (
        <p className={`text-xs ${th.muted}`}>{msg('UI_COMPONENTS_EMPTY')}</p>
      )}
      {components.length > 0 && (
        <table className="w-full text-xs">
          <thead>
            <tr className={`text-left ${th.muted}`}>
              <th className="pb-2 font-medium">{msg('UI_COMPONENTS_COL_COMPONENT')}</th>
              <th className="pb-2 font-medium">{msg('UI_COMPONENTS_COL_STATUS')}</th>
              <th className="pb-2 font-medium">{msg('UI_COMPONENTS_COL_LATENCY')}</th>
              <th className="pb-2 font-medium">{msg('UI_COMPONENTS_COL_SINCE')}</th>
              <th className="pb-2 font-medium">{msg('UI_COMPONENTS_COL_ERROR')}</th>
            </tr>
          </thead>
          <tbody>
            {components.map((c) => (
              <tr key={c.component} className={`border-t ${th.row}`}>
                <td className={`py-1.5 font-mono ${th.heading}`} data-testid="component-name">{c.component}</td>
                <td className="py-1.5">
                  <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${BADGE[c.status] ?? BADGE.UNKNOWN}`}>
                    {(LABEL[c.status] ?? LABEL.UNKNOWN)()}
                  </span>
                </td>
                <td className={`py-1.5 tabular-nums ${th.muted}`}>{c.latency_ms != null ? msg('UI_COMPONENTS_LATENCY_MS', { value: c.latency_ms >= 100 ? Math.round(c.latency_ms) : Math.round(c.latency_ms * 10) / 10 }) : ''}</td>
                <td className={`py-1.5 ${th.muted}`}>{ago(c.since)}</td>
                <td className="py-1.5 text-red-400 break-all">{c.last_error ?? ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
