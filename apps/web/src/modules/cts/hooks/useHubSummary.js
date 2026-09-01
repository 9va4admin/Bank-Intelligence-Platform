/**
 * useHubSummary — fetches GET /v1/cts/outward/hub-summary for CTSHubDashboard
 * in POC/PROD mode.
 *
 * Returns per-branch session stats from cts.eeh_sessions + cts.scanner_registrations.
 * Demo-only fields (current_lot, lots_sealed_today, total_held, eeh_latency_ms)
 * are absent — the hub dashboard guards them with optional-chaining and ?? 0.
 *
 * Polls every 30 seconds (hub data is less volatile than the inward queue).
 *
 * Returns: { branches, totalBranches, activeSessions, clearingDate, loading, error, refetch }
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 30_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Map one API branch row to the shape CTSHubDashboard expects.
 * The API omits demo-only fields; supply safe defaults so existing JSX doesn't break.
 */
function normaliseBranch(raw) {
  return {
    branch_id:        raw.branch_id,
    branch_name:      raw.branch_name,
    branch_ifsc:      raw.branch_ifsc,
    hub_type:         raw.hub_type ?? 'EEH',
    // eeh_status derived from scanner_health — hub dashboard uses this for the status chip
    eeh_status:       raw.scanner_health === 'HEALTHY'  ? 'CONNECTED'
                    : raw.scanner_health === 'DEGRADED' ? 'DEGRADED'
                    : raw.scanner_health === 'OFFLINE'  ? 'DISCONNECTED'
                    : 'UNKNOWN',
    eeh_latency_ms:   null,           // not stored — UI guards with ?. so this is safe
    session:          raw.session
      ? {
          session_id:      raw.session.session_id,
          status:          raw.session.status,
          opened_at:       raw.session.opened_at,
          total_uploaded:  raw.session.total_uploaded,
          total_accepted:  raw.session.total_accepted,
          total_rejected:  raw.session.total_rejected,
          total_held:      0,          // not tracked in eeh_sessions yet
        }
      : null,
    current_lot:      null,           // lot management not yet in DB — demo-only
    lots_sealed_today: 0,             // not tracked in DB — demo-only
  }
}

export default function useHubSummary({ pollEnabled = true } = {}) {
  const [branches, setBranches]             = useState([])
  const [totalBranches, setTotalBranches]   = useState(0)
  const [activeSessions, setActiveSessions] = useState(0)
  const [clearingDate, setClearingDate]     = useState(null)
  const [loading, setLoading]               = useState(true)
  const [error, setError]                   = useState(null)
  const timerRef = useRef(null)

  const fetchSummary = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/cts/outward/hub-summary`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setBranches((data.branches ?? []).map(normaliseBranch))
      setTotalBranches(data.total_branches ?? 0)
      setActiveSessions(data.active_sessions ?? 0)
      setClearingDate(data.clearing_date ?? null)
      setError(null)
    } catch (err) {
      setError(err.message)
      // Keep existing data on transient error
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchSummary()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchSummary, POLL_INTERVAL_MS)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchSummary, pollEnabled])

  return { branches, totalBranches, activeSessions, clearingDate, loading, error, refetch: fetchSummary }
}
