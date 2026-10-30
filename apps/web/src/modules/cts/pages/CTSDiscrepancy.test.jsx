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
    expect(screen.getAllByText('Open')[0]).toBeTruthy()
    expect(screen.getAllByText('Escalated')[0]).toBeTruthy()
  })
  it('renders type sidebar', () => {
    render(<Wrap><CTSDiscrepancy /></Wrap>)
    expect(screen.getAllByText('Amount Mismatch')[0]).toBeTruthy()
    expect(screen.getAllByText('MICR Read Error')[0]).toBeTruthy()
  })
  it('renders item rows', () => {
    render(<Wrap><CTSDiscrepancy /></Wrap>)
    expect(screen.getByText('DISC-0001')).toBeTruthy()
  })
})
