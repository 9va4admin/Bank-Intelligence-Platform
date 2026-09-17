/**
 * useAnalytics — fetches GET /v1/cts/outward/analytics/daily for CTSAnalytics.jsx
 * in POC/PROD mode. Polls every 5 minutes (analytics data is not real-time).
 *
 * Returns: { daily, loading, error, refetch }
 *
 * daily rows shape: { date, total, stp_confirm, stp_return, human_review, avg_ms }
 * which matches the mock SB_DAILY / SMB_DAILY shape in CTSAnalytics.jsx.
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000   // 5 min — analytics aggregates don't change by the second
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** Map API row to the shape CTSAnalytics mock data uses (camelCase renamed to match). */
function normaliseRow(raw) {
  return {
    date:        raw.date,
    total:       raw.total,
    stp_confirm: raw.stp_confirm,
    stp_return:  raw.stp_return,
    human:       raw.human_review,          // mock calls it "human"
    avg_ms:      Math.round(raw.avg_ms ?? 0),
    ocr_conf:    raw.ocr_conf  ?? null,
    sig_prec:    raw.sig_prec  ?? null,
  }
}

export default function useAnalytics({ days = 7, pollEnabled = true } = {}) {
  const [daily, setDaily]     = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const timerRef = useRef(null)

  const fetchAnalytics = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/v1/cts/outward/analytics/daily?days=${days}`,
        { credentials: 'include' },
      )
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setDaily((data.daily ?? []).map(normaliseRow))
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [days])

  useEffect(() => {
    fetchAnalytics()
    if (pollEnabled) {
      timerRef.current = setInterval(fetchAnalytics, POLL_INTERVAL_MS)
    }
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchAnalytics, pollEnabled])

  return { daily, loading, error, refetch: fetchAnalytics }
}
