/**
 * useVaultGaps — fetches the vault gap report from GET /v1/cts/vault-gaps.
 *
 * Used post-banking-hours by ops managers to identify accounts that presented
 * cheques today but have no signature specimen in the vault. Ops team uses
 * this list to trigger overnight enrollment before the next clearing session.
 */
import { useState, useEffect, useCallback } from 'react'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export default function useVaultGaps({ date = null } = {}) {
  const [data, setData]       = useState(null)   // VaultGapResponse shape
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const fetchGaps = useCallback(async () => {
    setLoading(true)
    try {
      const params = date ? `?date=${encodeURIComponent(date)}` : ''
      const res = await fetch(
        `${API_BASE}/v1/cts/vault-gaps${params}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [date])

  useEffect(() => { fetchGaps() }, [fetchGaps])

  return { data, loading, error, refetch: fetchGaps }
}
