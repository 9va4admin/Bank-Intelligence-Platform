import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useInbox } from './useInbox'

const item = (id, over = {}) => ({ notification_id: id, incident_id: null, severity: 'P1', title: `t-${id}`, body: 'b', action_link: null,
  created_at: '2026-11-17T10:00:00Z', read_at: null, acked_at: null, ...over })
const summary = (over = {}) => ({ unread: { total: 2, P0: 1, P1: 1, P2: 0, P3: 0 }, pinned: [item('p1', { severity: 'P0' })], ...over })

let calls
function route(handlers) {
  calls = []
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const method = opts.method ?? 'GET'
    calls.push({ url, method, headers: opts.headers, credentials: opts.credentials })
    const key = Object.keys(handlers).find(k => `${method} ${url}`.includes(k))
    if (!key) return { ok: false, status: 404, json: async () => ({}) }
    const h = handlers[key]
    return typeof h === 'function' ? h() : { ok: true, status: 200, json: async () => h }
  })
}

beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear() })
afterEach(() => { vi.useRealTimers() })

describe('useInbox', () => {
  it('loads the unread counts, the pinned critical alerts and the list on mount, with the session cookie', async () => {
    route({ '/v1/inbox/summary': summary(), 'GET /v1/inbox?': { notifications: [item('a'), item('b')], next_cursor: null } })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.items).toHaveLength(2))
    expect(result.current.unread.total).toBe(2)
    expect(result.current.pinned[0].notification_id).toBe('p1')
    expect(calls.every(c => c.credentials === 'include')).toBe(true)
  })

  it('polls the summary at the configured interval', async () => {
    vi.useFakeTimers()
    route({ '/v1/inbox/summary': summary(), 'GET /v1/inbox?': { notifications: [], next_cursor: null } })
    renderHook(() => useInbox({ pollSeconds: 15 }))
    await act(async () => { await vi.advanceTimersByTimeAsync(100) })
    const first = calls.filter(c => c.url.includes('/summary')).length
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000) })
    expect(calls.filter(c => c.url.includes('/summary')).length).toBeGreaterThan(first)
  })

  it('marking one read posts with the CSRF token and marks it read at once', async () => {
    sessionStorage.setItem('astra-csrf', 'tok')
    route({ '/v1/inbox/summary': summary(), 'GET /v1/inbox?': { notifications: [item('a', { severity: 'P1' })], next_cursor: null }, 'POST /v1/inbox/a/read': { marked: 1 } })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.items).toHaveLength(1))
    await act(async () => { await result.current.markRead('a') })
    const post = calls.find(c => c.method === 'POST' && c.url.endsWith('/v1/inbox/a/read'))
    expect(post.headers['X-CSRF-Token']).toBe('tok')
    expect(result.current.items[0].read_at).toBeTruthy()
  })

  it('read-all clears every unread mark', async () => {
    route({ '/v1/inbox/summary': summary(), 'GET /v1/inbox?': { notifications: [item('a'), item('b')], next_cursor: null }, 'POST /v1/inbox/read-all': { marked: 2 } })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.items).toHaveLength(2))
    await act(async () => { await result.current.markAllRead() })
    expect(result.current.items.every(i => i.read_at)).toBe(true)
  })

  it('acknowledging reports success and failure, and refreshes the pinned list', async () => {
    let acked = false
    route({
      '/v1/inbox/summary': () => ({ ok: true, status: 200, json: async () => summary({ pinned: acked ? [] : [item('p1', { severity: 'P0' })] }) }),
      'GET /v1/inbox?': { notifications: [], next_cursor: null },
      'POST /v1/inbox/p1/acknowledge': () => { acked = true; return { ok: true, status: 200, json: async () => ({ notification_id: 'p1', incident_acknowledged: true }) } },
      'POST /v1/inbox/bad/acknowledge': () => ({ ok: false, status: 409, json: async () => ({}) }),
    })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.pinned).toHaveLength(1))
    let ok
    await act(async () => { ok = await result.current.acknowledge('p1') })
    expect(ok).toBe(true)
    await waitFor(() => expect(result.current.pinned).toHaveLength(0))
    await act(async () => { ok = await result.current.acknowledge('bad') })
    expect(ok).toBe(false)
  })

  it('reports a failed load instead of showing an empty inbox, and recovers on retry', async () => {
    let fail = true
    route({
      '/v1/inbox/summary': () => (fail ? { ok: false, status: 503, json: async () => ({}) } : { ok: true, status: 200, json: async () => summary() }),
      'GET /v1/inbox?': () => (fail ? { ok: false, status: 503, json: async () => ({}) } : { ok: true, status: 200, json: async () => ({ notifications: [item('a')], next_cursor: null }) }),
    })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.error).toBeTruthy())
    fail = false
    await act(async () => { await result.current.refresh() })
    expect(result.current.error).toBeNull()
    expect(result.current.items).toHaveLength(1)
  })

  it('survives an unexpected answer from the server without breaking', async () => {
    route({ '/v1/inbox/summary': {}, 'GET /v1/inbox?': {} })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.unread.total).toBe(0)
    expect(result.current.items).toEqual([])
    expect(result.current.pinned).toEqual([])
  })

  it('loads the next page and appends it', async () => {
    let page = 0
    route({
      '/v1/inbox/summary': summary(),
      'GET /v1/inbox?': () => ({ ok: true, status: 200, json: async () => (page++ === 0 ? { notifications: [item('a')], next_cursor: 'c1' } : { notifications: [item('b')], next_cursor: null }) }),
    })
    const { result } = renderHook(() => useInbox({ pollSeconds: 0 }))
    await waitFor(() => expect(result.current.items).toHaveLength(1))
    expect(result.current.hasMore).toBe(true)
    await act(async () => { await result.current.loadMore() })
    expect(result.current.items.map(i => i.notification_id)).toEqual(['a', 'b'])
    expect(result.current.hasMore).toBe(false)
    expect(calls.some(c => c.url.includes('cursor=c1'))).toBe(true)
  })
})
