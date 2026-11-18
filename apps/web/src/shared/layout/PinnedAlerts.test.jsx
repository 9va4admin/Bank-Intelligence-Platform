import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import PinnedAlerts from './PinnedAlerts'

const item = (id, over = {}) => ({ notification_id: id, incident_id: 'inc-' + id, severity: 'P0', title: `down-${id}`, body: `why-${id}`, action_link: '/ops/incidents/inc-' + id,
  created_at: new Date().toISOString(), read_at: null, acked_at: null, ...over })

describe('PinnedAlerts', () => {
  it('shows nothing when there is nothing critical to acknowledge', () => {
    const { container } = render(<PinnedAlerts items={[]} isDark={false} onAcknowledge={vi.fn()} onOpen={vi.fn()} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('shows each critical alert with its words, severity in text, and how many are waiting', () => {
    render(<PinnedAlerts items={[item('1'), item('2')]} isDark={false} onAcknowledge={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByText('2 critical alert(s) waiting for acknowledgement')).toBeInTheDocument()
    expect(screen.getByText('down-1')).toBeInTheDocument()
    expect(screen.getByText('why-2')).toBeInTheDocument()
    expect(screen.getAllByText('Critical').length).toBeGreaterThan(0)
  })

  it('acknowledges one alert', async () => {
    const onAcknowledge = vi.fn(async () => true)
    render(<PinnedAlerts items={[item('1')]} isDark={false} onAcknowledge={onAcknowledge} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByText('Acknowledge'))
    await waitFor(() => expect(onAcknowledge).toHaveBeenCalledWith('1'))
  })

  it('tells the person when acknowledging failed', async () => {
    render(<PinnedAlerts items={[item('1')]} isDark={false} onAcknowledge={vi.fn(async () => false)} onOpen={vi.fn()} />)
    fireEvent.click(screen.getByText('Acknowledge'))
    await waitFor(() => expect(screen.getByText('Could not acknowledge. Try again.')).toBeInTheDocument())
  })

  it('opens the incident when the title is clicked', () => {
    const onOpen = vi.fn()
    render(<PinnedAlerts items={[item('1')]} isDark={false} onAcknowledge={vi.fn()} onOpen={onOpen} />)
    fireEvent.click(screen.getByText('down-1'))
    expect(onOpen).toHaveBeenCalledWith(expect.objectContaining({ notification_id: '1' }))
  })

  it('is an alert region so assistive technology announces it', () => {
    render(<PinnedAlerts items={[item('1')]} isDark onAcknowledge={vi.fn()} onOpen={vi.fn()} />)
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })
})
