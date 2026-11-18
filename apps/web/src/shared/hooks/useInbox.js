// The bell's data: the signed-in user's own notifications from /v1/inbox, kept fresh by polling.
// Failures are reported (never shown as an empty inbox); writes carry the CSRF token; counts update at once and are then confirmed by the server.
import { useState, useEffect, useCallback, useRef } from 'react'
import { csrfHeader } from '../api/csrf'
import { INBOX_POLL_SECONDS, INBOX_PAGE_SIZE, INBOX_PINNED_LIMIT } from '../config/inbox.config'

const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const NO_UNREAD = { total: 0, P0: 0, P1: 0, P2: 0, P3: 0 }

async function getJson(path) {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(String(res.status))
  return res.json()
}

async function post(path) {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', credentials: 'include', headers: { ...csrfHeader() } })
  return res
}

export function useInbox({ pollSeconds = INBOX_POLL_SECONDS, pageSize = INBOX_PAGE_SIZE, pinnedLimit = INBOX_PINNED_LIMIT } = {}) {
  const [unread, setUnread] = useState(NO_UNREAD)
  const [pinned, setPinned] = useState([])
  const [items, setItems] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const alive = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const [summary, page] = await Promise.all([
        getJson(`/v1/inbox/summary?pinned_limit=${pinnedLimit}`),
        getJson(`/v1/inbox?limit=${pageSize}`),
      ])
      if (!alive.current) return
      setUnread({ ...NO_UNREAD, ...(summary?.unread ?? {}) })       // an unexpected answer never breaks the page it sits on
      setPinned(summary?.pinned ?? [])
      setItems(page?.notifications ?? [])
      setNextCursor(page?.next_cursor ?? null)
      setError(null)
    } catch (e) {
      if (alive.current) setError(e.message)
    } finally {
      if (alive.current) setLoading(false)
    }
  }, [pageSize, pinnedLimit])

  useEffect(() => {
    alive.current = true
    refresh()
    const timer = pollSeconds > 0 ? setInterval(refresh, pollSeconds * 1000) : null
    return () => { alive.current = false; if (timer) clearInterval(timer) }
  }, [refresh, pollSeconds])

  const markRead = useCallback(async (id) => {
    const now = new Date().toISOString()
    const target = items.find(i => i.notification_id === id)
    const res = await post(`/v1/inbox/${id}/read`)
    if (!res.ok) return false
    setItems(prev => prev.map(i => (i.notification_id === id && !i.read_at ? { ...i, read_at: now } : i)))
    if (target && !target.read_at) {
      setUnread(u => ({ ...u, total: Math.max(0, u.total - 1), [target.severity]: Math.max(0, (u[target.severity] ?? 0) - 1) }))
    }
    return true
  }, [items])

  const markAllRead = useCallback(async () => {
    const res = await post('/v1/inbox/read-all')
    if (!res.ok) return false
    const now = new Date().toISOString()
    setItems(prev => prev.map(i => (i.read_at ? i : { ...i, read_at: now })))
    setUnread(NO_UNREAD)
    return true
  }, [])

  const acknowledge = useCallback(async (id) => {
    const res = await post(`/v1/inbox/${id}/acknowledge`)
    if (!res.ok) return false
    await refresh()
    return true
  }, [refresh])

  const loadMore = useCallback(async () => {
    if (!nextCursor) return
    try {
      const page = await getJson(`/v1/inbox?limit=${pageSize}&cursor=${encodeURIComponent(nextCursor)}`)
      setItems(prev => [...prev, ...(page?.notifications ?? [])])
      setNextCursor(page?.next_cursor ?? null)
    } catch (e) {
      setError(e.message)
    }
  }, [nextCursor, pageSize])

  return { unread, pinned, items, error, loading, hasMore: Boolean(nextCursor), refresh, markRead, markAllRead, acknowledge, loadMore }
}
