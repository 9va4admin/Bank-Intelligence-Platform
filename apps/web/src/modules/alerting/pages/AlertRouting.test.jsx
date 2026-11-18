import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import AlertRouting from './AlertRouting'
import { mockApi, renderPage, failing } from '../testing'

const T = (kind, ref, ...channels) => ({ kind, ref, channels })
const policy = (over = {}) => ({ scope_id: null, rules: [
  { id: 'p0', severities: ['P0'], components: [], teams: [], hours: 'always', targets: [T('external', 'ops@bank.example', 'email'), T('role', 'ops_manager', 'bell')],
    escalation: [{ level: 1, after_minutes: 10, targets: [T('role', 'bank_it_admin', 'email', 'bell')] }], repeat_minutes: 30, quiet_hold: false },
  { id: 'rest', severities: [], components: [], teams: [], hours: 'always', targets: [T('role', 'ops_manager', 'bell')], escalation: [], repeat_minutes: null, quiet_hold: false }], ...over })
const record = (over = {}) => ({ policy_id: 'p-1', bank_id: 'kbl', scope_level: 'BANK', scope_id: null, version: 3, status: 'ACTIVE', rule_ids: ['p0', 'rest'], note: null, created_by: 'maker', created_at: '2026-11-18T10:00:00Z', approved_by: 'checker', approved_at: '2026-11-18T11:00:00Z', ...over })
const active = (over = {}) => ({ active: { policy: policy(), record: record() }, pending: [], history: [record(), record({ policy_id: 'p-0', version: 2, status: 'SUPERSEDED' })], used_default: false, default_policy: null, ...over })

const base = (extra = {}) => mockApi({ 'GET /v1/admin/alert-routing/policies?': active(), 'GET /v1/admin/alert-routing/pending': { pending: [] }, 'GET /v1/admin/alert-routing/scopes': { scopes: [] }, ...extra })
const view = (opts) => renderPage(<AlertRouting />, { route: '/admin/alert-routing', path: '/admin/alert-routing', ...opts })

