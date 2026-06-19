import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'

vi.mock('../../../shared/layout/AppShell', () => ({
  default: ({ children }) => <div data-testid="appshell">{children}</div>,
}))

import CTSVaultStatus from './CTSVaultStatus'

const renderPage = () => render(<MemoryRouter><CTSVaultStatus /></MemoryRouter>)

describe('CTSVaultStatus', () => {
  it('renders inside AppShell', () => {
    renderPage()
    expect(screen.getByTestId('appshell')).toBeInTheDocument()
  })
  it('shows Signature Vault card', () => {
    renderPage()
    expect(screen.getByText('Signature Vault')).toBeInTheDocument()
  })
  it('shows PPS Vault card', () => {
    renderPage()
    expect(screen.getByText('PPS Vault')).toBeInTheDocument()
  })
  it('shows both vaults as HEALTHY', () => {
    renderPage()
    expect(screen.getAllByText('HEALTHY')).toHaveLength(2)
  })
  it('shows vault miss section', () => {
    renderPage()
    expect(screen.getByText('Recent Vault Misses')).toBeInTheDocument()
  })
  it('all misses route to HUMAN_REVIEW', () => {
    renderPage()
    const cells = screen.getAllByText('HUMAN_REVIEW')
    expect(cells.length).toBeGreaterThanOrEqual(3)
  })
  it('shows VaultSyncWorkflow log', () => {
    renderPage()
    expect(screen.getByText('VaultSyncWorkflow Log')).toBeInTheDocument()
  })
  it('never shows AUTO_RETURN as miss action', () => {
    renderPage()
    expect(screen.queryByText('AUTO_RETURN')).not.toBeInTheDocument()
  })
})
