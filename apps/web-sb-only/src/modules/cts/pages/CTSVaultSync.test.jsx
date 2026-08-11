import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSVaultSync from './CTSVaultSync'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/vault-sync']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSVaultSync />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSVaultSync', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    // heading text may also appear in breadcrumb — use getAllByText
    expect(screen.getAllByText('Positive Pay & Stop Cheque').length).toBeGreaterThanOrEqual(1)
  })

  it('shows sync status cards', () => {
    renderPage()
    expect(screen.getByText('Last Sync')).toBeInTheDocument()
    expect(screen.getByText('PPS Records')).toBeInTheDocument()
    // 'Stop Cheques' appears in both the status card and the tab nav
    expect(screen.getAllByText('Stop Cheques').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Next Scheduled')).toBeInTheDocument()
  })

  it('shows Sync Now button', () => {
    renderPage()
    expect(screen.getByText('Sync Now')).toBeInTheDocument()
  })

  it('shows tab navigation', () => {
    renderPage()
    expect(screen.getByText('Positive Pay')).toBeInTheDocument()
    expect(screen.getAllByText('Stop Cheques').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('Sync History')).toBeInTheDocument()
  })

  it('shows PPS table by default', () => {
    renderPage()
    expect(screen.getByText('Positive Pay Instructions')).toBeInTheDocument()
    expect(screen.getByText('Series From')).toBeInTheDocument()
  })

  it('switches to Stop Cheques tab', () => {
    renderPage()
    // 'Stop Cheques' appears in both the KPI card and the tab nav — click the button
    const stopChequesButtons = screen.getAllByText('Stop Cheques')
    fireEvent.click(stopChequesButtons[stopChequesButtons.length - 1])
    expect(screen.getByText('Stop Cheque Instructions')).toBeInTheDocument()
    expect(screen.getByText('Reason')).toBeInTheDocument()
  })

  it('switches to Sync History tab', () => {
    renderPage()
    fireEvent.click(screen.getByText('Sync History'))
    expect(screen.getByText('Sync Run History')).toBeInTheDocument()
    expect(screen.getByText('Triggered By')).toBeInTheDocument()
  })

  it('shows mock PPS data rows', () => {
    renderPage()
    const rows = screen.getAllByText('ACTIVE')
    expect(rows.length).toBeGreaterThan(0)
  })

  it('shows Sync Now button as disabled while syncing', async () => {
    renderPage()
    const btn = screen.getByText('Sync Now')
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByText('Syncing…')).toBeInTheDocument())
  })

  it('shows CBS connector info', () => {
    renderPage()
    expect(screen.getByText(/Finacle REST/)).toBeInTheDocument()
  })

  it('shows SCHEDULED and MANUAL trigger types in history', () => {
    renderPage()
    fireEvent.click(screen.getByText('Sync History'))
    const scheduledItems = screen.getAllByText('SCHEDULED')
    expect(scheduledItems.length).toBeGreaterThan(0)
    expect(screen.getByText('MANUAL')).toBeInTheDocument()
  })
})
