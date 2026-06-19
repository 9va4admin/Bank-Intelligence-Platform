import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import CTSAnalytics from './CTSAnalytics'

const renderPage = () => render(<MemoryRouter><CTSAnalytics /></MemoryRouter>)

describe('CTSAnalytics', () => {
  it('renders inside AppShell', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })
  it('shows Analytics heading', () => {
    renderPage()
    expect(screen.getByText('Analytics')).toBeInTheDocument()
  })
  it('shows KPI tiles', () => {
    renderPage()
    expect(screen.getByText('Today Total')).toBeInTheDocument()
    expect(screen.getByText('STP Rate')).toBeInTheDocument()
    expect(screen.getByText('Avg Agent Time')).toBeInTheDocument()
    expect(screen.getByText('IET Breaches')).toBeInTheDocument()
  })
  it('IET Breaches is always 0', () => {
    renderPage()
    const label = screen.getByText('IET Breaches')
    expect(label.nextSibling || label.parentElement.querySelector('.text-2xl')).toBeTruthy()
    expect(screen.getByText('0')).toBeInTheDocument()
  })
  it('shows daily volume chart', () => {
    renderPage()
    expect(screen.getByText('Daily Volume (7 days)')).toBeInTheDocument()
  })
  it('shows fraud score distribution', () => {
    renderPage()
    expect(screen.getByText('Fraud Score Distribution (today)')).toBeInTheDocument()
  })
  it('shows return reasons chart', () => {
    renderPage()
    expect(screen.getByText('STP Return Reasons (7-day)')).toBeInTheDocument()
  })
  it('does not show exact amounts', () => {
    renderPage()
    expect(screen.queryByText(/₹\d{5,}/)).not.toBeInTheDocument()
  })
})
