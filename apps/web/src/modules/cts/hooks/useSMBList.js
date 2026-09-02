import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch the list of Sub-Member Banks registered under this SB.
 * Hits GET /v1/cts/smb (SB-only endpoint).
 *
 * Returns { subMembers, total, loading, error, refetch }
 */
export default function useSMBList({ activeOnly = true, pollEnabled = true } = {}) {
  const [subMembers, setSubMembers] = useState(null)
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchList = useCallback(async () => {
    const params = new URLSearchParams()
    params.set('active_only', activeOnly ? 'true' : 'false')
    try {
      const res = await fetch(`${API_BASE}/v1/cts/smb?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setSubMembers(json.sub_members ?? [])
      setTotal(json.total ?? 0)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [activeOnly])

  useEffect(() => {
    fetchList()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchList, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchList, pollEnabled])

  return { subMembers, total, loading, error, refetch: fetchList }
}
