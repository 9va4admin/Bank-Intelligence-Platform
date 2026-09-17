import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 2 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch forwarding log for ALL SMBs under this SB bank.
 * Hits GET /v1/cts/smb/forwarding-log (SB-only endpoint).
 *
 * Returns { items, total, loading, error, refetch }
 */
export default function useSMBForwardingLog({ statusFilter = null, pollEnabled = true } = {}) {
  const [items, setItems] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchLog = useCallback(async () => {
    const params = new URLSearchParams()
    if (statusFilter) params.set('status_filter', statusFilter)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/smb/forwarding-log?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setItems(json.items ?? [])
      setTotal(json.total ?? 0)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    fetchLog()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchLog, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchLog, pollEnabled])

  return { items, total, loading, error, refetch: fetchLog }
}
