/**
 * useModelHealth — fetches GET /v1/ops/model-health
 * Returns rolling model drift indicators for OCR / fraud / signature models.
 * Polls every 5 minutes in POC/PROD; disabled in demo mode.
 *
 * Returns: { data, loading, error, refetch }
 *   data: { bank_id, as_of, models: ModelEntry[], degraded } | null
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 5 * 60_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

export default function useModelHealth({ pollEnabled = true } = {}) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const timerRef = useRef(null)

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/v1/ops/model-health`, { credentials: 'include' })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      setData(json)
      setError(null)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

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
