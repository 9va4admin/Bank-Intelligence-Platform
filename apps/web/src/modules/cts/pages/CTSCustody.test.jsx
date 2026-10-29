import { describe, it, expect, vi, beforeEach, beforeAll } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false }) }))
vi.mock('../../../shared/api/csrf', () => ({ csrfHeader: () => ({ 'X-CSRF-Token': 't' }) }))

import CTSCustody from './CTSCustody'
import { initMessages } from '../../../shared/messages'

beforeAll(async () => { await initMessages('en') })

const PENDING = { hold_days: 7, items: [
  { instrument_id: 'I1', cheque_number: '000111', branch_id: 'B1', payee_display: 'P***', amount_range: 'r', age_days: 9.2, overdue: true },
  { instrument_id: 'I2', cheque_number: '000222', branch_id: 'B1', payee_display: 'Q***', amount_range: 'r', age_days: 1, overdue: false },
] }

let calls
beforeEach(() => {
  calls = []
  global.fetch = vi.fn(async (url, opts = {}) => {
    calls.push([url, opts.method ?? 'GET', opts.body])
    const json = (b, ok = true) => ({ ok, json: async () => b })
    if (url.endsWith('/pending')) return json(PENDING)
    if (url.includes('/handovers?status')) return json({ handovers: [] })
    if (url.endsWith('/due-for-disposal')) return json({ items: [] })
    if (url.endsWith('/handovers') && opts.method === 'POST') return json({ handover_id: 'HO-1', status: 'IN_TRANSIT', item_count: 1 })
    return json({})
  })
})

describe('CTSCustody', () => {
  it('flags originals held longer than the configured hold days', async () => {
    render(<CTSCustody />)
    expect(await screen.findByText(/overdue/)).toBeTruthy()
    expect(screen.getByText(/up to 7 days/)).toBeTruthy()
  })

  it('hands over the selected originals with the courier reference and the CSRF header', async () => {
    render(<CTSCustody />)
    fireEvent.click(await screen.findByLabelText('Select I1'))
    fireEvent.change(screen.getByPlaceholderText(/Courier/), { target: { value: 'AWB-9' } })
    fireEvent.click(screen.getByText(/Hand over/))
    await waitFor(() => expect(calls.some(c => c[1] === 'POST' && c[0].endsWith('/handovers'))).toBe(true))
    const post = calls.find(c => c[1] === 'POST')
    expect(JSON.parse(post[2])).toEqual({ branch_id: 'B1', instrument_ids: ['I1'], courier_ref: 'AWB-9' })
  })
})
