import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 30_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch recent outward decisions from GET /v1/cts/outward/decisions
 * Optional outcome filter (comma-separated, e.g. 'STP_CONFIRM,STP_RETURN').
 *
 * Returns { decisions, loading, error, refetch }
 *   decisions: [] until loaded → OutwardDecisionItem[] on success
 */
export default function useOutwardDecisions({ outcome = null, limit = 100, pollEnabled = true } = {}) {
  const [decisions, setDecisions] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchDecisions = useCallback(async () => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (outcome) params.set('outcome', outcome)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/outward/decisions?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setDecisions(json.items ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [outcome, limit])

  useEffect(() => {
    // pollEnabled must gate the INITIAL fetch too, not just the recurring interval below —
    // otherwise a demo-mode caller (pollEnabled: false) still gets one real fetch on mount,
    // which overwrites curated demo data with live (and here, incompletely-mapped) rows.
    if (!pollEnabled) {
      setLoading(false)
      return
    }
    fetchDecisions()
    timerRef.current = setInterval(fetchDecisions, POLL_INTERVAL_MS)
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchDecisions, pollEnabled])

  return { decisions, loading, error, refetch: fetchDecisions }
}
