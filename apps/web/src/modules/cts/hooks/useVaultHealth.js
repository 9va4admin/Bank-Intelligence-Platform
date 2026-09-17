import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 60_000  // vault health refreshes every 60s
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch vault health summary — key counts, hit rate status, last sync times.
 * Hits GET /v1/cts/vault/health
 *
 * Returns { health, loading, error, refetch }
 *   health: null (pre-load) → VaultHealthResponse on success
 */
export default function useVaultHealth({ pollEnabled = true } = {}) {
  const [health, setHealth] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/cts/vault/health`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setHealth(json)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchHealth, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchHealth, pollEnabled])

  return { health, loading, error, refetch: fetchHealth }
}
