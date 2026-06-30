import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSSMBForwardingLog from './CTSSMBForwardingLog'

function Wrapper({ children }) {
  return (
    <MemoryRouter>
      <ThemeProvider>{children}</ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSSMBForwardingLog', () => {
  it('renders forwarding log heading', () => {
    render(<CTSSMBForwardingLog />, { wrapper: Wrapper })
    expect(screen.getByText(/SMB Forwarding Log/i)).toBeTruthy()
  })

  it('shows status filter', () => {
    render(<CTSSMBForwardingLog />, { wrapper: Wrapper })
    expect(screen.getByText(/All Statuses/i)).toBeTruthy()
  })
})
