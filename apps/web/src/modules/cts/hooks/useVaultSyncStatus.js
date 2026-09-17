import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch vault sync status from GET /v1/cts/vault/sync-status
 * Returns { syncStatus, syncHistory, loading, error, refetch }
 *   syncStatus: null until loaded → VaultSyncStatusData on success
 *   syncHistory: [] until loaded → VaultSyncRun[] on success
 */
export default function useVaultSyncStatus({ pollEnabled = true } = {}) {
  const [syncStatus, setSyncStatus] = useState(null)
  const [syncHistory, setSyncHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/cts/vault/sync-status`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setSyncStatus(json.status ?? null)
      setSyncHistory(json.history ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchStatus()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchStatus, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchStatus, pollEnabled])

  return { syncStatus, syncHistory, loading, error, refetch: fetchStatus }
}
