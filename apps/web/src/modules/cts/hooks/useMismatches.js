import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 2 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Fetch active mismatches from GET /v1/cts/mismatches.
 * Returns { mismatches, loading, error, refetch }
 *   mismatches: MismatchItem[] mapped to the shape CTSDiscrepancy expects
 */
export default function useMismatches({ branchId = null, pollEnabled = true } = {}) {
  const [mismatches, setMismatches] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchMismatches = useCallback(async () => {
    const params = new URLSearchParams()
    if (branchId) params.set('branch_id', branchId)
    try {
      const res = await fetch(`${API_BASE}/v1/cts/mismatches?${params}`, {
        credentials: 'include',
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      const raw = json.items ?? []
      // Map API MismatchItem → CTSDiscrepancy display shape
      setMismatches(raw.map(r => ({
        id: r.mismatch_id,
        instrument: r.instrument_id,
        lot: r.lot_id ?? '-',
        branch: r.branch_id ?? '-',
        session: '-',
        type: Array.isArray(r.mismatch_fields) && r.mismatch_fields.length > 0
          ? r.mismatch_fields[0]
          : 'UNPROCESSED',
        status: 'OPEN',
        micr_amount: r.scanner_amount ?? '-',
        actual_amount: r.vision_amount ?? '-',
        words_amount: '-',
        physical_count: null,
        electronic_count: null,
        detail: Array.isArray(r.mismatch_fields)
          ? r.mismatch_fields.join(', ')
          : 'Mismatch detected',
        raised_at: r.held_at,
        assigned_to: null,
      })))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [branchId])

  useEffect(() => {
    fetchMismatches()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchMismatches, POLL_INTERVAL_MS)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [fetchMismatches, pollEnabled])

  return { mismatches, loading, error, refetch: fetchMismatches }
}
