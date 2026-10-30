import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import CTSInwardReviewQueue from './CTSInwardReviewQueue'

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/layout/PageHeaderContext', () => ({ usePageHeader: () => ({ setHeader: vi.fn() }) }))
vi.mock('../../../shared/context/BankContext', () => ({
  useBankContext: () => ({ bankId: 'kbl', bankName: 'Central Bank of India', isDemo: false, userName: 'qa_rev' }),
}))

const MINE = { instrument_id: 'I-1', assigned_to: 'usr-qa_rev-kbl', assigned_to_me: true, bucket: 'LVC', amount_range: '₹[<1L]',
               account_display: '****0101', payee_display: 'A***', iet_deadline: Date.now() / 1000 + 9000, reason: 'x', drawee_name: 'Anjali' }
let calls
beforeEach(() => {
  calls = []
  sessionStorage.setItem('astra-csrf', 'tok-9')
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    calls.push({ url: String(url), opts })
    if (String(url).startsWith('/v1/cts/queue')) return { ok: true, json: async () => ({ items: [MINE] }) }
    return { ok: true, json: async () => ({}) }
  })
})

const renderPage = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <MemoryRouter><CTSInwardReviewQueue /></MemoryRouter>
  </QueryClientProvider>)

describe('CTSInwardReviewQueue (live)', () => {
  it('shows an item the API says I hold as claimed, with its amount', async () => {
    renderPage()
    expect(await screen.findByText(/Claimed/)).toBeTruthy()
    expect(screen.getByText('₹[<1L]')).toBeTruthy()
  })

  it('Confirm (PAY) calls the real decide endpoint with the CSRF token', async () => {
    renderPage()
    fireEvent.click(await screen.findByText('Confirm (PAY)'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/decide'))).toBe(true))
    const post = calls.find(c => c.url.endsWith('/decide'))
    expect(post.url).toBe('/v1/cts/review/I-1/decide')
    expect(JSON.parse(post.opts.body).action).toBe('CONFIRM')
    expect(post.opts.headers['X-CSRF-Token']).toBe('tok-9')
  })
})
