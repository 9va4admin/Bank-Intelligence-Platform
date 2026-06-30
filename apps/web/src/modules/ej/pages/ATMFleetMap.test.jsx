import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { describe, it, expect } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import ATMFleetMap from './ATMFleetMap'

const renderPage = () => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <ThemeProvider>
          <ATMFleetMap />
        </ThemeProvider>
      </QueryClientProvider>
    </MemoryRouter>
  )
}

describe('ATMFleetMap', () => {
  it('renders page heading', () => {
    renderPage()
    expect(screen.getByText('ATM Fleet Map')).toBeInTheDocument()
  })

  it('renders Refresh button', () => {
    renderPage()
    expect(screen.getByText('Refresh')).toBeInTheDocument()
  })

  it('renders status filter buttons', () => {
    renderPage()
    expect(screen.getByText('All')).toBeInTheDocument()
    expect(screen.getByText('HEALTHY')).toBeInTheDocument()
    expect(screen.getByText('DEGRADED')).toBeInTheDocument()
    expect(screen.getByText('CRITICAL')).toBeInTheDocument()
  })

  it('renders KPI cards', () => {
    renderPage()
    expect(screen.getByText('Total ATMs')).toBeInTheDocument()
    expect(screen.getByText('Healthy')).toBeInTheDocument()
    expect(screen.getByText('Degraded')).toBeInTheDocument()
    expect(screen.getByText('Critical')).toBeInTheDocument()
  })

  it('renders OEM legend', () => {
    renderPage()
    expect(screen.getByText('OEM Legend')).toBeInTheDocument()
  })
})
