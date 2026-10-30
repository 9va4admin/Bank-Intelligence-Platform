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
  it('shows KPI tiles', () => {
    renderPage()
    expect(screen.getByText('Total (7d)')).toBeInTheDocument()
    expect(screen.getAllByText('STP Rate')[0]).toBeInTheDocument()
    expect(screen.getByText('Avg Decision')).toBeInTheDocument()
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
    expect(screen.getByText('Daily Throughput — 7 Sessions')).toBeInTheDocument()
  })
  it('shows fraud score distribution', () => {
    renderPage()
    expect(screen.getByText('Fraud Score Distribution')).toBeInTheDocument()
  })
  it('shows return reasons chart', () => {
    renderPage()
    expect(screen.getByText('Return Reasons')).toBeInTheDocument()
  })
  it('does not show exact amounts', () => {
    renderPage()
    expect(screen.queryByText(/₹\d{5,}/)).not.toBeInTheDocument()
  })
})
