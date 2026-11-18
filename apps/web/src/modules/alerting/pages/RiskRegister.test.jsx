import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import RiskRegister from './RiskRegister'
import { mockApi, renderPage, failing } from '../testing'

const risk = (id, over = {}) => ({ risk_id: id, template_key: 'ONCALL_GAP', category: 'process', title: 'Nobody is on call', description: 'A gap in the rota.', likelihood: 3, impact: 5, rating: 15,
  owner: null, status: 'OPEN', mitigation: '', declared_by: null, verified_by: null, next_review_on: '2027-02-01', updated_by: 'admin-1', updated_at: '2026-11-18T10:00:00Z', ...over })
const data = (risks, summary = {}) => ({ risks, summary: { total: risks.length, without_owner: risks.filter(r => !r.owner).length, review_overdue: 0, verified: 0, ...summary } })
const base = (d, extra = {}) => mockApi({ 'GET /v1/admin/alert-risks': d, ...extra })
const view = (opts) => renderPage(<RiskRegister />, { route: '/admin/alert-risks', path: '/admin/alert-risks', ...opts })

describe('RiskRegister', () => {
  it('shows the summary and each risk with its rating, owner and status in words', async () => {
    base(data([risk('a'), risk('b', { title: 'Email delivery stops', owner: 'Duty manager', status: 'MITIGATED', declared_by: 'ops-1', mitigation: 'Second relay', rating: 12 })]))
    view()
    await waitFor(() => expect(screen.getByText('Nobody is on call')).toBeInTheDocument())
    expect(screen.getByText('Email delivery stops')).toBeInTheDocument()
    expect(screen.getByText(/1 without an owner/i)).toBeInTheDocument()
    expect(screen.getByText('Duty manager')).toBeInTheDocument()
    expect(screen.getByText('Mitigated, waiting for verification')).toBeInTheDocument()
    expect(screen.getByText('Open')).toBeInTheDocument()
    expect(screen.getByText(/rating 15/i)).toBeInTheDocument()
  })

  it('offers to seed the register from the template when it is empty, then reloads', async () => {
    let seeded = false
    const calls = base(data([]), { 'GET /v1/admin/alert-risks': () => (seeded ? data([risk('a')]) : data([])), 'POST /v1/admin/alert-risks/seed': () => { seeded = true; return { added: 10 } } })
    view()
    await waitFor(() => expect(screen.getByText('Seed from the template')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Seed from the template'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/alert-risks/seed'))).toBe(true))
    await waitFor(() => expect(screen.getByText('Nobody is on call')).toBeInTheDocument())
  })

  it('saves an owner and a mitigation for a risk', async () => {
    const calls = base(data([risk('a')]), { 'PATCH /v1/admin/alert-risks/a': risk('a', { owner: 'Duty manager' }) })
    view()
    await waitFor(() => expect(screen.getByText('Edit')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Edit'))
    fireEvent.change(screen.getByLabelText('Owner'), { target: { value: 'Duty manager' } })
    fireEvent.change(screen.getByLabelText('What was done'), { target: { value: 'Second relay added' } })
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(calls.some(c => c.method === 'PATCH' && c.url.endsWith('/alert-risks/a'))).toBe(true))
    expect(calls.find(c => c.method === 'PATCH').body).toMatchObject({ owner: 'Duty manager', mitigation: 'Second relay added', likelihood: 3, impact: 5 })
  })

  it('declares mitigated, verifies and reopens, and says why a step was refused', async () => {
    const calls = base(data([risk('a', { owner: 'X', mitigation: 'done' }), risk('b', { status: 'MITIGATED', declared_by: 'ops-1', owner: 'X', mitigation: 'done' }), risk('c', { status: 'VERIFIED', owner: 'X', verified_by: 'c-1' })]), {
      'POST /v1/admin/alert-risks/a/declare-mitigated': risk('a'), 'POST /v1/admin/alert-risks/b/verify': failing(409, { detail: 'A different person must verify the mitigation. The person who declared it cannot.' }),
      'POST /v1/admin/alert-risks/c/reopen': risk('c') })
    view()
    await waitFor(() => expect(screen.getByText('Declare mitigated')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Declare mitigated'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/a/declare-mitigated'))).toBe(true))
    fireEvent.click(screen.getByText('Verify'))
    await waitFor(() => expect(screen.getByText(/different person must verify/i)).toBeInTheDocument())
    fireEvent.click(screen.getAllByText('Reopen')[1])
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/c/reopen'))).toBe(true))
  })

  it('says when it cannot load and works in the dark theme', async () => {
    mockApi({ 'GET /v1/admin/alert-risks': failing(503, {}) })
    const { unmount } = view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    base(data([risk('a')]))
    view({ isDark: true })
    await waitFor(() => expect(screen.getByText('Nobody is on call')).toBeInTheDocument())
  })
})
