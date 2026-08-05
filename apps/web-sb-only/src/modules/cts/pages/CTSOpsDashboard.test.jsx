import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSOpsDashboard from './CTSOpsDashboard'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

describe('CTSOpsDashboard', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getByTestId('appshell')).toBeTruthy()
  })

  it('shows KPI labels', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getByText('Total Inward')).toBeTruthy()
    expect(screen.getByText('STP Confirmed')).toBeTruthy()
    expect(screen.getByText('Net Position')).toBeTruthy()
  })

  it('shows session cards', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getAllByText(/SES-/).length).toBeGreaterThan(0)
  })

  it('shows download buttons', () => {
    render(<MemoryRouter><CTSOpsDashboard /></MemoryRouter>)
    expect(screen.getAllByText(/NPCI/i).length).toBeGreaterThan(0)
  })
})
