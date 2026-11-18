import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import AlertSettings from './AlertSettings'
import { mockApi, renderPage, failing } from '../testing'

const channels = (over = {}) => ({ email: { configured: true, host: 'smtp.gmail.com', port: 587, security: 'starttls', from_address: 'admin@9va.in', public_provider: true }, whatsapp: { configured: false }, bell: { configured: true },
  email_recipients: 2, whatsapp_recipients: 0, ...over })
const entry = (key, value, over = {}) => ({ config_key: key, current_value: value, layer: 'LAYER_3', description: `about ${key}`, last_changed_at: null, last_changed_by: null, ...over })
const thresholds = () => ({ thresholds: [entry('stp_mode', 'SUPERVISED'), entry('alerts.email_recipients', 'ops@bank.example'), entry('alerting.retention_days', '730')], total: 3, bank_id: 'kbl' })
const change = (id, key, over = {}) => ({ change_id: id, config_key: key, new_value: '365', reason: 'shorter retention', status: 'PENDING_APPROVAL', submitted_by: 'maker', submitted_at: '2026-11-18T10:00:00Z', ...over })

const base = (extra = {}) => mockApi({ 'GET /v1/platform/alert-proofs': {}, 'GET /v1/admin/alert-routing/channels': channels(), 'GET /v1/admin/config/thresholds/changes': { changes: [], total: 0, bank_id: 'kbl' },
  'GET /v1/admin/config/thresholds': thresholds(), ...extra })
const view = (opts) => renderPage(<AlertSettings />, { route: '/admin/alert-settings', path: '/admin/alert-settings', ...opts })

