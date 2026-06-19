import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import EJShell from './EJShell'

const renderShell = () =>
  render(
    <MemoryRouter>
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

  it('shows ASTRA branding', () => {
    renderShell()
    expect(screen.getByText('ASTRA')).toBeInTheDocument()
  })

  it('shows EJ Intelligence label', () => {
    renderShell()
    expect(screen.getByText('/ EJ Intelligence')).toBeInTheDocument()
  })

  it('shows portal back link', () => {
    renderShell()
    expect(screen.getByText('← Portal')).toBeInTheDocument()
  })

  it('shows sun icon in dark mode (default)', () => {
    renderShell()
    expect(screen.getByTitle('Switch to light mode')).toBeInTheDocument()
  })

  it('switches to moon icon after toggle', () => {
    renderShell()
    fireEvent.click(screen.getByTitle('Switch to light mode'))
    expect(screen.getByTitle('Switch to dark mode')).toBeInTheDocument()
  })

  it('persists light mode to localStorage', () => {
    renderShell()
    fireEvent.click(screen.getByTitle('Switch to light mode'))
    expect(localStorage.getItem('astra-theme')).toBe('light')
  })
})
