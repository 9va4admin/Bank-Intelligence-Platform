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
  '/v1/cts/outward/human-review-queue': {
    items: [
      { instrument_id: 'OUT-FREE-1', assigned_to: null, bucket: 'OUT_MISMATCH', pu_id: 'PU-9', due_at: NOW + 1200 },
      { instrument_id: 'OUT-HELD-1', assigned_to: 'bob', bucket: 'OUT_HV', pu_id: 'PU-9', due_at: NOW + 1200 },
    ],
  },
  '/v1/cts/allocation/status': {
    bank_id: 'kbl', total: 1, allocation_mode: 'AUTO', allocation_strategy: 'LEAST_LOADED', max_per_reviewer: 5,
    active_claims: [{ instrument_id: 'HELD-1', reviewer_id: 'alice' }],
  },
  '/v1/cts/allocation/reviewers': {
    bank_id: 'kbl', total: 2,
    active_reviewers: [
      { reviewer_id: 'alice', expires_at: NOW + 200, load: 3, pu_ids: ['WEST'] },
      { reviewer_id: 'bob', expires_at: NOW + 200, load: 0, pu_ids: ['ALL'] },
    ],
  },
  '/v1/cts/admin/buckets': {
    bank_id: 'kbl', routing_enabled: false,
    buckets: [
      { bucket: 'HVC', subscribers: [{ reviewer_id: 'alice', online: true, load: 3 }] },
      { bucket: 'CA', subscribers: [] },
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
    if (path.endsWith('/buckets') && opts.method === 'PUT') return { ok: true, json: async () => ({ reviewer_id: 'bob', buckets: [] }) }
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

  it('shows the bucket grid with existing connections ticked and warns that routing is off', async () => {
    renderPage()
    expect(await screen.findByText('Bucket connections')).toBeTruthy()
    expect(await screen.findByText(/Bucket routing OFF/)).toBeTruthy()
    expect((await screen.findByLabelText('alice High value')).checked).toBe(true)
    expect(screen.getByLabelText('alice Corporate').checked).toBe(false)
  })

  it('connects a reviewer to another bucket, sending the full new set', async () => {
    renderPage()
    const box = await screen.findByLabelText('alice Corporate')
    fireEvent.click(box)
    await waitFor(() => expect(calls.some(c => c.path === '/v1/cts/admin/reviewers/alice/buckets' && c.opts.method === 'PUT')).toBe(true))
    const put = calls.find(c => c.opts.method === 'PUT')
    expect(JSON.parse(put.opts.body)).toEqual({ buckets: ['HVC', 'CA'] })
  })

  it('removes a connection by unticking it', async () => {
    renderPage()
    fireEvent.click(await screen.findByLabelText('alice High value'))
    await waitFor(() => expect(calls.some(c => c.opts.method === 'PUT')).toBe(true))
    expect(JSON.parse(calls.find(c => c.opts.method === 'PUT').opts.body)).toEqual({ buckets: [] })
  })

  it('lists the outward items waiting for an owner, with their bucket and when the session closes', async () => {
    renderPage()
    expect(await screen.findByText(/Outward items waiting for an owner \(1 of 2 held\)/)).toBeTruthy()
    expect(screen.getByText('OUT-FREE-1')).toBeTruthy()
    expect(screen.getByText('Out · mismatch', { selector: 'td' })).toBeTruthy()
    expect(screen.queryByText('OUT-HELD-1')).toBeNull()
    expect(screen.getByText(/Session closes in/)).toBeTruthy()
  })

  it('offers the checker and outward buckets in the reviewer grid', async () => {
    renderPage()
    await screen.findByText(/Outward items waiting/)
    for (const label of ['Checker', 'Out · high value', 'Out · compliance', 'Out · review']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0)
    }
  })
})
