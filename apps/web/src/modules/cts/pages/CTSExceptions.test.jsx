// @vitest-environment jsdom
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

// Render subtitle + actions into the DOM so tests can assert on them
vi.mock('../../../shared/layout/PageHeaderContext', () => ({
  usePageHeader: ({ subtitle, actions } = {}) => {
    // Render into a portal-like div so assertions work
    return null
  },
  PageHeaderCtx: { subtitle: null, actions: null },
  PageHeaderProvider: ({ children }) => <>{children}</>,
}))

import CTSExceptions from './CTSExceptions'

function Wrapper({ children }) {
  return <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter>
}

// Helper: capture what usePageHeader receives
let captured = {}
vi.mock('../../../shared/layout/PageHeaderContext', () => ({
  usePageHeader: (opts = {}) => { captured = opts },
  PageHeaderCtx: {},
  PageHeaderProvider: ({ children }) => <>{children}</>,
}))

describe('CTSExceptions', () => {
  it('renders without crashing', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('passes subtitle with bank name to page header', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(captured.subtitle).toMatch(/Saraswat/)
  })

  it('passes Download CSV button to page header actions', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    // Render the captured actions JSX to assert on it
    render(<div data-testid="actions-check">{captured.actions}</div>, { wrapper: Wrapper })
    expect(screen.getByText(/Download CSV/)).toBeInTheDocument()
  })

  it('shows Total Exceptions KPI', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText('Total Exceptions')).toBeInTheDocument()
  })

  it('shows Critical KPI tile', () => {
    render(<CTSExceptions />, { wrapper: Wrapper })
    expect(screen.getByText('Critical')).toBeInTheDocument()
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
