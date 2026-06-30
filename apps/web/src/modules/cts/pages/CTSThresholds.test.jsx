import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSThresholds from './CTSThresholds'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/config/thresholds']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSThresholds />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSThresholds', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText('Thresholds & Rules').length).toBeGreaterThanOrEqual(1)
  })

  it('shows critical threshold entries', () => {
    renderPage()
    expect(screen.getByText('IET Window')).toBeInTheDocument()
    expect(screen.getByText('STP Auto-Confirm Score')).toBeInTheDocument()
    expect(screen.getByText('Human Review Trigger Score')).toBeInTheDocument()
    expect(screen.getByText('High-Value Cheque Limit')).toBeInTheDocument()
  })

  it('shows locked vault miss action', () => {
    renderPage()
    expect(screen.getByText('Vault Miss Action')).toBeInTheDocument()
    expect(screen.getByText('HUMAN_REVIEW')).toBeInTheDocument()
    expect(screen.getAllByText('LOCKED').length).toBeGreaterThanOrEqual(1)
  })

  it('shows Layer badges', () => {
    renderPage()
    expect(screen.getAllByText('Layer 3').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Layer 1').length).toBeGreaterThanOrEqual(1)
  })

  it('shows CRITICAL warning badges', () => {
    renderPage()
    expect(screen.getAllByText('CRITICAL').length).toBeGreaterThanOrEqual(1)
  })

  it('category filters work', () => {
    renderPage()
    fireEvent.click(screen.getByText('Fraud Scoring'))
    expect(screen.getByText('STP Auto-Confirm Score')).toBeInTheDocument()
    expect(screen.queryByText('IET Window')).not.toBeInTheDocument()
  })

  it('clicking Edit on editable threshold opens modal', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    expect(screen.getByText('Submit for Approval')).toBeInTheDocument()
  })

  it('edit modal Cancel closes it', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Submit for Approval')).not.toBeInTheDocument()
  })

  it('change log tab shows history', () => {
    renderPage()
    fireEvent.click(screen.getByText('Change Log'))
    expect(screen.getAllByText('ops_manager@svcb').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('LIVE').length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText('PENDING')).toBeInTheDocument()
  })

  it('shows hot-reload description', () => {
    renderPage()
    expect(screen.getByText(/hot-reload within 30 seconds/i)).toBeInTheDocument()
  })
})
