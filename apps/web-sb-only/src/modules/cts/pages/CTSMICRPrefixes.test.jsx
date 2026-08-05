import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import { PageHeaderProvider } from '../../../shared/layout/PageHeaderContext'
import CTSMICRPrefixes from './CTSMICRPrefixes'

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/cts/config/micr-prefixes']}>
      <ThemeProvider>
        <PageHeaderProvider>
          <CTSMICRPrefixes />
        </PageHeaderProvider>
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSMICRPrefixes', () => {
  beforeEach(() => localStorage.clear())

  it('renders page heading', () => {
    renderPage()
    expect(screen.getAllByText('MICR Prefix Table').length).toBeGreaterThanOrEqual(1)
  })

  it('shows MICR prefix entries', () => {
    renderPage()
    expect(screen.getByText('400002')).toBeInTheDocument()
    expect(screen.getByText('110002')).toBeInTheDocument()
    expect(screen.getByText('560001')).toBeInTheDocument()
  })

  it('shows bank names', () => {
    renderPage()
    expect(screen.getByText('State Bank of India')).toBeInTheDocument()
    expect(screen.getByText('HDFC Bank')).toBeInTheDocument()
    expect(screen.getByText('ICICI Bank')).toBeInTheDocument()
  })

  it('shows zone filter buttons', () => {
    renderPage()
    expect(screen.getAllByText('MUMBAI').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('DELHI').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('CHENNAI').length).toBeGreaterThanOrEqual(1)
  })

  it('filtering by DELHI shows only Delhi entries', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('DELHI')[0])
    expect(screen.getByText('Punjab National Bank')).toBeInTheDocument()
    expect(screen.queryByText('State Bank of India')).not.toBeInTheDocument()
  })

  it('search filters by prefix', () => {
    renderPage()
    fireEvent.change(screen.getByPlaceholderText(/Search prefix/i), { target: { value: '400002' } })
    expect(screen.getByText('State Bank of India')).toBeInTheDocument()
    expect(screen.queryByText('HDFC Bank')).not.toBeInTheDocument()
  })

  it('shows routing warning callout', () => {
    renderPage()
    expect(screen.getByText(/MICR Routing Note/i)).toBeInTheDocument()
  })

  it('clicking Edit opens edit modal', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    expect(screen.getByText(/Submit for Approval/i)).toBeInTheDocument()
  })

  it('edit modal Cancel closes it', () => {
    renderPage()
    fireEvent.click(screen.getAllByText('Edit')[0])
    fireEvent.click(screen.getByText('Cancel'))
    expect(screen.queryByText('Submit for Approval')).not.toBeInTheDocument()
  })

  it('shows Add Prefix button', () => {
    renderPage()
    expect(screen.getByText('+ Add Prefix')).toBeInTheDocument()
  })
})
