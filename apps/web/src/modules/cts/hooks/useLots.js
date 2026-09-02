import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 2 * 60_000  // lots change frequently during clearing
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch all scanning lots for the bank on a given clearing date.
 * Hits GET /v1/cts/outward/lots?clearing_date=YYYY-MM-DD
 *
 * Returns { lots, loading, error, refetch }
 *   lots: null (pre-load) → LotSummaryRow[] on success
 */
export default function useLots({ clearing_date = null, pollEnabled = true } = {}) {
  const [lots, setLots] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchLots = useCallback(async () => {
    const params = new URLSearchParams()
    if (clearing_date) params.set('clearing_date', clearing_date)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/outward/lots?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setLots(json.lots ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [clearing_date])

  useEffect(() => {
    fetchLots()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchLots, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchLots, pollEnabled])

  return { lots, loading, error, refetch: fetchLots }
}
