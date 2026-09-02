import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch reconciliation sessions + discrepancies for a bank/date.
 * Hits GET /v1/cts/outward/reconciliation?recon_date=YYYY-MM-DD
 *
 * Returns { data, loading, error, refetch }
 *   data: null (pre-load) → { bank_id, recon_date, sessions[], discrepancies[] }
 */
export default function useReconciliation({ recon_date = null, pollEnabled = true } = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchData = useCallback(async () => {
    const params = new URLSearchParams()
    if (recon_date) params.set('recon_date', recon_date)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/outward/reconciliation?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [recon_date])

  useEffect(() => {
    fetchData()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchData, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchData, pollEnabled])

  return { data, loading, error, refetch: fetchData }
}
