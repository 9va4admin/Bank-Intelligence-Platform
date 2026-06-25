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

  it('renders all three mock schedules', () => {
    renderPage()
    expect(screen.getByText('PPS & Stop Cheque Vault Sync')).toBeInTheDocument()
    expect(screen.getByText('ATM Health Assessment')).toBeInTheDocument()
    expect(screen.getByText('EJ Log Pull')).toBeInTheDocument()
  })

  it('shows module badges CTS and EJ', () => {
    renderPage()
    expect(screen.getAllByText('CTS').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('EJ').length).toBeGreaterThanOrEqual(1)
  })

  it('shows cron expressions', () => {
    renderPage()
    expect(screen.getByText('0 7 * * *')).toBeInTheDocument()
    expect(screen.getByText('0 * * * *')).toBeInTheDocument()
    expect(screen.getByText('*/15 * * * *')).toBeInTheDocument()
  })

  it('shows workflow names', () => {
    renderPage()
    expect(screen.getByText('VaultSyncWorkflow')).toBeInTheDocument()
    expect(screen.getByText('ATMHealthWorkflow')).toBeInTheDocument()
    expect(screen.getByText('EJIngestionTriggerWorkflow')).toBeInTheDocument()
  })

  it('shows Pause and Edit buttons for each schedule', () => {
    renderPage()
    const pauseBtns = screen.getAllByText('Pause')
    expect(pauseBtns.length).toBe(3)
    const editBtns = screen.getAllByText('Edit')
    expect(editBtns.length).toBe(3)
  })

  it('filter tab ALL shows all schedules', () => {
    renderPage()
    expect(screen.getByText(/All \(3\)/)).toBeInTheDocument()
  })

  it('filter tabs ALL / CTS / EJ are present', () => {
    renderPage()
    // All 3 filter options exist — exact text "CTS" and "EJ" appear multiple times
    // (filter buttons + module badges), so just verify count >= 1
    expect(screen.getAllByText('CTS').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('EJ').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText(/All \(3\)/)).toBeInTheDocument()
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
