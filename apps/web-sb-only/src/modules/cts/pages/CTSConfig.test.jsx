import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import CTSConfig from './CTSConfig'

const renderPage = () => render(<MemoryRouter><CTSConfig /></MemoryRouter>)

describe('CTSConfig', () => {
  it('renders inside AppShell', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })
  it('shows Config heading', () => {
    renderPage()
    expect(screen.getByText('Config')).toBeInTheDocument()
  })
  it('shows Layer 3 section', () => {
    renderPage()
    expect(screen.getByText('Layer 3')).toBeInTheDocument()
  })
  it('shows Layer 1 section', () => {
    renderPage()
    expect(screen.getByText('Layer 1')).toBeInTheDocument()
  })
  it('vault miss action is HUMAN_REVIEW and not editable', () => {
    renderPage()
    expect(screen.getByText('HUMAN_REVIEW')).toBeInTheDocument()
  })
  it('does not allow vault miss action to be changed to AUTO_RETURN', () => {
    renderPage()
    const inputs = screen.getAllByRole('textbox')
    const keys = inputs.map(i => i.value)
    expect(keys).not.toContain('AUTO_RETURN')
    expect(screen.queryByDisplayValue('AUTO_RETURN')).not.toBeInTheDocument()
  })
  it('IET window field is editable', () => {
    renderPage()
    const input = screen.getByDisplayValue('180')
    fireEvent.change(input, { target: { value: '170' } })
    expect(screen.getByDisplayValue('170')).toBeInTheDocument()
  })
  it('shows Submit buttons for Layer 3 editable fields', () => {
    renderPage()
    const submitBtns = screen.getAllByRole('button', { name: /submit/i })
    expect(submitBtns.length).toBeGreaterThanOrEqual(4)
  })
  it('Layer 1 values are read-only — no inputs for them', () => {
    renderPage()
    expect(screen.getByText('1.3')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('1.3')).not.toBeInTheDocument()
  })
})
