import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSSMBLedger from './CTSSMBLedger'

function Wrapper({ children }) {
  return (
    <MemoryRouter>
      <ThemeProvider>{children}</ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSMBLedger', () => {
  it('renders SMB ledger heading', () => {
    render(<CTSSMBLedger />, { wrapper: Wrapper })
    expect(screen.getByText(/SMB Clearing Ledger/i)).toBeTruthy()
  })

  it('shows session date filter', () => {
    render(<CTSSMBLedger />, { wrapper: Wrapper })
    expect(screen.getByDisplayValue(/2026-06-26/i)).toBeTruthy()
  })
})
