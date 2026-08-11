import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSImageQuality from './CTSImageQuality'

function Wrapper({ children }) {
  return (
    <ThemeProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </ThemeProvider>
  )
}

describe('CTSImageQuality', () => {
  it('renders IQA page with KPI strip', () => {
    render(<CTSImageQuality />, { wrapper: Wrapper })
    expect(screen.getByText(/Image Quality/i)).toBeTruthy()
  })
})
