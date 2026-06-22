import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSBatches from './CTSBatches'

const Wrap = ({ children }) => (
  <MemoryRouter><ThemeProvider>{children}</ThemeProvider></MemoryRouter>
)

describe('CTSBatches', () => {
  it('renders heading and KPIs', () => {
    render(<Wrap><CTSBatches /></Wrap>)
    expect(screen.getByText('Batch / Lot Processing')).toBeTruthy()
    expect(screen.getByText('Total Lots')).toBeTruthy()
    expect(screen.getByText('Instruments')).toBeTruthy()
    expect(screen.getByText('Count Mismatch')).toBeTruthy()
  })
  it('renders session badges', () => {
    render(<Wrap><CTSBatches /></Wrap>)
    expect(screen.getByText(/CLOSED/)).toBeTruthy()
    expect(screen.getByText(/ACTIVE/)).toBeTruthy()
  })
  it('renders lot table rows', () => {
    render(<Wrap><CTSBatches /></Wrap>)
    expect(screen.getByText('0000001')).toBeTruthy()
  })
})