describe('AlertRouting', () => {
  it('shows the policy in force: version, who approved it, and every rule in words', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getAllByText(/Version 3/).length).toBeGreaterThan(0))
    expect(screen.getByText(/approved by checker/i)).toBeInTheDocument()
    expect(screen.getByText('p0')).toBeInTheDocument()
    expect(screen.getAllByText(/ops_manager/).length).toBeGreaterThan(0)
    expect(screen.getByText(/After 10 min/)).toBeInTheDocument()
    expect(screen.getAllByText(/o\*\*\*@bank\.example|ops@bank\.example/).length).toBeGreaterThan(0)
  })

  it('says plainly when the bank has no policy of its own and shows the default that is in force', async () => {
    base({ 'GET /v1/admin/alert-routing/policies?': { active: null, pending: [], history: [], used_default: true, default_policy: policy({ rules: [{ id: 'default-p0', severities: ['P0'], components: [], teams: [], hours: 'always', targets: [T('role', 'ops_manager', 'bell')], escalation: [], repeat_minutes: null, quiet_hold: false }] }) } })
    view()
    await waitFor(() => expect(screen.getByText(/no routing policy of its own/i)).toBeInTheDocument())
    expect(screen.getByText('default-p0')).toBeInTheDocument()
  })

  it('switches scope to a PU and asks for that PU s policy', async () => {
    const calls = base()
    view()
    await waitFor(() => expect(screen.getAllByText(/Version 3/).length).toBeGreaterThan(0))
    fireEvent.click(screen.getByRole('tab', { name: 'Processing unit' }))
    fireEvent.change(screen.getByLabelText('Processing unit ID'), { target: { value: 'PU1' } })
    fireEvent.click(screen.getByText('Load'))
    await waitFor(() => expect(calls.some(c => c.url.includes('level=PU') && c.url.includes('scope_id=PU1'))).toBe(true))
  })

  it('proposes a change from the current policy: edits a rule and sends it with a note', async () => {
    const calls = base({ 'POST /v1/admin/alert-routing/policies': record({ status: 'PENDING', version: 4, policy_id: 'p-4' }) })
    view()
    await waitFor(() => expect(screen.getByText('Propose a change')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Propose a change'))
    const repeat = screen.getAllByLabelText('Repeat every (minutes)')[0]
    fireEvent.change(repeat, { target: { value: '15' } })
    fireEvent.change(screen.getByLabelText('Note for the approver'), { target: { value: 'faster reminders' } })
    fireEvent.click(screen.getByText('Submit proposal'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/policies'))).toBe(true))
    const body = calls.find(c => c.method === 'POST' && c.url.endsWith('/policies')).body
    expect(body.level).toBe('BANK') && expect(body.note).toBe('faster reminders')
    expect(body.policy.rules[0].repeat_minutes).toBe(15) && expect(body.policy.rules[0].targets[0].ref).toBe('ops@bank.example')
    await waitFor(() => expect(screen.getByText(/proposal was submitted/i)).toBeInTheDocument())
  })

  it('explains in words why a policy was refused', async () => {
    base({ 'POST /v1/admin/alert-routing/policies': failing(422, { detail: { message: 'x', codes: ['p0_not_covered', 'p0_needs_two_channels'] } }) })
    view()
    await waitFor(() => expect(screen.getByText('Propose a change')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Propose a change'))
    fireEvent.click(screen.getByText('Submit proposal'))
    await waitFor(() => expect(screen.getByText('No rule covers critical (P0) alerts.')).toBeInTheDocument())
    expect(screen.getByText('A critical (P0) rule must reach people on at least two channels.')).toBeInTheDocument()
  })

  it('lets an approver read a pending proposal before deciding, then approve it', async () => {
    const pending = record({ policy_id: 'p-9', status: 'PENDING', version: 5, created_by: 'maker', approved_by: null, approved_at: null })
    const calls = base({
      'GET /v1/admin/alert-routing/pending': { pending: [pending] },
      'GET /v1/admin/alert-routing/policies/p-9': { record: pending, policy: policy() },
      'POST /v1/admin/alert-routing/policies/p-9/approve': record({ policy_id: 'p-9', version: 5 }),
    })
    view()
    await waitFor(() => expect(screen.getByText(/version 5, proposed by maker/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Read'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/policies/p-9') && c.method === 'GET')).toBe(true))
    await waitFor(() => expect(screen.getAllByText('p0').length).toBeGreaterThan(1))
    fireEvent.click(screen.getByText('Approve'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/policies/p-9/approve'))).toBe(true))
  })

  it('rejects a proposal and tells the person when approving was refused', async () => {
    const pending = record({ policy_id: 'p-9', status: 'PENDING', version: 5, approved_by: null })
    const calls = base({ 'GET /v1/admin/alert-routing/pending': { pending: [pending] },
      'POST /v1/admin/alert-routing/policies/p-9/approve': failing(403, { detail: 'The person who proposed a change cannot approve it. Another person must.' }),
      'POST /v1/admin/alert-routing/policies/p-9/reject': record({ status: 'REJECTED' }) })
    view()
    await waitFor(() => expect(screen.getByText('Approve')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Approve'))
    await waitFor(() => expect(screen.getByText(/cannot approve it/)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Reject'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/p-9/reject'))).toBe(true))
  })

  it('shows the history of versions', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getByText('History')).toBeInTheDocument())
    expect(screen.getByText('Superseded')).toBeInTheDocument()
  })

  it('simulates who would be told for an incident, with masked addresses and the escalation steps', async () => {
    const calls = base({ 'POST /v1/admin/alert-routing/simulate': {
      matched: [{ level: 'BANK', rule_id: 'p0' }], repeat_minutes: 30, held: false, warnings: ['oncall_unfilled:ops'], used_default: false,
      steps: [{ level: 0, after_minutes: 0, targets: [{ kind: 'external', ref: 'o***@bank.example', channels: ['email'] }], deliveries: [{ channel: 'email', recipient_ref: 'o***@bank.example' }, { channel: 'bell', recipient_ref: 'usr-ops' }] },
              { level: 1, after_minutes: 10, targets: [{ kind: 'role', ref: 'bank_it_admin', channels: ['email'] }], deliveries: [] }] } })
    view()
    await waitFor(() => expect(screen.getByText('Who would be told?')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Severity'), { target: { value: 'P0' } })
    fireEvent.change(screen.getByLabelText('Component'), { target: { value: 'redis' } })
    fireEvent.click(screen.getByText('Simulate'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/simulate'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/simulate')).body).toMatchObject({ severity: 'P0', component: 'redis' })
    await waitFor(() => expect(screen.getByText('usr-ops')).toBeInTheDocument())
    expect(screen.getByText(/Rule p0/)).toBeInTheDocument()
    expect(screen.getByText(/Nobody is on call for the rota "ops"/)).toBeInTheDocument()
  })

  it('says when it cannot load', async () => {
    mockApi({ 'GET /v1/admin/alert-routing/policies?': failing(503, {}), 'GET /v1/admin/alert-routing/pending': { pending: [] }, 'GET /v1/admin/alert-routing/scopes': { scopes: [] } })
    view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
  })

  it('works in the dark theme', async () => {
    base()
    view({ isDark: true })
    await waitFor(() => expect(screen.getAllByText(/Version 3/).length).toBeGreaterThan(0))
  })
})
