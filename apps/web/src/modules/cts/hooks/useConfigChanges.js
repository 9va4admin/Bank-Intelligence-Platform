/**
 * useConfigChanges — fetches GET /v1/admin/config/thresholds/changes
 * Returns the maker-checker change log for Layer 3 config keys.
 *
 * Returns: { changes, loading, error, refetch }
 *   changes: ConfigChangeEntry[] | null   (null until first fetch completes)
 */
import { useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export default function useConfigChanges({ limit = 50 } = {}) {
  const [changes, setChanges] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchChanges = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/v1/admin/config/thresholds/changes?limit=${limit}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setChanges(json.changes ?? [])
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => {
    fetchChanges()
  }, [fetchChanges])

  return { changes, loading, error, refetch: fetchChanges }
}
