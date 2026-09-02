import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch all SMB batch ledgers for the SB bank on a given date.
 * Hits GET /v1/cts/smb/ledgers?session_date=YYYY-MM-DD
 *
 * Returns { ledgers, loading, error, refetch }
 *   ledgers: null (pre-load) → SMBLedgerEntry[] on success
 */
export default function useSMBLedgers({ session_date = null, pollEnabled = true } = {}) {
  const [ledgers, setLedgers] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchLedgers = useCallback(async () => {
    const params = new URLSearchParams()
    if (session_date) params.set('session_date', session_date)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/smb/ledgers?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setLedgers(json.ledgers ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [session_date])

  useEffect(() => {
    fetchLedgers()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchLedgers, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchLedgers, pollEnabled])

  return { ledgers, loading, error, refetch: fetchLedgers }
}
