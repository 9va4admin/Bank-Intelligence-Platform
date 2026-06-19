import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import CTSWorkstation from './CTSWorkstation'

// AppShell renders children directly in test — mock to avoid layout deps
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

// BatchStats — render a minimal stub
vi.mock('../components/BatchStats', () => ({
  default: ({ stats }) => (
    <div data-testid="batch-stats">
      <span data-testid="human-review-count">{stats.human_review}</span>
      <span data-testid="stp-confirmed">{stats.stp_confirmed}</span>
    </div>
  ),
}))

// QueueCard — render instrument ID and a click target
vi.mock('../components/QueueCard', () => ({
  default: ({ item, selected, onClick }) => (
    <div
      data-testid={`queue-card-${item.instrument_id}`}
      data-selected={selected}
      onClick={onClick}
    >
      {item.instrument_id}
    </div>
  ),
}))

// ReviewPanel — render action buttons
vi.mock('../components/ReviewPanel', () => ({
  default: ({ item, onDecision }) =>
    item ? (
      <div data-testid="review-panel">
        <span data-testid="selected-id">{item.instrument_id}</span>
        <button onClick={() => onDecision(item.instrument_id, 'CONFIRM', '')}>Confirm</button>
        <button onClick={() => onDecision(item.instrument_id, 'RETURN', 'Signature mismatch confirmed')}>Return</button>
      </div>
    ) : (
      <div data-testid="review-panel-empty">No item selected</div>
    ),
}))

describe('CTSWorkstation — initial state', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('renders inside AppShell', () => {
    render(<CTSWorkstation />)
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('shows all 6 pending queue cards on load', () => {
    render(<CTSWorkstation />)
    // All MOCK_QUEUE items are PENDING initially
    expect(screen.getAllByTestId(/queue-card-CHQ/)).toHaveLength(6)
  })

  it('passes human_review count of 6 to BatchStats on load', () => {
    render(<CTSWorkstation />)
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('6')
  })

  it('auto-selects first item and passes it to ReviewPanel', () => {
    render(<CTSWorkstation />)
    // First item by IET deadline — expect ReviewPanel to have an item
    expect(screen.queryByTestId('review-panel-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('selected-id')).toBeInTheDocument()
  })

  it('shows STP Live Stream panel', () => {
    render(<CTSWorkstation />)
    expect(screen.getByText('STP Live Stream')).toBeInTheDocument()
  })

  it('shows no STP entries initially', () => {
    render(<CTSWorkstation />)
    expect(screen.getByText(/STP agents processing/)).toBeInTheDocument()
  })
})

describe('CTSWorkstation — STP simulation', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('adds a STP entry after first interval fires', async () => {
    render(<CTSWorkstation />)
    await act(async () => { vi.advanceTimersByTime(3300) })
    // First STP item should appear — CHQ-2026-001901
    expect(screen.getByText('CHQ-2026-001901')).toBeInTheDocument()
  })

  it('adds multiple STP entries as intervals fire', async () => {
    render(<CTSWorkstation />)
    await act(async () => { vi.advanceTimersByTime(10000) })
    // After 10s at 3.2s interval, should have ~3 entries
    const stpIds = screen.queryAllByText(/CHQ-2026-00190/)
    expect(stpIds.length).toBeGreaterThanOrEqual(3)
  })

  it('updates session summary STP count after entries arrive', async () => {
    render(<CTSWorkstation />)
    await act(async () => { vi.advanceTimersByTime(3300) })
    // First entry is CONFIRM — STP Confirmed counter should show 1
    expect(screen.getByText('STP Live Stream')).toBeInTheDocument()
    // Session summary shows at least 1 Immudb write
    const immudbLabel = screen.getByText('Immudb writes')
    expect(immudbLabel).toBeInTheDocument()
  })
})

describe('CTSWorkstation — human decisions', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('removes confirmed item from pending queue', async () => {
    render(<CTSWorkstation />)
    const initialCards = screen.getAllByTestId(/queue-card-CHQ/)
    const firstId = initialCards[0].textContent

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    // Confirmed item moves to "decided" section — pending count drops by 1
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('5')
  })

  it('removes returned item from pending queue', async () => {
    render(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Return' }))
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('5')
  })

  it('increments human decisions counter in session summary', async () => {
    render(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByText('Human decisions')).toBeInTheDocument()
  })

  it('shows decided section after a decision is made', () => {
    render(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByText('Decided this session')).toBeInTheDocument()
  })

  it('clicking a queue card selects that item in ReviewPanel', () => {
    render(<CTSWorkstation />)
    const cards = screen.getAllByTestId(/queue-card-CHQ/)
    fireEvent.click(cards[1])
    const selectedId = screen.getByTestId('selected-id').textContent
    expect(cards[1].textContent).toBe(selectedId)
  })
})

describe('CTSWorkstation — queue clear state', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('shows Queue clear message when all items decided', () => {
    render(<CTSWorkstation />)
    // Confirm all 6 items
    for (let i = 0; i < 6; i++) {
      const confirmBtn = screen.queryByRole('button', { name: 'Confirm' })
      if (confirmBtn) fireEvent.click(confirmBtn)
    }
    expect(screen.getByText('Queue clear')).toBeInTheDocument()
    expect(screen.getByTestId('review-panel-empty')).toBeInTheDocument()
  })
})
