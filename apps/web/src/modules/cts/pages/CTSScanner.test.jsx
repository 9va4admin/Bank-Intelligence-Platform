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

  it('shows scanner agent status bar with URL', () => {
    renderScanner()
    expect(screen.getByText('Scanner Agent')).toBeTruthy()
    expect(screen.getByText('http://localhost:9201')).toBeTruthy()
  })

  it('shows Start Session button initially', () => {
    renderScanner()
    expect(screen.queryAllByText('Start Session').length).toBeGreaterThan(0)
  })

  it('shows Stop Session after clicking start', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Session/ })
    fireEvent.click(btn)
    expect(screen.queryAllByText('Stop Session').length).toBeGreaterThan(0)
  })

  it('shows LIVE indicator when session active', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Session/ })
    fireEvent.click(btn)
    expect(screen.getAllByText('LIVE').length).toBeGreaterThan(0)
  })

  it('accumulates scans in the feed over time', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: /Start Session/ })
    fireEvent.click(btn)
    act(() => { vi.advanceTimersByTime(4000) })
    const rows = screen.queryAllByText(/SCAN-/)
    expect(rows.length).toBeGreaterThan(0)
  })

  it('shows empty state before session starts', () => {
    renderScanner()
    expect(screen.getByText(/Start Session/)).toBeTruthy()
  })

  it('renders Kafka topics section', () => {
    renderScanner()
    expect(screen.getByText('Kafka Topics — Outward Clearing')).toBeTruthy()
    expect(screen.getByText('Scanned')).toBeTruthy()
    expect(screen.getByText('Lot Sealed')).toBeTruthy()
    expect(screen.getByText('Submitted')).toBeTruthy()
  })

  it('renders SDK reference section', () => {
    renderScanner()
    expect(screen.getByText('SDK Integration Reference')).toBeTruthy()
    expect(screen.getByText('Canon CR-120')).toBeTruthy()
    expect(screen.getByText('Scanner Agent')).toBeTruthy()
  })

  it('renders pipeline KPI strip with 8 metrics', () => {
    renderScanner()
    expect(screen.getByText('Accepted')).toBeTruthy()
    expect(screen.getByText('CTS Rejected')).toBeTruthy()
    expect(screen.getByText('Mismatch Held')).toBeTruthy()
    expect(screen.getByText('Human Review')).toBeTruthy()
    expect(screen.getByText('MICR OK')).toBeTruthy()
  })

  it('shows audit events tab with CTS_OUT_* messages', () => {
    renderScanner()
    expect(screen.getAllByText(/CTS_OUT_/).length).toBeGreaterThan(0)
  })

  it('switches to Lots tab when clicked', () => {
    renderScanner()
    const lotsTab = screen.getByRole('button', { name: 'Lots' })
    fireEvent.click(lotsTab)
    expect(screen.getAllByText(/LOT-/).length).toBeGreaterThan(0)
  })

  it('switches to Msg Taxonomy tab when clicked', () => {
    renderScanner()
    const taxTab = screen.getByRole('button', { name: 'Msg Taxonomy' })
    fireEvent.click(taxTab)
    expect(screen.getByText('CTS_OUT_CTS2010_FAIL')).toBeTruthy()
    expect(screen.getByText('CTS_OUT_MISMATCH_HELD')).toBeTruthy()
  })

  it('shows Configure button that opens config panel', () => {
    renderScanner()
    const btn = screen.getByRole('button', { name: 'Configure' })
    fireEvent.click(btn)
    expect(screen.getByText('Scanner Agent Configuration')).toBeTruthy()
    expect(screen.getByPlaceholderText('http://localhost:9201')).toBeTruthy()
  })
})
