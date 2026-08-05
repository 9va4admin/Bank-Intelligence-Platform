import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSNGCHRouting from './CTSNGCHRouting'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/config/ngch-routing']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSNGCHRouting />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSNGCHRouting', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText('NGCH Routing').length).toBeGreaterThanOrEqual(1)
  })

  it('shows NGCH connectivity status', () => {
    renderPage()
    expect(screen.getByText('CONNECTED')).toBeInTheDocument()
    expect(screen.getByText('SFTP Host')).toBeInTheDocument()
    expect(screen.getByText('ngch.npci.org.in')).toBeInTheDocument()
  })

  it('shows routing rules', () => {
    renderPage()
    expect(screen.getByText('Default Mumbai Zone')).toBeInTheDocument()
    expect(screen.getByText('Default Delhi Zone')).toBeInTheDocument()
    expect(screen.getByText('High-Value Override')).toBeInTheDocument()
    expect(screen.getByText('IET Emergency Fallback')).toBeInTheDocument()
  })

  it('shows rule type badges', () => {
    renderPage()
    expect(screen.getAllByText('ZONE').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('OVERRIDE')).toBeInTheDocument()
    expect(screen.getByText('EMERGENCY')).toBeInTheDocument()
  })

  it('shows priority labels', () => {
    renderPage()
    expect(screen.getByText('P1')).toBeInTheDocument()
    expect(screen.getByText('P3')).toBeInTheDocument()
    expect(screen.getAllByText('P10').length).toBeGreaterThanOrEqual(1)
  })

  it('clicking a rule shows detail panel', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Detail →')[0])
    expect(screen.getAllByText('Condition').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Filings Today').length).toBeGreaterThanOrEqual(1)
  })

  it('detail panel closes on dismiss', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Detail →')[0])
    fireEvent.click(screen.getByText('✕ Close'))
    expect(screen.queryByText('Filings Today')).not.toBeInTheDocument()
  })

  it('emergency rule shows locked notice', () => {
    renderPage()
    const emergencyRow = screen.getByText('IET Emergency Fallback').closest('tr')
    fireEvent.click(emergencyRow.querySelector('button'))
    expect(screen.getByText(/Emergency routing rule/i)).toBeInTheDocument()
  })

  it('shows filed today counts', () => {
    renderPage()
    expect(screen.getByText('1,842')).toBeInTheDocument()
  })
})
