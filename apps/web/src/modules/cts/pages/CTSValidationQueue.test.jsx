import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSValidationQueue from './CTSValidationQueue'

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/context/BankContext', () => ({ useBankContext: () => ({ bankId: 'kbl', isDemo: false }) }))
vi.mock('../hooks/useOutwardDecisions', () => ({ default: () => ({ decisions: [] }) }))
vi.mock('../components/ChequeImageViewer', () => ({ default: () => null }))

const NOW = Date.now() / 1000
const VAL_ITEMS = [
  { instrument_id: 'I-1', account_display: '****1234', payee_display: 'A***', amount_range: '₹[1L-5L]', drawee_name: 'Drawee One',
    iet_deadline: NOW + 5400, maker_id: 'maker-1', maker_decision: 'CONFIRM', bucket: 'VAL', stage: 'VALIDATION' },
  { instrument_id: 'I-2', account_display: '****9876', payee_display: 'B***', amount_range: '₹[<1L]', drawee_name: 'Drawee Two',
    iet_deadline: NOW + 7200, maker_id: 'maker-2', maker_decision: 'RETURN', bucket: 'VAL', stage: 'VALIDATION' },
]

let calls
let failValidate
beforeEach(() => {
  calls = []
  failValidate = false
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const path = String(url).split('?')[0]
    calls.push({ path, url: String(url), opts })
    if (path.endsWith('/validate')) {
      return failValidate
        ? { ok: false, status: 403, json: async () => ({ detail: 'You made the first decision on this cheque; a different person must check it' }) }
        : { ok: true, json: async () => ({}) }
    }
    if (path === '/v1/cts/queue') return { ok: true, json: async () => ({ items: VAL_ITEMS }) }
    return { ok: true, json: async () => ({}) }
  })
})
afterEach(() => vi.restoreAllMocks())

const renderPage = () => render(<MemoryRouter><CTSValidationQueue mode="inward" /></MemoryRouter>)

describe('CTSValidationQueue (inward, live)', () => {
  it('lists the cheques in the VAL bucket and shows who made each decision and what it was', async () => {
    renderPage()
    expect(await screen.findByText('I-1')).toBeTruthy()
    expect(screen.getByText('I-2')).toBeTruthy()
    expect(screen.getByText(/maker-1/)).toBeTruthy()
    expect(calls.some(c => c.url.includes('/v1/cts/queue?bucket=VAL'))).toBe(true)
  })

  it('approve means the checker agrees with the maker: it sends the makers decision to the validate endpoint', async () => {
    renderPage()
    await screen.findByText('I-1')
    fireEvent.click(screen.getAllByTitle(/Approve/)[0])
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/validate'))).toBe(true))
    const post = calls.find(c => c.path.endsWith('/validate'))
    expect(post.path).toBe('/v1/cts/review/I-1/validate')
    expect(JSON.parse(post.opts.body)).toEqual({ action: 'CONFIRM', reason: 'Checker agrees with the maker' })
    await waitFor(() => expect(screen.queryByText('I-1')).toBeNull())
  })

  it('approving a cheque the maker returned files that same return', async () => {
    renderPage()
    await screen.findByText('I-2')
    fireEvent.click(screen.getAllByTitle(/Approve/)[1])
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/validate'))).toBe(true))
    expect(JSON.parse(calls.find(c => c.path.endsWith('/validate')).opts.body).action).toBe('RETURN')
  })

  it('return overrules to RETURN with the chosen reason', async () => {
    renderPage()
    await screen.findByText('I-1')
    fireEvent.click(screen.getAllByTitle('Return — select reason')[0])
    const reason = (await screen.findAllByRole('button')).find(b => b.getAttribute('type') === 'button' && b.className.includes('w-full text-left'))
    fireEvent.mouseDown(reason)
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/validate'))).toBe(true))
    const body = JSON.parse(calls.find(c => c.path.endsWith('/validate')).opts.body)
    expect(body.action).toBe('RETURN')
    expect(body.reason.length).toBeGreaterThan(3)
  })

  it('a refused validation (for example the maker trying to check their own work) keeps the row and says why', async () => {
    failValidate = true
    renderPage()
    await screen.findByText('I-1')
    fireEvent.click(screen.getAllByTitle(/Approve/)[0])
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.getByText(/a different person must check it/)).toBeTruthy()
    expect(screen.getByText('I-1')).toBeTruthy()
  })
})

describe('CTSValidationQueue (outward, maker-checker)', () => {
  const STAGED = [{ instrument_id: 'O-1', cheque_number: '1', payee_display: 'P***', amount_range: '₹[<1L]', maker_id: 'maker-9',
                    maker_decision: 'CONFIRMED', maker_reason: 'ok', instrument_category: 'CHEQUE', made_at: '2026-10-28T10:00:00Z' }]
  beforeEach(() => {
    globalThis.fetch = vi.fn(async (url, opts = {}) => {
      const path = String(url).split('?')[0]
      calls.push({ path, url: String(url), opts })
      if (path === '/v1/cts/outward/validation-queue') return { ok: true, json: async () => ({ items: STAGED }) }
      return { ok: true, json: async () => ({}) }
    })
  })

  it('lists the makers staged decisions and approving files the same decision through validate', async () => {
    render(<MemoryRouter><CTSValidationQueue mode="outward" /></MemoryRouter>)
    expect(await screen.findByText('O-1')).toBeTruthy()
    expect(screen.getByText(/maker-9/)).toBeTruthy()
    fireEvent.click(screen.getAllByTitle(/Approve/)[0])
    await waitFor(() => expect(calls.some(c => c.path.endsWith('/outward/review/O-1/validate'))).toBe(true))
    const body = JSON.parse(calls.find(c => c.path.endsWith('/validate')).opts.body)
    expect(body.action).toBe('CONFIRMED')
  })
})
