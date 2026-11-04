import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import useOpsDashboard, { sessionCard } from './useOpsDashboard'

const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

const SUMMARY = {
  session: { session_id: 'S1', session_slot: 'Session 1', status: 'FILED' },
  presenting_bank: { total_inward: 13, total_value_paise: 1250, stp_rate_pct: 60, return_rate_pct: 15.4 },
}

afterEach(() => vi.unstubAllGlobals())

describe('sessionCard', () => {
  it('maps a real session summary onto the card the grid renders', () => {
    expect(sessionCard(SUMMARY)).toEqual({
      id: 'S1', slot: 'Session 1', status: 'FILED', inward: 13, inward_val: 1250, stp_rate: 60, return_rate: 15.4,
    })
  })
})

describe('useOpsDashboard sessions', () => {
  it('loads the sessions the API lists, with each one\'s real figures', async () => {
    const calls = []
    vi.stubGlobal('fetch', vi.fn((url) => {
      calls.push(String(url))
      const u = String(url)
      if (u.includes('/sessions/S1/summary')) return Promise.resolve(json(SUMMARY))
      if (u.includes('/v1/cts/sessions')) return Promise.resolve(json({ sessions: [{ session_id: 'S1' }], total: 1 }))
      return Promise.resolve(json({}, 404))
    }))
    const { result } = renderHook(() => useOpsDashboard({ pollEnabled: false }))
    await waitFor(() => expect(result.current.sessions).not.toBeNull())
    expect(result.current.sessions).toHaveLength(1)
    expect(result.current.sessions[0].inward).toBe(13)
    expect(calls.some((c) => /\/v1\/cts\/sessions\?clearing_date=\d{4}-\d{2}-\d{2}/.test(c))).toBe(true)
  })

  it('leaves sessions null (not an empty list) when the API fails', async () => {
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(json({}, 503))))
    const { result } = renderHook(() => useOpsDashboard({ pollEnabled: false }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.sessions).toBeNull()
  })
})
