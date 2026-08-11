import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSDiscrepancy from './CTSDiscrepancy'

const Wrap = ({ children }) => (
  <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter>
)

describe('CTSDiscrepancy', () => {
  it('renders heading and KPI strip', () => {
    render(<Wrap><CTSDiscrepancy /></Wrap>)
    expect(screen.getByText('Discrepancy Register')).toBeTruthy()
    expect(screen.getByText('Total Items')).toBeTruthy()
    expect(screen.getByText('Open')).toBeTruthy()
    expect(screen.getByText('Escalated')).toBeTruthy()
  })
  it('renders type sidebar', () => {
    render(<Wrap><CTSDiscrepancy /></Wrap>)
    expect(screen.getByText('Amount Mismatch')).toBeTruthy()
    expect(screen.getByText('MICR Read Error')).toBeTruthy()
  })
  it('renders item rows', () => {
    render(<Wrap><CTSDiscrepancy /></Wrap>)
    expect(screen.getByText('DISC-0001')).toBeTruthy()
  })
})
