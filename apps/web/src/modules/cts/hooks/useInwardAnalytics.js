/**
 * useInwardAnalytics — fetches GET /v1/cts/inward/analytics for CTSAnalytics.jsx
 * in POC/PROD mode. Polls every 5 minutes.
 *
 * Returns: { data, loading, error, refetch }
 *
 * data shape:
 *   { daily, fraud_dist, risk_flags, return_reasons, branches, iet_trend }
 *
 * daily rows add ocr_conf + sig_prec (AI confidence averages) to the outward shape.
 * All other sections replace mock data when the DB has records.
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

const EMPTY = {
  daily:          [],
  fraud_dist:     [],
  risk_flags:     [],
  return_reasons: [],
  branches:       [],
  iet_trend:      [],
}

export default function useInwardAnalytics({ days = 7, pollEnabled = true } = {}) {
  const [data, setData]       = useState(EMPTY)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const timerRef = useRef(null)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/v1/cts/inward/analytics?days=${days}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData({
        daily:          json.daily          ?? [],
        fraud_dist:     json.fraud_dist     ?? [],
        risk_flags:     json.risk_flags     ?? [],
        return_reasons: json.return_reasons ?? [],
        branches:       json.branches       ?? [],
        iet_trend:      (json.iet_trend     ?? []).map(r => ({
          date:       r.date,
          nearBreach: r.nearBreach ?? 0,
        })),
      })
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    fetchData()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchData, POLL_INTERVAL_MS)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchData, pollEnabled])

  return { data, loading, error, refetch: fetchData }
}
