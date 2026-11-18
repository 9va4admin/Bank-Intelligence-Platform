import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import Silences from './Silences'
import { mockApi, renderPage, failing } from '../testing'

const silence = (id, over = {}) => ({ silence_id: id, component: 'redis', priorities: ['P1', 'P2'], starts_at: '2026-11-18T10:00:00Z', ends_at: '2026-11-18T12:00:00Z', reason: 'Redis maintenance',
  created_by: 'ops-1', created_at: '2026-11-18T09:00:00Z', cancelled_at: null, cancelled_by: null, ...over })
const listing = (over = {}) => ({ in_force: [silence('a')], upcoming: [silence('b', { component: 'kafka', reason: 'Kafka upgrade' })], recent: [silence('c', { component: 'cbs', reason: 'Old work', cancelled_at: '2026-11-18T09:30:00Z' })], ...over })
const base = (data = listing(), extra = {}) => mockApi({ 'GET /v1/admin/alert-silences': data, ...extra })
const view = (opts) => renderPage(<Silences />, { route: '/ops/silences', path: '/ops/silences', ...opts })

describe('Silences', () => {
  it('shows what is in force, what is coming and what ended, with the reason and who made it', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getByText('Redis maintenance')).toBeInTheDocument())
    expect(screen.getByText('Kafka upgrade')).toBeInTheDocument()
    expect(screen.getByText('Old work')).toBeInTheDocument()
    expect(screen.getByText('In force now')).toBeInTheDocument()
    expect(screen.getByText('Coming up')).toBeInTheDocument()
    expect(screen.getByText('Recently ended')).toBeInTheDocument()
    expect(screen.getAllByText(/ops-1/).length).toBeGreaterThan(0)
  })

  it('says plainly when nothing is silenced', async () => {
    base({ in_force: [], upcoming: [], recent: [] })
    view()
    await waitFor(() => expect(screen.getByText(/Nothing is silenced/i)).toBeInTheDocument())
  })

  it('creates a silence for a component with chosen priorities, an end time and a reason', async () => {
    const calls = base(listing(), { 'POST /v1/admin/alert-silences': silence('n') })
    view()
    await waitFor(() => expect(screen.getByText('Create silence')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Component (empty = all)'), { target: { value: 'redis' } })
    fireEvent.click(screen.getByLabelText('Info (P3)'))
    fireEvent.change(screen.getByLabelText('For how many hours'), { target: { value: '3' } })
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'Redis maintenance window' } })
    fireEvent.click(screen.getByText('Create silence'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/v1/admin/alert-silences'))).toBe(true))
    const sent = calls.find(c => c.method === 'POST').body
    expect(sent.component).toBe('redis')
    expect(sent.priorities).toEqual(expect.arrayContaining(['P1', 'P2', 'P3']))
    expect(sent.reason).toBe('Redis maintenance window')
    expect(new Date(sent.ends_at) - new Date()).toBeGreaterThan(2.9 * 3600 * 1000)
    await waitFor(() => expect(screen.getByText(/silence was created/i)).toBeInTheDocument())
  })

  it('shows why a silence was refused', async () => {
    base(listing(), { 'POST /v1/admin/alert-silences': failing(422, { detail: 'Critical alerts cannot be silenced at this bank.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Create silence')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Create silence'))
    await waitFor(() => expect(screen.getByText(/cannot be silenced/i)).toBeInTheDocument())
  })

  it('cancels a silence that is in force or coming up', async () => {
    const calls = base(listing(), { 'DELETE /v1/admin/alert-silences/a': {} })
    view()
    await waitFor(() => expect(screen.getAllByText('Cancel silence').length).toBe(2))
    fireEvent.click(screen.getAllByText('Cancel silence')[0])
    await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/alert-silences/a'))).toBe(true))
  })

  it('says when it cannot load and works in the dark theme', async () => {
    mockApi({ 'GET /v1/admin/alert-silences': failing(503, {}) })
    const { unmount } = view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    base()
    view({ isDark: true })
    await waitFor(() => expect(screen.getByText('Redis maintenance')).toBeInTheDocument())
  })
})
