import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSSettlement from './CTSSettlement'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

describe('CTSSettlement', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getByTestId('appshell')).toBeTruthy()
  })

  it('shows settlement heading', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getByText(/Settlement/i)).toBeTruthy()
  })

  it('shows pipeline stages', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getByText('OPEN')).toBeTruthy()
    expect(screen.getByText('SETTLED')).toBeTruthy()
  })

  it('shows session list', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getAllByText(/SES-/).length).toBeGreaterThan(0)
  })

  it('shows RECEIVE or PAY direction', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    const receives = screen.queryAllByText('RECEIVE')
    const pays = screen.queryAllByText('PAY')
    expect(receives.length + pays.length).toBeGreaterThan(0)
  })
})
