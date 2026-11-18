import { describe, it, expect, beforeEach } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import Incidents from './Incidents'
import { mockApi, renderPage, failing } from '../testing'

const inc = (id, over = {}) => ({ incident_id: id, alert_id: 'COMPONENT_DOWN', component: 'redis', severity: 'P0', state: 'OPEN', scope_level: 'BANK', summary: `summary-${id}`,
  opened_at: new Date(Date.now() - 10 * 60000).toISOString(), acked_at: null, acked_by: null, resolved_at: null, notification_count: 3, ...over })
const detail = (id, over = {}) => ({ incident: { ...inc(id), category: '', impact: 'Cheque decisions slow down.', escalation_level: 1, ...over },
  deliveries: [{ delivery_id: 'd1', escalation_level: 0, channel: 'email', recipient_ref: 'o***@bank.example', status: 'SENT', attempt: 1, created_at: new Date().toISOString(), completed_at: new Date().toISOString() },
               { delivery_id: 'd2', escalation_level: 1, channel: 'bell', recipient_ref: 'usr-ops', status: 'FAILED', attempt: 2, error: 'x', provider_class: 'network', created_at: new Date().toISOString() }] })

let calls
beforeEach(() => { calls = null })

const list = (...items) => ({ incidents: items, next_cursor: null })

describe('Incidents', () => {
  it('lists incidents with severity and state in words', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents?': list(inc('a'), inc('b', { severity: 'P2', state: 'RESOLVED', component: 'kafka' })) })
    renderPage(<Incidents />, { route: '/ops/incidents', path: '/ops/incidents' })
    await waitFor(() => expect(screen.getByText('summary-a')).toBeInTheDocument())
    expect(screen.getByText('summary-b')).toBeInTheDocument()
    expect(screen.getAllByText('Critical').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Open').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Resolved').length).toBeGreaterThan(0)
  })

  it('filters by state and severity through the server', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents?': list(inc('a')) })
    renderPage(<Incidents />, { route: '/ops/incidents', path: '/ops/incidents' })
    await waitFor(() => expect(screen.getByText('summary-a')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('State'), { target: { value: 'OPEN' } })
    fireEvent.change(screen.getByLabelText('Severity'), { target: { value: 'P0' } })
    await waitFor(() => expect(calls.some(c => c.url.includes('state=OPEN') && c.url.includes('severity=P0'))).toBe(true))
  })

  it('opens an incident to show its timeline: what was sent, to whom, and how it went', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents/a': detail('a'), 'GET /v1/ops/alerts/incidents?': list(inc('a')) })
    renderPage(<Incidents />, { route: '/ops/incidents/a', path: '/ops/incidents/:incidentId' })
    await waitFor(() => expect(screen.getByText('Cheque decisions slow down.')).toBeInTheDocument())
    expect(screen.getByText(/o\*\*\*@bank\.example/)).toBeInTheDocument()                 // masked, never the address
    expect(screen.getByText('Sent')).toBeInTheDocument()
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText(/Escalation level 1/)).toBeInTheDocument()
  })

  it('acknowledges an open incident and refreshes it', async () => {
    let acked = false
    calls = mockApi({
      'POST /v1/ops/alerts/incidents/a/acknowledge': () => { acked = true; return { incident_id: 'a', state: 'ACKED', acknowledged_by: 'u' } },
      'GET /v1/ops/alerts/incidents/a': () => detail('a', acked ? { state: 'ACKED', acked_by: 'user-7', acked_at: new Date().toISOString() } : {}),
      'GET /v1/ops/alerts/incidents?': list(inc('a')),
    })
    renderPage(<Incidents />, { route: '/ops/incidents/a', path: '/ops/incidents/:incidentId' })
    await waitFor(() => expect(screen.getByText('Acknowledge')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Acknowledge'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/incidents/a/acknowledge'))).toBe(true))
    await waitFor(() => expect(screen.getByText(/user-7/)).toBeInTheDocument())
    expect(screen.queryByText('Acknowledge')).toBeNull()
  })

  it('does not offer acknowledge for an incident that is already closed', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents/b': detail('b', { state: 'RESOLVED', resolved_at: new Date().toISOString() }), 'GET /v1/ops/alerts/incidents?': list(inc('b', { state: 'RESOLVED' })) })
    renderPage(<Incidents />, { route: '/ops/incidents/b', path: '/ops/incidents/:incidentId' })
    await waitFor(() => expect(screen.getByText('Cheque decisions slow down.')).toBeInTheDocument())
    expect(screen.queryByText('Acknowledge')).toBeNull()
  })

  it('tells the person when acknowledging was refused', async () => {
    calls = mockApi({
      'POST /v1/ops/alerts/incidents/a/acknowledge': failing(403, { detail: 'Your role cannot acknowledge alerts.' }),
      'GET /v1/ops/alerts/incidents/a': detail('a'), 'GET /v1/ops/alerts/incidents?': list(inc('a')),
    })
    renderPage(<Incidents />, { route: '/ops/incidents/a', path: '/ops/incidents/:incidentId' })
    await waitFor(() => expect(screen.getByText('Acknowledge')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Acknowledge'))
    await waitFor(() => expect(screen.getByText(/Your role cannot acknowledge alerts/)).toBeInTheDocument())
  })

  it('says so when it cannot load, instead of showing an empty list', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents?': failing(503, { detail: 'down' }) })
    renderPage(<Incidents />, { route: '/ops/incidents', path: '/ops/incidents' })
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toMatch(/could not be loaded/i)
  })

  it('says so when there is nothing to show', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents?': list() })
    renderPage(<Incidents />, { route: '/ops/incidents', path: '/ops/incidents' })
    await waitFor(() => expect(screen.getByText('No incidents match.')).toBeInTheDocument())
  })

  it('works in the dark theme', async () => {
    calls = mockApi({ 'GET /v1/ops/alerts/incidents?': list(inc('a')) })
    renderPage(<Incidents />, { route: '/ops/incidents', path: '/ops/incidents', isDark: true })
    await waitFor(() => expect(screen.getByText('summary-a')).toBeInTheDocument())
  })
})
