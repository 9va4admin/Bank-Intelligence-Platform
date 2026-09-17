import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 2 * 60_000  // vault misses update during clearing hours
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch today's vault miss events.
 * Hits GET /v1/cts/vault/misses?date=YYYY-MM-DD
 *
 * Returns { misses, total, loading, error, refetch }
 */
export default function useVaultMisses({ date = null, pollEnabled = true } = {}) {
  const [misses, setMisses] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchMisses = useCallback(async () => {
    const params = new URLSearchParams()
    if (date) params.set('date', date)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/vault/misses?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setMisses(json.misses ?? [])
      setTotal(json.total_count ?? 0)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [date])

  useEffect(() => {
    fetchMisses()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchMisses, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchMisses, pollEnabled])

  return { misses, total, loading, error, refetch: fetchMisses }
}
