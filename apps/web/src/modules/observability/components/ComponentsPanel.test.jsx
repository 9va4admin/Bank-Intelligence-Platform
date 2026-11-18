import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import ComponentsPanel from './ComponentsPanel'

const now = Date.now() / 1000
const payload = (over = {}) => ({
  bank_id: 'kbl', monitor: 'RUNNING', tick: 12, last_tick_age_seconds: 20,
  components: [
    { component: 'redis', status: 'DOWN', critical: true, since: now - 300, last_checked: now - 10, latency_ms: null, last_error: 'ConnectionError: refused', consecutive_failures: 5 },
    { component: 'vllm', status: 'SLOW', critical: false, since: now - 120, last_checked: now - 10, latency_ms: 1850.4, last_error: null, consecutive_failures: 0 },
    { component: 'yugabyte', status: 'OK', critical: true, since: now - 7200, last_checked: now - 10, latency_ms: 12.5, last_error: null, consecutive_failures: 0 },
  ],
  ...over,
})

function mockFetch(body, ok = true) {
  globalThis.fetch = vi.fn(async () => ({ ok, status: ok ? 200 : 503, json: async () => body }))
}

beforeEach(() => { vi.restoreAllMocks() })

describe('ComponentsPanel', () => {
  it('shows every component with its state, latency and last error', async () => {
    mockFetch(payload())
    render(<ComponentsPanel isDark={false} />)
    await waitFor(() => expect(screen.getByText('yugabyte')).toBeInTheDocument())
    expect(screen.getByText('redis')).toBeInTheDocument()
    expect(screen.getByText(/ConnectionError: refused/)).toBeInTheDocument()
    expect(screen.getByText(/12\.5 ms/)).toBeInTheDocument()
    expect(screen.getByText(/1850 ms/)).toBeInTheDocument()
  })

  it('labels each state in words, not only colour', async () => {
    mockFetch(payload())
    render(<ComponentsPanel isDark={false} />)
    await waitFor(() => expect(screen.getByText('yugabyte')).toBeInTheDocument())
    expect(screen.getByText('Down')).toBeInTheDocument()
    expect(screen.getByText('Slow')).toBeInTheDocument()
    expect(screen.getByText('OK')).toBeInTheDocument()
  })

  it('keeps the order the API gives (down first)', async () => {
    mockFetch(payload())
    render(<ComponentsPanel isDark={false} />)
    await waitFor(() => expect(screen.getByText('yugabyte')).toBeInTheDocument())
    const names = screen.getAllByTestId('component-name').map((n) => n.textContent)
    expect(names).toEqual(['redis', 'vllm', 'yugabyte'])
  })

  it('warns that the monitor itself has stopped, instead of showing stale states as fine', async () => {
    mockFetch(payload({ monitor: 'STALE', last_tick_age_seconds: 900 }))
    render(<ComponentsPanel isDark={false} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/has not reported for 15 minutes/i)
  })

  it('says so when the monitor is not running at all', async () => {
    mockFetch(payload({ monitor: 'NOT_RUNNING', components: [] }))
    render(<ComponentsPanel isDark={false} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/monitor is not running/i)
  })

  it('says so when the monitor cannot be reached', async () => {
    mockFetch(payload({ monitor: 'UNAVAILABLE', components: [] }))
    render(<ComponentsPanel isDark={false} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/cannot be reached/i)
  })

  it('shows an error and no components when the request fails', async () => {
    mockFetch({}, false)
    render(<ComponentsPanel isDark={false} />)
    expect(await screen.findByRole('alert')).toHaveTextContent(/503/)
  })

  it('says nothing is monitored yet when the list is empty and the monitor is running', async () => {
    mockFetch(payload({ components: [] }))
    render(<ComponentsPanel isDark={false} />)
    expect(await screen.findByText(/no components are being monitored yet/i)).toBeInTheDocument()
  })
})
