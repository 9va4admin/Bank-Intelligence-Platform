import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent, within } from '@testing-library/react'
import OnCall from './OnCall'
import { mockApi, renderPage, failing } from '../testing'

const rota = { shifts: [{ days: [0, 1, 2, 3, 4], start: '09:30', end: '18:00', users: ['alice', 'bob'], rotation: 'weekly', holidays: 'include' }], fallback: { users: ['manager'] } }
const detail = (over = {}) => ({ name: 'ops', rota, on_call: { users: ['alice'], source: 'shift' }, overrides: [], gaps: [], ...over })
const listing = (...names) => ({ rotas: names.map(n => ({ name: n, version: 2, updated_by: 'mgr', updated_at: new Date().toISOString(), on_call: { users: ['alice'], source: 'shift' } })) })
const open = (extra = {}) => mockApi({ 'GET /v1/ops/oncall/rotas/ops': detail(), 'GET /v1/ops/oncall/rotas': listing('ops', 'dba'), ...extra })
const view = () => renderPage(<OnCall />, { route: '/ops/oncall/ops', path: '/ops/oncall/:name?' })

describe('OnCall', () => {
  it('lists the rotas with who is on call right now', async () => {
    mockApi({ 'GET /v1/ops/oncall/rotas': listing('ops', 'dba') })
    renderPage(<OnCall />, { route: '/ops/oncall', path: '/ops/oncall/:name?' })
    await waitFor(() => expect(screen.getByText('ops')).toBeInTheDocument())
    expect(screen.getByText('dba')).toBeInTheDocument()
    expect(screen.getAllByText(/alice/).length).toBeGreaterThan(0)
  })

  it('shows a rota: who is on call and why, its shifts and the fallback', async () => {
    open()
    view()
    await waitFor(() => expect(screen.getByText('09:30 - 18:00')).toBeInTheDocument())
    expect(screen.getByText('Mon, Tue, Wed, Thu, Fri')).toBeInTheDocument()
    expect(screen.getByText(/alice, bob/)).toBeInTheDocument()
    expect(screen.getByText(/manager/)).toBeInTheDocument()
    expect(screen.getByText('From the shift')).toBeInTheDocument()
  })

  it('says when an override is in charge', async () => {
    open({ 'GET /v1/ops/oncall/rotas/ops': detail({ on_call: { users: ['bob'], source: 'override' } }) })
    view()
    await waitFor(() => expect(screen.getByText('From an override')).toBeInTheDocument())
  })

  it('warns about coverage gaps and says nothing is wrong when there are none', async () => {
    open({ 'GET /v1/ops/oncall/rotas/ops': detail({ gaps: [{ starts_at: '2026-11-21T00:00:00Z', ends_at: '2026-11-23T00:00:00Z' }] }) })
    const { unmount } = view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    expect(screen.getByRole('alert').textContent).toMatch(/nobody is on call/i)
    unmount()
    open()
    view()
    await waitFor(() => expect(screen.getByText('Covered for the whole look-ahead period.')).toBeInTheDocument())
  })

  it('adds an override with the person, the period and the reason', async () => {
    const calls = open({ 'POST /v1/ops/oncall/rotas/ops/overrides': { override_id: 'o1' } })
    view()
    await waitFor(() => expect(screen.getByLabelText('Person')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText('Person'), { target: { value: 'carol' } })
    fireEvent.change(screen.getByLabelText('From'), { target: { value: '2026-11-25T09:00' } })
    fireEvent.change(screen.getByLabelText('Until'), { target: { value: '2026-11-25T18:00' } })
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'covering leave' } })
    fireEvent.click(screen.getByText('Add override'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/rotas/ops/overrides'))).toBe(true))
    const body = calls.find(c => c.method === 'POST').body
    expect(body.user_id).toBe('carol') && expect(body.reason).toBe('covering leave')
    expect(new Date(body.starts_at).toString()).not.toBe('Invalid Date')
  })

  it('removes an override', async () => {
    const calls = open({ 'GET /v1/ops/oncall/rotas/ops': detail({ overrides: [{ override_id: 'o1', user_id: 'carol', starts_at: '2026-11-25T03:30:00Z', ends_at: '2026-11-25T12:30:00Z', reason: 'leave', created_by: 'mgr' }] }),
      'DELETE /v1/ops/oncall/rotas/ops/overrides/o1': { removed: true } })
    view()
    await waitFor(() => expect(screen.getByText('carol')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Remove'))
    await waitFor(() => expect(calls.some(c => c.method === 'DELETE' && c.url.endsWith('/overrides/o1'))).toBe(true))
  })

  it('edits and saves the rota: days, hours, people, rotation, holidays, fallback', async () => {
    const calls = open({ 'PUT /v1/ops/oncall/rotas/ops': { name: 'ops', version: 3 } })
    view()
    await waitFor(() => expect(screen.getByText('Edit rota')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Edit rota'))
    fireEvent.change(screen.getByLabelText('People (comma separated)'), { target: { value: 'alice, bob, dora' } })
    fireEvent.change(screen.getByLabelText('Rotation'), { target: { value: 'daily' } })
    fireEvent.click(screen.getByLabelText('Sat'))
    fireEvent.change(screen.getByLabelText('Fallback people (comma separated)'), { target: { value: 'manager, head' } })
    fireEvent.click(screen.getByText('Save rota'))
    await waitFor(() => expect(calls.some(c => c.method === 'PUT')).toBe(true))
    const sent = calls.find(c => c.method === 'PUT').body.rota
    expect(sent.shifts[0].users).toEqual(['alice', 'bob', 'dora']) && expect(sent.shifts[0].rotation).toBe('daily')
    expect(sent.shifts[0].days).toEqual([0, 1, 2, 3, 4, 5]) && expect(sent.fallback.users).toEqual(['manager', 'head'])
  })

  it('explains in words why a rota was refused', async () => {
    open({ 'PUT /v1/ops/oncall/rotas/ops': failing(422, { detail: { message: 'x', codes: ['bad_time', 'shift_needs_people'] } }) })
    view()
    await waitFor(() => expect(screen.getByText('Edit rota')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Edit rota'))
    fireEvent.click(screen.getByText('Save rota'))
    await waitFor(() => expect(screen.getByText('A shift needs a valid start and end time.')).toBeInTheDocument())
    expect(screen.getByText('Every shift needs at least one person.')).toBeInTheDocument()
  })

  it('says when it cannot load and when there are no rotas', async () => {
    mockApi({ 'GET /v1/ops/oncall/rotas': failing(503, {}) })
    const { unmount } = renderPage(<OnCall />, { route: '/ops/oncall', path: '/ops/oncall/:name?' })
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    mockApi({ 'GET /v1/ops/oncall/rotas': listing() })
    renderPage(<OnCall />, { route: '/ops/oncall', path: '/ops/oncall/:name?' })
    await waitFor(() => expect(screen.getByText('No on-call rotas yet.')).toBeInTheDocument())
  })

  it('works in the dark theme', async () => {
    open()
    renderPage(<OnCall />, { route: '/ops/oncall/ops', path: '/ops/oncall/:name?', isDark: true })
    await waitFor(() => expect(screen.getByText('09:30 - 18:00')).toBeInTheDocument())
  })
})
