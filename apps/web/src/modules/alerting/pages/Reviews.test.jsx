import { describe, it, expect } from 'vitest'
import { screen, waitFor, fireEvent } from '@testing-library/react'
import Reviews from './Reviews'
import { mockApi, renderPage, failing } from '../testing'

const review = (id, over = {}) => ({ review_id: id, incident_id: 'i-' + id, severity: 'P0', component: 'redis', resolved_at: '2026-11-15T10:00:00Z', due_at: '2026-11-18T10:00:00Z', overdue: true, status: 'DUE',
  root_cause_category: null, narrative: '', contributing_factors: '', detection_gap: '', impact: '', risk_id: null, submitted_by: null, submitted_at: null, ...over })
const action = (id, over = {}) => ({ action_id: id, review_id: 'r2', kind: 'preventive', description: 'Add a memory alert', owner: 'SRE lead', due_on: '2026-12-01', status: 'OPEN', evidence: '', note: '', done_by: null,
  done_at: null, verified_by: null, verified_at: null, created_by: 'ops-1', overdue: false, effectiveness: 'NA', ...over })
const base = (reviews, actions, extra = {}) => mockApi({ 'GET /v1/ops/alert-reviews/reviews': { reviews }, 'GET /v1/ops/alert-reviews/actions': { actions }, ...extra })
const view = (opts) => renderPage(<Reviews />, { route: '/ops/reviews', path: '/ops/reviews', ...opts })

describe('Reviews', () => {
  it('lists the reviews that are due, says which are overdue, and the actions with their state in words', async () => {
    base([review('r1'), review('r2', { status: 'SUBMITTED', component: 'kafka', root_cause_category: 'capacity', narrative: 'Kafka ran out of disk.' })],
      [action('a1', { overdue: true }), action('a2', { status: 'DONE', effectiveness: 'RECURRED', evidence: 'merged', done_by: 'sre-1' })])
    view()
    await waitFor(() => expect(screen.getAllByText('redis').length).toBeGreaterThan(0))
    expect(screen.getByText('Due for review')).toBeInTheDocument()
    expect(screen.getAllByText(/Overdue/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('Add a memory alert').length).toBe(2)
    expect(screen.getByText(/the same failure came back/i)).toBeInTheDocument()
  })

  it('says plainly when there is nothing to review', async () => {
    base([], [])
    view()
    await waitFor(() => expect(screen.getByText(/No reviews are due/i)).toBeInTheDocument())
  })

  it('submits a review with the root cause and narrative', async () => {
    const calls = base([review('r1')], [], { 'POST /v1/ops/alert-reviews/reviews/r1/submit': review('r1', { status: 'SUBMITTED' }) })
    view()
    await waitFor(() => expect(screen.getByText('Write the review')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Write the review'))
    fireEvent.change(screen.getByLabelText('Root cause'), { target: { value: 'capacity' } })
    fireEvent.change(screen.getByLabelText('What happened'), { target: { value: 'Redis ran out of memory after the warm-up.' } })
    fireEvent.click(screen.getByText('Submit review'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/reviews/r1/submit'))).toBe(true))
    expect(calls.find(c => c.method === 'POST').body).toMatchObject({ category: 'capacity', narrative: 'Redis ran out of memory after the warm-up.' })
  })

  it('shows why a review was refused', async () => {
    base([review('r1')], [], { 'POST /v1/ops/alert-reviews/reviews/r1/submit': failing(422, { detail: 'Write what happened in the narrative, in at least a few sentences.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Write the review')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Write the review'))
    fireEvent.click(screen.getByText('Submit review'))
    await waitFor(() => expect(screen.getByText(/at least a few sentences/i)).toBeInTheDocument())
  })

  it('adds an action to a submitted review', async () => {
    const calls = base([review('r2', { status: 'SUBMITTED' })], [], { 'POST /v1/ops/alert-reviews/reviews/r2/actions': action('n') })
    view()
    await waitFor(() => expect(screen.getByText('Add an action')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Add an action'))
    fireEvent.change(screen.getByLabelText('What will be done'), { target: { value: 'Add a memory alert' } })
    fireEvent.change(screen.getByLabelText('Owner'), { target: { value: 'SRE lead' } })
    fireEvent.change(screen.getByLabelText('Due date'), { target: { value: '2026-12-01' } })
    fireEvent.click(screen.getByText('Save action'))
    await waitFor(() => expect(calls.some(c => c.method === 'POST' && c.url.endsWith('/reviews/r2/actions'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/actions') && c.method === 'POST').body).toMatchObject({ kind: 'preventive', description: 'Add a memory alert', owner: 'SRE lead', due_on: '2026-12-01' })
  })

  it('finishes an action with evidence, verifies another, and shows when the same person tried to verify', async () => {
    const calls = base([], [action('a1'), action('a2', { status: 'DONE', done_by: 'sre-1', evidence: 'merged' })], {
      'POST /v1/ops/alert-reviews/actions/a1/status': action('a1', { status: 'DONE' }),
      'POST /v1/ops/alert-reviews/actions/a2/status': failing(409, { detail: 'A different person must verify the action. The person who finished it cannot.' }) })
    view()
    await waitFor(() => expect(screen.getByText('Mark done')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Mark done'))
    fireEvent.change(screen.getByLabelText('Evidence'), { target: { value: 'Rule merged in PR 123' } })
    fireEvent.click(screen.getByText('Save'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/a1/status'))).toBe(true))
    expect(calls.find(c => c.url.endsWith('/a1/status')).body).toMatchObject({ status: 'DONE', evidence: 'Rule merged in PR 123' })
    fireEvent.click(screen.getByText('Verify'))
    await waitFor(() => expect(screen.getByText(/different person must verify/i)).toBeInTheDocument())
  })

  it('says when it cannot load and works in the dark theme', async () => {
    mockApi({ 'GET /v1/ops/alert-reviews/reviews': failing(503, {}), 'GET /v1/ops/alert-reviews/actions': { actions: [] } })
    const { unmount } = view()
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument())
    unmount()
    base([review('r1')], [])
    view({ isDark: true })
    await waitFor(() => expect(screen.getAllByText('redis').length).toBeGreaterThan(0))
  })
})
