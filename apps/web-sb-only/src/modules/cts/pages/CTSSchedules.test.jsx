import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSSchedules from './CTSSchedules'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/schedules']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSSchedules />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSchedules', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText('Temporal Schedules').length).toBeGreaterThanOrEqual(1)
  })

  it('shows running count indicator', () => {
    renderPage()
    expect(screen.getAllByText(/running/i).length).toBeGreaterThanOrEqual(1)
  })

  it('renders CTS-only schedule', () => {
    renderPage()
    expect(screen.getByText('PPS & Stop Cheque Vault Sync')).toBeInTheDocument()
  })

  it('does NOT show EJ schedules', () => {
    renderPage()
    expect(screen.queryByText('ATM Health Assessment')).not.toBeInTheDocument()
    expect(screen.queryByText('EJ Log Pull')).not.toBeInTheDocument()
  })

  it('shows correct CTS cron expression', () => {
    renderPage()
    expect(screen.getByText('0 7 * * *')).toBeInTheDocument()
  })

  it('shows VaultSyncWorkflow name', () => {
    renderPage()
    expect(screen.getByText('VaultSyncWorkflow')).toBeInTheDocument()
  })

  it('shows Pause and Edit buttons', () => {
    renderPage()
    expect(screen.getAllByText('Pause').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Edit').length).toBeGreaterThanOrEqual(1)
  })

  it('clicking Edit opens the edit modal', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    expect(screen.getByText('Edit Schedule')).toBeInTheDocument()
    expect(screen.getByText('Save Schedule')).toBeInTheDocument()
  })

  it('edit modal shows Cancel button that closes it', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Edit Schedule')).not.toBeInTheDocument()
  })

  it('edit modal shows cron expression input', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    const input = screen.getByPlaceholderText(/e.g. 0 7 \* \* \*/i)
    expect(input).toBeInTheDocument()
  })

  it('shows how-it-works callout', () => {
    renderPage()
    expect(screen.getByText(/How Temporal Schedules work in ASTRA/i)).toBeInTheDocument()
  })

  it('shows SUCCESS run status pills', () => {
    renderPage()
    const pills = screen.getAllByText('SUCCESS')
    expect(pills.length).toBeGreaterThan(0)
  })
})
