import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSOutwardQueue from './CTSOutwardQueue'

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/layout/PageHeaderContext', () => ({ usePageHeader: () => ({}) }))
vi.mock('../../../shared/context/BankContext', () => ({
  useBankContext: () => ({ bankId: 'kbl', bankName: 'Central Bank of India', isSMB: false, isDemo: false }),
}))
vi.mock('../components/ChequeImageViewer', () => ({ default: () => null }))

const item = (id, over = {}) => ({ instrument_id: id, cheque_number: id, payee_display: 'P***', amount_range: '₹[<1L]', outcome: 'HUMAN_REVIEW',
  received_at: '2026-10-29T10:00:00Z', branch_id: 'b1', instrument_category: 'CHEQUE', assigned_to: null, assigned_to_me: false, ...over })

beforeEach(() => {
  sessionStorage.setItem('astra-csrf', 'tok-o')
  globalThis.fetch = vi.fn(async (url) => {
    if (String(url).includes('/outward/human-review-queue')) {
      return { ok: true, json: async () => ({ items: [item('O-FREE'), item('O-MINE', { assigned_to: 'usr-me', assigned_to_me: true }),
                                                      item('O-THEIRS', { assigned_to: 'usr-other' })] }) }
    }
    return { ok: true, json: async () => ({}) }
  })
})

describe('CTSOutwardQueue (live)', () => {
  it('shows who holds each held cheque: yours, held by someone else, or free', async () => {
    render(<MemoryRouter><CTSOutwardQueue /></MemoryRouter>)
    expect(await screen.findByText(/· yours/)).toBeTruthy()
    expect(screen.getByText(/held by usr-other/)).toBeTruthy()
  })
})
