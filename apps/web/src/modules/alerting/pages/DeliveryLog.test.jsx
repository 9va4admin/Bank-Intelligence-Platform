import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import DeliveryLog from './DeliveryLog'
import { mockApi, renderPage, failing } from '../testing'

const row = (id, over = {}) => ({ notification_id: id, channel: 'email', template_id: 'PLATFORM_HEALTH_ALERT', recipient_ref: 'o***@bank.example', delivery_status: 'SENT',
  attempt_count: 1, created_at: new Date(Date.now() - 5 * 60000).toISOString(), ...over })
const page = (...items) => ({ notifications: items, total: items.length, limit: 50, next_cursor: null })

describe('DeliveryLog', () => {
  it('lists every notification attempt with the channel, the masked recipient and the status in words', async () => {
    mockApi({ 'GET /v1/notifications?': page(row('a'), row('b', { channel: 'bell', recipient_ref: 'usr-ops', delivery_status: 'FAILED' }), row('c', { delivery_status: 'RETRYING', attempt_count: 2 })) })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getAllByText(/o\*\*\*@bank\.example/).length).toBe(2))
    expect(screen.getByText('usr-ops')).toBeInTheDocument()
    expect(screen.getAllByText('Sent').length).toBeGreaterThan(1)               // the status, and the filter choice of the same name
    expect(screen.getAllByText('Undelivered').length).toBeGreaterThan(1)
    expect(screen.getAllByText('Will retry').length).toBeGreaterThan(1)
  })

  it('filters by status and channel through the server', async () => {
    const calls = mockApi({ 'GET /v1/notifications?': page(row('a')) })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getByText(/o\*\*\*@bank\.example/)).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Status'), { target: { value: 'FAILED' } })
    fireEvent.change(screen.getByLabelText('Channel'), { target: { value: 'bell' } })
    await waitFor(() => expect(calls.some(c => c.url.includes('delivery_status=FAILED') && c.url.includes('channel=bell'))).toBe(true))
  })

  it('offers a retry only for deliveries that failed or will retry, and sends it', async () => {
    const calls = mockApi({
      'GET /v1/notifications?': page(row('ok'), row('bad', { delivery_status: 'FAILED' })),
      'POST /v1/notifications/bad/retry': { notification_id: 'bad', status: 'RETRYING', retried_at: 'now' },
    })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getAllByText(/o\*\*\*@bank\.example/).length).toBe(2))
    expect(screen.getAllByText('Retry now')).toHaveLength(1)
    fireEvent.click(screen.getByText('Retry now'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/v1/notifications/bad/retry'))).toBe(true))
    await waitFor(() => expect(screen.getByText('Queued to retry.')).toBeInTheDocument())
  })

  it('tells the person when a retry was refused', async () => {
    mockApi({ 'GET /v1/notifications?': page(row('bad', { delivery_status: 'FAILED' })), 'POST /v1/notifications/bad/retry': failing(403, { detail: 'Your role cannot send or retry notifications.' }) })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getByText('Retry now')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Retry now'))
    await waitFor(() => expect(screen.getByText(/cannot send or retry/)).toBeInTheDocument())
  })

  it('says so when it cannot load or when there is nothing', async () => {
    mockApi({ 'GET /v1/notifications?': failing(503, {}) })
    const { unmount } = renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    mockApi({ 'GET /v1/notifications?': page() })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getByText('No deliveries match.')).toBeInTheDocument())
  })

  it('loads the next page', async () => {
    let n = 0
    const calls = mockApi({ 'GET /v1/notifications?': () => (n++ === 0 ? { notifications: [row('a')], total: 2, limit: 50, next_cursor: 'c1' } : { notifications: [row('b', { recipient_ref: 'second' })], total: 2, limit: 50, next_cursor: null }) })
    renderPage(<DeliveryLog />)
    await waitFor(() => expect(screen.getByText('Load more')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Load more'))
    await waitFor(() => expect(screen.getByText('second')).toBeInTheDocument())
    expect(calls.some(c => c.url.includes('cursor=c1'))).toBe(true)
  })

  it('works in the dark theme', async () => {
    mockApi({ 'GET /v1/notifications?': page(row('a')) })
    renderPage(<DeliveryLog />, { isDark: true })
    await waitFor(() => expect(screen.getByText(/o\*\*\*@bank\.example/)).toBeInTheDocument())
  })
})
