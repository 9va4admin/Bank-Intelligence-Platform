import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import NotificationDrawer from './NotificationDrawer'

const item = (id, over = {}) => ({ notification_id: id, incident_id: 'inc-1', severity: 'P1', title: `title-${id}`, body: `body-${id}`, action_link: '/ops/incidents/inc-1',
  created_at: new Date(Date.now() - 5 * 60000).toISOString(), read_at: null, acked_at: null, ...over })

const base = (over = {}) => ({ open: true, isDark: false, items: [item('a'), item('b', { read_at: 'x', severity: 'P3', action_link: null })], unread: { total: 1 },
  error: null, hasMore: false, onClose: vi.fn(), onOpenItem: vi.fn(), onReadAll: vi.fn(), onRetry: vi.fn(), onLoadMore: vi.fn(), ...over })

describe('NotificationDrawer', () => {
  it('lists the real notifications with title, body and the severity in words', () => {
    render(<NotificationDrawer {...base()} />)
    expect(screen.getByText('title-a')).toBeInTheDocument()
    expect(screen.getByText('body-a')).toBeInTheDocument()
    expect(screen.getByText('Major')).toBeInTheDocument()
    expect(screen.getByText('Info')).toBeInTheDocument()
  })

  it('marks unread ones in words for screen readers, not only with a dot', () => {
    render(<NotificationDrawer {...base()} />)
    expect(screen.getAllByText('Unread')).toHaveLength(1)
  })

  it('opens an item when it is clicked', () => {
    const onOpenItem = vi.fn()
    render(<NotificationDrawer {...base({ onOpenItem })} />)
    fireEvent.click(screen.getByText('title-a'))
    expect(onOpenItem).toHaveBeenCalledWith(expect.objectContaining({ notification_id: 'a' }))
  })

  it('shows mark-all-read only when something is unread, and calls it', () => {
    const onReadAll = vi.fn()
    const { rerender } = render(<NotificationDrawer {...base({ onReadAll })} />)
    fireEvent.click(screen.getByText('Mark all read'))
    expect(onReadAll).toHaveBeenCalled()
    rerender(<NotificationDrawer {...base({ unread: { total: 0 } })} />)
    expect(screen.queryByText('Mark all read')).toBeNull()
  })

  it('says so when there is nothing, rather than showing a blank panel', () => {
    render(<NotificationDrawer {...base({ items: [], unread: { total: 0 } })} />)
    expect(screen.getByText('No notifications yet.')).toBeInTheDocument()
  })

  it('says so when loading failed, with a retry, instead of looking empty', () => {
    const onRetry = vi.fn()
    render(<NotificationDrawer {...base({ items: [], error: 'x', onRetry })} />)
    expect(screen.getByText('Notifications could not be loaded.')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Try again'))
    expect(onRetry).toHaveBeenCalled()
  })

  it('offers load more only when there is another page', () => {
    const onLoadMore = vi.fn()
    const { rerender } = render(<NotificationDrawer {...base({ hasMore: true, onLoadMore })} />)
    fireEvent.click(screen.getByText('Load more'))
    expect(onLoadMore).toHaveBeenCalled()
    rerender(<NotificationDrawer {...base({ hasMore: false })} />)
    expect(screen.queryByText('Load more')).toBeNull()
  })

  it('renders nothing when closed', () => {
    const { container } = render(<NotificationDrawer {...base({ open: false })} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('works in the dark theme too', () => {
    render(<NotificationDrawer {...base({ isDark: true })} />)
    expect(screen.getByText('title-a')).toBeInTheDocument()
  })
})
