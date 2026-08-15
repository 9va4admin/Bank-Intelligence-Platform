/**
 * useDecisions — fetches the agent decisions log from GET /v1/cts/decisions.
 *
 * In DEMO mode: falls through to API but returns empty list on error (no mock).
 * In POC/PROD mode: hits real API, polls every 15 seconds, never falls back to mock.
 *
 * Returns:
 *   { items, total, loading, error, refetch }
 */
import { useState, useEffect, useCallback, useRef } from 'react'

const POLL_INTERVAL_MS = 15_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Transform a raw decision row from the API into the shape CTSDecisionsLog expects.
 * Unix timestamps → ISO strings; shap_values dict → features array for the SHAP panel.
 */
function normaliseDecision(raw) {
  const shapFeatures = Object.entries(raw.shap_values ?? {}).map(([name, value]) => ({
    name,
    value: typeof value === 'number' ? value : 0,
  }))

  return {
    id: raw.instrument_id,
    workflow_id: raw.workflow_id,
    micr: raw.micr_code ?? '—',
    account: raw.account_display ?? '****????',
    amount: raw.amount_range ?? '₹[unknown]',
    payee: '***',                    // payee_name_enc requires server-side decrypt — placeholder
    outcome: raw.decision,
    reason: raw.decision_reason ?? '',
    agent_ms: raw.processing_duration_ms ?? 0,
    fraud: raw.fraud_score ?? 0,
    presenting_ifsc: raw.presenting_ifsc ?? null,
    degraded: raw.degraded_mode ?? false,
    filed: raw.created_at ? new Date(raw.created_at * 1000).toISOString() : null,
    alteration_detected: raw.alteration_detected ?? false,
    sig_match_score: raw.signature_match_score ?? 0,
    sig_verdict: raw.signature_verdict ?? 'UNKNOWN',
    pps_verdict: raw.pps_verdict ?? 'NOT_CHECKED',
    cbs_balance_status: raw.cbs_balance_status ?? 'NOT_CHECKED',
    iet_margin_seconds: raw.iet_margin_seconds ?? 0,
    ocr_engines_used: raw.ocr_engines_used ?? [],
    indic_ocr_kill_switch_active: raw.indic_ocr_kill_switch_active ?? false,
    shap: {
      fraud_score: raw.fraud_score ?? 0,
      features: shapFeatures,
    },
  }
}

export default function useDecisions({ limit = 50, pollEnabled = true } = {}) {
  const [items, setItems]     = useState([])
  const [total, setTotal]     = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const timerRef = useRef(null)

  const fetchDecisions = useCallback(async () => {
    try {
      const res = await fetch(
        `${API_BASE}/v1/cts/decisions?limit=${encodeURIComponent(limit)}`,
        { credentials: 'include' },   // session cookie — no Bearer token on frontend
      )

      if (!res.ok) throw new Error(`HTTP ${res.status}`)

      const data = await res.json()
      const normalised = (data.items ?? []).map(normaliseDecision)
      setItems(normalised)
      setTotal(data.total ?? normalised.length)
      setError(null)
    } catch (err) {
      setError(err.message)
      // Keep existing items on error — stale data beats an empty table
    } finally {
      setLoading(false)
    }
  }, [limit])

  useEffect(() => {
    fetchDecisions()

    if (pollEnabled) {
      timerRef.current = setInterval(fetchDecisions, POLL_INTERVAL_MS)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchDecisions, pollEnabled])

  return { items, total, loading, error, refetch: fetchDecisions }
}
