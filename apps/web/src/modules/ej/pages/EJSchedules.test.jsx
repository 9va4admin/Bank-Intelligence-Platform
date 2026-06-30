import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import EJSchedules from './EJSchedules'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/ej/schedules']}>
      <ThemeProvider>
        <EJSchedules />
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('EJSchedules', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText(/EJ Temporal Schedules/i).length).toBeGreaterThanOrEqual(1)
  })

  it('shows both EJ schedules', () => {
    renderPage()
    expect(screen.getByText('ATM Health Assessment')).toBeInTheDocument()
    expect(screen.getByText('EJ Log Pull')).toBeInTheDocument()
  })

  it('does NOT show CTS schedule VaultSyncWorkflow label', () => {
    renderPage()
    expect(screen.queryByText('PPS & Stop Cheque Vault Sync')).not.toBeInTheDocument()
  })

  it('shows correct cron expressions', () => {
    renderPage()
    expect(screen.getByText('0 * * * *')).toBeInTheDocument()
    expect(screen.getByText('*/15 * * * *')).toBeInTheDocument()
  })

  it('shows EJ workflow names', () => {
    renderPage()
    expect(screen.getByText('ATMHealthWorkflow')).toBeInTheDocument()
    expect(screen.getByText('EJIngestionTriggerWorkflow')).toBeInTheDocument()
  })

  it('shows Pause and Edit buttons for each schedule', () => {
    renderPage()
    expect(screen.getAllByText('Pause').length).toBe(2)
    expect(screen.getAllByText('Edit').length).toBe(2)
  })

  it('clicking Edit opens modal', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    expect(screen.getByText('Edit Schedule')).toBeInTheDocument()
    expect(screen.getByText('Save Schedule')).toBeInTheDocument()
  })

  it('edit modal Cancel closes it', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Edit Schedule')).not.toBeInTheDocument()
  })

  it('edit modal shows cron input', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    expect(screen.getByPlaceholderText(/e.g. 0 \* \* \* \*/i)).toBeInTheDocument()
  })

  it('shows how-it-works callout', () => {
    renderPage()
    expect(screen.getByText(/How EJ Temporal Schedules work/i)).toBeInTheDocument()
  })

  it('shows SUCCESS run status pills', () => {
    renderPage()
    expect(screen.getAllByText('SUCCESS').length).toBeGreaterThan(0)
  })
})
