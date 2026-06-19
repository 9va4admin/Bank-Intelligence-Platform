import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import CTSExceptions from './CTSExceptions'

function Wrapper({ children }) {
  return <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter>
}

describe('CTSExceptions', () => {
  it('renders without crashing', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('shows Exception Report heading', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText('Exception Report')).toBeInTheDocument()
  })

  it('shows Total Exceptions KPI', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText('Total Exceptions')).toBeInTheDocument()
  })

  it('shows Critical KPI tile', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('shows Download CSV button', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText(/Download CSV/)).toBeInTheDocument()
  })

  it('shows exception rows in table', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getAllByText(/CHQ-IN-/).length).toBeGreaterThan(0)
  })

  it('shows IET_NEAR_BREACH exception', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getAllByText(/IET Near-Breach/).length).toBeGreaterThan(0)
  })

  it('shows severity filter buttons', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getAllByText(/CRITICAL/).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/HIGH/).length).toBeGreaterThan(0)
  })
})
