import { describe, it, expect, vi, beforeEach, afterEach, beforeAll } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CTSBucketConfig from './CTSBucketConfig'
import { initMessages } from '../../../shared/messages'

beforeAll(async () => { await initMessages('en') })

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))

let calls
let lists
beforeEach(() => {
  calls = []
  lists = { CA: [{ account_hash: 'h1', account_last4: '7890', added_by: 'boss', added_at: '2026-10-28T10:00:00+00:00' }], IP: [] }
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const path = String(url).split('?')[0]
    calls.push({ path, opts })
    const m = path.match(/bucket-accounts\/(CA|IP)(?:\/(.+))?$/)
    if (m && (opts.method ?? 'GET') === 'GET') {
      return { ok: true, json: async () => ({ bucket: m[1], total: lists[m[1]].length, items: lists[m[1]], next_cursor: null }) }
    }
    if (m && opts.method === 'POST') return { ok: true, json: async () => ({ bucket: m[1], added: 2, already_present: 1, invalid: ['ab12'] }) }
    if (m && opts.method === 'DELETE') return { ok: true, json: async () => ({ bucket: m[1], removed: true }) }
    if (path === '/v1/admin/config/thresholds') {
      return { ok: true, json: async () => ({ thresholds: [
        { config_key: 'bucket_routing_enabled', current_value: 'false', description: 'Routing switch' },
        { config_key: 'bucket_hvc_min_amount', current_value: '500000', description: 'HVC floor' },
      ] }) }
    }
    return { ok: true, json: async () => ({}) }
  })
})
afterEach(() => vi.restoreAllMocks())

const renderPage = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><CTSBucketConfig /></MemoryRouter>
  </QueryClientProvider>)

describe('CTSBucketConfig', () => {
  it('lists the accounts on the CA list showing only the last four digits', async () => {
    renderPage()
    expect(await screen.findByText(/7890/)).toBeTruthy()
    expect(screen.getByText(/CA\)?: 1 account/)).toBeTruthy()
    expect(screen.queryByText(/1234567890/)).toBeNull()
  })

  it('adds the pasted accounts to the chosen list, de-duplicated and split on any separator', async () => {
    renderPage()
    await screen.findByText(/7890/)
    fireEvent.change(screen.getByLabelText('Add accounts'), { target: { value: '1234567890, 9876543210\n1234567890;5555566666' } })
    fireEvent.click(screen.getByRole('button', { name: /Add 3 to CA/ }))
    await waitFor(() => expect(calls.some(c => c.opts.method === 'POST')).toBe(true))
    const post = calls.find(c => c.opts.method === 'POST')
    expect(post.path).toBe('/v1/cts/admin/bucket-accounts/CA')
    expect(JSON.parse(post.opts.body).account_numbers).toEqual(['1234567890', '9876543210', '5555566666'])
    expect(await screen.findByText(/Added 2\. Already on the list: 1\./)).toBeTruthy()
    expect(screen.getByText(/entries ending …ab12/)).toBeTruthy()
  })

  it('switches to the IP list', async () => {
    renderPage()
    await screen.findByText(/7890/)
    fireEvent.click(screen.getByRole('button', { name: 'Institution (IP)' }))
    await waitFor(() => expect(calls.some(c => c.path === '/v1/cts/admin/bucket-accounts/IP')).toBe(true))
    expect(await screen.findByText('No accounts on this list yet.')).toBeTruthy()
  })

  it('removes an account by its hash', async () => {
    renderPage()
    fireEvent.click(await screen.findByLabelText('Remove account ending 7890'))
    await waitFor(() => expect(calls.some(c => c.opts.method === 'DELETE')).toBe(true))
    expect(calls.find(c => c.opts.method === 'DELETE').path).toBe('/v1/cts/admin/bucket-accounts/CA/h1')
  })

  it('the Add button stays disabled until there is something to add', async () => {
    renderPage()
    await screen.findByText(/7890/)
    expect(screen.getByRole('button', { name: /Add to CA/ }).disabled).toBe(true)
  })

  it('shows the current bucket rules read-only with a pointer to the maker-checker config page', async () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'Bucket rules' }))
    expect(await screen.findByText('bucket_hvc_min_amount')).toBeTruthy()
    expect(screen.getByText('500000')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Operations config' }).getAttribute('href')).toBe('/admin/config/operations')
  })

  it('explains when the user has no access', async () => {
    globalThis.fetch = vi.fn(async () => ({ ok: false, status: 403, json: async () => ({}) }))
    renderPage()
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText('You do not have access to these lists.')).toBeTruthy()
  })
})
