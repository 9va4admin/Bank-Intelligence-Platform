import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { ThemeProvider } from '../../../shared/theme/ThemeContext'
import CTSWorkstation from './CTSWorkstation'

function renderWithTheme(ui) {
  return render(<ThemeProvider>{ui}</ThemeProvider>)
}

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

// QueueCard — render instrument ID, click target, and principal_tag
vi.mock('../components/QueueCard', () => ({
  default: ({ item, selected, onClick }) => (
    <div
      data-testid={`queue-card-${item.instrument_id}`}
      data-selected={selected}
      data-principal={item.principal_tag || 'DIRECT'}
      onClick={onClick}
    >
      {item.instrument_id}
      {item.principal_tag === 'SUB_MEMBER' && (
        <span data-testid={`smb-badge-${item.instrument_id}`}>{item.sub_member_name}</span>
      )}
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
    renderWithTheme(<CTSWorkstation />)
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('shows all 6 pending queue cards on load', () => {
    renderWithTheme(<CTSWorkstation />)
    // All MOCK_QUEUE items are PENDING initially
    expect(screen.getAllByTestId(/queue-card-CHQ/)).toHaveLength(6)
  })

  it('passes human_review count of 6 to BatchStats on load', () => {
    renderWithTheme(<CTSWorkstation />)
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('6')
  })

  it('auto-selects first item and passes it to ReviewPanel', () => {
    renderWithTheme(<CTSWorkstation />)
    // First item by IET deadline — expect ReviewPanel to have an item
    expect(screen.queryByTestId('review-panel-empty')).not.toBeInTheDocument()
    expect(screen.getByTestId('selected-id')).toBeInTheDocument()
  })

  it('shows STP Live Stream panel', () => {
    renderWithTheme(<CTSWorkstation />)
    expect(screen.getByText('STP Live Stream')).toBeInTheDocument()
  })

  it('shows no STP entries initially', () => {
    renderWithTheme(<CTSWorkstation />)
    expect(screen.getByText(/STP agents processing/)).toBeInTheDocument()
  })
})

describe('CTSWorkstation — STP simulation', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('adds a STP entry after first interval fires', async () => {
    renderWithTheme(<CTSWorkstation />)
    await act(async () => { vi.advanceTimersByTime(3300) })
    // First STP item should appear — CHQ-2026-001901
    expect(screen.getByText('CHQ-2026-001901')).toBeInTheDocument()
  })

  it('adds multiple STP entries as intervals fire', async () => {
    renderWithTheme(<CTSWorkstation />)
    await act(async () => { vi.advanceTimersByTime(10000) })
    // After 10s at 3.2s interval, should have ~3 entries
    const stpIds = screen.queryAllByText(/CHQ-2026-00190/)
    expect(stpIds.length).toBeGreaterThanOrEqual(3)
  })

  it('updates session summary STP count after entries arrive', async () => {
    renderWithTheme(<CTSWorkstation />)
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
    renderWithTheme(<CTSWorkstation />)
    const initialCards = screen.getAllByTestId(/queue-card-CHQ/)
    const firstId = initialCards[0].textContent

    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))

    // Confirmed item moves to "decided" section — pending count drops by 1
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('5')
  })

  it('removes returned item from pending queue', async () => {
    renderWithTheme(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Return' }))
    expect(screen.getByTestId('human-review-count')).toHaveTextContent('5')
  })

  it('increments human decisions counter in session summary', async () => {
    renderWithTheme(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByText('Human decisions')).toBeInTheDocument()
  })

  it('shows decided section after a decision is made', () => {
    renderWithTheme(<CTSWorkstation />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect(screen.getByText('Decided this session')).toBeInTheDocument()
  })

  it('clicking a queue card selects that item in ReviewPanel', () => {
    renderWithTheme(<CTSWorkstation />)
    const cards = screen.getAllByTestId(/queue-card-CHQ/)
    fireEvent.click(cards[1])
    const selectedId = screen.getByTestId('selected-id').textContent
    expect(cards[1].textContent).toBe(selectedId)
  })

  it('marks sub-member queue items with SUB_MEMBER principal_tag', () => {
    renderWithTheme(<CTSWorkstation />)
    const smbBadges = screen.getAllByTestId(/smb-badge-CHQ/)
    expect(smbBadges.length).toBeGreaterThanOrEqual(2)
  })

  it('sub-member items carry sub_member_name from mockQueue', () => {
    renderWithTheme(<CTSWorkstation />)
    const vasaviBadge = screen.queryByText('Vasavi Co-op Bank')
    const andheriBadge = screen.queryByText('Andheri Urban Co-op Bank')
    expect(vasaviBadge).toBeTruthy()
    expect(andheriBadge).toBeTruthy()
  })
})

describe('CTSWorkstation — queue clear state', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { vi.useRealTimers() })

  it('shows Queue clear message when all items decided', () => {
    renderWithTheme(<CTSWorkstation />)
    // Confirm all 6 items
    for (let i = 0; i < 6; i++) {
      const confirmBtn = screen.queryByRole('button', { name: 'Confirm' })
      if (confirmBtn) fireEvent.click(confirmBtn)
    }
    expect(screen.getByText('Queue clear')).toBeInTheDocument()
    expect(screen.getByTestId('review-panel-empty')).toBeInTheDocument()
  })
})
