import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 30_000  // 30s — dashboard refreshes frequently during clearing
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** One session summary from GET /v1/cts/sessions/{id}/summary, shaped as the sessions grid's card. */
export function sessionCard(summary) {
  const s = summary.session
  const p = summary.presenting_bank
  return {
    id: s.session_id, slot: s.session_slot, status: s.status,
    inward: p.total_inward, inward_val: p.total_value_paise, stp_rate: p.stp_rate_pct, return_rate: p.return_rate_pct,
  }
}

/** Today's real sessions with their figures; null when the API could not answer (never a made-up list). */
async function fetchSessions() {
  const day = new Date().toLocaleDateString('en-CA')   // YYYY-MM-DD in the browser's local day
  const listRes = await fetch(`${API_BASE}/v1/cts/sessions?clearing_date=${day}`, { credentials: 'include' })
  if (!listRes.ok) return null
  const { sessions = [] } = await listRes.json()
  const summaries = await Promise.all(sessions.map(async (s) => {
    const r = await fetch(`${API_BASE}/v1/cts/sessions/${encodeURIComponent(s.session_id)}/summary`, { credentials: 'include' })
    return r.ok ? sessionCard(await r.json()) : null
  }))
  return summaries.some((c) => c === null) ? null : summaries
}

/**
 * Fetch today's clearing summary + 7-day trend for the Ops Dashboard.
 * Hits GET /v1/cts/dashboard/today and GET /v1/cts/dashboard/trend
 *
 * Returns { today, trend, sessions, loading, error, refetch }
 *   today: null | DashboardTodaySummary
 *   trend: null | DashboardTrendRow[]
 *   sessions: null | session cards (see sessionCard); null when the sessions API failed
 */
export default function useOpsDashboard({ pollEnabled = true } = {}) {
  const [today, setToday] = useState(null)
  const [trend, setTrend] = useState(null)
  const [sessions, setSessions] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchAll = useCallback(async () => {
    try {
      const [todayRes, trendRes, sessionList] = await Promise.all([
        fetch(`${API_BASE}/v1/cts/dashboard/today`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/cts/dashboard/trend?days=7`, { credentials: 'include' }),
        fetchSessions(),
      ])
      setSessions(sessionList)
      if (todayRes.ok) setToday(await todayRes.json())
      if (trendRes.ok) {
        const j = await trendRes.json()
        setTrend(j.trend ?? [])
      }
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAll()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchAll, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchAll, pollEnabled])

  return { today, trend, sessions, loading, error, refetch: fetchAll }
}
