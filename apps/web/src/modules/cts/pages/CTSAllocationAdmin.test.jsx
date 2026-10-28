import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CTSAllocationAdmin from './CTSAllocationAdmin'

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/context/BankContext', () => ({ useBankContext: () => ({ bankId: 'kbl', isDemo: false }) }))

const NOW = Date.now() / 1000
const ROUTES = {
  '/v1/cts/allocation/status': {
    bank_id: 'kbl', total: 1, allocation_mode: 'AUTO', allocation_strategy: 'LEAST_LOADED', max_per_reviewer: 5,
    active_claims: [{ instrument_id: 'HELD-1', reviewer_id: 'alice' }],
  },
  '/v1/cts/allocation/reviewers': {
    bank_id: 'kbl', total: 2,
    active_reviewers: [
      { reviewer_id: 'alice', expires_at: NOW + 200, load: 3, zones: ['WEST'] },
      { reviewer_id: 'bob', expires_at: NOW + 200, load: 0, zones: ['ALL'] },
    ],
  },
  '/v1/cts/queue': {
    items: [
      { instrument_id: 'HELD-1', assigned_to: 'alice', iet_deadline: NOW + 7200, clearing_zone: 'UNKNOWN' },
      { instrument_id: 'FREE-1', assigned_to: null, iet_deadline: NOW + 600, clearing_zone: 'WEST' },
    ],
  },
}

let calls
beforeEach(() => {
  calls = []
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const path = String(url).split('?')[0]
    calls.push({ path, opts })
    if (path.endsWith('/assign')) return { ok: true, json: async () => ({ reviewer_id: 'bob' }) }
    return { ok: true, json: async () => ROUTES[path] ?? {} }
  })
})
afterEach(() => vi.restoreAllMocks())

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}><MemoryRouter><CTSAllocationAdmin /></MemoryRouter></QueryClientProvider>
  )
}

describe('CTSAllocationAdmin', () => {
  it('shows the active mode, strategy and cap from the status endpoint', async () => {
    renderPage()
    expect(await screen.findByText('AUTO')).toBeTruthy()
    expect(screen.getByText(/least loaded, max 5 each/)).toBeTruthy()
  })

  it('shows each online reviewer with how many claims they hold', async () => {
    renderPage()
    expect(await screen.findByText('3 held')).toBeTruthy()
  })

  it('lists only unassigned queue items, flagging the urgent one', async () => {
    renderPage()
    expect(await screen.findByText('FREE-1')).toBeTruthy()
    expect(screen.getByText(/IET in \d+ min/)).toBeTruthy()
    expect(screen.getByText(/Unassigned in the queue \(1\)/)).toBeTruthy()
  })

  it('assigns an unassigned cheque to the chosen reviewer through the admin endpoint', async () => {
    renderPage()
    await screen.findByText('FREE-1')
    const selects = screen.getAllByRole('combobox')
    const assignSelect = selects.find(s => s.textContent.includes('Assign to'))
    fireEvent.change(assignSelect, { target: { value: 'bob' } })
    await waitFor(() => expect(calls.some(c => c.path === '/v1/cts/admin/review/FREE-1/assign')).toBe(true))
    const post = calls.find(c => c.path.endsWith('/assign'))
    expect(post.opts.method).toBe('POST')
    expect(JSON.parse(post.opts.body)).toEqual({ reviewer_id: 'bob' })
  })

  it('offers reassignment of a held cheque to anyone except its current holder', async () => {
    renderPage()
    await screen.findByText('HELD-1')
    const reassign = screen.getAllByRole('combobox').find(s => s.textContent.includes('Reassign'))
    const options = Array.from(reassign.querySelectorAll('option')).map(o => o.value).filter(Boolean)
    expect(options).toEqual(['bob'])
  })
})
