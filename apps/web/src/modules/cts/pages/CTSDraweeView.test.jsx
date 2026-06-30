import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import CTSDraweeView from './CTSDraweeView'

vi.mock('../../../shared/theme/ThemeContext', () => ({
  useTheme: () => ({ isDark: false, toggle: vi.fn() }),
}))
vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

describe('CTSDraweeView', () => {
  it('renders without crashing', () => {
    render(<MemoryRouter><CTSDraweeView /></MemoryRouter>)
    expect(screen.getByTestId('appshell')).toBeTruthy()
  })

  it('shows outward heading', () => {
    render(<MemoryRouter><CTSDraweeView /></MemoryRouter>)
    expect(screen.getByText(/Outward/i)).toBeTruthy()
  })

  it('shows branch names', () => {
    render(<MemoryRouter><CTSDraweeView /></MemoryRouter>)
    expect(screen.getByText('Churchgate')).toBeTruthy()
    expect(screen.getByText('Andheri (W)')).toBeTruthy()
  })

  it('shows return reasons section', () => {
    render(<MemoryRouter><CTSDraweeView /></MemoryRouter>)
    expect(screen.getByText(/Return Reasons/i)).toBeTruthy()
  })

  it('shows summary KPIs', () => {
    render(<MemoryRouter><CTSDraweeView /></MemoryRouter>)
    expect(screen.getByText('Total Outward')).toBeTruthy()
    expect(screen.getByText('NGCH Returned')).toBeTruthy()
  })
})
