import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('./AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import ComingSoon from './ComingSoon'

function renderComingSoon(props) {
  return render(
    <MemoryRouter>
      <ComingSoon {...props} />
    </MemoryRouter>
  )
}

describe('ComingSoon', () => {
  it('renders inside AppShell', () => {
    renderComingSoon({ module: 'Fleet', icon: '◉', desc: 'ATM fleet health.' })
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })

  it('displays module name', () => {
    renderComingSoon({ module: 'Fleet', icon: '◉', desc: 'ATM fleet health.' })
    expect(screen.getByText('Fleet')).toBeInTheDocument()
  })

  it('displays icon', () => {
    renderComingSoon({ module: 'Fleet', icon: '◉', desc: 'ATM fleet health.' })
    expect(screen.getByText('◉')).toBeInTheDocument()
  })

  it('displays description', () => {
    renderComingSoon({ module: 'Fleet', icon: '◉', desc: 'ATM fleet health.' })
    expect(screen.getByText('ATM fleet health.')).toBeInTheDocument()
  })

  it('shows phase 4 badge for Fleet', () => {
    renderComingSoon({ module: 'Fleet', icon: '◉', desc: 'ATM fleet.' })
    expect(screen.getByText(/Coming in Phase 4/i)).toBeInTheDocument()
  })

  it('shows phase 4 badge for Disputes', () => {
    renderComingSoon({ module: 'Disputes', icon: '⚖', desc: 'Disputes.' })
    expect(screen.getByText(/Coming in Phase 4/i)).toBeInTheDocument()
  })

  it('shows phase 3 badge for Audit Trail', () => {
    renderComingSoon({ module: 'Audit Trail', icon: '🔒', desc: 'Audit.' })
    expect(screen.getByText(/Coming in Phase 3/i)).toBeInTheDocument()
  })
})
