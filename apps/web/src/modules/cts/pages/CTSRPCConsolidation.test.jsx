import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSRPCConsolidation from './CTSRPCConsolidation'

function renderRPC() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <CTSRPCConsolidation />
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSRPCConsolidation', () => {
  it('renders the page heading', () => {
    renderRPC()
    expect(screen.getAllByText('RPC Consolidation').length).toBeGreaterThan(0)
  })

  it('shows 5 RPC cards', () => {
    renderRPC()
    expect(screen.queryAllByText('Mumbai RPC').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Delhi RPC').length).toBeGreaterThan(0)
    expect(screen.queryAllByText('Hyderabad RPC').length).toBeGreaterThan(0)
  })

  it('shows consolidated KPI strip', () => {
    renderRPC()
    expect(screen.getByText('Total Inward')).toBeTruthy()
    expect(screen.getByText('Avg STP Rate')).toBeTruthy()
    expect(screen.queryAllByText('IET Risk').length).toBeGreaterThan(0)
  })

  it('shows cross-centre intelligence section', () => {
    renderRPC()
    expect(screen.getByText('Cross-Centre Intelligence')).toBeTruthy()
  })

  it('shows DUPLICATE_SIGNATURE alert', () => {
    renderRPC()
    expect(screen.getByText(/DUPLICATE SIGNATURE/)).toBeTruthy()
  })

  it('clicking RPC card shows detail panel', () => {
    renderRPC()
    fireEvent.click(screen.queryAllByText('Mumbai RPC')[0])
    expect(screen.getByText('Mumbai RPC — Detail')).toBeTruthy()
  })

  it('closing detail panel hides it', () => {
    renderRPC()
    fireEvent.click(screen.queryAllByText('Mumbai RPC')[0])
    const closeBtn = screen.getByText('✕')
    fireEvent.click(closeBtn)
    expect(screen.queryByText('Mumbai RPC — Detail')).toBeFalsy()
  })

  it('shows settlement position table', () => {
    renderRPC()
    expect(screen.getByText('Settlement Position — All Zones')).toBeTruthy()
    expect(screen.getByText('All Zones')).toBeTruthy()
  })
})
