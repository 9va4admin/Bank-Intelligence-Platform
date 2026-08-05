/**
 * Tests for useReviewQueue hook.
 *
 * Uses vi.stubGlobal to mock fetch; no real network calls are made.
 * Vitest + @testing-library/react-hooks pattern.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import useReviewQueue from './useReviewQueue'

const MOCK_ITEMS = [
  {
    instrument_id: 'CHQ-001',
    workflow_id:   'wf-001',
    bank_id:       'test-bank',
    account_display: '****1234',
    payee_display:   'N***',
    amount_range:    '₹[1L-5L]',
    clearing_zone:   'MUMBAI',
    received_at:     1_700_000_000,
    iet_deadline:    1_700_010_800,
    reason:          'FRAUD_SCORE_HIGH',
    fraud_score:     0.85,
    ocr_confidence:  0.97,
    sig_match_score: 0.91,
  },
]

describe('useReviewQueue', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('returns mock data immediately when no token is provided', async () => {
    const { result } = renderHook(() => useReviewQueue())
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.useMock).toBe(true)
    expect(Array.isArray(result.current.items)).toBe(true)
  })

  it('fetches from API when token is provided and returns normalised items', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: MOCK_ITEMS, total: 1 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useReviewQueue({ token: 'test-token-bank1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.useMock).toBe(false)
    expect(result.current.items).toHaveLength(1)
    expect(result.current.items[0].instrument_id).toBe('CHQ-001')
    // normaliseItem should convert Unix timestamp to ISO string
    expect(result.current.items[0].received_at).toMatch(/^\d{4}-\d{2}-\d{2}T/)
    expect(result.current.items[0].iet_deadline).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })

  it('falls back to mock data on fetch error when items list is empty', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error('Network error'))
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useReviewQueue({ token: 'test-token-bank1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.useMock).toBe(true)
    expect(result.current.error).toBe('Network error')
  })

  it('returns error message on non-200 response', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: false, status: 503 })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useReviewQueue({ token: 'test-token-bank1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))

    expect(result.current.error).toBe('HTTP 503')
  })

  it('exposes refetch function that can be called manually', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const { result } = renderHook(() => useReviewQueue({ token: 'test-token-bank1' }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(typeof result.current.refetch).toBe('function')

    await result.current.refetch()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('does not set up polling when pollEnabled is false', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ items: [], total: 0 }),
    })
    vi.stubGlobal('fetch', fetchMock)

    renderHook(() => useReviewQueue({ token: 'test-token-bank1', pollEnabled: false }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1))

    // Advance past one poll interval — should not trigger another fetch
    vi.advanceTimersByTime(15_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
