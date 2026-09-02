import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch today's clearing sessions from GET /v1/cts/outward/sessions.
 * Returns { sessions, total, loading, error, refetch }
 */
export default function useSessions({ pollEnabled = true } = {}) {
  const [sessions, setSessions] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/cts/outward/sessions`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setSessions(json.sessions ?? [])
      setTotal(json.total ?? 0)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSessions()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchSessions, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchSessions, pollEnabled])

  return { sessions, total, loading, error, refetch: fetchSessions }
}
