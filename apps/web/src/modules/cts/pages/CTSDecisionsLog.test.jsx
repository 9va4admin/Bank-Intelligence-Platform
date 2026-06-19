import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import CTSDecisionsLog from './CTSDecisionsLog'

const renderPage = () => render(<MemoryRouter><CTSDecisionsLog /></MemoryRouter>)

describe('CTSDecisionsLog', () => {
  it('renders inside AppShell', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })
  it('shows Decisions Log heading', () => {
    renderPage()
    expect(screen.getByText('Decisions Log')).toBeInTheDocument()
  })
  it('shows summary counts', () => {
    renderPage()
    expect(screen.getByText('Total Filed')).toBeInTheDocument()
    expect(screen.getByText('STP Confirmed')).toBeInTheDocument()
    expect(screen.getByText('STP Returned')).toBeInTheDocument()
    expect(screen.getByText('Human Review')).toBeInTheDocument()
  })
  it('shows all 8 rows by default', () => {
    renderPage()
    expect(screen.getAllByText(/CHQ-2026-/)).toHaveLength(8)
  })
  it('filters to only STP CONFIRM rows', () => {
    renderPage()
    fireEvent.click(screen.getByRole('button', { name: 'STP CONFIRM' }))
    const rows = screen.getAllByText(/CHQ-2026-/)
    expect(rows.length).toBeLessThan(8)
  })
  it('shows NGCH reference column', () => {
    renderPage()
    expect(screen.getByText('NGCH Ref')).toBeInTheDocument()
  })
  it('masks account numbers', () => {
    renderPage()
    const accounts = screen.getAllByText(/^\*{4}\d{4}$/)
    expect(accounts.length).toBeGreaterThan(0)
  })
  it('does not expose full payee names', () => {
    renderPage()
    expect(screen.queryByText('Rajesh Kumar')).not.toBeInTheDocument()
    expect(screen.queryByText('Suresh Patel')).not.toBeInTheDocument()
  })
})
