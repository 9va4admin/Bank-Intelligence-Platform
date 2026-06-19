import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, beforeEach } from 'vitest'
import { ThemeProvider, useTheme } from './ThemeContext'

function Toggle() {
  const { theme, toggle, isDark } = useTheme()
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="isDark">{String(isDark)}</span>
      <button onClick={toggle}>toggle</button>
    </div>
  )
}

const renderWithProvider = () =>
  render(<ThemeProvider><Toggle /></ThemeProvider>)

describe('ThemeContext', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to dark theme', () => {
    renderWithProvider()
    expect(screen.getByTestId('theme').textContent).toBe('dark')
  })

  it('isDark is true initially', () => {
    renderWithProvider()
    expect(screen.getByTestId('isDark').textContent).toBe('true')
  })

  it('toggles to light on click', () => {
    renderWithProvider()
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByTestId('theme').textContent).toBe('light')
    expect(screen.getByTestId('isDark').textContent).toBe('false')
  })

  it('toggles back to dark on second click', () => {
    renderWithProvider()
    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByRole('button'))
    expect(screen.getByTestId('theme').textContent).toBe('dark')
  })

  it('persists theme to localStorage', () => {
    renderWithProvider()
    fireEvent.click(screen.getByRole('button'))
    expect(localStorage.getItem('astra-theme')).toBe('light')
  })

  it('reads persisted theme from localStorage', () => {
    localStorage.setItem('astra-theme', 'light')
    renderWithProvider()
    expect(screen.getByTestId('theme').textContent).toBe('light')
    expect(screen.getByTestId('isDark').textContent).toBe('false')
  })

  it('sets data-theme attribute on documentElement', () => {
    renderWithProvider()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    fireEvent.click(screen.getByRole('button'))
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })
})