describe('AlertSettings', () => {
  it('shows what can carry an alert: email with its server, WhatsApp, the bell, and how many recipients', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getByText(/smtp\.gmail\.com/)).toBeInTheDocument())
    expect(screen.getByText(/starttls/)).toBeInTheDocument()
    expect(screen.getByText('Not configured')).toBeInTheDocument()                    // WhatsApp
    expect(screen.getByText(/2 recipients/)).toBeInTheDocument()
  })

  it('warns that a public mail provider is a pilot-only arrangement', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getByText(/public mail provider/i)).toBeInTheDocument())
  })

  it('says when email is not set up and what to do', async () => {
    base({ 'GET /v1/admin/alert-routing/channels': channels({ email: { configured: false, public_provider: false }, email_recipients: 0 }) })
    view()
    await waitFor(() => expect(screen.getByText(/Email is not set up/i)).toBeInTheDocument())
    expect(screen.queryByText(/public mail provider/i)).toBeNull()
  })

  it('lists only the alert settings, with their description and current value', async () => {
    base()
    view()
    await waitFor(() => expect(screen.getByText('alerts.email_recipients')).toBeInTheDocument())
    expect(screen.getByText('about alerts.email_recipients')).toBeInTheDocument()
    expect(screen.getByText('730')).toBeInTheDocument()
    expect(screen.queryByText('stp_mode')).toBeNull()
  })

  it('submits a change for approval with a reason', async () => {
    const calls = base({ 'POST /v1/admin/config/thresholds': { change_id: 'c1', config_key: 'alerting.retention_days', new_value: '365', status: 'PENDING_APPROVAL', submitted_by: 'u', submitted_at: 'now' } })
    view()
    await waitFor(() => expect(screen.getByText('alerting.retention_days')).toBeInTheDocument())
    fireEvent.click(screen.getAllByText('Change')[1])
    fireEvent.change(screen.getByLabelText('New value'), { target: { value: '365' } })
    fireEvent.change(screen.getByLabelText('Reason (at least 10 characters)'), { target: { value: 'shorter retention for the pilot' } })
    fireEvent.click(screen.getByText('Submit for approval'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/config/thresholds'))).toBe(true))
    expect(calls.find(c => c.method === 'POST').body).toEqual({ config_key: 'alerting.retention_days', new_value: '365', reason: 'shorter retention for the pilot' })
    await waitFor(() => expect(screen.getByText(/submitted for approval/i)).toBeInTheDocument())
  })

  it('does not send a change without a proper reason', async () => {
    const calls = base()
    view()
    await waitFor(() => expect(screen.getByText('alerting.retention_days')).toBeInTheDocument())
    fireEvent.click(screen.getAllByText('Change')[1])
    fireEvent.change(screen.getByLabelText('New value'), { target: { value: '365' } })
    fireEvent.change(screen.getByLabelText('Reason (at least 10 characters)'), { target: { value: 'short' } })
    fireEvent.click(screen.getByText('Submit for approval'))
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(calls.some(c => c.method === 'POST')).toBe(false)
  })

  it('lists changes waiting for approval and approves or rejects them', async () => {
    const calls = base({ 'GET /v1/admin/config/thresholds/changes': { changes: [change('c1', 'alerting.retention_days'), change('c2', 'stp_mode'), change('c3', 'alerts.email_recipients', { status: 'APPROVED' })], total: 3, bank_id: 'kbl' },
      'POST /v1/admin/config/thresholds/c1/approve': { change_id: 'c1', status: 'APPROVED', actioned_by: 'u', actioned_at: 'now' },
      'POST /v1/admin/config/thresholds/c1/reject': { change_id: 'c1', status: 'REJECTED', actioned_by: 'u', actioned_at: 'now' } })
    view()
    await waitFor(() => expect(screen.getByText(/shorter retention/)).toBeInTheDocument())
    expect(screen.getAllByText('Approve')).toHaveLength(1)                              // only the alert setting that is waiting
    fireEvent.click(screen.getByText('Approve'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/c1/approve'))).toBe(true))
    fireEvent.click(screen.getByText('Reject'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/c1/reject'))).toBe(true))
  })

  it('tells the person when approving was refused', async () => {
    base({ 'GET /v1/admin/config/thresholds/changes': { changes: [change('c1', 'alerting.retention_days')], total: 1, bank_id: 'kbl' },
      'POST /v1/admin/config/thresholds/c1/approve': failing(403, { detail: 'You cannot approve your own change.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Approve')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Approve'))
    await waitFor(() => expect(screen.getByText(/cannot approve your own change/)).toBeInTheDocument())
  })

  it('says when it cannot load', async () => {
    mockApi({ 'GET /v1/admin/alert-routing/channels': failing(503, {}), 'GET /v1/admin/config/thresholds': failing(503, {}) })
    view()
    await waitFor(() => expect(screen.getAllByRole('alert').length).toBeGreaterThan(0))
  })

  it('works in the dark theme', async () => {
    base()
    view({ isDark: true })
    await waitFor(() => expect(screen.getByText('alerts.email_recipients')).toBeInTheDocument())
  })

  it('says the audit trail was never proved, then runs the proof and shows the result in words', async () => {
    let ran = false
    const calls = base({ 'GET /v1/platform/alert-proofs': () => (ran ? { audit_path: { ok: true, ran_by: 'admin-1', ran_at: '2026-11-18T10:00:00Z', reason: 'ok' } } : {}),
      'POST /v1/platform/alert-proofs/audit-path': () => { ran = true; return { ok: true, reason: 'ok' } } })
    view()
    await waitFor(() => expect(screen.getByText(/never been run/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Run the audit proof'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/v1/platform/alert-proofs/audit-path'))).toBe(true))
    await waitFor(() => expect(screen.getAllByText(/Passed on/).length).toBeGreaterThan(0))
    expect(screen.getByText(/admin-1/)).toBeInTheDocument()
  })

  it('shows a failed proof with the reason in words, and a refusal when the person may not run it', async () => {
    base({ 'GET /v1/platform/alert-proofs': { audit_path: { ok: false, ran_by: 'admin-1', ran_at: '2026-11-18T10:00:00Z', reason: 'verify_failed' } },
      'POST /v1/platform/alert-proofs/audit-path': failing(403, { detail: 'Your role cannot do this.' }) })
    view()
    await waitFor(() => expect(screen.getByText(/did not verify/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Run the audit proof'))
    await waitFor(() => expect(screen.getByText(/cannot do this/)).toBeInTheDocument())
  })

  it('runs the mail domain check and shows what it found, or that no sending address exists yet', async () => {
    let ran = false
    const calls = base({ 'GET /v1/platform/alert-proofs': () => (ran ? { mail_dns: { ok: false, ran_by: 'admin-1', ran_at: '2026-11-18T10:00:00Z', reason: 'missing_records' } } : {}),
      'POST /v1/platform/alert-proofs/mail-dns': () => { ran = true; return { ok: false, reason: 'missing_records' } } })
    view()
    await waitFor(() => expect(screen.getByText(/mail domain has never been checked/i)).toBeInTheDocument())
    fireEvent.click(screen.getByText('Check the mail domain'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/v1/platform/alert-proofs/mail-dns'))).toBe(true))
    await waitFor(() => expect(screen.getByText(/records are missing/i)).toBeInTheDocument())
  })

  it('tells the person when the mail domain check cannot run', async () => {
    base({ 'POST /v1/platform/alert-proofs/mail-dns': failing(409, { detail: 'There is no sending address yet. Set up email first.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Check the mail domain')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Check the mail domain'))
    await waitFor(() => expect(screen.getByText(/no sending address yet/i)).toBeInTheDocument())
  })
})
