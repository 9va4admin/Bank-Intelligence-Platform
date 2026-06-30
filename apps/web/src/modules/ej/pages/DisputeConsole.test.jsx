import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import DisputeConsole from './DisputeConsole'

const renderPage = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <DisputeConsole />
        </ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

describe('DisputeConsole', () => {
  it('renders page heading', () => {
    renderPage()
    expect(screen.getByText('Dispute Console')).toBeInTheDocument()
  })

  it('renders Raise Dispute button', () => {
    renderPage()
    expect(screen.getByText('Raise Dispute')).toBeInTheDocument()
  })

  it('renders Refresh button', () => {
    renderPage()
    expect(screen.getByText('Refresh')).toBeInTheDocument()
  })

  it('renders table headers', () => {
    renderPage()
    expect(screen.getByText('NPCI Claim ID')).toBeInTheDocument()
    expect(screen.getByText('ATM ID')).toBeInTheDocument()
    expect(screen.getByText('Amount')).toBeInTheDocument()
    expect(screen.getByText('Status')).toBeInTheDocument()
  })

  it('renders KPI strip', () => {
    renderPage()
    expect(screen.getByText('Total Disputes')).toBeInTheDocument()
    expect(screen.getByText('Auto-Resolved')).toBeInTheDocument()
    expect(screen.getByText('Escalated')).toBeInTheDocument()
    expect(screen.getByText('Pending')).toBeInTheDocument()
  })

  it('renders filter tabs', () => {
    renderPage()
    expect(screen.getByText(/AUTO_RESOLVED/)).toBeInTheDocument()
    expect(screen.getByText(/PENDING/)).toBeInTheDocument()
  })
})
