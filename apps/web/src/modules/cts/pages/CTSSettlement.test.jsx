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
    expect(screen.getAllByText(/Settlement/i)[0]).toBeTruthy()
  })

  it('shows pipeline stages', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getAllByText('OPEN')[0]).toBeTruthy()
    expect(screen.getAllByText('SETTLED')[0]).toBeTruthy()
  })

  it('shows session list', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    expect(screen.getAllByText(/\d{2}:\d{2}–\d{2}:\d{2}/).length).toBeGreaterThan(0)
  })

  it('shows RECEIVE or PAY direction', () => {
    render(<MemoryRouter><CTSSettlement /></MemoryRouter>)
    const receives = screen.queryAllByText('RECEIVE')
    const pays = screen.queryAllByText('PAY')
    expect(receives.length + pays.length).toBeGreaterThan(0)
  })
})
