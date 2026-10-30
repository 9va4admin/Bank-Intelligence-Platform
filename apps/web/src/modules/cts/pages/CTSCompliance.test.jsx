import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSCompliance from './CTSCompliance'

vi.mock('../../../shared/theme/ThemeContext', () => ({ useTheme: () => ({ isDark: false, toggle: vi.fn() }) }))
vi.mock('../../../shared/layout/AppShell', () => ({ default: ({ children }) => <div>{children}</div> }))
vi.mock('../../../shared/layout/PageHeaderContext', () => ({ usePageHeader: () => ({ setHeader: vi.fn() }) }))
vi.mock('../../../shared/context/BankContext', () => ({
  useBankContext: () => ({ bankId: 'kbl', bankName: 'Central Bank of India', bankIfsc: 'CBIN0000001', bankType: 'SB', isSB: true, isSMB: false, isDemo: false }),
}))

beforeEach(() => {
  globalThis.fetch = vi.fn(async () => ({ ok: true, json: async () => ({ items: [] }) }))
})

describe('CTSCompliance with live data', () => {
  it('renders (instead of crashing the whole app) when there are no compliance lots yet', async () => {
    render(<MemoryRouter><CTSCompliance /></MemoryRouter>)
    expect(await screen.findByText(/CTS-2010/i)).toBeTruthy()
  })
})
