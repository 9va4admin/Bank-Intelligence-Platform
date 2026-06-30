import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect } from 'vitest'
import { ThemeProvider } from '../theme/ThemeContext'
import ChequeSearchBar from './ChequeSearchBar'

function renderBar(isDark = true) {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <ChequeSearchBar isDark={isDark} />
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('ChequeSearchBar', () => {
  it('renders search input', () => {
    renderBar()
    expect(screen.getByPlaceholderText(/search cheque/i)).toBeInTheDocument()
  })

  it('does not show dropdown before typing', () => {
    renderBar()
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('does not show dropdown for fewer than 3 characters', () => {
    renderBar()
    fireEvent.change(screen.getByPlaceholderText(/search cheque/i), { target: { value: 'AB' } })
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('Escape keydown closes dropdown without error', () => {
    renderBar()
    const input = screen.getByPlaceholderText(/search cheque/i)
    fireEvent.change(input, { target: { value: 'ABC' } })
    fireEvent.keyDown(input, { key: 'Escape' })
    // Escape closes dropdown — no listbox should remain visible
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('renders in light theme without errors', () => {
    renderBar(false)
    expect(screen.getByPlaceholderText(/search cheque/i)).toBeInTheDocument()
  })

  it('renders in dark theme without errors', () => {
    renderBar(true)
    expect(screen.getByPlaceholderText(/search cheque/i)).toBeInTheDocument()
  })
})
