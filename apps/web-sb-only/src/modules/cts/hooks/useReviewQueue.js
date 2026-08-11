/**
 * useReviewQueue — fetches the human review queue from GET /v1/cts/queue.
 *
 * Falls back to mock data when the API is unreachable (dev / offline).
 * Polls every 10 seconds during an active clearing session.
 *
 * Returns:
 *   { items, total, loading, error, refetch }
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { MOCK_QUEUE } from '../data/mockQueue'

const POLL_INTERVAL_MS = 10_000
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * Transform a raw queue item from the API into the shape the UI expects.
 * The API returns Unix timestamps; the UI expects ISO strings for IETTimer.
 */
function normaliseItem(raw) {
  return {
    ...raw,
    received_at: raw.received_at
      ? new Date(raw.received_at * 1000).toISOString()
      : new Date().toISOString(),
    iet_deadline: raw.iet_deadline
      ? new Date(raw.iet_deadline * 1000).toISOString()
      : new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
    // UI-only fields not present on API items — filled with safe defaults
    status: raw.status ?? 'PENDING',
    reason_label: raw.reason_label ?? _reasonLabel(raw.reason),
    cbs_type: raw.cbs_type ?? 'Finacle',
    sig_specimen_available: raw.sig_match_score != null,
    sig_specimen_label: raw.sig_specimen_label ?? 'Specimen on file',
    principal_tag: raw.principal_tag ?? 'DIRECT',
    sub_member_name: raw.sub_member_name ?? null,
    sub_member_id: raw.sub_member_id ?? null,
    opa_rule: raw.opa_rule ?? null,
    shap_values: raw.shap_values ?? [],
    ocr_fields: raw.ocr_fields ?? {
      date: '—',
      payee: raw.payee_display ?? '—',
      amount_figures: '—',
      amount_words: '—',
      micr: '—',
      alterations: false,
    },
  }
}

function _reasonLabel(reason) {
  const MAP = {
    VAULT_MISS: 'No specimen on file',
    FRAUD_SCORE_HIGH: 'Fraud score above threshold',
    OCR_LOW_CONFIDENCE: 'OCR low confidence',
    SIGNATURE_LOW_CONFIDENCE: 'Signature mismatch',
    HIGH_VALUE_DUAL_APPROVAL: 'High value — dual approval required',
    CBS_UNAVAILABLE: 'CBS unreachable',
    PPS_MISS: 'PPS not registered',
  }
  return MAP[reason] ?? reason ?? 'Flagged for review'
}

export default function useReviewQueue({ token, pollEnabled = true } = {}) {
  const [items, setItems]     = useState([])
  const [total, setTotal]     = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)
  const [useMock, setUseMock] = useState(false)
  const timerRef = useRef(null)

  const fetchQueue = useCallback(async () => {
    if (!token) {
      // No auth token — use mock data for development
      const pending = MOCK_QUEUE.filter((q) => q.status === 'PENDING')
      setItems(pending)
      setTotal(pending.length)
      setUseMock(true)
      setLoading(false)
      return
    }

    try {
      const res = await fetch(`${API_BASE}/v1/cts/queue`, {
        headers: { Authorization: `Bearer ${token}` },
      })

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`)
      }

      const data = await res.json()
      const normalised = (data.items ?? []).map(normaliseItem)
      setItems(normalised)
      setTotal(data.total ?? normalised.length)
      setUseMock(false)
      setError(null)
    } catch (err) {
      setError(err.message)
      // On first failure fall back to mock so the UI stays usable
      if (items.length === 0) {
        const pending = MOCK_QUEUE.filter((q) => q.status === 'PENDING')
        setItems(pending)
        setTotal(pending.length)
        setUseMock(true)
      }
    } finally {
      setLoading(false)
    }
  }, [token])  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    fetchQueue()

    if (pollEnabled) {
      timerRef.current = setInterval(fetchQueue, POLL_INTERVAL_MS)
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
    }
  }, [fetchQueue, pollEnabled])

  return { items, total, loading, error, useMock, refetch: fetchQueue }
}
