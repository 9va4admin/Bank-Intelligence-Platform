import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 30_000  // 30s — dashboard refreshes frequently during clearing
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch today's clearing summary + 7-day trend for the Ops Dashboard.
 * Hits GET /v1/cts/dashboard/today and GET /v1/cts/dashboard/trend
 *
 * Returns { today, trend, loading, error, refetch }
 *   today: null | DashboardTodaySummary
 *   trend: null | DashboardTrendRow[]
 */
export default function useOpsDashboard({ pollEnabled = true } = {}) {
  const [today, setToday] = useState(null)
  const [trend, setTrend] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchAll = useCallback(async () => {
    try {
      const [todayRes, trendRes] = await Promise.all([
        fetch(`${API_BASE}/v1/cts/dashboard/today`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/cts/dashboard/trend?days=7`, { credentials: 'include' }),
      ])
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

  return { today, trend, loading, error, refetch: fetchAll }
}
