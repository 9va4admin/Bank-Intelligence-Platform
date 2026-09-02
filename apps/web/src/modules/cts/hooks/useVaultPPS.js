import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch PPS vault entries + stop cheque instructions.
 * PPS: GET /v1/cts/vault/pps?status=...
 * Stop cheques: GET /v1/cts/vault/stop-cheques
 *
 * Returns { ppsEntries, stopCheques, loading, error, refetch }
 */
export default function useVaultPPS({ statusFilter = null, pollEnabled = true } = {}) {
  const [ppsEntries, setPpsEntries] = useState(null)
  const [stopCheques, setStopCheques] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchAll = useCallback(async () => {
    const ppsParams = new URLSearchParams()
    if (statusFilter) ppsParams.set('status', statusFilter)
    try {
      const [ppsRes, stopRes] = await Promise.all([
        fetch(`${API_BASE}/v1/cts/vault/pps?${ppsParams}`, { credentials: 'include' }),
        fetch(`${API_BASE}/v1/cts/vault/stop-cheques`, { credentials: 'include' }),
      ])
      if (ppsRes.ok) {
        const j = await ppsRes.json()
        setPpsEntries(j.entries ?? [])
      }
      if (stopRes.ok) {
        const j = await stopRes.json()
        setStopCheques(j.instructions ?? [])
      }
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    fetchAll()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchAll, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchAll, pollEnabled])

  return { ppsEntries, stopCheques, loading, error, refetch: fetchAll }
}
