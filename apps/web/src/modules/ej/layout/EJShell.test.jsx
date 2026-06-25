import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import EJShell from './EJShell'

const renderShell = (pathname = '/ej') =>
  render(
    <MemoryRouter initialEntries={[pathname]}>
      <ThemeProvider>
        <EJShell><div data-testid="content">page</div></EJShell>
      </ThemeProvider>
    </MemoryRouter>
  )

describe('EJShell', () => {
  beforeEach(() => localStorage.clear())

  it('renders children', () => {
    renderShell()
    expect(screen.getByTestId('content')).toBeInTheDocument()
  })

  it('shows ASTRA logo text', () => {
    renderShell()
    expect(screen.getByText('stra')).toBeInTheDocument()
  })

  it('shows EJ Intelligence module label', () => {
    renderShell()
    const items = screen.getAllByText('EJ Intelligence')
    expect(items.length).toBeGreaterThan(0)
  })

  it('shows nav items for operations section', () => {
    renderShell()
    const ccItems = screen.getAllByText('Command Center')
    expect(ccItems.length).toBeGreaterThan(0)
    expect(screen.getByText('Incidents')).toBeInTheDocument()
    expect(screen.getByText('ATM Fleet Map')).toBeInTheDocument()
  })

  it('shows back link to CTS Workstation', () => {
    renderShell()
    expect(screen.getByTitle('CTS Workstation')).toBeInTheDocument()
  })

  it('shows collapse button', () => {
    renderShell()
    expect(screen.getByTitle('Collapse sidebar')).toBeInTheDocument()
  })

  it('collapses sidebar when collapse button clicked', () => {
    renderShell()
    fireEvent.click(screen.getByTitle('Collapse sidebar'))
    expect(screen.getByTitle('Expand sidebar')).toBeInTheDocument()
    expect(screen.queryByText('Incidents')).toBeNull()
  })

  it('shows breadcrumb for /ej route', () => {
    renderShell('/ej')
    const items = screen.getAllByText('Command Center')
    expect(items.length).toBeGreaterThan(0)
  })

  it('shows breadcrumb for /ej/incidents route', () => {
    renderShell('/ej/incidents')
    expect(screen.getByText('Incident Management')).toBeInTheDocument()
  })

  it('shows theme toggle button', () => {
    renderShell()
    const btn = screen.getByTitle(/Switch to/)
    expect(btn).toBeInTheDocument()
  })

  it('toggles theme on button click', () => {
    renderShell()
    const btn = screen.getByTitle('Switch to light')
    fireEvent.click(btn)
    expect(screen.getByTitle('Switch to dark')).toBeInTheDocument()
  })

  it('persists light mode to localStorage', () => {
    renderShell()
    fireEvent.click(screen.getByTitle('Switch to light'))
    expect(localStorage.getItem('astra-theme')).toBe('light')
  })

  it('expands Management section when clicked', () => {
    renderShell('/ej')
    const mgmtBtn = screen.getByText('Management').closest('button')
    fireEvent.click(mgmtBtn)
    expect(screen.getByText('Manager Portal')).toBeInTheDocument()
  })
})
