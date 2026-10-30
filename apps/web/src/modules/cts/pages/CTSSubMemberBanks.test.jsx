import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSSubMemberBanks from './CTSSubMemberBanks'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/config/sub-member-banks']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSSubMemberBanks />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSubMemberBanks', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText(/Sub-Member Banks/i).length).toBeGreaterThanOrEqual(1)
  })

  it('shows all mock sub-members', () => {
    renderPage()
    expect(screen.getByText('Sample Sub-Member Bank 1')).toBeInTheDocument()
    expect(screen.getByText('Sample Sub-Member Bank 2')).toBeInTheDocument()
    expect(screen.getByText('Sample Sub-Member Bank 3')).toBeInTheDocument()
  })

  it('shows stats cards', () => {
    renderPage()
    expect(screen.getByText('Total Sub-Members')).toBeInTheDocument()
    expect(screen.getByText('Active')).toBeInTheDocument()
    expect(screen.getByText('Cheques Today')).toBeInTheDocument()
    expect(screen.getByText('Suspended')).toBeInTheDocument()
  })

  it('shows IFSC prefixes', () => {
    renderPage()
    expect(screen.getByText('SMBA')).toBeInTheDocument()
    expect(screen.getByText('SMBB')).toBeInTheDocument()
    expect(screen.getByText('SMBC')).toBeInTheDocument()
  })

  it('shows risk level badges', () => {
    renderPage()
    expect(screen.getAllByText('LOW').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('MEDIUM')).toBeInTheDocument()
  })

  it('shows ACTIVE status badges and no suspended bank', () => {
    renderPage()
    expect(screen.getAllByText('ACTIVE').length).toBeGreaterThanOrEqual(2)
    expect(screen.queryByText('SUSPENDED')).not.toBeInTheDocument()
  })

  it('clicking View shows detail panel', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('View →')[0])
    expect(screen.getByText('Sub-Member ID')).toBeInTheDocument()
    expect(screen.getByText('Sponsor Account')).toBeInTheDocument()
  })

  it('detail panel can be closed', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('View →')[0])
    fireEvent.click(screen.getByText('✕ Close'))
    expect(screen.queryByText('Sub-Member ID')).not.toBeInTheDocument()
  })

  it('shows Onboard Sub-Member button', () => {
    renderPage()
    expect(screen.getByText('+ Onboard Sub-Member')).toBeInTheDocument()
  })
})
