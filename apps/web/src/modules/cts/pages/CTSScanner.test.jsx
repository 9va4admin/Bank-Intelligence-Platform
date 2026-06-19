import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSScanner from './CTSScanner'

vi.useFakeTimers()

function renderScanner() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <CTSScanner />
      </ThemeProvider>
    </MemoryRouter>
  )
}

describe('CTSScanner', () => {
  afterEach(() => {
    vi.clearAllTimers()
  })

  it('renders the page heading', () => {
    renderScanner()
    expect(screen.getAllByText('Scanner SDK').length).toBeGreaterThan(0)
  })

  it('renders all 5 scanner cards', () => {
    renderScanner()
    expect(screen.getByText('SCN-001')).toBeTruthy()
    expect(screen.getByText('SCN-005')).toBeTruthy()
  })

  it('shows Start Scanning button initially', () => {
    renderScanner()
    expect(screen.queryAllByText('Start Scanning').length).toBeGreaterThan(0)
  })

  it('shows Stop Scanning after clicking start', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Scanning/ })
    fireEvent.click(btn)
    expect(screen.queryAllByText('Stop Scanning').length).toBeGreaterThan(0)
  })

  it('shows LIVE indicator when scanning', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Scanning/ })
    fireEvent.click(btn)
    expect(screen.getByText('LIVE')).toBeTruthy()
  })

  it('accumulates scans in the feed over time', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Scanning/ })
    fireEvent.click(btn)
    act(() => { vi.advanceTimersByTime(3000) })
    // At least 1 scan row should appear (every 1400ms)
    const rows = screen.queryAllByText(/SCAN-/)
    expect(rows.length).toBeGreaterThan(0)
  })

  it('shows empty state before scanning starts', () => {
    renderScanner()
    expect(screen.getByText(/Press/)).toBeTruthy()
  })

  it('renders SDK reference section', () => {
    renderScanner()
    expect(screen.getByText('SDK Integration Reference')).toBeTruthy()
    expect(screen.getByText('Panini')).toBeTruthy()
    expect(screen.getByText('Canon')).toBeTruthy()
  })
})
