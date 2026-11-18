import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import Contacts from './Contacts'
import { mockApi, renderPage, failing } from '../testing'

const contact = (id, over = {}) => ({ contact_id: id, kind: 'email', address_masked: 'd***@bank.example', label: 'Duty officer', status: 'UNVERIFIED', code_pending: true,
  verified_at: null, verified_by: null, created_by: 'admin-1', created_at: '2026-11-18T10:00:00Z', ...over })
const base = (list, extra = {}) => mockApi({ 'GET /v1/admin/alert-contacts': { contacts: list }, ...extra })
const view = (opts) => renderPage(<Contacts />, { route: '/admin/alert-contacts', path: '/admin/alert-contacts', ...opts })

describe('Contacts', () => {
  it('lists contacts masked, with the kind, label and whether each is verified, in words', async () => {
    base([contact('a'), contact('b', { kind: 'phone', address_masked: '+91*****0001', label: '', status: 'VERIFIED', verified_by: 'admin-2', verified_at: '2026-11-18T11:00:00Z', code_pending: false })])
    view()
    await waitFor(() => expect(screen.getByText('d***@bank.example')).toBeInTheDocument())
    expect(screen.getByText('+91*****0001')).toBeInTheDocument()
    expect(screen.getByText('Duty officer')).toBeInTheDocument()
    expect(screen.getAllByText('Not verified').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Verified').length).toBeGreaterThan(0)
  })

  it('says plainly when there are no contacts yet', async () => {
    base([])
    view()
    await waitFor(() => expect(screen.getByText(/No contacts yet/i)).toBeInTheDocument())
  })

  it('adds a contact and says a code was sent to it', async () => {
    const calls = base([], { 'POST /v1/admin/alert-contacts': { contact: contact('n'), sent: true } })
    view()
    await waitFor(() => expect(screen.getByText('Add contact')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Address'), { target: { value: 'duty@bank.example' } })
    fireEvent.change(screen.getByLabelText('Label'), { target: { value: 'Duty officer' } })
    fireEvent.click(screen.getByText('Add contact'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/v1/admin/alert-contacts'))).toBe(true))
    expect(calls.find(c => c.method === 'POST').body).toEqual({ kind: 'email', address: 'duty@bank.example', label: 'Duty officer' })
    await waitFor(() => expect(screen.getByText(/code was sent/i)).toBeInTheDocument())
  })

  it('says when the contact was added but the code could not be sent, and why an address was refused', async () => {
    base([], { 'POST /v1/admin/alert-contacts': { contact: contact('n'), sent: false } })
    view()
    await waitFor(() => expect(screen.getByText('Add contact')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Address'), { target: { value: 'a@bank.example' } })
    fireEvent.click(screen.getByText('Add contact'))
    await waitFor(() => expect(screen.getByText(/could not be sent/i)).toBeInTheDocument())
  })

  it('shows the reason an address was refused', async () => {
    base([], { 'POST /v1/admin/alert-contacts': failing(422, { detail: 'That is not a valid email address.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Add contact')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Address'), { target: { value: 'nope' } })
    fireEvent.click(screen.getByText('Add contact'))
    await waitFor(() => expect(screen.getByText(/not a valid email/i)).toBeInTheDocument())
  })

  it('verifies a contact with the code, and says in words when the code is wrong', async () => {
    let answer = { ok: false, reason: 'wrong_code' }
    const calls = base([contact('a')], { 'POST /v1/admin/alert-contacts/a/verify': () => answer })
    view()
    await waitFor(() => expect(screen.getByText('Enter code')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Enter code'))
    fireEvent.change(screen.getByLabelText('Code'), { target: { value: '123456' } })
    fireEvent.click(screen.getByText('Verify'))
    await waitFor(() => expect(screen.getByText(/code is not right/i)).toBeInTheDocument())
    expect(calls.find(c => c.url.endsWith('/a/verify')).body).toEqual({ code: '123456' })
    answer = { ok: true, reason: 'ok' }
    fireEvent.click(screen.getByText('Verify'))
    await waitFor(() => expect(screen.getByText(/is now verified/i)).toBeInTheDocument())
  })

  it('sends a new code and removes a contact', async () => {
    const calls = base([contact('a')], { 'POST /v1/admin/alert-contacts/a/send-code': { sent: true }, 'DELETE /v1/admin/alert-contacts/a': {} })
    view()
    await waitFor(() => expect(screen.getByText('Send a new code')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Send a new code'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/a/send-code'))).toBe(true))
    fireEvent.click(screen.getByText('Remove'))
    await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/v1/admin/alert-contacts/a'))).toBe(true))
  })

  it('says when it cannot load and works in the dark theme', async () => {
    mockApi({ 'GET /v1/admin/alert-contacts': failing(503, {}) })
    const { unmount } = view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    base([contact('a')])
    view({ isDark: true })
    await waitFor(() => expect(screen.getByText('d***@bank.example')).toBeInTheDocument())
  })
})
