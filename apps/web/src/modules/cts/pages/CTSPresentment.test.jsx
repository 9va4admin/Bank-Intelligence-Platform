import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSPresentment from './CTSPresentment'

function Wrapper({ children }) {
  return (
    <MemoryRouter>
      <ThemeProvider>{children}</ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSPresentment', () => {
  it('renders without crashing', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
  })

  it('shows NGCH session windows in the session bar', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getByText(/10:00/)).toBeTruthy()
  })

  it('shows Outward pipeline lane labels', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getByText(/Outward Pipeline/)).toBeTruthy()
  })

  it('shows KPI tiles including Total Batch', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getByText('Total Batch')).toBeTruthy()
  })

  it('shows IQA Fail KPI tile', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getAllByText('IQA Fail').length).toBeGreaterThan(0)
  })

  it('shows NGCH ACK KPI tile', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getAllByText(/NGCH ACK/).length).toBeGreaterThan(0)
  })

  it('renders batch list rows with instrument IDs', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getAllByText(/CHQ-OUT-/).length).toBeGreaterThan(0)
  })

  it('shows search and filter toolbar', () => {
    render(<CTSPresentment />, { wrapper: Wrapper })
    expect(screen.getByPlaceholderText(/Search ID/)).toBeTruthy()
  })
})
