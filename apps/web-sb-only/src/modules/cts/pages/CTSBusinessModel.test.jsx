import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSBusinessModel from './CTSBusinessModel'

function Wrapper({ children }) {
  return (
    <ThemeProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </ThemeProvider>
  )
}

describe('CTSBusinessModel', () => {
  it('renders business model page with KPI cards', () => {
    render(<CTSBusinessModel />, { wrapper: Wrapper })
    expect(screen.getByText(/Business Model/i)).toBeTruthy()
  })
})
