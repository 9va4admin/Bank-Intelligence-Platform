import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import Buckets from './Buckets'

describe('Landing buckets', () => {
  it('shows every problem area as a tab and starts on the first one', () => {
    render(<Buckets />)
    const tabs = screen.getAllByRole('tab')
    expect(tabs.length).toBe(7)
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
  })

  it('shows what the bank has today and what ASTRA achieves, and switches with the tab', () => {
    render(<Buckets />)
    expect(screen.getByText('Today')).toBeTruthy()
    expect(screen.getByText('With ASTRA')).toBeTruthy()
    fireEvent.click(screen.getByRole('tab', { name: 'Compliance and regulators' }))
    expect(screen.getByRole('tabpanel').textContent).toContain('PRAMAAN')
    expect(screen.getByRole('tab', { name: 'Compliance and regulators' }).getAttribute('aria-selected')).toBe('true')
  })

  it('labels only CTS as the first product and never claims the planned ones are live', () => {
    render(<Buckets />)
    fireEvent.click(screen.getByRole('tab', { name: 'Fraud and mule defence' }))
    expect(screen.getByRole('tabpanel').textContent).toContain('Planned')
    fireEvent.click(screen.getByRole('tab', { name: 'Clearing and payments' }))
    expect(screen.getByRole('tabpanel').textContent).toContain('First product')
  })
})
